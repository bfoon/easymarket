from django.db.models.signals import post_save
from django.dispatch import receiver

from orders.models import Return, ReturnStatusHistory
from stores.models import Store
from .services.return_notifications import notify_store_return_created, notify_buyer_status_change

@receiver(post_save, sender=Return)
def _notify_store_on_return_created(sender, instance: Return, created, **kwargs):
    if not created:
        return
    # Identify stores involved (usually one)
    store_ids = list(instance.items.values_list('product__store_id', flat=True).distinct())
    for sid in store_ids:
        try:
            store = Store.objects.select_related('owner').get(pk=sid)
        except Store.DoesNotExist:
            continue
        notify_store_return_created(instance, store, store.owner)

@receiver(post_save, sender=ReturnStatusHistory)
def _notify_buyer_on_status_change(sender, instance: ReturnStatusHistory, created, **kwargs):
    if not created:
        return
    # Only notify for customer-facing statuses
    if instance.status in ['approved', 'rejected', 'in_transit', 'received', 'completed', 'cancelled', 'pending']:
        notify_buyer_status_change(instance.return_request, instance)
