# logistics/signals.py
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from logistics.models import Shipment, WarehouseShipmentNotification
from orders.models import Order, OrderItem



def generate_tracking_number_from_order_id(order_id: int) -> str:
    return f"EM{int(order_id):010d}"


@receiver(post_save, sender=Shipment)
def shipment_post_save_handler(sender, instance: Shipment, created: bool, **kwargs):
    """
    Update the related Order (tracking/status) safely.
    NOTE: Do NOT use select_for_update inside on_commit.
    """
    if not instance.order_id:
        return

    def _apply():
        order = Order.objects.filter(pk=instance.order_id).first()
        if not order:
            return

        changed_fields = []

        # tracking number only if missing
        if not getattr(order, "tracking_number", None):
            order.tracking_number = generate_tracking_number_from_order_id(order.pk)
            changed_fields.append("tracking_number")

        # status sync
        if instance.status in ["in_transit", "shipped"] and order.status not in ["shipped", "delivered", "cancelled"]:
            order.status = "shipped"
            changed_fields.append("status")

            if hasattr(order, "shipped_date") and not getattr(order, "shipped_date", None):
                order.shipped_date = instance.collect_time or instance.updated_at
                changed_fields.append("shipped_date")

        if instance.status == "delivered" and order.status != "delivered":
            order.status = "delivered"
            changed_fields.append("status")

            if hasattr(order, "delivered_date") and not getattr(order, "delivered_date", None):
                order.delivered_date = instance.updated_at
                changed_fields.append("delivered_date")

        if changed_fields:
            order.save(update_fields=list(set(changed_fields)))

    # ✅ If currently inside an atomic transaction, defer to commit. Otherwise run immediately.
    if transaction.get_connection().in_atomic_block:
        transaction.on_commit(_apply)
    else:
        _apply()


# ---- FIXED: track transition properly ----
@receiver(pre_save, sender=OrderItem)
def order_item_presave_track_old_value(sender, instance: OrderItem, **kwargs):
    """
    Store previous shipped_to_warehouse value on the instance before saving.
    """
    if not instance.pk:
        instance._old_shipped_to_warehouse = None
        return

    old_val = (
        OrderItem.objects
        .filter(pk=instance.pk)
        .values_list("shipped_to_warehouse", flat=True)
        .first()
    )
    instance._old_shipped_to_warehouse = old_val


@receiver(post_save, sender=OrderItem)
def create_warehouse_shipping_notification(sender, instance: OrderItem, created: bool, **kwargs):
    """
    Create notification ONLY when shipped_to_warehouse transitions False -> True.
    """
    old_val = getattr(instance, "_old_shipped_to_warehouse", None)

    # Only fire on updates where it flips to True
    if created or not instance.shipped_to_warehouse or old_val is True:
        return

    def _on_commit():
        store = getattr(instance.product, "store", None)
        order = instance.order

        if not store or not order:
            return

        WarehouseShipmentNotification.create_item_shipped_notification(
            order=order,
            store=store,
            items_count=1
        )

    transaction.on_commit(_on_commit)
