"""
Easy Market Logistics — Dispatch Service
=========================================
Central service for all driver & drone assignment operations.
All dispatch logic lives here; views call services, not models directly.

Services:
  DispatchService      — create & assign pickup / last-mile tasks
  DriverQueryService   — query available drivers / drones
  PickupTaskService    — pickup-specific operations
  LastMileTaskService  — last-mile-specific operations

Author: Logistics Team
Version: 3.0.0
"""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, F, Q, QuerySet
from django.utils import timezone

from .dispatch_models import (
    DispatchBatch,
    DriverProfile,
    DroneUnit,
    LastMileTask,
    LastMileTaskEvent,
    PickupTask,
    PickupTaskEvent,
)

User = get_user_model()
logger = logging.getLogger(__name__)


# ===========================================================================
# DRIVER QUERY SERVICE
# ===========================================================================

class DriverQueryService:
    """Read-only helpers for fetching eligible drivers and drones."""

    @staticmethod
    def get_available_drivers(
        driver_type: Optional[str] = None,
        exclude_ids: Optional[List] = None,
    ) -> QuerySet[DriverProfile]:
        """
        Return drivers that are approved, active, and currently available.

        Args:
            driver_type: Filter by DriverProfile.DriverType value
                         ('easy_move', 'external', 'drone_operator')
            exclude_ids: List of DriverProfile PKs to exclude
        """
        qs = DriverProfile.objects.filter(
            is_active=True,
            vetting_status=DriverProfile.VettingStatus.APPROVED,
            availability=DriverProfile.Availability.AVAILABLE,
        ).select_related("user", "assigned_office")

        if driver_type:
            qs = qs.filter(driver_type=driver_type)

        if exclude_ids:
            qs = qs.exclude(pk__in=exclude_ids)

        return qs.order_by("user__first_name", "user__last_name")

    @staticmethod
    def get_available_easy_move_drivers() -> QuerySet[DriverProfile]:
        return DriverQueryService.get_available_drivers(
            driver_type=DriverProfile.DriverType.EASY_MOVE
        )

    @staticmethod
    def get_available_external_drivers() -> QuerySet[DriverProfile]:
        return DriverQueryService.get_available_drivers(
            driver_type=DriverProfile.DriverType.EXTERNAL
        )

    @staticmethod
    def get_available_drones() -> QuerySet[DroneUnit]:
        """Return drones that are available and sufficiently charged."""
        return DroneUnit.objects.filter(
            is_active=True,
            status=DroneUnit.DroneStatus.AVAILABLE,
            battery_level__gte=30,
        ).select_related("home_base", "assigned_operator")

    @staticmethod
    def get_driver_current_tasks(driver: DriverProfile) -> Dict[str, Any]:
        """Summary of tasks currently assigned to a driver."""
        active_pickup_count = PickupTask.objects.filter(
            assigned_driver=driver,
            status__in=[
                PickupTask.TaskStatus.ASSIGNED,
                PickupTask.TaskStatus.ACCEPTED,
                PickupTask.TaskStatus.EN_ROUTE_PICKUP,
                PickupTask.TaskStatus.ARRIVED_AT_PICKUP,
                PickupTask.TaskStatus.PICKED_UP,
                PickupTask.TaskStatus.EN_ROUTE_WAREHOUSE,
            ],
        ).count()
        active_delivery_count = LastMileTask.objects.filter(
            assigned_driver=driver,
            status__in=[
                LastMileTask.TaskStatus.ASSIGNED,
                LastMileTask.TaskStatus.ACCEPTED,
                LastMileTask.TaskStatus.OUT_FOR_DELIVERY,
                LastMileTask.TaskStatus.ARRIVED,
            ],
        ).count()
        return {
            "active_pickup_tasks": active_pickup_count,
            "active_delivery_tasks": active_delivery_count,
            "total_active": active_pickup_count + active_delivery_count,
        }

    @staticmethod
    def get_all_drivers_with_status() -> QuerySet[DriverProfile]:
        """Used for the dispatch dashboard driver roster."""
        return (
            DriverProfile.objects.select_related("user", "assigned_office")
            .prefetch_related("operated_drones")
            .annotate(
                active_tasks=Count(
                    "pickup_tasks",
                    filter=Q(
                        pickup_tasks__status__in=[
                            "assigned", "accepted", "en_route_pickup",
                            "arrived_at_pickup", "picked_up", "en_route_warehouse",
                        ]
                    ),
                )
                + Count(
                    "last_mile_tasks",
                    filter=Q(
                        last_mile_tasks__status__in=[
                            "assigned", "accepted", "out_for_delivery", "arrived",
                        ]
                    ),
                )
            )
            .order_by("availability", "user__first_name")
        )


