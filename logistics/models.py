"""
Logistics Models Module

This module defines the core data models for the logistics management system,
including shipments, drivers, vehicles, warehouses, and related entities.

Author: Logistics Team
Version: 2.0.0
"""

from typing import Optional
from decimal import Decimal
import uuid

from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator, RegexValidator
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

import qrcode
from io import BytesIO
from django.core.files.base import ContentFile
from django.urls import reverse

from orders.models import Order, ShippingAddress, OrderItem

User = get_user_model()


# ============================================================================
# ABSTRACT BASE MODELS
# ============================================================================

class TimeStampedModel(models.Model):
    """
    Abstract base model that provides self-updating 
    created_at and updated_at fields.
    """
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name=_("Created At"),
        help_text=_("Timestamp when the record was created")
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Updated At"),
        help_text=_("Timestamp when the record was last updated")
    )

    class Meta:
        abstract = True
        ordering = ['-created_at']


class ActiveModel(models.Model):
    """
    Abstract base model that provides soft delete functionality.
    """
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name=_("Active"),
        help_text=_("Indicates if the record is active")
    )
    deactivated_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Deactivated At"),
        help_text=_("Timestamp when the record was deactivated")
    )

    class Meta:
        abstract = True

    def deactivate(self):
        """Soft delete the record."""
        self.is_active = False
        self.deactivated_at = timezone.now()
        self.save(update_fields=['is_active', 'deactivated_at'])

    def activate(self):
        """Reactivate the record."""
        self.is_active = True
        self.deactivated_at = None
        self.save(update_fields=['is_active', 'deactivated_at'])


# ============================================================================
# ORGANIZATIONAL MODELS
# ============================================================================

class LogisticOffice(TimeStampedModel, ActiveModel):
    """
    Represents a logistics office location that coordinates shipping operations.

    Attributes:
        name: Official name of the logistics office
        location: Physical address or location description
        code: Unique identifier code for the office
        contact_email: Primary contact email
        contact_phone: Primary contact phone number
        timezone: Office timezone for scheduling
    """

    name = models.CharField(
        max_length=100,
        verbose_name=_("Office Name"),
        help_text=_("Official name of the logistics office")
    )
    location = models.CharField(
        max_length=255,
        verbose_name=_("Location"),
        help_text=_("Physical address or location description")
    )
    code = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        verbose_name=_("Office Code"),
        help_text=_("Unique identifier code (auto-generated if empty)")
    )
    contact_email = models.EmailField(
        blank=True,
        verbose_name=_("Contact Email"),
        help_text=_("Primary contact email for the office")
    )
    contact_phone = models.CharField(
        max_length=20,
        blank=True,
        validators=[
            RegexValidator(
                regex=r'^\+?1?\d{9,15}$',
                message=_("Phone number must be in format: '+999999999'. Up to 15 digits.")
            )
        ],
        verbose_name=_("Contact Phone"),
        help_text=_("Primary contact phone number")
    )
    timezone = models.CharField(
        max_length=50,
        default='UTC',
        verbose_name=_("Timezone"),
        help_text=_("Office timezone for scheduling operations")
    )

    class Meta:
        verbose_name = _("Logistic Office")
        verbose_name_plural = _("Logistic Offices")
        ordering = ['name']
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['is_active', 'name']),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})" if self.code else self.name

    def save(self, *args, **kwargs):
        """Generate office code if not provided."""
        if not self.code:
            self.code = f"LO{self.pk or self._generate_temp_code()}"
        super().save(*args, **kwargs)

    def _generate_temp_code(self) -> str:
        """Generate temporary code based on timestamp."""
        return str(int(timezone.now().timestamp()))


