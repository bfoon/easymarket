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
from stores.b2b.models import B2BOrder, B2BOrderItem, B2BShippingAddress

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

    created_by = models.DateTimeField(auto_now_add=True)

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
        return reverse('logistics:warehouse_order_detail', kwargs={'order_id': self.order.id})

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


class B2BShipment(models.Model):
    """
    Logistics shipment record for a B2B order.
    Created/managed by logistics team after seller marks order as shipped.

    LOCK BEHAVIOR:
    - Shipment starts unlocked (editable)
    - When "Generate All Labels" is clicked, status becomes 'locked'
    - Locked shipments are READ-ONLY (logistics details cannot be changed)
    - Can be manually unlocked by logistics admins if needed
    """

    STATUS_CHOICES = [
        ("draft", "Draft - Editable"),
        ("locked", "Locked - Labels Generated"),
        ("in_transit", "In Transit"),
        ("delivered", "Delivered"),
    ]

    SHIPMENT_MODE_CHOICES = [
        ("easy_move", "Easy Move (Normal)"),
        ("cargo", "Cargo"),
        ("air_freight", "Air Freight"),
    ]

    MATERIAL_TYPE_CHOICES = [
        ("standard", "Standard"),
        ("fragile", "Fragile"),
        ("flammable", "Flammable"),
        ("chemical", "Dangerous Chemical"),
        ("perishable", "Perishable"),
    ]

    order = models.OneToOneField(
        B2BOrder,  # Use string reference
        on_delete=models.CASCADE,
        related_name="logistics_shipment",
    )

    # duplicate link (convenience) - B2B has its own shipping model
    shipping_address = models.OneToOneField(
        B2BShippingAddress,  # Use string reference
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="logistics_shipment",
    )

    tracking_number = models.CharField(max_length=80, blank=True, null=True, unique=True)

    # NEW: Lock status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="draft",
        help_text="Draft = editable, Locked = read-only after labels generated, In Transit = shipped, Delivered = completed"
    )
    locked_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when shipment was locked"
    )
    locked_by = models.ForeignKey(
        User,  # Use string reference
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="locked_shipments",
        help_text="User who locked the shipment"
    )

    # NEW: Delivery tracking
    delivered_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when shipment was marked as delivered"
    )
    delivered_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivered_shipments",
        help_text="User who marked shipment as delivered"
    )
    delivery_notes = models.TextField(
        blank=True,
        help_text="Notes about the delivery (signature, condition, etc.)"
    )
    delivery_proof = models.ImageField(
        upload_to='shipment_delivery_proofs/',
        null=True,
        blank=True,
        help_text="Photo proof of delivery (optional)"
    )

    # Logistics details
    weight_kg = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.01"))]
    )
    cubic_m = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.001"))],
        help_text="Cubic meters (m³)"
    )
    total_boxes = models.PositiveIntegerField(default=0)

    material_type = models.CharField(max_length=20, choices=MATERIAL_TYPE_CHOICES, default="standard")
    material_class = models.CharField(
        max_length=80, blank=True,
        help_text="Optional material class (e.g. Class 3 Flammable Liquids)"
    )

    shipment_mode = models.CharField(max_length=20, choices=SHIPMENT_MODE_CHOICES, default="easy_move")
    company_config = models.ForeignKey(
        "supply_chain.ShippingCompanyCountry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="logistics_shipments",
        help_text="Selected shipping company configuration based on origin + mode"
    )

    # Optional: cache company name (nice for display even if config changes later)
    shipping_company_name = models.CharField(max_length=200, blank=True)

    shipping_cost = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    eta_text = models.CharField(max_length=120, blank=True, help_text="Estimated delivery time, e.g. 3-5 days")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['tracking_number']),
        ]

    def __str__(self):
        status_emoji = "🔒" if self.is_locked() else "📝"
        return f"{status_emoji} B2BShipment {self.tracking_number or self.order_id}"

    def is_locked(self):
        """Check if shipment is locked (read-only)"""
        return self.status in ["locked", "in_transit", "delivered"]

    def is_draft(self):
        """Check if shipment is still editable"""
        return self.status == "draft"

    def is_delivered(self):
        """Check if shipment has been delivered"""
        return self.status == "delivered"

    def is_in_transit(self):
        """Check if shipment is currently in transit"""
        return self.status == "in_transit"

    def lock(self, user=None):
        """
        Lock the shipment (make it read-only).
        Called automatically when QR labels are generated.
        """
        if self.status == "draft":
            self.status = "locked"
            self.locked_at = timezone.now()
            if user:
                self.locked_by = user
            self.save(update_fields=['status', 'locked_at', 'locked_by', 'updated_at'])
            return True
        return False

    def unlock(self, user=None):
        """
        Unlock the shipment (allow editing again).
        Should only be done by logistics admins when corrections are needed.
        """
        if self.status in ["locked", "in_transit"]:
            self.status = "draft"
            self.locked_at = None
            self.locked_by = None
            self.save(update_fields=['status', 'locked_at', 'locked_by', 'updated_at'])
            return True
        return False

    def set_company_config(self, config):
        """Helper to keep fields consistent."""
        self.company_config = config
        self.shipping_company_name = config.shipping_company.name if config else ""

    def mark_in_transit(self, user=None):
        """
        Mark shipment as in transit.

        Requirements:
        - Shipment must be locked
        - Fulfillment must be READY
        """
        from django.core.exceptions import ValidationError
        from supply_chain.models import FulfillmentQueue

        # Validate shipment status
        if self.status != "locked":
            raise ValidationError("Shipment must be locked before marking as in transit")

        # Check fulfillment status
        try:
            fulfillment = FulfillmentQueue.objects.get(b2b_order=self.order)

            if fulfillment.status != "READY":
                raise ValidationError(
                    f"Fulfillment must be READY. Current status: {fulfillment.get_status_display()}"
                )

            # Update fulfillment to SHIPPED (keep this as your fulfillment system expects)
            fulfillment.status = "SHIPPED"
            fulfillment.shipped_at = timezone.now()
            if user:
                fulfillment.shipped_by = user
            fulfillment.save(update_fields=["status", "shipped_at", "shipped_by"])

        except FulfillmentQueue.DoesNotExist:
            raise ValidationError("No fulfillment queue found for this order")

        # Update shipment (✅ use lowercase choice)
        self.status = "in_transit"

        # If you don't have shipped_at on this model, REMOVE these two lines.
        if hasattr(self, "shipped_at"):
            self.shipped_at = timezone.now()

        # If you don't have estimated_delivery on this model, REMOVE these lines.
        if hasattr(self, "estimated_delivery") and not self.estimated_delivery and self.company_config:
            self.estimated_delivery = timezone.now() + timezone.timedelta(
                days=int(getattr(self.company_config, "estimated_days", 0) or 0)
            )

        self.save()
        return True

    def can_mark_in_transit(self):
        """
        Returns: (can_mark: bool, reason: str)
        """
        from supply_chain.models import FulfillmentQueue

        if self.status != "locked":
            return (False, "Shipment must be locked first")

        try:
            fulfillment = FulfillmentQueue.objects.get(b2b_order=self.order)

            if fulfillment.status != "READY":
                return (False, f"Fulfillment must be READY. Current: {fulfillment.get_status_display()}")

            return (True, "Ready to mark as in transit")

        except FulfillmentQueue.DoesNotExist:
            return (False, "No fulfillment queue found")

    def mark_shipped(self, tracking_number, user=None):
        """Mark shipment as shipped (alternative to mark_in_transit)"""
        self.status = 'SHIPPED'
        self.tracking_number = tracking_number
        self.shipped_at = timezone.now()

        # Set estimated delivery
        if self.company_config and not self.estimated_delivery:
            self.estimated_delivery = timezone.now() + timezone.timedelta(
                days=self.company_config.estimated_days
            )

        self.save()

        # Note: This doesn't update fulfillment - use mark_in_transit for that
        return True

    def mark_delivered(self, user=None, delivery_notes=None, delivery_proof=None):
        """
        Mark shipment as delivered and store optional delivery notes/proof.
        """
        # ✅ use lowercase choice value
        self.status = "DELIVERED"
        self.delivered_at = timezone.now()

        if user:
            self.delivered_by = user

        if delivery_notes is not None:
            self.delivery_notes = (delivery_notes or "").strip()

        if delivery_proof is not None:
            self.delivery_proof = delivery_proof

        self.save(update_fields=[
            "status", "delivered_at", "delivered_by",
            "delivery_notes", "delivery_proof", "updated_at"
        ])
        return True

    @property
    def fulfillment_status(self):
        from supply_chain.models import FulfillmentQueue
        try:
            fulfillment = FulfillmentQueue.objects.get(b2b_order=self.order)
            return fulfillment.status
        except FulfillmentQueue.DoesNotExist:
            return None

    @property
    def is_ready_to_ship(self):
        """Check if order is ready to be marked as in transit"""
        can_mark, _ = self.can_mark_in_transit()
        return can_mark

    def can_edit(self):
        """Check if logistics details can be edited"""
        return self.is_draft()

    def get_status_display_with_icon(self):
        """Get status with icon for display"""
        icons = {
            'draft': '📝 Draft - Editable',
            'locked': '🔒 Locked - Read Only',
            'in_transit': '🚚 In Transit',
            'delivered': '✅ Delivered',
        }
        return icons.get(self.status, self.status)

    def ensure_shipping_address(self):
        if not self.shipping_address and hasattr(self.order, "shipping_address"):
            self.shipping_address = self.order.shipping_address
        if not self.shipping_address:
            from .models import B2BShippingAddress  # Adjust import
            addr = B2BShippingAddress.objects.filter(order=self.order).first()
            if addr:
                self.shipping_address = addr

    def clean(self):
        super().clean()
        # Prevent editing locked shipments
        if self.pk and self.is_locked():
            # Allow certain fields to be updated even when locked
            allowed_updates = ['updated_at', 'total_boxes']

            # Get the original instance from database
            try:
                original = B2BShipment.objects.get(pk=self.pk)

                # Check if any protected fields were changed
                protected_fields = [
                    'weight_kg', 'cubic_m', 'material_type', 'material_class',
                    'shipment_mode', 'shipping_cost', 'eta_text'
                ]

                for field in protected_fields:
                    if getattr(self, field) != getattr(original, field):
                        from django.core.exceptions import ValidationError
                        raise ValidationError(
                            f"Cannot modify {field} - shipment is locked. "
                            "Please unlock the shipment first if corrections are needed."
                        )
            except B2BShipment.DoesNotExist:
                pass

        # Keep total_boxes consistent
        actual_boxes = self.boxes.count() if self.pk else 0
        if self.total_boxes and actual_boxes and self.total_boxes != actual_boxes:
            pass  # Allow mismatch, but you can enforce if needed