# ===========================================================================
# DISPATCH SERVICE  (main orchestrator)
# ===========================================================================

class DispatchService:
    """
    High-level dispatch operations.
    This is the primary class views should call.
    """

    # -----------------------------------------------------------------------
    # PICKUP TASK CREATION
    # -----------------------------------------------------------------------

    @staticmethod
    @transaction.atomic
    def create_pickup_task_for_order(
        order,
        order_type: str,
        destination_warehouse,
        pickup_address: str,
        packages_count: int = 1,
        estimated_weight_kg: Optional[Decimal] = None,
        requires_vetting: bool = False,
        scheduled_pickup_time=None,
        priority: int = PickupTask.Priority.NORMAL,
        pickup_contact_name: str = "",
        pickup_contact_phone: str = "",
        special_instructions: str = "",
        created_by: Optional[User] = None,
    ) -> PickupTask:
        """
        Create a PickupTask for any order type.

        Args:
            order: The Order / B2BOrder / CrossroadOrder instance
            order_type: 'regular' | 'b2b' | 'crossroad'
            destination_warehouse: Warehouse instance (Easy Market hub)
            ...

        Returns:
            PickupTask: The newly created task
        """
        # Build FK kwargs based on order_type
        order_kwargs: Dict[str, Any] = {}
        if order_type == PickupTask.OrderType.REGULAR:
            order_kwargs["order"] = order
        elif order_type == PickupTask.OrderType.B2B:
            order_kwargs["b2b_order"] = order
        elif order_type == PickupTask.OrderType.CROSSROAD:
            order_kwargs["crossroad_order"] = order
            requires_vetting = requires_vetting or getattr(order, "requested_vetting", False)
        else:
            raise ValidationError(f"Unknown order_type: {order_type}")

        task = PickupTask.objects.create(
            order_type=order_type,
            destination_warehouse=destination_warehouse,
            pickup_address=pickup_address,
            packages_count=packages_count,
            estimated_weight_kg=estimated_weight_kg,
            requires_vetting=requires_vetting,
            scheduled_pickup_time=scheduled_pickup_time,
            priority=priority,
            pickup_contact_name=pickup_contact_name,
            pickup_contact_phone=pickup_contact_phone,
            special_instructions=special_instructions,
            **order_kwargs,
        )

        PickupTaskEvent.objects.create(
            task=task,
            event_type=PickupTaskEvent.EventType.CREATED,
            actor=created_by,
            notes=f"Task created for {order_type} order",
        )

        logger.info("PickupTask %s created for %s order %s", task.task_number, order_type, order.pk)
        return task

    # -----------------------------------------------------------------------
    # ASSIGN PICKUP TASK
    # -----------------------------------------------------------------------

    @staticmethod
    def assign_pickup_to_driver(
        task: PickupTask,
        driver: DriverProfile,
        assigned_by: User,
        vehicle=None,
        scheduled_time=None,
        notes: str = "",
    ) -> PickupTask:
        """Assign a pickup task to a ground driver (Easy Move or external)."""
        if driver.driver_type == DriverProfile.DriverType.DRONE_OPERATOR:
            raise ValidationError(
                "Drone operators cannot be assigned as ground drivers. "
                "Assign them as a drone operator via assign_pickup_to_drone()."
            )
        task.assign_driver(
            driver=driver,
            assigned_by=assigned_by,
            vehicle=vehicle,
            scheduled_time=scheduled_time,
            notes=notes,
        )
        DispatchService._send_pickup_assignment_notification(task, driver=driver)
        return task

    @staticmethod
    def assign_pickup_to_drone(
        task: PickupTask,
        drone: DroneUnit,
        assigned_by: User,
        scheduled_time=None,
        notes: str = "",
    ) -> PickupTask:
        """Assign a pickup task to an Easy Move drone."""
        if task.estimated_weight_kg and task.estimated_weight_kg > drone.max_payload_kg:
            raise ValidationError(
                f"Package weight ({task.estimated_weight_kg} kg) exceeds drone capacity "
                f"({drone.max_payload_kg} kg)."
            )
        task.assign_drone(
            drone=drone,
            assigned_by=assigned_by,
            scheduled_time=scheduled_time,
            notes=notes,
        )
        DispatchService._send_pickup_assignment_notification(task, drone=drone)
        return task

    # -----------------------------------------------------------------------
    # LAST MILE TASK CREATION
    # -----------------------------------------------------------------------

    @staticmethod
    @transaction.atomic
    def create_last_mile_task(
        shipment,
        origin_warehouse,
        recipient_name: str = "",
        recipient_phone: str = "",
        delivery_address: str = "",
        delivery_latitude=None,
        delivery_longitude=None,
        scheduled_delivery_time=None,
        priority: int = LastMileTask.Priority.NORMAL,
        special_instructions: str = "",
        created_by: Optional[User] = None,
    ) -> LastMileTask:
        """
        Create a last-mile delivery task for a shipment.
        Typically called after the package has been received at the warehouse.
        """
        # Prevent duplicates
        if hasattr(shipment, "last_mile_task"):
            raise ValidationError(
                f"Shipment {shipment.tracking_number} already has a last-mile task."
            )

        # Pull recipient info from shipment if not provided
        if not recipient_name and hasattr(shipment, "shipping_address"):
            addr = shipment.shipping_address
            recipient_name = getattr(addr, "full_name", "") or ""
            recipient_phone = getattr(addr, "phone", "") or ""
            delivery_address = str(addr) or ""

        task = LastMileTask.objects.create(
            shipment=shipment,
            origin_warehouse=origin_warehouse,
            recipient_name=recipient_name,
            recipient_phone=recipient_phone,
            delivery_address=delivery_address,
            delivery_latitude=delivery_latitude,
            delivery_longitude=delivery_longitude,
            scheduled_delivery_time=scheduled_delivery_time,
            priority=priority,
            special_instructions=special_instructions,
        )

        LastMileTaskEvent.objects.create(
            task=task,
            event_type=LastMileTaskEvent.EventType.CREATED,
            actor=created_by,
            notes="Last-mile task created",
        )

        logger.info("LastMileTask %s created for shipment %s", task.task_number, shipment.tracking_number)
        return task

    # -----------------------------------------------------------------------
    # ASSIGN LAST MILE TASK
    # -----------------------------------------------------------------------

    @staticmethod
    def assign_last_mile_to_driver(
        task: LastMileTask,
        driver: DriverProfile,
        assigned_by: User,
        vehicle=None,
        scheduled_time=None,
        notes: str = "",
    ) -> LastMileTask:
        """Assign last-mile task to a ground driver."""
        if driver.driver_type == DriverProfile.DriverType.DRONE_OPERATOR:
            raise ValidationError("Use assign_last_mile_to_drone() for drone operators.")
        task.assign_driver(
            driver=driver,
            assigned_by=assigned_by,
            vehicle=vehicle,
            scheduled_time=scheduled_time,
            notes=notes,
        )
        DispatchService._send_last_mile_assignment_notification(task, driver=driver)
        return task

    @staticmethod
    def assign_last_mile_to_drone(
        task: LastMileTask,
        drone: DroneUnit,
        assigned_by: User,
        scheduled_time=None,
        notes: str = "",
    ) -> LastMileTask:
        """Assign last-mile task to an Easy Move drone."""
        shipment = task.shipment
        weight = getattr(shipment, "weight_kg", None)
        if weight and weight > drone.max_payload_kg:
            raise ValidationError(
                f"Package weight ({weight} kg) exceeds drone capacity ({drone.max_payload_kg} kg)."
            )
        task.assign_drone(
            drone=drone,
            assigned_by=assigned_by,
            scheduled_time=scheduled_time,
            notes=notes,
        )
        DispatchService._send_last_mile_assignment_notification(task, drone=drone)
        return task

    # -----------------------------------------------------------------------
    # BATCH DISPATCH
    # -----------------------------------------------------------------------

    @staticmethod
    @transaction.atomic
    def create_dispatch_batch(
        batch_type: str,
        assigned_by: User,
        driver: Optional[DriverProfile] = None,
        drone: Optional[DroneUnit] = None,
        vehicle=None,
        pickup_task_ids: Optional[List] = None,
        last_mile_task_ids: Optional[List] = None,
        planned_start_time=None,
        notes: str = "",
    ) -> DispatchBatch:
        """
        Create a batch run and assign all specified tasks to one driver/drone.
        Ideal for optimised route planning.
        """
        if not driver and not drone:
            raise ValidationError("A batch must have either a driver or a drone assigned.")

        batch = DispatchBatch.objects.create(
            batch_type=batch_type,
            assigned_driver=driver,
            assigned_drone=drone,
            assigned_vehicle=vehicle,
            assigned_by=assigned_by,
            planned_start_time=planned_start_time,
            notes=notes,
            status=DispatchBatch.BatchStatus.ASSIGNED,
        )

        if pickup_task_ids:
            pickup_tasks = PickupTask.objects.filter(
                pk__in=pickup_task_ids,
                status=PickupTask.TaskStatus.PENDING,
            )
            for task in pickup_tasks:
                if driver:
                    task.assign_driver(driver=driver, assigned_by=assigned_by)
                elif drone:
                    task.assign_drone(drone=drone, assigned_by=assigned_by)
            batch.pickup_tasks.set(pickup_tasks)

        if last_mile_task_ids:
            last_mile_tasks = LastMileTask.objects.filter(
                pk__in=last_mile_task_ids,
                status=LastMileTask.TaskStatus.PENDING,
            )
            for task in last_mile_tasks:
                if driver:
                    task.assign_driver(driver=driver, assigned_by=assigned_by)
                elif drone:
                    task.assign_drone(drone=drone, assigned_by=assigned_by)
            batch.last_mile_tasks.set(last_mile_tasks)

        logger.info(
            "DispatchBatch %s created by %s with %d pickup + %d delivery tasks",
            batch.batch_number, assigned_by, batch.pickup_tasks.count(), batch.last_mile_tasks.count()
        )
        return batch

    # -----------------------------------------------------------------------
    # REASSIGNMENT
    # -----------------------------------------------------------------------

    @staticmethod
    @transaction.atomic
    def reassign_pickup_task(
        task: PickupTask,
        new_driver: Optional[DriverProfile],
        new_drone: Optional[DroneUnit],
        reassigned_by: User,
        reason: str = "",
    ) -> PickupTask:
        """Reassign a task already in progress to a different driver/drone."""
        old_driver = task.assigned_driver
        old_drone = task.assigned_drone

        # Free old assignee
        if old_driver:
            old_driver.set_available()
        if old_drone:
            old_drone.status = DroneUnit.DroneStatus.AVAILABLE
            old_drone.save(update_fields=["status"])

        task.status = PickupTask.TaskStatus.REASSIGNED
        task.save(update_fields=["status", "updated_at"])

        PickupTaskEvent.objects.create(
            task=task,
            event_type=PickupTaskEvent.EventType.REASSIGNED,
            actor=reassigned_by,
            notes=reason or "Reassigned",
        )

        if new_driver:
            task.assign_driver(driver=new_driver, assigned_by=reassigned_by, notes=reason)
        elif new_drone:
            task.assign_drone(drone=new_drone, assigned_by=reassigned_by, notes=reason)

        return task

    # -----------------------------------------------------------------------
    # DASHBOARD STATS
    # -----------------------------------------------------------------------

    @staticmethod
    def get_dispatch_dashboard_stats() -> Dict[str, Any]:
        """Aggregate stats for the dispatch operations dashboard."""
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        pickup_qs = PickupTask.objects.all()
        lm_qs = LastMileTask.objects.all()
        driver_qs = DriverProfile.objects.filter(is_active=True)
        drone_qs = DroneUnit.objects.filter(is_active=True)

        return {
            # Pickup tasks
            "pickup_pending": pickup_qs.filter(status=PickupTask.TaskStatus.PENDING).count(),
            "pickup_in_progress": pickup_qs.filter(
                status__in=[
                    PickupTask.TaskStatus.ASSIGNED,
                    PickupTask.TaskStatus.ACCEPTED,
                    PickupTask.TaskStatus.EN_ROUTE_PICKUP,
                    PickupTask.TaskStatus.ARRIVED_AT_PICKUP,
                    PickupTask.TaskStatus.PICKED_UP,
                    PickupTask.TaskStatus.EN_ROUTE_WAREHOUSE,
                ]
            ).count(),
            "pickup_completed_today": pickup_qs.filter(
                status=PickupTask.TaskStatus.COMPLETED,
                updated_at__gte=today_start,
            ).count(),
            "pickup_failed_today": pickup_qs.filter(
                status=PickupTask.TaskStatus.FAILED,
                updated_at__gte=today_start,
            ).count(),
            # By order type
            "pickup_regular": pickup_qs.filter(
                status=PickupTask.TaskStatus.PENDING,
                order_type=PickupTask.OrderType.REGULAR,
            ).count(),
            "pickup_b2b": pickup_qs.filter(
                status=PickupTask.TaskStatus.PENDING,
                order_type=PickupTask.OrderType.B2B,
            ).count(),
            "pickup_crossroad": pickup_qs.filter(
                status=PickupTask.TaskStatus.PENDING,
                order_type=PickupTask.OrderType.CROSSROAD,
            ).count(),
            # Last mile tasks
            "delivery_pending": lm_qs.filter(status=LastMileTask.TaskStatus.PENDING).count(),
            "delivery_in_progress": lm_qs.filter(
                status__in=[
                    LastMileTask.TaskStatus.ASSIGNED,
                    LastMileTask.TaskStatus.ACCEPTED,
                    LastMileTask.TaskStatus.OUT_FOR_DELIVERY,
                    LastMileTask.TaskStatus.ARRIVED,
                ]
            ).count(),
            "delivery_completed_today": lm_qs.filter(
                status=LastMileTask.TaskStatus.DELIVERED,
                updated_at__gte=today_start,
            ).count(),
            "delivery_failed_today": lm_qs.filter(
                status=LastMileTask.TaskStatus.FAILED_ATTEMPT,
                updated_at__gte=today_start,
            ).count(),
            # Drivers
            "drivers_available": driver_qs.filter(
                availability=DriverProfile.Availability.AVAILABLE,
                vetting_status=DriverProfile.VettingStatus.APPROVED,
            ).count(),
            "drivers_on_trip": driver_qs.filter(
                availability=DriverProfile.Availability.ON_TRIP,
            ).count(),
            "easy_move_drivers": driver_qs.filter(
                driver_type=DriverProfile.DriverType.EASY_MOVE,
                vetting_status=DriverProfile.VettingStatus.APPROVED,
            ).count(),
            "external_drivers": driver_qs.filter(
                driver_type=DriverProfile.DriverType.EXTERNAL,
                vetting_status=DriverProfile.VettingStatus.APPROVED,
            ).count(),
            "drivers_pending_vetting": driver_qs.filter(
                vetting_status__in=[
                    DriverProfile.VettingStatus.PENDING,
                    DriverProfile.VettingStatus.UNDER_REVIEW,
                ]
            ).count(),
            # Drones
            "drones_available": drone_qs.filter(
                status=DroneUnit.DroneStatus.AVAILABLE,
                battery_level__gte=30,
            ).count(),
            "drones_on_mission": drone_qs.filter(
                status=DroneUnit.DroneStatus.ON_MISSION,
            ).count(),
        }

    # -----------------------------------------------------------------------
    # PRIVATE HELPERS
    # -----------------------------------------------------------------------

    @staticmethod
    def _send_pickup_assignment_notification(
        task: PickupTask,
        driver: Optional[DriverProfile] = None,
        drone: Optional[DroneUnit] = None,
    ) -> None:
        """Fire-and-forget notification; errors are logged, not raised."""
        try:
            from marketplace.notifications import send_email, send_whatsapp

            subject = f"New Pickup Task Assigned — {task.task_number}"
            order_ref = task.source_order
            body = (
                f"Task: {task.task_number}\n"
                f"Order Type: {task.get_order_type_display()}\n"
                f"Pickup Address: {task.pickup_address}\n"
                f"Destination: {task.destination_warehouse.name}\n"
                f"Scheduled: {task.scheduled_pickup_time or 'ASAP'}\n"
                f"Priority: {task.get_priority_display()}\n"
            )
            if task.special_instructions:
                body += f"Special Instructions: {task.special_instructions}\n"

            if driver:
                send_email(subject, body, [driver.user.email])
                if driver.phone:
                    send_whatsapp(driver.phone, body)

        except Exception as e:
            logger.warning("Could not send pickup assignment notification: %s", e)

    @staticmethod
    def _send_last_mile_assignment_notification(
        task: LastMileTask,
        driver: Optional[DriverProfile] = None,
        drone: Optional[DroneUnit] = None,
    ) -> None:
        try:
            from marketplace.notifications import send_email, send_whatsapp

            subject = f"New Delivery Task — {task.task_number}"
            body = (
                f"Task: {task.task_number}\n"
                f"Recipient: {task.recipient_name}\n"
                f"Address: {task.delivery_address}\n"
                f"Scheduled: {task.scheduled_delivery_time or 'ASAP'}\n"
                f"Priority: {task.get_priority_display()}\n"
            )
            if driver:
                send_email(subject, body, [driver.user.email])
                if driver.phone:
                    send_whatsapp(driver.phone, body)
        except Exception as e:
            logger.warning("Could not send last-mile assignment notification: %s", e)


