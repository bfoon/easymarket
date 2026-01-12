from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError
from decimal import Decimal


# ==================== WAREHOUSE & LOGISTICS ====================

class WarehouseLinkage(models.Model):
    """
    Links store warehouses to logistics warehouses.
    Manages the flow of goods from store to logistics centers.
    """
    # Using BigAutoField instead of UUID for compatibility

    # Warehouses
    store_warehouse = models.ForeignKey(
        'stock.Warehouse',
        on_delete=models.CASCADE,
        related_name='logistics_linkages'
    )
    logistics_warehouse = models.ForeignKey(
        'logistics.Warehouse',
        on_delete=models.CASCADE,
        related_name='store_linkages'
    )

    # Linkage Configuration
    is_primary = models.BooleanField(
        default=True,
        help_text="Primary logistics warehouse for this store"
    )
    is_active = models.BooleanField(default=True)
    priority = models.IntegerField(
        default=1,
        help_text="Lower number = higher priority"
    )

    # Logistics Info
    distance_km = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Distance between warehouses in km"
    )
    estimated_transfer_time_minutes = models.IntegerField(
        default=60,
        help_text="Estimated time to transfer goods"
    )

    # Capacity & Constraints
    max_daily_transfers = models.IntegerField(
        default=10,
        help_text="Maximum number of daily transfers"
    )
    operating_hours_start = models.TimeField(default='08:00')
    operating_hours_end = models.TimeField(default='18:00')

    # Metadata
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['store_warehouse', 'priority']
        unique_together = ['store_warehouse', 'logistics_warehouse']

    def __str__(self):
        return f"{self.store_warehouse.code} → {self.logistics_warehouse.name}"

    @classmethod
    def get_optimal_logistics_warehouse(cls, store_warehouse):
        """Get the optimal logistics warehouse for a store warehouse"""
        linkage = cls.objects.filter(
            store_warehouse=store_warehouse,
            is_active=True
        ).order_by('priority', 'distance_km').first()

        return linkage.logistics_warehouse if linkage else None


class StoreToLogisticsTransfer(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending Pickup'),
        ('PICKED_UP', 'In Transit'),
        ('RECEIVED', 'Received at Logistics'),
        ('CANCELLED', 'Cancelled'),
    ]

    transfer_number = models.CharField(max_length=50, unique=True, editable=False)

    store_warehouse = models.ForeignKey(
        'stock.Warehouse', on_delete=models.PROTECT, related_name='outbound_transfers'
    )
    logistics_warehouse = models.ForeignKey(
        'logistics.Warehouse', on_delete=models.PROTECT, related_name='inbound_transfers'
    )

    # Orders
    order = models.ForeignKey(
        'orders.Order',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='supply_transfers'
    )
    b2b_order = models.ForeignKey(
        'stores.B2BOrder',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='supply_transfers'
    )

    # Status and Duration
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    actual_duration_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Actual transfer duration in minutes"
    )

    # ✅ NEW FIELDS - Requested tracking
    requested_at = models.DateTimeField(auto_now_add=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='requested_transfers'
    )

    # ✅ NEW FIELDS - Picked up tracking
    picked_up_at = models.DateTimeField(null=True, blank=True)
    picked_up_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='picked_up_transfers'
    )

    # ✅ NEW FIELDS - Received tracking
    received_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='received_transfers'
    )

    # ✅ NEW FIELDS - Vehicle and Driver
    vehicle = models.ForeignKey(
        'logistics.Vehicle',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transfers'
    )
    driver = models.ForeignKey(
        'logistics.Driver',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transfers'
    )

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-requested_at']

    def save(self, *args, **kwargs):
        if not self.transfer_number:
            # Generate transfer number: TRF-YYYYMMDD-XXXX
            from django.db.models import Max
            today = timezone.now().date()
            prefix = f"TRF-{today.strftime('%Y%m%d')}"

            last_transfer = StoreToLogisticsTransfer.objects.filter(
                transfer_number__startswith=prefix
            ).aggregate(Max('transfer_number'))['transfer_number__max']

            if last_transfer:
                last_num = int(last_transfer.split('-')[-1])
                new_num = last_num + 1
            else:
                new_num = 1

            self.transfer_number = f"{prefix}-{new_num:04d}"

        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        # Enforce exactly one of (order, b2b_order)
        if bool(self.order_id) == bool(self.b2b_order_id):
            raise ValidationError("Transfer must be linked to either Order OR B2BOrder (not both).")

    def __str__(self):
        ref = self.order_id or self.b2b_order_id
        return f"{self.transfer_number} ({ref})"

    def mark_picked_up(self, user, vehicle=None, driver=None):
        """Mark transfer as picked up"""
        self.status = 'PICKED_UP'
        self.picked_up_at = timezone.now()
        self.picked_up_by = user
        self.vehicle = vehicle
        self.driver = driver
        self.save()

    def mark_received(self, user, condition_notes=''):
        """Mark transfer as received"""
        self.status = 'RECEIVED'
        self.received_at = timezone.now()
        self.received_by = user

        if condition_notes:
            self.notes = (self.notes or '') + f"\n\nReceiving Notes: {condition_notes}"

        # Calculate duration from pickup to receipt
        if self.picked_up_at:
            duration = (self.received_at - self.picked_up_at).total_seconds() / 60
            self.actual_duration_minutes = int(duration)

        self.save()

    @property
    def ref_order(self):
        """Return whichever order is set (B2C or B2B)"""
        return self.order or self.b2b_order


