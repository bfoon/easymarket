from django.core.mail import send_mail
from django.urls import reverse


def notify_new_ticket(ticket):
    subject = f"[EasyMarket Helpdesk] New ticket #{ticket.id}: {ticket.subject}"
    try:
        to = [ticket.customer.email] if ticket.customer and ticket.customer.email else []
        if to:
            send_mail(subject, ticket.description, None, to, fail_silently=True)
    except Exception:
        pass


def ticket_url(ticket, request=None):
    url = reverse("helpdesk:ticket_detail", args=[ticket.id])
    if request:
        return request.build_absolute_uri(url)
    return url