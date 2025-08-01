from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden, Http404
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone
from decimal import Decimal
from django.contrib import messages
from django.core.exceptions import ValidationError, PermissionDenied
from django.db.models import Prefetch
from django.conf import settings
from django.views.decorators.http import require_POST
from django.db import transaction
from django.db.models import Sum, Subquery

from orders.models import Order, OrderItem
from stores.models import Store
from .models import Return, ReturnItem, ReturnImage, ReturnStatusHistory
from .services.returns import validate_return_request  # keep only once
# Maybe use them later, import but don’t duplicate:
# from .services.returns import mark_status, compute_refund, adjust_stock_after_receive, process_refund


def return_policy(request):
    """
    Public Returns & Exchanges Policy page.
    """
    # You can keep policy values in settings for easy changes
    policy = {
        "return_window_days": getattr(settings, "RETURN_WINDOW_DAYS", 30),
        "eligible_statuses": ["delivered"],
        "methods": [
            ("easymarket_pickup", "EasyMarket Pickup"),
            ("buyer_dropoff", "Buyer Drop-off"),
            ("courier_service", "Courier Service"),
        ],
        "reasons": [
            ("defective", "Product Defective"),
            ("wrong_item", "Wrong Item Received"),
            ("wrong_size", "Wrong Size"),
            ("damaged_shipping", "Damaged During Shipping"),
            ("not_as_described", "Not as Described"),
            ("changed_mind", "Changed Mind"),
            ("quality_issues", "Quality Issues"),
            ("other", "Other"),
        ],
        "non_returnable": [
            "Perishable goods",
            "Personal care items once opened",
            "Gift cards / vouchers",
            "Items marked Final Sale",
        ],
        "refund_timelines": {
            "original_payment": "3–10 business days (processor dependent)",
            "store_credit": "Instant once processed",
            "bank_transfer": "1–3 business days after approval",
            "cash": "At the point of in‑store processing",
        },
        "support_email": getattr(settings, "SUPPORT_EMAIL", "support@example.com"),
    }
    return render(request, "returns/policy.html", {"policy": policy})

@login_required
def returns_hub(request):
    # Delivered orders within your return window logic (adjust filter)
    orders = (Order.objects
              .filter(buyer=request.user, status='delivered')
              .prefetch_related('items__product__store')
              .order_by('-created_at'))

    # All RMAs for this user
    my_returns = (Return.objects
                  .filter(buyer=request.user)
                  .select_related('order')
                  .order_by('-created_at'))

    return render(request, 'returns/hub.html', {
        'orders': orders,
        'my_returns': my_returns,
    })

@login_required
def start_return(request, order_id, store_id):
    order = get_object_or_404(Order, pk=order_id, buyer=request.user)
    store = get_object_or_404(Store, pk=store_id)

    items_qs = (
        order.items
        .select_related("product")
        .filter(product__store=store)
        .order_by("id")
    )

    if request.method == "POST":
        posted_reason = request.POST.get("reason")
        note = (request.POST.get("note") or "").strip()

        rows = []
        for oi in items_qs:
            try:
                qty = int(request.POST.get(f"qty_{oi.id}", "0") or 0)
            except ValueError:
                qty = 0
            qty = max(qty, 0)

            resolution = request.POST.get(f"resolution_{oi.id}", "refund")
            condition = request.POST.get(f"condition_{oi.id}", "good")
            item_reason = request.POST.get(f"reason_{oi.id}") or posted_reason or ""
            ex_variant = (request.POST.get(f"ex_variant_{oi.id}", "") or "").strip()

            if qty > 0:
                rows.append({
                    "order_item": oi,
                    "qty": qty,
                    "resolution": resolution,
                    "condition": condition,
                    "reason": item_reason,
                    "exchange_variant": ex_variant,
                })

        try:
            validate_return_request(order, store, request.user, rows)
        except ValidationError as e:
            context = {
                "order": order,
                "items": items_qs,
                "error": e.messages[0] if hasattr(e, "messages") else str(e),
                "posted": request.POST,
            }
            return render(request, "returns/start_return.html", context, status=400)

        with transaction.atomic():
            ret = Return.objects.create(
                order=order,
                buyer=request.user,
                status="pending",
                reason=posted_reason or (rows[0]["reason"] if rows else "other"),
                reason_description=note,
                logistics_method="easymarket_pickup",
            )

            for r in rows:
                oi = r["order_item"]
                price_snapshot = oi.price_at_time or oi.product.price
                ReturnItem.objects.create(
                    return_request=ret,
                    order_item=oi,
                    product=oi.product,
                    quantity=r["qty"],
                    reason=r["reason"] or "other",
                    condition=r["condition"],
                    price_at_return=Decimal(str(price_snapshot)),
                )

            for f in request.FILES.getlist("images"):
                ReturnImage.objects.create(return_request=ret, image=f)

            # Compute and store refund
            ret.calculate_refund_amount()
            ret.save(update_fields=["refund_amount", "updated_at"])

        messages.success(request, f"Return {ret.return_number} created successfully.")
        return redirect("returns:buyer_detail", rma=ret.return_number)

    context = {
        "order": order,
        "items": items_qs,
    }
    return render(request, "returns/start_return.html", context)

