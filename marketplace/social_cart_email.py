# marketplace/utils/social_cart_email.py
import logging
import threading
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def _send_email(subject: str, to_email: str, html_template: str, context: dict, text_template: str | None = None):
    """
    Internal: sends email using HTML template + optional text fallback.
    """
    try:
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None)
        if not from_email:
            raise RuntimeError("DEFAULT_FROM_EMAIL is not set in settings.py")

        html_body = render_to_string(html_template, context)

        if text_template:
            text_body = render_to_string(text_template, context)
        else:
            # simple fallback from context
            text_body = f"{subject}\n\nPlease view this message in HTML."

        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=from_email,
            to=[to_email],
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send(fail_silently=False)

    except Exception as e:
        logger.exception("Social cart email failed to %s: %s", to_email, str(e))


def send_email_async(subject: str, to_email: str, html_template: str, context: dict, text_template: str | None = None):
    """
    Public: run email in a background thread.
    """
    t = threading.Thread(
        target=_send_email,
        kwargs={
            "subject": subject,
            "to_email": to_email,
            "html_template": html_template,
            "context": context,
            "text_template": text_template,
        },
        daemon=True,
    )
    t.start()