class FulfillmentQueue(models.Model):
    PRIORITY_CHOICES = [
        ('URGENT', 'Urgent'),
        ('HIGH', 'High'),
        ('NORMAL', 'Normal'),
        ('LOW', 'Low'),
    ]

    STATUS_CHOICES = [
        ('QUEUED', 'In Queue'),
        ('PICKING', 'Being Picked'),
        ('PACKING', 'Being Packed'),
        ('READY', 'Ready to Ship'),
        ('SHIPPED', 'Shipped'),
        ('CANCELLED', 'Cancelled'),
    ]

    # ✅ B2C order (make nullable now)
    order = models.OneToOneField(
        'orders.Order',
        on_delete=models.CASCADE,
        related_name='fulfillment_queue',
        null=True, blank=True
    )

    # ✅ B2B order (NEW)
    b2b_order = models.OneToOneField(
        'stores.B2BOrder',
        on_delete=models.CASCADE,
        related_name='fulfillment_queue',
        null=True, blank=True
    )

    logistics_warehouse = models.ForeignKey(
        'logistics.Warehouse', on_delete=models.PROTECT, related_name='fulfillment_queue'
    )

    transfer = models.ForeignKey(
        StoreToLogisticsTransfer, on_delete=models.SET_NULL, null=True, blank=True
    )

    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='NORMAL')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='QUEUED')

    queued_at = models.DateTimeField(auto_now_add=True)

    picking_started_at = models.DateTimeField(null=True, blank=True)
    picking_completed_at = models.DateTimeField(null=True, blank=True)
    picked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='picked_orders'
    )

    packing_started_at = models.DateTimeField(null=True, blank=True)
    packing_completed_at = models.DateTimeField(null=True, blank=True)
    packed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='packed_orders'
    )
    shipped_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fulfillment_shipped_by",
    )

    estimated_pick_time_minutes = models.IntegerField(default=30)
    actual_pick_time_minutes = models.IntegerField(null=True, blank=True)

    estimated_pack_time_minutes = models.IntegerField(default=15)
    actual_pack_time_minutes = models.IntegerField(null=True, blank=True)
    shipped_at = models.DateTimeField(auto_now=True)

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['priority', 'queued_at']
        verbose_name = 'Fulfillment Queue'
        verbose_name_plural = 'Fulfillment Queues'

    def clean(self):
        super().clean()
        # ✅ Enforce exactly one of (order, b2b_order)
        if bool(self.order_id) == bool(self.b2b_order_id):
            raise ValidationError(
                "FulfillmentQueue must be linked to either Order OR B2BOrder (not both)."
            )

    # ==================== PROPERTIES ====================

    @property
    def ref_order(self):
        """Return whichever order is set (B2C or B2B)."""
        return self.order or self.b2b_order

    @property
    def ref_order_id(self):
        """Return whichever order ID is set (B2C or B2B)."""
        return self.order_id or self.b2b_order_id

    @property
    def order_type(self):
        """Return order type string."""
        return "B2B" if self.b2b_order_id else "B2C" if self.order_id else "Unknown"

    # ==================== STRING REPRESENTATION ====================

    def __str__(self):
        """String representation of fulfillment queue."""
        if self.ref_order_id:
            return f"FQ #{self.id} - {self.order_type} Order #{self.ref_order_id} - {self.status}"
        else:
            return f"FQ #{self.id} - No Order - {self.status}"

    # ==================== LIFECYCLE METHODS ====================

    def start_picking(self, user):
        """Start picking process"""
        self.status = 'PICKING'
        self.picking_started_at = timezone.now()
        self.picked_by = user
        self.save()

    def complete_picking(self):
        """Complete picking process and move to packing"""
        self.status = 'PACKING'
        self.picking_completed_at = timezone.now()

        # Calculate actual pick time
        if self.picking_started_at:
            duration = (self.picking_completed_at - self.picking_started_at).total_seconds() / 60
            self.actual_pick_time_minutes = int(duration)

        self.save()

    def start_packing(self, user):
        """Start packing process"""
        self.status = 'PACKING'
        self.packing_started_at = timezone.now()
        self.packed_by = user
        self.save()

    def complete_packing(self):
        """Complete packing process and mark as ready"""
        self.status = 'READY'
        self.packing_completed_at = timezone.now()

        # Calculate actual pack time
        if self.packing_started_at:
            duration = (self.packing_completed_at - self.packing_started_at).total_seconds() / 60
            self.actual_pack_time_minutes = int(duration)

        self.save()

    def mark_shipped(self, user):
        """Mark as shipped"""
        self.status = 'SHIPPED'
        self.shipped_at = timezone.now()
        self.shipped_by = user
        self.save()

    # ==================== HELPER METHODS ====================

    def get_total_time(self):
        """Get total time spent on picking and packing"""
        total = 0
        if self.actual_pick_time_minutes:
            total += self.actual_pick_time_minutes
        if self.actual_pack_time_minutes:
            total += self.actual_pack_time_minutes
        return total if total > 0 else None

    def is_overdue(self):
        """Check if fulfillment is taking longer than estimated"""
        if self.status in ['SHIPPED', 'CANCELLED']:
            return False

        if self.queued_at:
            elapsed = (timezone.now() - self.queued_at).total_seconds() / 60
            estimated_total = self.estimated_pick_time_minutes + self.estimated_pack_time_minutes
            return elapsed > estimated_total

        return False


