"""
Supply Chain Models - Store to Logistics Warehouse Flow

This module handles the flow of products from store warehouses to EasyMarket
logistics warehouses, and finally to customers.

Flow:
1. Customer places order
2. Stock reserved at Store Warehouse
3. Stock transferred to Logistics Warehouse
4. Shipment created and dispatched to customer
"""

from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models import Sum, Avg, F, Q, Count
from decimal import Decimal


class StoreToLogisticsTransfer(models.Model):
    """
    Tracks product transfers from store warehouses to logistics warehouses.

    This is the critical link between retail inventory and fulfillment operations.
    """

    STATUS_CHOICES = [
        ('PENDING', 'Pending Pickup'),
        ('IN_TRANSIT', 'In Transit to Logistics'),
        ('RECEIVED', 'Received at Logistics'),
        ('CANCELLED', 'Cancelled'),
        ('REJECTED', 'Rejected'),
    ]

    transfer_number = models.CharField(
        max_length=50,
        unique=True,
        help_text="Unique transfer identifier"
    )

    # Source and destination
    store_warehouse = models.ForeignKey(
        'stock.Warehouse',
        on_delete=models.PROTECT,
        related_name='outbound_transfers',
        help_text="Store warehouse (source)"
    )

    logistics_warehouse = models.ForeignKey(
        'logistics.Warehouse',
        on_delete=models.PROTECT,
        related_name='inbound_transfers',
        help_text="EasyMarket logistics warehouse (destination)"
    )

    # Order reference
    order = models.ForeignKey(
        'orders.Order',
        on_delete=models.CASCADE,
        related_name='warehouse_transfers',
        null=True,
        blank=True,
        help_text="Associated customer order"
    )

    # Status and tracking
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDING'
    )

    # Dates
    requested_at = models.DateTimeField(auto_now_add=True)
    pickup_scheduled = models.DateTimeField(null=True, blank=True)
    picked_up_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)

    # Personnel
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='requested_transfers'
    )

    picked_up_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pickup_transfers'
    )

    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='received_transfers'
    )

    # Logistics
    vehicle = models.ForeignKey(
        'logistics.Vehicle',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='warehouse_transfers'
    )

    driver = models.ForeignKey(
        'logistics.Driver',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='warehouse_transfers'
    )

    # Notes
    notes = models.TextField(blank=True)
    rejection_reason = models.TextField(blank=True)

    # Tracking
    estimated_duration_minutes = models.PositiveIntegerField(
        default=60,
        help_text="Estimated transfer duration in minutes"
    )

    actual_duration_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Actual transfer duration in minutes"
    )

    class Meta:
        ordering = ['-requested_at']
        indexes = [
            models.Index(fields=['transfer_number']),
            models.Index(fields=['status', '-requested_at']),
            models.Index(fields=['order']),
            models.Index(fields=['store_warehouse', 'status']),
            models.Index(fields=['logistics_warehouse', 'status']),
        ]

    def __str__(self):
        return f"Transfer {self.transfer_number}: {self.store_warehouse.code} → {self.logistics_warehouse.code}"

    def save(self, *args, **kwargs):
        if not self.transfer_number:
            self.transfer_number = self._generate_transfer_number()
        super().save(*args, **kwargs)

    def _generate_transfer_number(self):
        """Generate unique transfer number"""
        import uuid
        timestamp = int(timezone.now().timestamp())
        unique = str(uuid.uuid4().hex[:6]).upper()
        return f"TRF{timestamp}{unique}"

    @property
    def is_complete(self):
        return self.status == 'RECEIVED'

    @property
    def is_in_progress(self):
        return self.status in ['PENDING', 'IN_TRANSIT']

    def mark_picked_up(self, user, vehicle=None, driver=None):
        """Mark transfer as picked up from store"""
        if self.status != 'PENDING':
            raise ValidationError("Transfer must be in PENDING status")

        self.status = 'IN_TRANSIT'
        self.picked_up_at = timezone.now()
        self.picked_up_by = user

        if vehicle:
            self.vehicle = vehicle
        if driver:
            self.driver = driver

        self.save()

    def mark_received(self, user):
        """Mark transfer as received at logistics warehouse"""
        if self.status != 'IN_TRANSIT':
            raise ValidationError("Transfer must be in IN_TRANSIT status")

        self.status = 'RECEIVED'
        self.received_at = timezone.now()
        self.received_by = user

        # Calculate actual duration
        if self.picked_up_at:
            delta = self.received_at - self.picked_up_at
            self.actual_duration_minutes = int(delta.total_seconds() / 60)

        self.save()

        # Move stock from store warehouse to logistics warehouse
        self._execute_stock_transfer()

    def _execute_stock_transfer(self):
        """Execute the actual stock transfer"""
        from stock.utils import adjust_stock

        for item in self.items.all():
            # Reduce from store warehouse
            adjust_stock(
                product=item.product,
                warehouse=self.store_warehouse,
                quantity=-item.quantity,
                movement_type='TRANSFER',
                reference_number=self.transfer_number,
                notes=f'Transfer to logistics: {self.logistics_warehouse.code}'
            )

            # We don't add to logistics warehouse stock because it uses a different system
            # Instead, we just track that it's available for shipment
            item.transferred = True
            item.transferred_at = timezone.now()
            item.save()

    def cancel(self, reason):
        """Cancel the transfer"""
        if self.status in ['RECEIVED', 'CANCELLED']:
            raise ValidationError("Cannot cancel completed or already cancelled transfer")

        self.status = 'CANCELLED'
        self.rejection_reason = reason
        self.save()

        # Release stock reservations
        for item in self.items.all():
            from stock.utils import release_reservation
            if hasattr(item, 'stock_reservation') and item.stock_reservation:
                release_reservation(item.stock_reservation)


