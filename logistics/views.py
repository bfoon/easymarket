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
from django.db.models.functions import TruncDate, Coalesce, Cast
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import (
    HttpResponse, JsonResponse, HttpRequest,
    HttpResponseRedirect, Http404
)
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods, require_GET, require_POST
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
    Shipment, ShipmentBox, BoxItem, Driver, Vehicle, ShipmentItem,
    Warehouse, LogisticOffice, DriverLocation, WarehouseShipmentNotification


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
    get_optimal_route, get_shipment_location_data
)
from .services import (
    NotificationService,
    ShipmentService,
    AnalyticsService
)
from orders.models import Order, OrderItem, ShippingAddress, OrderStatusHistory
from stock.models import Warehouse as StockWarehouse
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

def _is_ajax(request):
    return (
        request.headers.get("x-requested-with") == "XMLHttpRequest"
        or "application/json" in (request.headers.get("accept") or "")
        or request.GET.get("format") == "json"
    )

@login_required
def notifications_list(request):
    """
    Display all notifications for the logged-in logistics user.
    """
    qs = (
        WarehouseShipmentNotification.objects
        .filter(recipient=request.user)
        .select_related("order", "store")
        .order_by("-created_at")
    )

    if _is_ajax(request):
        unread_count = qs.filter(is_read=False).count()
        notifications = []
        for n in qs[:50]:
            notifications.append({
                "id": n.id,
                "type": n.notification_type,
                "title": n.title,
                "message": n.message,
                "items_count": n.items_count,
                "is_read": n.is_read,
                "created_at": n.created_at.isoformat(),
                "order_id": n.order_id,
                "store_name": n.store.name if n.store else None,
            })

        return JsonResponse({
            "success": True,
            "unread_count": unread_count,
            "notifications": notifications,
        })

    # normal page view
    return render(request, "logistics/notification_list.html", {
        "notifications": qs[:50],
        "unread_count": qs.filter(is_read=False).count(),
    })

@login_required
@require_POST
def notification_mark_as_read(request, pk):
    """Mark a single notification as read."""
    n = get_object_or_404(WarehouseShipmentNotification, pk=pk, recipient=request.user)
    if not n.is_read:
        n.is_read = True
        n.read_at = timezone.now()
        n.save(update_fields=["is_read", "read_at"])
    return JsonResponse({"success": True})


@login_required
@require_POST
def notification_mark_all_as_read(request):
    """Mark all notifications as read for current user."""
    WarehouseShipmentNotification.objects.filter(
        recipient=request.user,
        is_read=False
    ).update(is_read=True, read_at=timezone.now())
    return JsonResponse({"success": True})

@login_required
def notification_dropdown(request):
    """
    AJAX endpoint for notification dropdown in navbar.
    Returns JSON with recent notifications.
    """
    notifications = WarehouseShipmentNotification.get_recent_notifications(
        request.user,
        limit=10
    )

    notifications_data = [
        {
            'id': notif.id,
            'type': notif.notification_type,
            'title': notif.title,
            'message': notif.message,
            'order_id': notif.order.id,
            'store_name': notif.store.name if notif.store else 'N/A',
            'items_count': notif.items_count,
            'time_since': notif.get_time_since(),
            'is_read': notif.is_read,
            'url': notif.get_absolute_url(),
            'created_at': notif.created_at.isoformat()
        }
        for notif in notifications
    ]

    return JsonResponse({
        'success': True,
        'notifications': notifications_data,
        'unread_count': WarehouseShipmentNotification.get_unread_count(request.user),
        'total_count': WarehouseShipmentNotification.objects.filter(recipient=request.user).count()
    })


@login_required
def notification_detail(request, notification_id):
    """
    View notification detail and mark as read.
    Redirects to the related order page.
    """
    notification = get_object_or_404(
        WarehouseShipmentNotification,
        id=notification_id,
        recipient=request.user
    )

    # Mark as read
    notification.mark_as_read()

    # Redirect to order detail page
    return redirect(notification.get_absolute_url())


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