class TransferItem(models.Model):
    """Individual items in a transfer"""
    transfer = models.ForeignKey(
        StoreToLogisticsTransfer,
        on_delete=models.CASCADE,
        related_name='items'
    )
    product = models.ForeignKey('marketplace.Product', on_delete=models.PROTECT)
    order_item = models.ForeignKey(
        'orders.OrderItem',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    quantity = models.PositiveIntegerField()
    stock_reservation = models.ForeignKey(
        'stock.StockReservation',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    def __str__(self):
        return f"{self.quantity}x {self.product.name}"


# ==================== B2B SHIPPING & LOGISTICS ====================

class CountryShippingConfig(models.Model):
    """
    Configuration for shipping to different countries.
    Links countries with approved shipping companies.
    """
    country_code = models.CharField(
        max_length=2,
        unique=True,
        help_text="ISO 3166-1 alpha-2 country code"
    )
    country_name = models.CharField(max_length=100)

    # Configuration
    is_active = models.BooleanField(default=True)
    requires_customs = models.BooleanField(default=False)
    estimated_delivery_days = models.IntegerField(default=7)

    # Restrictions
    max_package_weight_kg = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True
    )
    restricted_items = models.TextField(
        blank=True,
        help_text="Comma-separated list of restricted product categories"
    )

    # Metadata
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['country_name']
        verbose_name_plural = 'Country Shipping Configurations'

    def __str__(self):
        return f"{self.country_name} ({self.country_code})"

    def get_available_shipping_companies(self):
        """Get all active shipping companies for this country"""
        return self.shipping_companies.filter(is_active=True).order_by('priority')


class ShippingCompany(models.Model):
    """
    Shipping companies registered for international B2B shipping.
    """
    # Company Info
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, unique=True)
    logo = models.ImageField(upload_to='shipping/logos/', null=True, blank=True)

    # Contact
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=50)
    website = models.URLField(blank=True)

    # API Integration
    has_api_integration = models.BooleanField(default=False)
    api_endpoint = models.URLField(blank=True)
    api_key = models.CharField(max_length=255, blank=True)

    # Capabilities
    supports_tracking = models.BooleanField(default=True)
    supports_insurance = models.BooleanField(default=False)
    supports_cod = models.BooleanField(default=False)

    # Status
    is_active = models.BooleanField(default=True)

    # Service Countries
    countries = models.ManyToManyField(
        CountryShippingConfig,
        through='ShippingCompanyCountry',
        related_name='shipping_companies'
    )
    supported_modes = models.JSONField(
        default=list,
        blank=True,
        help_text="Example: ['easy_move', 'cargo', 'air_freight']. Leave empty = supports all."
    )

    # Metadata
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Shipping Companies'

    def __str__(self):
        return self.name


