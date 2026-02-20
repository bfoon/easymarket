from __future__ import annotations

import json
import logging
import re
import secrets
from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate, get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.utils.timezone import now
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from allauth.socialaccount.adapter import get_adapter
from allauth.socialaccount.models import SocialApp
from django.contrib.sites.shortcuts import get_current_site

from marketplace.utils import migrate_session_cart_to_user
from orders.models import Order

from .forms import ProfileUpdateForm
from .models import Address, AdminLog, Device, OneTimeCode, Currency, Country
from .utils import device_fingerprint, parse_ua, send_otp_email, send_otp_whatsapp

logger = logging.getLogger(__name__)
User = get_user_model()

# -------------------------------------------------------------------
# Device cookie
# -------------------------------------------------------------------
DEVICE_COOKIE_NAME = "em_dev"
DEVICE_COOKIE_MAX_AGE = 60 * 60 * 24 * 365 * 2  # 2 years

def _client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")

def _get_device_token(request):
    return request.COOKIES.get(DEVICE_COOKIE_NAME)

def _set_device_cookie(response, token, request):
    secure = getattr(settings, "SESSION_COOKIE_SECURE", False) or request.is_secure()
    response.set_cookie(
        DEVICE_COOKIE_NAME,
        token,
        max_age=DEVICE_COOKIE_MAX_AGE,
        httponly=True,
        samesite="Lax",
        secure=secure,
        path="/",
    )
    return response

# -------------------------------------------------------------------
# Phone normalization (force E.164 with +220)
# -------------------------------------------------------------------
DEFAULT_COUNTRY_CODE = "+220"
_phone_re = re.compile(r"[^\d+]")  # keep digits and '+'

