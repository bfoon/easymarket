# accounts/views.py

from __future__ import annotations

from django.contrib import messages
import json
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate, get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.paginator import Paginator
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.utils.timezone import now
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from allauth.socialaccount.models import SocialApp

from marketplace.utils import migrate_session_cart_to_user
from orders.models import Order

from .forms import ProfileUpdateForm
from .models import Address, AdminLog
from django.contrib.sites.shortcuts import get_current_site
from allauth.socialaccount.adapter import get_adapter
import logging

logger = logging.getLogger(__name__)

User = get_user_model()


# ---------- Auth ----------

def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)

            # If checkout flow was interrupted, migrate cart and continue
            if request.session.get("checkout_after_login"):
                migrate_session_cart_to_user(request, user)
                request.session.pop("checkout_after_login", None)
                return redirect("orders:checkout_redirect")

            messages.success(request, f"Welcome back, {user.username}!")
            return redirect("/")  # or user dashboard

        messages.error(request, "Invalid username or password.")

    return render(request, "accounts/login.html")


def custom_logout(request):
    logout(request)
    return redirect("marketplace:product_list")


def generate_unique_username(email: str) -> str:
    local_part = email.split("@")[0] if email and "@" in email else email
    base_username = slugify(local_part) or "user"
    username = base_username
    counter = 1
    while User.objects.filter(username=username).exists():
        username = f"{base_username}{counter}"
        counter += 1
    return username


@csrf_protect
def register_view(request):
    if request.method == "POST":
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password") or ""
        password_confirm = request.POST.get("password_confirm") or ""
        telephone = request.POST.get("phone", "").strip()
        profile_pic = request.FILES.get("profile_picture")

        if not email:
            messages.error(request, "Email is required.")
            return redirect("accounts:register")

        if password != password_confirm:
            messages.error(request, "Passwords do not match.")
            return redirect("accounts:register")

        if User.objects.filter(email=email).exists():
            messages.error(request, "Email is already in use.")
            return redirect("accounts:register")

        username = generate_unique_username(email)

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )
        # Optional fields on your custom User
        if hasattr(user, "telephone"):
            user.telephone = telephone
        if hasattr(user, "profile_pic"):
            user.profile_pic = profile_pic
        if hasattr(user, "is_buyer"):
            user.is_buyer = True
        user.save(update_fields=["first_name", "last_name", "telephone", "profile_pic", "is_buyer"])

        login(request, user)
        messages.success(request, "Account created successfully.")
        return redirect("/")

    # GET: show whether Google is configured for this Site

    else:
        # Initialize context with safe defaults
        ctx = {
            "google_enabled": False,
            "google_misconfigured": False,
            "google_count": 0,
            "google_error": None,
        }

        try:
            site = get_current_site(request)
            google_count  = SocialApp.objects.filter(provider="google", sites=site).count()

            ctx.update({
                "google_enabled": google_count == 1,
                "google_misconfigured": google_count > 1,
                "google_count": google_count,
            })

            # Additional validation - check if provider is actually accessible
            if google_count == 1:
                try:
                    adapter = get_adapter(request)
                    adapter.get_provider(request, "google")
                except Exception as e:
                    logger.warning(f"Google provider misconfigured: {e}")
                    ctx.update({
                        "google_enabled": False,
                        "google_misconfigured": True,
                        "google_error": str(e),
                    })

        except Exception as e:
            logger.error(f"Error checking Google social app configuration: {e}")
            ctx.update({
                "google_enabled": False,
                "google_misconfigured": True,
                "google_error": "Configuration check failed",
            })
    return render(request, "accounts/register.html", ctx)


# ---------- Admin Logs (staff-only) ----------

@staff_member_required
def admin_logs(request):
    logs_qs = AdminLog.objects.order_by("-created_at")
    paginator = Paginator(logs_qs, 20)
    page_number = request.GET.get("page")
    logs = paginator.get_page(page_number)

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        # Return just the list fragment for AJAX pagination
        return render(request, "accounts/partials/log_list.html", {"logs": logs})

    return render(request, "accounts/admin_logs.html", {"logs": logs})


