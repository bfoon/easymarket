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
from .models import Order, OrderItem,  PromoCode
from marketplace.models import Cart, CartItem
from django.core.exceptions import ValidationError
from decimal import Decimal
from django.views.decorators.csrf import csrf_protect
from django.db import transaction
from django.views.decorators.http import require_POST
import json
from django.views.decorators.http import require_http_methods


@require_http_methods(["POST"])
@csrf_protect
@login_required
def checkout_cart(request):
    promo_code_str = request.POST.get('promo_code', '').strip()
    promo = None
    discount_amount = Decimal('0')

    try:
        cart = Cart.objects.get(user=request.user)
        cart_items = CartItem.objects.filter(cart=cart).select_related('product')

        if not cart_items.exists():
            messages.error(request, "Your cart is empty.")
            return redirect('marketplace:cart_view')

        subtotal = sum(item.product.price * item.quantity for item in cart_items)

        # Handle Promo Code
        if promo_code_str:
            try:
                promo = PromoCode.objects.get(code__iexact=promo_code_str, is_active=True)
                if not promo.is_valid():
                    messages.error(request, "Promo code is invalid or expired.")
                    return redirect('marketplace:cart_view')
                discount_amount = (subtotal * Decimal(promo.discount_percentage)) / 100
            except PromoCode.DoesNotExist:
                messages.error(request, "Promo code not found.")
                return redirect('marketplace:cart_view')

        # Create Order with promo applied using database transaction
        try:
            with transaction.atomic():
                order = Order.objects.create(
                    buyer=request.user,
                    promo_code=promo,
                    discount_amount=discount_amount
                )

                for item in cart_items:
                    # Lock the product row to prevent race conditions
                    product = item.product.__class__.objects.select_for_update().get(id=item.product.id)

                    # Reduce stock with the locked product
                    reduce_stock(product, item.quantity)

                    OrderItem.objects.create(
                        order=order,
                        product=product,
                        quantity=item.quantity
                    )

                # Clear cart items after successful order creation
                cart_items.delete()

                # Increment promo code usage
                if promo:
                    promo.increment_usage()

                messages.success(request, "Order placed successfully!")
                return redirect('orders:order_detail', order_id=order.id)

        except ValidationError as e:
            messages.error(request, f"Failed to checkout: {str(e)}")
            return redirect('marketplace:cart_view')
        except Exception as e:
            # Log the error for debugging
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Checkout error for user {request.user.id}: {str(e)}")

            messages.error(request, "An error occurred during checkout. Please try again.")
            return redirect('marketplace:cart_view')

    except Cart.DoesNotExist:
        messages.error(request, "You don't have any cart to checkout.")
        return redirect('marketplace:cart_view')


@login_required
def order_detail(request, order_id):
    order = get_object_or_404(Order, id=order_id, buyer=request.user)

    # Get other orders for the sidebar (exclude current order)
    other_orders = Order.objects.filter(
        buyer=request.user
    ).exclude(id=order_id).order_by('-created_at')[:5]

    context = {
        'order': order,
        'other_orders': other_orders,
    }

    return render(request, 'orders/order_detail.html', context)


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


# @login_required
# def process_payment(request, order_id):
#     """Process payment for an order"""
#     if request.method != 'POST':
#         return JsonResponse({'success': False, 'error': 'Invalid request method'})
#
#     order = get_object_or_404(Order, id=order_id, buyer=request.user)
#
#     if order.status != 'pending':
#         return JsonResponse({'success': False, 'error': 'Order is not in pending status'})
#
#     try:
#         # Get payment details from form
#         payment_method = request.POST.get('payment_method')
#         card_number = request.POST.get('card_number')
#         expiry_date = request.POST.get('expiry_date')
#         cvv = request.POST.get('cvv')
#         cardholder_name = request.POST.get('cardholder_name')
#
#         # Basic validation
#         if not all([payment_method, card_number, expiry_date, cvv, cardholder_name]):
#             return JsonResponse({'success': False, 'error': 'All payment fields are required'})
#
#         # Here you would integrate with your payment processor
#         # For now, we'll simulate a successful payment
#
#         # Update order status
#         order.status = 'processing'
#         order.payment_method = payment_method
#         order.payment_date = timezone.now()
#         order.expected_delivery_date = timezone.now() + timedelta(days=7)
#         order.save()
#
#         return JsonResponse({'success': True, 'message': 'Payment processed successfully'})
#
#     except Exception as e:
#         return JsonResponse({'success': False, 'error': str(e)})


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
                    'total': float(order.get_total()),
                    'item_count': order.get_item_count(),
                },
                'tracking_updates': tracking_updates,
                'shipping_address': {
                    'full_name': order.shipping_address.full_name if order.shipping_address else '',
                    'street': order.shipping_address.street if order.shipping_address else '',
                    'city': order.shipping_address.city if order.shipping_address else '',
                    'state': order.shipping_address.state if order.shipping_address else '',
                    'zip_code': order.shipping_address.zip_code if order.shipping_address else '',
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
            item.product.stock.quantity += item.quantity
            item.product.stock.save()

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

    context = {
        'order': order,
        'company_name': 'Your Company Name',
        'company_address': 'Your Company Address',
        'company_email': 'contact@yourcompany.com',
        'company_phone': '+1 (555) 123-4567',
    }

    return render(request, 'orders/order_invoice.html', context)


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
        'total_spent': sum(order.get_total() for order in orders if order.status != 'cancelled'),
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