class Warehouse(TimeStampedModel, ActiveModel):
    """
    Represents a warehouse facility for storing and managing inventory.

    Attributes:
        name: Name of the warehouse
        code: Unique warehouse identifier
        address: Complete physical address
        capacity_cubic_meters: Storage capacity in cubic meters
        current_utilization: Current utilization percentage
        manager: Optional manager user reference
        logistic_office: Associated logistics office
    """

    name = models.CharField(
        max_length=100,
        verbose_name=_("Warehouse Name"),
        help_text=_("Name of the warehouse facility")
    )
    code = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        verbose_name=_("Warehouse Code"),
        help_text=_("Unique warehouse identifier")
    )
    address = models.TextField(
        verbose_name=_("Address"),
        help_text=_("Complete physical address of the warehouse")
    )
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        verbose_name=_("Latitude"),
        help_text=_("GPS latitude coordinate")
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        verbose_name=_("Longitude"),
        help_text=_("GPS longitude coordinate")
    )
    capacity_cubic_meters = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        null=True,
        blank=True,
        verbose_name=_("Capacity (m³)"),
        help_text=_("Total storage capacity in cubic meters")
    )
    current_utilization = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name=_("Current Utilization (%)"),
        help_text=_("Current warehouse utilization percentage")
    )
    manager = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='managed_warehouses',
        verbose_name=_("Warehouse Manager")
    )
    logistic_office = models.ForeignKey(
        LogisticOffice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='warehouses',
        verbose_name=_("Logistic Office")
    )

    class Meta:
        verbose_name = _("Warehouse")
        verbose_name_plural = _("Warehouses")
        ordering = ['name']
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['is_active', 'name']),
            models.Index(fields=['logistic_office', 'is_active']),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})" if self.code else self.name

    def save(self, *args, **kwargs):
        """Generate warehouse code if not provided."""
        if not self.code:
            self.code = f"WH{self.pk or self._generate_temp_code()}"
        super().save(*args, **kwargs)

    def _generate_temp_code(self) -> str:
        """Generate temporary code based on timestamp."""
        return str(int(timezone.now().timestamp()))

    def get_available_capacity(self) -> Optional[Decimal]:
        """Calculate available capacity in cubic meters."""
        if self.capacity_cubic_meters:
            used = (self.capacity_cubic_meters * self.current_utilization) / 100
            return self.capacity_cubic_meters - used
        return None

    def update_utilization(self) -> None:
        """
        Recalculate and update warehouse utilization based on current shipments.
        This should be called after shipments are added or removed.
        """
        if not self.capacity_cubic_meters:
            return

        from django.db.models import Sum
        total_volume = self.shipments.filter(
            status__in=['pending', 'in_transit']
        ).aggregate(
            total=Sum('size_cubic_meters')
        )['total'] or Decimal('0.00')

        self.current_utilization = (total_volume / self.capacity_cubic_meters) * 100
        self.save(update_fields=['current_utilization', 'updated_at'])


# ============================================================================
# PERSONNEL MODELS
# ============================================================================

class Driver(TimeStampedModel, ActiveModel):
    """
    Represents a delivery driver with their credentials and information.

    Attributes:
        user: Associated user account
        employee_id: Unique employee identifier
        phone: Contact phone number
        license_number: Driver's license number
        license_expiry: License expiration date
        date_hired: Employment start date
        emergency_contact_name: Emergency contact person
        emergency_contact_phone: Emergency contact phone
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='driver_profile',
        verbose_name=_("User Account")
    )
    employee_id = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        verbose_name=_("Employee ID"),
        help_text=_("Unique employee identifier")
    )
    phone = models.CharField(
        max_length=20,
        validators=[
            RegexValidator(
                regex=r'^\+?1?\d{9,15}$',
                message=_("Phone number must be in format: '+999999999'. Up to 15 digits.")
            )
        ],
        verbose_name=_("Phone Number"),
        help_text=_("Contact phone number")
    )
    license_number = models.CharField(
        max_length=50,
        unique=True,
        verbose_name=_("License Number"),
        help_text=_("Driver's license number")
    )
    license_expiry = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("License Expiry Date"),
        help_text=_("Expiration date of driver's license")
    )
    date_hired = models.DateField(
        default=timezone.now,
        verbose_name=_("Date Hired"),
        help_text=_("Employment start date")
    )
    emergency_contact_name = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("Emergency Contact Name")
    )
    emergency_contact_phone = models.CharField(
        max_length=20,
        blank=True,
        validators=[
            RegexValidator(
                regex=r'^\+?1?\d{9,15}$',
                message=_("Phone number must be in format: '+999999999'. Up to 15 digits.")
            )
        ],
        verbose_name=_("Emergency Contact Phone")
    )

    class Meta:
        verbose_name = _("Driver")
        verbose_name_plural = _("Drivers")
        ordering = ['user__first_name', 'user__last_name']
        indexes = [
            models.Index(fields=['employee_id']),
            models.Index(fields=['license_number']),
            models.Index(fields=['is_active', 'user']),
        ]

    def __str__(self) -> str:
        full_name = self.user.get_full_name()
        return f"{full_name} ({self.employee_id})" if full_name and self.employee_id else full_name or self.user.username

    def save(self, *args, **kwargs):
        """Generate employee ID if not provided."""
        if not self.employee_id:
            self.employee_id = f"DR{self.pk or self._generate_temp_id()}"
        super().save(*args, **kwargs)

    def _generate_temp_id(self) -> str:
        """Generate temporary ID based on timestamp."""
        return str(int(timezone.now().timestamp()))

    def is_license_valid(self) -> bool:
        """Check if driver's license is currently valid."""
        if not self.license_expiry:
            return False
        return self.license_expiry >= timezone.now().date()

    def get_active_shipments_count(self) -> int:
        """Get count of active shipments assigned to this driver."""
        return self.shipments.filter(
            status__in=['pending', 'in_transit', 'shipped']
        ).count()


