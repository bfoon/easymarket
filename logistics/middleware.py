# logistics/middleware.py
from django.shortcuts import redirect
from django.contrib import messages
from django.urls import resolve
from django.urls import reverse
from logistics.models import Shipment
from .models import Driver


class DriverAccessMiddleware:
    """
    Middleware to restrict access to driver views to only authenticated drivers
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.driver_paths = [
            'driver_dashboard',
            'driver_profile',
            'shipment_detail_map',
            'start_delivery',
            'mark_delivered',
            'get_shipment_location'
        ]

    def __call__(self, request):
        # Check if this is a driver-specific view
        try:
            resolver_match = resolve(request.path)
            if (resolver_match.app_name == 'logistics' and
                    resolver_match.url_name in self.driver_paths):

                # Check authentication
                if not request.user.is_authenticated:
                    messages.warning(request, "Please log in to access the driver portal.")
                    return redirect('login')  # Change to your login URL name

                # Check driver status
                if not request.user.is_driver:
                    messages.error(request, "Access denied. Driver privileges required.")
                    return redirect('home')  # Change to your home URL name

                # Check driver profile exists
                try:
                    driver = Driver.objects.get(user=request.user)
                    request.driver = driver  # Add to request for easy access
                except Driver.DoesNotExist:
                    messages.error(request, "Driver profile not found. Please contact administrator.")
                    return redirect('home')

        except:
            # If URL resolution fails, continue normally
            pass

        response = self.get_response(request)
        return response


class ShipmentLockMiddleware:
    """
    Middleware to prevent modification of shipments in 'in_transit' or 'delivered' status.

    Protects:
    - Shipment edit view
    - Box create/edit/delete views
    - Box item create/edit/delete views
    """

    # URLs that should be protected
    PROTECTED_PATTERNS = [
        'logistics:shipment_edit',
        'logistics:box_create',
        'logistics:box_edit',
        'logistics:box_delete',
        'logistics:box_item_create',
        'logistics:box_item_edit',
        'logistics:box_item_delete',
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Check if this is a protected URL
        if hasattr(request, 'resolver_match') and request.resolver_match:
            url_name = request.resolver_match.url_name

            if url_name in self.PROTECTED_PATTERNS:
                # Get shipment from URL parameters
                shipment = self._get_shipment_from_request(request)

                if shipment and shipment.status in ['in_transit', 'delivered']:
                    # Shipment is locked - prevent modification
                    messages.error(
                        request,
                        f'Cannot modify shipment - status is "{shipment.get_status_display()}". '
                        f'Shipments in transit or delivered are read-only.'
                    )
                    return redirect('logistics:shipment_detail', pk=shipment.pk)

        response = self.get_response(request)
        return response

    def _get_shipment_from_request(self, request):
        """Extract shipment from URL parameters."""
        try:
            # Try to get shipment ID from URL
            if 'pk' in request.resolver_match.kwargs:
                shipment_id = request.resolver_match.kwargs['pk']
                return Shipment.objects.get(pk=shipment_id)

            # For box-related views, get shipment from box
            if 'box_id' in request.resolver_match.kwargs:
                from logistics.models import ShipmentBox
                box_id = request.resolver_match.kwargs['box_id']
                box = ShipmentBox.objects.select_related('shipment').get(pk=box_id)
                return box.shipment

            # For box item views, get shipment from box item
            if 'item_id' in request.resolver_match.kwargs:
                from logistics.models import BoxItem
                item_id = request.resolver_match.kwargs['item_id']
                item = BoxItem.objects.select_related('box__shipment').get(pk=item_id)
                return item.box.shipment

        except Exception:
            pass

        return None


# ALTERNATIVE: View-level Protection (use decorators)
# ===================================================

from functools import wraps
from django.http import HttpResponseForbidden


def require_unlocked_shipment(view_func):
    """
    Decorator to protect views from modifying locked shipments.

    Usage:
        @require_unlocked_shipment
        def shipment_edit_view(request, pk):
            ...
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # Get shipment from kwargs
        shipment_id = kwargs.get('pk') or kwargs.get('shipment_id')

        if shipment_id:
            try:
                shipment = Shipment.objects.get(pk=shipment_id)

                if shipment.status in ['in_transit', 'delivered']:
                    messages.error(
                        request,
                        f'Cannot modify shipment - status is "{shipment.get_status_display()}". '
                        f'Shipments in transit or delivered are read-only.'
                    )
                    return redirect('logistics:shipment_detail', pk=shipment.pk)

            except Shipment.DoesNotExist:
                pass

        return view_func(request, *args, **kwargs)

    return wrapper


# MIXIN FOR CLASS-BASED VIEWS
# ============================

from django.contrib import messages
from django.shortcuts import redirect


class ShipmentLockMixin:
    """
    Mixin to prevent editing of locked shipments in class-based views.

    Usage:
        class ShipmentEditView(ShipmentLockMixin, UpdateView):
            ...
    """

    def dispatch(self, request, *args, **kwargs):
        # Get the shipment object
        shipment = self.get_shipment()

        if shipment and shipment.status in ['in_transit', 'delivered']:
            messages.error(
                request,
                f'Cannot modify shipment - status is "{shipment.get_status_display()}". '
                f'Shipments in transit or delivered are read-only.'
            )
            return redirect('logistics:shipment_detail', pk=shipment.pk)

        return super().dispatch(request, *args, **kwargs)

    def get_shipment(self):
        """Override this method to return the shipment."""
        if hasattr(self, 'object') and self.object:
            if isinstance(self.object, Shipment):
                return self.object
            elif hasattr(self.object, 'shipment'):
                return self.object.shipment
            elif hasattr(self.object, 'box') and hasattr(self.object.box, 'shipment'):
                return self.object.box.shipment

        # Try to get from URL
        shipment_id = self.kwargs.get('pk')
        if shipment_id:
            try:
                return Shipment.objects.get(pk=shipment_id)
            except Shipment.DoesNotExist:
                pass

        return None