class B2BShipmentItem(models.Model):
    """
    What is being shipped (B2B order items with quantity).
    """
    shipment = models.ForeignKey(B2BShipment, on_delete=models.CASCADE, related_name="shipment_items")
    order_item = models.ForeignKey(B2BOrderItem, on_delete=models.CASCADE, related_name="b2b_shipment_items")
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        unique_together = ("shipment", "order_item")

    def __str__(self):
        return f"{self.order_item_id} x{self.quantity}"

    def get_total_price(self):
        # prefer seller_unit_price if it exists, else requested_unit_price, else 0
        unit = getattr(self.order_item, "seller_unit_price", None) or getattr(self.order_item, "requested_unit_price", None) or Decimal("0.00")
        return (unit or Decimal("0.00")) * Decimal(int(self.quantity or 0))


class B2BShipmentBox(models.Model):
    """
    Box inside a B2BShipment (label + QR).
    """
    shipment = models.ForeignKey(B2BShipment, on_delete=models.CASCADE, related_name="boxes")
    box_number = models.PositiveIntegerField()
    weight_kg = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.01"))]
    )
    dimensions = models.CharField(max_length=50, blank=True, help_text="LxWxH in cm (optional)")

    label = models.ImageField(upload_to="b2b_shipments/box_labels/%Y/%m/%d/", null=True, blank=True)
    qr_data = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("shipment", "box_number")
        ordering = ["shipment", "box_number"]

    def __str__(self):
        return f"B2B Box #{self.box_number} ({self.shipment.tracking_number})"

    def generate_qr_label(self):
        """
        QR includes tracking + customer info.
        Mirrors your existing ShipmentBox.generate_qr_label pattern :contentReference[oaicite:3]{index=3}
        """
        sh = self.shipment
        sh.ensure_shipping_address()
        addr = sh.shipping_address

        buyer = sh.order.buyer
        buyer_name = buyer.get_full_name() or buyer.username

        # Build readable customer block
        customer_block = ""
        if addr:
            customer_block = (
                f"Customer: {addr.full_name or buyer_name}\n"
                f"Phone: {addr.phone or ''}\n"
                f"Company: {addr.company_name or ''}\n"
                f"Address: {addr.address_line or ''}\n"
                f"City/Region: {addr.city or ''} {addr.region or ''}\n"
                f"Country: {addr.country or ''}\n"
            ).strip()

        total_boxes = sh.boxes.count() or (sh.total_boxes or 0)

        self.qr_data = (
            f"TRACKING: {sh.tracking_number}\n"
            f"BOX: {self.box_number}/{total_boxes}\n"
            f"MODE: {sh.shipment_mode}\n"
            f"{customer_block}"
        ).strip()

        qr = qrcode.QRCode(
            version=2,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=3,
        )
        qr.add_data(self.qr_data)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        filename = f"b2b_box_{sh.tracking_number}_#{self.box_number}.png"
        self.label.save(filename, ContentFile(buf.getvalue()), save=False)
        buf.close()

        self.save(update_fields=["label", "qr_data", "updated_at"])


