"""
Logistics Views Module

This module contains all view classes and functions for the logistics application,
organized using modern Django patterns with proper separation of concerns.

Author: Logistics Team
Version: 2.0.0
"""

from typing import Any, Dict, Optional, List
from decimal import Decimal
from datetime import datetime, timedelta
import csv
import json
import logging
import threading

from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import (
    ListView, DetailView, CreateView, UpdateView,
    DeleteView, TemplateView
)
from django.contrib.auth.mixins import (
    LoginRequiredMixin, PermissionRequiredMixin, UserPassesTestMixin
)
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse_lazy, reverse
from django.db.models import (
    Q, Count, Avg, Sum, F, ExpressionWrapper,
    DecimalField, Case, When, Value
)
from django.db.models.functions import TruncDate, Coalesce
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import (
    HttpResponse, JsonResponse, HttpRequest,
    HttpResponseRedirect, Http404
)
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods, require_POST
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.core.exceptions import ValidationError, PermissionDenied
from django.contrib.auth import get_user_model

# Third-party imports
import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.styles import Font, PatternFill, Alignment

# Local imports
from .models import (
    Shipment, ShipmentBox, BoxItem, Driver, Vehicle,
    Warehouse, LogisticOffice
)
from .forms import (
    ShipmentForm, ShipmentBoxForm, BoxItemForm,
    DriverForm, VehicleForm, WarehouseForm
)
from .decorators import driver_required, warehouse_manager_required
from .utils import (
    send_delivery_notification,
    create_delivery_history,
    get_driver_statistics,
    validate_shipment_transition,
    calculate_shipping_cost,
    get_optimal_route
)
from .services import (
    NotificationService,
    ShipmentService,
    AnalyticsService
)
from orders.models import Order, OrderItem, ShippingAddress, OrderStatusHistory
from marketplace.notifications import send_whatsapp, send_email

# Configure logging
logger = logging.getLogger(__name__)

User = get_user_model()


# ============================================================================
# NOTIFICATION FUNCTIONS
# ============================================================================

class NotificationManager:
    """
    Centralized notification management for all logistics events.
    Uses threading for non-blocking notification delivery.
    """

    @staticmethod
    def notify_driver_delivery_assigned(driver: Driver, shipment: Shipment) -> None:
        """Notify driver of new delivery assignment."""
        try:
            message = (
                f"🚚 New Delivery Assignment\n\n"
                f"Shipment: {shipment.tracking_number}\n"
                f"Pickup: {shipment.warehouse}\n"
                f"Pickup Time: {shipment.collect_time.strftime('%Y-%m-%d %H:%M')}\n"
                f"Delivery: {shipment.shipping_address.address}\n"
                f"Est. Delivery: {shipment.estimated_dropoff_time.strftime('%Y-%m-%d %H:%M')}"
            )

            subject = f"New Delivery Assignment - {shipment.tracking_number}"
            send_email(subject, message, [driver.user.email])
            send_whatsapp(driver.phone, message)

            logger.info(f"Notified driver {driver.employee_id} of shipment {shipment.tracking_number}")
        except Exception as e:
            logger.error(f"Failed to notify driver {driver.employee_id}: {str(e)}")

    @staticmethod
    def notify_buyer_order_shipped(order: Order) -> None:
        """Notify buyer when order is shipped."""
        try:
            buyer = order.buyer
            message = (
                f"📦 Your Order Has Been Shipped!\n\n"
                f"Order ID: #{order.id}\n"
                f"Tracking: {order.tracking_number}\n"
                f"Est. Delivery: {order.estimated_delivery_date.strftime('%Y-%m-%d') if order.estimated_delivery_date else 'TBD'}\n\n"
                f"Track your order at: {order.get_tracking_url()}\n"
                f"Thank you for shopping with us!"
            )

            subject = f"Order #{order.id} Shipped - Track Your Package"
            send_email(subject, message, [buyer.email])
            if buyer.telephone:
                send_whatsapp(buyer.telephone, message)

            logger.info(f"Notified buyer {buyer.id} of order {order.id} shipment")
        except Exception as e:
            logger.error(f"Failed to notify buyer for order {order.id}: {str(e)}")

    @staticmethod
    def notify_buyer_shipment_in_transit(order: Order) -> None:
        """Notify buyer when shipment is in transit."""
        try:
            buyer = order.buyer
            message = (
                f"🚚 Your Order is On The Way!\n\n"
                f"Order ID: #{order.id}\n"
                f"Status: In Transit\n\n"
                f"Your package is currently being delivered to you.\n"
                f"Please ensure someone is available to receive it.\n\n"
                f"Track your order: {order.get_tracking_url()}"
            )

            subject = f"Order #{order.id} In Transit"
            send_email(subject, message, [buyer.email])
            if buyer.telephone:
                send_whatsapp(buyer.telephone, message)

            logger.info(f"Notified buyer {buyer.id} - order {order.id} in transit")
        except Exception as e:
            logger.error(f"Failed to notify buyer in-transit for order {order.id}: {str(e)}")

    @staticmethod
    def notify_buyer_shipment_delivered(order: Order) -> None:
        """Notify buyer when shipment is delivered."""
        try:
            buyer = order.buyer
            delivery_time = timezone.now().strftime("%Y-%m-%d %H:%M")

            message = (
                f"✅ Your Order Has Been Delivered!\n\n"
                f"Order ID: #{order.id}\n"
                f"Delivered: {delivery_time}\n\n"
                f"We hope you enjoy your purchase!\n"
                f"Please take a moment to rate your experience.\n\n"
                f"Thank you for choosing us!"
            )

            subject = f"Order #{order.id} Delivered Successfully"
            send_email(subject, message, [buyer.email])
            if buyer.telephone:
                send_whatsapp(buyer.telephone, message)

            logger.info(f"Notified buyer {buyer.id} - order {order.id} delivered")
        except Exception as e:
            logger.error(f"Failed to notify buyer delivery for order {order.id}: {str(e)}")

    @classmethod
    def run_in_background(cls, method_name: str, *args, **kwargs) -> None:
        """Execute notification method in background thread."""
        method = getattr(cls, method_name)
        thread = threading.Thread(
            target=method,
            args=args,
            kwargs=kwargs,
            daemon=True
        )
        thread.start()


# ============================================================================
# BASE MIXIN CLASSES
# ============================================================================

class LogisticsMixin(LoginRequiredMixin):
    """Base mixin for all logistics views."""

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        """Add common context data for logistics views."""
        context = super().get_context_data(**kwargs)
        context['app_name'] = 'logistics'
        context['current_time'] = timezone.now()
        return context


class SearchMixin:
    """Mixin to add search functionality to list views."""

    search_fields: List[str] = []

    def get_queryset(self):
        """Apply search filter to queryset."""
        queryset = super().get_queryset()
        search_query = self.request.GET.get('search', '').strip()

        if search_query and self.search_fields:
            q_objects = Q()
            for field in self.search_fields:
                q_objects |= Q(**{f"{field}__icontains": search_query})
            queryset = queryset.filter(q_objects)

        return queryset

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        """Add search query to context."""
        context = super().get_context_data(**kwargs)
        context['search_query'] = self.request.GET.get('search', '')
        return context


class FilterMixin:
    """Mixin to add filtering functionality to list views."""

    filter_fields: Dict[str, str] = {}

    def get_queryset(self):
        """Apply filters to queryset."""
        queryset = super().get_queryset()

        for param, field in self.filter_fields.items():
            value = self.request.GET.get(param)
            if value:
                queryset = queryset.filter(**{field: value})

        return queryset

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        """Add filter values to context."""
        context = super().get_context_data(**kwargs)
        context['filters'] = {
            param: self.request.GET.get(param, '')
            for param in self.filter_fields.keys()
        }
        return context


class ExportMixin:
    """Mixin to add export functionality to list views."""

    export_fields: List[str] = []
    export_headers: List[str] = []

    def get_export_data(self) -> List[List[Any]]:
        """Get data for export."""
        queryset = self.get_queryset()
        data = []

        for obj in queryset:
            row = [getattr(obj, field, '') for field in self.export_fields]
            data.append(row)

        return data


# ============================================================================
# DASHBOARD VIEWS
# ============================================================================

