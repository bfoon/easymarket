from django.core.mail import send_mass_mail
from marketplace.models import Subscription

def send_newsletter(subject: str, message: str, from_email: str = "no-reply@easymarket.com"):
    emails = list(Subscription.objects.filter(active=True).values_list("email", flat=True))
    if not emails:
        return 0

    # send_mass_mail expects a list of (subject, message, from_email, recipient_list)
    payload = [(subject, message, from_email, [e]) for e in emails]
    return send_mass_mail(payload, fail_silently=True)