@login_required
def return_detail_buyer(request, rma: str):
    ret = get_object_or_404(
        Return.objects
        .select_related('order', 'buyer')
        .prefetch_related(
            Prefetch('items', queryset=ReturnItem.objects.select_related('product', 'order_item')),
            'images',
            'status_history',
        ),
        return_number=rma,
        buyer=request.user,
    )

    items = list(ret.items.all())
    items_refund_total = sum((ri.get_refund_amount() for ri in items), Decimal('0.00'))

    context = {
        'ret': ret,
        'order': ret.order,
        'items': items,
        'images': ret.images.all(),
        'status_history': ret.status_history.all(),
        'items_refund_total': items_refund_total,   # purely display; authoritative is ret.refund_amount
        'can_cancel': ret.can_be_cancelled(),
        'can_approve': ret.can_be_approved(),
    }
    return render(request, 'returns/buyer_detail.html', context)


@login_required
def return_detail_store(request, store_id, rma):
    # Ensure this store is owned by the current user
    store = get_object_or_404(Store, pk=store_id, owner=request.user)

    # Pull the Return with related data for template
    ret = get_object_or_404(
        Return.objects
        .select_related('order', 'buyer')            # header info
        .select_related('refund')                    # if you created ReturnRefund as OneToOne 'refund'
        .prefetch_related(
            Prefetch('items', queryset=ReturnItem.objects.select_related('product', 'order_item')),
            'images',
            'status_history',
        ),
        return_number=rma
    )

    # Security: make sure this return involves this store
    if not ret.items.filter(product__store=store).exists():
        raise PermissionDenied("This return is not associated with your store.")

    # Optional: split admin notes into lines for nicer display
    admin_notes_lines = (ret.admin_notes or "").splitlines()

    context = {
        'ret': ret,
        'store': store,
        'admin_notes_lines': admin_notes_lines,  # for template convenience
        'status_history': ret.status_history.all(),  # ordered by '-timestamp' per your model Meta
    }
    return render(request, 'returns/store_detail.html', context)

