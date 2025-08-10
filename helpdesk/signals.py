from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import Ticket, TicketMessage  # ✅ Added import


@receiver(post_save, sender=TicketMessage)
def mark_first_response(sender, instance: TicketMessage, created, **kwargs):
    if not created:
        return
    ticket = instance.ticket
    # Set first_response_at when first staff (non-customer) replies
    if ticket.first_response_at is None and instance.author != ticket.customer and not instance.is_internal:
        ticket.first_response_at = timezone.now()
        ticket.save(update_fields=["first_response_at", "updated_at"])


@receiver(post_save, sender=Ticket)
def track_solved_time(sender, instance: Ticket, **kwargs):
    if instance.status == "solved" and instance.solved_at is None:
        instance.solved_at = timezone.now()
        Ticket.objects.filter(pk=instance.pk).update(solved_at=instance.solved_at)