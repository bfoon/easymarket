from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.http import JsonResponse
from django.core.exceptions import PermissionDenied
from django.db import transaction
from .models import Shipment, Driver, Vehicle, Warehouse, LogisticOffice
from .forms import ShipmentForm
from orders.models import Order  # Ensure your Order model is correctly imported


@login_required
def shipment_list(request):
    """Display list of shipments with basic filtering and stats"""
    shipments = Shipment.objects.all().order_by('-created_at')

    # Add basic filtering if needed
    status_filter = request.GET.get('status')
    if status_filter:
        shipments = shipments.filter(status=status_filter)

    # Calculate stats
    pending_shipments_count = Shipment.objects.filter(status='pending').count()
    in_transit_count = Shipment.objects.filter(status='in_transit').count()
    delivered_count = Shipment.objects.filter(status='delivered').count()

    context = {
        'shipments': shipments,
        'pending_shipments_count': pending_shipments_count,
        'in_transit_count': in_transit_count,
        'delivered_count': delivered_count,
        'current_filter': status_filter,
    }
    return render(request, 'logistics/shipment_list.html', context)


@login_required
def shipment_detail(request, shipment_id):
    """Display detailed information for a specific shipment"""
    shipment = get_object_or_404(Shipment, id=shipment_id)

    # Add authorization check if needed
    # if not user_can_view_shipment(request.user, shipment):
    #     raise PermissionDenied("You don't have permission to view this shipment")

    context = {
        'shipment': shipment,
        'can_edit': True,  # Add your permission logic here
        'status_choices': Shipment.STATUS_CHOICES if hasattr(Shipment, 'STATUS_CHOICES') else [],
    }
    return render(request, 'logistics/shipment_detail.html', context)


@login_required
def create_shipment(request):
    """Create a new shipment"""
    if request.method == 'POST':
        form = ShipmentForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    shipment = form.save(commit=False)

                    # Set shipping address from order if available
                    if shipment.order and shipment.order.shipping_address:
                        shipment.shipping_address = shipment.order.shipping_address

                    # Set created by user if your model has this field
                    # shipment.created_by = request.user

                    shipment.save()

                    messages.success(request, f"Shipment #{shipment.id} created successfully!")
                    return redirect('logistics:shipment_detail', shipment_id=shipment.id)

            except Exception as e:
                messages.error(request, f"Error creating shipment: {str(e)}")

    else:
        form = ShipmentForm()

        # Pre-populate with order if provided in URL
        order_id = request.GET.get('order_id')
        if order_id:
            try:
                order = Order.objects.get(id=order_id)
                form.fields['order'].initial = order
            except Order.DoesNotExist:
                messages.warning(request, "Specified order not found.")

    context = {
        'form': form,
        'title': 'Create New Shipment',
    }
    return render(request, 'logistics/shipment_form.html', context)


@login_required
def get_shipping_address(request):
    """AJAX endpoint to get shipping address for selected order"""
    if not request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'success': False, 'error': 'Invalid request'})

    order_id = request.GET.get('order_id')

    if not order_id:
        return JsonResponse({'success': False, 'error': 'Order ID is required'})

    try:
        order = get_object_or_404(Order, id=order_id)

        # Add authorization check if needed
        # if not user_can_access_order(request.user, order):
        #     return JsonResponse({'success': False, 'error': 'Permission denied'})

        if order.shipping_address:
            return JsonResponse({
                'success': True,
                'address_id': order.shipping_address.id,
                'address_text': str(order.shipping_address),
                'order_total': str(order.total) if hasattr(order, 'total') else None,
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'No shipping address found for this order'
            })

    except Order.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Order not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@require_POST
