"""
Easy Market Logistics — Dispatch Views
=======================================
All views for the dispatch & assignment interface.

Views overview:
  DRIVER MANAGEMENT
    DriverRosterView         — list all drivers with real-time status
    DriverRegistrationView   — register a new driver (with photo upload)
    DriverProfileView        — view a driver's full profile
    DriverEditView           — edit driver details
    VettingQueueView         — pending applications awaiting approval
    approve_driver           — POST: approve a driver
    reject_driver            — POST: reject a driver
    suspend_driver           — POST: suspend a driver

  PICKUP ASSIGNMENTS
    PickupTaskListView       — all pickup tasks (filterable by status/type)
    PickupTaskDetailView     — task detail + event log
    CreatePickupTaskView     — create a pickup task for any order
    AssignPickupTaskView     — assign driver/drone to a pickup task
    PickupTaskStatusUpdateView — update task status (mobile-friendly)

  LAST MILE ASSIGNMENTS
    LastMileTaskListView     — all last-mile tasks
    LastMileTaskDetailView   — task detail + event log
    CreateLastMileTaskView   — create a last-mile task from a shipment
    AssignLastMileTaskView   — assign driver/drone to a delivery task

  DISPATCH DASHBOARD
    DispatchDashboardView    — KPI overview + live task board
    DispatchBatchCreateView  — create a multi-task batch run

  AJAX / API ENDPOINTS
    available_drivers_api    — JSON: available drivers for assignment modal
    available_drones_api     — JSON: available drones
    driver_tasks_api         — JSON: current tasks for a driver

Author: Logistics Team
Version: 3.0.0
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from .dispatch_models import (
    DispatchBatch,
    DriverDocument,
    DriverProfile,
    DroneUnit,
    LastMileTask,
    LastMileTaskEvent,
    PickupTask,
    PickupTaskEvent,
)
from .dispatch_services import (
    DispatchService,
    DriverQueryService,
    DriverVettingService,
)

logger = logging.getLogger(__name__)


# ===========================================================================
# ACCESS CONTROL
# ===========================================================================

def is_logistics_staff(user) -> bool:
    return user.is_active and (
        user.is_staff
        or user.groups.filter(name__in=["Logistics", "Dispatch", "Fleet Management"]).exists()
        or getattr(user, "is_logistic", False)
    )


class LogisticsRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return is_logistics_staff(self.request.user)

    def handle_no_permission(self):
        messages.error(self.request, "You do not have access to the Logistics Dispatch module.")
        return redirect("logistics:dashboard")


# ===========================================================================
# DISPATCH DASHBOARD
# ===========================================================================

class DispatchDashboardView(LogisticsRequiredMixin, View):
    template_name = "logistics/dispatch/dashboard.html"

    def get(self, request):
        stats = DispatchService.get_dispatch_dashboard_stats()

        # Live task boards
        pending_pickups = (
            PickupTask.objects.filter(status=PickupTask.TaskStatus.PENDING)
            .select_related("destination_warehouse", "order", "b2b_order", "crossroad_order")
            .order_by("-priority", "-created_at")[:20]
        )
        in_progress_pickups = (
            PickupTask.objects.filter(
                status__in=[
                    PickupTask.TaskStatus.ASSIGNED,
                    PickupTask.TaskStatus.ACCEPTED,
                    PickupTask.TaskStatus.EN_ROUTE_PICKUP,
                    PickupTask.TaskStatus.ARRIVED_AT_PICKUP,
                    PickupTask.TaskStatus.PICKED_UP,
                    PickupTask.TaskStatus.EN_ROUTE_WAREHOUSE,
                ]
            )
            .select_related("assigned_driver__user", "assigned_drone", "destination_warehouse")
            .order_by("-priority", "-assigned_at")[:20]
        )
        pending_deliveries = (
            LastMileTask.objects.filter(status=LastMileTask.TaskStatus.PENDING)
            .select_related("shipment", "origin_warehouse")
            .order_by("-priority", "-created_at")[:20]
        )
        in_progress_deliveries = (
            LastMileTask.objects.filter(
                status__in=[
                    LastMileTask.TaskStatus.ASSIGNED,
                    LastMileTask.TaskStatus.ACCEPTED,
                    LastMileTask.TaskStatus.OUT_FOR_DELIVERY,
                    LastMileTask.TaskStatus.ARRIVED,
                ]
            )
            .select_related("assigned_driver__user", "assigned_drone", "origin_warehouse")
            .order_by("-priority", "-assigned_at")[:20]
        )

        # Driver roster (top strip)
        drivers = DriverQueryService.get_all_drivers_with_status()[:20]

        context = {
            "page_title": "Dispatch Operations Centre",
            "stats": stats,
            "pending_pickups": pending_pickups,
            "in_progress_pickups": in_progress_pickups,
            "pending_deliveries": pending_deliveries,
            "in_progress_deliveries": in_progress_deliveries,
            "drivers": drivers,
            "now": timezone.now(),
        }
        return render(request, self.template_name, context)


# ===========================================================================
# DRIVER MANAGEMENT
# ===========================================================================

class DriverRosterView(LogisticsRequiredMixin, View):
    template_name = "logistics/dispatch/driver_roster.html"

    def get(self, request):
        qs = DriverProfile.objects.select_related("user", "assigned_office").annotate(
            active_tasks=Count(
                "pickup_tasks",
                filter=Q(pickup_tasks__status__in=["assigned", "accepted", "en_route_pickup", "picked_up"]),
            )
        )

        # Filters
        driver_type = request.GET.get("type", "")
        vetting_status = request.GET.get("vetting", "")
        availability = request.GET.get("avail", "")
        search = request.GET.get("q", "").strip()

        if driver_type:
            qs = qs.filter(driver_type=driver_type)
        if vetting_status:
            qs = qs.filter(vetting_status=vetting_status)
        if availability:
            qs = qs.filter(availability=availability)
        if search:
            qs = qs.filter(
                Q(user__first_name__icontains=search)
                | Q(user__last_name__icontains=search)
                | Q(user__email__icontains=search)
                | Q(employee_id__icontains=search)
                | Q(phone__icontains=search)
            )

        paginator = Paginator(qs.order_by("availability", "user__first_name"), 25)
        page = paginator.get_page(request.GET.get("page"))

        context = {
            "page_title": "Driver Roster",
            "drivers": page,
            "driver_type_choices": DriverProfile.DriverType.choices,
            "vetting_choices": DriverProfile.VettingStatus.choices,
            "availability_choices": DriverProfile.Availability.choices,
            "selected_type": driver_type,
            "selected_vetting": vetting_status,
            "selected_avail": availability,
            "search": search,
        }
        return render(request, self.template_name, context)


class DriverRegistrationView(LogisticsRequiredMixin, View):
    """Register a new driver (Easy Move or external) with photo & documents."""
    template_name = "logistics/dispatch/driver_register.html"

    def get(self, request):
        context = {
            "page_title": "Register New Driver",
            "driver_type_choices": DriverProfile.DriverType.choices,
            "doc_type_choices": DriverDocument.DocType.choices,
        }
        return render(request, self.template_name, context)

    def post(self, request):
        data = request.POST
        files = request.FILES

        # Validate required user linkage
        user_id = data.get("user_id")
        if not user_id:
            messages.error(request, "Please select a user account for this driver.")
            return redirect(request.path)

        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            messages.error(request, "User account not found.")
            return redirect(request.path)

        if hasattr(user, "dispatch_driver_profile"):
            messages.error(request, f"A driver profile already exists for {user}.")
            return redirect("logistics:dispatch_driver_detail", pk=user.dispatch_driver_profile.pk)

        try:
            profile = DriverProfile.objects.create(
                user=user,
                driver_type=data.get("driver_type", DriverProfile.DriverType.EXTERNAL),
                phone=data.get("phone", ""),
                national_id_number=data.get("national_id_number", ""),
                license_number=data.get("license_number", ""),
                license_category=data.get("license_category", ""),
                license_expiry=data.get("license_expiry") or None,
                date_of_birth=data.get("date_of_birth") or None,
                emergency_contact_name=data.get("emergency_contact_name", ""),
                emergency_contact_phone=data.get("emergency_contact_phone", ""),
                photo=files.get("photo"),
                vetting_status=DriverProfile.VettingStatus.PENDING,
            )

            # Attach license document if provided
            if files.get("license_document"):
                DriverDocument.objects.create(
                    driver=profile,
                    doc_type=DriverDocument.DocType.LICENSE,
                    file=files["license_document"],
                    expiry_date=data.get("license_expiry") or None,
                )

            # Auto-submit for review if admin-created
            if request.user.is_staff:
                DriverVettingService.submit_for_review(profile)

            messages.success(request, f"Driver profile created for {user.get_full_name()}.")
            return redirect("logistics:dispatch_driver_detail", pk=profile.pk)

        except Exception as e:
            logger.exception("Error creating driver profile")
            messages.error(request, f"Error creating driver profile: {e}")
            return redirect(request.path)


class DriverProfileView(LogisticsRequiredMixin, DetailView):
    model = DriverProfile
    template_name = "logistics/dispatch/driver_detail.html"
    context_object_name = "driver"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        driver = self.object
        ctx.update({
            "page_title": f"Driver — {driver.user.get_full_name()}",
            "documents": driver.documents.order_by("-created_at"),
            "recent_pickup_tasks": PickupTask.objects.filter(
                assigned_driver=driver
            ).order_by("-created_at")[:10],
            "recent_last_mile_tasks": LastMileTask.objects.filter(
                assigned_driver=driver
            ).order_by("-created_at")[:10],
            "current_tasks": DriverQueryService.get_driver_current_tasks(driver),
            "doc_type_choices": DriverDocument.DocType.choices,
        })
        return ctx


class DriverEditView(LogisticsRequiredMixin, View):
    template_name = "logistics/dispatch/driver_edit.html"

    def get(self, request, pk):
        driver = get_object_or_404(DriverProfile, pk=pk)
        return render(request, self.template_name, {
            "driver": driver,
            "page_title": f"Edit Driver — {driver.user.get_full_name()}",
            "driver_type_choices": DriverProfile.DriverType.choices,
            "availability_choices": DriverProfile.Availability.choices,
        })

    def post(self, request, pk):
        driver = get_object_or_404(DriverProfile, pk=pk)
        data = request.POST
        files = request.FILES

        fields_to_save = []
        for field in [
            "phone", "national_id_number", "license_number", "license_category",
            "emergency_contact_name", "emergency_contact_phone", "notes",
        ]:
            if field in data:
                setattr(driver, field, data[field])
                fields_to_save.append(field)

        for date_field in ["license_expiry", "date_of_birth", "date_hired"]:
            if data.get(date_field):
                setattr(driver, date_field, data[date_field])
                fields_to_save.append(date_field)

        if "availability" in data and request.user.is_staff:
            driver.availability = data["availability"]
            fields_to_save.append("availability")

        if files.get("photo"):
            driver.photo = files["photo"]
            fields_to_save.append("photo")

        if fields_to_save:
            fields_to_save.append("updated_at")
            driver.save(update_fields=fields_to_save)
            messages.success(request, "Driver profile updated.")
        else:
            messages.info(request, "No changes detected.")

        return redirect("logistics:dispatch_driver_detail", pk=driver.pk)


# ---------------------------------------------------------------------------
# VETTING
# ---------------------------------------------------------------------------

class VettingQueueView(LogisticsRequiredMixin, View):
    template_name = "logistics/dispatch/vetting_queue.html"

    def get(self, request):
        pending = DriverVettingService.get_pending_vetting_queue()
        context = {
            "page_title": "Driver Vetting Queue",
            "drivers": pending,
            "doc_type_labels": dict(DriverDocument.DocType.choices),
        }
        return render(request, self.template_name, context)


@login_required
@user_passes_test(is_logistics_staff)
def approve_driver(request, pk):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    driver = get_object_or_404(DriverProfile, pk=pk)
    notes = request.POST.get("notes", "")
    try:
        DriverVettingService.approve(driver=driver, approved_by=request.user, notes=notes)
        messages.success(request, f"{driver.user.get_full_name()} has been approved.")
    except ValidationError as e:
        messages.error(request, str(e))
    return redirect("logistics:dispatch_vetting_queue")


@login_required
@user_passes_test(is_logistics_staff)
def reject_driver(request, pk):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    driver = get_object_or_404(DriverProfile, pk=pk)
    reason = request.POST.get("reason", "").strip()
    if not reason:
        messages.error(request, "A rejection reason is required.")
        return redirect("logistics:dispatch_vetting_queue")
    try:
        DriverVettingService.reject(driver=driver, rejected_by=request.user, reason=reason)
        messages.warning(request, f"{driver.user.get_full_name()} has been rejected.")
    except ValidationError as e:
        messages.error(request, str(e))
    return redirect("logistics:dispatch_vetting_queue")


@login_required
@user_passes_test(is_logistics_staff)
def suspend_driver(request, pk):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    driver = get_object_or_404(DriverProfile, pk=pk)
    reason = request.POST.get("reason", "").strip()
    if not reason:
        messages.error(request, "A suspension reason is required.")
        return redirect("logistics:dispatch_driver_detail", pk=pk)
    try:
        DriverVettingService.suspend(driver=driver, suspended_by=request.user, reason=reason)
        messages.warning(request, f"{driver.user.get_full_name()} has been suspended.")
    except ValidationError as e:
        messages.error(request, str(e))
    return redirect("logistics:dispatch_driver_detail", pk=pk)


# ===========================================================================
# PICKUP TASK VIEWS
# ===========================================================================

class PickupTaskListView(LogisticsRequiredMixin, View):
    template_name = "logistics/dispatch/pickup_task_list.html"

    def get(self, request):
        qs = PickupTask.objects.select_related(
            "assigned_driver__user",
            "assigned_drone",
            "destination_warehouse",
            "order",
            "b2b_order",
            "crossroad_order",
        )

        # Filters
        status = request.GET.get("status", "")
        order_type = request.GET.get("order_type", "")
        method = request.GET.get("method", "")
        search = request.GET.get("q", "").strip()
        overdue_only = request.GET.get("overdue") == "1"

        if status:
            qs = qs.filter(status=status)
        if order_type:
            qs = qs.filter(order_type=order_type)
        if method:
            qs = qs.filter(pickup_method=method)
        if search:
            qs = qs.filter(
                Q(task_number__icontains=search)
                | Q(pickup_address__icontains=search)
                | Q(pickup_contact_name__icontains=search)
            )
        if overdue_only:
            qs = qs.filter(
                scheduled_pickup_time__lt=timezone.now(),
            ).exclude(status__in=[PickupTask.TaskStatus.COMPLETED, PickupTask.TaskStatus.FAILED])

        paginator = Paginator(qs.order_by("-priority", "-created_at"), 30)
        page = paginator.get_page(request.GET.get("page"))

        context = {
            "page_title": "Pickup Tasks",
            "tasks": page,
            "status_choices": PickupTask.TaskStatus.choices,
            "order_type_choices": PickupTask.OrderType.choices,
            "method_choices": PickupTask.PickupMethod.choices,
            "selected_status": status,
            "selected_order_type": order_type,
            "selected_method": method,
            "search": search,
            "overdue_only": overdue_only,
        }
        return render(request, self.template_name, context)


class PickupTaskDetailView(LogisticsRequiredMixin, View):
    template_name = "logistics/dispatch/pickup_task_detail.html"

    def get(self, request, pk):
        task = get_object_or_404(
            PickupTask.objects.select_related(
                "assigned_driver__user",
                "assigned_drone",
                "destination_warehouse",
                "assigned_by",
                "order",
                "b2b_order",
                "crossroad_order",
            ),
            pk=pk,
        )
        events = task.events.select_related("actor").order_by("created_at")
        available_drivers = DriverQueryService.get_available_drivers()
        available_drones = DriverQueryService.get_available_drones()

        context = {
            "page_title": f"Pickup Task — {task.task_number}",
            "task": task,
            "events": events,
            "available_drivers": available_drivers,
            "available_drones": available_drones,
            "can_assign": task.status in [
                PickupTask.TaskStatus.PENDING,
                PickupTask.TaskStatus.REASSIGNED,
            ],
        }
        return render(request, self.template_name, context)


class CreatePickupTaskView(LogisticsRequiredMixin, View):
    """Create a pickup task for any order type."""
    template_name = "logistics/dispatch/pickup_task_create.html"

    def get(self, request):
        from logistics.models import Warehouse
        context = {
            "page_title": "Create Pickup Task",
            "order_type_choices": PickupTask.OrderType.choices,
            "priority_choices": PickupTask.Priority.choices,
            "warehouses": Warehouse.objects.filter(is_active=True).order_by("name"),
        }
        return render(request, self.template_name, context)

    def post(self, request):
        from logistics.models import Warehouse
        data = request.POST
        order_type = data.get("order_type")
        order_id = data.get("order_id")
        warehouse_id = data.get("warehouse_id")

        # Load the order
        try:
            order, warehouse = _load_order_and_warehouse(order_type, order_id, warehouse_id)
        except (ValueError, Exception) as e:
            messages.error(request, str(e))
            return redirect(request.path + f"?order_type={order_type}")

        try:
            task = DispatchService.create_pickup_task_for_order(
                order=order,
                order_type=order_type,
                destination_warehouse=warehouse,
                pickup_address=data.get("pickup_address", ""),
                packages_count=int(data.get("packages_count", 1)),
                priority=int(data.get("priority", PickupTask.Priority.NORMAL)),
                pickup_contact_name=data.get("pickup_contact_name", ""),
                pickup_contact_phone=data.get("pickup_contact_phone", ""),
                special_instructions=data.get("special_instructions", ""),
                scheduled_pickup_time=data.get("scheduled_pickup_time") or None,
                created_by=request.user,
            )
            messages.success(request, f"Pickup task {task.task_number} created.")
            return redirect("logistics:dispatch_pickup_task_detail", pk=task.pk)
        except ValidationError as e:
            messages.error(request, str(e))
            return redirect(request.path)


class AssignPickupTaskView(LogisticsRequiredMixin, View):
    """Assign a driver or drone to a pickup task (AJAX-friendly)."""

    def post(self, request, pk):
        task = get_object_or_404(PickupTask, pk=pk)
        data = request.POST
        assignment_type = data.get("assignment_type")  # 'driver' or 'drone'

        try:
            if assignment_type == "driver":
                driver = get_object_or_404(DriverProfile, pk=data.get("driver_id"))
                vehicle_id = data.get("vehicle_id")
                vehicle = None
                if vehicle_id:
                    from logistics.models import Vehicle
                    vehicle = Vehicle.objects.filter(pk=vehicle_id, is_active=True).first()
                scheduled_time = data.get("scheduled_pickup_time") or None

                DispatchService.assign_pickup_to_driver(
                    task=task,
                    driver=driver,
                    assigned_by=request.user,
                    vehicle=vehicle,
                    scheduled_time=scheduled_time,
                    notes=data.get("notes", ""),
                )
                messages.success(
                    request,
                    f"Task {task.task_number} assigned to {driver.user.get_full_name()}.",
                )

            elif assignment_type == "drone":
                drone = get_object_or_404(DroneUnit, pk=data.get("drone_id"))
                DispatchService.assign_pickup_to_drone(
                    task=task,
                    drone=drone,
                    assigned_by=request.user,
                    notes=data.get("notes", ""),
                )
                messages.success(
                    request,
                    f"Task {task.task_number} assigned to drone {drone.drone_id}.",
                )
            else:
                messages.error(request, "Please select a driver or drone.")

        except ValidationError as e:
            messages.error(request, str(e))

        return redirect("logistics:dispatch_pickup_task_detail", pk=task.pk)


class PickupTaskStatusUpdateView(LogisticsRequiredMixin, View):
    """
    Update a pickup task status.
    Also used by the driver mobile view.
    """

    STATUS_TRANSITIONS = {
        "accept": (
            [PickupTask.TaskStatus.ASSIGNED],
            PickupTask.TaskStatus.ACCEPTED,
            PickupTaskEvent.EventType.ACCEPTED,
        ),
        "en_route_pickup": (
            [PickupTask.TaskStatus.ACCEPTED],
            PickupTask.TaskStatus.EN_ROUTE_PICKUP,
            PickupTaskEvent.EventType.EN_ROUTE_PICKUP,
        ),
        "arrived_at_pickup": (
            [PickupTask.TaskStatus.EN_ROUTE_PICKUP],
            PickupTask.TaskStatus.ARRIVED_AT_PICKUP,
            PickupTaskEvent.EventType.ARRIVED_AT_PICKUP,
        ),
        "picked_up": (
            [PickupTask.TaskStatus.ARRIVED_AT_PICKUP],
            PickupTask.TaskStatus.PICKED_UP,
            PickupTaskEvent.EventType.PICKED_UP,
        ),
        "en_route_warehouse": (
            [PickupTask.TaskStatus.PICKED_UP],
            PickupTask.TaskStatus.EN_ROUTE_WAREHOUSE,
            PickupTaskEvent.EventType.EN_ROUTE_WAREHOUSE,
        ),
        "arrived_at_warehouse": (
            [PickupTask.TaskStatus.EN_ROUTE_WAREHOUSE],
            PickupTask.TaskStatus.ARRIVED_AT_WAREHOUSE,
            PickupTaskEvent.EventType.ARRIVED_AT_WAREHOUSE,
        ),
        "complete": (
            [PickupTask.TaskStatus.ARRIVED_AT_WAREHOUSE],
            PickupTask.TaskStatus.COMPLETED,
            PickupTaskEvent.EventType.COMPLETED,
        ),
    }

    def post(self, request, pk, action):
        task = get_object_or_404(PickupTask, pk=pk)

        if action == "fail":
            reason = request.POST.get("reason", "No reason provided")
            task.fail(actor=request.user, reason=reason)
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse({"success": True, "status": task.status})
            messages.warning(request, f"Task {task.task_number} marked as failed.")
            return redirect("logistics:dispatch_pickup_task_detail", pk=task.pk)

        if action not in self.STATUS_TRANSITIONS:
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse({"error": "Unknown action"}, status=400)
            messages.error(request, "Unknown action.")
            return redirect("logistics:dispatch_pickup_task_detail", pk=task.pk)

        valid_statuses, new_status, event_type = self.STATUS_TRANSITIONS[action]
        if task.status not in valid_statuses:
            msg = f"Cannot perform '{action}' when status is '{task.status}'."
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse({"error": msg}, status=400)
            messages.error(request, msg)
            return redirect("logistics:dispatch_pickup_task_detail", pk=task.pk)

        task.status = new_status
        task.save(update_fields=["status", "updated_at"])
        PickupTaskEvent.objects.create(
            task=task,
            event_type=event_type,
            actor=request.user,
        )

        if action == "complete":
            task.complete(actor=request.user)

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"success": True, "status": task.status, "status_display": task.get_status_display()})

        messages.success(request, f"Task {task.task_number} updated to '{task.get_status_display()}'.")
        return redirect("logistics:dispatch_pickup_task_detail", pk=task.pk)


# ===========================================================================
# LAST MILE DELIVERY TASK VIEWS
# ===========================================================================

class LastMileTaskListView(LogisticsRequiredMixin, View):
    template_name = "logistics/dispatch/last_mile_list.html"

    def get(self, request):
        qs = LastMileTask.objects.select_related(
            "assigned_driver__user",
            "assigned_drone",
            "shipment",
            "origin_warehouse",
        )

        status = request.GET.get("status", "")
        method = request.GET.get("method", "")
        search = request.GET.get("q", "").strip()

        if status:
            qs = qs.filter(status=status)
        if method:
            qs = qs.filter(delivery_method=method)
        if search:
            qs = qs.filter(
                Q(task_number__icontains=search)
                | Q(recipient_name__icontains=search)
                | Q(delivery_address__icontains=search)
                | Q(shipment__tracking_number__icontains=search)
            )

        paginator = Paginator(qs.order_by("-priority", "-created_at"), 30)
        page = paginator.get_page(request.GET.get("page"))

        context = {
            "page_title": "Last Mile Delivery Tasks",
            "tasks": page,
            "status_choices": LastMileTask.TaskStatus.choices,
            "method_choices": LastMileTask.DeliveryMethod.choices,
            "selected_status": status,
            "selected_method": method,
            "search": search,
        }
        return render(request, self.template_name, context)


class LastMileTaskDetailView(LogisticsRequiredMixin, View):
    template_name = "logistics/dispatch/last_mile_detail.html"

    def get(self, request, pk):
        task = get_object_or_404(
            LastMileTask.objects.select_related(
                "assigned_driver__user",
                "assigned_drone",
                "shipment",
                "origin_warehouse",
                "assigned_by",
            ),
            pk=pk,
        )
        events = task.events.select_related("actor").order_by("created_at")
        available_drivers = DriverQueryService.get_available_drivers()
        available_drones = DriverQueryService.get_available_drones()

        context = {
            "page_title": f"Delivery Task — {task.task_number}",
            "task": task,
            "events": events,
            "available_drivers": available_drivers,
            "available_drones": available_drones,
            "can_assign": task.status in [
                LastMileTask.TaskStatus.PENDING,
                LastMileTask.TaskStatus.RESCHEDULED,
            ],
        }
        return render(request, self.template_name, context)


class AssignLastMileTaskView(LogisticsRequiredMixin, View):

    def post(self, request, pk):
        task = get_object_or_404(LastMileTask, pk=pk)
        data = request.POST
        assignment_type = data.get("assignment_type")

        try:
            if assignment_type == "driver":
                driver = get_object_or_404(DriverProfile, pk=data.get("driver_id"))
                vehicle_id = data.get("vehicle_id")
                vehicle = None
                if vehicle_id:
                    from logistics.models import Vehicle
                    vehicle = Vehicle.objects.filter(pk=vehicle_id, is_active=True).first()
                scheduled_time = data.get("scheduled_delivery_time") or None

                DispatchService.assign_last_mile_to_driver(
                    task=task,
                    driver=driver,
                    assigned_by=request.user,
                    vehicle=vehicle,
                    scheduled_time=scheduled_time,
                    notes=data.get("notes", ""),
                )
                messages.success(
                    request,
                    f"Delivery task {task.task_number} assigned to {driver.user.get_full_name()}.",
                )

            elif assignment_type == "drone":
                drone = get_object_or_404(DroneUnit, pk=data.get("drone_id"))
                DispatchService.assign_last_mile_to_drone(
                    task=task,
                    drone=drone,
                    assigned_by=request.user,
                    notes=data.get("notes", ""),
                )
                messages.success(
                    request,
                    f"Delivery task {task.task_number} assigned to drone {drone.drone_id}.",
                )
            else:
                messages.error(request, "Please select a driver or drone.")

        except ValidationError as e:
            messages.error(request, str(e))

        return redirect("logistics:dispatch_last_mile_detail", pk=task.pk)


class CreateLastMileTaskView(LogisticsRequiredMixin, View):
    template_name = "logistics/dispatch/last_mile_create.html"

    def get(self, request):
        from logistics.models import Warehouse, Shipment
        # Only shipments at warehouse that don't have a last-mile task yet
        eligible_shipments = Shipment.objects.filter(
            status__in=["in_transit", "shipped"],
        ).exclude(last_mile_task__isnull=False)

        context = {
            "page_title": "Create Last Mile Delivery Task",
            "shipments": eligible_shipments.order_by("-created_at")[:100],
            "warehouses": Warehouse.objects.filter(is_active=True),
            "priority_choices": LastMileTask.Priority.choices,
        }
        return render(request, self.template_name, context)

    def post(self, request):
        from logistics.models import Warehouse, Shipment
        data = request.POST
        shipment_id = data.get("shipment_id")
        warehouse_id = data.get("warehouse_id")

        try:
            shipment = Shipment.objects.get(pk=shipment_id)
            warehouse = Warehouse.objects.get(pk=warehouse_id)
        except Exception as e:
            messages.error(request, f"Invalid shipment or warehouse: {e}")
            return redirect(request.path)

        try:
            task = DispatchService.create_last_mile_task(
                shipment=shipment,
                origin_warehouse=warehouse,
                recipient_name=data.get("recipient_name", ""),
                recipient_phone=data.get("recipient_phone", ""),
                delivery_address=data.get("delivery_address", ""),
                scheduled_delivery_time=data.get("scheduled_delivery_time") or None,
                priority=int(data.get("priority", LastMileTask.Priority.NORMAL)),
                special_instructions=data.get("special_instructions", ""),
                created_by=request.user,
            )
            messages.success(request, f"Last mile task {task.task_number} created.")
            return redirect("logistics:dispatch_last_mile_detail", pk=task.pk)
        except ValidationError as e:
            messages.error(request, str(e))
            return redirect(request.path)


# ===========================================================================
# DRONE MANAGEMENT
# ===========================================================================

class DroneListView(LogisticsRequiredMixin, View):
    template_name = "logistics/dispatch/drone_list.html"

    def get(self, request):
        drones = DroneUnit.objects.select_related("home_base", "assigned_operator__user").order_by(
            "status", "drone_id"
        )
        context = {
            "page_title": "Easy Move Drone Fleet",
            "drones": drones,
            "status_choices": DroneUnit.DroneStatus.choices,
        }
        return render(request, self.template_name, context)


# ===========================================================================
# DISPATCH BATCH
# ===========================================================================

class DispatchBatchCreateView(LogisticsRequiredMixin, View):
    template_name = "logistics/dispatch/batch_create.html"

    def get(self, request):
        context = {
            "page_title": "Create Dispatch Batch",
            "available_drivers": DriverQueryService.get_available_drivers(),
            "available_drones": DriverQueryService.get_available_drones(),
            "pending_pickup_tasks": PickupTask.objects.filter(
                status=PickupTask.TaskStatus.PENDING
            ).order_by("-priority", "-created_at"),
            "pending_delivery_tasks": LastMileTask.objects.filter(
                status=LastMileTask.TaskStatus.PENDING
            ).order_by("-priority", "-created_at"),
            "batch_type_choices": DispatchBatch.BatchType.choices,
        }
        return render(request, self.template_name, context)

    def post(self, request):
        data = request.POST
        driver_id = data.get("driver_id")
        drone_id = data.get("drone_id")
        pickup_task_ids = request.POST.getlist("pickup_tasks")
        last_mile_task_ids = request.POST.getlist("last_mile_tasks")

        driver = DriverProfile.objects.filter(pk=driver_id).first() if driver_id else None
        drone = DroneUnit.objects.filter(pk=drone_id).first() if drone_id else None

        try:
            batch = DispatchService.create_dispatch_batch(
                batch_type=data.get("batch_type", DispatchBatch.BatchType.MIXED),
                assigned_by=request.user,
                driver=driver,
                drone=drone,
                pickup_task_ids=pickup_task_ids,
                last_mile_task_ids=last_mile_task_ids,
                planned_start_time=data.get("planned_start_time") or None,
                notes=data.get("notes", ""),
            )
            messages.success(request, f"Dispatch batch {batch.batch_number} created with {batch.total_tasks} tasks.")
            return redirect("logistics:dispatch_dashboard")
        except ValidationError as e:
            messages.error(request, str(e))
            return redirect(request.path)


# ===========================================================================
# AJAX / JSON API ENDPOINTS
# ===========================================================================

@login_required
@user_passes_test(is_logistics_staff)
def available_drivers_api(request):
    """JSON: list available drivers for assignment modals."""
    driver_type = request.GET.get("type", "")
    qs = DriverQueryService.get_available_drivers(driver_type=driver_type or None)
    data = []
    for d in qs:
        tasks = DriverQueryService.get_driver_current_tasks(d)
        data.append({
            "id": str(d.pk),
            "name": d.user.get_full_name(),
            "employee_id": d.employee_id or "",
            "type": d.driver_type,
            "type_label": d.get_driver_type_display(),
            "phone": d.phone,
            "photo": d.photo.url if d.photo else None,
            "active_tasks": tasks["total_active"],
            "rating": float(d.average_rating),
        })
    return JsonResponse({"success": True, "drivers": data})


@login_required
@user_passes_test(is_logistics_staff)
def available_drones_api(request):
    """JSON: list available drones for assignment modals."""
    qs = DriverQueryService.get_available_drones()
    data = []
    for drone in qs:
        data.append({
            "id": str(drone.pk),
            "drone_id": drone.drone_id,
            "model": drone.model_name,
            "max_payload_kg": float(drone.max_payload_kg),
            "max_range_km": float(drone.max_range_km) if drone.max_range_km else None,
            "battery_level": drone.battery_level,
            "photo": drone.photo.url if drone.photo else None,
            "home_base": drone.home_base.name if drone.home_base else None,
        })
    return JsonResponse({"success": True, "drones": data})


@login_required
@user_passes_test(is_logistics_staff)
def driver_tasks_api(request, pk):
    """JSON: current active tasks for a specific driver."""
    driver = get_object_or_404(DriverProfile, pk=pk)
    tasks_summary = DriverQueryService.get_driver_current_tasks(driver)

    pickup_tasks = list(
        PickupTask.objects.filter(
            assigned_driver=driver,
            status__in=["assigned", "accepted", "en_route_pickup", "arrived_at_pickup", "picked_up", "en_route_warehouse"],
        ).values("task_number", "status", "pickup_address", "priority", "order_type")
    )
    last_mile_tasks = list(
        LastMileTask.objects.filter(
            assigned_driver=driver,
            status__in=["assigned", "accepted", "out_for_delivery", "arrived"],
        ).values("task_number", "status", "delivery_address", "priority", "recipient_name")
    )

    return JsonResponse({
        "success": True,
        "driver": {
            "name": driver.user.get_full_name(),
            "availability": driver.availability,
            "type": driver.driver_type,
        },
        "summary": tasks_summary,
        "pickup_tasks": pickup_tasks,
        "last_mile_tasks": last_mile_tasks,
    })


@login_required
@user_passes_test(is_logistics_staff)
def dispatch_stats_api(request):
    """JSON: live dashboard stats for polling / websocket fallback."""
    stats = DispatchService.get_dispatch_dashboard_stats()
    return JsonResponse({"success": True, "stats": stats, "timestamp": timezone.now().isoformat()})


# ===========================================================================
# HELPERS
# ===========================================================================

def _load_order_and_warehouse(order_type: str, order_id, warehouse_id):
    """Load the correct order model and warehouse."""
    from logistics.models import Warehouse

    warehouse = Warehouse.objects.get(pk=warehouse_id, is_active=True)

    if order_type == PickupTask.OrderType.REGULAR:
        from orders.models import Order
        order = Order.objects.get(pk=order_id)
    elif order_type == PickupTask.OrderType.B2B:
        from stores.b2b.models import B2BOrder
        order = B2BOrder.objects.get(pk=order_id)
    elif order_type == PickupTask.OrderType.CROSSROAD:
        from crossroad_deals.models import CrossroadOrder
        order = CrossroadOrder.objects.get(pk=order_id)
    else:
        raise ValueError(f"Unknown order_type: {order_type}")

    return order, warehouse
