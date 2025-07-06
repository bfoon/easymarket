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
from .models import Order, OrderItem
from marketplace.models import Cart, CartItem
from django.core.exceptions import ValidationError
import json
from django.views.decorators.http import require_http_methods


@login_required
def checkout_cart(request):
    try:
        cart = Cart.objects.get(user=request.user)
        cart_items = CartItem.objects.filter(cart=cart)

        if not cart_items.exists():
            messages.error(request, "Your cart is empty.")
            return redirect('marketplace:cart_view')

        order = Order.objects.create(buyer=request.user)

        for item in cart_items:
            try:
                reduce_stock(item.product, item.quantity)
            except ValidationError as e:
                order.delete()
                messages.error(request, f"Failed to checkout: {str(e)}")
                return redirect('marketplace:cart_view')

            OrderItem.objects.create(
                order=order,
                product=item.product,
                quantity=item.quantity
            )

        cart_items.delete()

        messages.success(request, "Order placed successfully!")
        return redirect('orders:order_detail', order_id=order.id)

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


@login_required
def process_payment(request, order_id):
    """Process payment for an order"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'})

    order = get_object_or_404(Order, id=order_id, buyer=request.user)

    if order.status != 'pending':
        return JsonResponse({'success': False, 'error': 'Order is not in pending status'})

    try:
        # Get payment details from form
        payment_method = request.POST.get('payment_method')
        card_number = request.POST.get('card_number')
        expiry_date = request.POST.get('expiry_date')
        cvv = request.POST.get('cvv')
        cardholder_name = request.POST.get('cardholder_name')

        # Basic validation
        if not all([payment_method, card_number, expiry_date, cvv, cardholder_name]):
            return JsonResponse({'success': False, 'error': 'All payment fields are required'})

        # Here you would integrate with your payment processor
        # For now, we'll simulate a successful payment

        # Update order status
        order.status = 'processing'
        order.payment_method = payment_method
        order.payment_date = timezone.now()
        order.expected_delivery_date = timezone.now() + timedelta(days=7)
        order.save()

        return JsonResponse({'success': True, 'message': 'Payment processed successfully'})

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


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
def cancel_order(request, order_id):
    """Cancel an order if it's still pending"""
    order = get_object_or_404(Order, id=order_id, buyer=request.user)

    if order.status != 'pending':
        messages.error(request, "Only pending orders can be cancelled.")
        return redirect('orders:order_detail', order_id=order.id)

    try:
        # Restore stock for cancelled orders
        for item in order.items.all():
            item.product.stock += item.quantity
            item.product.save()

        # Update order status
        order.status = 'cancelled'
        order.save()

        messages.success(request, "Order cancelled successfully. Stock has been restored.")

    except Exception as e:
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