@staff_member_required
def admin_log_detail(request, pk):
    log = get_object_or_404(AdminLog, pk=pk)
    return render(request, "accounts/log_detail.html", {"log": log})


@staff_member_required
@require_POST
@csrf_protect
def mark_log_reviewed(request, pk):
    """
    Expects JSON: {"review_note": "..."}
    """
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON."}, status=400)

    review_note = (data.get("review_note") or "").strip()
    log = get_object_or_404(AdminLog, pk=pk)

    log.reviewed = True
    log.notes = review_note
    log.reviewed_at = now()
    log.reviewed_by = request.user
    log.save(update_fields=["reviewed", "notes", "reviewed_at", "reviewed_by"])

    return JsonResponse({"success": True, "message": "Log marked as reviewed."})


@staff_member_required
@require_POST
@csrf_protect
def flag_log_entry(request, pk):
    log = get_object_or_404(AdminLog, pk=pk)
    log.is_flagged = True
    log.flagged_at = now()
    log.flagged_by = request.user
    log.save(update_fields=["is_flagged", "flagged_at", "flagged_by"])
    return JsonResponse({"success": True, "message": "Log flagged successfully."})


@staff_member_required
@require_POST
@csrf_protect
def save_log_note(request, pk):
    """
    Expects JSON: {"note": "..."}
    """
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON."}, status=400)

    note = (data.get("note") or "").strip()
    if not note:
        return JsonResponse({"success": False, "error": "Note cannot be empty."}, status=400)

    log = get_object_or_404(AdminLog, pk=pk)
    log.notes = note
    log.save(update_fields=["notes"])
    return JsonResponse({"success": True})


# ---------- Profile / Address ----------

@login_required
@require_POST
@csrf_protect
def edit_address_modal(request):
    """
    Handles modal form submission; expects POST fields:
    address1, address2, country, geo_code
    """
    address, _ = Address.objects.get_or_create(user=request.user)
    address.address1 = request.POST.get("address1", "").strip()
    address.address2 = request.POST.get("address2", "").strip()
    address.country = request.POST.get("country", "").strip()
    address.geo_code = request.POST.get("geo_code", "").strip()  # geo fence identifier
    address.save()
    return redirect(request.META.get("HTTP_REFERER") or "marketplace:product_list")


@login_required
def user_profile(request):
    user = request.user
    addresses = Address.objects.filter(user=user)

    # Orders (paginated)
    order_list = Order.objects.filter(buyer=user).order_by("-created_at")
    paginator = Paginator(order_list, 5)
    page_number = request.GET.get("page")
    orders = paginator.get_page(page_number)

    if request.method == "POST":
        if "update_profile" in request.POST:
            profile_form = ProfileUpdateForm(request.POST, request.FILES, instance=user)
            password_form = PasswordChangeForm(user)  # keep second form pristine
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Profile updated successfully.")
                return redirect("accounts:user_profile")

        elif "change_password" in request.POST:
            profile_form = ProfileUpdateForm(instance=user)
            password_form = PasswordChangeForm(user, request.POST)
            if password_form.is_valid():
                updated_user = password_form.save()
                update_session_auth_hash(request, updated_user)  # keep user logged in
                messages.success(request, "Password changed successfully.")
                return redirect("accounts:user_profile")
        else:
            # Unknown submit source
            return HttpResponseBadRequest("Invalid form submission.")
    else:
        profile_form = ProfileUpdateForm(instance=user)
        password_form = PasswordChangeForm(user)

    return render(
        request,
        "accounts/user_profile.html",
        {
            "user": user,
            "addresses": addresses,
            "profile_form": profile_form,
            "orders": orders,  # paginated
            "password_form": password_form,
        },
    )


@login_required
@require_POST
@csrf_protect
def delete_address(request, address_id):
    address = get_object_or_404(Address, id=address_id, user=request.user)
    address.delete()
    messages.success(request, "Address removed successfully.")
    return redirect("accounts:user_profile")
