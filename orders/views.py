from django.shortcuts import redirect, render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q, Sum
from django.core.paginator import Paginator
from django.utils import timezone
from datetime import timedelta
from stock.utils import reduce_stock
from stock.models import Stock
from stores.models import Store
from .models import Order, OrderItem, PromoCode, ChatMessage
from marketplace.models import Cart, CartItem, Product
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


@require_http_methods(["POST"])
@csrf_protect
def checkout_cart(request):
    if not request.user.is_authenticated:
        request.session['checkout_after_login'] = True
        return redirect(f"{reverse('accounts:sign_in')}?next={reverse('orders:checkout_redirect')}")

        # migrate and proceed
    from marketplace.utils import migrate_session_cart_to_user
    migrate_session_cart_to_user(request, request.user)

    promo_code_str = request.POST.get('promo_code', '').strip()
    promo = None
    discount_amount = Decimal('0')

    try:
        cart = Cart.objects.get(user=request.user)
        cart_items = CartItem.objects.filter(cart=cart).select_related('product')

        if not cart_items.exists():
            messages.error(request, "Your cart is empty.")
            return redirect('marketplace:cart_view')

        subtotal = Decimal('0')
        eligible_discount = Decimal('0')

        # Handle Promo Code
        if promo_code_str:
            try:
                promo = PromoCode.objects.get(code__iexact=promo_code_str, is_active=True)
                if not promo.is_valid():
                    messages.error(request, "Promo code is invalid or expired.")
                    return redirect('marketplace:cart_view')
            except PromoCode.DoesNotExist:
                messages.error(request, "Promo code not found.")
                return redirect('marketplace:cart_view')

        for item in cart_items:
            line_total = item.product.price * item.quantity
            subtotal += line_total

            if promo and promo.applies_to_product(item.product):
                eligible_discount += (line_total * Decimal(promo.discount_percentage)) / 100

        discount_amount = eligible_discount

        # Create Order
        with transaction.atomic():
            order = Order.objects.create(
                buyer=request.user,
                promo_code=promo,
                discount_amount=discount_amount
            )

            for item in cart_items:
                product = item.product.__class__.objects.select_for_update().get(id=item.product.id)
                reduce_stock(product, item.quantity)
                OrderItem.objects.create(
                    order=order,
                    product=product,
                    quantity=item.quantity,
                    selected_features=item.selected_features
                )

            cart_items.delete()
            if promo:
                promo.increment_usage()

            notify_store_new_order_async(order)

            messages.success(request, "Order placed successfully!")
            return redirect('orders:order_detail', order_id=order.id)

    except Cart.DoesNotExist:
        messages.error(request, "You don't have any cart to checkout.")
        return redirect('marketplace:cart_view')

    except ValidationError as e:
        messages.error(request, f"Failed to checkout: {str(e)}")
        return redirect('marketplace:cart_view')

    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Checkout error for user {request.user.id}: {str(e)}")
        messages.error(request, "An error occurred during checkout. Please try again.")
        return redirect('marketplace:cart_view')

@require_http_methods(["POST"])
@csrf_protect
@login_required
def quick_checkout(request):
    product_id = request.POST.get('product')
    quantity = request.POST.get('quantity', 1)

    try:
        quantity = int(quantity)
        if quantity < 1:
            raise ValueError
    except (ValueError, TypeError):
        messages.error(request, "Invalid quantity selected.")
        return redirect('marketplace:all_products')

    product = get_object_or_404(Product, id=product_id)

    if product.stock.quantity < quantity:
        messages.error(request, "Insufficient stock available.")
        return redirect('marketplace:product_detail', product_id=product.id)

    try:
        with transaction.atomic():
            order = Order.objects.create(
                buyer=request.user,
                promo_code=None,
                discount_amount=Decimal('0')
            )

            # Lock product to avoid race conditions
            locked_product = Product.objects.select_for_update().get(id=product.id)
            reduce_stock(locked_product, quantity)

            OrderItem.objects.create(
                order=order,
                product=locked_product,
                quantity=quantity
            )

            notify_store_new_order_async(order)

            messages.success(request, "Quick checkout successful!")
            return redirect('orders:order_detail', order_id=order.id)

    except ValidationError as e:
        messages.error(request, f"Checkout failed: {str(e)}")
        return redirect('marketplace:product_detail', product_id=product.id)
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Quick checkout error for user {request.user.id}: {str(e)}")

        messages.error(request, "An error occurred during quick checkout.")
        return redirect('marketplace:product_detail', product_id=product.id)

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

    # Detect AJAX request
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'

    if order.status not in ['pending', 'processing']:
        if is_ajax:
            return JsonResponse({'success': False, 'error': "Only pending or processing orders can be cancelled."})

        messages.error(request, "Only pending or processing orders can be cancelled.")
        return redirect('orders:order_detail', order_id=order.id)

    try:
        for item in order.items.all():
            try:
                stock = item.product.stock  # Only works if OneToOneField
            except Stock.DoesNotExist:
                stock = Stock.objects.create(product=item.product, quantity=0)

            stock.quantity += item.quantity
            stock.save()

        order.status = 'cancelled'
        order.save()

        if is_ajax:
            return JsonResponse({'success': True})

        messages.success(request, "Order cancelled successfully.")
        return redirect('orders:order_detail', order_id=order.id)

    except Exception as e:
        if is_ajax:
            return JsonResponse({'success': False, 'error': str(e)})

        messages.error(request, f"Error cancelling order: {str(e)}")
        return redirect('orders:order_detail', order_id=order.id)

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

login_required
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