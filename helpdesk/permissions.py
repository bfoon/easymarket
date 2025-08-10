from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType


HELPDESK_GROUP_AGENT = "helpdesk_agents"
HELPDESK_GROUP_MANAGER = "helpdesk_managers"


def ensure_groups():
    # Create two groups with model-level perms
    from .models import Ticket, TicketMessage

    for name in [HELPDESK_GROUP_AGENT, HELPDESK_GROUP_MANAGER]:
        Group.objects.get_or_create(name=name)

    ct_ticket = ContentType.objects.get_for_model(Ticket)
    ct_message = ContentType.objects.get_for_model(TicketMessage)

    # Minimal useful perms (you can refine with object perms later)
    perms = [
        ("view_ticket", ct_ticket),
        ("add_ticket", ct_ticket),
        ("change_ticket", ct_ticket),
        ("delete_ticket", ct_ticket),
        ("view_ticketmessage", ct_message),
        ("add_ticketmessage", ct_message),
        ("change_ticketmessage", ct_message),
        ("delete_ticketmessage", ct_message),
    ]

    for codename, ct in perms:
        try:
            p = Permission.objects.get(codename=codename, content_type=ct)
        except Permission.DoesNotExist:
            continue
        Group.objects.filter(name__in=[HELPDESK_GROUP_AGENT, HELPDESK_GROUP_MANAGER]).update()
        Group.objects.get(name=HELPDESK_GROUP_AGENT).permissions.add(p)
        Group.objects.get(name=HELPDESK_GROUP_MANAGER).permissions.add(p)