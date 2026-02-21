"""
Easy Market Logistics — Dispatch & Assignment Models
=====================================================
Extends the core logistics models to support:
  • Driver registration with photo & vetting workflow
  • Easy Move driver vs. external vetted driver distinction
  • Drone unit management (Easy Move fleet)
  • Unified PickupTask across Regular / B2B / Crossroad (Black Market) orders
  • Last-mile delivery assignment with driver or drone

Author: Logistics Team
Version: 3.0.0
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Optional

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

User = settings.AUTH_USER_MODEL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def driver_photo_upload_path(instance, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower()
    return f"drivers/photos/{instance.pk or 'new'}.{ext}"


def driver_document_upload_path(instance, filename: str) -> str:
    return f"drivers/documents/{instance.driver.pk}/{filename}"


def drone_photo_upload_path(instance, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower()
    return f"drones/photos/{instance.pk or 'new'}.{ext}"


# ---------------------------------------------------------------------------
# Abstract helpers
# ---------------------------------------------------------------------------

class TimestampModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]


# ===========================================================================
# DRIVER PROFILE  (extends / complements the existing Driver model)
# ===========================================================================

class DriverProfile(TimestampModel):
    """
    Full driver registration record.

    A DriverProfile can exist for:
      - Easy Move drivers  (employed by Easy Market)
      - External / partner drivers  (vetted & registered on the platform)
      - Drone operators  (fly Easy Move drones, but are still human accounts)

    Vetting lifecycle:
      pending → under_review → approved | rejected | suspended
    """

    # -- Driver type ---------------------------------------------------------
    class DriverType(models.TextChoices):
        EASY_MOVE = "easy_move", _("Easy Move (Easy Market Staff)")
        EXTERNAL = "external", _("External / Partner Driver")
        DRONE_OPERATOR = "drone_operator", _("Drone Operator")

    # -- Vetting status ------------------------------------------------------
    class VettingStatus(models.TextChoices):
        PENDING = "pending", _("Pending Submission")
        UNDER_REVIEW = "under_review", _("Under Review")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")
        SUSPENDED = "suspended", _("Suspended")

    # -- Availability --------------------------------------------------------
    class Availability(models.TextChoices):
        AVAILABLE = "available", _("Available")
        ON_TRIP = "on_trip", _("On Trip")
        OFFLINE = "offline", _("Offline")
        ON_LEAVE = "on_leave", _("On Leave")

    # -- Fields --------------------------------------------------------------
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="dispatch_driver_profile",
        verbose_name=_("User Account"),
    )

    driver_type = models.CharField(
        max_length=20,
        choices=DriverType.choices,
        default=DriverType.EASY_MOVE,
        db_index=True,
        verbose_name=_("Driver Type"),
    )

    # -- Personal info -------------------------------------------------------
    photo = models.ImageField(
        upload_to=driver_photo_upload_path,
        null=True,
        blank=True,
        verbose_name=_("Driver Photo"),
        help_text=_("Clear headshot photo for ID badge and app display"),
    )
    phone = models.CharField(
        max_length=20,
        validators=[RegexValidator(r"^\+?\d{7,15}$", _("Enter a valid phone number."))],
        verbose_name=_("Mobile Phone"),
    )
    national_id_number = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("National ID / Passport Number"),
    )
    date_of_birth = models.DateField(null=True, blank=True, verbose_name=_("Date of Birth"))

    # -- License -------------------------------------------------------------
    license_number = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("Driver's License Number"),
    )
    license_category = models.CharField(
        max_length=20,
        blank=True,
        verbose_name=_("License Category"),
        help_text=_("e.g. B, C1, C, D — or 'drone' for drone operators"),
    )
    license_expiry = models.DateField(
        null=True, blank=True, verbose_name=_("License Expiry Date")
    )
    license_document = models.FileField(
        upload_to=driver_document_upload_path,
        null=True,
        blank=True,
        verbose_name=_("License Document"),
    )

    # -- Vetting -------------------------------------------------------------
    vetting_status = models.CharField(
        max_length=20,
        choices=VettingStatus.choices,
        default=VettingStatus.PENDING,
        db_index=True,
        verbose_name=_("Vetting Status"),
    )
    vetting_date = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Vetting Approval / Rejection Date")
    )
    vetted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vetted_drivers",
        verbose_name=_("Vetted By"),
    )
    vetting_notes = models.TextField(
        blank=True, verbose_name=_("Vetting Notes / Remarks")
    )

    # -- Availability --------------------------------------------------------
    availability = models.CharField(
        max_length=20,
        choices=Availability.choices,
        default=Availability.OFFLINE,
        db_index=True,
        verbose_name=_("Current Availability"),
    )
    last_seen = models.DateTimeField(null=True, blank=True, verbose_name=_("Last Seen Online"))

    # -- Employment details (Easy Move only) --------------------------------
    employee_id = models.CharField(
        max_length=30, blank=True, unique=True, null=True,
        verbose_name=_("Employee ID"),
        help_text=_("Auto-assigned for Easy Move staff"),
    )
    date_hired = models.DateField(null=True, blank=True, verbose_name=_("Date Hired"))
    assigned_office = models.ForeignKey(
        "logistics.LogisticOffice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_drivers",
        verbose_name=_("Assigned Office"),
    )

    # -- Emergency contact ---------------------------------------------------
    emergency_contact_name = models.CharField(
        max_length=100, blank=True, verbose_name=_("Emergency Contact Name")
    )
    emergency_contact_phone = models.CharField(
        max_length=20,
        blank=True,
        validators=[RegexValidator(r"^\+?\d{7,15}$", "")],
        verbose_name=_("Emergency Contact Phone"),
    )

    # -- Rating & stats (denormalised for speed) -----------------------------
    total_deliveries = models.PositiveIntegerField(default=0)
    total_pickups = models.PositiveIntegerField(default=0)
    successful_deliveries = models.PositiveIntegerField(default=0)
    average_rating = models.DecimalField(
        max_digits=3, decimal_places=2, default=Decimal("0.00")
    )

    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True, verbose_name=_("Internal Notes"))

    # -- Meta ----------------------------------------------------------------
    class Meta:
        verbose_name = _("Driver Profile")
        verbose_name_plural = _("Driver Profiles")
        ordering = ["user__first_name", "user__last_name"]
        indexes = [
            models.Index(fields=["driver_type", "vetting_status"]),
            models.Index(fields=["availability", "is_active"]),
            models.Index(fields=["vetting_status", "is_active"]),
        ]

    def __str__(self) -> str:
        name = self.user.get_full_name() or self.user.username
        return f"{name} [{self.get_driver_type_display()}]"

    # -- Business logic methods ---------------------------------------------

    def is_eligible_for_dispatch(self) -> bool:
        """Driver must be approved, active, and available."""
        return (
            self.is_active
            and self.vetting_status == self.VettingStatus.APPROVED
            and self.availability == self.Availability.AVAILABLE
        )

    def approve(self, approved_by: User, notes: str = "") -> None:
        """Approve the driver after vetting."""
        self.vetting_status = self.VettingStatus.APPROVED
        self.vetting_date = timezone.now()
        self.vetted_by = approved_by
        if notes:
            self.vetting_notes = notes
        if self.driver_type == self.DriverType.EASY_MOVE and not self.employee_id:
            self.employee_id = self._generate_employee_id()
        self.save(
            update_fields=[
                "vetting_status", "vetting_date", "vetted_by",
                "vetting_notes", "employee_id", "updated_at",
            ]
        )

    def reject(self, rejected_by: User, reason: str) -> None:
        """Reject the driver's application."""
        self.vetting_status = self.VettingStatus.REJECTED
        self.vetting_date = timezone.now()
        self.vetted_by = rejected_by
        self.vetting_notes = reason
        self.save(
            update_fields=[
                "vetting_status", "vetting_date", "vetted_by",
                "vetting_notes", "updated_at",
            ]
        )

    def suspend(self, suspended_by: User, reason: str) -> None:
        """Suspend an approved driver."""
        self.vetting_status = self.VettingStatus.SUSPENDED
        self.vetting_date = timezone.now()
        self.vetted_by = suspended_by
        self.vetting_notes = reason
        self.availability = self.Availability.OFFLINE
        self.save(
            update_fields=[
                "vetting_status", "vetting_date", "vetted_by",
                "vetting_notes", "availability", "updated_at",
            ]
        )

    def set_available(self) -> None:
        self.availability = self.Availability.AVAILABLE
        self.last_seen = timezone.now()
        self.save(update_fields=["availability", "last_seen", "updated_at"])

    def set_on_trip(self) -> None:
        self.availability = self.Availability.ON_TRIP
        self.save(update_fields=["availability", "updated_at"])

    @property
    def success_rate(self) -> Optional[float]:
        if not self.total_deliveries:
            return None
        return round((self.successful_deliveries / self.total_deliveries) * 100, 1)

    @property
    def is_license_valid(self) -> bool:
        if not self.license_expiry:
            return False
        return self.license_expiry >= timezone.now().date()

    def _generate_employee_id(self) -> str:
        from django.db.models import Max
        last = DriverProfile.objects.filter(
            driver_type=self.DriverType.EASY_MOVE,
            employee_id__startswith="EM-"
        ).aggregate(Max("employee_id"))["employee_id__max"]
        if last:
            try:
                num = int(last.replace("EM-", "")) + 1
            except ValueError:
                num = 1001
        else:
            num = 1001
        return f"EM-{num:05d}"


