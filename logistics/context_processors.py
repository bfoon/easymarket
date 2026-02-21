"""
Easy Market Logistics — Context Processors
===========================================
Injects navigation counts and dispatch indicators into every template.

Processors:
  logistics_nav_counts  — active shipment & B2B badges
  notification_context  — unread notification count for logistics staff
  nav_counts            — comprehensive nav badge counts
  dispatch_nav_counts   — dispatch-specific counts (pending tasks, vetting queue)

Author: Logistics Team
Version: 3.0.0
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def logistics_nav_counts(request):
    """Legacy processor: simple active shipment and B2B badge counts."""
    if not request.user.is_authenticated:
        return {}

    try:
        from .models import Shipment
        active_shipments_count = Shipment.objects.filter(
            status__in=["pending", "in_transit"]
        ).count()
    except Exception:
        active_shipments_count = 0

    try:
        from stores.b2b.models import B2BOrder
        nav_b2b_shipments_count = B2BOrder.objects.filter(status__iexact="shipped").count()
    except Exception:
        nav_b2b_shipments_count = 0

    return {
        "nav_active_shipments_count": active_shipments_count,
        "nav_b2b_shipments_count": nav_b2b_shipments_count,
    }


def notification_context(request):
    """Unread warehouse shipment notification count for logistics users."""
    if not (
        request.user.is_authenticated
        and hasattr(request.user, "is_logistic")
        and request.user.is_logistic
    ):
        return {"notification_unread_count": 0}

    try:
        from .models import WarehouseShipmentNotification
        unread_count = WarehouseShipmentNotification.get_unread_count(request.user)
    except Exception:
        unread_count = 0

    return {"notification_unread_count": unread_count}


def nav_counts(request):
    """
    Comprehensive nav badge counts for the logistics sidebar.

    Context variables injected:
      nav_active_shipments_count  — regular shipments in active statuses
      nav_b2b_shipments_count     — active B2B shipments
      nav_black_market_count      — active Crossroad / Easy Move orders
      pending_warehouse_count     — pending warehouse receipts
    """
    if not request.user.is_authenticated:
        return {}

    context = {}

    ACTIVE_SHIPMENT_STATUSES = [
        "pending", "picked_up", "shipped", "in_transit",
        "at_warehouse", "out_for_delivery",
    ]

    try:
        from .models import Shipment
        context["nav_active_shipments_count"] = Shipment.objects.filter(
            status__in=ACTIVE_SHIPMENT_STATUSES
        ).count()
    except Exception as e:
        logger.debug("nav_counts: shipments error — %s", e)
        context["nav_active_shipments_count"] = 0

    try:
        from .models import Shipment
        context["nav_b2b_shipments_count"] = Shipment.objects.filter(
            is_b2b=True,
            status__in=ACTIVE_SHIPMENT_STATUSES,
        ).count()
    except Exception as e:
        logger.debug("nav_counts: b2b shipments error — %s", e)
        context["nav_b2b_shipments_count"] = 0

    try:
        from crossroad_deals.models import CrossroadOrder
        context["nav_black_market_count"] = CrossroadOrder.objects.filter(
            delivery_method="easy_move",
            status__in=["pending", "confirmed", "pickup_scheduled", "in_transit"],
        ).count()
    except Exception as e:
        logger.debug("nav_counts: crossroad error — %s", e)
        context["nav_black_market_count"] = 0

    try:
        from .models import WarehouseReceipt
        context["pending_warehouse_count"] = WarehouseReceipt.objects.filter(
            status="pending"
        ).count()
    except Exception as e:
        logger.debug("nav_counts: warehouse receipt error — %s", e)
        context["pending_warehouse_count"] = 0

    return context


def dispatch_nav_counts(request):
    """
    Dispatch-specific badge counts.
    Only evaluated for logistics staff to avoid unnecessary DB hits.

    Context variables:
      dispatch_pending_pickups     — unassigned pickup tasks
      dispatch_pending_deliveries  — unassigned last-mile tasks
      dispatch_vetting_queue       — drivers awaiting vetting approval
      dispatch_on_trip_drivers     — drivers currently on a trip
    """
    if not request.user.is_authenticated:
        return _empty_dispatch_context()

    is_logistics = (
        request.user.is_staff
        or getattr(request.user, "is_logistic", False)
        or request.user.groups.filter(
            name__in=["Logistics", "Dispatch", "Fleet Management"]
        ).exists()
    )

    if not is_logistics:
        return _empty_dispatch_context()

    context = {}

    try:
        from .dispatch_models import PickupTask
        context["dispatch_pending_pickups"] = PickupTask.objects.filter(
            status=PickupTask.TaskStatus.PENDING
        ).count()
    except Exception as e:
        logger.debug("dispatch_nav_counts: pickup tasks error — %s", e)
        context["dispatch_pending_pickups"] = 0

    try:
        from .dispatch_models import LastMileTask
        context["dispatch_pending_deliveries"] = LastMileTask.objects.filter(
            status=LastMileTask.TaskStatus.PENDING
        ).count()
    except Exception as e:
        logger.debug("dispatch_nav_counts: last mile tasks error — %s", e)
        context["dispatch_pending_deliveries"] = 0

    try:
        from .dispatch_models import DriverProfile
        context["dispatch_vetting_queue"] = DriverProfile.objects.filter(
            vetting_status__in=[
                DriverProfile.VettingStatus.PENDING,
                DriverProfile.VettingStatus.UNDER_REVIEW,
            ]
        ).count()
    except Exception as e:
        logger.debug("dispatch_nav_counts: vetting queue error — %s", e)
        context["dispatch_vetting_queue"] = 0

    try:
        from .dispatch_models import DriverProfile
        context["dispatch_on_trip_drivers"] = DriverProfile.objects.filter(
            availability=DriverProfile.Availability.ON_TRIP
        ).count()
    except Exception as e:
        logger.debug("dispatch_nav_counts: on-trip drivers error — %s", e)
        context["dispatch_on_trip_drivers"] = 0

    # Combined urgency badge (unassigned tasks + vetting queue)
    context["dispatch_urgent_count"] = (
        context["dispatch_pending_pickups"]
        + context["dispatch_pending_deliveries"]
        + context["dispatch_vetting_queue"]
    )

    return context


def _empty_dispatch_context() -> dict:
    return {
        "dispatch_pending_pickups": 0,
        "dispatch_pending_deliveries": 0,
        "dispatch_vetting_queue": 0,
        "dispatch_on_trip_drivers": 0,
        "dispatch_urgent_count": 0,
    }