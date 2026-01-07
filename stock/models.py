from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta


class Warehouse(models.Model):
    """Physical warehouse locations for stock storage"""
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, unique=True)
    address = models.TextField()
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)
    capacity = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)

    # Geocode fields
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True,
                                   help_text="Latitude coordinate")
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True,
                                    help_text="Longitude coordinate")

    manager = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                related_name='stock_warehouses_managed')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.code})"

    @property
    def full_address(self):
        """Get formatted full address"""
        parts = [self.address]
        if self.city:
            parts.append(self.city)
        if self.state:
            parts.append(self.state)
        if self.postal_code:
            parts.append(self.postal_code)
        if self.country:
            parts.append(self.country)
        return ', '.join(parts)

    @property
    def has_geocode(self):
        """Check if warehouse has geocode coordinates"""
        return self.latitude is not None and self.longitude is not None

    def get_coordinates(self):
        """Get latitude and longitude as tuple"""
        if self.has_geocode:
            return (float(self.latitude), float(self.longitude))
        return None


class Stock(models.Model):
    """Current stock levels for products across warehouses"""
    product = models.ForeignKey('marketplace.Product', on_delete=models.CASCADE, related_name='stock_records')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='stock_items')
    quantity = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)])
    reserved_quantity = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)])
    reorder_level = models.PositiveIntegerField(default=10, help_text="Minimum quantity before reorder")
    reorder_quantity = models.PositiveIntegerField(default=50, help_text="Quantity to reorder")
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    updated_at = models.DateTimeField(auto_now=True)
    last_counted = models.DateTimeField(null=True, blank=True, help_text="Last physical count date")

    class Meta:
        unique_together = ['product', 'warehouse']
        ordering = ['product', 'warehouse']
        indexes = [
            models.Index(fields=['product', 'warehouse']),
            models.Index(fields=['quantity']),
        ]

    @property
    def available_quantity(self):
        """Quantity available for sale (total - reserved)"""
        return max(0, self.quantity - self.reserved_quantity)

    @property
    def is_below_reorder_level(self):
        """Check if stock needs reordering"""
        return self.quantity <= self.reorder_level

    @property
    def stock_value(self):
        """Total value of stock at unit cost"""
        return Decimal(self.quantity) * self.unit_cost

    def __str__(self):
        warehouse_code = self.warehouse.code if self.warehouse else "No Warehouse"
        product_name = self.product.name if self.product else "Unknown Product"
        return f"{product_name} @ {warehouse_code} - {self.quantity} units"


class StockMovement(models.Model):
    """Track all stock movements for audit trail and reporting"""

    MOVEMENT_TYPES = [
        ('PURCHASE', 'Purchase/Receiving'),
        ('SALE', 'Sale/Dispatch'),
        ('RETURN_IN', 'Customer Return'),
        ('RETURN_OUT', 'Return to Supplier'),
        ('TRANSFER', 'Warehouse Transfer'),
        ('ADJUSTMENT', 'Stock Adjustment'),
        ('DAMAGE', 'Damaged Goods'),
        ('LOSS', 'Lost/Stolen'),
        ('PRODUCTION', 'Production Usage'),
        ('ASSEMBLY', 'Assembly/Manufacturing'),
    ]

    product = models.ForeignKey('marketplace.Product', on_delete=models.CASCADE, related_name='movements')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='movements')
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPES)
    quantity = models.IntegerField(help_text="Positive for increase, negative for decrease")
    reference_number = models.CharField(max_length=100, blank=True, help_text="PO, SO, or other reference")
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                   related_name='stock_movements')
    created_at = models.DateTimeField(auto_now_add=True)

    # For transfers
    destination_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='incoming_transfers'
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['product', '-created_at']),
            models.Index(fields=['warehouse', '-created_at']),
            models.Index(fields=['movement_type', '-created_at']),
            models.Index(fields=['reference_number']),
        ]

    @property
    def total_value(self):
        """Total value of this movement"""
        return abs(Decimal(self.quantity)) * self.unit_cost

    def __str__(self):
        product_name = self.product.name if self.product else "Unknown Product"
        direction = "+" if self.quantity > 0 else ""
        return f"{product_name} - {self.movement_type}: {direction}{self.quantity} units"


