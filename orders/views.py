from django.shortcuts import redirect, render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q
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
from decimal import Decimal
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

    context = {
        'order': order,
        'other_orders': other_orders,
        'chat_messages': chat_messages,
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

@login_required
@require_POST
def send_chat_message(request):
    """Handle AJAX chat message sending"""
    try:
        # Get form data
        order_id = request.POST.get('order_id')
        message_content = request.POST.get('message', '').strip()

        if not order_id or not message_content:
            return JsonResponse({
                'success': False,
                'error': 'Missing required data'
            })

        # Verify order belongs to user
        try:
            order = Order.objects.get(id=order_id, buyer=request.user)
        except Order.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Order not found'
            })

        # Create the chat message
        chat_message = ChatMessage.objects.create(
            order=order,
            sender=request.user,
            content=message_content
        )

        return JsonResponse({
            'success': True,
            'message': {
                'id': chat_message.id,
                'content': chat_message.content,
                'sender': chat_message.sender.username,
                'created_at': chat_message.created_at.strftime('%b %d, %Y %H:%M'),
                'is_sender': True
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
def fetch_chat_messages(request, order_id):
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        try:
            order = Order.objects.get(id=order_id)
            messages = order.chat_messages.select_related('sender').order_by('created_at')

            return JsonResponse({
                'success': True,
                'messages': [
                    {
                        'id': msg.id,
                        'sender_id': msg.sender.id,
                        'sender_name': msg.sender.get_full_name() or msg.sender.username,
                        'content': msg.content,
                        'timestamp': msg.created_at.strftime('%b %d, %H:%M'),
                        'is_self': msg.sender == request.user,
                    }
                    for msg in messages
                ]
            })
        except Order.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Order not found'})
    return JsonResponse({'success': False, 'message': 'Invalid request'})

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
                # Search for order by tracking number
                order = Order.objects.get(
                    tracking_number__iexact=tracking_number,
                    status__in=['shipped', 'delivered']  # Only allow tracking for shipped/delivered orders
                )
            except Order.DoesNotExist:
                error_message = "No order found with this tracking number. Please check the number and try again."
            except Order.MultipleObjectsReturned:
                # In case of duplicates, get the most recent one
                order = Order.objects.filter(
                    tracking_number__iexact=tracking_number,
                    status__in=['shipped', 'delivered']
                ).order_by('-created_at').first()
        else:
            error_message = "Please enter a tracking number."

    # Generate tracking timeline if order found
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
                'error': 'Tracking number is required'
            })

        try:
            order = Order.objects.get(
                tracking_number__iexact=tracking_number,
                status__in=['shipped', 'delivered']
            )

            tracking_updates = generate_tracking_timeline(order)

            return JsonResponse({
                'success': True,
                'order': {
                    'id': order.id,
                    'status': order.get_status_display(),
                    'status_code': order.status,
                    'created_at': order.created_at.strftime('%B %d, %Y'),
                    'expected_delivery': order.expected_delivery_date.strftime(
                        '%B %d, %Y') if order.expected_delivery_date else None,
                    'total': float(order.get_total),
                    'item_count': order.get_item_count(),
                },
                'tracking_updates': tracking_updates,
                'shipping_address': {
                    'full_name': order.shipping_address.full_name if order.shipping_address else '',
                    'street': order.shipping_address.street if order.shipping_address else '',
                    'city': order.shipping_address.city if order.shipping_address else '',
                    'state': order.shipping_address.region if order.shipping_address else '',
                    'zip_code': order.shipping_address.geo_code if order.shipping_address else '',
                } if order.shipping_address else None
            })

        except Order.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'No order found with this tracking number'
            })

    return JsonResponse({'success': False, 'error': 'Invalid request method'})


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
        'completed': order.status in ['shipped', 'delivered'],
        'icon': 'fas fa-cogs',
        'color': 'success' if order.status in ['shipped', 'delivered'] else 'warning'
    })

    # Shipped
    if order.shipped_date:
        timeline.append({
            'title': 'Shipped',
            'description': 'Your order has been shipped via our delivery partner.',
            'date': order.shipped_date,
            'completed': True,
            'icon': 'fas fa-truck',
            'color': 'success'
        })

        # In Transit
        in_transit_date = order.shipped_date + timedelta(days=1)
        timeline.append({
            'title': 'In Transit',
            'description': 'Your package is on its way to the destination.',
            'date': in_transit_date,
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
    if order.delivered_date:
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

@login_required
def store_order_invoice(request, store_id, order_id):
    """Generate invoice for a store owner – only their items."""
    store = get_object_or_404(Store, id=store_id, owner=request.user)
    order = get_object_or_404(Order, id=order_id)

    # Filter only items sold by this store
    store_order_items = order.items.filter(product__seller=store.owner).select_related('product')

    if not store_order_items.exists():
        return render(request, 'orders/access_denied.html', {
            'message': "You do not have any products in this order."
        })

    # Calculate total for just the store's items
    subtotal = sum(item.get_total_price() for item in store_order_items)
    tax_amount = (order.tax_rate / 100) * subtotal
    discount = order.discount_amount or 0
    shipping = order.shipping_cost or 0  # Optional: split proportionally if multi-store shipping
    total = subtotal + tax_amount + shipping - discount

    qr_code = generate_invoice_qr_code(order)

    context = {
        'store': store,
        'order': order,
        'order_items': store_order_items,
        'invoice_qr_code': qr_code,
        'company_name': store.name or 'EasyMarket',
        'company_address': store.address_line_1 and store.address_line_2 or store.address_line_1,
        'company_email': store.email,
        'company_phone': store.phone,
        'subtotal': subtotal,
        'tax_amount': tax_amount,
        'discount': discount,
        'shipping': shipping,
        'total': total,
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