class TransferItem(models.Model):
    """Individual products in a store-to-logistics transfer"""

    transfer = models.ForeignKey(
        StoreToLogisticsTransfer,
        on_delete=models.CASCADE,
        related_name='items'
    )

    product = models.ForeignKey(
        'marketplace.Product',
        on_delete=models.PROTECT
    )

    order_item = models.ForeignKey(
        'orders.OrderItem',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Corresponding order item"
    )

    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    # Stock tracking
    stock_reservation = models.ForeignKey(
        'stock.StockReservation',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Stock reservation at store warehouse"
    )

    transferred = models.BooleanField(
        default=False,
        help_text="Has been transferred to logistics warehouse"
    )

    transferred_at = models.DateTimeField(null=True, blank=True)

    # Condition tracking
    condition_notes = models.TextField(
        blank=True,
        help_text="Notes about product condition during transfer"
    )

    damaged = models.BooleanField(default=False)
    damage_notes = models.TextField(blank=True)

    class Meta:
        ordering = ['transfer', 'product']
        unique_together = [['transfer', 'product']]

    def __str__(self):
        return f"{self.quantity}x {self.product.name} - {self.transfer.transfer_number}"


class FulfillmentQueue(models.Model):
    """
    Queue of orders ready for fulfillment at logistics warehouse.

    Orders enter this queue after stock transfer is received.
    """

    PRIORITY_CHOICES = [
        ('LOW', 'Low Priority'),
        ('NORMAL', 'Normal Priority'),
        ('HIGH', 'High Priority'),
        ('URGENT', 'Urgent'),
    ]

    STATUS_CHOICES = [
        ('QUEUED', 'In Queue'),
        ('PICKING', 'Being Picked'),
        ('PACKING', 'Being Packed'),
        ('READY', 'Ready for Shipment'),
        ('SHIPPED', 'Shipped'),
        ('CANCELLED', 'Cancelled'),
    ]

    order = models.OneToOneField(
        'orders.Order',
        on_delete=models.CASCADE,
        related_name='fulfillment_queue'
    )

    logistics_warehouse = models.ForeignKey(
        'logistics.Warehouse',
        on_delete=models.PROTECT,
        related_name='fulfillment_queue'
    )

    transfer = models.ForeignKey(
        StoreToLogisticsTransfer,
        on_delete=models.SET_NULL,
        null=True,
        related_name='fulfillment_entries'
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='QUEUED'
    )

    priority = models.CharField(
        max_length=10,
        choices=PRIORITY_CHOICES,
        default='NORMAL'
    )

    # Dates
    queued_at = models.DateTimeField(auto_now_add=True)
    picking_started_at = models.DateTimeField(null=True, blank=True)
    packing_started_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)

    # Personnel
    picker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='picked_orders'
    )

    packer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='packed_orders'
    )

    # Metrics
    estimated_pick_time_minutes = models.PositiveIntegerField(default=15)
    actual_pick_time_minutes = models.PositiveIntegerField(null=True, blank=True)
    estimated_pack_time_minutes = models.PositiveIntegerField(default=10)
    actual_pack_time_minutes = models.PositiveIntegerField(null=True, blank=True)

    # Shipment
    shipment = models.ForeignKey(
        'logistics.Shipment',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='fulfillment_entries'
    )

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-priority', 'queued_at']
        indexes = [
            models.Index(fields=['status', '-priority', 'queued_at']),
            models.Index(fields=['logistics_warehouse', 'status']),
        ]

    def __str__(self):
        return f"Fulfillment: Order #{self.order.id} - {self.status}"

    def start_picking(self, picker):
        """Start picking process"""
        if self.status != 'QUEUED':
            raise ValidationError("Can only start picking from QUEUED status")

        self.status = 'PICKING'
        self.picking_started_at = timezone.now()
        self.picker = picker
        self.save()

    def start_packing(self, packer):
        """Start packing process"""
        if self.status != 'PICKING':
            raise ValidationError("Must complete picking before packing")

        # Calculate pick time
        if self.picking_started_at:
            delta = timezone.now() - self.picking_started_at
            self.actual_pick_time_minutes = int(delta.total_seconds() / 60)

        self.status = 'PACKING'
        self.packing_started_at = timezone.now()
        self.packer = packer
        self.save()

    def mark_ready(self):
        """Mark as ready for shipment"""
        if self.status != 'PACKING':
            raise ValidationError("Must complete packing before marking ready")

        # Calculate pack time
        if self.packing_started_at:
            delta = timezone.now() - self.packing_started_at
            self.actual_pack_time_minutes = int(delta.total_seconds() / 60)

        self.status = 'READY'
        self.ready_at = timezone.now()
        self.save()

    def mark_shipped(self, shipment):
        """Mark as shipped"""
        if self.status != 'READY':
            raise ValidationError("Order must be ready before shipping")

        self.status = 'SHIPPED'
        self.shipped_at = timezone.now()
        self.shipment = shipment
        self.save()

    @property
    def total_fulfillment_time(self):
        """Total time from queue to shipped"""
        if self.shipped_at:
            delta = self.shipped_at - self.queued_at
            return int(delta.total_seconds() / 60)
        return None

    @property
    def is_overdue(self):
        """Check if fulfillment is taking too long"""
        if self.status in ['SHIPPED', 'CANCELLED']:
            return False

        total_estimated = self.estimated_pick_time_minutes + self.estimated_pack_time_minutes
        elapsed = (timezone.now() - self.queued_at).total_seconds() / 60

        return elapsed > total_estimated * 1.5  # 50% buffer