class ShippingCompanyCountry(models.Model):
    """
    Through model for ShippingCompany and CountryShippingConfig.
    Defines shipping rates and options per country.
    """
    shipping_company = models.ForeignKey(
        ShippingCompany,
        on_delete=models.CASCADE,
        related_name='country_configs'
    )
    country = models.ForeignKey(
        CountryShippingConfig,
        on_delete=models.CASCADE,
        related_name='company_configs'
    )

    # Pricing
    base_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Base shipping rate in USD"
    )
    per_kg_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Additional rate per kg"
    )

    # Service Level
    service_level = models.CharField(
        max_length=50,
        choices=[
            ('STANDARD', 'Standard'),
            ('EXPRESS', 'Express'),
            ('ECONOMY', 'Economy'),
        ],
        default='STANDARD'
    )
    estimated_days = models.IntegerField(default=7)

    # Priority
    priority = models.IntegerField(
        default=1,
        help_text="Lower number = higher priority (shown first)"
    )
    is_active = models.BooleanField(default=True)

    # Constraints
    min_weight_kg = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    max_weight_kg = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ['country', 'priority']
        unique_together = ['shipping_company', 'country', 'service_level']

    def __str__(self):
        return f"{self.shipping_company.name} - {self.country.country_name} ({self.service_level})"

    def calculate_cost(self, weight_kg):
        """Calculate shipping cost for given weight"""
        if self.max_weight_kg and weight_kg > float(self.max_weight_kg):
            raise ValidationError(f"Weight exceeds maximum ({self.max_weight_kg} kg)")

        if weight_kg < float(self.min_weight_kg):
            raise ValidationError(f"Weight below minimum ({self.min_weight_kg} kg)")

        cost = self.base_rate + (Decimal(str(weight_kg)) * self.per_kg_rate)
        return cost.quantize(Decimal('0.01'))


