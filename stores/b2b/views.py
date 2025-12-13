from decimal import Decimal, InvalidOperation
import secrets
from .utils import _generate_b2b_tracking_number

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum, Q
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from marketplace.models import Product, ProductVariant
from stores.models import Store  # adjust if your Store model lives elsewhere

from .models import B2BCart, B2BCartItem, B2BOrder, B2BOrderItem, B2BShippingAddress, B2BOrderMessage


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def _get_or_create_active_cart(user):
    cart = B2BCart.objects.filter(buyer=user, is_active=True).first()
    return cart or B2BCart.objects.create(buyer=user, is_active=True)


def _notify_store_new_b2b_order(order: B2BOrder):
    # Plug into your notifications (DB + websocket + email/whatsapp)
    pass


def _notify_buyer_b2b_priced(order: B2BOrder):
    pass


def _user_has_store_access(user) -> bool:
    return Store.objects.filter(owner=user).exists()


def _safe_decimal(val, default=Decimal("0.00")):
    if val is None or str(val).strip() == "":
        return default
    try:
        return Decimal(str(val))
    except (InvalidOperation, ValueError, TypeError):
        return default


def _gen_tracking_number(order) -> str:
    """
    Example format: EM-B2B-20251212-8B2F-7C9A21
    - date stamp
    - short order id chunk
    - random
    """
    date_part = timezone.now().strftime("%Y%m%d")
    short_part = str(order.id).split("-")[0].upper()  # works great for UUID orders
    rand_part = secrets.token_hex(3).upper()          # 6 chars
    return f"EM-B2B-{date_part}-{short_part}-{rand_part}"


def _ensure_unique_tracking(order) -> str:
    """
    Very low collision risk, but we still enforce uniqueness if you have a unique constraint.
    Tries a few times then falls back.
    """
    Model = order.__class__
    for _ in range(8):
        candidate = _gen_tracking_number(order)
        if not hasattr(order, "tracking_number"):
            return candidate
        if not Model.objects.filter(tracking_number=candidate).exists():
            return candidate
    return _gen_tracking_number(order)

# -------------------------------------------------------------------
# Small helpers
# -------------------------------------------------------------------
def _is_store_owner(request_user, order: B2BOrder) -> bool:
    owner = getattr(order.store, "owner", None)
    return bool(owner and owner == request_user)


def _recalc_order_subtotal(order: B2BOrder) -> Decimal:
    subtotal = Decimal("0.00")
    for item in order.items.all():
        # Your B2BOrderItem has line_total() in earlier code
        if hasattr(item, "line_total") and callable(item.line_total):
            subtotal += Decimal(item.line_total() or 0)
        else:
            # fallback
            unit = getattr(item, "seller_unit_price", None) or getattr(item, "requested_unit_price", None) or Decimal("0.00")
            subtotal += Decimal(unit) * Decimal(getattr(item, "quantity", 0) or 0)
    return subtotal

def _recalc_order_totals(order: B2BOrder) -> Decimal:
    subtotal = _recalc_order_subtotal(order)
    ship = _safe_decimal(getattr(order, "shipping_cost", Decimal("0.00")), Decimal("0.00"))
    order.subtotal = subtotal
    order.shipping_cost = ship
    return subtotal + ship


def _apply_optional_totals(order: B2BOrder, subtotal: Decimal):
    """
    If your order has optional fields like shipping_cost/total/discount,
    update them safely without breaking if they don’t exist.
    """
    order.subtotal = subtotal

    shipping_cost = getattr(order, "shipping_cost", None)
    if shipping_cost is None and hasattr(order, "shipping_fee"):
        shipping_cost = getattr(order, "shipping_fee", None)

    discount = getattr(order, "discount_amount", None)
    if discount is None and hasattr(order, "discount"):
        discount = getattr(order, "discount", None)

    shipping_cost = Decimal(str(shipping_cost or 0))
    discount = Decimal(str(discount or 0))

    if hasattr(order, "total"):
        order.total = (subtotal + shipping_cost - discount)

    order.updated_at = timezone.now()

def _notify_buyer_b2b_status(order: B2BOrder):
    pass


def _notify_store_new_b2b_message(order: B2BOrder, message_obj=None):
    pass