class Vehicle(TimeStampedModel, ActiveModel):
    """
    Represents a delivery vehicle with its specifications and status.

    Attributes:
        driver: Assigned driver
        plate_number: Vehicle license plate
        model: Vehicle make and model
        year: Manufacturing year
        capacity_kg: Maximum weight capacity
        capacity_cubic_meters: Maximum volume capacity
        fuel_type: Type of fuel used
        last_maintenance: Last maintenance date
        next_maintenance: Scheduled next maintenance
    """

    FUEL_TYPE_CHOICES = [
        ('gasoline', _('Gasoline')),
        ('diesel', _('Diesel')),
        ('electric', _('Electric')),
        ('hybrid', _('Hybrid')),
        ('cng', _('Compressed Natural Gas')),
    ]

    driver = models.ForeignKey(
        Driver,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vehicles',
        verbose_name=_("Assigned Driver")
    )
    plate_number = models.CharField(
        max_length=20,
        unique=True,
        verbose_name=_("Plate Number"),
        help_text=_("Vehicle license plate number")
    )
    model = models.CharField(
        max_length=50,
        verbose_name=_("Model"),
        help_text=_("Vehicle make and model")
    )
    year = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Year"),
        help_text=_("Manufacturing year")
    )
    capacity_kg = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        verbose_name=_("Capacity (kg)"),
        help_text=_("Maximum weight capacity in kilograms")
    )
    capacity_cubic_meters = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        null=True,
        blank=True,
        verbose_name=_("Capacity (m³)"),
        help_text=_("Maximum volume capacity in cubic meters")
    )
    fuel_type = models.CharField(
        max_length=20,
        choices=FUEL_TYPE_CHOICES,
        default='gasoline',
        verbose_name=_("Fuel Type")
    )
    last_maintenance = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Last Maintenance"),
        help_text=_("Date of last maintenance service")
    )
    next_maintenance = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Next Maintenance"),
        help_text=_("Scheduled date for next maintenance")
    )
    vin = models.CharField(
        max_length=17,
        blank=True,
        unique=True,
        verbose_name=_("VIN"),
        help_text=_("Vehicle Identification Number")
    )

    class Meta:
        verbose_name = _("Vehicle")
        verbose_name_plural = _("Vehicles")
        ordering = ['plate_number']
        indexes = [
            models.Index(fields=['plate_number']),
            models.Index(fields=['driver', 'is_active']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self) -> str:
        return f"{self.plate_number} - {self.model}"

    def clean(self):
        """Validate vehicle data."""
        super().clean()

        if self.year and self.year > timezone.now().year + 1:
            raise ValidationError({
                'year': _('Year cannot be in the future.')
            })

        if self.next_maintenance and self.last_maintenance:
            if self.next_maintenance <= self.last_maintenance:
                raise ValidationError({
                    'next_maintenance': _('Next maintenance must be after last maintenance.')
                })

    def needs_maintenance(self) -> bool:
        """Check if vehicle needs maintenance."""
        if not self.next_maintenance:
            return False
        return self.next_maintenance <= timezone.now().date()

    def is_available(self) -> bool:
        """Check if vehicle is available for assignment."""
        if not self.is_active:
            return False
        if self.needs_maintenance():
            return False
        # Check if vehicle has active shipments
        active_shipments = self.shipments.filter(
            status__in=['pending', 'in_transit']
        ).exists()
        return not active_shipments


# ============================================================================
# SHIPMENT MODELS
# ============================================================================

class ShipmentItem(models.Model):
    """
    Tracks which OrderItems are included in which Shipment.
    Allows multiple shipments for the same order with different items.
    """
    shipment = models.ForeignKey(
        'logistics.Shipment',
        on_delete=models.CASCADE,
        related_name='shipment_items'
    )
    order_item = models.ForeignKey(
        'orders.OrderItem',
        on_delete=models.CASCADE,
        related_name='shipment_items'
    )
    quantity = models.PositiveIntegerField()  # Quantity in this specific shipment

    # Track when this item was added to the shipment
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['shipment', 'order_item']
        verbose_name = 'Shipment Item'
        verbose_name_plural = 'Shipment Items'
        ordering = ['added_at']

    def __str__(self):
        return f"{self.order_item.product.name} x{self.quantity} - Shipment #{self.shipment.id}"

    def get_total_price(self):
        """Calculate total price for this item in the shipment"""
        return self.order_item.discounted_unit_price * self.quantity

class Shipment(TimeStampedModel):
    """
    Core shipment model representing a delivery from warehouse to customer.

    This model tracks the entire lifecycle of a shipment including assignment,
    transit, and delivery with comprehensive status tracking and notifications.
    """

    STATUS_CHOICES = [
        ('pending', _('Pending')),
        ('in_transit', _('In Transit')),
        ('shipped', _('Shipped')),
        ('delivered', _('Delivered')),
        ('cancelled', _('Cancelled')),
        ('returned', _('Returned')),
    ]

    MATERIAL_TYPE_CHOICES = [
        ('fragile', _('Fragile')),
        ('flammable', _('Flammable')),
        ('chemical', _('Dangerous Chemical')),
        ('perishable', _('Perishable')),
        ('standard', _('Standard')),
    ]

    SHIPMENT_TYPE_CHOICES = [
        ('express', _('Express')),
        ('normal', _('Normal')),
        ('economic', _('Economic')),
        ('free', _('Free')),
        ('same_day', _('Same Day')),
    ]

    PACKING_TYPE_CHOICES = [
        ('paper_box', _('Paper Box')),
        ('metal_box', _('Metal Box')),
        ('plastic_box', _('Plastic Box')),
        ('wooden_crate', _('Wooden Crate')),
        ('envelope', _('Envelope')),
    ]

    CONTAINER_TYPE_CHOICES = [
        ('plastic', _('Plastic')),
        ('paper', _('Paper')),
        ('metal', _('Metal')),
        ('composite', _('Composite')),
    ]

    # Relationships
    shipping_address = models.ForeignKey(
        ShippingAddress,
        on_delete=models.CASCADE,
        related_name='shipments',
        verbose_name=_("Shipping Address")
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='shipments',
        verbose_name=_("Warehouse")
    )
    driver = models.ForeignKey(
        Driver,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='shipments',
        verbose_name=_("Assigned Driver")
    )
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='shipments',
        verbose_name=_("Assigned Vehicle")
    )
    logistic_office = models.ForeignKey(
        LogisticOffice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='shipments',
        verbose_name=_("Logistic Office")
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='shipments',
        null=True,
        blank=True,
        verbose_name=_("Order")
    )
    shipment_number = models.PositiveIntegerField(
        default=1,
        help_text="Sequential number for this order's shipments"
    )

    # Tracking Information
    tracking_number = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        db_index=True,
        verbose_name=_("Tracking Number"),
        help_text=_("Unique tracking identifier")
    )

    # Scheduling
    collect_time = models.DateTimeField(
        verbose_name=_("Collection Time"),
        help_text=_("Scheduled time for package collection")
    )
    estimated_dropoff_time = models.DateTimeField(
        verbose_name=_("Estimated Dropoff Time"),
        help_text=_("Estimated delivery time")
    )
    actual_dropoff_time = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Actual Dropoff Time"),
        help_text=_("Actual delivery completion time")
    )

    # Physical Specifications
    weight_kg = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        verbose_name=_("Weight (kg)"),
        help_text=_("Total shipment weight in kilograms")
    )
    size_cubic_meters = models.DecimalField(
        max_digits=8,
        decimal_places=3,
        validators=[MinValueValidator(Decimal('0.001'))],
        verbose_name=_("Size (m³)"),
        help_text=_("Total shipment volume in cubic meters")
    )

    # Classification
    material_type = models.CharField(
        max_length=20,
        choices=MATERIAL_TYPE_CHOICES,
        default='standard',
        db_index=True,
        verbose_name=_("Material Type")
    )
    shipment_type = models.CharField(
        max_length=20,
        choices=SHIPMENT_TYPE_CHOICES,
        default='normal',
        db_index=True,
        verbose_name=_("Shipment Type")
    )
    packing_type = models.CharField(
        max_length=20,
        choices=PACKING_TYPE_CHOICES,
        default='paper_box',
        verbose_name=_("Packing Type")
    )
    container_type = models.CharField(
        max_length=20,
        choices=CONTAINER_TYPE_CHOICES,
        default='paper',
        verbose_name=_("Container Type")
    )

    # Status and Documentation
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True,
        verbose_name=_("Status")
    )
    verification_photo = models.ImageField(
        upload_to='shipments/verification/%Y/%m/%d/',
        null=True,
        blank=True,
        verbose_name=_("Verification Photo"),
        help_text=_("Photo proof of delivery")
    )
    delivery_notes = models.TextField(
        blank=True,
        verbose_name=_("Delivery Notes"),
        help_text=_("Additional notes about the delivery")
    )
    special_instructions = models.TextField(
        blank=True,
        verbose_name=_("Special Instructions"),
        help_text=_("Special handling or delivery instructions")
    )

    # Pricing
    shipping_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name=_("Shipping Cost")
    )

    def save(self, *args, **kwargs):
        """Generate tracking number if not provided."""
        if not self.tracking_number:
            self.tracking_number = self._generate_tracking_number()
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = _("Shipment")
        verbose_name_plural = _("Shipments")
        unique_together = ['order', 'shipment_number']
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tracking_number']),
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['driver', 'status']),
            models.Index(fields=['warehouse', 'status']),
            models.Index(fields=['order']),
            models.Index(fields=['-collect_time']),
        ]


    def __str__(self) -> str:
        return f"Shipment {self.tracking_number or f'#{self.id}'}"

    def _generate_tracking_number(self) -> str:
        """Generate unique tracking number."""
        prefix = "TRK"
        timestamp = int(timezone.now().timestamp())
        unique_id = str(uuid.uuid4().hex[:8]).upper()
        return f"{prefix}{timestamp}{unique_id}"

    def clean(self):
        """Validate shipment data."""
        super().clean()

        if self.estimated_dropoff_time and self.collect_time:
            if self.estimated_dropoff_time <= self.collect_time:
                raise ValidationError({
                    'estimated_dropoff_time': _('Estimated dropoff time must be after collection time.')
                })

        if self.actual_dropoff_time and self.collect_time:
            if self.actual_dropoff_time < self.collect_time:
                raise ValidationError({
                    'actual_dropoff_time': _('Actual dropoff time cannot be before collection time.')
                })

    def mark_as_shipped(self) -> None:
        """Transition shipment to shipped status."""
        if self.status == 'pending':
            self.status = 'shipped'
            self.save(update_fields=['status', 'updated_at'])

    def mark_as_in_transit(self) -> None:
        """Transition shipment to in-transit status."""
        if self.status in ['pending', 'shipped']:
            self.status = 'in_transit'
            self.save(update_fields=['status', 'updated_at'])

    def mark_as_delivered(self) -> None:
        """Transition shipment to delivered status."""
        if self.status == 'in_transit':
            self.status = 'delivered'
            self.actual_dropoff_time = timezone.now()
            self.save(update_fields=['status', 'actual_dropoff_time', 'updated_at'])

    def cancel(self, reason: str = "") -> None:
        """Cancel the shipment."""
        if self.status not in ['delivered', 'cancelled']:
            self.status = 'cancelled'
            if reason:
                self.delivery_notes = f"{self.delivery_notes}\nCancellation reason: {reason}".strip()
            self.save(update_fields=['status', 'delivery_notes', 'updated_at'])

    def is_overdue(self) -> bool:
        """Check if shipment is past estimated delivery time."""
        if self.status in ['delivered', 'cancelled', 'returned']:
            return False
        return timezone.now() > self.estimated_dropoff_time

    def get_status_display_color(self) -> str:
        """Get Bootstrap color class for current status."""
        status_colors = {
            'pending': 'warning',
            'in_transit': 'info',
            'shipped': 'primary',
            'delivered': 'success',
            'cancelled': 'danger',
            'returned': 'secondary',
        }
        return status_colors.get(self.status, 'secondary')

    def __str__(self):
        if self.order:
            return f"Shipment #{self.shipment_number} for Order #{self.order.id}"
        return f"Shipment #{self.id}"

    def get_items_count(self):
        """Get count of items in this shipment"""
        return self.shipment_items.count()

    def get_total_value(self):
        """Calculate total value of all items in this shipment"""
        return sum(item.get_total_price() for item in self.shipment_items.all())

    def get_items_list(self):
        """Get list of items with details"""
        return [
            {
                'product_name': item.order_item.product.name,
                'sku': getattr(item.order_item.product, 'sku', 'N/A'),
                'quantity': item.quantity,
                'price': item.get_total_price()
            }
            for item in self.shipment_items.all()
        ]


