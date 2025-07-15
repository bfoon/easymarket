import random
from django.db.models.signals import post_save
from django.dispatch import receiver
from logistics.models import Shipment
from orders.models import Order

def generate_tracking_number():
    return f"EM{random.randint(10000000, 99999999)}"

@receiver(post_save, sender=Shipment)
def shipment_post_save_handler(sender, instance, created, **kwargs):
    # Auto-generate tracking number only once
    if not instance.order.tracking_number:
        instance.order.tracking_number = generate_tracking_number()
        instance.order.save(update_fields=['tracking_number'])

    # Sync order status
    if instance.status == 'shipped' and instance.order.status != 'shipped':
        instance.order.status = 'shipped'
        instance.order.collect_time = instance.collect_time or instance.updated_at
        instance.order.save()