# -------------------------------------------------------------------
# Cart
# -------------------------------------------------------------------
@login_required
def b2b_cart(request):
    cart = _get_or_create_active_cart(request.user)

    # cart item usually has: cart, product, variant, quantity, requested_unit_price
    items = cart.items.select_related("product", "variant", "product__store").all()

    subtotal = Decimal("0.00")
    for it in items:
        # Prefer explicit B2B price fields
        b2b_price = getattr(it.product, "b2b_price", None)
        retail_price = getattr(it.product, "price", None)
        unit = _safe_decimal(b2b_price, _safe_decimal(retail_price))
        subtotal += unit * Decimal(int(it.quantity or 0))

    cart_count = cart.items.aggregate(total=Sum("quantity"))["total"] or 0

    return render(
        request,
        "b2b/cart.html",
        {
            "cart": cart,
            "items": items,
            "subtotal": subtotal,
            "cart_count": int(cart_count),
        },
    )


@login_required
@transaction.atomic
def b2b_cart_add(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"}, status=405)

    product_id = request.POST.get("product_id")
    variant_id = request.POST.get("variant_id") or None

    if not product_id:
        return JsonResponse({"success": False, "error": "product_id is required"}, status=400)

    # quantity safe parse
    try:
        quantity = int(request.POST.get("quantity", "1") or "1")
    except (TypeError, ValueError):
        quantity = 1
    quantity = max(1, quantity)

    requested_unit_price = request.POST.get("requested_unit_price")

    product = get_object_or_404(Product, id=product_id)
    variant = None
    if variant_id:
        variant = get_object_or_404(ProductVariant, id=variant_id, product=product)

    # MOQ (prefer B2B-specific fields)
    moq = (
        getattr(product, "b2b_min_quantity", None)
        or getattr(product, "moq", None)
        or getattr(product, "min_order_qty", None)
    )
    if moq:
        try:
            moq_int = int(moq)
        except (TypeError, ValueError):
            moq_int = None

        if moq_int and quantity < moq_int:
            return JsonResponse({"success": False, "error": f"MOQ is {moq_int}."}, status=400)

    cart = _get_or_create_active_cart(request.user)

    item, created = B2BCartItem.objects.get_or_create(
        cart=cart,
        product=product,
        variant=variant,
        defaults={"quantity": quantity},
    )

    if not created:
        item.quantity = int(item.quantity or 0) + quantity

    if requested_unit_price:
        item.requested_unit_price = _safe_decimal(requested_unit_price, default=item.requested_unit_price or None)

    item.save()

    cart_count = cart.items.aggregate(total=Sum("quantity"))["total"] or 0

    return JsonResponse(
        {
            "success": True,
            "qty": int(item.quantity or 0),      # line item qty after update
            "cart_count": int(cart_count),       # total qty across cart
            "item_id": str(item.id),
            "created": bool(created),
        }
    )


# -------------------------------------------------------------------
# Place Order (convert cart -> one order per store)
# -------------------------------------------------------------------
@login_required
@transaction.atomic
def b2b_place_order(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"}, status=405)

    cart = B2BCart.objects.select_for_update().filter(buyer=request.user, is_active=True).first()
    if not cart:
        return JsonResponse({"success": False, "error": "No active cart"}, status=400)

    cart_items = list(cart.items.select_related("product", "variant", "product__store").all())
    if not cart_items:
        return JsonResponse({"success": False, "error": "Cart is empty"}, status=400)

    grouped = {}
    for it in cart_items:
        st = getattr(it.product, "store", None)
        if not st:
            return JsonResponse({"success": False, "error": "A product has no store"}, status=400)

        grouped.setdefault(st.id, {"store": st, "items": []})
        grouped[st.id]["items"].append(it)

    created_orders = []

    for _, grp in grouped.items():
        store = grp["store"]

        order = B2BOrder.objects.create(
            buyer=request.user,
            store=store,
            cart_source=cart,
            status="submitted",
            buyer_note=(request.POST.get("buyer_note") or "").strip(),
        )

        # create items + subtotal
        for it in grp["items"]:
            B2BOrderItem.objects.create(
                order=order,
                product=it.product,
                variant=it.variant,
                quantity=int(it.quantity or 0),
                product_name=getattr(it.product, "name", "") or "",
                requested_unit_price=it.requested_unit_price,
                seller_unit_price=None,
            )

        # ✅ create shipping PER order
        B2BShippingAddress.objects.create(
            order=order,
            full_name=request.POST.get("ship_full_name") or request.user.get_full_name(),
            phone=request.POST.get("ship_phone", ""),
            email=request.POST.get("ship_email", request.user.email),
            company_name=request.POST.get("ship_company", ""),
            address_line=request.POST.get("ship_address", ""),
            city=request.POST.get("ship_city", ""),
            region=request.POST.get("ship_region", ""),
            country=request.POST.get("ship_country", "Gambia"),
            delivery_instructions=request.POST.get("ship_note", ""),
        )

        # ✅ recalc totals (subtotal + total)
        _recalc_order_totals(order)
        order.save(update_fields=["subtotal", "shipping_cost", "total", "updated_at"])

        created_orders.append(str(order.id))
        _notify_store_new_b2b_order(order)

    # close cart + clear items
    cart.is_active = False
    cart.updated_at = timezone.now()
    cart.save(update_fields=["is_active", "updated_at"])
    cart.items.all().delete()

    return JsonResponse({"success": True, "orders": created_orders})


# -------------------------------------------------------------------
# Orders (Store Owner Views)
# -------------------------------------------------------------------

@login_required
def b2b_my_orders(request):
    if not _user_has_store_access(request.user):
        return redirect("home")

    # ✅ All my stores
    stores = Store.objects.filter(owner=request.user).order_by("name")
    my_store_ids = list(stores.values_list("id", flat=True))

    # ✅ Pick "current store" (optional via query param ?store=<id>)
    store_id = (request.GET.get("store") or "").strip()
    if store_id:
        store = get_object_or_404(Store, id=store_id, owner=request.user)
    else:
        store = stores.first()  # could be None if user has no store

    # ✅ Base: seller orders (all my stores) + buyer orders (me)
    orders_qs = (
        B2BOrder.objects.filter(
            Q(store_id__in=my_store_ids) |
            Q(buyer=request.user)
        )
        .select_related("store", "buyer")
        .order_by("-created_at")
        .distinct()
    )

    # ✅ Optional: if a store is selected, filter seller side to that store
    # (buyer orders remain visible)
    if store:
        orders_qs = orders_qs.filter(Q(buyer=request.user) | Q(store=store))

    # ✅ attach role for template
    orders = []
    for o in orders_qs:
        view_as = "seller" if o.store_id in my_store_ids else "buyer"
        orders.append({"order": o, "view_as": view_as})

    return render(request, "b2b/my_orders.html", {
        "stores": stores,   # ✅ list of stores for dropdown/sidebar
        "store": store,     # ✅ current selected store
        "orders": orders,
    })

@login_required
@transaction.atomic
def store_b2b_order_detail(request, order_id):
    order = get_object_or_404(
        B2BOrder.objects.select_related("store", "buyer")
        .prefetch_related("items__product", "items__variant", "messages__sender", "shipping"),
        id=order_id,
    )

    if getattr(order.store, "owner", None) != request.user:
        return render(request, "403.html", status=403)

    items = order.items.select_related("product", "variant", "product__store").all()

    # ✅ totals always accurate (subtotal + shipping + total)
    grand_total = _recalc_order_totals(order)
    order.save(update_fields=["subtotal", "shipping_cost", "updated_at"])

    shipping = getattr(order, "shipping", None)

    # ✅ History: safe fallback list of dicts with title/created_at/note (no Status key)
    history = []
    try:
        B2BOrderStatusHistory = __import__("b2b.models", fromlist=["B2BOrderStatusHistory"]).B2BOrderStatusHistory
        history = B2BOrderStatusHistory.objects.filter(order=order).order_by("-created_at")
    except Exception:
        history = [
            {"title": f"Status: {order.get_status_display()}", "created_at": order.updated_at, "note": ""}
        ]

    # ✅ Messages from your B2B chat model
    messages = order.messages.all()  # already ordered by Meta.ordering

    return render(
        request,
        "b2b/store_order_detail.html",
        {
            "order": order,
            "store": order.store,
            "items": items,
            "shipping": shipping,
            "history": history,
            "messages": messages,
            "grand_total": grand_total,
        },
    )

# -------------------------------------------------------------------
# Invoice (IF you keep it inside stores_b2b app)
# NOTE: If you want {% url 'orders:invoice' %}, move this view + url into orders app instead.
# -------------------------------------------------------------------
@login_required
def order_invoice(request, order_id):
    order = get_object_or_404(
        B2BOrder.objects.select_related("buyer", "store").prefetch_related("items__product", "items__variant"),
        id=order_id,
    )

    if request.user != order.buyer and request.user != getattr(order.store, "owner", None):
        return render(request, "403.html", status=403)

    subtotal = Decimal("0.00")
    for item in order.items.all():
        subtotal += item.line_total()

    context = {
        "order": order,
        "items": order.items.all(),
        "subtotal": subtotal,
        "company_name": "EasyMarket B2B",
        "company_address": "Banjul, The Gambia",
        "company_email": "b2b@easymarket.gm",
        "company_phone": "+220 XXX XXX",
    }
    return render(request, "b2b/invoice.html", context)

# -------------------------------------------------------------------
# 1) Update B2B order status (store owner only)
# -------------------------------------------------------------------


@login_required
@transaction.atomic
def b2b_update_order_status(request, order_id):
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"}, status=405)

    try:
        order = get_object_or_404(
            B2BOrder.objects.select_related("store", "buyer"),
            id=order_id
        )

        # ✅ JSON on forbidden (frontend expects JSON)
        if not _is_store_owner(request.user, order):
            return JsonResponse({"success": False, "error": "Not allowed"}, status=403)

        new_status = (request.POST.get("status") or "").strip().lower()
        if not new_status:
            return JsonResponse({"success": False, "error": "status is required"}, status=400)

        allowed = {"priced", "in_progress", "ready", "shipped", "delivered", "rejected"}
        if new_status not in allowed:
            return JsonResponse(
                {"success": False, "error": f"Invalid status '{new_status}'"},
                status=400
            )

        now = timezone.now()
        current_status = (getattr(order, "status", "") or "").strip().lower()

        # ----------------------------------------------------
        # ✅ HARD LOCK once shipped/delivered
        # BUT: allow generating tracking if already shipped and missing tracking
        # ----------------------------------------------------
        if current_status in ("shipped", "delivered"):
            # allow only a “no-op” status set (same value) and only to generate tracking when missing
            if new_status == current_status == "shipped":
                if hasattr(order, "tracking_number"):
                    cur_tracking = (getattr(order, "tracking_number", "") or "").strip()
                    if not cur_tracking:
                        generated_tracking = None
                        for _ in range(5):
                            candidate = _generate_b2b_tracking_number(prefix="EM-B2B")
                            if not B2BOrder.objects.filter(tracking_number=candidate).exists():
                                generated_tracking = candidate
                                break

                        if not generated_tracking:
                            return JsonResponse(
                                {"success": False, "error": "Could not generate tracking number. Try again."},
                                status=500
                            )

                        update_fields = []

                        order.tracking_number = generated_tracking
                        update_fields.append("tracking_number")

                        if hasattr(order, "tracking_note"):
                            note = (getattr(order, "tracking_note", "") or "").strip()
                            if not note:
                                order.tracking_note = "Auto-generated after order was marked shipped."
                                update_fields.append("tracking_note")

                        if hasattr(order, "updated_at"):
                            order.updated_at = now
                            update_fields.append("updated_at")

                        order.save(update_fields=list(set(update_fields)))

                        return JsonResponse({
                            "success": True,
                            "order_id": str(order.id),
                            "status": getattr(order, "status", ""),
                            "tracking_number": getattr(order, "tracking_number", ""),
                            "tracking_generated": True,
                            "locked": True,
                        })

                # shipped already + tracking already exists => locked
                return JsonResponse(
                    {"success": False, "error": "Order is shipped and locked. Status cannot be changed."},
                    status=400
                )

            # delivered lock or any other attempted change
            return JsonResponse(
                {"success": False, "error": "Order is shipped and locked. Status cannot be changed."},
                status=400
            )

        # ----------------------------------------------------
        # Normal status update (pre-shipped)
        # ----------------------------------------------------
        update_fields = []

        if hasattr(order, "status"):
            order.status = new_status
            update_fields.append("status")

        # Optional timestamps (only if fields exist)
        if new_status == "priced" and hasattr(order, "priced_at"):
            order.priced_at = now
            update_fields.append("priced_at")

        if new_status == "accepted" and hasattr(order, "accepted_at"):
            order.accepted_at = now
            update_fields.append("accepted_at")

        if new_status == "shipped" and hasattr(order, "shipped_at"):
            order.shipped_at = now
            update_fields.append("shipped_at")

        if new_status == "delivered" and hasattr(order, "delivered_at"):
            order.delivered_at = now
            update_fields.append("delivered_at")

        if new_status == "cancelled" and hasattr(order, "cancelled_at"):
            order.cancelled_at = now
            update_fields.append("cancelled_at")

        # ✅ AUTO TRACKING when moved to shipped AND tracking not set
        generated_tracking = None
        if new_status == "shipped" and hasattr(order, "tracking_number"):
            cur_tracking = (getattr(order, "tracking_number", "") or "").strip()
            if not cur_tracking:
                for _ in range(5):
                    candidate = _generate_b2b_tracking_number(prefix="EM-B2B")
                    if not B2BOrder.objects.filter(tracking_number=candidate).exists():
                        order.tracking_number = candidate
                        generated_tracking = candidate
                        update_fields.append("tracking_number")
                        break

                if generated_tracking and hasattr(order, "tracking_note"):
                    note = (getattr(order, "tracking_note", "") or "").strip()
                    if not note:
                        order.tracking_note = "Auto-generated on status update to shipped."
                        update_fields.append("tracking_note")

        if hasattr(order, "updated_at"):
            order.updated_at = now
            update_fields.append("updated_at")

        if update_fields:
            order.save(update_fields=list(set(update_fields)))
        else:
            order.save()

        _notify_buyer_b2b_status(order)

        return JsonResponse({
            "success": True,
            "order_id": str(order.id),
            "status": getattr(order, "status", ""),
            "tracking_number": getattr(order, "tracking_number", "") if hasattr(order, "tracking_number") else "",
            "tracking_generated": bool(generated_tracking),
            "locked": False,
        })

    except Exception as e:
        return JsonResponse({"success": False, "error": f"Server error: {str(e)}"}, status=500)

# -------------------------------------------------------------------
# 2) Save seller prices for items (store owner only)
#    Expects POST: price_<item_id> = "12.50"
# -------------------------------------------------------------------

@login_required
@transaction.atomic
def b2b_save_prices(request, order_id):
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"}, status=405)

    order = get_object_or_404(
        B2BOrder.objects.select_related("store", "buyer").prefetch_related("items"),
        id=order_id
    )

    if not _is_store_owner(request.user, order):
        return JsonResponse({"success": False, "error": "Not allowed"}, status=403)

    updated = 0
    errors = []
    locked = 0

    for item in order.items.all():
        key = f"price_{item.id}"
        raw = (request.POST.get(key) or "").strip()

        # empty => no change
        if raw == "":
            continue

        # ✅ LOCK shipped items
        if getattr(item, "status", "") == "shipped":
            locked += 1
            errors.append(f"Item {item.id} is shipped; price is locked.")
            continue

        price = _safe_decimal(raw, default=None)
        if price is None or price < 0:
            errors.append(f"Invalid price for item {item.id}")
            continue

        # lock BOTH seller_unit_price + unit_price
        item.seller_unit_price = price
        item.unit_price = price
        item.save(update_fields=["seller_unit_price", "unit_price"])
        updated += 1

    # Recalc subtotal + optional totals
    subtotal = _recalc_order_subtotal(order)
    _apply_optional_totals(order, subtotal)

    # If any price updated and status was submitted => priced
    if updated > 0 and getattr(order, "status", "") == "submitted":
        order.status = "priced"
        if hasattr(order, "priced_at"):
            order.priced_at = timezone.now()

    # Save order fields safely
    fields = ["subtotal"]
    if hasattr(order, "updated_at"):
        fields.append("updated_at")
    if hasattr(order, "status"):
        fields.append("status")
    if hasattr(order, "priced_at") and updated > 0:
        fields.append("priced_at")
    if hasattr(order, "total"):
        fields.append("total")

    order.save(update_fields=list(set(fields)))

    if updated > 0:
        _notify_buyer_b2b_priced(order)

    return JsonResponse({
        "success": True,
        "updated": updated,
        "locked": locked,
        "errors": errors,
        "status": getattr(order, "status", ""),
        "subtotal": str(order.subtotal),
        "total": str(getattr(order, "total", order.subtotal)),
    })

@login_required
@transaction.atomic
def b2b_save_unit_prices(request, order_id):
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"}, status=405)

    try:
        order = get_object_or_404(
            B2BOrder.objects.select_related("store", "buyer").prefetch_related("items"),
            id=order_id
        )

        if not _is_store_owner(request.user, order):
            return JsonResponse({"success": False, "error": "Not allowed"}, status=403)

        updated = 0
        locked = 0
        errors = []

        for item in order.items.all():
            key = f"unit_price_{item.id}"
            raw = (request.POST.get(key) or "").strip()

            # empty => skip
            if raw == "":
                continue

            # ✅ LOCK shipped items
            if getattr(item, "status", "") == "shipped":
                locked += 1
                errors.append(f"Item {item.id} is shipped; unit price is locked.")
                continue

            price = _safe_decimal(raw, default=None)
            if price is None or price < 0:
                errors.append(f"Invalid unit price for item {item.id}")
                continue

            item.unit_price = price

            # Sync seller unit price for B2B
            item.seller_unit_price = price

            item.save(update_fields=["unit_price", "seller_unit_price"])
            updated += 1

        # recalc totals
        subtotal = _recalc_order_subtotal(order)
        _apply_optional_totals(order, subtotal)

        # save order
        fields = ["subtotal"]
        if hasattr(order, "total"):
            fields.append("total")
        if hasattr(order, "updated_at"):
            fields.append("updated_at")

        order.save(update_fields=list(set(fields)))

        return JsonResponse({
            "success": True,
            "updated": updated,
            "locked": locked,
            "errors": errors,
            "subtotal": str(order.subtotal),
            "total": str(getattr(order, "total", order.subtotal)),
        })

    except Exception as e:
        return JsonResponse(
            {"success": False, "error": f"Server error: {str(e)}"},
            status=500
        )

# -------------------------------------------------------------------
# 3) Send chat message (store owner -> buyer)
#    Uses your existing orders chat models if available:
#      orders.models.ChatThread (manager get_or_create_between)
#      orders.models.ChatMessage
#    Expects POST: message="...", (optional) channel, etc.
# -------------------------------------------------------------------

@login_required
def b2b_order_send_message(request, order_id):
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"}, status=405)

    order = get_object_or_404(B2BOrder.objects.select_related("store", "buyer"), id=order_id)

    is_owner = (getattr(order.store, "owner", None) == request.user)
    is_buyer = (order.buyer == request.user)
    if not (is_owner or is_buyer):
        return JsonResponse({"success": False, "error": "Not allowed"}, status=403)

    message = (request.POST.get("message") or "").strip()
    if not message:
        return JsonResponse({"success": False, "error": "message is required"}, status=400)

    msg = B2BOrderMessage.objects.create(order=order, sender=request.user, message=message)

    return JsonResponse({
        "success": True,
        "message": {
            "id": str(msg.id),
            "sender_id": msg.sender_id,
            "sender_name": msg.sender.get_full_name() or msg.sender.username,
            "text": msg.message,
            "created_at": msg.created_at.isoformat(),
        }
    })

# -------------------------------------------------------------------
# 4) Mark order items shipped (store owner only)
#    Expects POST: item_ids="1,2,3"  OR item_ids[]=...
#    If your B2BOrderItem has shipped fields, it sets them.
#    Otherwise it safely does nothing but can still set order status if requested.
# -------------------------------------------------------------------

@login_required
@transaction.atomic
def b2b_mark_items_shipped(request, order_id):
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"}, status=405)

    try:
        order = get_object_or_404(
            B2BOrder.objects.select_related("store", "buyer").prefetch_related("items"),
            id=order_id
        )

        if not _is_store_owner(request.user, order):
            return JsonResponse({"success": False, "error": "Not allowed"}, status=403)

        # Accept both: item_ids[] OR item_ids csv
        item_ids = request.POST.getlist("item_ids[]")
        if not item_ids:
            raw = (request.POST.get("item_ids") or "").strip()
            item_ids = [x.strip() for x in raw.split(",") if x.strip()]

        if not item_ids:
            return JsonResponse({"success": False, "error": "Select at least one item."}, status=400)

        now = timezone.now()

        qs = order.items.filter(id__in=item_ids)

        found_ids = set(str(x) for x in qs.values_list("id", flat=True))
        requested_ids = set(str(x) for x in item_ids)
        missing_ids = sorted(list(requested_ids - found_ids))

        if not qs.exists():
            return JsonResponse(
                {"success": False, "error": "No valid items selected for this order.", "missing_ids": missing_ids},
                status=400
            )

        # ✅ mark selected items shipped
        updated = 0
        for item in qs:
            # if already shipped, skip (optional)
            if getattr(item, "status", "") == "shipped":
                continue

            item.status = "shipped"
            item.shipped_at = now
            item.save(update_fields=["status", "shipped_at"])
            updated += 1

        # ✅ auto-generate tracking number on FIRST shipment (only if blank)
        order_fields = []

        if hasattr(order, "tracking_number"):
            current_tracking = (order.tracking_number or "").strip()
            if not current_tracking:
                order.tracking_number = _ensure_unique_tracking(order)
                order_fields.append("tracking_number")

        # Optional note from request
        note = (request.POST.get("note") or "").strip()
        if note and hasattr(order, "tracking_note"):
            # append nicely if note already exists
            existing = (getattr(order, "tracking_note", "") or "").strip()
            order.tracking_note = (existing + "\n" if existing else "") + note
            order_fields.append("tracking_note")

        # Always bump updated_at
        if hasattr(order, "updated_at"):
            order.updated_at = now
            order_fields.append("updated_at")

        # ✅ auto mark order shipped only when ALL items shipped
        all_shipped = not order.items.exclude(status="shipped").exists()
        if all_shipped:
            if hasattr(order, "status"):
                order.status = "shipped"
                order_fields.append("status")
            if hasattr(order, "shipped_at"):
                order.shipped_at = now
                order_fields.append("shipped_at")

        if order_fields:
            order.save(update_fields=list(set(order_fields)))

        return JsonResponse({
            "success": True,
            "updated": updated,
            "missing_ids": missing_ids,
            "order_status": getattr(order, "status", ""),
            "all_shipped": all_shipped,
            "tracking_number": getattr(order, "tracking_number", ""),
        })

    except Exception as e:
        return JsonResponse({"success": False, "error": f"Server error: {str(e)}"}, status=500)

# -------------------------------------------------------------------
# 5) Set shipping cost (store owner only)
#    Expects POST: shipping_cost="50.00"
# -------------------------------------------------------------------

@login_required
@transaction.atomic
def b2b_set_shipping_cost(request, order_id):
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"}, status=405)

    order = get_object_or_404(
        B2BOrder.objects.select_related("store", "buyer").prefetch_related("items"),
        id=order_id
    )

    # Must be store owner
    if getattr(order.store, "owner", None) != request.user:
        return JsonResponse({"success": False, "error": "Not allowed"}, status=403)

    # ✅ LOCK: once shipped (or delivered), shipping cost cannot be edited
    status = (getattr(order, "status", "") or "").lower().strip()
    if status in ("shipped", "delivered"):
        return JsonResponse(
            {"success": False, "error": "Shipping cost cannot be updated after the order is shipped."},
            status=400
        )

    cost = _safe_decimal(request.POST.get("shipping_cost"), default=None)
    if cost is None:
        return JsonResponse({"success": False, "error": "shipping_cost is required"}, status=400)
    if cost < 0:
        return JsonResponse({"success": False, "error": "Invalid shipping_cost"}, status=400)

    order.shipping_cost = cost

    # Recalc totals (your helper should set subtotal/total)
    _recalc_order_totals(order)

    # Ensure updated_at changes (if field exists)
    update_fields = ["shipping_cost", "subtotal", "total"]
    if hasattr(order, "updated_at"):
        order.updated_at = timezone.now()
        update_fields.append("updated_at")

    order.save(update_fields=list(set(update_fields)))

    return JsonResponse({
        "success": True,
        "shipping_cost": str(order.shipping_cost),
        "subtotal": str(getattr(order, "subtotal", "")),
        "total": str(getattr(order, "total", getattr(order, "subtotal", ""))),
    })
