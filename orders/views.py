from django.shortcuts import redirect, render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q, Sum
from django.core.paginator import Paginator
from django.utils import timezone
from datetime import timedelta
from stock.stock_utils_compatibility import reduce_stock
from stock.models import Stock, StockMovement
from stores.models import Store
from .models import Order, OrderItem, PromoCode, ChatMessage
from marketplace.models import Cart, CartItem, Product, PaymentShare, CartMember, SocialCart
from analytics.models import CartEvent
from utils.qr import generate_invoice_qr_code
from django.core.exceptions import ValidationError
from decimal import Decimal, InvalidOperation
from django.views.decorators.csrf import csrf_protect
from django.db import transaction
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_GET
import json
from django.views.decorators.http import require_http_methods
from django.template.loader import get_template
from django.http import HttpResponse
from django.urls import reverse
from weasyprint import HTML
import tempfile
from django.contrib.auth import get_user_model
import threading
from marketplace.notifications import send_whatsapp, send_email
from analytics.services import track_event
import logging
logger = logging.getLogger(__name__)

def _ensure_session(request):
    """Make sure guests also have a session_key for tracking."""
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def _track_cart_event(request, event: str):
    """
    Record cart analytics event (add/remove/checkout/completed/abandoned).
    Safe: never breaks cart flow if analytics fails.
    """
    try:
        session_key = _ensure_session(request)
        CartEvent.objects.create(
            user=request.user if request.user.is_authenticated else None,
            session_key=session_key,
            event=event,
        )
    except Exception:
        pass

def notify_store_new_order(order):
    User = get_user_model()

    # Get distinct sellers from this order
    seller_ids = (
        order.items
        .select_related('product__seller')
        .values_list('product__seller', flat=True)
        .distinct()
    )

    for seller_id in seller_ids:
        try:
            seller = User.objects.get(id=seller_id)
            seller_items = order.items.filter(product__seller=seller)

            # 🧾 Build order summary for this seller
            item_lines = []
            for item in seller_items:
                feature_str = ""
                if item.selected_features:
                    feature_str = " | Features: " + ", ".join(
                        f"{k}: {v}" for k, v in item.selected_features.items()
                    )

                item_lines.append(
                    f"- {item.product.name} x{item.quantity}{feature_str}"
                )

            summary = "\n".join(item_lines)

            subject = f"🛒 New Order #{order.id} - {seller_items.count()} Item(s)"
            message = (
                f"You have received a new order from {order.buyer.get_full_name()}.\n\n"
                f"Order Number: {order.id}\n"
                f"Buyer Email: {order.buyer.email}\n"
                f"Items:\n{summary}\n\n"
                f"View and fulfill the order from your dashboard."
                f"https://www.easymarket.vip/"
            )

            # Send batched email and WhatsApp
            send_email(subject, message, [seller.email])
            send_whatsapp(seller.telephone, message)

        except Exception as e:
            print(f"[Notify Seller] Error for seller {seller_id}: {e}")


def notify_store_new_order_async(order):
    """Run notify_store_new_order in a background thread."""
    thread = threading.Thread(target=notify_store_new_order, args=(order,))
    thread.start()

def notify_buyer_new_message(message):
    buyer = message.recipient
    subject = "You have a new message"
    msg = f"You have a new message from {message.sender.get_full_name()}: {message.content[:50]}"
    send_email(subject, msg, [buyer.email])
    send_whatsapp(buyer.telephone, msg)



@login_required
@require_GET
def checkout_redirect(request):
    """
    Auto-submit POST to /orders/checkout/ if 'checkout_after_login' is in session
    """
    if request.session.get('checkout_after_login'):
        del request.session['checkout_after_login']
        return render(request, 'orders/confirm_checkout.html')  # auto-submit form
    return redirect('marketplace:cart_view')



def _resolve_active_social_for(user):
    # Mirrors your social resolver approach in social_cart.py :contentReference[oaicite:2]{index=2}
    return (
        SocialCart.objects
        .filter(is_active=True, status__in=["open", "checkout"],
                members__user=user, members__status="joined")
        .select_related("cart", "owner")
        .order_by("-created_at")
        .first()
    )


def _money(v):
    return (v or Decimal("0.00")).quantize(Decimal("0.01"))

# ---------------------------------------------------------
# ✅ STOCK UTILS (put in orders/views.py or import from stock utils)
# ---------------------------------------------------------
def _safe_selected_features(value):
    """
    Normalize selected_features coming from CartItem.

    Handles:
    - None
    - dict
    - JSON string
    - empty string
    - invalid JSON (fails silently)

    Always returns:
    - dict (preferred)
    - or None
    """
    if value in (None, "", {}, []):
        return None

    # Already a dict → OK
    if isinstance(value, dict):
        return value

    # JSON stored as string
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    # Any other type → discard safely
    return None

@transaction.atomic
def reduce_stock_for_checkout(*, product, quantity, warehouse, user=None, reference_prefix="ORDER", notes="Checkout sale"):
    """
    Reduce stock safely from Stock table (NOT Product.stock_quantity property).
    - Locks stock row (select_for_update)
    - Prevents negative stock
    - Records StockMovement as SALE
    """
    qty = int(quantity or 0)
    if qty <= 0:
        raise ValidationError("Invalid quantity.")

    if warehouse is None:
        raise ValidationError(f"Store '{product.store.name}' has no warehouse configured.")

    stock_row, _ = Stock.objects.select_for_update().get_or_create(
        product=product,
        warehouse=warehouse,
        defaults={
            "quantity": 0,
            "unit_cost": Decimal("0.00"),
        },
    )

    available = int(stock_row.quantity or 0)
    if available < qty:
        raise ValidationError(
            f"Insufficient stock for '{product.name}'. Available: {available}, requested: {qty}"
        )

    stock_row.quantity = available - qty
    stock_row.save(update_fields=["quantity", "updated_at"])

    StockMovement.objects.create(
        product=product,
        warehouse=warehouse,
        movement_type="SALE",
        quantity=-qty,
        reference_number=f"{reference_prefix}-{product.id}-{int(timezone.now().timestamp())}",
        unit_cost=stock_row.unit_cost,
        notes=notes,
        created_by=user if user and getattr(user, "is_authenticated", False) else None,
    )


def get_available_stock(*, product, warehouse):
    """
    Helper for quick checks (no lock). Real enforcement happens in reduce_stock_for_checkout().
    """
    if not warehouse:
        return 0
    return int(
        Stock.objects.filter(product=product, warehouse=warehouse)
        .values_list("quantity", flat=True)
        .first() or 0
    )