class B2BShipment(models.Model):
    """
    B2B International shipments with shipping company integration.
    """
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('SHIPPED', 'Shipped'),
        ('IN_TRANSIT', 'In Transit'),
        ('CUSTOMS', 'In Customs'),
        ('OUT_FOR_DELIVERY', 'Out for Delivery'),
        ('DELIVERED', 'Delivered'),
        ('FAILED', 'Failed'),
        ('RETURNED', 'Returned'),
    ]

    shipment_number = models.CharField(max_length=50, unique=True, editable=False)

    # Related Order
    b2b_order = models.ForeignKey(
        'stores.B2BOrder',
        on_delete=models.CASCADE,
        related_name='shipments'
    )

    # Shipping Company
    shipping_company = models.ForeignKey(
        ShippingCompany,
        on_delete=models.PROTECT,
        related_name='shipments'
    )
    company_config = models.ForeignKey(
        ShippingCompanyCountry,
        on_delete=models.PROTECT,
        related_name='shipments'
    )

    # Destination
    country = models.ForeignKey(
        CountryShippingConfig,
        on_delete=models.PROTECT,
        related_name='shipments'
    )

    # Package Details
    total_weight_kg = models.DecimalField(max_digits=8, decimal_places=2)
    package_count = models.IntegerField(default=1)
    dimensions_cm = models.CharField(
        max_length=50,
        blank=True,
        help_text="LxWxH in cm (e.g., 50x40x30)"
    )

    # Costs
    shipping_cost = models.DecimalField(max_digits=12, decimal_places=2)
    insurance_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    customs_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_cost = models.DecimalField(max_digits=12, decimal_places=2)

    # Tracking
    tracking_number = models.CharField(max_length=100, unique=True, null=True, blank=True)
    carrier_tracking_url = models.URLField(blank=True)

    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    estimated_delivery = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    # Documents
    commercial_invoice = models.FileField(
        upload_to='shipments/invoices/',
        null=True,
        blank=True
    )
    packing_list = models.FileField(
        upload_to='shipments/packing/',
        null=True,
        blank=True
    )
    customs_declaration = models.FileField(
        upload_to='shipments/customs/',
        null=True,
        blank=True
    )

    # Notes
    notes = models.TextField(blank=True)
    customs_notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.shipment_number:
            # Generate shipment number: SHP-YYYYMMDD-XXXX
            from django.db.models import Max
            today = timezone.now().date()
            prefix = f"SHP-{today.strftime('%Y%m%d')}"

            last_shipment = B2BShipment.objects.filter(
                shipment_number__startswith=prefix
            ).aggregate(Max('shipment_number'))['shipment_number__max']

            if last_shipment:
                last_num = int(last_shipment.split('-')[-1])
                new_num = last_num + 1
            else:
                new_num = 1

            self.shipment_number = f"{prefix}-{new_num:04d}"

        # Calculate total cost
        self.total_cost = self.shipping_cost + self.insurance_cost + self.customs_fee

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.shipment_number} - {self.b2b_order.id}"

    def mark_shipped(self, tracking_number, user=None):
        """Mark shipment as shipped"""
        self.status = 'SHIPPED'
        self.tracking_number = tracking_number
        self.shipped_at = timezone.now()

        # Set estimated delivery
        if self.company_config:
            self.estimated_delivery = timezone.now() + timezone.timedelta(
                days=self.company_config.estimated_days
            )

        self.save()

        # Update B2B order
        self.b2b_order.status = 'processing'
        self.b2b_order.save()


class ShipmentTracking(models.Model):
    """
    Tracking history for B2B shipments.
    """
    shipment = models.ForeignKey(
        B2BShipment,
        on_delete=models.CASCADE,
        related_name='tracking_history'
    )

    status = models.CharField(max_length=50)
    location = models.CharField(max_length=200, blank=True)
    description = models.TextField()

    timestamp = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.shipment.shipment_number} - {self.status} at {self.timestamp}"
