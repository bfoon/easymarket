from accounts.models import AdminLog
import hashlib
import logging
from django.core.mail import send_mail
from django.conf import settings
from twilio.rest import Client
import re
import json

logger = logging.getLogger(__name__)

def log_admin_action(user, action_type, message, model=None, object_id=None):
    if not user.is_authenticated:
        return
    AdminLog.objects.create(
        action_type=action_type,
        related_model=model,
        related_object_id=str(object_id) if object_id else None,
        message=message,
        created_by=user
    )
def _client_ip(request):
    # Works behind common proxies; adjust as needed for your infra
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")

def parse_ua(ua: str):
    # Minimal, no external libs
    ua = ua or ""
    browser = "Unknown"
    os = "Unknown"
    if "Chrome" in ua and "Safari" in ua:
        browser = "Chrome"
    elif "Firefox" in ua:
        browser = "Firefox"
    elif "Safari" in ua and "Chrome" not in ua:
        browser = "Safari"
    elif "Edg" in ua:
        browser = "Edge"
    if "Windows" in ua: os = "Windows"
    elif "Mac OS X" in ua or "Macintosh" in ua: os = "macOS"
    elif "Android" in ua: os = "Android"
    elif "iPhone" in ua or "iPad" in ua: os = "iOS"
    elif "Linux" in ua: os = "Linux"
    return browser, os

def device_fingerprint(request):
    """
    Stable-ish fingerprint using user-agent, accept-language, and /24 IP block.
    """
    ua = request.META.get("HTTP_USER_AGENT", "")
    lang = request.META.get("HTTP_ACCEPT_LANGUAGE", "")
    ip = _client_ip(request) or ""
    # only first 3 octets to avoid changing per DHCP
    ip24 = ".".join(ip.split(".")[:3]) if ip and "." in ip else ip
    raw = f"{ua}|{lang}|{ip24}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def send_otp_email(user, code):
    email = getattr(user, "email", None)
    if not email:
        return  # ✅ no email provided; silently skip
    subject = "Your EasyMarket login code"
    body = f"Use this code to complete your login: {code}\nIt expires in 10 minutes."
    try:
        send_mail(subject, body, getattr(settings, "DEFAULT_FROM_EMAIL", None), [email], fail_silently=False)
    except Exception as e:
        logger.exception("Failed to send OTP email: %s", e)


DEFAULT_COUNTRY_CODE = "+220"
_phone_re = re.compile(r"[^\d+]")

def _normalize_phone(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw: return ""
    if raw.startswith("+"):
        cleaned = "+" + _phone_re.sub("", raw)[1:]
    else:
        cleaned = _phone_re.sub("", raw)
    if cleaned.startswith("+"): return cleaned
    if cleaned.startswith("00220"): return "+220" + cleaned[5:]
    if cleaned.startswith("220"):   return "+220" + cleaned[3:]
    return DEFAULT_COUNTRY_CODE + cleaned


def send_otp_whatsapp(user, code: str):
    phone = getattr(user, "telephone", "") or ""
    to_e164 = _normalize_phone(phone)
    if not to_e164:
        logger.info("No phone; skipping WhatsApp OTP for user %s", getattr(user, "id", None))
        return

    sid = settings.TWILIO_ACCOUNT_SID
    tok = settings.TWILIO_AUTH_TOKEN
    if not sid or not tok:
        logger.error("Twilio credentials missing.")
        return

    client = Client(sid, tok)

    # Choose sender: Messaging Service (preferred) OR direct from_ (not both)
    kwargs = {"to": f"whatsapp:{to_e164}"}
    if getattr(settings, "TWILIO_MSG_SERVICE_SID", None):
        kwargs["messaging_service_sid"] = settings.TWILIO_MSG_SERVICE_SID
    else:
        from_number = getattr(settings, "TWILIO_WHATSAPP_NUMBER", None)
        if not from_number:
            logger.error("No WhatsApp sender configured.")
            return
        kwargs["from_"] = f"whatsapp:{from_number}"

    content_sid = getattr(settings, "TWILIO_CONTENT_SID", None)
    if content_sid:
        # Map your template variables here. Example: {"1": code, "2": "10 minutes"}
        kwargs["content_sid"] = content_sid
        kwargs["content_variables"] = json.dumps({"1": code, "2": "10 minutes"})
    else:
        kwargs["body"] = f"Your EasyMarket login code is {code}. It expires in 10 minutes."

    try:
        msg = client.messages.create(**kwargs)
        logger.info("WhatsApp OTP sent to %s (SID: %s)", to_e164, msg.sid)
    except Exception as e:
        logger.exception("Failed to send WhatsApp OTP to %s: %s", to_e164, e)