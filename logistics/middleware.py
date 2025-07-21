# logistics/middleware.py
from django.shortcuts import redirect
from django.contrib import messages
from django.urls import resolve
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