# ===========================================================================
# DRIVER DOCUMENT
# ===========================================================================

class DriverDocument(TimestampModel):
    """Additional compliance documents for a driver (insurance, certifications, etc.)."""

    class DocType(models.TextChoices):
        LICENSE = "license", _("Driver's License")
        NATIONAL_ID = "national_id", _("National ID / Passport")
        INSURANCE = "insurance", _("Insurance Certificate")
        VEHICLE_INSPECTION = "vehicle_inspection", _("Vehicle Inspection Report")
        DRONE_CERT = "drone_cert", _("Drone Pilot Certificate")
        BACKGROUND_CHECK = "background_check", _("Background Check Clearance")
        OTHER = "other", _("Other")

    driver = models.ForeignKey(
        DriverProfile,
        on_delete=models.CASCADE,
        related_name="documents",
        verbose_name=_("Driver"),
    )
    doc_type = models.CharField(
        max_length=30, choices=DocType.choices, verbose_name=_("Document Type")
    )
    file = models.FileField(upload_to=driver_document_upload_path, verbose_name=_("File"))
    expiry_date = models.DateField(null=True, blank=True, verbose_name=_("Expiry Date"))
    notes = models.CharField(max_length=255, blank=True)
    is_verified = models.BooleanField(default=False, verbose_name=_("Verified"))
    verified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_documents",
    )

    class Meta:
        verbose_name = _("Driver Document")
        verbose_name_plural = _("Driver Documents")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.driver} — {self.get_doc_type_display()}"

    @property
    def is_expired(self) -> bool:
        if not self.expiry_date:
            return False
        return self.expiry_date < timezone.now().date()