class B2BBoxItem(models.Model):
    """
    B2B order items packed in a B2BShipmentBox.
    """
    box = models.ForeignKey(B2BShipmentBox, on_delete=models.CASCADE, related_name="items")
    order_item = models.ForeignKey(B2BOrderItem, on_delete=models.CASCADE, related_name="b2b_box_items")
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        unique_together = ("box", "order_item")

    def clean(self):
        super().clean()
        if self.quantity and self.quantity < 1:
            raise ValidationError({"quantity": "Quantity must be at least 1."})


class OrderLogisticsAgent(models.Model):
    """
    Tracks logistics agents/staff assigned to handle specific orders
    """
    STATUS_CHOICES = [
        ('assigned', 'Assigned'),
        ('working', 'Working on Order'),
        ('paused', 'Paused'),
        ('completed', 'Completed'),
    ]

    order = models.OneToOneField(
        'orders.Order',
        on_delete=models.CASCADE,
        related_name='logistics_agent_assignment'
    )
    agent = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='assigned_orders',
        help_text="Logistics staff/agent assigned to this order"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='assigned'
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    started_working_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    # Agent availability status
    is_available = models.BooleanField(default=True)
    last_activity = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-assigned_at']
        verbose_name = 'Order Logistics Agent'
        verbose_name_plural = 'Order Logistics Agents'

    def __str__(self):
        agent_name = self.agent.get_full_name() if self.agent else "Unassigned"
        return f"Order #{self.order.id} - {agent_name}"

    def start_working(self):
        """Mark agent as actively working on the order"""
        self.status = 'working'
        self.started_working_at = timezone.now()
        self.save(update_fields=['status', 'started_working_at', 'last_activity'])

    def mark_completed(self):
        """Mark the logistics work as completed"""
        self.status = 'completed'
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'completed_at', 'last_activity'])

    def pause_work(self):
        """Pause work on this order"""
        self.status = 'paused'
        self.save(update_fields=['status', 'last_activity'])

    @property
    def is_working(self):
        """Check if agent is currently working on this order"""
        return self.status == 'working'

    @property
    def agent_display_name(self):
        """Get display name for the agent"""
        if not self.agent:
            return "No agent assigned"
        return self.agent.get_full_name() or self.agent.username

    @property
    def working_duration(self):
        """Calculate how long the agent has been working"""
        if not self.started_working_at:
            return None

        end_time = self.completed_at or timezone.now()
        return end_time - self.started_working_at


