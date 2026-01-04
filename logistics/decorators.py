"""
Logistics Decorators Module

This module provides custom decorators for access control and permission checking
in the logistics application.

Author: Logistics Team
Version: 2.0.0
"""

from functools import wraps
from typing import Callable, Any
import logging

from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.urls import reverse

from .models import Driver, Warehouse

logger = logging.getLogger(__name__)


# ============================================================================
# ROLE-BASED ACCESS DECORATORS
# ============================================================================

def driver_required(view_func: Callable) -> Callable:
    """
    Decorator that ensures the user is authenticated and has a Driver profile.

    This decorator must be used after @login_required or combined with it.
    It adds the driver instance to the request object for easy access.

    Usage:
        @login_required
        @driver_required
        def driver_dashboard(request):
            driver = request.driver
            # ...

    Args:
        view_func: The view function to wrap

    Returns:
        Wrapped view function with driver access control
    """

    @wraps(view_func)
    def _wrapped_view(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        # Check if user has driver flag
        if not hasattr(request.user, 'is_driver') or not request.user.is_driver:
            logger.warning(
                f"Non-driver user {request.user.username} attempted to access driver view"
            )
            messages.error(
                request,
                "You don't have permission to access this page. Driver privileges required."
            )
            return redirect('logistics:driver_dashboard')

        # Get or verify driver profile
        try:
            driver = Driver.objects.select_related('user').get(user=request.user)

            # Check if driver is active
            if not driver.is_active:
                logger.warning(
                    f"Inactive driver {driver.employee_id} attempted access"
                )
                messages.error(
                    request,
                    "Your driver account is inactive. Please contact your supervisor."
                )
                return redirect('logistics:dashboard')

            # Check license validity
            if not driver.is_license_valid():
                logger.warning(
                    f"Driver {driver.employee_id} with expired license attempted access"
                )
                messages.warning(
                    request,
                    "Your driver's license has expired. Please update your license information."
                )
                # Still allow access but with warning

            # Add driver to request for easy access in views
            request.driver = driver

        except Driver.DoesNotExist:
            logger.error(
                f"Driver profile not found for user {request.user.username}"
            )
            messages.error(
                request,
                "Driver profile not found. Please contact the administrator."
            )
            return redirect('logistics:dashboard')

        return view_func(request, *args, **kwargs)

    return _wrapped_view


def warehouse_manager_required(view_func: Callable) -> Callable:
    """
    Decorator that ensures the user is a warehouse manager.

    Usage:
        @login_required
        @warehouse_manager_required
        def warehouse_inventory(request):
            warehouses = request.managed_warehouses
            # ...

    Args:
        view_func: The view function to wrap

    Returns:
        Wrapped view function with warehouse manager access control
    """

    @wraps(view_func)
    def _wrapped_view(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        # Check if user manages any warehouses
        managed_warehouses = Warehouse.objects.filter(
            manager=request.user,
            is_active=True
        )

        if not managed_warehouses.exists():
            logger.warning(
                f"User {request.user.username} attempted warehouse manager access without privileges"
            )
            messages.error(
                request,
                "You don't have warehouse manager permissions."
            )
            return redirect('logistics:dashboard')

        # Add managed warehouses to request
        request.managed_warehouses = managed_warehouses

        return view_func(request, *args, **kwargs)

    return _wrapped_view


def logistics_staff_required(view_func: Callable) -> Callable:
    """
    Decorator that ensures the user is logistics staff (has logistics permissions).

    Usage:
        @login_required
        @logistics_staff_required
        def shipment_management(request):
            # ...

    Args:
        view_func: The view function to wrap

    Returns:
        Wrapped view function with logistics staff access control
    """

    @wraps(view_func)
    def _wrapped_view(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        # Check if user has logistics permissions
        has_logistics_perms = (
                request.user.is_staff or
                request.user.has_perm('logistics.view_shipment') or
                request.user.groups.filter(name='Logistics').exists()
        )

        if not has_logistics_perms:
            logger.warning(
                f"User {request.user.username} attempted logistics staff access without permissions"
            )
            messages.error(
                request,
                "You don't have logistics staff permissions."
            )
            return redirect('logistics:dashboard')

        return view_func(request, *args, **kwargs)

    return _wrapped_view


def admin_or_manager_required(view_func: Callable) -> Callable:
    """
    Decorator that ensures the user is either an admin or has manager privileges.

    Usage:
        @login_required
        @admin_or_manager_required
        def manage_drivers(request):
            # ...

    Args:
        view_func: The view function to wrap

    Returns:
        Wrapped view function with admin/manager access control
    """

    @wraps(view_func)
    def _wrapped_view(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        is_authorized = (
                request.user.is_superuser or
                request.user.is_staff or
                request.user.groups.filter(name__in=['Managers', 'Logistics Managers']).exists()
        )

        if not is_authorized:
            logger.warning(
                f"User {request.user.username} attempted admin/manager access without privileges"
            )
            messages.error(
                request,
                "You need administrator or manager privileges to access this page."
            )
            return redirect('logistics:dashboard')

        return view_func(request, *args, **kwargs)

    return _wrapped_view


# ============================================================================
# API DECORATORS
# ============================================================================

def ajax_required(view_func: Callable) -> Callable:
    """
    Decorator that ensures the request is an AJAX request.
    Returns JSON error response if not AJAX.

    Usage:
        @login_required
        @ajax_required
        def get_shipment_status(request, shipment_id):
            # ...
            return JsonResponse({'status': 'success'})

    Args:
        view_func: The view function to wrap

    Returns:
        Wrapped view function that validates AJAX requests
    """

    @wraps(view_func)
    def _wrapped_view(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            logger.warning(
                f"Non-AJAX request to AJAX-only endpoint by {request.user.username if request.user.is_authenticated else 'anonymous'}"
            )
            return JsonResponse(
                {'error': 'This endpoint only accepts AJAX requests'},
                status=400
            )

        return view_func(request, *args, **kwargs)

    return _wrapped_view


def api_key_required(view_func: Callable) -> Callable:
    """
    Decorator that validates API key for external integrations.

    Usage:
        @api_key_required
        def external_shipment_webhook(request):
            # ...

    Args:
        view_func: The view function to wrap

    Returns:
        Wrapped view function that validates API keys
    """

    @wraps(view_func)
    def _wrapped_view(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        from django.conf import settings

        # Get API key from header or query param
        api_key = (
                request.headers.get('X-API-Key') or
                request.GET.get('api_key')
        )

        # Validate API key
        valid_keys = getattr(settings, 'LOGISTICS_API_KEYS', [])

        if not api_key or api_key not in valid_keys:
            logger.warning(
                f"Invalid API key attempt from {request.META.get('REMOTE_ADDR')}"
            )
            return JsonResponse(
                {'error': 'Invalid or missing API key'},
                status=401
            )

        return view_func(request, *args, **kwargs)

    return _wrapped_view


# ============================================================================
# PERMISSION DECORATORS
# ============================================================================

def shipment_owner_or_staff(view_func: Callable) -> Callable:
    """
    Decorator that ensures the user is either the shipment owner or staff.
    Used for views that require shipment-level access control.

    The view must accept a 'shipment_id' or 'pk' parameter.

    Usage:
        @login_required
        @shipment_owner_or_staff
        def view_shipment_details(request, shipment_id):
            # ...

    Args:
        view_func: The view function to wrap

    Returns:
        Wrapped view function with shipment access control
    """

    @wraps(view_func)
    def _wrapped_view(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        from .models import Shipment

        # Get shipment ID from kwargs
        shipment_id = kwargs.get('shipment_id') or kwargs.get('pk')

        if not shipment_id:
            logger.error("shipment_owner_or_staff decorator used without shipment_id parameter")
            raise ValueError("This decorator requires a shipment_id or pk parameter")

        try:
            shipment = Shipment.objects.select_related('order__buyer', 'driver__user').get(
                pk=shipment_id
            )
        except Shipment.DoesNotExist:
            messages.error(request, "Shipment not found.")
            return redirect('logistics:shipment_list')

        # Check if user has access
        is_authorized = (
                request.user.is_staff or
                request.user.is_superuser or
                (shipment.order and shipment.order.buyer == request.user) or
                (shipment.driver and shipment.driver.user == request.user) or
                request.user.groups.filter(name='Logistics').exists()
        )

        if not is_authorized:
            logger.warning(
                f"User {request.user.username} attempted unauthorized access to shipment {shipment_id}"
            )
            messages.error(
                request,
                "You don't have permission to view this shipment."
            )
            return redirect('logistics:shipment_list')

        # Add shipment to request for use in view
        request.shipment = shipment

        return view_func(request, *args, **kwargs)

    return _wrapped_view


def can_modify_shipment(view_func: Callable) -> Callable:
    """
    Decorator that ensures the user can modify the shipment.
    Only staff and logistics personnel can modify shipments.

    Usage:
        @login_required
        @can_modify_shipment
        def update_shipment(request, shipment_id):
            # ...

    Args:
        view_func: The view function to wrap

    Returns:
        Wrapped view function with modification permission check
    """

    @wraps(view_func)
    def _wrapped_view(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        from .models import Shipment

        shipment_id = kwargs.get('shipment_id') or kwargs.get('pk')

        if not shipment_id:
            raise ValueError("This decorator requires a shipment_id or pk parameter")

        try:
            shipment = Shipment.objects.get(pk=shipment_id)
        except Shipment.DoesNotExist:
            messages.error(request, "Shipment not found.")
            return redirect('logistics:shipment_list')

        # Check modification permissions
        can_modify = (
                request.user.is_staff or
                request.user.has_perm('logistics.change_shipment') or
                request.user.groups.filter(name__in=['Logistics', 'Logistics Managers']).exists()
        )

        if not can_modify:
            logger.warning(
                f"User {request.user.username} attempted to modify shipment {shipment_id} without permission"
            )
            messages.error(
                request,
                "You don't have permission to modify this shipment."
            )
            return redirect('logistics:shipment_detail', pk=shipment_id)

        # Check if shipment is in a modifiable state
        if shipment.status == 'delivered':
            messages.warning(
                request,
                "Cannot modify a delivered shipment. Contact an administrator if changes are needed."
            )
            return redirect('logistics:shipment_detail', pk=shipment_id)

        request.shipment = shipment

        return view_func(request, *args, **kwargs)

    return _wrapped_view


# ============================================================================
# RATE LIMITING DECORATORS
# ============================================================================

def rate_limit(max_requests: int = 100, window_seconds: int = 3600):
    """
    Simple rate limiting decorator (for production, use django-ratelimit).

    Usage:
        @rate_limit(max_requests=10, window_seconds=60)
        def api_endpoint(request):
            # ...

    Args:
        max_requests: Maximum number of requests allowed
        window_seconds: Time window in seconds

    Returns:
        Decorator function
    """

    def decorator(view_func: Callable) -> Callable:
        @wraps(view_func)
        def _wrapped_view(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            # This is a placeholder - implement actual rate limiting
            # using django-ratelimit or similar library
            # For production: pip install django-ratelimit

            # Example implementation would track requests in cache/redis
            # and return 429 Too Many Requests if exceeded

            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator


# ============================================================================
# UTILITY DECORATORS
# ============================================================================

def log_view_access(view_func: Callable) -> Callable:
    """
    Decorator that logs access to sensitive views.

    Usage:
        @login_required
        @log_view_access
        def sensitive_data_view(request):
            # ...

    Args:
        view_func: The view function to wrap

    Returns:
        Wrapped view function with access logging
    """

    @wraps(view_func)
    def _wrapped_view(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        logger.info(
            f"View access: {view_func.__name__} | "
            f"User: {request.user.username if request.user.is_authenticated else 'anonymous'} | "
            f"IP: {request.META.get('REMOTE_ADDR')} | "
            f"Method: {request.method}"
        )

        return view_func(request, *args, **kwargs)

    return _wrapped_view


def require_feature_flag(flag_name: str):
    """
    Decorator that checks if a feature flag is enabled.
    Useful for gradual rollout of new features.

    Usage:
        @require_feature_flag('advanced_routing')
        def advanced_route_optimization(request):
            # ...

    Args:
        flag_name: Name of the feature flag

    Returns:
        Decorator function
    """

    def decorator(view_func: Callable) -> Callable:
        @wraps(view_func)
        def _wrapped_view(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            from django.conf import settings

            # Check if feature is enabled
            feature_flags = getattr(settings, 'FEATURE_FLAGS', {})
            is_enabled = feature_flags.get(flag_name, False)

            if not is_enabled:
                logger.info(
                    f"Feature {flag_name} accessed but disabled by {request.user.username}"
                )
                messages.info(
                    request,
                    "This feature is currently unavailable."
                )
                return redirect('logistics:dashboard')

            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def check_driver_permissions(user) -> bool:
    """
    Helper function to check if user has driver permissions.

    Args:
        user: Django user instance

    Returns:
        Boolean indicating if user is an active driver
    """
    if not user.is_authenticated:
        return False

    try:
        driver = Driver.objects.get(user=user)
        return driver.is_active and driver.is_license_valid()
    except Driver.DoesNotExist:
        return False


def check_warehouse_permissions(user, warehouse_id: int = None) -> bool:
    """
    Helper function to check warehouse management permissions.

    Args:
        user: Django user instance
        warehouse_id: Optional specific warehouse ID to check

    Returns:
        Boolean indicating if user can manage warehouse(s)
    """
    if not user.is_authenticated:
        return False

    if user.is_superuser or user.is_staff:
        return True

    query = Warehouse.objects.filter(manager=user, is_active=True)
    if warehouse_id:
        query = query.filter(id=warehouse_id)

    return query.exists()