# ===========================================================================
# DRONE UNIT  (Easy Move)
# ===========================================================================

class DroneUnit(TimestampModel):
    """
    An Easy Move delivery drone.
    Each drone is owned by Easy Market and can be assigned delivery tasks.
    """

    class DroneStatus(models.TextChoices):
        AVAILABLE = "available", _("Available")
        ON_MISSION = "on_mission", _("On Mission")
        CHARGING = "charging", _("Charging")
        MAINTENANCE = "maintenance", _("Under Maintenance")
        GROUNDED = "grounded", _("Grounded")
        RETIRED = "retired", _("Retired")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    drone_id = models.CharField(
        max_length=30,
        unique=True,
        verbose_name=_("Drone ID"),
        help_text=_("e.g. EM-DRONE-001"),
    )
    model_name = models.CharField(max_length=100, verbose_name=_("Model / Manufacturer"))
    serial_number = models.CharField(max_length=100, blank=True, unique=True, null=True)
    photo = models.ImageField(
        upload_to=drone_photo_upload_path, null=True, blank=True, verbose_name=_("Photo")
    )

    # -- Capabilities --------------------------------------------------------
    max_payload_kg = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        verbose_name=_("Max Payload (kg)"),
    )
    max_range_km = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        verbose_name=_("Max Range (km)"),
    )
    max_flight_time_minutes = models.PositiveIntegerField(
        null=True, blank=True, verbose_name=_("Max Flight Time (mins)")
    )
    battery_level = models.PositiveSmallIntegerField(
        default=100,
        verbose_name=_("Battery Level (%)"),
        help_text=_("Current battery percentage 0–100"),
    )

    # -- Status & assignment -------------------------------------------------
    status = models.CharField(
        max_length=20,
        choices=DroneStatus.choices,
        default=DroneStatus.AVAILABLE,
        db_index=True,
    )
    assigned_operator = models.ForeignKey(
        DriverProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"driver_type": DriverProfile.DriverType.DRONE_OPERATOR},
        related_name="operated_drones",
        verbose_name=_("Assigned Operator"),
    )
    home_base = models.ForeignKey(
        "logistics.Warehouse",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="drones",
        verbose_name=_("Home Base Warehouse"),
    )

    # -- Location ------------------------------------------------------------
    current_latitude = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True
    )
    current_longitude = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True
    )
    last_location_update = models.DateTimeField(null=True, blank=True)

    # -- Maintenance ---------------------------------------------------------
    total_missions = models.PositiveIntegerField(default=0)
    total_flight_hours = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("0.00")
    )
    last_maintenance_date = models.DateField(null=True, blank=True)
    next_maintenance_date = models.DateField(null=True, blank=True)

    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("Drone Unit")
        verbose_name_plural = _("Drone Units")
        ordering = ["drone_id"]
        indexes = [
            models.Index(fields=["status", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.drone_id} ({self.model_name})"

    def is_available_for_dispatch(self) -> bool:
        return (
            self.is_active
            and self.status == self.DroneStatus.AVAILABLE
            and self.battery_level >= 30
        )

    def needs_maintenance(self) -> bool:
        if not self.next_maintenance_date:
            return False
        return self.next_maintenance_date <= timezone.now().date()


# ===========================================================================
# PICKUP TASK
# ===========================================================================

class PickupTask(TimestampModel):
    """
    A unified pickup assignment covering all order types:
      - Regular marketplace orders
      - B2B orders
      - Crossroad / Black Market orders (Easy Move vetting orders)

    The task represents: driver/drone goes to seller/vendor location,
    picks up the package(s), and delivers them to the Easy Market Warehouse.
    """

    class OrderType(models.TextChoices):
        REGULAR = "regular", _("Regular Marketplace Order")
        B2B = "b2b", _("B2B Order")
        CROSSROAD = "crossroad", _("Black Market / Crossroad Order")

    class PickupMethod(models.TextChoices):
        EASY_MOVE_DRIVER = "easy_move_driver", _("Easy Move Driver")
        EXTERNAL_DRIVER = "external_driver", _("External / Partner Driver")
        DRONE = "drone", _("Easy Move Drone")

    class TaskStatus(models.TextChoices):
        PENDING = "pending", _("Pending Assignment")
        ASSIGNED = "assigned", _("Assigned — Awaiting Acceptance")
        ACCEPTED = "accepted", _("Accepted by Driver")
        EN_ROUTE_PICKUP = "en_route_pickup", _("En Route to Pickup Location")
        ARRIVED_AT_PICKUP = "arrived_at_pickup", _("Arrived at Pickup Location")
        PICKED_UP = "picked_up", _("Package Picked Up")
        EN_ROUTE_WAREHOUSE = "en_route_warehouse", _("En Route to Warehouse")
        ARRIVED_AT_WAREHOUSE = "arrived_at_warehouse", _("Arrived at Warehouse")
        COMPLETED = "completed", _("Completed — Handed Over to Warehouse")
        FAILED = "failed", _("Failed / Cancelled")
        REASSIGNED = "reassigned", _("Reassigned to Another Driver")

    class Priority(models.IntegerChoices):
        LOW = 1, _("Low")
        NORMAL = 2, _("Normal")
        HIGH = 3, _("High")
        URGENT = 4, _("Urgent")
        CRITICAL = 5, _("Critical")

    # -- Identifiers ---------------------------------------------------------
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task_number = models.CharField(
        max_length=30,
        unique=True,
        blank=True,
        verbose_name=_("Task Number"),
        help_text=_("Auto-generated: PT-YYYYMMDD-XXXX"),
    )

    # -- Order reference (one of these three will be set) --------------------
    order_type = models.CharField(
        max_length=20,
        choices=OrderType.choices,
        db_index=True,
        verbose_name=_("Order Type"),
    )
    # Regular order
    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="pickup_tasks",
        verbose_name=_("Regular Order"),
    )
    # B2B order
    b2b_order = models.ForeignKey(
        "stores.B2BOrder",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="pickup_tasks",
        verbose_name=_("B2B Order"),
    )
    # Crossroad / Black Market order
    crossroad_order = models.ForeignKey(
        "crossroad_deals.CrossroadOrder",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="pickup_tasks",
        verbose_name=_("Crossroad Order"),
    )

    # -- Destination ---------------------------------------------------------
    destination_warehouse = models.ForeignKey(
        "logistics.Warehouse",
        on_delete=models.PROTECT,
        related_name="incoming_pickup_tasks",
        verbose_name=_("Destination Warehouse"),
        help_text=_("Easy Market warehouse where package must be delivered"),
    )

    # -- Assignment ----------------------------------------------------------
    pickup_method = models.CharField(
        max_length=25,
        choices=PickupMethod.choices,
        default=PickupMethod.EASY_MOVE_DRIVER,
        db_index=True,
        verbose_name=_("Pickup Method"),
    )
    assigned_driver = models.ForeignKey(
        DriverProfile,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        limit_choices_to={"driver_type__in": [
            DriverProfile.DriverType.EASY_MOVE,
            DriverProfile.DriverType.EXTERNAL,
        ]},
        related_name="pickup_tasks",
        verbose_name=_("Assigned Driver"),
    )
    assigned_drone = models.ForeignKey(
        DroneUnit,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="pickup_tasks",
        verbose_name=_("Assigned Drone"),
    )
    assigned_vehicle = models.ForeignKey(
        "logistics.Vehicle",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="pickup_tasks",
        verbose_name=_("Assigned Vehicle"),
    )
    assigned_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="dispatch_pickup_assignments",
        verbose_name=_("Assigned By"),
    )
    assigned_at = models.DateTimeField(null=True, blank=True)

    # -- Status --------------------------------------------------------------
    status = models.CharField(
        max_length=30,
        choices=TaskStatus.choices,
        default=TaskStatus.PENDING,
        db_index=True,
    )

    # -- Pickup location -----------------------------------------------------
    pickup_address = models.TextField(verbose_name=_("Pickup Address"))
    pickup_latitude = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True
    )
    pickup_longitude = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True
    )
    pickup_contact_name = models.CharField(max_length=150, blank=True)
    pickup_contact_phone = models.CharField(max_length=20, blank=True)

    # -- Scheduling ----------------------------------------------------------
    priority = models.IntegerField(
        choices=Priority.choices,
        default=Priority.NORMAL,
        db_index=True,
    )
    scheduled_pickup_time = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Scheduled Pickup Time")
    )
    actual_pickup_time = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Actual Pickup Time")
    )
    actual_warehouse_arrival_time = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Actual Warehouse Arrival")
    )

    # -- Package details -----------------------------------------------------
    packages_count = models.PositiveIntegerField(default=1)
    estimated_weight_kg = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    requires_vetting = models.BooleanField(
        default=False,
        verbose_name=_("Requires Vetting"),
        help_text=_("Set for Crossroad / Easy Move vetting orders"),
    )
    vetting_completed = models.BooleanField(default=False)

    # -- Proof & notes -------------------------------------------------------
    pickup_photo = models.ImageField(
        upload_to="pickup_tasks/photos/%Y/%m/",
        null=True, blank=True,
        verbose_name=_("Pickup Confirmation Photo"),
    )
    delivery_photo = models.ImageField(
        upload_to="pickup_tasks/delivery/%Y/%m/",
        null=True, blank=True,
        verbose_name=_("Warehouse Delivery Photo"),
    )
    warehouse_receiver_signature = models.ImageField(
        upload_to="pickup_tasks/signatures/%Y/%m/",
        null=True, blank=True,
    )
    warehouse_receiver = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="received_pickup_tasks",
        verbose_name=_("Warehouse Receiver"),
    )
    failure_reason = models.TextField(blank=True)
    special_instructions = models.TextField(blank=True)
    internal_notes = models.TextField(blank=True)

    class Meta:
        verbose_name = _("Pickup Task")
        verbose_name_plural = _("Pickup Tasks")
        ordering = ["-priority", "-created_at"]
        indexes = [
            models.Index(fields=["status", "priority", "-created_at"]),
            models.Index(fields=["order_type", "status"]),
            models.Index(fields=["assigned_driver", "status"]),
            models.Index(fields=["assigned_drone", "status"]),
            models.Index(fields=["destination_warehouse", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.task_number} [{self.get_status_display()}]"

    def save(self, *args, **kwargs):
        if not self.task_number:
            self.task_number = self._generate_task_number()
        super().save(*args, **kwargs)

    def _generate_task_number(self) -> str:
        from django.db.models import Count
        date_str = timezone.now().strftime("%Y%m%d")
        count = PickupTask.objects.filter(
            task_number__startswith=f"PT-{date_str}-"
        ).count() + 1
        return f"PT-{date_str}-{count:04d}"

    # -- Convenience properties -----------------------------------------------

    @property
    def source_order(self):
        """Return whichever order is linked."""
        return self.order or self.b2b_order or self.crossroad_order

    @property
    def assignee_display(self) -> str:
        if self.assigned_drone:
            return f"🚁 {self.assigned_drone.drone_id}"
        if self.assigned_driver:
            return f"🚗 {self.assigned_driver.user.get_full_name()}"
        return "— Unassigned —"

    @property
    def is_overdue(self) -> bool:
        if self.status in [self.TaskStatus.COMPLETED, self.TaskStatus.FAILED]:
            return False
        if not self.scheduled_pickup_time:
            return False
        return timezone.now() > self.scheduled_pickup_time

    # -- State transitions ----------------------------------------------------

    def assign_driver(
        self,
        driver: DriverProfile,
        assigned_by: User,
        vehicle=None,
        scheduled_time=None,
        notes: str = "",
    ) -> None:
        """Assign a driver and transition to ASSIGNED."""
        if not driver.is_eligible_for_dispatch():
            raise ValidationError(
                _("Driver %(name)s is not eligible for dispatch (check vetting / availability)."),
                params={"name": str(driver)},
            )
        with transaction.atomic():
            self.assigned_driver = driver
            self.assigned_drone = None
            self.assigned_vehicle = vehicle
            self.pickup_method = (
                PickupTask.PickupMethod.EASY_MOVE_DRIVER
                if driver.driver_type == DriverProfile.DriverType.EASY_MOVE
                else PickupTask.PickupMethod.EXTERNAL_DRIVER
            )
            self.assigned_by = assigned_by
            self.assigned_at = timezone.now()
            self.status = PickupTask.TaskStatus.ASSIGNED
            if scheduled_time:
                self.scheduled_pickup_time = scheduled_time
            if notes:
                self.internal_notes = notes
            self.save()
            driver.set_on_trip()
            PickupTaskEvent.objects.create(
                task=self,
                event_type=PickupTaskEvent.EventType.ASSIGNED,
                actor=assigned_by,
                notes=f"Assigned to {driver}",
            )

    def assign_drone(
        self,
        drone: DroneUnit,
        assigned_by: User,
        scheduled_time=None,
        notes: str = "",
    ) -> None:
        """Assign a drone and transition to ASSIGNED."""
        if not drone.is_available_for_dispatch():
            raise ValidationError(_("Drone %(id)s is not available."), params={"id": drone.drone_id})
        with transaction.atomic():
            self.assigned_drone = drone
            self.assigned_driver = None
            self.pickup_method = PickupTask.PickupMethod.DRONE
            self.assigned_by = assigned_by
            self.assigned_at = timezone.now()
            self.status = PickupTask.TaskStatus.ASSIGNED
            if scheduled_time:
                self.scheduled_pickup_time = scheduled_time
            if notes:
                self.internal_notes = notes
            self.save()
            drone.status = DroneUnit.DroneStatus.ON_MISSION
            drone.save(update_fields=["status", "updated_at"])
            PickupTaskEvent.objects.create(
                task=self,
                event_type=PickupTaskEvent.EventType.ASSIGNED,
                actor=assigned_by,
                notes=f"Assigned to drone {drone.drone_id}",
            )

    def mark_picked_up(self, actor: User, photo=None) -> None:
        self.status = PickupTask.TaskStatus.PICKED_UP
        self.actual_pickup_time = timezone.now()
        if photo:
            self.pickup_photo = photo
        self.save(update_fields=["status", "actual_pickup_time", "pickup_photo", "updated_at"])
        PickupTaskEvent.objects.create(
            task=self, event_type=PickupTaskEvent.EventType.PICKED_UP, actor=actor
        )

    def mark_arrived_at_warehouse(
        self, actor: User, receiver: User = None, signature=None, photo=None
    ) -> None:
        self.status = PickupTask.TaskStatus.ARRIVED_AT_WAREHOUSE
        self.actual_warehouse_arrival_time = timezone.now()
        if receiver:
            self.warehouse_receiver = receiver
        if signature:
            self.warehouse_receiver_signature = signature
        if photo:
            self.delivery_photo = photo
        self.save()
        PickupTaskEvent.objects.create(
            task=self,
            event_type=PickupTaskEvent.EventType.ARRIVED_AT_WAREHOUSE,
            actor=actor,
        )

    def complete(self, actor: User) -> None:
        self.status = PickupTask.TaskStatus.COMPLETED
        self.save(update_fields=["status", "updated_at"])
        # Free the driver/drone
        if self.assigned_driver:
            self.assigned_driver.set_available()
            self.assigned_driver.total_pickups = models.F("total_pickups") + 1
            self.assigned_driver.save(update_fields=["total_pickups", "availability"])
        if self.assigned_drone:
            self.assigned_drone.status = DroneUnit.DroneStatus.AVAILABLE
            self.assigned_drone.total_missions = models.F("total_missions") + 1
            self.assigned_drone.save(update_fields=["status", "total_missions", "updated_at"])
        PickupTaskEvent.objects.create(
            task=self, event_type=PickupTaskEvent.EventType.COMPLETED, actor=actor
        )

    def fail(self, actor: User, reason: str) -> None:
        self.status = PickupTask.TaskStatus.FAILED
        self.failure_reason = reason
        self.save(update_fields=["status", "failure_reason", "updated_at"])
        if self.assigned_driver:
            self.assigned_driver.set_available()
        if self.assigned_drone:
            self.assigned_drone.status = DroneUnit.DroneStatus.AVAILABLE
            self.assigned_drone.save(update_fields=["status", "updated_at"])
        PickupTaskEvent.objects.create(
            task=self,
            event_type=PickupTaskEvent.EventType.FAILED,
            actor=actor,
            notes=reason,
        )


# ===========================================================================
# PICKUP TASK EVENT LOG
# ===========================================================================

class PickupTaskEvent(TimestampModel):
    """Audit trail for every state change on a PickupTask."""

    class EventType(models.TextChoices):
        CREATED = "created", _("Task Created")
        ASSIGNED = "assigned", _("Assigned to Driver / Drone")
        ACCEPTED = "accepted", _("Accepted by Driver")
        EN_ROUTE_PICKUP = "en_route_pickup", _("En Route to Pickup")
        ARRIVED_AT_PICKUP = "arrived_at_pickup", _("Arrived at Pickup")
        PICKED_UP = "picked_up", _("Package Picked Up")
        EN_ROUTE_WAREHOUSE = "en_route_warehouse", _("En Route to Warehouse")
        ARRIVED_AT_WAREHOUSE = "arrived_at_warehouse", _("Arrived at Warehouse")
        COMPLETED = "completed", _("Completed")
        FAILED = "failed", _("Failed")
        REASSIGNED = "reassigned", _("Reassigned")
        NOTE_ADDED = "note_added", _("Note Added")

    task = models.ForeignKey(
        PickupTask, on_delete=models.CASCADE, related_name="events"
    )
    event_type = models.CharField(max_length=30, choices=EventType.choices)
    actor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="pickup_task_events"
    )
    notes = models.TextField(blank=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)

    class Meta:
        verbose_name = _("Pickup Task Event")
        verbose_name_plural = _("Pickup Task Events")
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.task.task_number} — {self.get_event_type_display()}"