class DashboardView(LogisticsMixin, TemplateView):
    """
    Main logistics dashboard with key metrics and statistics.
    """
    template_name = 'logistics/dashboard.html'

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)

        # Get date range for statistics
        today = timezone.now().date()
        week_ago = today - timedelta(days=7)
        month_ago = today - timedelta(days=30)

        # Shipment statistics
        all_shipments = Shipment.objects.all()
        context['total_shipments'] = all_shipments.count()
        context['pending_shipments'] = all_shipments.filter(status='pending').count()
        context['in_transit_shipments'] = all_shipments.filter(status='in_transit').count()
        context['delivered_today'] = all_shipments.filter(
            status='delivered',
            actual_dropoff_time__date=today
        ).count()

        # Recent shipments
        context['recent_shipments'] = all_shipments.select_related(
            'driver', 'vehicle', 'warehouse', 'shipping_address', 'order'
        ).order_by('-created_at')[:10]

        # Driver statistics
        context['total_drivers'] = Driver.objects.filter(is_active=True).count()
        context['active_drivers'] = Driver.objects.filter(
            is_active=True,
            shipments__status__in=['in_transit', 'shipped']
        ).distinct().count()

        # Vehicle statistics
        context['total_vehicles'] = Vehicle.objects.filter(is_active=True).count()
        context['vehicles_in_use'] = Vehicle.objects.filter(
            is_active=True,
            shipments__status__in=['in_transit', 'shipped']
        ).distinct().count()

        # Warehouse statistics
        warehouses = Warehouse.objects.filter(is_active=True)
        context['total_warehouses'] = warehouses.count()
        context['warehouse_utilization'] = warehouses.aggregate(
            avg_util=Avg('current_utilization')
        )['avg_util'] or 0

        # Performance metrics
        delivered_this_week = all_shipments.filter(
            status='delivered',
            actual_dropoff_time__date__gte=week_ago
        )

        context['on_time_delivery_rate'] = self._calculate_on_time_rate(delivered_this_week)
        context['avg_delivery_time'] = self._calculate_avg_delivery_time(delivered_this_week)

        # Charts data
        context['shipments_by_status'] = self._get_shipments_by_status()
        context['daily_shipments'] = self._get_daily_shipments(week_ago)

        return context

    def _calculate_on_time_rate(self, queryset) -> float:
        """Calculate on-time delivery rate."""
        total = queryset.count()
        if total == 0:
            return 0.0

        on_time = queryset.filter(
            actual_dropoff_time__lte=F('estimated_dropoff_time')
        ).count()

        return round((on_time / total) * 100, 2)

    def _calculate_avg_delivery_time(self, queryset) -> Optional[float]:
        """Calculate average delivery time in hours."""
        deliveries = queryset.annotate(
            delivery_time=ExpressionWrapper(
                F('actual_dropoff_time') - F('collect_time'),
                output_field=DecimalField()
            )
        )

        avg_seconds = deliveries.aggregate(
            avg=Avg('delivery_time')
        )['avg']

        if avg_seconds:
            return round(float(avg_seconds) / 3600, 2)  # Convert to hours
        return None

    def _get_shipments_by_status(self) -> Dict[str, int]:
        """Get shipment counts grouped by status."""
        return dict(
            Shipment.objects.values_list('status').annotate(
                count=Count('id')
            )
        )

    def _get_daily_shipments(self, start_date) -> List[Dict[str, Any]]:
        """Get daily shipment counts."""
        daily_data = Shipment.objects.filter(
            created_at__date__gte=start_date
        ).annotate(
            date=TruncDate('created_at')
        ).values('date').annotate(
            count=Count('id')
        ).order_by('date')

        return list(daily_data)


# ============================================================================
# SHIPMENT VIEWS
# ============================================================================

class ShipmentListView(LogisticsMixin, SearchMixin, FilterMixin, ListView):
    """
    Display paginated list of all shipments with search and filtering.
    """
    model = Shipment
    template_name = 'logistics/shipment_list.html'
    context_object_name = 'shipments'
    paginate_by = 25

    search_fields = [
        'tracking_number',
        'id',
        'shipping_address__address',
        'shipping_address__city',
        'driver__user__first_name',
        'driver__user__last_name',
        'order__id',
    ]

    filter_fields = {
        'status': 'status',
        'order_status': 'order__status',
        'warehouse': 'warehouse_id',
        'driver': 'driver_id',
        'shipment_type': 'shipment_type',
        'material_type': 'material_type',
    }

    def get_queryset(self):
        """Get optimized queryset with related objects."""
        queryset = super().get_queryset().select_related(
            'shipping_address',
            'warehouse',
            'driver__user',
            'vehicle',
            'order',
            'logistic_office'
        ).prefetch_related(
            'boxes'
        ).order_by('-created_at')

        # Date range filter
        date_from = self.request.GET.get('date_from')
        date_to = self.request.GET.get('date_to')

        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)

        return queryset

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)

        # Add filter options
        context['status_choices'] = Shipment.STATUS_CHOICES
        context['shipment_type_choices'] = Shipment.SHIPMENT_TYPE_CHOICES
        context['material_type_choices'] = Shipment.MATERIAL_TYPE_CHOICES
        context['warehouses'] = Warehouse.objects.filter(is_active=True)
        context['drivers'] = Driver.objects.filter(is_active=True).select_related('user')

        # Add statistics
        queryset = self.get_queryset()
        context['total_count'] = queryset.count()
        context['pending_count'] = queryset.filter(status='pending').count()
        context['in_transit_count'] = queryset.filter(status='in_transit').count()
        context['delivered_count'] = queryset.filter(status='delivered').count()

        return context


class ShipmentDetailView(LogisticsMixin, DetailView):
    """
    Display detailed information about a single shipment.
    """
    model = Shipment
    template_name = 'logistics/shipment_detail.html'
    context_object_name = 'shipment'

    def get_queryset(self):
        """Get optimized queryset."""
        return super().get_queryset().select_related(
            'shipping_address',
            'warehouse',
            'driver__user',
            'vehicle',
            'order__buyer',
            'logistic_office'
        ).prefetch_related(
            'boxes__items__order_item__product__store'
        )

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)
        shipment = self.get_object()

        # Box information
        context['boxes'] = shipment.boxes.all()
        context['total_boxes'] = shipment.boxes.count()
        context['total_items'] = sum(
            box.get_total_items_count() for box in context['boxes']
        )

        # Order information
        if shipment.order:
            order = shipment.order
            context['order'] = order
            context['order_status'] = order.status
            context['order_status_display'] = order.get_status_display()
            context['is_order_delivered'] = order.status == 'delivered'
            context['can_mark_delivered'] = (
                    order.status == 'shipped' and
                    shipment.status == 'shipped'
            )
            context['delivered_date'] = order.delivered_date
            context['boxes_readonly'] = order.status == 'delivered'

            # Get unique stores from order items
            stores = set()
            for item in order.items.select_related('product__store').all():
                if item.product and item.product.store:
                    stores.add(item.product.store)
            context['stores'] = stores
        else:
            context['boxes_readonly'] = False
            context['stores'] = []

        # Timeline/History
        context['status_history'] = self._get_shipment_history(shipment)

        # Route information
        if shipment.warehouse and shipment.shipping_address:
            context['route_info'] = self._get_route_info(shipment)

        return context

    def _get_shipment_history(self, shipment: Shipment) -> List[Dict[str, Any]]:
        """Get shipment status history."""
        history = []

        # Created
        history.append({
            'status': 'created',
            'timestamp': shipment.created_at,
            'description': 'Shipment created'
        })

        # Add other status changes from audit log if available
        # This would require an audit/history model

        return history

    def _get_route_info(self, shipment: Shipment) -> Dict[str, Any]:
        """Get route information between warehouse and destination."""
        # This would integrate with a routing API
        return {
            'distance_km': 0,  # Calculate actual distance
            'estimated_duration': 0,  # Calculate duration
            'route_points': []  # Get route coordinates
        }


class ShipmentCreateView(LogisticsMixin, CreateView):
    """
    Create a new shipment with comprehensive validation.
    """
    model = Shipment
    template_name = 'logistics/shipment_form.html'
    form_class = ShipmentForm

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context['title'] = 'Create New Shipment'
        context['processing_orders_count'] = Order.objects.filter(
            status='processing'
        ).count()
        return context

    def get_success_url(self) -> str:
        """Redirect to shipment detail after creation."""
        return reverse_lazy('logistics:shipment_detail', kwargs={'pk': self.object.pk})

    @transaction.atomic
    def form_valid(self, form):
        """Handle successful form submission."""
        response = super().form_valid(form)
        shipment = self.object

        # Auto-calculate shipping cost if not set
        if not shipment.shipping_cost:
            shipment.shipping_cost = calculate_shipping_cost(shipment)
            shipment.save(update_fields=['shipping_cost'])

        # Send notifications
        if shipment.order and shipment.order.buyer:
            NotificationManager.run_in_background(
                'notify_buyer_order_shipped',
                shipment.order
            )

        if shipment.driver:
            NotificationManager.run_in_background(
                'notify_driver_delivery_assigned',
                shipment.driver,
                shipment
            )

        # Log activity
        logger.info(
            f"Shipment {shipment.tracking_number} created by {self.request.user.username}"
        )

        messages.success(
            self.request,
            f'Shipment {shipment.tracking_number} created successfully!'
        )

        return response

    def form_invalid(self, form):
        """Handle form errors."""
        logger.warning(
            f"Shipment creation failed. Errors: {form.errors}"
        )
        messages.error(
            self.request,
            'Please correct the errors below and try again.'
        )
        return super().form_invalid(form)