def _normalize_phone(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    # strip everything except digits and '+'
    if raw.startswith("+"):
        cleaned = "+" + _phone_re.sub("", raw)[1:]
    else:
        cleaned = _phone_re.sub("", raw)

    if cleaned.startswith("+"):
        return cleaned
    if cleaned.startswith("00220"):
        return "+220" + cleaned[5:]
    if cleaned.startswith("220"):
        return "+220" + cleaned[3:]
    return f"{DEFAULT_COUNTRY_CODE}{cleaned}"

def generate_unique_username(email: str) -> str:
    base = (email.split("@")[0].lower() if email else "user")
    base = re.sub(r"[^a-z0-9]+", "", base) or "user"
    candidate = f"{base}{secrets.token_hex(2)}"
    while User.objects.filter(username=candidate).exists():
        candidate = f"{base}{secrets.token_hex(2)}"
    return candidate

# -------------------------------------------------------------------
# Auth
# -------------------------------------------------------------------
import threading

def send_otp_async(user, device):
    """
    Fire-and-forget thread that creates an OTP and sends via email + WhatsApp.
    """
    def task():
        try:
            otp = OneTimeCode.make(user=user, device=device, ttl_minutes=10)
            send_otp_email(user, otp.code)
            send_otp_whatsapp(user, otp.code)
        except Exception as e:
            # log error but don't crash the request
            import logging
            logging.exception("OTP sending failed: %s", e)

    thread = threading.Thread(target=task, daemon=True)
    thread.start()


@csrf_protect
def login_view(request):
    if request.method == "POST":
        # Accept multiple possible field names from the template
        raw_identifier = (
            request.POST.get("username")
            or request.POST.get("email")
            or request.POST.get("login")
            or request.POST.get("phone")
            or ""
        ).strip()
        password = request.POST.get("password") or ""

        # Resolve by username / email / telephone (telephone normalised to +220…)
        norm_phone = _normalize_phone(raw_identifier)

        # Build phone candidates to match legacy rows too (without +, with 220, plain local)
        digits = re.sub(r"\D+", "", raw_identifier or "")
        candidates = set()
        if norm_phone:
            candidates.add(norm_phone)          # +2203930160
        if digits:
            candidates.add(digits)              # 3930160
            if not digits.startswith("220"):
                candidates.add(f"220{digits}")  # 2203930160

        phone_q = Q()
        for p in candidates:
            phone_q |= Q(telephone__iexact=p)

        user_obj = (
            User.objects.filter(
                Q(username__iexact=raw_identifier) |
                Q(email__iexact=raw_identifier) |
                phone_q
            )
            .order_by("-id")
            .first()
        )

        if not user_obj:
            messages.error(request, "Invalid username or password.")
            return render(request, "accounts/login.html")

        # Authenticate using the model's USERNAME_FIELD
        login_identifier_value = getattr(user_obj, user_obj.USERNAME_FIELD)
        user = authenticate(request, username=login_identifier_value, password=password)
        if user is None:
            logger.warning(
                "Auth failed for identifier=%r (resolved %s=%r). is_active=%s",
                raw_identifier, user_obj.USERNAME_FIELD, login_identifier_value, user_obj.is_active,
            )
            messages.error(request, "Invalid username or password.")
            return render(request, "accounts/login.html")

        # Device bind via persistent cookie token
        token = _get_device_token(request)
        new_cookie_needed = False
        if not token:
            token = secrets.token_urlsafe(32)
            new_cookie_needed = True

        ua = request.META.get("HTTP_USER_AGENT", "")
        ip = _client_ip(request)
        browser, os = parse_ua(ua)

        device, created = Device.objects.get_or_create(
            user=user,
            device_id=token,
            defaults={"user_agent": ua, "browser": browser, "os": os, "ip": ip, "is_trusted": False},
        )
        if not created:
            update_fields = []
            if getattr(device, "user_agent", None) != ua:
                device.user_agent = ua
                update_fields.append("user_agent")
            if getattr(device, "ip", None) != ip:
                device.ip = ip
                update_fields.append("ip")
            if update_fields:
                device.save(update_fields=update_fields)

        # ── UNTRUSTED DEVICE ────────────────────────────────────────────────
        # Send OTP and redirect to verify — do NOT log in yet.
        # We save the next URL so the OTP view can redirect correctly after
        # merging the session cart.
        if not device.is_trusted:
            send_otp_async(user, device)

            request.session["pending_login_user_id"] = user.id
            request.session["pending_device_id"] = device.id
            # Store the backend so OTP view can call login() with the right one
            backend = getattr(user, "backend", None) or settings.AUTHENTICATION_BACKENDS[0]
            request.session["pending_auth_backend"] = backend
            # Preserve intended destination so OTP view can redirect correctly
            next_url = request.POST.get("next") or request.GET.get("next") or "/"
            request.session["pending_next_url"] = next_url

            messages.info(
                request,
                "We sent a 6-digit code to your email and WhatsApp. Enter it to finish logging in.",
            )
            resp = redirect("accounts:verify_login_otp")
            if new_cookie_needed:
                _set_device_cookie(resp, token, request)
            return resp

        # ── TRUSTED DEVICE — complete login immediately ──────────────────────
        login(request, user)

        # Always merge any guest session cart into the user's DB cart.
        # This handles both normal logins and the checkout-after-login flow.
        migrate_session_cart_to_user(request, user)

        # If the user was sent here from the checkout flow, go straight there.
        if request.session.pop("checkout_after_login", None):
            resp = redirect("orders:checkout_redirect")
        else:
            next_url = request.POST.get("next") or request.GET.get("next") or "/"
            # Safety: only allow relative URLs to prevent open-redirect attacks
            from django.utils.http import url_has_allowed_host_and_scheme
            if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                next_url = "/"
            resp = redirect(next_url)

        if new_cookie_needed:
            _set_device_cookie(resp, token, request)
        messages.success(request, f"Welcome back, {user.username}!")
        return resp

    return render(request, "accounts/login.html")


@csrf_protect
def verify_login_otp(request):
    """
    GET: render form
    POST: validate code, trust device, log in, continue flow
    """
    pending_user_id = request.session.get("pending_login_user_id")
    pending_device_id = request.session.get("pending_device_id")
    if not pending_user_id or not pending_device_id:
        messages.error(request, "Your session expired. Please sign in again.")
        return redirect("accounts:sign_in")

    if request.method == "POST":
        code = (request.POST.get("code") or "").strip()
        try:
            user = User.objects.get(id=pending_user_id)
            device = Device.objects.get(id=pending_device_id, user=user)
        except (User.DoesNotExist, Device.DoesNotExist):
            messages.error(request, "Session invalid. Please sign in again.")
            return redirect("accounts:sign_in")

        otp = (
            OneTimeCode.objects
            .filter(user=user, device=device, consumed_at__isnull=True)
            .order_by("-created_at")
            .first()
        )
        if not otp:
            messages.error(request, "No active code. Please sign in again.")
            return redirect("accounts:sign_in")

        if now() > otp.expires_at:
            messages.error(request, "That code expired. Please sign in again.")
            return redirect("accounts:sign_in")

        otp.attempts += 1
        if otp.is_valid(code):
            otp.consumed_at = now()
            otp.save(update_fields=["attempts", "consumed_at"])

            # Trust this device and finish login
            if not device.is_trusted:
                device.is_trusted = True
                device.save(update_fields=["is_trusted"])

            backend = request.session.get("pending_auth_backend", settings.AUTHENTICATION_BACKENDS[0])
            login(request, user, backend=backend)

            # Cleanup pending session keys
            request.session.pop("pending_login_user_id", None)
            request.session.pop("pending_device_id", None)
            request.session.pop("pending_auth_backend", None)

            # Continue interrupted checkout if any
            if request.session.get("checkout_after_login"):
                migrate_session_cart_to_user(request, user)
                request.session.pop("checkout_after_login", None)
                resp = redirect("orders:checkout_redirect")
            else:
                resp = redirect("/")

            # Ensure the device cookie matches this trusted device
            token = _get_device_token(request)
            if not token or token != device.device_id:
                _set_device_cookie(resp, device.device_id, request)

            messages.success(request, f"Welcome, {user.username}! Device trusted.")
            return resp
        else:
            otp.save(update_fields=["attempts"])
            messages.error(request, "Incorrect code. Please try again.")

    return render(request, "accounts/verify_login_otp.html")


def custom_logout(request):
    logout(request)
    return redirect("marketplace:product_list")

# -------------------------------------------------------------------
# Registration
# -------------------------------------------------------------------
@csrf_protect
def register_view(request):
    if request.method == "POST":
        first_name = (request.POST.get("first_name") or "").strip()
        last_name  = (request.POST.get("last_name")  or "").strip()
        email      = (request.POST.get("email")      or "").strip().lower()
        password   = request.POST.get("password") or ""
        password_confirm = request.POST.get("password_confirm") or ""
        telephone_raw = request.POST.get("phone") or ""
        profile_pic = request.FILES.get("profile_picture")

        if password != password_confirm:
            messages.error(request, "Passwords do not match.")
            return redirect("accounts:register")

        telephone = _normalize_phone(telephone_raw)
        if not telephone:
            messages.error(request, "Phone number is required.")
            return redirect("accounts:register")

        if User.objects.filter(telephone__iexact=telephone).exists():
            messages.error(request, "Phone number is already in use.")
            return redirect("accounts:register")

        if email and User.objects.filter(email__iexact=email).exists():
            messages.error(request, "Email is already in use.")
            return redirect("accounts:register")

        username = generate_unique_username(email)

        try:
            with transaction.atomic():
                extra = {
                    "first_name": first_name,
                    "last_name": last_name,
                    "telephone": telephone,
                    "is_buyer": True,
                }
                if email:
                    extra["email"] = email
                if profile_pic:
                    extra["profile_pic"] = profile_pic

                user = User.objects.create_user(
                    username=username,
                    password=password,
                    **extra,
                )
        except IntegrityError as e:
            logger.exception("Integrity error creating user: %s", e)
            messages.error(
                request,
                "Could not create account. The phone number or username already exists."
            )
            return redirect("accounts:register")

        # Authenticate to set backend (since multiple backends are configured)
        auth_user = authenticate(request, username=username, password=password)
        if auth_user:
            login(request, auth_user)
        else:
            login(request, user, backend=settings.AUTHENTICATION_BACKENDS[0])

        # Trust & store the first device
        try:
            fp = device_fingerprint(request)
            ua = request.META.get("HTTP_USER_AGENT", "")
            ip = request.META.get("REMOTE_ADDR")
            browser, os = parse_ua(ua)

            device, created = Device.objects.get_or_create(
                user=user,
                device_id=fp,
                defaults={
                    "user_agent": ua,
                    "browser": browser,
                    "os": os,
                    "ip": ip,
                    "is_trusted": True,
                },
            )
            if not created and not device.is_trusted:
                device.is_trusted = True
                device.save(update_fields=["is_trusted"])
        except Exception:
            logger.exception("Failed to store/trust first device after registration")

        messages.success(request, "Account created successfully.")
        return redirect("/")

    # GET: show Google provider status
    ctx = {"google_enabled": False, "google_misconfigured": False, "google_count": 0, "google_error": None}
    try:
        site = get_current_site(request)
        google_count = SocialApp.objects.filter(provider="google", sites=site).count()
        ctx.update({"google_enabled": (google_count == 1), "google_misconfigured": (google_count > 1), "google_count": google_count})
        if google_count == 1:
            try:
                adapter = get_adapter(request); adapter.get_provider(request, "google")
            except Exception as e:
                logger.warning(f"Google provider misconfigured: {e}")
                ctx.update({"google_enabled": False, "google_misconfigured": True, "google_error": str(e)})
    except Exception:
        logger.exception("Google social app configuration check failed")
        ctx.update({"google_enabled": False, "google_misconfigured": True, "google_error": "Configuration check failed"})

    return render(request, "accounts/register.html", ctx)

# -------------------------------------------------------------------
# Admin Logs (staff-only)
# -------------------------------------------------------------------
@staff_member_required
def admin_logs(request):
    logs_qs = AdminLog.objects.order_by("-created_at")
    paginator = Paginator(logs_qs, 20)
    page_number = request.GET.get("page")
    logs = paginator.get_page(page_number)

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
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

# -------------------------------------------------------------------
# Profile / Address
# -------------------------------------------------------------------
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


@login_required
@require_POST
@csrf_protect
def set_currency_preference(request):
    """
    Quick currency switcher from header or profile
    """
    currency_code = request.POST.get('currency_code', '').strip()
    redirect_to = request.POST.get('redirect_to', request.META.get('HTTP_REFERER', '/'))

    if currency_code:
        try:
            currency = Currency.objects.get(code=currency_code, is_active=True)
            request.user.preferred_currency = currency
            request.user.save(update_fields=['preferred_currency'])

            messages.success(
                request,
                f'Currency updated to {currency.name} ({currency.symbol})'
            )
        except Currency.DoesNotExist:
            messages.error(request, 'Invalid currency selected')

    return redirect(redirect_to)


@login_required
@require_POST
@csrf_protect
def set_country_preference(request):
    """
    Set user's country preference (updates their primary address)
    """
    country_id = request.POST.get('country_id')
    redirect_to = request.POST.get('redirect_to', request.META.get('HTTP_REFERER', '/'))

    if country_id:
        try:
            country = Country.objects.get(id=country_id, is_active=True)

            # Update or create primary address
            address, created = Address.objects.get_or_create(
                user=request.user,
                defaults={'country': country}
            )

            if not created:
                address.country = country
                address.save(update_fields=['country'])

            # Optionally set currency to country's default currency
            if country.currency:
                request.user.preferred_currency = country.currency
                request.user.save(update_fields=['preferred_currency'])

            messages.success(
                request,
                f'Location updated to {country.name}'
            )
        except Country.DoesNotExist:
            messages.error(request, 'Invalid country selected')

    return redirect(redirect_to)


@login_required
@require_POST
@csrf_protect
def update_preferences(request):
    """
    Update both currency and country preferences from profile page
    """
    currency_id = request.POST.get('preferred_currency')
    country_id = request.POST.get('country')

    updated = False

    # Update currency preference
    if currency_id:
        try:
            currency = Currency.objects.get(id=currency_id, is_active=True)
            request.user.preferred_currency = currency
            request.user.save(update_fields=['preferred_currency'])
            updated = True
        except Currency.DoesNotExist:
            messages.error(request, 'Invalid currency selected')

    # Update country (primary address)
    if country_id:
        try:
            country = Country.objects.get(id=country_id, is_active=True)

            # Get or create the user's first address
            address = request.user.address_set.first()
            if address:
                address.country = country
                address.save(update_fields=['country'])
            else:
                Address.objects.create(user=request.user, country=country)

            updated = True
        except Country.DoesNotExist:
            messages.error(request, 'Invalid country selected')

    if updated:
        messages.success(request, 'Preferences updated successfully')

    return redirect('accounts:user_profile')


@login_required
@csrf_protect
def quick_currency_switch(request):
    """
    Quick currency switch from profile sidebar
    """
    if request.method == 'POST':
        return set_currency_preference(request)
    return redirect('accounts:user_profile')


# UPDATE THE EXISTING user_profile VIEW TO INCLUDE CURRENCIES AND COUNTRIES

@login_required
def user_profile(request):
    """
    Enhanced user profile view with currency and country support
    """
    user = request.user
    addresses = Address.objects.filter(user=user).select_related('country')

    # Get all active currencies and countries
    currencies = Currency.objects.filter(is_active=True).order_by('code')
    countries = Country.objects.filter(is_active=True).select_related('currency').order_by('name')

    # Orders (paginated)
    from orders.models import Order
    from django.core.paginator import Paginator

    order_list = Order.objects.filter(buyer=user).order_by("-created_at")
    paginator = Paginator(order_list, 5)
    page_number = request.GET.get("page")
    orders = paginator.get_page(page_number)

    if request.method == "POST":
        if "update_profile" in request.POST:
            from .forms import ProfileUpdateForm
            from django.contrib.auth.forms import PasswordChangeForm

            profile_form = ProfileUpdateForm(request.POST, request.FILES, instance=user)
            password_form = PasswordChangeForm(user)

            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Profile updated successfully.")
                return redirect("accounts:user_profile")

        elif "change_password" in request.POST:
            from .forms import ProfileUpdateForm
            from django.contrib.auth.forms import PasswordChangeForm
            from django.contrib.auth import update_session_auth_hash

            profile_form = ProfileUpdateForm(instance=user)
            password_form = PasswordChangeForm(user, request.POST)

            if password_form.is_valid():
                updated_user = password_form.save()
                update_session_auth_hash(request, updated_user)
                messages.success(request, "Password changed successfully.")
                return redirect("accounts:user_profile")
        else:
            from django.http import HttpResponseBadRequest
            return HttpResponseBadRequest("Invalid form submission.")
    else:
        from .forms import ProfileUpdateForm
        from django.contrib.auth.forms import PasswordChangeForm

        profile_form = ProfileUpdateForm(instance=user)
        password_form = PasswordChangeForm(user)

    return render(
        request,
        "accounts/user_profile.html",
        {
            "user": user,
            "addresses": addresses,
            "profile_form": profile_form,
            "orders": orders,
            "password_form": password_form,
            "currencies": currencies,  # NEW
            "countries": countries,  # NEW
        },
    )


# UPDATE THE edit_address_modal VIEW TO SUPPORT COUNTRY SELECTION

@login_required
@require_POST
@csrf_protect
def edit_address_modal(request):
    """
    Handles modal form submission for addresses with country support
    """
    address, _ = Address.objects.get_or_create(user=request.user)

    address.address1 = request.POST.get("address1", "").strip()
    address.address2 = request.POST.get("address2", "").strip()
    address.geo_code = request.POST.get("geo_code", "").strip()

    # Handle country selection
    country_id = request.POST.get("country")
    if country_id:
        try:
            country = Country.objects.get(id=country_id)
            address.country = country
            # Keep country_name for backward compatibility
            address.country_name = country.name
        except Country.DoesNotExist:
            pass

    address.save()
    messages.success(request, "Address saved successfully.")

    return redirect(request.META.get("HTTP_REFERER") or "marketplace:product_list")