# ===========================================================================
# LAST MILE DELIVERY TASK
# ===========================================================================

class LastMileTask(TimestampModel):
    """
    A last-mile delivery assignment: package leaves the Easy Market warehouse
    and is delivered to the end customer.

    Can be assigned to:
      - Easy Move driver
      - External / vetted driver
      - Easy Move drone
    """

    class DeliveryMethod(models.TextChoices):
        EASY_MOVE_DRIVER = "easy_move_driver", _("Easy Move Driver")
        EXTERNAL_DRIVER = "external_driver", _("External / Partner Driver")
        DRONE = "drone", _("Easy Move Drone")

    class TaskStatus(models.TextChoices):
        PENDING = "pending", _("Pending Assignment")
        ASSIGNED = "assigned", _("Assigned")
        ACCEPTED = "accepted", _("Accepted by Driver")
        OUT_FOR_DELIVERY = "out_for_delivery", _("Out for Delivery")
        ARRIVED = "arrived", _("Arrived at Customer")
        DELIVERED = "delivered", _("Delivered")
        FAILED_ATTEMPT = "failed_attempt", _("Failed Delivery Attempt")
        RESCHEDULED = "rescheduled", _("Rescheduled")
        RETURNED_TO_WAREHOUSE = "returned_to_warehouse", _("Returned to Warehouse")

    class Priority(models.IntegerChoices):
        LOW = 1, _("Low")
        NORMAL = 2, _("Normal")
        HIGH = 3, _("High")
        URGENT = 4, _("Urgent")
        CRITICAL = 5, _("Critical")

    # -- Identifiers ---------------------------------------------------------
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task_number = models.CharField(max_length=30, unique=True, blank=True)

    # -- Source shipment -----------------------------------------------------
    shipment = models.OneToOneField(
        "logistics.Shipment",
        on_delete=models.CASCADE,
        related_name="last_mile_task",
        verbose_name=_("Shipment"),
    )
    origin_warehouse = models.ForeignKey(
        "logistics.Warehouse",
        on_delete=models.PROTECT,
        related_name="outgoing_last_mile_tasks",
        verbose_name=_("Origin Warehouse"),
    )

    # -- Assignment ----------------------------------------------------------
    delivery_method = models.CharField(
        max_length=25,
        choices=DeliveryMethod.choices,
        default=DeliveryMethod.EASY_MOVE_DRIVER,
        db_index=True,
    )
    assigned_driver = models.ForeignKey(
        DriverProfile,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="last_mile_tasks",
        verbose_name=_("Assigned Driver"),
    )
    assigned_drone = models.ForeignKey(
        DroneUnit,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="last_mile_tasks",
        verbose_name=_("Assigned Drone"),
    )
    assigned_vehicle = models.ForeignKey(
        "logistics.Vehicle",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="last_mile_tasks",
    )
    assigned_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="dispatch_last_mile_assignments",
    )
    assigned_at = models.DateTimeField(null=True, blank=True)

    # -- Status --------------------------------------------------------------
    status = models.CharField(
        max_length=30,
        choices=TaskStatus.choices,
        default=TaskStatus.PENDING,
        db_index=True,
    )
    attempt_count = models.PositiveSmallIntegerField(default=0)

    # -- Delivery details ----------------------------------------------------
    priority = models.IntegerField(
        choices=Priority.choices, default=Priority.NORMAL, db_index=True
    )
    scheduled_delivery_time = models.DateTimeField(null=True, blank=True)
    actual_delivery_time = models.DateTimeField(null=True, blank=True)

    # Recipient info (denormalised for driver app use)
    recipient_name = models.CharField(max_length=150, blank=True)
    recipient_phone = models.CharField(max_length=20, blank=True)
    delivery_address = models.TextField(blank=True)
    delivery_latitude = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True
    )
    delivery_longitude = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True
    )

    # -- Proof of delivery ---------------------------------------------------
    pod_photo = models.ImageField(
        upload_to="last_mile/pod/%Y/%m/",
        null=True, blank=True,
        verbose_name=_("Proof of Delivery Photo"),
    )
    pod_signature = models.ImageField(
        upload_to="last_mile/signatures/%Y/%m/",
        null=True, blank=True,
        verbose_name=_("Customer Signature"),
    )
    pod_collected_by = models.CharField(
        max_length=150, blank=True,
        verbose_name=_("Received By (if not customer)"),
    )

    failure_reason = models.TextField(blank=True)
    special_instructions = models.TextField(blank=True)
    internal_notes = models.TextField(blank=True)

    class Meta:
        verbose_name = _("Last Mile Delivery Task")
        verbose_name_plural = _("Last Mile Delivery Tasks")
        ordering = ["-priority", "-created_at"]
        indexes = [
            models.Index(fields=["status", "priority", "-created_at"]),
            models.Index(fields=["assigned_driver", "status"]),
            models.Index(fields=["assigned_drone", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.task_number} [{self.get_status_display()}]"

    def save(self, *args, **kwargs):
        if not self.task_number:
            self.task_number = self._generate_task_number()
        super().save(*args, **kwargs)

    def _generate_task_number(self) -> str:
        date_str = timezone.now().strftime("%Y%m%d")
        count = LastMileTask.objects.filter(
            task_number__startswith=f"LM-{date_str}-"
        ).count() + 1
        return f"LM-{date_str}-{count:04d}"

    @property
    def assignee_display(self) -> str:
        if self.assigned_drone:
            return f"🚁 {self.assigned_drone.drone_id}"
        if self.assigned_driver:
            return f"🚗 {self.assigned_driver.user.get_full_name()}"
        return "— Unassigned —"

    @property
    def is_overdue(self) -> bool:
        if self.status in [self.TaskStatus.DELIVERED, self.TaskStatus.RETURNED_TO_WAREHOUSE]:
            return False
        if not self.scheduled_delivery_time:
            return False
        return timezone.now() > self.scheduled_delivery_time

    def assign_driver(
        self,
        driver: DriverProfile,
        assigned_by: User,
        vehicle=None,
        scheduled_time=None,
        notes: str = "",
    ) -> None:
        if not driver.is_eligible_for_dispatch():
            raise ValidationError(
                _("Driver %(name)s is not eligible (check vetting / availability)."),
                params={"name": str(driver)},
            )
        with transaction.atomic():
            self.assigned_driver = driver
            self.assigned_drone = None
            self.assigned_vehicle = vehicle
            self.delivery_method = (
                LastMileTask.DeliveryMethod.EASY_MOVE_DRIVER
                if driver.driver_type == DriverProfile.DriverType.EASY_MOVE
                else LastMileTask.DeliveryMethod.EXTERNAL_DRIVER
            )
            self.assigned_by = assigned_by
            self.assigned_at = timezone.now()
            self.status = LastMileTask.TaskStatus.ASSIGNED
            if scheduled_time:
                self.scheduled_delivery_time = scheduled_time
            if notes:
                self.internal_notes = notes
            self.save()
            driver.set_on_trip()
            LastMileTaskEvent.objects.create(
                task=self,
                event_type=LastMileTaskEvent.EventType.ASSIGNED,
                actor=assigned_by,
                notes=f"Assigned to {driver}",
            )

    def assign_drone(
        self,
        drone: DroneUnit,
        assigned_by: User,
        scheduled_time=None,
        notes: str = "",
    ) -> None:
        if not drone.is_available_for_dispatch():
            raise ValidationError(_("Drone %(id)s not available."), params={"id": drone.drone_id})
        with transaction.atomic():
            self.assigned_drone = drone
            self.assigned_driver = None
            self.delivery_method = LastMileTask.DeliveryMethod.DRONE
            self.assigned_by = assigned_by
            self.assigned_at = timezone.now()
            self.status = LastMileTask.TaskStatus.ASSIGNED
            if scheduled_time:
                self.scheduled_delivery_time = scheduled_time
            if notes:
                self.internal_notes = notes
            self.save()
            drone.status = DroneUnit.DroneStatus.ON_MISSION
            drone.save(update_fields=["status", "updated_at"])
            LastMileTaskEvent.objects.create(
                task=self,
                event_type=LastMileTaskEvent.EventType.ASSIGNED,
                actor=assigned_by,
                notes=f"Assigned to drone {drone.drone_id}",
            )

    def mark_delivered(
        self, actor: User, pod_photo=None, signature=None, collected_by: str = ""
    ) -> None:
        self.status = LastMileTask.TaskStatus.DELIVERED
        self.actual_delivery_time = timezone.now()
        if pod_photo:
            self.pod_photo = pod_photo
        if signature:
            self.pod_signature = signature
        if collected_by:
            self.pod_collected_by = collected_by
        self.save()
        if self.assigned_driver:
            self.assigned_driver.set_available()
            DriverProfile.objects.filter(pk=self.assigned_driver.pk).update(
                total_deliveries=models.F("total_deliveries") + 1,
                successful_deliveries=models.F("successful_deliveries") + 1,
            )
        if self.assigned_drone:
            self.assigned_drone.status = DroneUnit.DroneStatus.AVAILABLE
            self.assigned_drone.total_missions = models.F("total_missions") + 1
            self.assigned_drone.save(update_fields=["status", "total_missions", "updated_at"])
        LastMileTaskEvent.objects.create(
            task=self,
            event_type=LastMileTaskEvent.EventType.DELIVERED,
            actor=actor,
        )

    def record_failed_attempt(self, actor: User, reason: str) -> None:
        self.attempt_count += 1
        self.status = LastMileTask.TaskStatus.FAILED_ATTEMPT
        self.failure_reason = reason
        self.save(update_fields=["attempt_count", "status", "failure_reason", "updated_at"])
        LastMileTaskEvent.objects.create(
            task=self,
            event_type=LastMileTaskEvent.EventType.FAILED_ATTEMPT,
            actor=actor,
            notes=reason,
        )


# ===========================================================================
# LAST MILE TASK EVENT LOG
# ===========================================================================

class LastMileTaskEvent(TimestampModel):
    """Audit trail for LastMileTask state changes."""

    class EventType(models.TextChoices):
        CREATED = "created", _("Created")
        ASSIGNED = "assigned", _("Assigned")
        ACCEPTED = "accepted", _("Accepted by Driver")
        OUT_FOR_DELIVERY = "out_for_delivery", _("Out for Delivery")
        ARRIVED = "arrived", _("Arrived at Customer")
        DELIVERED = "delivered", _("Delivered")
        FAILED_ATTEMPT = "failed_attempt", _("Failed Attempt")
        RESCHEDULED = "rescheduled", _("Rescheduled")
        RETURNED = "returned", _("Returned to Warehouse")
        NOTE_ADDED = "note_added", _("Note Added")

    task = models.ForeignKey(
        LastMileTask, on_delete=models.CASCADE, related_name="events"
    )
    event_type = models.CharField(max_length=30, choices=EventType.choices)
    actor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )
    notes = models.TextField(blank=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)

    class Meta:
        verbose_name = _("Last Mile Task Event")
        verbose_name_plural = _("Last Mile Task Events")
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.task.task_number} — {self.get_event_type_display()}"


