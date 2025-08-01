from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.db import IntegrityError
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

from .models import Subscription

@require_POST
def subscribe_email(request):
    email = (request.POST.get("email") or "").strip().lower()
    source = (request.POST.get("source") or "").strip()

    if not email:
        return JsonResponse({"success": False, "message": "Please enter your email address."}, status=400)

    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse({"success": False, "message": "Please enter a valid email address."}, status=400)

    try:
        # Try create; if duplicate (case-insensitive), DB raises IntegrityError
        Subscription.objects.create(email=email, source=source or "footer")
        return JsonResponse({"success": True, "message": "Thanks! You're subscribed to Easy Market deals & news."})
    except IntegrityError:
        # Already subscribed
        return JsonResponse({"success": False, "message": "You're already subscribed."}, status=200)