class StockCount(models.Model):
    """Physical stock count sessions for inventory reconciliation"""

    STATUS_CHOICES = [
        ('PLANNED', 'Planned'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ]

    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='stock_counts')
    count_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PLANNED')
    counted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                   related_name='conducted_counts')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-count_date']

    def __str__(self):
        warehouse_code = self.warehouse.code if self.warehouse else "No Warehouse"
        return f"Stock Count - {warehouse_code} on {self.count_date} ({self.status})"


class StockCountItem(models.Model):
    """Individual product counts within a stock count session"""
    stock_count = models.ForeignKey(StockCount, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('marketplace.Product', on_delete=models.CASCADE)
    expected_quantity = models.PositiveIntegerField()
    counted_quantity = models.PositiveIntegerField()
    variance = models.IntegerField(default=0)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = ['stock_count', 'product']

    def save(self, *args, **kwargs):
        """Auto-calculate variance"""
        self.variance = self.counted_quantity - self.expected_quantity
        super().save(*args, **kwargs)

    @property
    def variance_percentage(self):
        """Calculate variance as percentage"""
        if self.expected_quantity == 0:
            return 0
        return (self.variance / self.expected_quantity) * 100

    def __str__(self):
        product_name = self.product.name if self.product else "Unknown Product"
        return f"{product_name}: Expected {self.expected_quantity}, Counted {self.counted_quantity}"


class StockAlert(models.Model):
    """Automated alerts for stock issues"""

    ALERT_TYPES = [
        ('LOW_STOCK', 'Low Stock Level'),
        ('OUT_OF_STOCK', 'Out of Stock'),
        ('OVERSTOCK', 'Overstock'),
        ('EXPIRING_SOON', 'Expiring Soon'),
        ('NEGATIVE_STOCK', 'Negative Stock Error'),
    ]

    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('ACKNOWLEDGED', 'Acknowledged'),
        ('RESOLVED', 'Resolved'),
        ('IGNORED', 'Ignored'),
    ]

    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='alerts')
    alert_type = models.CharField(max_length=20, choices=ALERT_TYPES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['alert_type', 'status']),
        ]

    def __str__(self):
        product_name = self.stock.product.name if (self.stock and self.stock.product) else "Unknown Product"
        return f"{self.get_alert_type_display()} - {product_name} ({self.status})"


class StockReservation(models.Model):
    """Reserve stock for orders before actual dispatch"""
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='reservations')
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    order_reference = models.CharField(max_length=100)
    reserved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    reserved_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(help_text="Reservation expiry time")
    is_active = models.BooleanField(default=True)
    fulfilled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-reserved_at']
        indexes = [
            models.Index(fields=['order_reference']),
            models.Index(fields=['is_active', 'expires_at']),
        ]

    @property
    def is_expired(self):
        """Check if reservation has expired"""
        return timezone.now() > self.expires_at and not self.fulfilled_at

    def __str__(self):
        product_name = self.stock.product.name if (self.stock and self.stock.product) else "Unknown Product"
        return f"Reserved {self.quantity} x {product_name} for {self.order_reference}"


class BatchTracking(models.Model):
    """Track product batches/lots for traceability"""
    product = models.ForeignKey('marketplace.Product', on_delete=models.CASCADE, related_name='batches')
    batch_number = models.CharField(max_length=100)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='batches')
    quantity = models.PositiveIntegerField(default=0)
    manufacturing_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    supplier_reference = models.CharField(max_length=100, blank=True)
    received_date = models.DateField(auto_now_add=True)

    class Meta:
        unique_together = ['product', 'batch_number', 'warehouse']
        ordering = ['expiry_date', 'batch_number']
        verbose_name_plural = 'Batch Tracking'

    @property
    def is_expired(self):
        """Check if batch has expired"""
        if self.expiry_date:
            return timezone.now().date() > self.expiry_date
        return False

    @property
    def days_until_expiry(self):
        """Days until expiry"""
        if self.expiry_date:
            delta = self.expiry_date - timezone.now().date()
            return delta.days
        return None

    def __str__(self):
        product_name = self.product.name if self.product else "Unknown Product"
        return f"Batch {self.batch_number} - {product_name}"