@login_required
def store_returns(request, store_id):
    """
    Seller dashboard view: list return requests that involve this store's products.
    Only the store owner can access it.
    """
    store = get_object_or_404(Store, pk=store_id, owner=request.user)

    # --- LIST (with prefetch for the table) ---
    returns_qs = (
        Return.objects
        .filter(items__product__store=store)   # ReturnItem.product.store == this store
        .select_related("order", "buyer")
        .prefetch_related(
            Prefetch(
                "items",
                queryset=ReturnItem.objects.select_related("product", "order_item")
            )
        )
        .distinct()  # fine for listing
        .order_by("-created_at")
    )

    # --- STATS (avoid duplicate rows from the join) ---
    # 1) Get unique Return IDs for this store
    base_ids = (
        Return.objects
        .filter(items__product__store=store)
        .values("id")
        .distinct()
    )
    # 2) Rebuild a clean queryset to aggregate on (no DISTINCT on aggregates)
    store_returns = Return.objects.filter(id__in=Subquery(base_ids))

    pending_count  = store_returns.filter(status="pending").count()
    approved_count = store_returns.filter(status="approved").count()
    total_refunds  = store_returns.filter(status="completed").aggregate(
        total=Sum("refund_amount")
    )["total"] or Decimal("0.00")

    context = {
        "store": store,
        "returns": returns_qs,
        # expose stats under simple keys (or a 'stats' dict if your template expects that)
        "pending_returns_count": pending_count,
        "approved_returns_count": approved_count,
        "total_refunds_amount": total_refunds,
    }
    return render(request, "returns/store_returns.html", context)
# --- Helper ---------------------------------------------------------------

def _get_store_and_return_or_403(store_id, rma, user):
    """
    Resolve store (owned by user) and return (by return_number),
    and ensure the return includes items from this store.
    """
    store = get_object_or_404(Store, pk=store_id, owner=user)

    # Your template uses ret.return_number, so lookups should use return_number
    ret = get_object_or_404(Return, return_number=rma)

    # If Return has no store FK, validate via items -> product.store
    if not ret.items.filter(product__store=store).exists():
        raise PermissionDenied("This return is not associated with your store.")

    return store, ret


def _append_history(ret, new_status=None, note=""):
    ReturnStatusHistory.objects.create(
        return_request=ret,
        status=(new_status or ret.status),
        changed_by=getattr(ret, "updated_by", None),
        notes=note or "",
    )


# --- Actions --------------------------------------------------------------

@login_required
@require_POST
def store_approve_return(request, store_id, rma):
    try:
        store, ret = _get_store_and_return_or_403(store_id, rma, request.user)

        allowed_from = ("pending", "rejected")  # re-approval allowed if you want
        if ret.status not in allowed_from:
            return JsonResponse({"success": False, "message": "Invalid status transition."}, status=400)

        ret.status = "approved"
        ret.updated_at = timezone.now()
        ret.save(update_fields=["status", "updated_at"])
        _append_history(ret, new_status="approved", note="Store approved return")

        return JsonResponse({"success": True})
    except PermissionDenied as e:
        return JsonResponse({"success": False, "message": str(e)}, status=403)
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=400)



@login_required
@require_POST
def store_reject_return(request, store_id, rma):
    try:
        store, ret = _get_store_and_return_or_403(store_id, rma, request.user)

        allowed_from = ("pending", "approved")  # decide your policy
        if ret.status not in allowed_from:
            return JsonResponse({"success": False, "message": "Invalid status transition."}, status=400)

        reason = (request.POST.get("reason") or "Rejected by store").strip()

        ret.status = "rejected"
        if hasattr(ret, "rejection_reason"):
            ret.rejection_reason = reason[:500]
            ret.updated_at = timezone.now()
            ret.save(update_fields=["status", "rejection_reason", "updated_at"])
        else:
            ret.updated_at = timezone.now()
            ret.save(update_fields=["status", "updated_at"])

        _append_history(ret, new_status="rejected", note=reason)
        return JsonResponse({"success": True})
    except PermissionDenied as e:
        return JsonResponse({"success": False, "message": str(e)}, status=403)
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=400)


@login_required
@require_POST
def store_mark_received(request, store_id, rma):
    try:
        store, ret = _get_store_and_return_or_403(store_id, rma, request.user)

        allowed_from = ("approved", "in_transit")
        if ret.status not in allowed_from:
            return JsonResponse({"success": False, "message": "Invalid status transition."}, status=400)

        ret.status = "received"
        if hasattr(ret, "received_at_store_date"):
            ret.received_at_store_date = timezone.now()
            ret.updated_at = timezone.now()
            ret.save(update_fields=["status", "received_at_store_date", "updated_at"])
        else:
            ret.updated_at = timezone.now()
            ret.save(update_fields=["status", "updated_at"])

        _append_history(ret, new_status="received", note="Parcel received at warehouse")
        # Optionally: adjust_stock_after_receive(ret)
        return JsonResponse({"success": True})
    except PermissionDenied as e:
        return JsonResponse({"success": False, "message": str(e)}, status=403)
    except ValueError as e:
        return JsonResponse({"success": False, "message": str(e)}, status=400)
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=400)