class LogisticsAgentMessage(models.Model):
    """
    Chat messages between store owners and logistics agents
    """
    order = models.ForeignKey(
        'orders.Order',
        on_delete=models.CASCADE,
        related_name='logistics_messages'
    )
    sender = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='sent_logistics_messages'
    )
    message = models.TextField()
    image = models.ImageField(
        upload_to='logistics_chat/%Y/%m/%d/',
        null=True,
        blank=True
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Logistics Agent Message'
        verbose_name_plural = 'Logistics Agent Messages'

    def __str__(self):
        return f"Message on Order #{self.order.id} from {self.sender.username}"


class WarehouseReceipt(models.Model):
    """
    Tracks when shipments/orders are received at the warehouse
    """
    STATUS_CHOICES = [
        ('pending', 'Pending Receipt'),
        ('partial', 'Partially Received'),
        ('received', 'Fully Received'),
        ('discrepancy', 'Has Discrepancies'),
    ]

    shipment = models.ForeignKey(
        'Shipment',
        on_delete=models.CASCADE,
        related_name='warehouse_receipts',
        null=True,
        blank=True
    )
    order = models.ForeignKey(
        'orders.Order',
        on_delete=models.CASCADE,
        related_name='warehouse_receipts'
    )

    # Receipt details
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    received_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='warehouse_receipts_received'
    )
    received_at = models.DateTimeField(null=True, blank=True)

    # Verification
    verification_code = models.CharField(max_length=50, unique=True, db_index=True)
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)

    # Notes and issues
    notes = models.TextField(blank=True, help_text="Any notes or observations")
    has_issues = models.BooleanField(default=False)
    issue_description = models.TextField(blank=True)

    # Notifications
    store_notified = models.BooleanField(default=False)
    notification_sent_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Warehouse Receipt'
        verbose_name_plural = 'Warehouse Receipts'

    def __str__(self):
        return f"Receipt for Order #{self.order.id} - {self.status}"

    def mark_received(self, user, notes=''):
        """Mark this receipt as received"""
        self.status = 'received'
        self.received_by = user
        self.received_at = timezone.now()
        self.is_verified = True
        self.verified_at = timezone.now()
        if notes:
            self.notes = notes
        self.save()

    def generate_verification_code(self):
        """Generate unique verification code"""
        import uuid
        self.verification_code = f"WH-{self.order.id}-{uuid.uuid4().hex[:8].upper()}"
        self.save()
        return self.verification_code