class ShipmentUpdateView(LogisticsMixin, UpdateView):
    """
    Update existing shipment information.
    """
    model = Shipment
    template_name = 'logistics/shipment_form.html'
    form_class = ShipmentForm

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit Shipment {self.object.tracking_number}'
        context['is_edit'] = True
        return context

    def get_success_url(self) -> str:
        """Redirect to shipment detail after update."""
        return reverse_lazy('logistics:shipment_detail', kwargs={'pk': self.object.pk})

    @transaction.atomic
    def form_valid(self, form):
        """Handle successful form submission."""
        # Track changes
        old_instance = Shipment.objects.get(pk=self.object.pk)
        response = super().form_valid(form)

        # Check for significant changes
        if old_instance.driver != self.object.driver and self.object.driver:
            # Driver changed - notify new driver
            NotificationManager.run_in_background(
                'notify_driver_delivery_assigned',
                self.object.driver,
                self.object
            )

        # Log activity
        logger.info(
            f"Shipment {self.object.tracking_number} updated by {self.request.user.username}"
        )

        messages.success(
            self.request,
            f'Shipment {self.object.tracking_number} updated successfully!'
        )

        return response


class ShipmentDeleteView(LogisticsMixin, PermissionRequiredMixin, DeleteView):
    """
    Delete a shipment (soft delete preferred).
    """
    model = Shipment
    template_name = 'logistics/shipment_confirm_delete.html'
    success_url = reverse_lazy('logistics:shipment_list')
    permission_required = 'logistics.delete_shipment'

    def delete(self, request, *args, **kwargs):
        """Override to perform soft delete or cancellation."""
        shipment = self.get_object()

        if shipment.status in ['delivered', 'in_transit']:
            messages.error(
                request,
                'Cannot delete delivered or in-transit shipments.'
            )
            return redirect('logistics:shipment_detail', pk=shipment.pk)

        # Cancel instead of delete
        shipment.cancel(reason="Deleted by admin")

        logger.info(
            f"Shipment {shipment.tracking_number} cancelled by {request.user.username}"
        )

        messages.success(request, 'Shipment cancelled successfully.')
        return HttpResponseRedirect(self.success_url)


# ============================================================================
# SHIPMENT STATUS MANAGEMENT
# ============================================================================

@login_required
@require_POST
def update_shipment_status(request: HttpRequest, pk: int) -> JsonResponse:
    """
    Update shipment status with validation.

    Args:
        request: HTTP request object
        pk: Shipment primary key

    Returns:
        JsonResponse with success status and message
    """
    try:
        shipment = get_object_or_404(Shipment, pk=pk)
        new_status = request.POST.get('status')

        if not new_status or new_status not in dict(Shipment.STATUS_CHOICES):
            return JsonResponse({
                'success': False,
                'error': 'Invalid status provided'
            }, status=400)

        # Validate status transition
        if not validate_shipment_transition(shipment.status, new_status):
            return JsonResponse({
                'success': False,
                'error': f'Cannot transition from {shipment.status} to {new_status}'
            }, status=400)

        # Update status
        old_status = shipment.status
        shipment.status = new_status
        shipment.save(update_fields=['status', 'updated_at'])

        # Handle status-specific actions
        if new_status == 'shipped':
            shipment.mark_as_shipped()
        elif new_status == 'in_transit':
            shipment.mark_as_in_transit()
            if shipment.order:
                NotificationManager.run_in_background(
                    'notify_buyer_shipment_in_transit',
                    shipment.order
                )
        elif new_status == 'delivered':
            shipment.mark_as_delivered()
            if shipment.order:
                NotificationManager.run_in_background(
                    'notify_buyer_shipment_delivered',
                    shipment.order
                )

        logger.info(
            f"Shipment {shipment.tracking_number} status changed "
            f"from {old_status} to {new_status} by {request.user.username}"
        )

        return JsonResponse({
            'success': True,
            'message': f'Status updated to {new_status}',
            'new_status': new_status,
            'new_status_display': shipment.get_status_display()
        })

    except Shipment.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Shipment not found'
        }, status=404)
    except Exception as e:
        logger.error(f"Error updating shipment status: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'An error occurred while updating status'
        }, status=500)


@login_required
@require_POST
def mark_order_as_delivered(request: HttpRequest, shipment_pk: int) -> HttpResponseRedirect:
    """
    Mark shipment and associated order as delivered.

    Args:
        request: HTTP request object
        shipment_pk: Shipment primary key

    Returns:
        Redirect to shipment detail page
    """
    try:
        with transaction.atomic():
            shipment = get_object_or_404(
                Shipment.objects.select_for_update(),
                pk=shipment_pk
            )

            # Verify shipment can be marked as delivered
            if shipment.status != 'shipped':
                messages.error(
                    request,
                    'Only shipped shipments can be marked as delivered.'
                )
                return redirect('logistics:shipment_detail', pk=shipment_pk)

            # Update shipment
            shipment.mark_as_delivered()

            # Update order if all shipments are delivered
            if shipment.order:
                order = shipment.order
                all_shipments = order.shipments.all()

                if all(s.status == 'delivered' for s in all_shipments):
                    order.status = 'delivered'
                    order.delivered_date = timezone.now()
                    order.save(update_fields=['status', 'delivered_date', 'updated_at'])

                    # Send notification
                    NotificationManager.run_in_background(
                        'notify_buyer_shipment_delivered',
                        order
                    )

            messages.success(
                request,
                f'Shipment {shipment.tracking_number} marked as delivered.'
            )

            logger.info(
                f"Shipment {shipment.tracking_number} marked as delivered "
                f"by {request.user.username}"
            )

    except Exception as e:
        logger.error(f"Error marking shipment as delivered: {str(e)}")
        messages.error(
            request,
            'An error occurred while marking the shipment as delivered.'
        )

    return redirect('logistics:shipment_detail', pk=shipment_pk)


@login_required
def get_shipment_order_status(request: HttpRequest, shipment_pk: int) -> JsonResponse:
    """
    Get current order status for a shipment.

    Args:
        request: HTTP request object
        shipment_pk: Shipment primary key

    Returns:
        JsonResponse with order status information
    """
    try:
        shipment = get_object_or_404(
            Shipment.objects.select_related('order'),
            pk=shipment_pk
        )

        if not shipment.order:
            return JsonResponse({
                'success': False,
                'error': 'No order associated with this shipment'
            }, status=404)

        order = shipment.order

        return JsonResponse({
            'success': True,
            'order_id': order.id,
            'order_status': order.status,
            'order_status_display': order.get_status_display(),
            'shipped_date': order.shipped_date.isoformat() if order.shipped_date else None,
            'delivered_date': order.delivered_date.isoformat() if order.delivered_date else None,
            'tracking_number': order.tracking_number,
        })

    except Exception as e:
        logger.error(f"Error getting order status: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'An error occurred'
        }, status=500)


# ============================================================================
# BOX MANAGEMENT VIEWS
# ============================================================================

class ShipmentBoxCreateView(LoginRequiredMixin, CreateView):
    """Create a new box for a shipment"""
    model = ShipmentBox
    fields = ['box_number', 'weight_kg', 'dimensions']
    template_name = 'logistics/box_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['shipment'] = get_object_or_404(Shipment, pk=self.kwargs['shipment_pk'])
        return context

    def form_valid(self, form):
        form.instance.shipment_id = self.kwargs['shipment_pk']
        response = super().form_valid(form)
        self.object.generate_qr_label()
        messages.success(self.request, f'Box #{self.object.box_number} created successfully!')
        return response

    def get_success_url(self):
        return reverse_lazy('logistics:shipment_detail', kwargs={'pk': self.kwargs['shipment_pk']})


class ShipmentBoxDetailView(LoginRequiredMixin, DetailView):
    """View box details"""
    model = ShipmentBox
    template_name = 'logistics/box_detail.html'
    context_object_name = 'box'


class ShipmentBoxUpdateView(LoginRequiredMixin, UpdateView):
    """Update box information"""
    model = ShipmentBox
    fields = ['box_number', 'weight_kg', 'dimensions']
    template_name = 'logistics/box_form.html'

    def get_success_url(self):
        return reverse_lazy('logistics:shipment_detail', kwargs={'pk': self.object.shipment.pk})


