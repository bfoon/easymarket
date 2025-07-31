from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden, Http404
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone
from decimal import Decimal
from django.contrib import messages

from orders.models import Order, OrderItem, Return, ReturnItem, ReturnImage
from marketplace.models import ProductVariant
from stores.models import Store
from .services.returns import (
    validate_return_request, create_return_from_post, mark_status, compute_refund,
    adjust_stock_after_receive, process_refund,
)
from .services.returns import validate_return_request
from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from django.conf import settings
from .models import Return, ReturnStatusHistory
from django.core.exceptions import PermissionDenied

from django.views.decorators.http import require_POST

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
    """
    Create a return for a specific order+store.
    Assumes your URL pattern is:
      orders/<int:order_id>/store/<uuid:store_id>/returns/start/
    If Store.id is INT, change <uuid:store_id> to <int:store_id>.
    """

    order = get_object_or_404(Order, pk=order_id, buyer=request.user)

    # Resolve store (UUID or INT depending on your model)
    store = get_object_or_404(Store, pk=store_id)

    # Items limited to this store. Adjust if your Product->Store relation differs.
    items_qs = (
        order.items
        .select_related("product")
        .filter(product__store=store)
        .order_by("id")
    )

    if request.method == "POST":
        posted_reason = request.POST.get("reason")  # overall reason (select)
        note = request.POST.get("note", "").strip()

        # Build rows from POST
        rows = []
        for oi in items_qs:
            qty = int(request.POST.get(f"qty_{oi.id}", "0") or 0)
            if qty < 0:
                qty = 0  # sanitize, server-side validation will catch if needed

            resolution = request.POST.get(f"resolution_{oi.id}", "refund")
            condition = request.POST.get(f"condition_{oi.id}", "good")
            item_reason = request.POST.get(f"reason_{oi.id}") or posted_reason or ""
            ex_variant = (request.POST.get(f"ex_variant_{oi.id}", "") or "").strip()

            # Only add non-zero rows; zeroes are ignored
            if qty > 0:
                rows.append({
                    "order_item": oi,
                    "qty": qty,
                    "resolution": resolution,
                    "condition": condition,
                    "reason": item_reason,
                    "exchange_variant": ex_variant,
                })

        # Validate request (ownership, store match, qty remaining, at least one line, etc.)
        try:
            validate_return_request(order, store, request.user, rows)
        except ValidationError as e:
            # Show a friendly error and re-render the form (HTTP 400)
            context = {
                "order": order,
                "items": items_qs,
                "error": e.messages[0] if hasattr(e, "messages") else str(e),
                "posted": request.POST,
            }
            return render(request, "returns/start.html", context, status=400)

        # Create Return header
        ret = Return.objects.create(
            order=order,
            buyer=request.user,
            status="pending",
            reason=posted_reason or (rows[0]["reason"] if rows else "other"),
            reason_description=note,
            logistics_method="easymarket_pickup",  # or use posted value if you add it
        )

        # Create ReturnItem lines
        for r in rows:
            oi = r["order_item"]
            ReturnItem.objects.create(
                return_request=ret,
                order_item=oi,
                product=oi.product,
                quantity=r["qty"],
                reason=r["reason"] or "other",
                condition=r["condition"],
                # snapshot (falls back to product.price)
                price_at_return=(oi.price_at_time or oi.product.price),
            )

        # Save uploaded images (multi-file)
        for f in request.FILES.getlist("images"):
            ReturnImage.objects.create(return_request=ret, image=f)

        # Recalculate refund and save
        ret.calculate_refund_amount()
        ret.save(update_fields=["refund_amount", "updated_at"])

        messages.success(request, f"Return {ret.return_number} created successfully.")
        return redirect("returns:buyer_detail", rma=ret.return_number)

    # GET — render form
    context = {
        "order": order,
        "items": items_qs,
    }
    return render(request, "returns/start_return.html", context)


@login_required
def return_detail_buyer(request, rma: str):
    """
    Buyer-facing detail page for a Return.
    URL: /returns/<return_number>/
    Named param 'rma' is the return number string (e.g., 'RET-584460').
    """

    ret = get_object_or_404(
        Return.objects
        .select_related('order', 'buyer')
        .prefetch_related(
            Prefetch('items', queryset=ReturnItem.objects.select_related('product', 'order_item')),
            'images',
            'status_history',
        ),
        return_number=rma,               # <-- use correct field
        buyer=request.user,              # ensure ownership
    )

    # Optional: quick derived totals for template
    items = list(ret.items.all())
    items_refund_total = sum((ri.get_refund_amount() for ri in items), start=0)
    # If you want to ensure accuracy, you can also call:
    # ret.calculate_refund_amount()  # but this will save; avoid on GET unless needed

    context = {
        'ret': ret,
        'order': ret.order,
        'items': items,
        'images': ret.images.all(),
        'status_history': ret.status_history.all(),
        'items_refund_total': items_refund_total,
        'can_cancel': ret.can_be_cancelled(),
        'can_approve': ret.can_be_approved(),  # buyers won’t approve; useful if you reuse template
    }
    return render(request, 'returns/buyer_detail.html', context)