# ---------------------------------------------------------
# ✅ CHECKOUT CART (SOCIAL CART + SPLIT-AWARE + DUPLICATE-SAFE)
# ---------------------------------------------------------
def validate_promo_code(promo_code_str, subtotal, user=None):
    """
    Validate and calculate promo code discount.
    Returns: (promo_object, discount_amount, error_message)
    """
    if not promo_code_str:
        return None, Decimal('0'), None

    try:
        promo = PromoCode.objects.get(
            code=promo_code_str.strip(),
            is_active=True,
            valid_from__lte=timezone.now(),
            valid_until__gte=timezone.now()
        )
    except PromoCode.DoesNotExist:
        return None, Decimal('0'), "Invalid promo code"

    # Check max uses
    if promo.max_uses and promo.uses >= promo.max_uses:
        return None, Decimal('0'), "Promo code has reached maximum uses"

    # Check minimum purchase
    if subtotal < promo.min_purchase_amount:
        return None, Decimal('0'), f"Minimum purchase of ${promo.min_purchase_amount} required"

    # Check user-specific promo
    if promo.user and user and promo.user != user:
        return None, Decimal('0'), "This promo code is not valid for your account"

    # Calculate discount
    discount_amount = Decimal('0')
    if promo.discount_type == 'percentage':
        discount_amount = subtotal * (promo.discount_value / Decimal('100'))
        # Cap at max discount if specified
        if promo.max_discount_amount:
            discount_amount = min(discount_amount, promo.max_discount_amount)
    elif promo.discount_type == 'fixed':
        discount_amount = min(promo.discount_value, subtotal)

    return promo, discount_amount, None


@login_required
def checkout_cart(request):
    """
    Normal cart checkout with promo code support

    GET: Display checkout page
    POST: Process checkout
    """
    try:
        cart = Cart.objects.get(user=request.user)
    except Cart.DoesNotExist:
        messages.error(request, "Your cart is empty.")
        return redirect("marketplace:cart")

    # Get ONLY normal cart items
    cart_items = (
        CartItem.objects.filter(cart=cart, cart_type='normal')
        .select_related('product', 'product__store', 'product__category')
    )

    if not cart_items.exists():
        messages.error(request, "Your normal cart is empty.")
        return redirect("marketplace:cart")

    # Calculate totals
    CART_TAX_RATE = Decimal("0.085")
    subtotal = sum(item.product.price * item.quantity for item in cart_items)

    # GET request - show checkout page
    if request.method == 'GET':
        tax = subtotal * CART_TAX_RATE
        total = subtotal + tax

        context = {
            'cart_items': cart_items,
            'subtotal': subtotal,
            'tax': tax,
            'total': total,
            'cart_type': 'normal',
            'show_promo': True,
        }
        return render(request, 'orders/checkout.html', context)

    # POST request - process checkout
    elif request.method == 'POST':
        # Validate promo code
        promo_code_str = request.POST.get('promo_code', '').strip()
        promo, discount_amount, error = validate_promo_code(promo_code_str, subtotal, request.user)

        if error:
            messages.warning(request, error)

        # Calculate final totals
        tax = subtotal * CART_TAX_RATE
        total = subtotal + tax - discount_amount

        try:
            with transaction.atomic():
                # Create order
                order = Order.objects.create(
                    user=request.user,
                    total_amount=total,
                    subtotal=subtotal,
                    tax_amount=tax,
                    discount_amount=discount_amount,
                    status='pending',
                    payment_status='pending',
                    source='normal_cart',
                    promo_code=promo,
                    notes=request.POST.get('notes', '')
                )

                # Create order items
                for cart_item in cart_items:
                    OrderItem.objects.create(
                        order=order,
                        product=cart_item.product,
                        quantity=cart_item.quantity,
                        price=cart_item.product.price,
                        selected_features=cart_item.selected_features
                    )

                # Update promo usage
                if promo:
                    promo.uses += 1
                    promo.save(update_fields=['uses'])

                # Clear normal cart items
                cart_items.delete()

                # Track analytics
                try:
                    from analytics.services import track_event
                    track_event(
                        session_key=request.session.session_key or request.user.username,
                        event_type="checkout",
                        user=request.user,
                        product=None,
                        path=request.path,
                    )
                except Exception:
                    pass

                messages.success(request, f"Order #{order.id} created successfully!")
                if discount_amount > 0:
                    messages.success(request, f"Promo code applied! You saved ${discount_amount:.2f}")

                return redirect('orders:order_detail', order_id=order.id)

        except Exception as e:
            logger.error(f"Error processing checkout: {str(e)}", exc_info=True)
            messages.error(request, "An error occurred during checkout. Please try again.")
            return redirect("marketplace:cart")


@login_required
def checkout_social_cart(request):
    """
    Checkout view for SOCIAL cart - OWNER ONLY with promo code support.

    GET: Display checkout page
    POST: Process checkout and create individual orders
    """
    try:
        cart = Cart.objects.get(user=request.user)
        social = cart.social
    except (Cart.DoesNotExist, SocialCart.DoesNotExist):
        messages.error(request, "No active social cart found.")
        return redirect("marketplace:cart")

    if not social.is_active:
        messages.error(request, "Social cart is not active.")
        return redirect("marketplace:cart")

    # Verify user is the owner
    if social.owner != request.user:
        messages.error(request, "Only the owner can checkout the social cart.")
        return redirect("marketplace:cart")

    # Get social cart items
    social_items = (
        CartItem.objects.filter(cart=cart, cart_type='social')
        .select_related('product', 'product__store', 'product__category', 'added_by')
    )

    if not social_items.exists():
        messages.error(request, "Social cart is empty.")
        return redirect("marketplace:cart")

    # Calculate totals
    CART_TAX_RATE = Decimal("0.000")
    subtotal = sum(item.product.price * item.quantity for item in social_items)

    # GET request - show checkout page
    if request.method == 'GET':
        tax = subtotal * CART_TAX_RATE
        total = subtotal + tax

        # Group items by member
        items_by_member = {}
        for item in social_items:
            user = item.added_by or social.owner
            if user not in items_by_member:
                items_by_member[user] = {
                    'user': user,
                    'items': [],
                    'subtotal': Decimal('0'),
                }
            items_by_member[user]['items'].append(item)
            items_by_member[user]['subtotal'] += item.product.price * item.quantity

        context = {
            'social': social,
            'social_items': social_items,
            'items_by_member': items_by_member.values(),
            'subtotal': subtotal,
            'tax': tax,
            'total': total,
            'cart_type': 'social',
            'member_count': len(items_by_member),
            'show_promo': True,  # Owner can apply promo to entire social cart
        }
        return render(request, 'orders/checkout_social.html', context)

    # POST request - process checkout
    elif request.method == 'POST':
        # Validate promo code (applies to total cart)
        promo_code_str = request.POST.get('promo_code', '').strip()
        promo, total_discount, error = validate_promo_code(promo_code_str, subtotal, request.user)

        if error:
            messages.warning(request, error)

        try:
            with transaction.atomic():
                # Group items by who added them
                items_by_user = {}
                for item in social_items:
                    user = item.added_by or social.owner
                    if user not in items_by_user:
                        items_by_user[user] = []
                    items_by_user[user].append(item)

                # Create individual orders for each member
                created_orders = {}
                total_user_subtotals = Decimal('0')

                # First pass - calculate each user's subtotal
                user_subtotals = {}
                for user, items in items_by_user.items():
                    user_subtotal = sum(item.product.price * item.quantity for item in items)
                    user_subtotals[user] = user_subtotal
                    total_user_subtotals += user_subtotal

                # Create orders with proportional discount
                for user, items in items_by_user.items():
                    if not items:
                        continue

                    # Calculate this user's subtotal
                    user_subtotal = user_subtotals[user]

                    # Apply proportional discount
                    if total_discount > 0 and total_user_subtotals > 0:
                        proportion = user_subtotal / total_user_subtotals
                        user_discount = total_discount * proportion
                    else:
                        user_discount = Decimal('0')

                    # Calculate user's tax and total
                    user_tax = user_subtotal * CART_TAX_RATE
                    user_total = user_subtotal + user_tax - user_discount

                    # Create order
                    order = Order.objects.create(
                        user=user,
                        total_amount=user_total,
                        subtotal=user_subtotal,
                        tax_amount=user_tax,
                        discount_amount=user_discount,
                        status='pending',
                        payment_status='pending',
                        source='social_cart',
                        promo_code=promo if user == request.user else None,  # Only owner gets promo reference
                        notes=f'Order from Social Cart #{social.id}'
                    )

                    # Create order items
                    for cart_item in items:
                        OrderItem.objects.create(
                            order=order,
                            product=cart_item.product,
                            quantity=cart_item.quantity,
                            price=cart_item.product.price,
                            selected_features=cart_item.selected_features
                        )

                    created_orders[user] = order

                # Update promo usage
                if promo:
                    promo.uses += 1
                    promo.save(update_fields=['uses'])

                # Mark social cart as closed
                social.is_active = False
                social.status = 'closed'
                social.completed_at = timezone.now()
                social.save(update_fields=['is_active', 'status', 'completed_at', 'updated_at'])

                # Delete all social cart items
                social_items.delete()

                # Deactivate all members
                social.members.all().update(status='left')

                # Track analytics
                try:
                    from analytics.services import track_event
                    track_event(
                        session_key=request.session.session_key or request.user.username,
                        event_type="social_cart_checkout",
                        user=request.user,
                        product=None,
                        path=request.path,
                    )
                except:
                    pass

                # Success message
                owner_order = created_orders.get(request.user)
                success_msg = f"Social cart checked out! {len(created_orders)} orders created."
                if total_discount > 0:
                    success_msg += f" Promo code applied! Total savings: ${total_discount:.2f}"

                messages.success(request, success_msg)

                if owner_order:
                    return redirect('orders:order_detail', order_id=owner_order.id)
                else:
                    return redirect('orders:order_history')

        except Exception as e:
            logger.error(f"Error processing social checkout: {str(e)}", exc_info=True)
            messages.error(request, "An error occurred during social cart checkout. Please try again.")
            return redirect("marketplace:cart")


