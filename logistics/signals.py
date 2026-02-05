# logistics/signals.py
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from logistics.models import Shipment, WarehouseShipmentNotification
from orders.models import Order, OrderItem
from crossroad_deals.models import CrossroadOrder
from .models import CrossroadLogisticsTask



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


@receiver(post_save, sender=CrossroadOrder)
def create_logistics_task_for_easy_move(sender, instance, created, **kwargs):
    """
    Automatically create a logistics task when an order with Easy Move (vetting) is created
    """
    if created and instance.requested_vetting:
        # Check if logistics task doesn't already exist
        if not hasattr(instance, 'logistics_task'):
            # Create logistics task
            task = CrossroadLogisticsTask.objects.create(
                order=instance,
                requires_vetting=True,
                status='pending',
                priority=5,  # Default priority
            )

            # Send notification to logistics team
            from crossroad_deals.tasks import send_crossroad_email

            # Get logistics team email (you'll need to configure this)
            logistics_email = "logistics@yourdomain.com"  # Update with actual email

            subject = f"New Easy Move Order - Task {task.task_id}"
            message = f"""
            New Easy Move order requires logistics handling:

            Task ID: {task.task_id}
            Order ID: {instance.order_id}
            Item: {instance.listing.title if instance.listing else 'N/A'}
            Quantity: {instance.quantity}
            Customer: {instance.buyer.get_full_name() or instance.buyer.username}

            Vendor Location: {instance.listing.location_description if instance.listing else 'N/A'}
            Delivery Location: {instance.buyer_geocode}

            Please assign an agent to handle this pickup and vetting.

            View task: [Dashboard Link]
            """

            # Send email to logistics team
            send_crossroad_email.delay(subject, message, logistics_email)


@receiver(post_save, sender=CrossroadOrder)
def update_logistics_task_on_order_change(sender, instance, created, **kwargs):
    """
    Update logistics task when order status changes
    """
    if not created and hasattr(instance, 'logistics_task'):
        task = instance.logistics_task

        # If order is cancelled, cancel the logistics task
        if instance.status == 'cancelled' and task.status not in ['delivered', 'cancelled']:
            task.status = 'cancelled'
            task.failure_reason = "Order cancelled by customer"
            task.save()

