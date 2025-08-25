from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import ChatMessage
from orders.notifications import notify_new_order_message

@receiver(post_save, sender=ChatMessage)
def chatmessage_created(sender, instance, created, **kwargs):
    if created:
        notify_new_order_message(instance)