@login_required
def checkout_redirect(request):
    """
    Smart redirect after login - determines checkout type
    """
    try:
        cart = Cart.objects.get(user=request.user)

        # Check for active social cart where user is owner
        try:
            social = cart.social
            if social and social.is_active and social.owner == request.user:
                social_items = CartItem.objects.filter(cart=cart, cart_type='social').exists()
                if social_items:
                    return redirect('orders:checkout_social_cart')
        except SocialCart.DoesNotExist:
            pass

        # Default to normal checkout
        return redirect('orders:checkout_cart')

    except Cart.DoesNotExist:
        messages.error(request, "Your cart is empty.")
        return redirect("marketplace:cart")


# ---------------------------------------------------------
# ✅ QUICK CHECKOUT (BUY NOW)
# ---------------------------------------------------------
@require_http_methods(["POST"])
@csrf_protect
def quick_checkout(request):
    """
    Quick checkout (buy now) - bypasses cart.

    ✅ Analytics: Tracks checkout and paid events for single product
    """
    if not request.user.is_authenticated:
        request.session["checkout_after_login"] = True
        return redirect(f"{reverse('accounts:sign_in')}?next={request.path}")

    product_id = request.POST.get("product")
    quantity = request.POST.get("quantity", 1)

    try:
        quantity = int(quantity)
        if quantity < 1:
            raise ValueError
    except (ValueError, TypeError):
        messages.error(request, "Invalid quantity selected.")
        return redirect("marketplace:all_products")

    product = get_object_or_404(Product.objects.select_related("store"), id=product_id)
    warehouse = getattr(product.store, "warehouse", None)

    # ✅ quick pre-check (real enforcement is inside atomic reduce_stock_for_checkout)
    available = get_available_stock(product=product, warehouse=warehouse)
    if available < quantity:
        messages.error(request, f"Insufficient stock available. Available: {available}")
        return redirect("marketplace:product_detail", product_id=product.id)

    try:
        session_key = request.session.session_key or request.user.username

        # ANALYTICS: Track checkout initiation
        track_event(
            session_key=session_key,
            event_type="checkout",
            user=request.user,
            store=product.store,
            product=product,
            path=request.path,
        )

        with transaction.atomic():
            order = Order.objects.create(
                buyer=request.user,
                promo_code=None,
                discount_amount=Decimal("0"),
            )

            locked_product = Product.objects.select_for_update().select_related("store").get(id=product.id)
            locked_warehouse = getattr(locked_product.store, "warehouse", None)

            reduce_stock_for_checkout(
                product=locked_product,
                quantity=quantity,
                warehouse=locked_warehouse,
                user=request.user,
                reference_prefix=f"ORDER{order.id}",
                notes=f"Quick checkout sale (Order #{order.id})",
            )

            OrderItem.objects.create(
                order=order,
                product=locked_product,
                quantity=quantity,
            )

            # ANALYTICS: Track paid event
            track_event(
                session_key=session_key,
                event_type="paid",
                user=request.user,
                store=product.store,
                product=product,
                order=order,
                path=request.path,
            )

            notify_store_new_order_async(order)

        messages.success(request, "Quick checkout successful!")
        return redirect("orders:order_detail", order_id=order.id)

    except ValidationError as e:
        messages.error(request, f"Checkout failed: {str(e)}")
        return redirect("marketplace:product_detail", product_id=product.id)

    except Exception as e:
        logger.exception("Quick checkout error for user %s: %s", getattr(request.user, "id", None), str(e))
        messages.error(request, "An error occurred during quick checkout.")
        return redirect("marketplace:product_detail", product_id=product.id)

@login_required
def order_detail(request, order_id):
    """Enhanced order_detail view with chat messages"""
    try:
        order = Order.objects.get(id=order_id, buyer=request.user)
    except Order.DoesNotExist:
        return redirect('orders:order_history')

    # Get other orders for sidebar
    other_orders = Order.objects.filter(buyer=request.user).exclude(id=order_id)[:5]

    # Get chat messages for this order
    chat_messages = ChatMessage.objects.filter(order=order).order_by('created_at')

    cod_allowed = True
    if order.get_total > 500:
        cod_allowed = all([
            item.product.store and item.product.store.accept_cash_risk
            for item in order.items.select_related('product__store')
        ])

        # Resolve stores for this order
    store_ids = order.items.values_list('product__store_id', flat=True).distinct()
    if not store_ids or list(store_ids) == [None]:
        seller_ids = order.items.values_list('product__seller_id', flat=True).distinct()
        order_stores = Store.objects.filter(owner_id__in=seller_ids)
    else:
        order_stores = Store.objects.filter(id__in=store_ids)

    context = {
        'order': order,
        'other_orders': other_orders,
        'order_stores': order_stores,
        'chat_messages': chat_messages,
        'cod_allowed': cod_allowed,
    }

    return render(request, 'orders/order_detail.html', context)