@login_required
def return_detail_store(request, store_id, rma):
    store = get_object_or_404(Store,  id=store_id, owner=request.user)
    ret = get_object_or_404(Return, return_number=rma)
    return render(request, 'returns/store_detail.html', {'ret': ret, 'store': store})



@login_required
def store_returns(request, store_id):
    """
    Seller dashboard view: list return requests that involve this store's products.
    Only the store owner can access it.
    """
    store = get_object_or_404(Store, pk=store_id, owner=request.user)

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
        .distinct()
        .order_by("-created_at")
    )

    context = {
        "store": store,
        "returns": returns_qs,
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
    """
    Create a status history row. Adapt field names to your model.
    """
    if hasattr(ReturnStatusHistory, "_meta"):
        # Field names: use 'note' or 'notes' depending on your model
        kwargs = dict(
            return_request=ret,
            status=(new_status or ret.status),
            changed_by=getattr(ret, "updated_by", None),  # optional
        )
        try:
            # Most common naming
            kwargs["note"] = note
            ReturnStatusHistory.objects.create(**kwargs)
        except TypeError:
            # Fallback if your model uses 'notes'
            kwargs.pop("note", None)
            kwargs["notes"] = note
            ReturnStatusHistory.objects.create(**kwargs)

# --- Actions --------------------------------------------------------------

@login_required
@require_POST
def store_approve_return(request, store_id, rma):
    try:
        store, ret = _get_store_and_return_or_403(store_id, rma, request.user)

        # Allow only certain transitions (adapt to your choices)
        allowed_from = ("requested", "pending", "rejected")
        if ret.status not in allowed_from:
            return JsonResponse(
                {"success": False, "message": "Invalid status transition."},
                status=400
            )

        # If you have a helper that also writes history, use it:
        # mark_status(ret, 'approved', note='Store approved return', user=request.user)
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

        allowed_from = ("requested", "pending", "approved")  # tweak as needed
        if ret.status not in allowed_from:
            return JsonResponse(
                {"success": False, "message": "Invalid status transition."},
                status=400
            )

        reason = (request.POST.get("reason") or "Rejected by store").strip()

        # mark_status(ret, 'rejected', note=reason, user=request.user)
        ret.status = "rejected"
        if hasattr(ret, "rejection_reason"):
            ret.rejection_reason = reason[:500]
            ret.save(update_fields=["status", "rejection_reason", "updated_at"])
        else:
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

        allowed_from = ("approved", "in_transit", "awaiting_pickup")
        if ret.status not in allowed_from:
            return JsonResponse(
                {"success": False, "message": "Invalid status transition."},
                status=400
            )

        # mark_status(ret, 'received', note='Parcel received at warehouse', user=request.user)
        ret.status = "received"
        if hasattr(ret, "received_at_store_date"):
            ret.received_at_store_date = timezone.now()
            ret.save(update_fields=["status", "received_at_store_date", "updated_at"])
        else:
            ret.save(update_fields=["status", "updated_at"])
        _append_history(ret, new_status="received", note="Parcel received at warehouse")

        # Optional: move to 'inspecting' and adjust stock
        # mark_status(ret, 'inspecting', note='Inspection in progress', user=request.user)
        ret.status = "inspecting"
        ret.updated_at = timezone.now()
        ret.save(update_fields=["status", "updated_at"])
        _append_history(ret, new_status="inspecting", note="Inspection in progress")

        # If you have stock logic:
        # adjust_stock_after_receive(ret)

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

        if ret.status not in ("inspecting", "approved_refund"):
            return JsonResponse({"success": False, "message": "Return not ready for refund."}, status=400)

        method = (request.POST.get("method") or "original").strip()
        reference = (request.POST.get("reference") or "").strip()

        # refund = process_refund(ret, method=method, reference=reference, user=request.user)
        # Dummy example if you don’t have process_refund wired yet:
        class RefundLike:
            amount = getattr(ret, "refund_amount", 0)
        refund = RefundLike()

        # mark_status(ret, 'completed', note=f"Refund processed via {method}", user=request.user)
        ret.status = "completed"
        ret.updated_at = timezone.now()
        if hasattr(ret, "completed_at"):
            ret.completed_at = timezone.now()
            ret.save(update_fields=["status", "updated_at", "completed_at"])
        else:
            ret.save(update_fields=["status", "updated_at"])
        _append_history(ret, new_status="completed", note=f"Refund processed via {method}. Ref: {reference}")

        return JsonResponse({"success": True, "amount": f"{float(refund.amount):.2f}"})
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