class ShipmentBox(TimeStampedModel):
    """
    Represents an individual box/package within a shipment.

    Used for tracking multiple boxes in a single shipment with individual
    labels and contents.
    """

    shipment = models.ForeignKey(
        Shipment,
        on_delete=models.CASCADE,
        related_name='boxes',
        verbose_name=_("Shipment")
    )
    box_number = models.PositiveIntegerField(
        verbose_name=_("Box Number"),
        help_text=_("Sequential number within the shipment")
    )
    weight_kg = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.01'))],
        verbose_name=_("Weight (kg)")
    )
    dimensions = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("Dimensions"),
        help_text=_("Format: LxWxH in cm")
    )
    label = models.ImageField(
        upload_to='shipments/box_labels/%Y/%m/%d/',
        blank=True,
        null=True,
        verbose_name=_("Label"),
        help_text=_("QR code label for the box")
    )
    qr_data = models.TextField(
        blank=True,
        verbose_name=_("QR Data"),
        help_text=_("Data encoded in the QR code")
    )

    class Meta:
        verbose_name = _("Shipment Box")
        verbose_name_plural = _("Shipment Boxes")
        unique_together = [['shipment', 'box_number']]
        ordering = ['shipment', 'box_number']
        indexes = [
            models.Index(fields=['shipment', 'box_number']),
        ]

    def __str__(self) -> str:
        return f"Box #{self.box_number} of {self.shipment.tracking_number}"

    def generate_qr_label(self) -> None:
        """Generate QR code label for the box."""
        # Prepare QR data
        self.qr_data = (
            f"Shipment: {self.shipment.tracking_number}\n"
            f"Box: {self.box_number}/{self.shipment.boxes.count()}\n"
            f"Weight: {self.weight_kg}kg"
        )

        # Generate QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(self.qr_data)
        qr.make(fit=True)

        # Create image
        img = qr.make_image(fill_color="black", back_color="white")

        # Save to buffer
        buffer = BytesIO()
        img.save(buffer, format='PNG')

        # Save to model
        filename = f"box_{self.shipment.tracking_number}_{self.box_number}.png"
        self.label.save(filename, ContentFile(buffer.getvalue()), save=False)
        buffer.close()

        self.save(update_fields=['label', 'qr_data', 'updated_at'])

    def get_total_items_count(self) -> int:
        """Get total count of items in this box."""
        return sum(item.quantity for item in self.items.all())