# ===========================================================================
# DRIVER VETTING SERVICE
# ===========================================================================

class DriverVettingService:
    """Handles the vetting workflow for new driver registrations."""

    @staticmethod
    @transaction.atomic
    def submit_for_review(driver: DriverProfile) -> None:
        """Move a driver from PENDING to UNDER_REVIEW."""
        if driver.vetting_status != DriverProfile.VettingStatus.PENDING:
            raise ValidationError("Only PENDING drivers can be submitted for review.")
        driver.vetting_status = DriverProfile.VettingStatus.UNDER_REVIEW
        driver.save(update_fields=["vetting_status", "updated_at"])

    @staticmethod
    @transaction.atomic
    def approve(
        driver: DriverProfile,
        approved_by: User,
        notes: str = "",
    ) -> DriverProfile:
        if driver.vetting_status not in [
            DriverProfile.VettingStatus.UNDER_REVIEW,
            DriverProfile.VettingStatus.REJECTED,  # allow re-approval after rejection
        ]:
            raise ValidationError("Driver must be UNDER_REVIEW to be approved.")
        driver.approve(approved_by=approved_by, notes=notes)
        # Set available so they immediately show in dispatch
        driver.availability = DriverProfile.Availability.AVAILABLE
        driver.save(update_fields=["availability", "updated_at"])

        DriverVettingService._notify_driver_approval(driver)
        logger.info("Driver %s approved by %s", driver, approved_by)
        return driver

    @staticmethod
    @transaction.atomic
    def reject(
        driver: DriverProfile,
        rejected_by: User,
        reason: str,
    ) -> DriverProfile:
        driver.reject(rejected_by=rejected_by, reason=reason)
        DriverVettingService._notify_driver_rejection(driver, reason)
        logger.info("Driver %s rejected by %s: %s", driver, rejected_by, reason)
        return driver

    @staticmethod
    @transaction.atomic
    def suspend(
        driver: DriverProfile,
        suspended_by: User,
        reason: str,
    ) -> DriverProfile:
        driver.suspend(suspended_by=suspended_by, reason=reason)
        logger.warning("Driver %s SUSPENDED by %s: %s", driver, suspended_by, reason)
        return driver

    @staticmethod
    def get_pending_vetting_queue() -> QuerySet[DriverProfile]:
        return DriverProfile.objects.filter(
            vetting_status__in=[
                DriverProfile.VettingStatus.PENDING,
                DriverProfile.VettingStatus.UNDER_REVIEW,
            ]
        ).select_related("user").prefetch_related("documents").order_by("created_at")

    @staticmethod
    def _notify_driver_approval(driver: DriverProfile) -> None:
        try:
            from marketplace.notifications import send_email, send_whatsapp

            msg = (
                f"Congratulations {driver.user.get_full_name()}!\n\n"
                f"Your Easy Market driver application has been approved. "
                f"You can now log in and start accepting delivery assignments.\n\n"
                f"Your Employee ID: {driver.employee_id or 'N/A'}"
            )
            send_email("Driver Application Approved — Easy Market", msg, [driver.user.email])
            if driver.phone:
                send_whatsapp(driver.phone, msg)
        except Exception as e:
            logger.warning("Could not send driver approval notification: %s", e)

    @staticmethod
    def _notify_driver_rejection(driver: DriverProfile, reason: str) -> None:
        try:
            from marketplace.notifications import send_email, send_whatsapp

            msg = (
                f"Dear {driver.user.get_full_name()},\n\n"
                f"Unfortunately your driver application has not been approved at this time.\n\n"
                f"Reason: {reason}\n\n"
                f"You may reapply after addressing the above concern."
            )
            send_email("Driver Application Update — Easy Market", msg, [driver.user.email])
            if driver.phone:
                send_whatsapp(driver.phone, msg)
        except Exception as e:
            logger.warning("Could not send driver rejection notification: %s", e)