class StockAnalytics(models.Model):
    """Daily aggregated analytics for reporting"""
    product = models.ForeignKey('marketplace.Product', on_delete=models.CASCADE, related_name='analytics')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='analytics')
    date = models.DateField()

    # Quantity metrics
    opening_stock = models.IntegerField(default=0)
    closing_stock = models.IntegerField(default=0)
    total_received = models.IntegerField(default=0)
    total_sold = models.IntegerField(default=0)
    total_adjusted = models.IntegerField(default=0)

    # Financial metrics
    total_purchase_value = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_sales_value = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    average_unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    # Velocity metrics
    turnover_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0.00, help_text="Daily turnover rate")
    days_of_stock = models.IntegerField(default=0, help_text="Days until stockout at current rate")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['product', 'warehouse', 'date']
        ordering = ['-date', 'product', 'warehouse']
        indexes = [
            models.Index(fields=['date', 'product']),
            models.Index(fields=['date', 'warehouse']),
        ]
        verbose_name_plural = 'Stock Analytics'

    def __str__(self):
        product_name = self.product.name if self.product else "Unknown Product"
        warehouse_code = self.warehouse.code if self.warehouse else "No Warehouse"
        return f"{product_name} @ {warehouse_code} - {self.date}"


class Supplier(models.Model):
    """Supplier information for purchase order management"""
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, unique=True)
    contact_person = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    payment_terms = models.CharField(max_length=100, blank=True, help_text="e.g., Net 30")
    is_active = models.BooleanField(default=True)
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=0.00,
                                 validators=[MinValueValidator(0), MinValueValidator(5)])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.code})"


class PurchaseOrder(models.Model):
    """Purchase orders for stock replenishment"""

    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('SUBMITTED', 'Submitted'),
        ('APPROVED', 'Approved'),
        ('SENT', 'Sent to Supplier'),
        ('PARTIALLY_RECEIVED', 'Partially Received'),
        ('RECEIVED', 'Fully Received'),
        ('CANCELLED', 'Cancelled'),
    ]

    po_number = models.CharField(max_length=50, unique=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='purchase_orders')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, blank=True, null=True, related_name='purchase_orders')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    order_date = models.DateField()
    expected_delivery_date = models.DateField(null=True, blank=True)
    actual_delivery_date = models.DateField(null=True, blank=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                   related_name='created_pos')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-order_date', '-po_number']
        indexes = [
            models.Index(fields=['po_number']),
            models.Index(fields=['status', '-order_date']),
        ]

    def __str__(self):
        supplier_name = self.supplier.name if self.supplier else "Unknown Supplier"
        return f"PO {self.po_number} - {supplier_name} ({self.status})"


class PurchaseOrderItem(models.Model):
    """Line items in purchase orders"""
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('marketplace.Product', on_delete=models.PROTECT)
    quantity_ordered = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    quantity_received = models.PositiveIntegerField(default=0)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        unique_together = ['purchase_order', 'product']

    @property
    def quantity_pending(self):
        """Quantity still to be received"""
        return self.quantity_ordered - self.quantity_received

    @property
    def line_total(self):
        """Total cost for this line item"""
        return Decimal(self.quantity_ordered) * self.unit_price

    @property
    def is_fully_received(self):
        """Check if item is fully received"""
        return self.quantity_received >= self.quantity_ordered

    def __str__(self):
        product_name = self.product.name if self.product else "Unknown Product"
        return f"{product_name} - {self.quantity_ordered} units @ ${self.unit_price}"