class ShipmentBoxDeleteView(LoginRequiredMixin, DeleteView):
    """Delete a box"""
    model = ShipmentBox
    template_name = 'logistics/box_confirm_delete.html'

    def get_success_url(self):
        return reverse_lazy('logistics:shipment_detail', kwargs={'pk': self.object.shipment.pk})


@login_required
def manage_shipment_boxes(request, shipment_pk):
    """Manage all boxes for a shipment"""
    shipment = get_object_or_404(Shipment, pk=shipment_pk)
    boxes = shipment.boxes.prefetch_related('items__order_item__product')

    return render(request, 'logistics/manage_boxes.html', {
        'shipment': shipment,
        'boxes': boxes
    })


@login_required
@require_POST
def bulk_create_boxes(request, shipment_pk):
    """Create multiple boxes at once"""
    shipment = get_object_or_404(Shipment, pk=shipment_pk)
    num_boxes = int(request.POST.get('num_boxes', 1))

    with transaction.atomic():
        for i in range(1, num_boxes + 1):
            box = ShipmentBox.objects.create(
                shipment=shipment,
                box_number=i
            )
            box.generate_qr_label()

    messages.success(request, f'Created {num_boxes} boxes successfully!')
    return redirect('logistics:shipment_detail', pk=shipment_pk)


@login_required
def generate_box_label(request, box_id):
    """Generate QR label for a box"""
    box = get_object_or_404(ShipmentBox, pk=box_id)
    box.generate_qr_label()

    if request.is_ajax():
        return JsonResponse({'success': True, 'label_url': box.label.url})

    messages.success(request, 'Label generated successfully!')
    return redirect('logistics:shipment_detail', pk=box.shipment.pk)


@login_required
def generate_all_box_labels(request, shipment_id):
    """Generate labels for all boxes in a shipment"""
    shipment = get_object_or_404(Shipment, pk=shipment_id)

    for box in shipment.boxes.all():
        box.generate_qr_label()

    messages.success(request, f'Generated labels for all {shipment.boxes.count()} boxes!')
    return redirect('logistics:shipment_detail', pk=shipment_id)


# ============================================================================
# BOX ITEMS VIEWS
# ============================================================================

class BoxItemCreateView(LoginRequiredMixin, CreateView):
    """Add items to a box"""
    model = BoxItem
    fields = ['order_item', 'quantity', 'notes']
    template_name = 'logistics/box_item_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['box'] = get_object_or_404(ShipmentBox, pk=self.kwargs['box_pk'])
        return context

    def form_valid(self, form):
        form.instance.box_id = self.kwargs['box_pk']
        return super().form_valid(form)

    def get_success_url(self):
        box = self.object.box
        return reverse_lazy('logistics:shipment_detail', kwargs={'pk': box.shipment.pk})


class BoxItemDetailView(LoginRequiredMixin, DetailView):
    """View box item details"""
    model = BoxItem
    template_name = 'logistics/box_item_detail.html'


class BoxItemUpdateView(LoginRequiredMixin, UpdateView):
    """Update box item"""
    model = BoxItem
    fields = ['order_item', 'quantity', 'notes']
    template_name = 'logistics/box_item_form.html'

    def get_success_url(self):
        return reverse_lazy('logistics:shipment_detail', kwargs={'pk': self.object.box.shipment.pk})


class BoxItemDeleteView(LoginRequiredMixin, DeleteView):
    """Delete box item"""
    model = BoxItem
    template_name = 'logistics/box_item_confirm_delete.html'

    def get_success_url(self):
        return reverse_lazy('logistics:shipment_detail', kwargs={'pk': self.object.box.shipment.pk})


# ============================================================================
# DRIVER VIEWS - Additional
# ============================================================================

class DriverListView(LoginRequiredMixin, ListView):
    """List all drivers"""
    model = Driver
    template_name = 'logistics/driver_list.html'
    context_object_name = 'drivers'
    paginate_by = 20

    def get_queryset(self):
        return Driver.objects.filter(is_active=True).select_related('user').annotate(
            active_shipments_count=Count('shipments',
                                         filter=Q(shipments__status__in=['pending', 'in_transit', 'shipped']))
        )


class DriverDetailView(LoginRequiredMixin, DetailView):
    """View driver details"""
    model = Driver
    template_name = 'logistics/driver_detail.html'
    context_object_name = 'driver'


class DriverCreateView(LoginRequiredMixin, CreateView):
    """Create new driver"""
    model = Driver
    fields = ['user', 'phone', 'license_number', 'license_expiry', 'emergency_contact_name', 'emergency_contact_phone']
    template_name = 'logistics/driver_form.html'
    success_url = reverse_lazy('logistics:driver_list')


class DriverUpdateView(LoginRequiredMixin, UpdateView):
    """Update driver information"""
    model = Driver
    fields = ['phone', 'license_number', 'license_expiry', 'emergency_contact_name', 'emergency_contact_phone']
    template_name = 'logistics/driver_form.html'
    success_url = reverse_lazy('logistics:driver_list')


class DriverDeleteView(LoginRequiredMixin, DeleteView):
    """Delete driver"""
    model = Driver
    template_name = 'logistics/driver_confirm_delete.html'
    success_url = reverse_lazy('logistics:driver_list')


@login_required
@require_POST
def deactivate_driver(request, pk):
    """Deactivate a driver"""
    driver = get_object_or_404(Driver, pk=pk)
    driver.deactivate()
    messages.success(request, f'Driver {driver.user.get_full_name()} deactivated.')
    return redirect('logistics:driver_list')


@login_required
@require_POST
def activate_driver(request, pk):
    """Activate a driver"""
    driver = get_object_or_404(Driver, pk=pk)
    driver.activate()
    messages.success(request, f'Driver {driver.user.get_full_name()} activated.')
    return redirect('logistics:driver_list')


@login_required
def driver_statistics(request, pk):
    """View driver statistics"""
    driver = get_object_or_404(Driver, pk=pk)
    from .utils import get_driver_statistics
    stats = get_driver_statistics(driver)

    return render(request, 'logistics/driver_statistics.html', {
        'driver': driver,
        'stats': stats
    })


@login_required
def driver_performance(request, pk):
    """View driver performance metrics"""
    driver = get_object_or_404(Driver, pk=pk)
    from .services import AnalyticsService
    performance = AnalyticsService.get_driver_performance(driver)

    return render(request, 'logistics/driver_performance.html', {
        'driver': driver,
        'performance': performance
    })


@login_required
@driver_required
def driver_dashboard(request):
    """
    Driver dashboard showing assigned shipments and statistics.
    Requires @driver_required decorator which adds request.driver
    """
    driver = request.driver

    # Get shipments by status
    shipped_shipments = driver.shipments.filter(
        status='shipped'
    ).select_related(
        'shipping_address', 'order', 'vehicle'
    ).order_by('collect_time')

    in_transit_shipments = driver.shipments.filter(
        status='in_transit'
    ).select_related(
        'shipping_address', 'order', 'vehicle'
    ).order_by('estimated_dropoff_time')

    delivered_shipments = driver.shipments.filter(
        status='delivered'
    ).select_related(
        'shipping_address', 'order'
    ).order_by('-actual_dropoff_time')[:10]

    # Calculate statistics
    total_shipments = driver.shipments.count()

    # Performance metrics
    from datetime import timedelta
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)

    delivered_this_week = driver.shipments.filter(
        status='delivered',
        actual_dropoff_time__date__gte=week_ago
    ).count()

    delivered_today = driver.shipments.filter(
        status='delivered',
        actual_dropoff_time__date=today
    ).count()

    context = {
        'driver': driver,
        'shipped_shipments': shipped_shipments,
        'in_transit_shipments': in_transit_shipments,
        'delivered_shipments': delivered_shipments,
        'total_shipments': total_shipments,
        'delivered_this_week': delivered_this_week,
        'delivered_today': delivered_today,
        'current_time': timezone.now(),
    }

    return render(request, 'logistics/driver_dashboard.html', context)


@login_required
@driver_required
def driver_profile(request):
    """
    View driver profile information.
    Shows personal details, statistics, and performance metrics.
    """
    driver = request.driver

    # Get driver statistics
    stats = get_driver_statistics(driver)

    # Get recent shipments
    recent_shipments = driver.shipments.select_related(
        'shipping_address', 'order', 'vehicle'
    ).order_by('-created_at')[:5]

    # Get assigned vehicle
    current_vehicle = Vehicle.objects.filter(driver=driver).first()

    context = {
        'driver': driver,
        'stats': stats,
        'recent_shipments': recent_shipments,
        'current_vehicle': current_vehicle,
    }

    return render(request, 'logistics/driver_profile.html', context)