class BoxItem(TimeStampedModel):
    """
    Represents individual order items packed in a shipment box.

    Links order items to specific boxes for accurate tracking and verification.
    """

    box = models.ForeignKey(
        ShipmentBox,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name=_("Box")
    )
    order_item = models.ForeignKey(
        OrderItem,
        on_delete=models.CASCADE,
        related_name='box_items',
        verbose_name=_("Order Item")
    )
    quantity = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        verbose_name=_("Quantity"),
        help_text=_("Number of units packed in this box")
    )
    notes = models.TextField(
        blank=True,
        verbose_name=_("Notes"),
        help_text=_("Additional notes about this item in the box")
    )

    class Meta:
        verbose_name = _("Box Item")
        verbose_name_plural = _("Box Items")
        ordering = ['box', 'order_item']
        indexes = [
            models.Index(fields=['box', 'order_item']),
        ]

    def __str__(self) -> str:
        product_name = self.order_item.product.name if self.order_item.product else "Unknown Product"
        return f"{self.quantity}x {product_name} in {self.box}"

    def clean(self):
        """Validate box item data."""
        super().clean()

        if self.order_item and self.quantity:
            # Check if quantity exceeds order item quantity
            if self.quantity > self.order_item.quantity:
                raise ValidationError({
                    'quantity': _('Quantity cannot exceed order item quantity.')
                })

