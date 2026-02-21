"""
Easy Market Logistics — Signals
================================
All signal handlers for the logistics module.

Handlers:
  Shipment signals       — sync Order status & tracking number
  OrderItem signals      — WarehouseShipmentNotification on transition
  CrossroadOrder signals — auto-create CrossroadLogisticsTask on creation
                           cancel task on order cancellation
  PickupTask signals     — auto-create LastMileTask when pickup completes
  DriverProfile signals  — send notification on vetting status changes

Author: Logistics Team
Version: 3.0.0
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


# ===========================================================================
# SHIPMENT ↔ ORDER SYNC
# ===========================================================================

@receiver(post_save, sender="logistics.Shipment")
def shipment_post_save_handler(sender, instance, created: bool, **kwargs):
    """
    Keep the related Order tracking number and status in sync.
    Deferred with on_commit when inside an atomic block.
    """
    if not instance.order_id:
        return

    def _apply():
        from orders.models import Order

        order = Order.objects.filter(pk=instance.order_id).first()
        if not order:
            return

        changed_fields = []

        # Assign tracking number once
        if not getattr(order, "tracking_number", None):
            order.tracking_number = f"EM{int(order.pk):010d}"
            changed_fields.append("tracking_number")

        # shipped / in_transit → order becomes "shipped"
        if instance.status in ("in_transit", "shipped") and order.status not in (
            "shipped", "delivered", "cancelled"
        ):
            order.status = "shipped"
            changed_fields.append("status")
            if hasattr(order, "shipped_date") and not order.shipped_date:
                order.shipped_date = instance.collect_time or instance.updated_at
                changed_fields.append("shipped_date")

        # delivered → order becomes "delivered"
        if instance.status == "delivered" and order.status != "delivered":
            order.status = "delivered"
            changed_fields.append("status")
            if hasattr(order, "delivered_date") and not order.delivered_date:
                order.delivered_date = instance.updated_at
                changed_fields.append("delivered_date")

        if changed_fields:
            order.save(update_fields=list(set(changed_fields)))

    if transaction.get_connection().in_atomic_block:
        transaction.on_commit(_apply)
    else:
        _apply()


# ===========================================================================
# ORDER ITEM → WAREHOUSE SHIPMENT NOTIFICATION
# ===========================================================================

@receiver(pre_save, sender="orders.OrderItem")
def order_item_presave_track_old_value(sender, instance, **kwargs):
    """Cache previous shipped_to_warehouse before the save."""
    if not instance.pk:
        instance._old_shipped_to_warehouse = None
        return
    instance._old_shipped_to_warehouse = (
        sender.objects.filter(pk=instance.pk)
        .values_list("shipped_to_warehouse", flat=True)
        .first()
    )


@receiver(post_save, sender="orders.OrderItem")
def create_warehouse_shipping_notification(sender, instance, created: bool, **kwargs):
    """
    Emit a WarehouseShipmentNotification exactly once:
    when shipped_to_warehouse transitions False → True.
    """
    old_val = getattr(instance, "_old_shipped_to_warehouse", None)
    if created or not instance.shipped_to_warehouse or old_val is True:
        return

    def _on_commit():
        from logistics.models import WarehouseShipmentNotification

        store = getattr(instance.product, "store", None)
        order = instance.order
        if not store or not order:
            return
        WarehouseShipmentNotification.create_item_shipped_notification(
            order=order, store=store, items_count=1
        )

    transaction.on_commit(_on_commit)


# ===========================================================================
# CROSSROAD ORDER → LOGISTICS TASK
# ===========================================================================

@receiver(post_save, sender="crossroad_deals.CrossroadOrder")
def create_logistics_task_for_easy_move(sender, instance, created: bool, **kwargs):
    """
    Auto-create a CrossroadLogisticsTask when a new Easy Move (vetting) order is placed.
    Also creates a PickupTask so it appears in the unified dispatch board.
    """
    if not created or not instance.requested_vetting:
        return

    def _create_task():
        from logistics.models import CrossroadLogisticsTask, Warehouse

        # Prevent duplicate task
        if CrossroadLogisticsTask.objects.filter(order=instance).exists():
            return

        task = CrossroadLogisticsTask.objects.create(
            order=instance,
            requires_vetting=True,
            status="pending",
            priority=5,
        )

        # Auto-create PickupTask on the dispatch board
        try:
            from logistics.dispatch_models import PickupTask
            from logistics.dispatch_services import DispatchService

            # Use the first active Easy Market warehouse as destination
            warehouse = (
                Warehouse.objects.filter(is_active=True).order_by("name").first()
            )
            if warehouse:
                pickup_address = (
                    getattr(instance.listing, "location_description", "")
                    or str(getattr(instance, "seller_geocode", ""))
                    or "Seller location — confirm with order details"
                )
                DispatchService.create_pickup_task_for_order(
                    order=instance,
                    order_type=PickupTask.OrderType.CROSSROAD,
                    destination_warehouse=warehouse,
                    pickup_address=pickup_address,
                    requires_vetting=True,
                    priority=PickupTask.Priority.HIGH,
                    pickup_contact_name=(
                        instance.listing.seller.get_full_name()
                        if hasattr(instance, "listing") and instance.listing
                        else ""
                    ),
                )
        except Exception as exc:
            logger.warning("Could not auto-create PickupTask for CrossroadOrder %s: %s", instance.pk, exc)

        # Email logistics team
        try:
            from crossroad_deals.tasks import send_crossroad_email

            subject = f"[Easy Move] New Vetting Order — Task {task.task_id}"
            body = (
                f"A new Easy Move order requires logistics handling.\n\n"
                f"Task ID:     {task.task_id}\n"
                f"Order ID:    {instance.order_id}\n"
                f"Item:        {instance.listing.title if instance.listing else 'N/A'}\n"
                f"Qty:         {instance.quantity}\n"
                f"Customer:    {instance.buyer.get_full_name() or instance.buyer.username}\n\n"
                f"Vendor Location: {getattr(instance.listing, 'location_description', 'N/A') if instance.listing else 'N/A'}\n"
                f"Delivery:        {instance.buyer_geocode}\n\n"
                f"Please assign a driver in the Dispatch Centre."
            )
            send_crossroad_email.delay(subject, body, "logistics@easymarket.com")
        except Exception as exc:
            logger.warning("Could not send Easy Move logistics email: %s", exc)

    if transaction.get_connection().in_atomic_block:
        transaction.on_commit(_create_task)
    else:
        _create_task()


@receiver(post_save, sender="crossroad_deals.CrossroadOrder")
def update_logistics_task_on_order_change(sender, instance, created: bool, **kwargs):
    """Cascade order cancellation to the logistics task and any open PickupTask."""
    if created or instance.status != "cancelled":
        return

    # Cancel CrossroadLogisticsTask
    try:
        from logistics.models import CrossroadLogisticsTask
        task = CrossroadLogisticsTask.objects.filter(
            order=instance
        ).exclude(status__in=["delivered", "cancelled"]).first()
        if task:
            task.status = "cancelled"
            task.failure_reason = "Order cancelled by customer"
            task.save(update_fields=["status", "failure_reason"])
    except Exception as exc:
        logger.warning("Could not cancel CrossroadLogisticsTask for order %s: %s", instance.pk, exc)

    # Cancel open PickupTask
    def _cancel_pickup():
        from logistics.dispatch_models import PickupTask

        open_tasks = PickupTask.objects.filter(
            crossroad_order=instance,
        ).exclude(status__in=[PickupTask.TaskStatus.COMPLETED, PickupTask.TaskStatus.FAILED])

        for pt in open_tasks:
            pt.fail(actor=None, reason="Crossroad order cancelled by customer")

    if transaction.get_connection().in_atomic_block:
        transaction.on_commit(_cancel_pickup)
    else:
        _cancel_pickup()


# ===========================================================================
# PICKUP TASK → AUTO-CREATE LAST MILE TASK
# ===========================================================================

@receiver(post_save, sender="logistics.PickupTask")
def auto_create_last_mile_on_pickup_complete(sender, instance, created: bool, **kwargs):
    """
    When a PickupTask is marked COMPLETED and the related order has a Shipment
    that has been received at the warehouse, automatically queue a LastMileTask.

    Only fires for regular orders (B2B and Crossroad typically have manual last-mile).
    """
    from logistics.dispatch_models import PickupTask  # local import for safety

    if instance.status != PickupTask.TaskStatus.COMPLETED:
        return
    if instance.order_type != PickupTask.OrderType.REGULAR:
        return
    if not instance.order_id:
        return

    def _maybe_create():
        from logistics.models import Shipment
        from logistics.dispatch_models import LastMileTask
        from logistics.dispatch_services import DispatchService

        # Find the shipment for this order
        shipment = (
            Shipment.objects.filter(order_id=instance.order_id)
            .exclude(status__in=["cancelled", "returned"])
            .first()
        )
        if not shipment:
            return

        # Skip if already has a last-mile task
        if hasattr(shipment, "last_mile_task"):
            return

        try:
            DispatchService.create_last_mile_task(
                shipment=shipment,
                origin_warehouse=instance.destination_warehouse,
                priority=instance.priority,
                special_instructions=instance.special_instructions,
            )
            logger.info(
                "Auto-created LastMileTask for shipment %s after PickupTask %s completed",
                shipment.tracking_number,
                instance.task_number,
            )
        except Exception as exc:
            logger.warning(
                "Could not auto-create LastMileTask for shipment %s: %s",
                shipment.pk, exc
            )

    if transaction.get_connection().in_atomic_block:
        transaction.on_commit(_maybe_create)
    else:
        _maybe_create()


# ===========================================================================
# LAST MILE TASK → SYNC SHIPMENT STATUS
# ===========================================================================

@receiver(post_save, sender="logistics.LastMileTask")
def sync_shipment_on_last_mile_status(sender, instance, created: bool, **kwargs):
    """Keep the Shipment status in sync with the LastMileTask."""
    from logistics.dispatch_models import LastMileTask  # local import

    if created:
        return

    def _sync():
        shipment = instance.shipment
        if instance.status == LastMileTask.TaskStatus.OUT_FOR_DELIVERY and shipment.status != "in_transit":
            shipment.status = "in_transit"
            shipment.save(update_fields=["status", "updated_at"])

        elif instance.status == LastMileTask.TaskStatus.DELIVERED and shipment.status != "delivered":
            shipment.status = "delivered"
            shipment.actual_dropoff_time = instance.actual_delivery_time or timezone.now()
            shipment.save(update_fields=["status", "actual_dropoff_time", "updated_at"])

    try:
        from django.utils import timezone
        if transaction.get_connection().in_atomic_block:
            transaction.on_commit(_sync)
        else:
            _sync()
    except Exception as exc:
        logger.warning("Could not sync shipment from LastMileTask: %s", exc)