class WarehouseLinkage(models.Model):
    """
    Links store warehouses to logistics warehouses.

    Defines which logistics warehouse serves which store warehouses
    for optimal routing and efficiency.
    """

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

    is_primary = models.BooleanField(
        default=True,
        help_text="Is this the primary logistics warehouse for this store?"
    )

    is_active = models.BooleanField(default=True)

    # Distance and logistics
    distance_km = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Distance between warehouses"
    )

    estimated_transfer_time_minutes = models.PositiveIntegerField(
        default=60,
        help_text="Estimated transfer time"
    )

    # Capacity management
    max_daily_transfers = models.PositiveIntegerField(
        default=10,
        help_text="Maximum transfers per day from this store"
    )

    # Created/updated
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['store_warehouse', 'logistics_warehouse']]
        ordering = ['store_warehouse', '-is_primary']
        indexes = [
            models.Index(fields=['store_warehouse', 'is_primary', 'is_active']),
        ]

    def __str__(self):
        primary = " (Primary)" if self.is_primary else ""
        return f"{self.store_warehouse.code} → {self.logistics_warehouse.code}{primary}"

    def get_todays_transfer_count(self):
        """Get number of transfers today"""
        today = timezone.now().date()
        return StoreToLogisticsTransfer.objects.filter(
            store_warehouse=self.store_warehouse,
            logistics_warehouse=self.logistics_warehouse,
            requested_at__date=today
        ).count()

    def can_accept_transfer(self):
        """Check if can accept another transfer today"""
        return self.get_todays_transfer_count() < self.max_daily_transfers

    @classmethod
    def get_optimal_logistics_warehouse(cls, store_warehouse):
        """Get the optimal logistics warehouse for a store"""
        linkage = cls.objects.filter(
            store_warehouse=store_warehouse,
            is_active=True,
            is_primary=True
        ).first()

        if linkage and linkage.can_accept_transfer():
            return linkage.logistics_warehouse

        # Fall back to secondary if primary is at capacity
        secondary = cls.objects.filter(
            store_warehouse=store_warehouse,
            is_active=True,
            is_primary=False
        ).order_by('distance_km').first()

        if secondary and secondary.can_accept_transfer():
            return secondary.logistics_warehouse

        return None