@login_required
@driver_required
def shipment_detail_map(request, shipment_id):
    """
    Show detailed shipment view with map and navigation for driver.
    Includes GPS coordinates, route information, and delivery details.
    """
    driver = request.driver

    # Get shipment - ensure it belongs to this driver
    shipment = get_object_or_404(
        Shipment.objects.select_related(
            'shipping_address', 'order__buyer', 'warehouse', 'vehicle'
        ).prefetch_related('boxes__items__order_item__product'),
        pk=shipment_id,
        driver=driver
    )

    # Get location data with coordinates
    location_data = get_shipment_location_data(shipment)

    # Get warehouse coordinates if available
    warehouse_coords = None
    if shipment.warehouse and shipment.warehouse.latitude:
        warehouse_coords = {
            'lat': float(shipment.warehouse.latitude),
            'lng': float(shipment.warehouse.longitude),
            'name': shipment.warehouse.name
        }

    # Calculate estimated distance and time
    estimated_distance = None
    estimated_time = None
    if location_data.get('coordinates') and warehouse_coords:
        from .utils import calculate_distance_haversine
        estimated_distance = calculate_distance_haversine(
            warehouse_coords['lat'],
            warehouse_coords['lng'],
            location_data['coordinates']['lat'],
            location_data['coordinates']['lng']
        )
        # Rough estimate: 30 km/h average speed in urban areas
        estimated_time = round(estimated_distance / 30 * 60)  # minutes

    # Get delivery instructions
    from .utils import enhance_delivery_instructions
    delivery_instructions = enhance_delivery_instructions(shipment)

    context = {
        'shipment': shipment,
        'driver': driver,
        'location_data': location_data,
        'warehouse_coords': warehouse_coords,
        'estimated_distance': estimated_distance,
        'estimated_time': estimated_time,
        'delivery_instructions': delivery_instructions,
        'can_start': shipment.status == 'shipped',
        'can_deliver': shipment.status == 'in_transit',
    }

    return render(request, 'logistics/shipment_detail_map.html', context)