@login_required
def mark_shipment_as_shipped(request, shipment_id):
    """Mark a shipment as shipped - this is for shipments, not orders"""
    shipment = get_object_or_404(Shipment, id=shipment_id)

    # Add authorization check
    # if not user_can_edit_shipment(request.user, shipment):
    #     messages.error(request, "You are not authorized to update this shipment.")
    #     return redirect('logistics:shipment_detail', shipment_id=shipment.id)

    try:
        # Check current status
        if shipment.status == 'shipped':
            messages.warning(request, f"Shipment #{shipment.id} is already marked as shipped.")
        elif shipment.status == 'delivered':
            messages.warning(request, f"Shipment #{shipment.id} is already delivered.")
        else:
            # Update shipment status
            shipment.status = 'shipped'
            shipment.save(update_fields=['status'])

            # Also update the related order if it exists
            if shipment.order:
                shipment.order.status = 'shipped'
                shipment.order.save(update_fields=['status'])

            messages.success(request, f"Shipment #{shipment.id} has been marked as shipped.")

    except Exception as e:
        messages.error(request, f"Failed to update shipment status: {str(e)}")

    return redirect('logistics:shipment_detail', shipment_id=shipment.id)


@require_POST
@login_required
def mark_order_as_shipped(request, order_id):
    """Mark an order as shipped - this is for orders, not shipments"""
    order = get_object_or_404(Order, id=order_id)

    # Check if order has a store and user is authorized
    if not hasattr(order, 'store') or order.store is None:
        messages.error(request, "This order is not associated with any store.")
        return redirect('logistics:shipment_list')

    if hasattr(order.store, 'owner') and order.store.owner != request.user:
        messages.error(request, "You are not authorized to mark this order as shipped.")
        return redirect('logistics:shipment_list')

    try:
        with transaction.atomic():
            # Check if order can be marked as shipped
            if hasattr(order, 'status') and order.status == 'shipped':
                messages.warning(request, f"Order #{order.id} is already marked as shipped.")
            else:
                # Mark order as shipped
                if hasattr(order, 'mark_as_shipped'):
                    order.mark_as_shipped()
                else:
                    order.status = 'shipped'
                    order.save(update_fields=['status'])

                # Update related shipment if it exists
                try:
                    shipment = Shipment.objects.get(order=order)
                    shipment.status = 'shipped'
                    shipment.save(update_fields=['status'])
                except Shipment.DoesNotExist:
                    pass  # No shipment exists for this order

                messages.success(request, f"Order #{order.id} has been successfully marked as shipped.")

    except Exception as e:
        messages.error(request, f"Failed to mark order as shipped: {str(e)}")

    # Redirect back to shipment list or detail as appropriate
    try:
        shipment = Shipment.objects.get(order=order)
        return redirect('logistics:shipment_detail', shipment_id=shipment.id)
    except Shipment.DoesNotExist:
        return redirect('logistics:shipment_list')


@require_POST
@login_required
def mark_shipment_as_delivered(request, shipment_id):
    """Mark a shipment as delivered"""
    shipment = get_object_or_404(Shipment, id=shipment_id)

    try:
        if shipment.status == 'delivered':
            messages.warning(request, f"Shipment #{shipment.id} is already marked as delivered.")
        else:
            shipment.status = 'delivered'
            shipment.save(update_fields=['status'])

            # Update related order if it exists
            if shipment.order:
                shipment.order.status = 'delivered'
                shipment.order.save(update_fields=['status'])

            messages.success(request, f"Shipment #{shipment.id} has been marked as delivered.")

    except Exception as e:
        messages.error(request, f"Failed to mark shipment as delivered: {str(e)}")

    return redirect('logistics:shipment_detail', shipment_id=shipment.id)


@login_required
def edit_shipment(request, shipment_id):
    """Edit an existing shipment"""
    shipment = get_object_or_404(Shipment, id=shipment_id)

    if request.method == 'POST':
        form = ShipmentForm(request.POST, instance=shipment)
        if form.is_valid():
            try:
                form.save()
                messages.success(request, f"Shipment #{shipment.id} updated successfully!")
                return redirect('logistics:shipment_detail', shipment_id=shipment.id)
            except Exception as e:
                messages.error(request, f"Error updating shipment: {str(e)}")
    else:
        form = ShipmentForm(instance=shipment)

    context = {
        'form': form,
        'shipment': shipment,
        'title': f'Edit Shipment #{shipment.id}',
    }
    return render(request, 'logistics/shipment_form.html', context)