def download_invoice_pdf(request, order_id):
    from orders.models import Order

    order = Order.objects.get(id=order_id, buyer=request.user)
    template = get_template('orders/invoice_template.html')  # your template name
    html_content = template.render({
        'order': order,
        'company_name': "EasyMarket",
        'company_address': "Banjul, The Gambia",
        'company_email': "info@easymarket.com",
        'company_phone': "+220 123 4567"
    })

    # Generate PDF
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'filename="Invoice_{order.id}.pdf"'

    # Temp file to write PDF
    with tempfile.NamedTemporaryFile(delete=True) as output:
        HTML(string=html_content).write_pdf(target=output.name)
        output.seek(0)
        response.write(output.read())

    return response

ALLOWED_IMAGE_CT = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
MAX_IMAGE_MB = 5

@login_required
@require_POST
def send_chat_message(request):
    if request.headers.get('x-requested-with') != 'XMLHttpRequest':
        return JsonResponse({'success': False, 'error': 'Invalid request type.'}, status=400)

    order_id = request.POST.get('order_id')
    content = (request.POST.get('message') or '').strip()
    image = request.FILES.get('image')  # keep if you support photos; else remove

    if not order_id:
        return JsonResponse({'success': False, 'error': 'Missing order id'}, status=400)
    if not content and not image:
        return JsonResponse({'success': False, 'error': 'Type a message or attach an image.'}, status=400)

    # --- load order without buyer filter
    try:
        order = Order.objects.get(id=order_id)
    except Order.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Order not found'}, status=404)

    # --- permissions: buyer OR seller tied to this order
    is_buyer = (order.buyer_id == request.user.id)

    # Adjust the relation to match your models:
    # assumes OrderItem has product -> store -> owner
    is_store_actor = order.items.filter(product__store__owner_id=request.user.id).exists()

    # (optionally) allow store staff:
    # is_store_actor = is_store_actor or order.items.filter(product__store__staff__user_id=request.user.id).exists()

    if not (is_buyer or is_store_actor or request.user.is_staff):
        return JsonResponse({'success': False, 'error': 'Forbidden'}, status=403)

    # (optional) validate image type/size if you support photos
    # ...

    msg = ChatMessage.objects.create(order=order, sender=request.user, content=content, image=image if image else None)

    return JsonResponse({
        'success': True,
        'message': {
            'id': msg.id,
            'content': msg.content or '',
            'image_url': msg.image.url if getattr(msg, "image", None) else '',
            'sender': msg.sender.username,
            'created_at': msg.created_at.strftime('%b %d, %Y %H:%M'),
            'is_sender': True
        }
    })

@login_required
def fetch_chat_messages(request, order_id):
    if request.headers.get('x-requested-with') != 'XMLHttpRequest':
        return JsonResponse({'success': False, 'message': 'Invalid request'}, status=400)

    try:
        order = Order.objects.get(id=order_id)
    except Order.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Order not found'}, status=404)

    is_buyer = (order.buyer_id == request.user.id)
    is_store_actor = order.items.filter(product__store__owner_id=request.user.id).exists()
    # (optional) include staff check as above

    if not (is_buyer or is_store_actor or request.user.is_staff):
        return JsonResponse({'success': False, 'message': 'Forbidden'}, status=403)

    msgs = order.chat_messages.select_related('sender').order_by('created_at')
    return JsonResponse({
        'success': True,
        'messages': [{
            'id': m.id,
            'sender_id': m.sender_id,
            'sender_name': m.sender.get_full_name() or m.sender.username,
            'content': m.content,
            'image_url': m.image.url if getattr(m, "image", None) else '',
            'timestamp': m.created_at.strftime('%b %d, %H:%M'),
            'is_self': (m.sender_id == request.user.id),
        } for m in msgs]
    })

@login_required
def order_history(request):
    """Display all orders for the current user"""
    orders = Order.objects.filter(buyer=request.user).order_by('-created_at')

    # Filter by status if provided
    status_filter = request.GET.get('status')
    if status_filter:
        orders = orders.filter(status=status_filter)

    # Search by order ID
    search_query = request.GET.get('search')
    if search_query:
        orders = orders.filter(
            Q(id__icontains=search_query) |
            Q(items__product__name__icontains=search_query)
        ).distinct()

    # Pagination
    paginator = Paginator(orders, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Get order status choices for filter dropdown
    status_choices = Order.STATUS_CHOICES

    context = {
        'page_obj': page_obj,
        'status_choices': status_choices,
        'current_status': status_filter,
        'search_query': search_query,
    }

    return render(request, 'orders/order_history.html', context)


@login_required
def complete_order(request, order_id):
    """Redirect to order detail page for completing pending orders"""
    order = get_object_or_404(Order, id=order_id, buyer=request.user)

    # NEW: Mark wheel spin as redeemed if applicable
    if order.promo_code and order.promo_code.source == 'campaign_wheel':
        wheel_spins = order.promo_code.wheel_spins.all()
        for spin in wheel_spins:
            if not spin.is_redeemed:
                spin.mark_redeemed()

    if order.status != 'pending':
        messages.warning(request, "This order is not in pending status.")

    return redirect('orders:order_detail', order_id=order.id)


@login_required
def track_order(request, order_id):
    """Track order status and delivery"""
    order = get_object_or_404(Order, id=order_id, buyer=request.user)

    # Mock tracking information
    tracking_updates = [
        {
            'date': order.created_at,
            'status': 'Order Placed',
            'description': 'Your order has been placed successfully.',
            'completed': True
        },
        {
            'date': order.payment_date if order.payment_date else None,
            'status': 'Payment Confirmed',
            'description': 'Payment has been processed successfully.',
            'completed': bool(order.payment_date)
        },
        {
            'date': order.shipped_date if hasattr(order, 'shipped_date') else None,
            'status': 'Order Shipped',
            'description': 'Your order has been shipped and is on the way.',
            'completed': order.status in ['shipped', 'delivered']
        },
        {
            'date': order.delivered_date if hasattr(order, 'delivered_date') else None,
            'status': 'Delivered',
            'description': 'Your order has been delivered successfully.',
            'completed': order.status == 'delivered'
        }
    ]

    context = {
        'order': order,
        'tracking_updates': tracking_updates,
    }

    return render(request, 'orders/track_order.html', context)

def track_order_public(request):
    """Public tracking page where anyone can track orders using tracking number"""
    order = None
    tracking_number = None
    error_message = None

    if request.method == 'POST':
        tracking_number = request.POST.get('tracking_number', '').strip()

        if tracking_number:
            try:
                # Include order if status is shipped/delivered or has in_transit shipment
                order = Order.objects.filter(
                    tracking_number__iexact=tracking_number
                ).filter(
                    Q(status__in=['shipped', 'delivered']) |
                    Q(shipments__status='in_transit')
                ).distinct().order_by('-created_at').first()

                if not order:
                    error_message = "No order found with this tracking number. Please check the number and try again."
            except Order.MultipleObjectsReturned:
                order = Order.objects.filter(
                    tracking_number__iexact=tracking_number
                ).filter(
                    Q(status__in=['shipped', 'delivered']) |
                    Q(shipments__status='in_transit')
                ).distinct().order_by('-created_at').first()
        else:
            error_message = "Please enter a tracking number."

    tracking_updates = []
    if order:
        tracking_updates = generate_tracking_timeline(order)

    context = {
        'order': order,
        'tracking_number': tracking_number,
        'error_message': error_message,
        'tracking_updates': tracking_updates,
    }

    return render(request, 'orders/track_order_public.html', context)

def track_order_ajax(request):
    """AJAX endpoint for real-time tracking updates"""
    if request.method == 'GET':
        tracking_number = request.GET.get('tracking_number', '').strip()

        if not tracking_number:
            return JsonResponse({
                'success': False,
                'error': 'Tracking number is required.'
            })

        try:
            order = Order.objects.filter(
                tracking_number__iexact=tracking_number
            ).filter(
                Q(status__in=['shipped', 'delivered']) |
                Q(shipments__status='in_transit')
            ).distinct().order_by('-created_at').first()

            if not order:
                return JsonResponse({
                    'success': False,
                    'error': 'No order found with this tracking number.'
                })

            tracking_updates = generate_tracking_timeline(order)
            shipment_in_transit = order.shipments.filter(status='in_transit').exists()

            return JsonResponse({
                'success': True,
                'order': {
                    'id': order.id,
                    'status': 'In Transit' if shipment_in_transit else order.get_status_display(),
                    'status_code': 'in_transit' if shipment_in_transit else order.status,
                    'created_at': order.created_at.strftime('%B %d, %Y'),
                    'expected_delivery': order.expected_delivery_date.strftime('%B %d, %Y') if order.expected_delivery_date else None,
                    'total': float(order.get_total),
                    'item_count': order.get_item_count(),
                },
                'tracking_updates': tracking_updates,
                'shipping_address': {
                    'full_name': getattr(order.shipping_address, 'full_name', ''),
                    'street': getattr(order.shipping_address, 'street', ''),
                    'city': getattr(order.shipping_address, 'city', ''),
                    'region': getattr(order.shipping_address, 'region', ''),
                    'geo_code': getattr(order.shipping_address, 'geo_code', ''),
                } if order.shipping_address else None
            })

        except Order.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'No order found with this tracking number.'
            })

    return JsonResponse({
        'success': False,
        'error': 'Invalid request method.'
    })



