from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.db.models.signals import pre_save, post_save
from marketplace.utils import migrate_session_cart_to_user
from django.core.cache import cache
from .models import Product
from django.db import transaction
from stock.models import Stock
from .background import submit
from .notifications import notify_wishlist_back_in_stock_threadsafe

@receiver(user_logged_in)
def move_session_cart_on_login(sender, request, user, **kwargs):
    migrate_session_cart_to_user(request, user)


@receiver(pre_save, sender=Stock)
def _capture_old_qty(sender, instance: Stock, **kwargs):
    if instance.pk:
        try:
            old = Stock.objects.get(pk=instance.pk)
            instance._old_qty = old.quantity
        except Stock.DoesNotExist:
            instance._old_qty = None
    else:
        instance._old_qty = None

@receiver(post_save, sender=Stock)
def _notify_back_in_stock(sender, instance: Stock, created, **kwargs):
    old_qty = getattr(instance, "_old_qty", None)
    new_qty = instance.quantity
    # If not a real change, skip
    if old_qty is None:
        old_qty = 0 if created else None

    if old_qty is not None and old_qty <= 0 and new_qty > 0:
        product_id = instance.product_id
        transaction.on_commit(lambda: submit(
            notify_wishlist_back_in_stock_threadsafe, product_id, old_qty, new_qty
        ))