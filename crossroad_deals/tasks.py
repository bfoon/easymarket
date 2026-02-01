# crossroad_deals/tasks.py
from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 5})
def send_crossroad_email(self, subject: str, message: str, to_email: str):
    if not to_email:
        return {"ok": False, "reason": "missing_email"}
    send_mail(
        subject=subject,
        message=message,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[to_email],
        fail_silently=False,
    )
    return {"ok": True, "type": "email", "to": to_email, "ts": timezone.now().isoformat()}


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 5})
def send_crossroad_whatsapp(self, phone: str, message: str):
    """
    Plug your WhatsApp provider here:
    - Twilio WhatsApp
    - Meta WhatsApp Cloud API
    - Termii
    - Vonage
    etc.

    For now, we just stub it (so your app works even before provider is ready).
    """
    if not phone:
        return {"ok": False, "reason": "missing_phone"}

    # TODO: Implement provider call
    # Example (pseudo):
    # provider.send_whatsapp(phone=phone, message=message)

    return {"ok": True, "type": "whatsapp", "to": phone, "ts": timezone.now().isoformat()}