from datetime import timedelta

def generate_tracking_timeline(order):
    """Generate tracking timeline for an order"""
    timeline = []

    # Order Placed
    timeline.append({
        'title': 'Order Placed',
        'description': 'Your order has been received and is being prepared.',
        'date': order.created_at,
        'completed': True,
        'icon': 'fas fa-shopping-cart',
        'color': 'success'
    })

    # Payment Confirmed
    payment_date = None
    if hasattr(order, 'payment') and order.payment and getattr(order.payment, 'payment_date', None):
        payment_date = order.payment.payment_date
        timeline.append({
            'title': 'Payment Confirmed',
            'description': 'Payment has been processed successfully.',
            'date': payment_date,
            'completed': True,
            'icon': 'fas fa-credit-card',
            'color': 'success'
        })

    # Order Processing
    processing_date = payment_date or (order.created_at + timedelta(hours=2))
    timeline.append({
        'title': 'Order Processing',
        'description': 'Your order is being prepared for shipment.',
        'date': processing_date,
        'completed': order.status in ['shipped', 'in_transit', 'delivered'],
        'icon': 'fas fa-cogs',
        'color': 'success' if order.status in ['shipped', 'in_transit', 'delivered'] else 'warning'
    })

    # Shipped
    if order.shipped_date:
        timeline.append({
            'title': 'Shipped',
            'description': 'Your order has been shipped via our delivery partner.',
            'date': order.shipped_date,
            'completed': order.status in ['shipped', 'delivered'],
            'icon': 'fas fa-truck',
            'color': 'success' if order.status in ['in_transit', 'delivered'] else 'warning'
        })

    # In Transit
    shipment = order.shipments.filter(status='in_transit').order_by('-created_at').first()
    if shipment:
        timeline.append({
            'title': 'In Transit',
            'description': 'Your package is on its way through our logistics network and may arrive today.',
            'date': shipment.collect_time,
            'completed': order.status == 'delivered',
            'icon': 'fas fa-route',
            'color': 'success' if order.status == 'delivered' else 'primary'
        })

    # Out for Delivery
    if order.status == 'delivered' and order.delivered_date:
        out_for_delivery_date = order.delivered_date.replace(hour=8, minute=0)
        timeline.append({
            'title': 'Out for Delivery',
            'description': 'Your package is out for delivery and will arrive today.',
            'date': out_for_delivery_date,
            'completed': True,
            'icon': 'fas fa-shipping-fast',
            'color': 'success'
        })

    # Delivered
    if order.status == 'delivered' and order.delivered_date:
        timeline.append({
            'title': 'Delivered',
            'description': 'Your order has been delivered successfully.',
            'date': order.delivered_date,
            'completed': True,
            'icon': 'fas fa-check-circle',
            'color': 'success'
        })
    elif order.expected_delivery_date:
        timeline.append({
            'title': 'Expected Delivery',
            'description': 'Estimated delivery date.',
            'date': order.expected_delivery_date,
            'completed': False,
            'icon': 'fas fa-calendar-check',
            'color': 'info'
        })

    return timeline

# Add this to generate tracking numbers for existing orders
def generate_tracking_number(order):
    """Generate a tracking number for an order"""
    import random
    import string

    # Format: EM + 8 random uppercase letters and numbers
    prefix = "EM"
    suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    return f"{prefix}{suffix}"

