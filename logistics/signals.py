# logistics/signals.py
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from logistics.models import Shipment
from orders.models import Order


def generate_tracking_number_from_order_id(order_id: int) -> str:
    """
    Sequential tracking number using Order ID.
    Example: order_id=1 -> EM0000000001
    """
    return f"EM{int(order_id):010d}"


@receiver(post_save, sender=Shipment)
def shipment_post_save_handler(sender, instance: Shipment, created: bool, **kwargs):
    """
    - If shipment has an order, ensure order.tracking_number exists (only once).
    - Sync order status when shipment status moves forward.
    """
    # Shipment may be created without an order (your error shows instance.order is None)
    if not instance.order_id:
        return

    # Run after DB commit to avoid weird partial-save states
    def _on_commit():
        # Lock the order row to prevent race conditions when multiple shipments save at same time
        order = (
            Order.objects.select_for_update()
            .filter(pk=instance.order_id)
            .first()
        )
        if not order:
            return

        changed_fields = []

        # 1) Tracking number (only if missing)
        if not order.tracking_number:
            # Uses Order ID (sequential & stable)
            order.tracking_number = generate_tracking_number_from_order_id(order.pk)
            changed_fields.append("tracking_number")

        # 2) Sync order status based on shipment status
        # Adjust these rules to match your logistics status flow
        if instance.status in ["in_transit", "shipped"] and order.status not in ["shipped", "delivered", "cancelled"]:
            order.status = "shipped"
            changed_fields.append("status")

            # Use shipped_date if it exists on Order
            if hasattr(order, "shipped_date") and not order.shipped_date:
                order.shipped_date = instance.collect_time or instance.updated_at
                changed_fields.append("shipped_date")

        if instance.status == "delivered" and order.status != "delivered":
            order.status = "delivered"
            changed_fields.append("status")

            if hasattr(order, "delivered_date") and not order.delivered_date:
                order.delivered_date = instance.updated_at
                changed_fields.append("delivered_date")

        if changed_fields:
            order.save(update_fields=list(set(changed_fields)))

    transaction.on_commit(_on_commit)
