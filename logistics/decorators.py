# logistics/decorators.py
from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .models import Driver


def driver_required(view_func):
    """
    Decorator that ensures the user is a driver and has a Driver profile.
    Must be used after @login_required
    """

    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_driver:
            messages.error(request, "You don't have permission to access this page.")
            return redirect('/')  # Change to your home URL name

        try:
            driver = Driver.objects.get(user=request.user)
            # Add driver to request for easy access in views
            request.driver = driver
        except Driver.DoesNotExist:
            messages.error(request, "Driver profile not found. Please contact administrator.")
            return redirect('/')

        return view_func(request, *args, **kwargs)

    return _wrapped_view