# ===========================================================================
# DISPATCH BATCH  (optional: group multiple tasks into one driver run)
# ===========================================================================

class DispatchBatch(TimestampModel):
    """
    Group multiple PickupTasks or LastMileTasks into a single optimised run
    for a driver (think: a route that does 5 pickups or 10 deliveries).
    """

    class BatchType(models.TextChoices):
        PICKUP = "pickup", _("Pickup Run")
        DELIVERY = "delivery", _("Delivery Run")
        MIXED = "mixed", _("Mixed (Pickup + Delivery)")

    class BatchStatus(models.TextChoices):
        PLANNING = "planning", _("Planning")
        ASSIGNED = "assigned", _("Assigned")
        IN_PROGRESS = "in_progress", _("In Progress")
        COMPLETED = "completed", _("Completed")
        CANCELLED = "cancelled", _("Cancelled")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch_number = models.CharField(max_length=30, unique=True, blank=True)
    batch_type = models.CharField(max_length=20, choices=BatchType.choices)
    status = models.CharField(
        max_length=20, choices=BatchStatus.choices, default=BatchStatus.PLANNING
    )

    # -- Assignment ----------------------------------------------------------
    assigned_driver = models.ForeignKey(
        DriverProfile,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="dispatch_batches",
    )
    assigned_drone = models.ForeignKey(
        DroneUnit,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="dispatch_batches",
    )
    assigned_vehicle = models.ForeignKey(
        "logistics.Vehicle",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="dispatch_batches",
    )
    assigned_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="created_dispatch_batches",
    )

    # -- Tasks ---------------------------------------------------------------
    pickup_tasks = models.ManyToManyField(
        PickupTask,
        blank=True,
        related_name="batches",
    )
    last_mile_tasks = models.ManyToManyField(
        LastMileTask,
        blank=True,
        related_name="batches",
    )

    # -- Timing --------------------------------------------------------------
    planned_start_time = models.DateTimeField(null=True, blank=True)
    actual_start_time = models.DateTimeField(null=True, blank=True)
    actual_end_time = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = _("Dispatch Batch")
        verbose_name_plural = _("Dispatch Batches")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.batch_number} [{self.get_status_display()}]"

    def save(self, *args, **kwargs):
        if not self.batch_number:
            date_str = timezone.now().strftime("%Y%m%d")
            count = DispatchBatch.objects.filter(
                batch_number__startswith=f"DB-{date_str}-"
            ).count() + 1
            self.batch_number = f"DB-{date_str}-{count:04d}"
        super().save(*args, **kwargs)

    @property
    def total_tasks(self) -> int:
        return self.pickup_tasks.count() + self.last_mile_tasks.count()