@login_required
@driver_required
@require_POST
def start_delivery(request, shipment_id):
    """
    Mark shipment as in transit when driver starts delivery.
    Updates status and records start time.
    """
    driver = request.driver

    try:
        # Get shipment - ensure it belongs to this driver
        shipment = get_object_or_404(
            Shipment,
            pk=shipment_id,
            driver=driver
        )

        # Validate status transition
        from .utils import validate_shipment_transition
        if not validate_shipment_transition(shipment.status, 'in_transit'):
            return JsonResponse({
                'success': False,
                'error': f'Cannot start delivery from status: {shipment.get_status_display()}'
            }, status=400)

        # Update shipment
        with transaction.atomic():
            shipment.status = 'in_transit'
            shipment.save()

            # Create history entry
            create_delivery_history(
                shipment=shipment,
                status='in_transit',
                user=request.user,
                notes=f"Driver {driver.employee_id} started delivery"
            )

            # Send notification to buyer
            send_delivery_notification(
                shipment=shipment,
                status='in_transit',
                driver=driver
            )

        return JsonResponse({
            'success': True,
            'message': 'Delivery started successfully!',
            'shipment_status': shipment.get_status_display()
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@driver_required
@require_POST
def mark_delivered(request, shipment_id):
    """
    Mark shipment as delivered when driver completes delivery.
    Records delivery time, notes, and signature if provided.
    """
    driver = request.driver

    try:
        # Get shipment - ensure it belongs to this driver
        shipment = get_object_or_404(
            Shipment,
            pk=shipment_id,
            driver=driver
        )

        # Validate status transition
        from .utils import validate_shipment_transition
        if not validate_shipment_transition(shipment.status, 'delivered'):
            return JsonResponse({
                'success': False,
                'error': f'Cannot mark as delivered from status: {shipment.get_status_display()}'
            }, status=400)

        # Get delivery notes from request
        data = json.loads(request.body) if request.body else {}
        delivery_notes = data.get('notes', '')
        recipient_name = data.get('recipient_name', '')
        signature = data.get('signature', '')  # Base64 encoded signature

        # Update shipment
        with transaction.atomic():
            shipment.status = 'delivered'
            shipment.actual_dropoff_time = timezone.now()

            # Store additional delivery info if you have these fields
            if hasattr(shipment, 'delivery_notes'):
                shipment.delivery_notes = delivery_notes
            if hasattr(shipment, 'recipient_name'):
                shipment.recipient_name = recipient_name

            shipment.save()

            # Update order status if linked
            if shipment.order:
                shipment.order.status = 'delivered'
                shipment.order.save()

            # Create history entry
            create_delivery_history(
                shipment=shipment,
                status='delivered',
                user=request.user,
                notes=f"Delivered by {driver.employee_id}. {delivery_notes}"
            )

            # Send notification to buyer
            send_delivery_notification(
                shipment=shipment,
                status='delivered',
                driver=driver
            )

        return JsonResponse({
            'success': True,
            'message': 'Delivery marked as complete!',
            'delivered_at': shipment.actual_dropoff_time.isoformat()
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
def get_shipment_location(request, shipment_id):
    """
    Get shipment location data including coordinates, address, and delivery info.
    Returns JSON with location details for maps and navigation.
    """
    try:
        shipment = get_object_or_404(
            Shipment.objects.select_related(
                'shipping_address', 'warehouse', 'driver__user', 'vehicle'
            ),
            pk=shipment_id
        )

        # Check permission - must be assigned driver or staff
        if not (request.user.is_staff or
                (hasattr(request.user, 'driver') and shipment.driver == request.user.driver)):
            return JsonResponse({
                'error': 'Permission denied'
            }, status=403)

        # Get comprehensive location data
        location_data = get_shipment_location_data(shipment)

        # Add real-time tracking info if available
        tracking_info = {
            'status': shipment.status,
            'status_display': shipment.get_status_display(),
            'estimated_delivery': shipment.estimated_dropoff_time.isoformat() if shipment.estimated_dropoff_time else None,
            'actual_delivery': shipment.actual_dropoff_time.isoformat() if shipment.actual_dropoff_time else None,
            'driver': {
                'name': shipment.driver.user.get_full_name() if shipment.driver else None,
                'phone': shipment.driver.phone if shipment.driver else None,
                'employee_id': shipment.driver.employee_id if shipment.driver else None,
            } if shipment.driver else None,
            'vehicle': {
                'plate_number': shipment.vehicle.plate_number if shipment.vehicle else None,
                'model': shipment.vehicle.model if shipment.vehicle else None,
            } if shipment.vehicle else None
        }

        # Merge data
        location_data['tracking_info'] = tracking_info

        return JsonResponse(location_data)

    except Exception as e:
        return JsonResponse({
            'error': str(e)
        }, status=500)

@login_required
@driver_required
def driver_profile_edit(request):
    """Edit driver profile"""
    driver = request.driver

    if request.method == 'POST':
        # Handle form submission
        driver.phone = request.POST.get('phone', driver.phone)
        driver.emergency_contact_name = request.POST.get('emergency_contact_name', driver.emergency_contact_name)
        driver.emergency_contact_phone = request.POST.get('emergency_contact_phone', driver.emergency_contact_phone)
        driver.save()
        messages.success(request, 'Profile updated successfully!')
        return redirect('logistics:driver_profile')

    return render(request, 'logistics/driver_profile_edit.html', {'driver': driver})


@login_required
@require_POST
def update_driver_location(request, shipment_id):
    """Update driver's current location"""
    # This would integrate with GPS tracking
    data = json.loads(request.body)
    latitude = data.get('latitude')
    longitude = data.get('longitude')

    # Store location update (you'd need a DriverLocation model)
    return JsonResponse({'success': True, 'message': 'Location updated'})
# ============================================================================
# VEHICLE VIEWS - Additional
# ============================================================================

class VehicleListView(LoginRequiredMixin, ListView):
    """List all vehicles"""
    model = Vehicle
    template_name = 'logistics/vehicle_list.html'
    context_object_name = 'vehicles'
    paginate_by = 20


class VehicleDetailView(LoginRequiredMixin, DetailView):
    """View vehicle details"""
    model = Vehicle
    template_name = 'logistics/vehicle_detail.html'


class VehicleCreateView(LoginRequiredMixin, CreateView):
    """Create new vehicle"""
    model = Vehicle
    fields = ['driver', 'plate_number', 'model', 'year', 'capacity_kg', 'capacity_cubic_meters', 'fuel_type', 'vin']
    template_name = 'logistics/vehicle_form.html'
    success_url = reverse_lazy('logistics:vehicle_list')


class VehicleUpdateView(LoginRequiredMixin, UpdateView):
    """Update vehicle information"""
    model = Vehicle
    fields = ['driver', 'plate_number', 'model', 'year', 'capacity_kg', 'capacity_cubic_meters', 'fuel_type']
    template_name = 'logistics/vehicle_form.html'
    success_url = reverse_lazy('logistics:vehicle_list')


class VehicleDeleteView(LoginRequiredMixin, DeleteView):
    """Delete vehicle"""
    model = Vehicle
    template_name = 'logistics/vehicle_confirm_delete.html'
    success_url = reverse_lazy('logistics:vehicle_list')


@login_required
@require_POST
def deactivate_vehicle(request, pk):
    """Deactivate a vehicle"""
    vehicle = get_object_or_404(Vehicle, pk=pk)
    vehicle.deactivate()
    messages.success(request, f'Vehicle {vehicle.plate_number} deactivated.')
    return redirect('logistics:vehicle_list')


@login_required
@require_POST
def activate_vehicle(request, pk):
    """Activate a vehicle"""
    vehicle = get_object_or_404(Vehicle, pk=pk)
    vehicle.activate()
    messages.success(request, f'Vehicle {vehicle.plate_number} activated.')
    return redirect('logistics:vehicle_list')


@login_required
def vehicle_maintenance_log(request, pk):
    """View vehicle maintenance history"""
    vehicle = get_object_or_404(Vehicle, pk=pk)
    return render(request, 'logistics/vehicle_maintenance.html', {'vehicle': vehicle})


@login_required
@require_POST
def add_maintenance_record(request, pk):
    """Add maintenance record"""
    vehicle = get_object_or_404(Vehicle, pk=pk)
    # Add maintenance record logic
    messages.success(request, 'Maintenance record added.')
    return redirect('logistics:vehicle_maintenance', pk=pk)


@login_required
@require_POST
def schedule_maintenance(request, pk):
    """Schedule vehicle maintenance"""
    vehicle = get_object_or_404(Vehicle, pk=pk)
    # Schedule maintenance logic
    messages.success(request, 'Maintenance scheduled.')
    return redirect('logistics:vehicle_detail', pk=pk)


# ============================================================================
# WAREHOUSE VIEWS - Additional
# ============================================================================

class WarehouseListView(LoginRequiredMixin, ListView):
    """List all warehouses"""
    model = Warehouse
    template_name = 'logistics/warehouse_list.html'
    context_object_name = 'warehouses'


class WarehouseDetailView(LoginRequiredMixin, DetailView):
    """View warehouse details"""
    model = Warehouse
    template_name = 'logistics/warehouse_detail.html'


class WarehouseCreateView(LoginRequiredMixin, CreateView):
    """Create new warehouse"""
    model = Warehouse
    fields = ['name', 'address', 'latitude', 'longitude', 'capacity_cubic_meters', 'manager', 'logistic_office']
    template_name = 'logistics/warehouse_form.html'
    success_url = reverse_lazy('logistics:warehouse_list')


class WarehouseUpdateView(LoginRequiredMixin, UpdateView):
    """Update warehouse"""
    model = Warehouse
    fields = ['name', 'address', 'latitude', 'longitude', 'capacity_cubic_meters', 'manager']
    template_name = 'logistics/warehouse_form.html'
    success_url = reverse_lazy('logistics:warehouse_list')


class WarehouseDeleteView(LoginRequiredMixin, DeleteView):
    """Delete warehouse"""
    model = Warehouse
    template_name = 'logistics/warehouse_confirm_delete.html'
    success_url = reverse_lazy('logistics:warehouse_list')


@login_required
def warehouse_queue(request, pk):
    """View warehouse queue"""
    warehouse = get_object_or_404(Warehouse, pk=pk)
    return render(request, 'logistics/warehouse_queue.html', {'warehouse': warehouse})


class WarehouseQueueItemDetailView(LoginRequiredMixin, DetailView):
    """View warehouse queue item"""
    model = Shipment  # Or your queue item model
    template_name = 'logistics/warehouse_queue_item.html'


@login_required
def warehouse_inventory(request, pk):
    """View warehouse inventory"""
    warehouse = get_object_or_404(Warehouse, pk=pk)
    return render(request, 'logistics/warehouse_inventory.html', {'warehouse': warehouse})


@login_required
def warehouse_utilization(request, pk):
    """View warehouse utilization"""
    warehouse = get_object_or_404(Warehouse, pk=pk)
    warehouse.update_utilization()
    return render(request, 'logistics/warehouse_utilization.html', {'warehouse': warehouse})


# ============================================================================
# LOGISTIC OFFICE VIEWS
# ============================================================================

class LogisticOfficeListView(LoginRequiredMixin, ListView):
    """List all logistic offices"""
    model = LogisticOffice
    template_name = 'logistics/logistic_office_list.html'
    context_object_name = 'offices'


class LogisticOfficeDetailView(LoginRequiredMixin, DetailView):
    """View office details"""
    model = LogisticOffice
    template_name = 'logistics/logistic_office_detail.html'


class LogisticOfficeCreateView(LoginRequiredMixin, CreateView):
    """Create new office"""
    model = LogisticOffice
    fields = ['name', 'location', 'contact_email', 'contact_phone', 'timezone']
    template_name = 'logistics/logistic_office_form.html'
    success_url = reverse_lazy('logistics:logistic_office_list')


class LogisticOfficeUpdateView(LoginRequiredMixin, UpdateView):
    """Update office"""
    model = LogisticOffice
    fields = ['name', 'location', 'contact_email', 'contact_phone', 'timezone']
    template_name = 'logistics:logistic_office_form.html'
    success_url = reverse_lazy('logistics:logistic_office_list')


class LogisticOfficeDeleteView(LoginRequiredMixin, DeleteView):
    """Delete office"""
    model = LogisticOffice
    template_name = 'logistics/logistic_office_confirm_delete.html'
    success_url = reverse_lazy('logistics:logistic_office_list')


# ============================================================================
# ASSIGNMENT VIEWS
# ============================================================================

class AssignmentDashboardView(LoginRequiredMixin, TemplateView):
    """Assignment dashboard"""
    template_name = 'logistics/assignment_dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['total_vehicles'] = Vehicle.objects.filter(is_active=True).count()
        context['assigned_vehicles'] = Vehicle.objects.filter(is_active=True, driver__isnull=False).count()
        context['unassigned_vehicles'] = Vehicle.objects.filter(is_active=True, driver__isnull=True)
        context['active_drivers'] = Driver.objects.filter(is_active=True).count()
        context['vehicles'] = Vehicle.objects.filter(is_active=True).select_related('driver__user').annotate(
            active_shipments_count=Count('shipments', filter=Q(shipments__status__in=['pending', 'in_transit']))
        )[:10]
        context['drivers'] = Driver.objects.filter(is_active=True).select_related('user')
        return context


class VehicleAssignmentListView(LoginRequiredMixin, ListView):
    """List vehicle assignments"""
    model = Vehicle
    template_name = 'logistics/vehicle_assignment_list.html'
    context_object_name = 'vehicles'


class DriverAssignmentListView(LoginRequiredMixin, ListView):
    """List driver assignments"""
    model = Driver
    template_name = 'logistics/driver_assignment_list.html'
    context_object_name = 'drivers'


@login_required
def assignment_report(request):
    """Generate assignment report"""
    vehicles = Vehicle.objects.filter(is_active=True).select_related('driver__user')
    return render(request, 'logistics/assignment_report.html', {'vehicles': vehicles})


@login_required
@require_POST
def assign_vehicle_to_driver(request):
    """Assign vehicle to driver"""
    vehicle_id = request.POST.get('vehicle_id')
    driver_id = request.POST.get('driver_id')

    vehicle = get_object_or_404(Vehicle, pk=vehicle_id)

    if driver_id:
        driver = get_object_or_404(Driver, pk=driver_id)
        vehicle.driver = driver
    else:
        vehicle.driver = None

    vehicle.save()

    return JsonResponse({'success': True, 'message': 'Vehicle assigned successfully'})


@login_required
@require_POST
def quick_assign_vehicle(request):
    """Quick assign vehicles automatically"""
    from .services import ShipmentService

    unassigned = Vehicle.objects.filter(driver__isnull=True, is_active=True)
    assigned_count = 0

    for vehicle in unassigned:
        # Auto-assign logic
        available_driver = Driver.objects.filter(
            is_active=True,
            vehicles__isnull=True
        ).first()

        if available_driver:
            vehicle.driver = available_driver
            vehicle.save()
            assigned_count += 1

    return JsonResponse({
        'success': True,
        'message': f'Assigned {assigned_count} vehicles'
    })


@login_required
@require_POST
def bulk_assign_vehicles(request):
    """Bulk assign vehicles"""
    vehicle_ids = request.POST.getlist('vehicle_ids')
    driver_ids = request.POST.getlist('driver_ids')

    assigned = 0
    for vehicle_id, driver_id in zip(vehicle_ids, driver_ids):
        if driver_id:
            vehicle = Vehicle.objects.get(pk=vehicle_id)
            driver = Driver.objects.get(pk=driver_id)
            vehicle.driver = driver
            vehicle.save()
            assigned += 1

    messages.success(request, f'Assigned {assigned} vehicles')
    return redirect('logistics:assignment_dashboard')


@login_required
@require_POST
def unassign_vehicle(request, vehicle_id):
    """Unassign vehicle from driver"""
    vehicle = get_object_or_404(Vehicle, pk=vehicle_id)
    vehicle.driver = None
    vehicle.save()

    return JsonResponse({'success': True, 'message': 'Vehicle unassigned'})


@login_required
@require_POST
def reassign_shipment(request, shipment_id):
    """Reassign shipment to different driver/vehicle"""
    shipment = get_object_or_404(Shipment, pk=shipment_id)
    driver_id = request.POST.get('driver_id')
    vehicle_id = request.POST.get('vehicle_id')

    if driver_id:
        shipment.driver_id = driver_id
    if vehicle_id:
        shipment.vehicle_id = vehicle_id

    shipment.save()
    messages.success(request, 'Shipment reassigned successfully')
    return redirect('logistics:shipment_detail', pk=shipment_id)


@login_required
def assignment_report_export(request):
    """Export assignment report"""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="assignments.csv"'

    writer = csv.writer(response)
    writer.writerow(['Vehicle', 'Driver', 'Status', 'Active Shipments'])

    for vehicle in Vehicle.objects.filter(is_active=True).select_related('driver__user'):
        writer.writerow([
            vehicle.plate_number,
            vehicle.driver.user.get_full_name() if vehicle.driver else 'Unassigned',
            'Assigned' if vehicle.driver else 'Available',
            vehicle.shipments.filter(status__in=['pending', 'in_transit']).count()
        ])

    return response


@login_required
def assignment_report_json(request):
    """Get assignment data as JSON"""
    data = []
    for vehicle in Vehicle.objects.filter(is_active=True).select_related('driver__user'):
        data.append({
            'vehicle_id': vehicle.id,
            'plate_number': vehicle.plate_number,
            'driver': vehicle.driver.user.get_full_name() if vehicle.driver else None,
            'status': 'assigned' if vehicle.driver else 'available'
        })

    return JsonResponse({'assignments': data})


class AssignmentAnalyticsView(LoginRequiredMixin, TemplateView):
    """Assignment analytics"""
    template_name = 'logistics/assignment_analytics.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from .services import AnalyticsService
        context['analytics'] = AnalyticsService.get_vehicle_utilization_metrics()
        return context


# ============================================================================
# AJAX ENDPOINTS
# ============================================================================

@login_required
def ajax_addresses_for_order(request):
    """Get addresses for an order"""
    order_id = request.GET.get('order_id')
    addresses = ShippingAddress.objects.filter(order_id=order_id)
    data = [{'id': a.id, 'address': str(a)} for a in addresses]
    return JsonResponse({'addresses': data})


@login_required
def ajax_addresses_by_order(request):
    """Get addresses by order"""
    order_id = request.GET.get('order_id')
    # Implementation
    return JsonResponse({'addresses': []})


@login_required
def ajax_orders_for_address(request):
    """Get orders for an address"""
    address_id = request.GET.get('address_id')
    # Implementation
    return JsonResponse({'orders': []})


@login_required
def ajax_vehicles_by_driver(request):
    """Get vehicles for a driver"""
    driver_id = request.GET.get('driver_id')
    vehicles = Vehicle.objects.filter(driver_id=driver_id)
    data = [{'id': v.id, 'plate_number': v.plate_number, 'model': v.model} for v in vehicles]
    return JsonResponse({'vehicles': data})


@login_required
def get_unassigned_vehicles_ajax(request):
    """Get unassigned vehicles"""
    vehicles = Vehicle.objects.filter(driver__isnull=True, is_active=True)
    data = [{'id': v.id, 'plate_number': v.plate_number, 'model': v.model} for v in vehicles]
    return JsonResponse({'vehicles': data})


@login_required
def ajax_drivers_by_vehicle(request):
    """Get driver for a vehicle"""
    vehicle_id = request.GET.get('vehicle_id')
    vehicle = Vehicle.objects.filter(id=vehicle_id).select_related('driver__user').first()
    if vehicle and vehicle.driver:
        data = {'id': vehicle.driver.id, 'name': vehicle.driver.user.get_full_name()}
    else:
        data = None
    return JsonResponse({'driver': data})


@login_required
def get_driver_vehicles_ajax(request, driver_id):
    """Get all vehicles for a driver"""
    vehicles = Vehicle.objects.filter(driver_id=driver_id)
    data = [{'id': v.id, 'plate_number': v.plate_number, 'model': v.model} for v in vehicles]
    return JsonResponse({'vehicles': data})


@login_required
def get_shipment_status_ajax(request, shipment_id):
    """Get shipment status"""
    shipment = get_object_or_404(Shipment, pk=shipment_id)
    return JsonResponse({
        'status': shipment.status,
        'status_display': shipment.get_status_display(),
        'tracking_number': shipment.tracking_number
    })


@login_required
def get_tracking_info_ajax(request, shipment_id):
    """Get tracking information"""
    from .utils import get_shipment_location_data
    shipment = get_object_or_404(Shipment, pk=shipment_id)
    data = get_shipment_location_data(shipment)
    return JsonResponse(data)


@login_required
def ajax_search_shipments(request):
    """Search shipments"""
    query = request.GET.get('q', '')
    shipments = Shipment.objects.filter(
        Q(tracking_number__icontains=query) |
        Q(shipping_address__address__icontains=query)
    )[:10]

    data = [{
        'id': s.id,
        'tracking_number': s.tracking_number,
        'status': s.status,
        'destination': str(s.shipping_address)
    } for s in shipments]

    return JsonResponse({'results': data})


@login_required
def ajax_filter_warehouses(request):
    """Filter warehouses"""
    query = request.GET.get('q', '')
    warehouses = Warehouse.objects.filter(name__icontains=query, is_active=True)
    data = [{'id': w.id, 'name': w.name, 'code': w.code} for w in warehouses]
    return JsonResponse({'warehouses': data})


# ============================================================================
# REPORTING VIEWS
# ============================================================================

@login_required
def reports_dashboard(request):
    """Reports dashboard"""
    return render(request, 'logistics/reports_dashboard.html')


@login_required
def delivery_performance_report(request):
    """Delivery performance report"""
    from .services import AnalyticsService
    metrics = AnalyticsService.get_delivery_performance_metrics()
    return render(request, 'logistics/delivery_performance.html', {'metrics': metrics})


@login_required
def driver_performance_report(request):
    """Driver performance report"""
    from .utils import get_top_performing_drivers
    drivers = get_top_performing_drivers(limit=20)
    return render(request, 'logistics/driver_performance_report.html', {'drivers': drivers})


@login_required
def warehouse_utilization_report(request):
    """Warehouse utilization report"""
    from .services import AnalyticsService
    report = AnalyticsService.get_warehouse_utilization_report()
    return render(request, 'logistics/warehouse_utilization_report.html', {'report': report})


@login_required
def custom_report_builder(request):
    """Custom report builder"""
    return render(request, 'logistics/custom_report_builder.html')


@login_required
def generate_custom_report(request):
    """Generate custom report"""
    # Implementation based on user selection
    return render(request, 'logistics/custom_report.html')


@login_required
def export_report_pdf(request):
    """Export report as PDF"""
    # PDF generation logic
    return HttpResponse("PDF Report", content_type='application/pdf')


@login_required
def export_report_csv(request):
    """Export report as CSV"""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="report.csv"'
    # CSV generation logic
    return response


@login_required
def export_report_excel(request):
    """Export report as Excel"""
    # Excel generation logic
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename="report.xlsx"'
    return response


# ============================================================================
# NOTIFICATION VIEWS
# ============================================================================

@login_required
def notification_list(request):
    """List notifications"""
    # Notification logic
    return render(request, 'logistics/notification_list.html')


@login_required
@require_POST
def mark_notification_read(request, pk):
    """Mark notification as read"""
    # Mark read logic
    return JsonResponse({'success': True})


@login_required
@require_POST
def mark_all_notifications_read(request):
    """Mark all notifications as read"""
    # Mark all read logic
    return JsonResponse({'success': True})


@login_required
def notification_settings(request):
    """Notification settings"""
    return render(request, 'logistics/notification_settings.html')


# ============================================================================
# SHIPMENT ADDITIONAL VIEWS
# ============================================================================

@login_required
@require_POST
def cancel_shipment(request, shipment_pk):
    """Cancel a shipment"""
    shipment = get_object_or_404(Shipment, pk=shipment_pk)
    reason = request.POST.get('reason', '')
    shipment.cancel(reason=reason)
    messages.success(request, f'Shipment {shipment.tracking_number} cancelled.')
    return redirect('logistics:shipment_detail', pk=shipment_pk)


@login_required
def export_shipments_pdf(request):
    """Export shipments to PDF"""
    # PDF export logic
    return HttpResponse("PDF Export", content_type='application/pdf')


# Missing warehouse activation/deactivation
@login_required
@require_POST
def deactivate_warehouse(request, pk):
    """Deactivate warehouse"""
    warehouse = get_object_or_404(Warehouse, pk=pk)
    warehouse.deactivate()
    messages.success(request, f'Warehouse {warehouse.name} deactivated.')
    return redirect('logistics:warehouse_list')


@login_required
@require_POST
def activate_warehouse(request, pk):
    """Activate warehouse"""
    warehouse = get_object_or_404(Warehouse, pk=pk)
    warehouse.activate()
    messages.success(request, f'Warehouse {warehouse.name} activated.')
    return redirect('logistics:warehouse_list')


# ============================================================================
# EXPORT VIEWS
# ============================================================================

@login_required
def export_shipments_csv(request):
    """
    Export shipments to CSV format.
    Includes filtering by status, date range, and driver.
    """
    # Get filter parameters
    status = request.GET.get('status', '')
    driver_id = request.GET.get('driver_id', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    # Build queryset
    shipments = Shipment.objects.select_related(
        'shipping_address', 'driver__user', 'vehicle', 'warehouse', 'order'
    ).order_by('-created_at')

    # Apply filters
    if status:
        shipments = shipments.filter(status=status)
    if driver_id:
        shipments = shipments.filter(driver_id=driver_id)
    if date_from:
        shipments = shipments.filter(created_at__date__gte=date_from)
    if date_to:
        shipments = shipments.filter(created_at__date__lte=date_to)

    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="shipments_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'

    writer = csv.writer(response)

    # Write header
    writer.writerow([
        'Tracking Number',
        'Order ID',
        'Status',
        'Created Date',
        'Pickup Time',
        'Delivery Time',
        'Destination Address',
        'City',
        'Region',
        'Country',
        'Driver',
        'Driver Phone',
        'Vehicle',
        'Warehouse',
        'Weight (kg)',
        'Volume (m³)',
        'Shipment Type',
        'Material Type',
        'Cost',
        'Boxes',
    ])

    # Write data rows
    for shipment in shipments:
        writer.writerow([
            shipment.tracking_number or f'#{shipment.id}',
            shipment.order.id if shipment.order else '',
            shipment.get_status_display(),
            shipment.created_at.strftime('%Y-%m-%d %H:%M'),
            shipment.collect_time.strftime('%Y-%m-%d %H:%M') if shipment.collect_time else '',
            shipment.actual_dropoff_time.strftime('%Y-%m-%d %H:%M') if shipment.actual_dropoff_time else '',
            shipment.shipping_address.address if shipment.shipping_address else '',
            shipment.shipping_address.city if shipment.shipping_address else '',
            shipment.shipping_address.region if shipment.shipping_address else '',
            shipment.shipping_address.country if shipment.shipping_address else '',
            shipment.driver.user.get_full_name() if shipment.driver else 'Unassigned',
            shipment.driver.phone if shipment.driver else '',
            shipment.vehicle.plate_number if shipment.vehicle else 'None',
            shipment.warehouse.name if shipment.warehouse else '',
            float(shipment.weight_kg),
            float(shipment.size_cubic_meters),
            shipment.get_shipment_type_display(),
            shipment.get_material_type_display(),
            float(shipment.cost) if shipment.cost else 0,
            shipment.boxes.count(),
        ])

    return response


@login_required
def export_shipments_excel(request):
    """
    Export shipments to Excel format with formatting.
    Creates a professional Excel workbook with multiple sheets.
    """
    # Get filter parameters
    status = request.GET.get('status', '')
    driver_id = request.GET.get('driver_id', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    # Build queryset
    shipments = Shipment.objects.select_related(
        'shipping_address', 'driver__user', 'vehicle', 'warehouse', 'order'
    ).order_by('-created_at')

    # Apply filters
    if status:
        shipments = shipments.filter(status=status)
    if driver_id:
        shipments = shipments.filter(driver_id=driver_id)
    if date_from:
        shipments = shipments.filter(created_at__date__gte=date_from)
    if date_to:
        shipments = shipments.filter(created_at__date__lte=date_to)

    # Create workbook
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Shipments"

    # Define styles
    header_font = Font(bold=True, color="FFFFFF", size=12)
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center")

    # Write header
    headers = [
        'Tracking Number', 'Order ID', 'Status', 'Created Date',
        'Pickup Time', 'Delivery Time', 'Destination', 'City', 'Region',
        'Driver', 'Driver Phone', 'Vehicle', 'Warehouse',
        'Weight (kg)', 'Volume (m³)', 'Type', 'Material', 'Cost', 'Boxes'
    ]

    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_num)
        cell.value = header
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment

    # Write data
    for row_num, shipment in enumerate(shipments, 2):
        ws.cell(row=row_num, column=1, value=shipment.tracking_number or f'#{shipment.id}')
        ws.cell(row=row_num, column=2, value=shipment.order.id if shipment.order else '')
        ws.cell(row=row_num, column=3, value=shipment.get_status_display())
        ws.cell(row=row_num, column=4, value=shipment.created_at.strftime('%Y-%m-%d %H:%M'))
        ws.cell(row=row_num, column=5,
                value=shipment.collect_time.strftime('%Y-%m-%d %H:%M') if shipment.collect_time else '')
        ws.cell(row=row_num, column=6,
                value=shipment.actual_dropoff_time.strftime('%Y-%m-%d %H:%M') if shipment.actual_dropoff_time else '')
        ws.cell(row=row_num, column=7, value=shipment.shipping_address.address if shipment.shipping_address else '')
        ws.cell(row=row_num, column=8, value=shipment.shipping_address.city if shipment.shipping_address else '')
        ws.cell(row=row_num, column=9, value=shipment.shipping_address.region if shipment.shipping_address else '')
        ws.cell(row=row_num, column=10, value=shipment.driver.user.get_full_name() if shipment.driver else 'Unassigned')
        ws.cell(row=row_num, column=11, value=shipment.driver.phone if shipment.driver else '')
        ws.cell(row=row_num, column=12, value=shipment.vehicle.plate_number if shipment.vehicle else 'None')
        ws.cell(row=row_num, column=13, value=shipment.warehouse.name if shipment.warehouse else '')
        ws.cell(row=row_num, column=14, value=float(shipment.weight_kg))
        ws.cell(row=row_num, column=15, value=float(shipment.size_cubic_meters))
        ws.cell(row=row_num, column=16, value=shipment.get_shipment_type_display())
        ws.cell(row=row_num, column=17, value=shipment.get_material_type_display())
        ws.cell(row=row_num, column=18, value=float(shipment.cost) if shipment.cost else 0)
        ws.cell(row=row_num, column=19, value=shipment.boxes.count())

    # Auto-adjust column widths
    for column in ws.columns:
        max_length = 0
        column_letter = get_column_letter(column[0].column)
        for cell in column:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(cell.value)
            except:
                pass
        adjusted_width = min(max_length + 2, 50)
        ws.column_dimensions[column_letter].width = adjusted_width

    # Add summary sheet
    summary_ws = wb.create_sheet("Summary")
    summary_ws.cell(row=1, column=1, value="Summary Statistics")
    summary_ws.cell(row=1, column=1).font = Font(bold=True, size=14)

    summary_ws.cell(row=3, column=1, value="Total Shipments:")
    summary_ws.cell(row=3, column=2, value=shipments.count())

    summary_ws.cell(row=4, column=1, value="Delivered:")
    summary_ws.cell(row=4, column=2, value=shipments.filter(status='delivered').count())

    summary_ws.cell(row=5, column=1, value="In Transit:")
    summary_ws.cell(row=5, column=2, value=shipments.filter(status='in_transit').count())

    summary_ws.cell(row=6, column=1, value="Pending:")
    summary_ws.cell(row=6, column=2, value=shipments.filter(status='pending').count())

    # Create HTTP response
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response[
        'Content-Disposition'] = f'attachment; filename="shipments_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'

    wb.save(response)
    return response


# ============================================================================
# HELPER FUNCTION
# ============================================================================

def get_column_letter(col_idx):
    """Convert column index to Excel column letter (1 -> A, 27 -> AA, etc.)"""
    result = ""
    while col_idx > 0:
        col_idx -= 1
        result = chr(col_idx % 26 + 65) + result
        col_idx //= 26
    return result
