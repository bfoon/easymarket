# store/b2b/views.py
from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import B2BCart, B2BCartItem, B2BOrder, B2BOrderItem


def _get_or_create_active_cart(user):
    cart = B2BCart.objects.filter(buyer=user, is_active=True).first()
    return cart or B2BCart.objects.create(buyer=user, is_active=True)


def _notify_store_new_b2b_order(order: B2BOrder):
    # Plug into your notifications (DB + websocket + email/whatsapp)
    # Notification.objects.create(user=order.store.owner, ...)
    pass


def _notify_buyer_b2b_priced(order: B2BOrder):
    pass


@login_required
def b2b_cart(request):
    cart = _get_or_create_active_cart(request.user)
    items = cart.items.select_related("product", "variant", "store").all()

    subtotal = Decimal("0.00")
    for it in items:
        b2b_price = getattr(it.product, "b2b_price", None)
        retail_price = getattr(it.product, "price", None)
        unit = Decimal(b2b_price) if b2b_price is not None else Decimal(retail_price or 0)
        subtotal += unit * Decimal(it.quantity)

    return render(request, "b2b/cart.html", {"cart": cart, "items": items, "subtotal": subtotal})


@login_required
@transaction.atomic
def b2b_cart_add(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    product_id = request.POST.get("product_id")
    variant_id = request.POST.get("variant_id") or None
    quantity = int(request.POST.get("quantity", "1") or "1")
    requested_unit_price = request.POST.get("requested_unit_price")

    Product = __import__("marketplace.models", fromlist=["Product"]).Product
    ProductVariant = __import__("marketplace.models", fromlist=["ProductVariant"]).ProductVariant

    product = get_object_or_404(Product, id=product_id)
    variant = None
    if variant_id:
        variant = get_object_or_404(ProductVariant, id=variant_id, product=product)

    # MOQ check if you have product.moq
    moq = getattr(product, "moq", None)
    if moq and quantity < int(moq):
        return JsonResponse({"error": f"MOQ is {moq}."}, status=400)

    cart = _get_or_create_active_cart(request.user)

    item, created = B2BCartItem.objects.get_or_create(
        cart=cart,
        product=product,
        variant=variant,
        defaults={"quantity": quantity}
    )

    if not created:
        item.quantity += quantity

    if requested_unit_price:
        try:
            item.requested_unit_price = Decimal(requested_unit_price)
        except Exception:
            pass

    item.save()
    return JsonResponse({"success": True, "qty": item.quantity})


@login_required
@transaction.atomic
def b2b_place_order(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    cart = B2BCart.objects.select_for_update().filter(buyer=request.user, is_active=True).first()
    if not cart:
        return JsonResponse({"error": "No active cart"}, status=400)

    cart_items = list(cart.items.select_related("product", "variant", "store").all())
    if not cart_items:
        return JsonResponse({"error": "Cart is empty"}, status=400)

    # One order per store
    grouped = {}
    for it in cart_items:
        st = it.store or getattr(it.product, "store", None)
        if not st:
            return JsonResponse({"error": "A product has no store"}, status=400)
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

        subtotal = Decimal("0.00")
        for it in grp["items"]:
            oi = B2BOrderItem.objects.create(
                order=order,
                product=it.product,
                variant=it.variant,
                quantity=it.quantity,
                product_name=it.product_name,
                requested_unit_price=it.requested_unit_price,
                seller_unit_price=None,  # seller sets later
            )
            subtotal += oi.line_total()

        order.subtotal = subtotal
        order.save(update_fields=["subtotal", "updated_at"])

        created_orders.append(str(order.id))
        _notify_store_new_b2b_order(order)

    # close cart
    cart.is_active = False
    cart.save(update_fields=["is_active", "updated_at"])
    cart.items.all().delete()

    return JsonResponse({"success": True, "orders": created_orders})


@login_required
@transaction.atomic
def store_b2b_order_detail(request, order_id):
    order = get_object_or_404(
        B2BOrder.objects.select_related("store", "buyer").prefetch_related("items__product", "items__variant"),
        id=order_id
    )

    # permission: only owner
    owner = getattr(order.store, "owner", None)
    if owner != request.user:
        return HttpResponseForbidden("Not allowed")

    if request.method == "POST":
        updated = 0
        for item in order.items.all():
            val = request.POST.get(f"price_{item.id}", "").strip()
            if not val:
                continue
            try:
                item.seller_unit_price = Decimal(val)
                item.save(update_fields=["seller_unit_price"])
                updated += 1
            except Exception:
                continue

        if updated > 0 and order.status == "submitted":
            order.status = "priced"
            order.priced_at = timezone.now()

        subtotal = Decimal("0.00")
        for item in order.items.all():
            subtotal += item.line_total()

        order.subtotal = subtotal
        order.save(update_fields=["status", "priced_at", "subtotal", "updated_at"])

        _notify_buyer_b2b_priced(order)
        return redirect("store_b2b:order_detail", order_id=str(order.id))

    return render(request, "store/b2b/store_order_detail.html", {"order": order})