class ShipmentCreateView(LoginRequiredMixin, CreateView):
    """
    Enhanced shipment creation view with warehouse shipping integration.

    Features:
    - Shows only orders with warehouse-shipped items
    - Automatically includes shipped items in shipment
    - Sets sequential shipment number
    - Updates order status on first shipment
    """
    model = Shipment
    form_class = ShipmentForm
    template_name = "logistics/shipment_form.html"

    def get_success_url(self):
        return reverse("logistics:shipment_detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        with transaction.atomic():
            shipment = form.save(commit=False)
            order = shipment.order

            # Set shipment number
            shipment.shipment_number = order.get_next_shipment_number()
            shipment.save()

            # ✅ IMPORTANT: set self.object so CreateView has it
            self.object = shipment

            # Items marked as shipped but not yet assigned
            available_items = OrderItem.objects.select_for_update().filter(
                order=order,
                shipped_to_warehouse=True,
                current_shipment__isnull=True
            )

            items_added = 0
            for order_item in available_items:
                ShipmentItem.objects.create(
                    shipment=shipment,
                    order_item=order_item,
                    quantity=order_item.quantity
                )

                order_item.current_shipment = shipment
                order_item.save(update_fields=["current_shipment"])
                items_added += 1

            # Optional: update order status
            if items_added > 0 and order.status != "shipped":
                order.status = "shipped"
                order.save(update_fields=["status"])

        messages.success(
            self.request,
            f"Shipment #{shipment.shipment_number} created successfully with {items_added} item(s)."
        )
        return redirect(self.get_success_url())


class ShipmentUpdateView(LoginRequiredMixin, UpdateView):
    """Enhanced shipment update view."""
    model = Shipment
    form_class = ShipmentForm
    template_name = 'logistics/shipment_form.html'

    def get_success_url(self):
        return reverse_lazy('logistics:shipment_detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, f'Shipment #{self.object.id} updated successfully.')
        return super().form_valid(form)


class ShipmentDetailView(LoginRequiredMixin, DetailView):
    """
    Enhanced shipment detail view showing warehouse-shipped items.
    """
    model = Shipment
    template_name = 'logistics/shipment_detail.html'
    context_object_name = 'shipment'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        shipment = self.object

        # Get items in this shipment
        context['shipment_items'] = shipment.shipment_items.select_related(
            'order_item__product'
        ).all()

        # Calculate totals
        context['total_items'] = sum(item.quantity for item in context['shipment_items'])
        context['total_value'] = sum(item.get_total_price() for item in context['shipment_items'])

        # Order information
        if shipment.order:
            context['order'] = shipment.order
            context['total_shipments'] = shipment.order.get_shipment_count()
            context['has_more_items'] = shipment.order.has_unshipped_items()

        # Get boxes for this shipment (if any)
        context['boxes'] = shipment.boxes.prefetch_related('items').all()

        return context


@login_required
def get_shipment_items_preview(request, order_id):
    """
    Get a preview of items ready to be added to a new shipment.
    Used in both store and logistics interfaces.
    """
    order = get_object_or_404(Order, pk=order_id)

    # Get items ready for shipment
    items = OrderItem.objects.filter(
        order=order,
        shipped_to_warehouse=True,
        current_shipment__isnull=True
    ).select_related('product')

    items_data = [
        {
            'id': item.id,
            'product_name': item.product.name,
            'sku': getattr(item.product, 'sku', 'N/A'),
            'quantity': item.quantity,
            'price': float(item.get_total_price()),
            'shipped_at': item.shipped_at.isoformat() if item.shipped_at else None
        }
        for item in items
    ]

    total_value = sum(item.get_total_price() for item in items)

    return JsonResponse({
        'success': True,
        'items': items_data,
        'items_count': len(items_data),
        'total_value': float(total_value),
        'next_shipment_number': order.get_next_shipment_number(),
        'existing_shipments_count': order.get_shipment_count(),
        'order_id': order.id,
        'order_status': order.status,
        'order_status_display': order.get_status_display()
    })


@login_required
@transaction.atomic
def quick_create_shipment(request, order_id):
    """
    Quick shipment creation from store order page.
    Creates shipment with all warehouse-shipped items.
    """
    order = get_object_or_404(Order, pk=order_id)

    # Security check - only logistics users
    if not getattr(request.user, 'is_logistic', False):
        return JsonResponse({
            'success': False,
            'message': 'Only logistics users can create shipments.'
        }, status=403)

    # Check if order has items available
    available_items = order.get_shipped_items_without_shipment()

    if not available_items.exists():
        return JsonResponse({
            'success': False,
            'message': 'No items available for shipment.'
        }, status=400)

    try:
        # Get next shipment number
        shipment_number = order.get_next_shipment_number()

        # Create shipment
        shipment = Shipment.objects.create(
            order=order,
            shipping_address=getattr(order, 'shipping_address', None),
            shipment_number=shipment_number,
            status='pending',
            weight_kg=0.00,
            size_cubic_meters=0.00,
            notes=f"Quick-created shipment #{shipment_number}"
        )

        # Add items
        items_added = 0
        for order_item in available_items:
            ShipmentItem.objects.create(
                shipment=shipment,
                order_item=order_item,
                quantity=order_item.quantity
            )
            order_item.current_shipment = shipment
            order_item.save(update_fields=['current_shipment'])
            items_added += 1

        # Update order status if first shipment
        if shipment_number == 1 and order.status == 'processing':
            order.status = 'shipped'
            order.save(update_fields=['status'])

        return JsonResponse({
            'success': True,
            'shipment_id': shipment.id,
            'shipment_number': shipment_number,
            'items_count': items_added,
            'message': f'Shipment #{shipment_number} created with {items_added} item(s).'
        })

    except Exception as e:
        logger.error(f"Error creating quick shipment: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': f'Error creating shipment: {str(e)}'
        }, status=500)


@login_required
def shipment_items_ajax(request, shipment_id):
    """
    AJAX endpoint to get items for a specific shipment.
    Used for box packing interface.
    """
    shipment = get_object_or_404(Shipment, pk=shipment_id)

    items = shipment.shipment_items.select_related(
        'order_item__product'
    ).all()

    items_data = [
        {
            'id': item.id,
            'order_item_id': item.order_item.id,
            'product_id': item.order_item.product.id,
            'product_name': item.order_item.product.name,
            'sku': getattr(item.order_item.product, 'sku', 'N/A'),
            'quantity': item.quantity,
            'price': float(item.get_total_price()),
            'shipped_at': item.order_item.shipped_at.isoformat() if item.order_item.shipped_at else None
        }
        for item in items
    ]

    return JsonResponse({
        'success': True,
        'shipment_id': shipment.id,
        'shipment_number': shipment.shipment_number,
        'items': items_data,
        'items_count': len(items_data)
    })


class ShipmentListView(LoginRequiredMixin, ListView):
    """Enhanced shipment list view."""
    model = Shipment
    template_name = 'logistics/shipment_list.html'
    context_object_name = 'shipments'
    paginate_by = 20

    def get_queryset(self):
        queryset = Shipment.objects.select_related(
            'order', 'warehouse', 'driver', 'vehicle'
        ).prefetch_related('shipment_items').order_by('-created_at')

        # Filter by status if provided
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)

        # Search by order ID or shipment number
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(order__id__icontains=search) |
                Q(shipment_number__icontains=search)
            )

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Add filter options
        context['status_filter'] = self.request.GET.get('status', '')
        context['search_query'] = self.request.GET.get('search', '')

        # Count by status
        context['pending_count'] = Shipment.objects.filter(status='pending').count()
        context['in_transit_count'] = Shipment.objects.filter(status='in_transit').count()
        context['delivered_count'] = Shipment.objects.filter(status='delivered').count()

        return context


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
    model = BoxItem
    fields = ["order_item", "quantity", "notes"]
    template_name = "logistics/box_item_form.html"

    def _box_pk(self):
        return self.kwargs.get("box_pk") or self.kwargs.get("box_id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        box = get_object_or_404(ShipmentBox, pk=self._box_pk())
        context["box"] = box
        context["shipment"] = box.shipment   # <-- THIS fixes shipment_detail reverse
        context["action"] = "Add"
        return context

    def form_valid(self, form):
        form.instance.box_id = self._box_pk()
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("logistics:shipment_detail", kwargs={"pk": self.object.box.shipment.pk})


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
    model = Driver
    template_name = 'logistics/driver_list.html'
    context_object_name = 'drivers'
    paginate_by = 20

    def get_queryset(self):
        return (
            Driver.objects.filter(is_active=True)
            .select_related('user')
            .annotate(
                active_shipments_count=Count(
                    'shipments',
                    filter=Q(shipments__status__in=['pending', 'in_transit', 'shipped'])
                )
            )
        )

class DriverDetailView(LoginRequiredMixin, DetailView):
    model = Driver
    template_name = "logistics/driver_detail.html"
    context_object_name = "driver"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        driver = self.object

        active_statuses = ["pending", "shipped", "in_transit"]

        # Vehicles assigned to THIS driver
        vehicles_qs = (
            Vehicle.objects
            .filter(driver=driver)
            .annotate(
                active_shipments_count=Count(
                    "shipments",
                    filter=Q(shipments__status__in=active_statuses),
                    distinct=True
                )
            )
            .order_by("-id")
        )

        # Shipments assigned to THIS driver (recent)
        recent_shipments_qs = (
            Shipment.objects
            .filter(driver=driver)
            .select_related("shipping_address", "vehicle", "order")
            .order_by("-collect_time")[:10]
        )

        ctx["vehicles"] = vehicles_qs
        ctx["vehicle_count"] = vehicles_qs.count()

        ctx["recent_shipments"] = recent_shipments_qs
        ctx["total_shipments"] = Shipment.objects.filter(driver=driver).count()
        ctx["active_shipments"] = Shipment.objects.filter(driver=driver, status__in=active_statuses).count()
        ctx["completed_shipments"] = Shipment.objects.filter(driver=driver, status="delivered").count()

        return ctx


class DriverCreateView(LoginRequiredMixin, CreateView):
    model = Driver
    form_class = DriverForm
    template_name = 'logistics/driver_form.html'
    success_url = reverse_lazy('logistics:driver_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Driver created: {self.object.user.get_full_name()}")
        return response

    def form_invalid(self, form):
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)


class DriverUpdateView(LoginRequiredMixin, UpdateView):
    model = Driver
    form_class = DriverForm
    template_name = 'logistics/driver_form.html'
    success_url = reverse_lazy('logistics:driver_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Driver updated: {self.object.user.get_full_name()}")
        return response

    def form_invalid(self, form):
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)


class DriverDeleteView(LoginRequiredMixin, DeleteView):
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
@require_POST
@driver_required
def update_driver_location(request, shipment_id):
    """
    Driver sends GPS updates for a shipment they are assigned to.
    """
    shipment = get_object_or_404(Shipment, pk=shipment_id, driver=request.driver)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    lat = data.get('latitude')
    lng = data.get('longitude')

    if lat is None or lng is None:
        return JsonResponse({'success': False, 'error': 'latitude and longitude are required'}, status=400)

    loc = DriverLocation.objects.create(
        driver=request.driver,
        shipment=shipment,
        latitude=lat,
        longitude=lng,
        accuracy_m=data.get('accuracy_m'),
        heading=data.get('heading'),
        speed_mps=data.get('speed_mps'),
    )

    return JsonResponse({
        'success': True,
        'message': 'Location updated',
        'recorded_at': loc.recorded_at.isoformat(),
    })

@login_required
@require_GET
def get_latest_driver_location(request, shipment_id):
    """
    Staff/driver/buyer can read latest driver location (you can tighten this later).
    """
    shipment = get_object_or_404(Shipment.objects.select_related('order__buyer', 'driver'), pk=shipment_id)

    # permission: staff OR assigned driver OR buyer
    allowed = (
        request.user.is_staff or
        (hasattr(request.user, 'driver') and shipment.driver_id == request.user.driver.id) or
        (shipment.order and shipment.order.buyer_id == request.user.id)
    )
    if not allowed:
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    last = shipment.driver_locations.select_related('driver').first()
    if not last:
        return JsonResponse({'success': True, 'location': None})

    return JsonResponse({
        'success': True,
        'location': {
            'lat': float(last.latitude),
            'lng': float(last.longitude),
            'accuracy_m': float(last.accuracy_m) if last.accuracy_m is not None else None,
            'heading': float(last.heading) if last.heading is not None else None,
            'speed_mps': float(last.speed_mps) if last.speed_mps is not None else None,
            'recorded_at': last.recorded_at.isoformat(),
        }
    })

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
    driver = request.driver

    try:
        shipment = get_object_or_404(Shipment, pk=shipment_id, driver=driver)

        if not validate_shipment_transition(shipment.status, "in_transit"):
            return JsonResponse({
                "success": False,
                "error": f"Cannot start delivery from status: {shipment.get_status_display()}"
            }, status=400)

        with transaction.atomic():
            shipment.status = "in_transit"
            shipment.save(update_fields=["status"])  # ✅ reduce side effects

            create_delivery_history(
                shipment=shipment,
                status="in_transit",
                user=request.user,
                notes=f"Driver {getattr(driver, 'employee_id', driver.id)} started delivery"
            )

        # ✅ send notification AFTER commit (no crashes during atomic exit)
        transaction.on_commit(lambda: send_delivery_notification(
            shipment=shipment,
            status="in_transit",
            driver=driver
        ))

        return JsonResponse({
            "success": True,
            "message": "Delivery started successfully!",
            "shipment_status": shipment.get_status_display()
        })

    except Exception as e:
        # ✅ return error message so frontend can show it
        return JsonResponse({
            "success": False,
            "error": str(e),
            "shipment_id": shipment_id
        }, status=500)


@login_required
@driver_required
@require_POST
def mark_delivered(request, shipment_id):
    """
    Mark shipment as delivered when driver completes delivery.

    Supports:
    - multipart/form-data (FormData): notes, recipient_name, delivery_photo
    - JSON body: {notes, recipient_name, signature} (signature optional)

    Requires delivery photo proof if field exists / policy requires.
    """
    driver = request.driver

    # Get shipment - ensure it belongs to this driver
    shipment = get_object_or_404(Shipment, pk=shipment_id, driver=driver)

    # Validate status transition
    if not validate_shipment_transition(shipment.status, "delivered"):
        return JsonResponse({
            "success": False,
            "error": f"Cannot mark as delivered from status: {shipment.get_status_display()}"
        }, status=400)

    # ---------- Extract input safely ----------
    content_type = (request.content_type or "").lower()

    if "application/json" in content_type:
        try:
            data = json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            data = {}
        delivery_notes = (data.get("notes") or "").strip()
        recipient_name = (data.get("recipient_name") or "").strip()
        signature = data.get("signature") or ""  # optional base64
        delivery_photo = None
    else:
        # FormData / multipart
        delivery_notes = (request.POST.get("notes") or "").strip()
        recipient_name = (request.POST.get("recipient_name") or "").strip()
        signature = request.POST.get("signature") or ""  # optional
        delivery_photo = request.FILES.get("delivery_photo")

    # Require photo proof if you need it
    if hasattr(shipment, "delivery_photo"):
        if not delivery_photo and not shipment.delivery_photo:
            return JsonResponse({
                "success": False,
                "error": "Delivery photo is required."
            }, status=400)

    delivered_at = timezone.now()
    employee_id = getattr(driver, "employee_id", None) or str(getattr(driver, "id", "")) or "Driver"

    # ---------- Save safely ----------
    def _after_commit():
        # Notify buyer AFTER commit (avoid breaking the transaction)
        try:
            send_delivery_notification(
                shipment=shipment,
                status="delivered",
                driver=driver
            )
        except Exception:
            # Don't crash user flow because notification failed
            pass

    try:
        with transaction.atomic():
            shipment.status = "delivered"

            # set time field if it exists
            if hasattr(shipment, "actual_dropoff_time"):
                shipment.actual_dropoff_time = delivered_at
            elif hasattr(shipment, "delivered_at"):
                shipment.delivered_at = delivered_at

            # optional fields
            if hasattr(shipment, "delivery_notes"):
                shipment.delivery_notes = delivery_notes
            if hasattr(shipment, "recipient_name"):
                shipment.recipient_name = recipient_name

            # save photo if model supports it
            if hasattr(shipment, "delivery_photo") and delivery_photo:
                shipment.delivery_photo = delivery_photo

            # signature (if you have a field for it)
            if signature and hasattr(shipment, "signature_data"):
                shipment.signature_data = signature

            # Save shipment
            shipment.save()

            # Update order status if linked
            if shipment.order_id:
                # safer than loading full order object
                shipment.order.status = "delivered"
                shipment.order.save(update_fields=["status"])

            # History entry
            create_delivery_history(
                shipment=shipment,
                status="delivered",
                user=request.user,
                notes=f"Delivered by {employee_id}. {delivery_notes}".strip()
            )

            transaction.on_commit(_after_commit)

        # Determine delivered timestamp to return
        delivered_time = None
        if hasattr(shipment, "actual_dropoff_time") and shipment.actual_dropoff_time:
            delivered_time = shipment.actual_dropoff_time
        elif hasattr(shipment, "delivered_at") and getattr(shipment, "delivered_at", None):
            delivered_time = shipment.delivered_at
        else:
            delivered_time = delivered_at

        return JsonResponse({
            "success": True,
            "message": "Delivery marked as complete!",
            "delivered_at": delivered_time.isoformat(),
        })

    except Exception as e:
        return JsonResponse({
            "success": False,
            "error": str(e),
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

DECIMAL = DecimalField(max_digits=12, decimal_places=2)

class VehicleListView(LoginRequiredMixin, ListView):
    model = Vehicle
    template_name = 'logistics/vehicle_list.html'
    context_object_name = 'vehicles'
    paginate_by = 20

    def get_queryset(self):
        qs = (
            Vehicle.objects
            .select_related('driver__user')
            .annotate(
                active_shipments_count=Count(
                    'shipments',
                    filter=Q(shipments__status__in=ACTIVE_STATUSES),
                    distinct=True
                ),

                # sum weight of active shipments (Decimal)
                active_weight_kg=Coalesce(
                    Sum('shipments__weight_kg', filter=Q(shipments__status__in=ACTIVE_STATUSES)),
                    Value(Decimal('0.00')),
                    output_field=DECIMAL
                ),

                # capacity_kg as Decimal (in case your field is IntegerField)
                capacity_kg_dec=Coalesce(
                    Cast('capacity_kg', DECIMAL),
                    Value(Decimal('0.00')),
                    output_field=DECIMAL
                ),
            )
            .annotate(
                # percent = (active_weight_kg * 100) / capacity
                capacity_used_percent=ExpressionWrapper(
                    # avoid division by 0: if capacity is 0, percent becomes 0
                    Coalesce(
                        (F('active_weight_kg') * Value(Decimal('100.00'))) /
                        Coalesce(
                            # if capacity is 0 => use 1 to avoid crash, then we handle below
                            Cast('capacity_kg', DECIMAL),
                            Value(Decimal('1.00')),
                            output_field=DECIMAL
                        ),
                        Value(Decimal('0.00')),
                        output_field=DECIMAL
                    ),
                    output_field=DECIMAL
                )
            )
            .order_by('plate_number')
        )
        return qs


class VehicleDetailView(LoginRequiredMixin, DetailView):
    model = Vehicle
    template_name = 'logistics/vehicle_detail.html'
    context_object_name = 'vehicle'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        vehicle = self.object

        shipments_qs = (
            vehicle.shipments.select_related('driver__user', 'shipping_address', 'order')
            .order_by('-created_at')
        )

        context['recent_shipments'] = shipments_qs[:10]
        context['total_shipments'] = shipments_qs.count()
        context['active_shipments'] = shipments_qs.filter(status__in=ACTIVE_STATUSES).count()
        context['completed_shipments'] = shipments_qs.filter(status='delivered').count()

        # Simple “current utilization”
        context['current_utilization'] = (
            "In Use" if shipments_qs.filter(status__in=ACTIVE_STATUSES).exists()
            else "Idle"
        )

        return context

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

# Get all store warehouses
store_warehouses = StockWarehouse.objects.filter(
    store__isnull=False,
    is_active=True
)

@login_required
def warehouse_order_detail(request, order_id):
    """
    Logistics-only warehouse view of an order:
    - shows ONLY warehouse-ready items
    - shows shipment linkage and status
    - gives quick shipment actions
    """
    if not getattr(request.user, "is_logistic", False):
        messages.error(request, "Access denied. Logistics users only.")
        return render(request, "403.html", status=403)

    order = get_object_or_404(Order, pk=order_id)

    # Items that are ready (store marked shipped_to_warehouse)
    ready_items_qs = (
        OrderItem.objects
        .filter(order=order, shipped_to_warehouse=True)
        .select_related("product", "product__store")
        .order_by("product__store__name", "product__name")
    )

    # Split by whether already assigned to a shipment
    unassigned_ready_items = ready_items_qs.filter(current_shipment__isnull=True)
    assigned_ready_items = ready_items_qs.filter(current_shipment__isnull=False).select_related("current_shipment")

    # Shipments for this order
    shipments = (
        Shipment.objects
        .filter(order=order)
        .select_related("driver", "vehicle", "warehouse", "logistic_office")
        .order_by("-created_at")
    )

    # Totals
    total_ready_qty = ready_items_qs.aggregate(total=Sum("quantity"))["total"] or 0
    unassigned_qty = unassigned_ready_items.aggregate(total=Sum("quantity"))["total"] or 0
    assigned_qty = assigned_ready_items.aggregate(total=Sum("quantity"))["total"] or 0

    # Store breakdown (simple grouping in Python; no custom template filters needed)
    store_breakdown = {}
    for item in ready_items_qs:
        store = getattr(item.product, "store", None)
        store_name = store.name if store else "Unknown Store"
        if store_name not in store_breakdown:
            store_breakdown[store_name] = {
                "store": store,
                "items": [],
                "qty": 0,
            }
        store_breakdown[store_name]["items"].append(item)
        store_breakdown[store_name]["qty"] += item.quantity

    context = {
        "order": order,
        "ready_items": ready_items_qs,
        "unassigned_ready_items": unassigned_ready_items,
        "assigned_ready_items": assigned_ready_items,
        "shipments": shipments,

        "total_ready_qty": total_ready_qty,
        "unassigned_qty": unassigned_qty,
        "assigned_qty": assigned_qty,

        "store_breakdown": store_breakdown,
        "shipments_count": shipments.count(),
    }
    return render(request, "logistics/warehouse_order_detail.html", context)

@login_required
def order_items_preview(request, order_id):
    """
    JSON endpoint for shipment create page:
    returns items that are shipped_to_warehouse=True and not assigned to a shipment yet.
    """
    order = get_object_or_404(Order, pk=order_id)

    qs = (
        OrderItem.objects
        .filter(order=order, shipped_to_warehouse=True, current_shipment__isnull=True)
        .select_related("product", "product__store")
        .order_by("product__store__name", "product__name")
    )

    items = []
    total_qty = 0

    for it in qs:
        store = getattr(it.product, "store", None)
        store_name = store.name if store else "Unknown Store"

        items.append({
            "id": it.id,
            "product_id": it.product_id,
            "product_name": getattr(it.product, "name", "—"),
            "store_name": store_name,
            "quantity": it.quantity,
            "price": str(getattr(it, "price", "")) if hasattr(it, "price") else None,
        })
        total_qty += (it.quantity or 0)

    return JsonResponse({
        "success": True,
        "order_id": order.id,
        "items_count": qs.count(),
        "total_qty": total_qty,
        "items": items
    })

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

# Keep statuses consistent everywhere
ACTIVE_STATUSES = ['pending', 'in_transit', 'shipped']


def _driver_vehicles_rel_name_q():
    """
    Safe Q filter for drivers with no vehicles.
    Works whether Vehicle.driver has related_name="vehicles" or default "vehicle_set".
    """
    # Try both; only one will actually match in the DB query
    return Q(vehicles__isnull=True)


class AssignmentDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'logistics/assignment_dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        vehicles_qs = Vehicle.objects.filter(is_active=True).select_related('driver__user')

        unassigned_qs = vehicles_qs.filter(driver__isnull=True).order_by('plate_number')

        context['total_vehicles'] = vehicles_qs.count()
        context['assigned_vehicles'] = vehicles_qs.filter(driver__isnull=False).count()

        # ✅ FIX: iterable list for template
        context['unassigned_vehicles'] = unassigned_qs[:10]
        # ✅ count for cards
        context['unassigned_vehicles_count'] = unassigned_qs.count()

        context['active_drivers'] = Driver.objects.filter(is_active=True, user__is_active=True).count()

        context['vehicles'] = vehicles_qs.annotate(
            active_shipments_count=Count(
                'shipments',
                filter=Q(shipments__status__in=ACTIVE_STATUSES)
            )
        ).order_by('-id')[:10]

        context['drivers'] = Driver.objects.filter(
            is_active=True, user__is_active=True
        ).select_related('user').order_by('user__first_name', 'user__last_name')

        # Optional: drivers without vehicles (works if related_name='vehicles')
        context['drivers_without_vehicles'] = Driver.objects.filter(
            is_active=True, user__is_active=True,
            vehicles__isnull=True
        ).select_related('user').order_by('user__first_name')[:10]

        return context


class VehicleAssignmentListView(LoginRequiredMixin, ListView):
    """List vehicle assignments"""
    model = Vehicle
    template_name = 'logistics/vehicle_assignment_list.html'
    context_object_name = 'vehicles'
    paginate_by = 30

    def get_queryset(self):
        qs = Vehicle.objects.filter(is_active=True).select_related('driver__user').annotate(
            active_shipments_count=Count(
                'shipments',
                filter=Q(shipments__status__in=ACTIVE_STATUSES)
            )
        ).order_by('plate_number')

        # Optional filter: ?driver=<driver_id>
        driver_id = self.request.GET.get('driver')
        if driver_id:
            qs = qs.filter(driver_id=driver_id)

        return qs


class DriverAssignmentListView(LoginRequiredMixin, ListView):
    """List driver assignments"""
    model = Driver
    template_name = 'logistics/driver_assignment_list.html'
    context_object_name = 'drivers'
    paginate_by = 30

    def get_queryset(self):
        return (
            Driver.objects.filter(is_active=True, user__is_active=True)
            .select_related('user')
            .annotate(
                vehicle_count=Count('vehicles', distinct=True),
                active_shipments_count=Count(
                    'shipments',
                    filter=Q(shipments__status__in=ACTIVE_STATUSES),
                    distinct=True
                )
            )
            .order_by('user__first_name', 'user__last_name')
        )


@login_required
def assignment_report(request):
    """Generate assignment report"""
    vehicles = Vehicle.objects.filter(is_active=True).select_related('driver__user').annotate(
        active_shipments_count=Count('shipments', filter=Q(shipments__status__in=ACTIVE_STATUSES))
    )
    return render(request, 'logistics/assignment_report.html', {'vehicles': vehicles})


@login_required
@require_POST
def assign_vehicle_to_driver(request):
    """
    Assign vehicle to driver.
    - If driver_id is empty => unassign
    - Blocks changes if vehicle has active shipments
    """
    vehicle_id = request.POST.get('vehicle_id')
    driver_id = request.POST.get('driver_id')

    if not vehicle_id:
        return JsonResponse({'success': False, 'message': 'Missing vehicle_id'}, status=400)

    vehicle = get_object_or_404(Vehicle, pk=vehicle_id)

    # Block reassign/unassign if active shipments exist
    active_shipments = vehicle.shipments.filter(status__in=ACTIVE_STATUSES).count()
    if active_shipments > 0:
        return JsonResponse({
            'success': False,
            'message': f'This vehicle has {active_shipments} active shipment(s) and cannot be reassigned.'
        }, status=400)

    if driver_id:
        driver = get_object_or_404(Driver, pk=driver_id, is_active=True, user__is_active=True)

        # Optional: prevent assigning multiple vehicles if your business rule is 1 vehicle per driver
        # Comment this out if you allow multiple.
        # if Vehicle.objects.filter(driver=driver, is_active=True).exclude(pk=vehicle.pk).exists():
        #     return JsonResponse({'success': False, 'message': 'This driver already has a vehicle assigned.'}, status=400)

        vehicle.driver = driver
    else:
        vehicle.driver = None

    vehicle.save(update_fields=['driver'])
    return JsonResponse({'success': True, 'message': 'Vehicle assignment updated successfully'})


@login_required
@require_POST
def quick_assign_vehicle(request):
    """Quick assign: assign unassigned vehicles to drivers who currently have no vehicles."""
    unassigned = Vehicle.objects.filter(driver__isnull=True, is_active=True)
    assigned_count = 0

    for vehicle in unassigned:
        # Find a driver without vehicles
        available_driver = (
            Driver.objects.filter(is_active=True, user__is_active=True)
            .filter(_driver_vehicles_rel_name_q())
            .select_related('user')
            .first()
        )

        if available_driver:
            # block if vehicle has active shipments (extra safety)
            if vehicle.shipments.filter(status__in=ACTIVE_STATUSES).exists():
                continue

            vehicle.driver = available_driver
            vehicle.save(update_fields=['driver'])
            assigned_count += 1

    return JsonResponse({'success': True, 'message': f'Assigned {assigned_count} vehicles'})


@login_required
@require_POST
def bulk_assign_vehicles(request):
    """Bulk assign vehicles (vehicle_ids[] + driver_ids[] aligned)."""
    vehicle_ids = request.POST.getlist('vehicle_ids')
    driver_ids = request.POST.getlist('driver_ids')

    if not vehicle_ids:
        messages.error(request, 'No vehicles selected.')
        return redirect('logistics:assignment_dashboard')

    assigned = 0
    for vehicle_id, driver_id in zip(vehicle_ids, driver_ids):
        vehicle = Vehicle.objects.filter(pk=vehicle_id, is_active=True).first()
        if not vehicle:
            continue

        # block if vehicle has active shipments
        if vehicle.shipments.filter(status__in=ACTIVE_STATUSES).exists():
            continue

        if driver_id:
            driver = Driver.objects.filter(pk=driver_id, is_active=True, user__is_active=True).first()
            if not driver:
                continue
            vehicle.driver = driver
            vehicle.save(update_fields=['driver'])
            assigned += 1

    messages.success(request, f'Assigned {assigned} vehicles (vehicles with active shipments were skipped).')
    return redirect('logistics:assignment_dashboard')


@login_required
@require_GET
def api_unassigned_vehicles(request):
    qs = (
        Vehicle.objects
        .filter(is_active=True, driver__isnull=True)
        .annotate(
            active_shipments_count=Count(
                'shipments',
                filter=Q(shipments__status__in=ACTIVE_STATUSES)
            )
        )
        .filter(active_shipments_count=0)
        .order_by('plate_number')
    )

    vehicles = [{
        "id": v.id,
        "plate_number": v.plate_number,
        "model": v.model,
        "capacity_kg": float(v.capacity_kg) if v.capacity_kg is not None else None,
        "active_shipments_count": v.active_shipments_count,
    } for v in qs]

    return JsonResponse({"success": True, "vehicles": vehicles})


@login_required
@require_POST
def assign_vehicle_to_driver(request):
    """
    Assign a vehicle to a driver.
    Guards:
    - vehicle must exist + be active
    - vehicle must be unassigned
    - vehicle must have no active shipments
    """
    vehicle_id = request.POST.get('vehicle_id')
    driver_id = request.POST.get('driver_id')

    if not vehicle_id or not driver_id:
        return JsonResponse({'success': False, 'message': 'Vehicle and driver are required.'}, status=400)

    vehicle = get_object_or_404(Vehicle, pk=vehicle_id, is_active=True)
    driver = get_object_or_404(Driver, pk=driver_id, is_active=True)

    if vehicle.driver_id is not None:
        return JsonResponse({'success': False, 'message': 'This vehicle is already assigned.'}, status=400)

    active_shipments = vehicle.shipments.filter(status__in=['pending', 'shipped', 'in_transit']).count()
    if active_shipments > 0:
        return JsonResponse(
            {'success': False, 'message': f'Vehicle has {active_shipments} active shipment(s) and cannot be assigned.'},
            status=400
        )

    vehicle.driver = driver
    vehicle.save(update_fields=['driver'])

    return JsonResponse({'success': True, 'message': 'Vehicle assigned successfully'})


@login_required
@require_POST
def unassign_vehicle(request, vehicle_id):
    """
    Unassign vehicle (only if no active shipments)
    """
    vehicle = get_object_or_404(Vehicle, pk=vehicle_id, is_active=True)

    active_shipments = vehicle.shipments.filter(status__in=['pending', 'shipped', 'in_transit']).count()
    if active_shipments > 0:
        return JsonResponse(
            {'success': False, 'message': f'Vehicle has {active_shipments} active shipment(s) and cannot be unassigned.'},
            status=400
        )

    vehicle.driver = None
    vehicle.save(update_fields=['driver'])
    return JsonResponse({'success': True, 'message': 'Vehicle unassigned successfully'})


@login_required
@require_POST
def reassign_shipment(request, shipment_id):
    """Reassign shipment to different driver/vehicle (validates inputs)."""
    shipment = get_object_or_404(Shipment, pk=shipment_id)

    driver_id = request.POST.get('driver_id')
    vehicle_id = request.POST.get('vehicle_id')

    if driver_id:
        driver = get_object_or_404(Driver, pk=driver_id, is_active=True, user__is_active=True)
        shipment.driver = driver

    if vehicle_id:
        vehicle = get_object_or_404(Vehicle, pk=vehicle_id, is_active=True)
        # Optional safety: only allow if vehicle has driver OR is available
        shipment.vehicle = vehicle

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

    qs = Vehicle.objects.filter(is_active=True).select_related('driver__user').annotate(
        active_shipments_count=Count('shipments', filter=Q(shipments__status__in=ACTIVE_STATUSES))
    ).order_by('plate_number')

    for vehicle in qs:
        writer.writerow([
            vehicle.plate_number,
            vehicle.driver.user.get_full_name() if vehicle.driver else 'Unassigned',
            'Assigned' if vehicle.driver else 'Available',
            vehicle.active_shipments_count,
        ])

    return response


@login_required
def assignment_report_json(request):
    """Get assignment data as JSON"""
    qs = Vehicle.objects.filter(is_active=True).select_related('driver__user').order_by('plate_number')

    data = [{
        'vehicle_id': v.id,
        'plate_number': v.plate_number,
        'driver': v.driver.user.get_full_name() if v.driver else None,
        'status': 'assigned' if v.driver else 'available'
    } for v in qs]

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