class DriverLocation(models.Model):
    driver = models.ForeignKey("logistics.Driver", on_delete=models.CASCADE, related_name="locations")
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    accuracy_m = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    speed_mps = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    heading = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    recorded_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-recorded_at"]
        indexes = [models.Index(fields=["driver", "-recorded_at"])]


class WarehouseShipmentNotification(models.Model):
    """
    Notifications for items marked as shipped to warehouse.
    Sent to logistics users when store owners mark items.
    """

    NOTIFICATION_TYPES = [
        ('item_shipped', 'Item Shipped to Warehouse'),
        ('all_items_shipped', 'All Items Shipped'),
        ('shipment_created', 'Shipment Created'),
    ]

    # Recipients
    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='warehouse_notifications'
    )

    # Notification details
    notification_type = models.CharField(
        max_length=20,
        choices=NOTIFICATION_TYPES,
        default='item_shipped'
    )

    # Related objects
    order = models.ForeignKey(
        'orders.Order',
        on_delete=models.CASCADE,
        related_name='warehouse_notifications'
    )
    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.CASCADE,
        related_name='warehouse_notifications',
        null=True,
        blank=True
    )

    # Notification content
    title = models.CharField(max_length=255)
    message = models.TextField()
    items_count = models.PositiveIntegerField(default=1)

    # Status tracking
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'is_read', '-created_at']),
            models.Index(fields=['order', '-created_at']),
        ]

    def __str__(self):
        return f"{self.notification_type} - Order #{self.order.id} ({self.recipient.username})"

    def mark_as_read(self):
        """Mark notification as read"""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])

    def get_absolute_url(self):
        """Get URL to view this notification's order"""
        return reverse('logistics:order_detail', kwargs={'order_id': self.order.id})

    def get_time_since(self):
        """Get human-readable time since creation"""
        from django.utils.timesince import timesince
        return timesince(self.created_at)

    @staticmethod
    def create_item_shipped_notification(order, store, items_count=1):
        """
        Create notifications for all logistics users when item(s) shipped.

        Args:
            order: Order instance
            store: Store instance
            items_count: Number of items in this notification
        """
        logistics_users = User.objects.filter(is_logistic=True, is_active=True)

        notifications = []
        for user in logistics_users:
            notification = WarehouseShipmentNotification.objects.create(
                recipient=user,
                notification_type='item_shipped',
                order=order,
                store=store,
                title=f"Items shipped to warehouse - Order #{order.id}",
                message=f"{store.name} marked {items_count} item(s) as shipped to warehouse for Order #{order.id}",
                items_count=items_count
            )
            notifications.append(notification)

        return notifications

    @staticmethod
    def create_all_items_shipped_notification(order, store, items_count):
        """Create notification when all items in order are shipped."""
        logistics_users = User.objects.filter(is_logistic=True, is_active=True)

        notifications = []
        for user in logistics_users:
            notification = WarehouseShipmentNotification.objects.create(
                recipient=user,
                notification_type='all_items_shipped',
                order=order,
                store=store,
                title=f"All items ready - Order #{order.id}",
                message=f"All {items_count} item(s) from {store.name} are now shipped to warehouse",
                items_count=items_count
            )
            notifications.append(notification)

        return notifications

    @staticmethod
    def get_unread_count(user):
        """Get count of unread notifications for user"""
        return WarehouseShipmentNotification.objects.filter(
            recipient=user,
            is_read=False
        ).count()

    @staticmethod
    def get_recent_notifications(user, limit=10):
        """Get recent notifications for user"""
        return WarehouseShipmentNotification.objects.filter(
            recipient=user
        ).select_related('order', 'store')[:limit]

    @staticmethod
    def mark_all_as_read(user):
        """Mark all notifications as read for user"""
        return WarehouseShipmentNotification.objects.filter(
            recipient=user,
            is_read=False
        ).update(
            is_read=True,
            read_at=timezone.now()
        )