@login_required
def reorder_items(request, order_id):
    """Add items from a previous order to cart"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'})

    order = get_object_or_404(Order, id=order_id, buyer=request.user)

    try:
        # Get or create cart
        cart, created = Cart.objects.get_or_create(user=request.user)

        # Add order items to cart
        items_added = 0
        for order_item in order.items.all():
            cart_item, created = CartItem.objects.get_or_create(
                cart=cart,
                product=order_item.product,
                defaults={'quantity': order_item.quantity}
            )

            if not created:
                cart_item.quantity += order_item.quantity
                cart_item.save()

            items_added += 1

        return JsonResponse({
            'success': True,
            'message': f'{items_added} items added to your cart successfully'
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
@require_POST
def cancel_order(request, order_id):
    order = get_object_or_404(Order, id=order_id, buyer=request.user)

    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"

    if order.status not in ["pending", "processing"]:
        msg = "Only pending or processing orders can be cancelled."
        if is_ajax:
            return JsonResponse({"success": False, "error": msg}, status=400)
        messages.error(request, msg)
        return redirect("orders:order_detail", order_id=order.id)

    try:
        with transaction.atomic():
            # Optional: lock order row to avoid double-cancel from multiple clicks
            order = Order.objects.select_for_update().get(id=order.id)

            # Restore stock for each item
            for item in order.items.select_related("product", "product__store").all():
                product = item.product
                qty = int(item.quantity or 0)

                if qty <= 0:
                    continue

                warehouse = getattr(product.store, "warehouse", None)
                if not warehouse:
                    raise ValidationError(
                        f"Store '{product.store.name}' has no warehouse configured. Cannot restore stock."
                    )

                stock_row, _ = Stock.objects.select_for_update().get_or_create(
                    product=product,
                    warehouse=warehouse,
                    defaults={
                        "quantity": 0,
                        "unit_cost": Decimal("0.00"),
                    },
                )

                # Add back the cancelled quantity
                stock_row.quantity = int(stock_row.quantity or 0) + qty
                stock_row.save(update_fields=["quantity", "updated_at"])

                # ✅ Create movement record (stock IN)
                StockMovement.objects.create(
                    product=product,
                    warehouse=warehouse,
                    movement_type="RETURN_IN",  # you can also use "ADJUSTMENT" if you prefer
                    quantity=qty,  # positive because stock is coming back
                    reference_number=f"CANCEL-{order.id}-{product.id}-{int(timezone.now().timestamp())}",
                    unit_cost=stock_row.unit_cost,
                    notes=f"Order #{order.id} cancelled — stock restored (+{qty}).",
                    created_by=request.user,
                )

            order.status = "cancelled"
            order.save(update_fields=["status", "updated_at"] if hasattr(order, "updated_at") else ["status"])

        if is_ajax:
            return JsonResponse({"success": True})

        messages.success(request, "Order cancelled successfully and stock was restored.")
        return redirect("orders:order_detail", order_id=order.id)

    except ValidationError as e:
        if is_ajax:
            return JsonResponse({"success": False, "error": str(e)}, status=400)
        messages.error(request, str(e))
        return redirect("orders:order_detail", order_id=order.id)

    except Exception as e:
        if is_ajax:
            return JsonResponse({"success": False, "error": str(e)}, status=500)

        messages.error(request, f"Error cancelling order: {str(e)}")
        return redirect("orders:order_detail", order_id=order.id)

@login_required
def order_invoice(request, order_id):
    """Generate and display order invoice"""
    order = get_object_or_404(Order, id=order_id, buyer=request.user)
    qr_code = generate_invoice_qr_code(order)

    context = {
        'order': order,
        'invoice_qr_code': qr_code,
        'company_name': 'EasyMarket',
        'company_address': 'Banjul, The Gambia',
        'company_email': 'info@easymarket.com',
        'company_phone': ' +220 123 4567',
    }

    return render(request, 'orders/order_invoice.html', context)

def q2(x):
    """Quantize to 2dp Decimal safely."""
    if x is None:
        x = Decimal('0')
    if not isinstance(x, Decimal):
        x = Decimal(str(x))
    return x.quantize(Decimal('0.01'))

@login_required
def store_order_invoice(request, store_id, order_id):
    """Generate invoice for a store owner – only their items, with clear discount breakdown."""
    store = get_object_or_404(Store, id=store_id, owner=request.user)
    order = get_object_or_404(Order, id=order_id)

    # Items for THIS store only
    store_items = (
        order.items
        .filter(product__seller=store.owner)
        .select_related('product')
    )
    if not store_items.exists():
        return render(request, 'orders/access_denied.html', {
            'message': "You do not have any products in this order."
        })

    # All order items (needed to apportion order-level discount/shipping fairly)
    all_items = order.items.select_related('product')

    # --- Helpers to read prices/discounts whether or not helpers exist on the model ---
    def unit_base_price(item: "OrderItem") -> Decimal:
        # Prefer helper if available (from previous step)
        if hasattr(item, 'base_unit_price'):
            return q2(item.base_unit_price)
        base = item.price_at_time if item.price_at_time is not None else item.product.price
        return q2(base)

    def unit_discount(item: "OrderItem") -> Decimal:
        # Prefer helper if available (from previous step)
        if hasattr(item, 'get_unit_discount_amount'):
            return q2(item.get_unit_discount_amount())
        # No per-item discount fields? assume 0
        return Decimal('0.00')

    def line_total_discounted(item: "OrderItem") -> Decimal:
        # Prefer helper if available (from previous step)
        if hasattr(item, 'get_total_price'):
            return q2(item.get_total_price())
        # Else compute: (base - per_unit_discount) * qty
        return q2((unit_base_price(item) - unit_discount(item)) * item.quantity)

    # --- Build store-level and order-level sums ---
    base_subtotal_store = Decimal('0.00')        # BEFORE discounts
    item_discount_total_store = Decimal('0.00')  # per-unit discount * qty
    discounted_subtotal_store = Decimal('0.00')  # AFTER item discounts

    for it in store_items:
        up = unit_base_price(it)
        ud = unit_discount(it)
        qty = it.quantity

        base_subtotal_store += (up * qty)
        item_discount_total_store += (ud * qty)
        discounted_subtotal_store += line_total_discounted(it)

    base_subtotal_store = q2(base_subtotal_store)
    item_discount_total_store = q2(item_discount_total_store)
    discounted_subtotal_store = q2(discounted_subtotal_store)

    # Totals for ALL items (to apportion order-level discount/shipping)
    discounted_subtotal_all = Decimal('0.00')
    for it in all_items:
        discounted_subtotal_all += line_total_discounted(it)
    discounted_subtotal_all = q2(discounted_subtotal_all)

    # --- Order-level discount & shipping apportionment (proportional by discounted value) ---
    order_level_discount = q2(getattr(order, 'discount_amount', 0) or 0)
    order_shipping_cost = q2(getattr(order, 'shipping_cost', 0) or 0)

    # Avoid division by zero
    if discounted_subtotal_all > 0:
        store_share_ratio = (discounted_subtotal_store / discounted_subtotal_all)
    else:
        store_share_ratio = Decimal('0.00')

    # Share of order-level discount for this store:
    store_order_discount_share = q2(order_level_discount * store_share_ratio)

    # Share (optional) of shipping; set to 0 if you don't want to split
    # To keep your previous behavior (full shipping on store invoice), comment the next line
    store_shipping_share = q2(order_shipping_cost * store_share_ratio)
    # Or force 0 to avoid splitting:
    # store_shipping_share = Decimal('0.00')

    # --- Tax ---
    tax_rate = q2(getattr(order, 'tax_rate', 0) or 0)  # e.g., 15 means 15%
    # Taxable base: discounted subtotal AFTER store's share of order-level discount
    taxable_base = discounted_subtotal_store - store_order_discount_share
    if taxable_base < 0:
        taxable_base = Decimal('0.00')

    tax_amount = q2(taxable_base * (tax_rate / Decimal('100')))

    # --- Final totals to show on invoice (for THIS store) ---
    # 'subtotal'   -> original sum before discounts (for clarity)
    # 'discount'   -> item discounts + store share of order-level discount
    # 'shipping'   -> store share (or 0 / full, per your policy)
    # 'total'      -> (taxable_base + tax + shipping)
    subtotal = base_subtotal_store
    discount = q2(item_discount_total_store + store_order_discount_share)
    shipping = store_shipping_share
    total = q2(taxable_base + tax_amount + shipping)

    # QR, company header (keep your own helpers)
    qr_code = generate_invoice_qr_code(order)

    context = {
        'store': store,
        'order': order,
        'order_items': store_items,

        'invoice_qr_code': qr_code,
        'company_name': store.name or 'EasyMarket',
        # You may want a more robust address builder; this mirrors your original line
        'company_address': store.address_line_1 and store.address_line_2 or store.address_line_1,
        'company_email': store.email,
        'company_phone': store.phone,

        # Numbers used by the template
        'subtotal': subtotal,          # before discounts
        'discount': discount,          # items + store share of order-level discount
        'shipping': shipping,          # allocated shipping
        'tax_amount': tax_amount,      # tax on net
        'total': total,                # grand total for this store
    }

    return render(request, 'stores/store_order_invoice.html', context)
@login_required
def update_order_status(request, order_id):
    """Update order status (for admin/seller use)"""
    if not request.user.is_staff:
        messages.error(request, "You don't have permission to update order status.")
        return redirect('orders:order_detail', order_id=order_id)

    order = get_object_or_404(Order, id=order_id)

    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status in dict(Order.STATUS_CHOICES):
            order.status = new_status

            # Set timestamps based on status
            if new_status == 'shipped' and not hasattr(order, 'shipped_date'):
                order.shipped_date = timezone.now()
            elif new_status == 'delivered' and not hasattr(order, 'delivered_date'):
                order.delivered_date = timezone.now()

            order.save()
            messages.success(request, f"Order status updated to {order.get_status_display()}")
        else:
            messages.error(request, "Invalid status selected.")

    return redirect('orders:order_detail', order_id=order.id)


@login_required
@require_POST
def update_item_discount(request, item_id):
    item = get_object_or_404(OrderItem, pk=item_id)

    # Only the seller who owns this store can modify
    if getattr(item.product.store, "owner_id", None) != request.user.id:
        return HttpResponseForbidden("Not allowed.")

    # Prevent editing after shipment
    if item.order.status in ("shipped", "delivered"):
        return JsonResponse({"success": False, "message": "Cannot change discount after shipping."}, status=400)

    d_type = request.POST.get("discount_type", "none")
    d_value_raw = request.POST.get("discount_value", "0")

    if d_type not in ("none", "percent", "amount"):
        return JsonResponse({"success": False, "message": "Invalid discount type."}, status=400)

    try:
        d_value = Decimal(d_value_raw or "0")
    except InvalidOperation:
        return JsonResponse({"success": False, "message": "Invalid discount value."}, status=400)

    if d_type == "percent":
        if d_value < 0 or d_value > 100:
            return JsonResponse({"success": False, "message": "Percent must be between 0 and 100."}, status=400)
    elif d_type == "amount":
        if d_value < 0:
            return JsonResponse({"success": False, "message": "Amount cannot be negative."}, status=400)

    item.discount_type = d_type
    item.discount_value = d_value
    item.save()

    return JsonResponse({
        "success": True,
        "discounted_unit_price": f"{item.discounted_unit_price:.2f}",
        "line_total": f"{item.get_total_price():.2f}",
    })


@login_required
def order_stats(request):
    """Display order statistics for the user"""
    orders = Order.objects.filter(buyer=request.user)

    stats = {
        'total_orders': orders.count(),
        'pending_orders': orders.filter(status='pending').count(),
        'processing_orders': orders.filter(status='processing').count(),
        'shipped_orders': orders.filter(status='shipped').count(),
        'delivered_orders': orders.filter(status='delivered').count(),
        'cancelled_orders': orders.filter(status='cancelled').count(),
        'total_spent': sum(order.get_total for order in orders if order.status != 'cancelled'),
        'recent_orders': orders.order_by('-created_at')[:5]
    }

    return render(request, 'orders/order_stats.html', {'stats': stats})

@login_required
@require_http_methods(["GET"])
def pending_orders_count_api(request):
    """API endpoint to get pending orders count for the current user"""
    try:
        pending_count = request.user.orders.filter(status='pending').count()
        return JsonResponse({
            'count': pending_count,
            'success': True
        })
    except Exception as e:
        return JsonResponse({
            'count': 0,
            'success': False,
            'error': str(e)
        })


@require_POST
@csrf_protect
@login_required
def validate_promo(request):
    """
    AJAX endpoint to validate promo codes before checkout
    """
    promo_code_str = request.POST.get('promo_code', '').strip()

    if not promo_code_str:
        return JsonResponse({
            'success': False,
            'message': 'Please enter a promo code'
        })

    try:
        promo = PromoCode.objects.get(code__iexact=promo_code_str, is_active=True)

        if not promo.is_valid():
            return JsonResponse({
                'success': False,
                'message': 'Promo code is invalid or expired'
            })

        return JsonResponse({
            'success': True,
            'message': 'Promo code is valid',
            'discount_percentage': float(promo.discount_percentage),
            'promo_code': promo.code
        })

    except PromoCode.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Promo code not found'
        })

@login_required
def copy_order_to_cart(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    cart, _ = Cart.objects.get_or_create(user=request.user)

    for item in order.items.all():
        CartItem.objects.update_or_create(
            cart=cart,
            product=item.product,
            defaults={
                'quantity': item.quantity,
                'selected_features': item.selected_features if hasattr(item, 'selected_features') else {}
            }
        )

    messages.success(request, "Order copied to cart.")
    return redirect('marketplace:cart_view')


@require_POST
@login_required
def apply_promo_code(request):
    """
    Apply a promo code to the user's cart.
    Enhanced to handle campaign wheel prizes.
    """
    promo_code_str = request.POST.get('promo_code', '').strip().upper()

    if not promo_code_str:
        return JsonResponse({
            'success': False,
            'error': 'Please enter a promo code.'
        }, status=400)

    try:
        # Get the promo code
        promo = PromoCode.objects.select_related('campaign', 'wheel_spin').get(
            code__iexact=promo_code_str
        )

        # Get user's cart
        cart = Cart.objects.filter(user=request.user).first()
        if not cart:
            return JsonResponse({
                'success': False,
                'error': 'Your cart is empty.'
            }, status=400)

        # Calculate cart total
        cart_items = CartItem.objects.filter(cart=cart).select_related('product')
        cart_total = sum(
            item.product.price * item.quantity
            for item in cart_items
        )
        cart_total = Decimal(str(cart_total))

        # Validate promo code
        is_valid, error_message = promo.is_valid(
            user=request.user,
            cart_total=cart_total
        )

        if not is_valid:
            return JsonResponse({
                'success': False,
                'error': error_message
            }, status=400)

        # Special handling for wheel prizes
        if promo.source == 'campaign_wheel':
            # Verify wheel spin ownership
            if hasattr(promo, 'wheel_spin') and promo.wheel_spin:
                wheel_spin = promo.wheel_spin

                # Check if this wheel spin belongs to the current user
                if wheel_spin.user and wheel_spin.user != request.user:
                    return JsonResponse({
                        'success': False,
                        'error': 'This wheel prize belongs to another user.'
                    }, status=403)

                # Check if already redeemed
                if wheel_spin.is_redeemed:
                    return JsonResponse({
                        'success': False,
                        'error': 'This wheel prize has already been used.'
                    }, status=400)

        # Calculate discount
        shipping_cost = Decimal('0')  # Get from your shipping calculation
        discount_info = promo.calculate_discount(cart_total, shipping_cost)

        # Store promo code in session
        request.session['applied_promo_code'] = {
            'code': promo.code,
            'cart_discount': str(discount_info['cart_discount']),
            'shipping_discount': str(discount_info['shipping_discount']),
            'total_discount': str(discount_info['total_discount']),
            'is_wheel_prize': promo.source == 'campaign_wheel',
        }

        return JsonResponse({
            'success': True,
            'promo_code': promo.code,
            'discount_type': promo.get_discount_type_display(),
            'cart_discount': float(discount_info['cart_discount']),
            'shipping_discount': float(discount_info['shipping_discount']),
            'total_discount': float(discount_info['total_discount']),
            'final_cart_total': float(discount_info['final_cart_total']),
            'final_shipping_cost': float(discount_info['final_shipping_cost']),
            'message': f'✅ {promo.description or "Promo code applied successfully!"}',
            'is_wheel_prize': promo.source == 'campaign_wheel',
        })

    except PromoCode.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Invalid promo code. Please check and try again.'
        }, status=404)

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': 'An error occurred while applying the promo code.'
        }, status=500)


@require_POST
@login_required
def remove_promo_code(request):
    """Remove applied promo code from session"""
    if 'applied_promo_code' in request.session:
        del request.session['applied_promo_code']

    return JsonResponse({
        'success': True,
        'message': 'Promo code removed.'
    })


@transaction.atomic
@login_required
def create_order_from_cart(request):
    """
    Create an order from cart with promo code application.
    Enhanced to handle wheel prize redemption.
    """
    cart = Cart.objects.filter(user=request.user).first()
    if not cart:
        return JsonResponse({
            'success': False,
            'error': 'Your cart is empty.'
        }, status=400)

    cart_items = CartItem.objects.filter(cart=cart).select_related('product')
    if not cart_items.exists():
        return JsonResponse({
            'success': False,
            'error': 'Your cart is empty.'
        }, status=400)

    # Calculate totals
    subtotal = sum(item.product.price * item.quantity for item in cart_items)
    shipping_cost = Decimal('0')  # Calculate shipping

    # Apply promo code if exists
    promo_code = None
    cart_discount = Decimal('0')
    shipping_discount = Decimal('0')

    promo_data = request.session.get('applied_promo_code')
    if promo_data:
        try:
            promo_code = PromoCode.objects.get(code=promo_data['code'])

            # Revalidate promo code
            is_valid, error_message = promo_code.is_valid(
                user=request.user,
                cart_total=subtotal
            )

            if is_valid:
                discount_info = promo_code.calculate_discount(subtotal, shipping_cost)
                cart_discount = discount_info['cart_discount']
                shipping_discount = discount_info['shipping_discount']
            else:
                # Promo code no longer valid
                del request.session['applied_promo_code']
                promo_code = None

        except PromoCode.DoesNotExist:
            del request.session['applied_promo_code']
            promo_code = None

    # Calculate final total
    total_discount = cart_discount + shipping_discount
    final_total = subtotal + shipping_cost - total_discount

    # Create order
    order = Order.objects.create(
        user=request.user,
        subtotal=subtotal,
        shipping_cost=shipping_cost,
        discount_amount=total_discount,
        total=final_total,
        promo_code=promo_code,
        status='pending',
    )

    # Create order items
    for cart_item in cart_items:
        OrderItem.objects.create(
            order=order,
            product=cart_item.product,
            quantity=cart_item.quantity,
            price=cart_item.product.price,
        )

    # If promo code was used, increment usage
    if promo_code:
        promo_code.increment_usage()

        # Mark wheel spin as redeemed if applicable
        if promo_code.source == 'campaign_wheel':
            if hasattr(promo_code, 'wheel_spin') and promo_code.wheel_spin:
                promo_code.wheel_spin.mark_redeemed(order=order)

    # Clear cart and session
    cart_items.delete()
    if 'applied_promo_code' in request.session:
        del request.session['applied_promo_code']

    return JsonResponse({
        'success': True,
        'order_id': order.id,
        'order_number': order.order_number if hasattr(order, 'order_number') else str(order.id),
        'total': float(final_total),
        'message': 'Order created successfully!',
    })


# ==============================================================================
# Admin view to check wheel prize usage
# ==============================================================================

@login_required
def admin_wheel_prize_stats(request):
    """
    Admin view to see wheel prize statistics.
    Requires staff permission.
    """
    if not request.user.is_staff:
        return JsonResponse({
            'error': 'Permission denied'
        }, status=403)

    from marketplace.models import WheelSpin, Campaign

    # Get campaign stats
    campaigns = Campaign.objects.filter(enable_wheel=True)

    stats = []
    for campaign in campaigns:
        wheel_spins = WheelSpin.objects.filter(campaign=campaign)

        total_spins = wheel_spins.count()
        redeemed_spins = wheel_spins.filter(is_redeemed=True).count()
        unredeemed_spins = total_spins - redeemed_spins

        # Prize breakdown
        prize_stats = {}
        for spin in wheel_spins:
            prize_name = spin.prize_won
            if prize_name not in prize_stats:
                prize_stats[prize_name] = {
                    'count': 0,
                    'redeemed': 0,
                    'value': float(spin.prize_value)
                }
            prize_stats[prize_name]['count'] += 1
            if spin.is_redeemed:
                prize_stats[prize_name]['redeemed'] += 1

        stats.append({
            'campaign': campaign.name,
            'campaign_slug': campaign.slug,
            'total_spins': total_spins,
            'redeemed': redeemed_spins,
            'unredeemed': unredeemed_spins,
            'redemption_rate': (redeemed_spins / total_spins * 100) if total_spins > 0 else 0,
            'prizes': prize_stats,
        })

    return JsonResponse({
        'success': True,
        'stats': stats,
    })


# ==============================================================================
# User view to see their wheel prizes
# ==============================================================================

@login_required
def my_wheel_prizes(request):
    """View user's wheel prizes and their status"""
    from marketplace.models import WheelSpin

    wheel_spins = WheelSpin.objects.filter(
        user=request.user
    ).select_related('campaign', 'promo_code', 'order').order_by('-spun_at')

    prizes = []
    for spin in wheel_spins:
        prize_data = {
            'campaign': spin.campaign.name,
            'prize': spin.prize_won,
            'spun_at': spin.spun_at.isoformat(),
            'is_redeemed': spin.is_redeemed,
            'promo_code': spin.code_string,
            'can_use': spin.can_be_used(),
        }

        if spin.is_redeemed and spin.redeemed_at:
            prize_data['redeemed_at'] = spin.redeemed_at.isoformat()
            if spin.order:
                prize_data['order_number'] = getattr(spin.order, 'order_number', str(spin.order.id))

        if spin.promo_code:
            prize_data['expires_at'] = spin.promo_code.valid_until.isoformat() if spin.promo_code.valid_until else None
            prize_data['days_left'] = spin.promo_code.days_until_expiry

        prizes.append(prize_data)

    return render(request, 'orders/my_wheel_prizes.html', {
        'prizes': prizes,
        'total_prizes': len(prizes),
        'active_prizes': len([p for p in prizes if p['can_use']]),
    })