@login_required
@require_POST
def store_finalize_refund(request, store_id, rma):
    try:
        store, ret = _get_store_and_return_or_403(store_id, rma, request.user)

        if ret.status != "received":
            return JsonResponse({"success": False, "message": "Return not ready for refund."}, status=400)

        method = (request.POST.get("method") or "original_payment").strip()
        reference = (request.POST.get("reference") or "").strip()

        # If you wire a real PSP, call process_refund(ret, method=..., reference=..., user=request.user)
        # Ensure refund_amount is quantized & current
        ret.recalc_totals(save=True)

        ret.status = "completed"
        ret.updated_at = timezone.now()
        if hasattr(ret, "completed_at"):
            ret.completed_at = timezone.now()
            ret.save(update_fields=["status", "updated_at", "completed_at"])
        else:
            ret.save(update_fields=["status", "updated_at"])

        _append_history(ret, new_status="completed", note=f"Refund processed via {method}. Ref: {reference}")

        # Return the final refund string (avoid float rounding drift)
        return JsonResponse({"success": True, "amount": f"{ret.refund_amount:.2f}"})
    except PermissionDenied as e:
        return JsonResponse({"success": False, "message": str(e)}, status=403)
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=400)


@login_required
@require_POST
def store_fulfill_exchange(request, store_id, rma):
    try:
        store, ret = _get_store_and_return_or_403(store_id, rma, request.user)

        if ret.status not in ("inspecting", "approved_exchange"):
            return JsonResponse({"success": False, "message": "Return not ready for exchange."}, status=400)

        # shipment = create_exchange_shipment(ret)
        shipment = None  # remove when wired

        ret.status = "exchanged"
        ret.updated_at = timezone.now()
        ret.save(update_fields=["status", "updated_at"])
        _append_history(ret, new_status="exchanged", note="Exchange shipment created")

        return JsonResponse({"success": True, "shipment_id": str(getattr(shipment, "id", ""))})
    except PermissionDenied as e:
        return JsonResponse({"success": False, "message": str(e)}, status=403)
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=400)


@login_required
@require_POST
def add_return_note(request, store_id, rma):
    """
    Store owner adds an internal note to a return.
    URL name: returns:add_note  -> /store/<uuid:store_id>/returns/<str:rma>/add-note/
    """
    try:
        store, ret = _get_store_and_return_or_403(store_id, rma, request.user)

        note = (request.POST.get("note") or "").strip()
        if not note:
            return JsonResponse({"success": False, "message": "Note cannot be empty."}, status=400)
        if len(note) > 2000:
            return JsonResponse({"success": False, "message": "Note is too long."}, status=400)

        # History line (keep current status)
        _append_history(ret, new_status=ret.status, note=note)

        # Optional: accumulate into admin_notes
        stamp = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M")
        who = request.user.get_full_name() or request.user.username
        line = f"[{stamp}] {who}: {note}"
        if getattr(ret, "admin_notes", ""):
            ret.admin_notes = f"{ret.admin_notes}\n{line}"
        else:
            ret.admin_notes = line
        ret.updated_at = timezone.now()
        ret.save(update_fields=["admin_notes", "updated_at"])

        return JsonResponse({
            "success": True,
            "message": "Note added.",
            "note": {
                "text": note,
                "by": who,
                "at": stamp,
                "status": ret.get_status_display(),
            }
        })
    except PermissionDenied as e:
        return JsonResponse({"success": False, "message": str(e)}, status=403)
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=400)