class WarehouseReceiptItem(models.Model):
    """
    Individual items in a warehouse receipt
    """
    receipt = models.ForeignKey(
        'WarehouseReceipt',
        on_delete=models.CASCADE,
        related_name='items'
    )
    order_item = models.ForeignKey(
        'orders.OrderItem',
        on_delete=models.CASCADE,
        related_name='warehouse_receipt_items'
    )

    # Expected vs Received quantities
    expected_quantity = models.PositiveIntegerField()
    received_quantity = models.PositiveIntegerField(default=0)

    # Condition
    condition = models.CharField(
        max_length=20,
        choices=[
            ('good', 'Good Condition'),
            ('damaged', 'Damaged'),
            ('missing', 'Missing'),
        ],
        default='good'
    )

    # Notes for this specific item
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['id']
        verbose_name = 'Warehouse Receipt Item'
        verbose_name_plural = 'Warehouse Receipt Items'

    def __str__(self):
        return f"{self.order_item.product.name} - {self.received_quantity}/{self.expected_quantity}"

    @property
    def is_complete(self):
        """Check if received quantity matches expected"""
        return self.received_quantity == self.expected_quantity

    @property
    def has_discrepancy(self):
        """Check if there's a discrepancy"""
        return self.received_quantity != self.expected_quantity or self.condition != 'good'
