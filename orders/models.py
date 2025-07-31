from django.db import models
from django.contrib.auth.models import User
from django.conf import settings
from django.utils import timezone
from decimal import Decimal
import uuid
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models import Sum

class PromoCode(models.Model):
    code = models.CharField(max_length=50, unique=True)
    discount_percentage = models.PositiveIntegerField(help_text="Percentage discount, e.g., 10 for 10%")
    influencer = models.ForeignKey(
        'marketplace.CelebrityFeature',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='promo_codes'
    )
    products = models.ManyToManyField('marketplace.Product', blank=True, related_name='promo_codes')
    is_active = models.BooleanField(default=True)
    usage_limit = models.PositiveIntegerField(default=0, help_text="0 means unlimited")
    usage_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        scope = f"{self.influencer.celebrity_name}" if self.influencer else "General"
        return f"{self.code} - {self.discount_percentage}% ({scope})"

    def is_valid(self):
        if not self.is_active:
            return False
        if self.usage_limit > 0 and self.usage_count >= self.usage_limit:
            return False
        return True

    def increment_usage(self):
        if self.usage_limit == 0 or self.usage_count < self.usage_limit:
            self.usage_count += 1
            self.save()

    def applies_to_product(self, product):
        """
        Return True if promo code applies to this product.
        If no products are tied, it's considered global.
        """
        return self.products.count() == 0 or self.products.filter(id=product.id).exists()



class Order(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('shipped', 'Shipped'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
    ]

    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='orders')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Payment information
    # payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, blank=True, null=True)
    payment_date = models.DateTimeField(blank=True, null=True)

    # Financial fields
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.0'))  # 8.5% default tax
    shipping_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    promo_code = models.ForeignKey(PromoCode, on_delete=models.SET_NULL, null=True, blank=True)

    # Delivery information
    expected_delivery_date = models.DateField(blank=True, null=True)
    shipped_date = models.DateTimeField(blank=True, null=True)
    delivered_date = models.DateTimeField(blank=True, null=True)
    tracking_number = models.CharField(max_length=100, blank=True, null=True)

    # Address information
    shipping_address = models.ForeignKey('ShippingAddress', on_delete=models.SET_NULL, blank=True, null=True)

    # Notes
    order_notes = models.TextField(blank=True, null=True)
    admin_notes = models.TextField(blank=True, null=True)

    source_type = models.CharField(
        max_length=20,
        choices=[
            ('marketplace', 'Marketplace'),
            ('auction', 'Auction'),
        ],
        default='marketplace'
    )

    store_referral = models.ForeignKey('stores.StoreReferral', null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Order #{self.id} - {self.buyer.username}"

    def get_subtotal(self):
        """Calculate the subtotal (sum of all items)"""
        return sum(item.get_total_price() for item in self.items.all())

    def get_tax_amount(self):
        """Calculate tax amount based on subtotal"""
        return self.get_subtotal() * (self.tax_rate / 100)

    @property
    def is_auction_order(self):
        return self.source_type == 'auction'

    @property
    def get_total(self):
        """Calculate the final total including tax and shipping"""
        subtotal = Decimal(self.get_subtotal() or 0)
        tax = Decimal(self.get_tax_amount() or 0)
        shipping = Decimal(self.shipping_cost or 0)
        discount = Decimal(self.discount_amount or 0)

        total = subtotal + tax + shipping - discount
        return total.quantize(Decimal("0.01"))

    def get_item_count(self):
        """Get total number of items in the order"""
        return sum(item.quantity for item in self.items.all())

    def can_be_cancelled(self):
        """Check if order can be cancelled"""
        return self.status in ['pending', 'processing']

    def can_be_tracked(self):
        """Check if order can be tracked based on status or related shipment"""
        return (
                self.status in ['shipped', 'delivered'] or
                self.shipments.filter(status='in_transit').exists()
        ) and self.tracking_number

    def is_completed(self):
        """Check if order is completed"""
        return self.status == 'delivered'

    # In your Order model
    def get_subtotal_with_tax_and_shipping(self):
        """Get subtotal + tax + shipping (before promo discount)"""
        subtotal = self.get_subtotal()
        tax = self.get_tax_amount()
        shipping = self.shipping_cost or Decimal('0')
        return subtotal + tax + shipping

    def get_payment_method_display(self):
        """
        Retrieve a human-readable payment method name from the related Payment model
        """
        if hasattr(self, 'payment_record') and self.payment_record.method:
            method_map = {
                'wave': 'Wave',
                'qmoney': 'Qmoney',
                'afrimoney': 'Afrimoney',
                'cash': 'Cash Payment',
                'verve_card': 'Verve Card',
            }
            return method_map.get(self.payment_record.method, 'Unknown')
        return 'Not specified'

    def mark_as_shipped(self):
        """Mark the order as shipped and set shipped_date if not already set."""
        self.status = 'shipped'
        if not self.collect_time:
            self.collect_time = timezone.now()
        self.save()

    @property
    def is_in_transit(self):
        return self.shipments.filter(status='in_transit').exists()

    def save(self, *args, **kwargs):
        # Auto-set dates based on status changes
        if self.pk:  # Only for existing orders
            old_order = Order.objects.get(pk=self.pk)
            if old_order.status != self.status:
                if self.status == 'shipped' and not self.collect_time:
                    self.collect_time = timezone.now()
                elif self.status == 'delivered' and not self.delivered_date:
                    self.delivered_date = timezone.now()

        super().save(*args, **kwargs)


class OrderItem(models.Model):
    order = models.ForeignKey('orders.Order', on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('marketplace.Product', related_name='order_items', on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    selected_features = models.JSONField(blank=True, null=True)
    price_at_time = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)

    # NEW: per-item discount
    DISCOUNT_NONE = 'none'
    DISCOUNT_PERCENT = 'percent'
    DISCOUNT_AMOUNT = 'amount'
    DISCOUNT_CHOICES = [
        (DISCOUNT_NONE, 'None'),
        (DISCOUNT_PERCENT, 'Percent'),
        (DISCOUNT_AMOUNT, 'Amount'),
    ]
    discount_type = models.CharField(max_length=10, choices=DISCOUNT_CHOICES, default=DISCOUNT_NONE)
    discount_value = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    shipped_to_warehouse = models.BooleanField(default=False)
    shipped_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['order', 'product']  # NOTE: If you ever need same product twice (different features/discounts),
                                                # remove this, or include features in uniqueness.

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"

    # ---- Pricing helpers ----
    @property
    def base_unit_price(self) -> Decimal:
        # Always work with a Decimal
        p = self.price_at_time if self.price_at_time is not None else self.product.price
        return (p if isinstance(p, Decimal) else Decimal(str(p))).quantize(Decimal('0.01'), ROUND_HALF_UP)

    def get_unit_discount_amount(self) -> Decimal:
        if self.discount_type == self.DISCOUNT_PERCENT:
            pct = max(Decimal('0'), min(Decimal('100'), self.discount_value or Decimal('0')))
            return (self.base_unit_price * pct / Decimal('100')).quantize(Decimal('0.01'), ROUND_HALF_UP)
        elif self.discount_type == self.DISCOUNT_AMOUNT:
            amt = max(Decimal('0.00'), self.discount_value or Decimal('0.00'))
            # Never allow discount > base price
            return min(amt, self.base_unit_price).quantize(Decimal('0.01'), ROUND_HALF_UP)
        return Decimal('0.00')

    @property
    def discounted_unit_price(self) -> Decimal:
        return (self.base_unit_price - self.get_unit_discount_amount()).quantize(Decimal('0.01'), ROUND_HALF_UP)

    def get_total_price(self) -> Decimal:
        return (self.discounted_unit_price * self.quantity).quantize(Decimal('0.01'), ROUND_HALF_UP)

    # ---- Validation & defaults ----
    def clean(self):
        # Basic validation for discount values
        if self.discount_type == self.DISCOUNT_PERCENT:
            if self.discount_value is None:
                raise ValidationError({'discount_value': 'Percent discount is required.'})
            if self.discount_value < 0 or self.discount_value > 100:
                raise ValidationError({'discount_value': 'Percent must be between 0 and 100.'})
        elif self.discount_type == self.DISCOUNT_AMOUNT:
            if self.discount_value is None:
                raise ValidationError({'discount_value': 'Amount discount is required.'})
            if self.discount_value < 0:
                raise ValidationError({'discount_value': 'Amount cannot be negative.'})

        # Ensure discounted price not below zero
        if self.discounted_unit_price < 0:
            raise ValidationError('Discounted unit price cannot be negative.')

    def save(self, *args, **kwargs):
        # lock in snapshot price if missing
        if self.price_at_time is None:
            self.price_at_time = self.product.price
        # run validations (optional but recommended)
        self.full_clean()
        super().save(*args, **kwargs)

class ShippingAddress(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='shipping_addresses')
    full_name = models.CharField(max_length=100)
    street = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    region = models.CharField(max_length=100)
    geo_code = models.CharField(max_length=20)
    country = models.CharField(max_length=100, default='Gambia')
    phone_number = models.CharField(max_length=20)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Shipping Address'
        verbose_name_plural = 'Shipping Addresses'

    def __str__(self):
        return f"{self.full_name} - {self.street}, {self.city}"

    def save(self, *args, **kwargs):
        # Ensure only one default address per user
        if self.is_default:
            ShippingAddress.objects.filter(
                user=self.user, is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


class OrderStatusHistory(models.Model):
    """Track status changes for orders"""
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='status_history')
    status = models.CharField(max_length=20, choices=Order.STATUS_CHOICES)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Order Status History'
        verbose_name_plural = 'Order Status Histories'

    def update_status(self, new_status, changed_by=None, notes=''):
        """Safely update order status and log history."""
        if self.status != new_status:
            self.status = new_status
            self.save()

            OrderStatusHistory.objects.create(
                order=self,
                status=new_status,
                changed_by=changed_by,
                notes=notes
            )

    def __str__(self):
        return f"Order #{self.order.id} - {self.get_status_display()} at {self.timestamp}"

def q2(val) -> Decimal:
    """Quantize to 2dp Decimal safely."""
    if val is None:
        val = Decimal('0')
    if not isinstance(val, Decimal):
        val = Decimal(str(val))
    return val.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


class Return(models.Model):
    """Main return model that handles product returns"""

    RETURN_STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('approved', 'Approved - Awaiting Pickup'),
        ('rejected', 'Rejected'),
        ('in_transit', 'In Transit to Store'),
        ('received', 'Received by Store'),
        ('completed', 'Completed - Refund Processed'),
        ('cancelled', 'Cancelled'),
    ]

    RETURN_REASON_CHOICES = [
        ('defective', 'Product Defective'),
        ('wrong_item', 'Wrong Item Received'),
        ('wrong_size', 'Wrong Size'),
        ('damaged_shipping', 'Damaged During Shipping'),
        ('not_as_described', 'Not as Described'),
        ('changed_mind', 'Changed Mind'),
        ('quality_issues', 'Quality Issues'),
        ('other', 'Other'),
    ]

    LOGISTICS_METHOD_CHOICES = [
        ('easymarket_pickup', 'EasyMarket Pickup'),
        ('buyer_dropoff', 'Buyer Drop-off'),
        ('courier_service', 'Courier Service'),
    ]

    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    return_number = models.CharField(max_length=20, unique=True, editable=False)
    order = models.ForeignKey('orders.Order', on_delete=models.CASCADE, related_name='returns')
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='returns')

    # Return Details
    status = models.CharField(max_length=20, choices=RETURN_STATUS_CHOICES, default='pending')
    reason = models.CharField(max_length=20, choices=RETURN_REASON_CHOICES)
    # Make description optional in case buyer just selects a reason.
    reason_description = models.TextField(blank=True, default="", help_text="Detailed explanation for the return")

    # Financial Information
    total_return_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    # If you use this as restocking fee or manual adjustment, keep it positive; it will be subtracted.
    discount_applied = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'),
                                           validators=[MinValueValidator(Decimal('0'))])
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    # Logistics Information
    logistics_method = models.CharField(max_length=20, choices=LOGISTICS_METHOD_CHOICES, default='easymarket_pickup')
    tracking_number = models.CharField(max_length=100, blank=True, null=True)
    estimated_pickup_date = models.DateField(blank=True, null=True)
    actual_pickup_date = models.DateTimeField(blank=True, null=True)
    received_at_store_date = models.DateTimeField(blank=True, null=True)

    # Approval/Processing Information
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_returns'
    )
    approved_at = models.DateTimeField(blank=True, null=True)
    rejection_reason = models.TextField(blank=True, null=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    # Additional Notes
    buyer_notes = models.TextField(blank=True, null=True)
    admin_notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Return'
        verbose_name_plural = 'Returns'

    def __str__(self):
        return f"Return {self.return_number} - Order #{self.order.id}"

    # ---- Lifecycle helpers ----

    def save(self, *args, **kwargs):
        # Generate return number if not exists
        if not self.return_number:
            self.return_number = self.generate_return_number()

        # Track status transitions to set timestamps
        if self.pk:
            old = Return.objects.filter(pk=self.pk).only('status', 'approved_at', 'completed_at', 'received_at_store_date').first()
            if old and old.status != self.status:
                if self.status == 'approved' and not self.approved_at:
                    self.approved_at = timezone.now()
                elif self.status == 'completed' and not self.completed_at:
                    self.completed_at = timezone.now()
                elif self.status == 'received' and not self.received_at_store_date:
                    self.received_at_store_date = timezone.now()

        # Keep financials quantized
        self.total_return_amount = q2(self.total_return_amount)
        self.discount_applied = q2(self.discount_applied)
        self.refund_amount = q2(self.refund_amount)

        super().save(*args, **kwargs)

    def generate_return_number(self):
        """Generate unique return number like RET-123456"""
        import random
        import string
        while True:
            number = 'RET-' + ''.join(random.choices(string.digits, k=6))
            if not Return.objects.filter(return_number=number).exists():
                return number

    # ---- Business logic ----

    def recalc_totals(self, save=True):
        """
        Recompute line totals and overall refund.
        total_return_amount = sum of line totals (unit snapshot × qty)
        refund_amount = total_return_amount - discount_applied
        """
        total = Decimal('0.00')
        for it in self.items.all():
            # Ensure each line has a proper subtotal cached
            total += q2(it.get_refund_amount())
        self.total_return_amount = q2(total)
        # Never refund negative
        self.refund_amount = q2(max(Decimal('0.00'), self.total_return_amount - q2(self.discount_applied)))
        if save:
            super(Return, self).save(update_fields=['total_return_amount', 'refund_amount', 'updated_at'])
        return self.refund_amount

    def calculate_refund_amount(self):
        """Kept for backward compatibility; delegates to recalc_totals()."""
        return self.recalc_totals(save=True)

    def can_be_approved(self):
        return self.status == 'pending'

    def can_be_cancelled(self):
        return self.status in ['pending', 'approved']

    def get_store(self):
        """
        Get the store associated with this return.
        Tries product.store; falls back to resolving via product.seller if needed.
        """
        first_item = self.items.select_related('product').first()
        if not first_item:
            return None
        product = first_item.product
        # Common schema: Product has either .store or .seller (User) -> Store
        if hasattr(product, 'store') and product.store_id:
            return product.store
        if hasattr(product, 'seller') and product.seller_id:
            from stores.models import Store
            return Store.objects.filter(owner=product.seller).first()
        return None

    def approve_return(self, approved_by=None, estimated_pickup=None, note=''):
        """Approve the return and log status history."""
        if not self.can_be_approved():
            return
        self.status = 'approved'
        self.approved_by = approved_by
        self.approved_at = timezone.now()
        if estimated_pickup:
            self.estimated_pickup_date = estimated_pickup
        # Generate tracking number
        self.tracking_number = f"EM-TRACK-{timezone.now().strftime('%Y%m%d')}-{self.return_number[-4:]}"
        self.save()

        ReturnStatusHistory.objects.create(
            return_request=self,
            status='approved',
            changed_by=approved_by,
            notes=note or (f"Return approved. Pickup scheduled for {estimated_pickup}" if estimated_pickup else "Return approved.")
        )

    def reject_return(self, rejected_by=None, reason=''):
        """Reject the return and log status history."""
        if not self.can_be_approved():
            return
        self.status = 'rejected'
        self.rejection_reason = reason or ''
        self.save()

        ReturnStatusHistory.objects.create(
            return_request=self,
            status='rejected',
            changed_by=rejected_by,
            notes=reason
        )

    def complete_return(self, discount_applied=0, note=''):
        """
        Complete the return and process refund.
        Applies discount_applied (e.g., restocking fee or admin adjustment) and recalculates totals.
        """
        if self.status != 'received':
            return
        self.discount_applied = q2(discount_applied)
        self.recalc_totals(save=False)
        self.status = 'completed'
        self.completed_at = timezone.now()
        self.save()

        # Update store inventory
        self.update_store_inventory()

        ReturnStatusHistory.objects.create(
            return_request=self,
            status='completed',
            notes=note or f"Return completed. Refund amount: D{self.refund_amount}"
        )

    def update_store_inventory(self):
        """Update store inventory when return is completed (simple example)."""
        store = self.get_store()
        if not store:
            return
        inventory, _ = StoreInventory.objects.get_or_create(
            store=store,
            defaults={
                'store_name': getattr(store, 'name', 'Store'),
                'regular_stock': 0,
                'returned_stock': 0,
                'discounted_stock': 0
            }
        )
        # Sum quantities from all items
        qty = sum(i.quantity for i in self.items.all())
        inventory.returned_stock = (inventory.returned_stock or 0) + qty
        if q2(self.discount_applied) > 0:
            inventory.discounted_stock = (inventory.discounted_stock or 0) + qty
        inventory.save(update_fields=['returned_stock', 'discounted_stock', 'last_updated'])


class ReturnItem(models.Model):
    """Individual items within a return"""

    return_request = models.ForeignKey(Return, on_delete=models.CASCADE, related_name='items')

    # ADD related_name here ↓↓↓
    order_item = models.ForeignKey('OrderItem', on_delete=models.CASCADE, related_name='return_items')

    product = models.ForeignKey('marketplace.Product', on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    reason = models.CharField(max_length=20, choices=Return.RETURN_REASON_CHOICES)
    condition = models.CharField(
        max_length=20,
        choices=[
            ('new', 'Like New'),
            ('good', 'Good Condition'),
            ('fair', 'Fair Condition'),
            ('poor', 'Poor Condition'),
            ('damaged', 'Damaged'),
        ],
        default='good'
    )
    price_at_return = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Return Item'
        verbose_name_plural = 'Return Items'

    def __str__(self):
        return f"{self.product.name} x {self.quantity} - {self.return_request.return_number}"

    def get_refund_amount(self):
        """Calculate refund amount for this item"""
        return self.price_at_return * self.quantity

    @property
    def previously_returned_qty(self):
        return self.return_items.aggregate(total=Sum('quantity'))['total'] or 0

    @property
    def remaining_returnable_qty(self):
        return max(self.quantity - self.previously_returned_qty, 0)

    def save(self, *args, **kwargs):
        # Store the price at time of return
        if not self.price_at_return:
            self.price_at_return = self.order_item.price_at_time or self.product.price
        super().save(*args, **kwargs)

class ReturnImage(models.Model):
    """Images uploaded for return requests"""

    return_request = models.ForeignKey(Return, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='returns/images/')
    description = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Return Image'
        verbose_name_plural = 'Return Images'

    def __str__(self):
        return f"Image for {self.return_request.return_number}"


class ReturnStatusHistory(models.Model):
    """Track status changes for returns"""

    return_request = models.ForeignKey(Return, on_delete=models.CASCADE, related_name='status_history')
    status = models.CharField(max_length=20, choices=Return.RETURN_STATUS_CHOICES)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Return Status History'
        verbose_name_plural = 'Return Status Histories'

    def __str__(self):
        return f"Return {self.return_request.return_number} - {self.get_status_display()} at {self.timestamp}"


class StoreInventory(models.Model):
    """
    Track store inventory including returned items.
    One summary row per store.
    """
    # One-to-one is the cleanest way if you want a single row per store.
    store = models.OneToOneField('stores.Store', on_delete=models.CASCADE, related_name='inventory_summary')
    store_name = models.CharField(max_length=255)  # Denormalized for performance
    regular_stock = models.PositiveIntegerField(default=0)
    returned_stock = models.PositiveIntegerField(default=0)
    discounted_stock = models.PositiveIntegerField(default=0)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Store Inventory'
        verbose_name_plural = 'Store Inventories'

    def __str__(self):
        return f"{self.store_name} - Inventory"

    @property
    def total_stock(self):
        return (self.regular_stock or 0) + (self.returned_stock or 0) + (self.discounted_stock or 0)


class ReturnRefund(models.Model):
    """Track refund processing for returns"""

    REFUND_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    REFUND_METHOD_CHOICES = [
        ('original_payment', 'Original Payment Method'),
        ('store_credit', 'Store Credit'),
        ('bank_transfer', 'Bank Transfer'),
        ('cash', 'Cash'),
    ]

    return_request = models.OneToOneField(Return, on_delete=models.CASCADE, related_name='refund')
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2)
    refund_method = models.CharField(max_length=20, choices=REFUND_METHOD_CHOICES, default='original_payment')
    status = models.CharField(max_length=20, choices=REFUND_STATUS_CHOICES, default='pending')

    # Payment gateway information
    transaction_id = models.CharField(max_length=100, blank=True, null=True)
    gateway_response = models.JSONField(blank=True, null=True)

    # Processing information
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    processed_at = models.DateTimeField(blank=True, null=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Additional information
    notes = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = 'Return Refund'
        verbose_name_plural = 'Return Refunds'

    def __str__(self):
        return f"Refund for {self.return_request.return_number} - D{q2(self.refund_amount)}"

    def process_refund(self, processed_by=None, transaction_id='', gateway_response=None):
        """
        Process the refund (record-keeping).
        Integrate your actual PSP here; we mark as completed for now.
        """
        self.status = 'processing'
        self.processed_by = processed_by
        self.processed_at = timezone.now()
        self.transaction_id = transaction_id or self.transaction_id
        if gateway_response is not None:
            self.gateway_response = gateway_response
        self.refund_amount = q2(self.refund_amount)
        self.save()

        # Mark completed (simulate gateway success)
        self.status = 'completed'
        self.save(update_fields=['status', 'updated_at'])


# --------------------------
# Utility helpers
# --------------------------

def can_create_return(order):
    """
    Check if a return can be created for an order.
    - Order must be delivered
    - Within 30 days (config)
    - No active return in progress for this order
    """
    if getattr(order, 'status', None) != 'delivered':
        return False, "Order must be delivered to create a return"

    from datetime import timedelta
    delivered_date = getattr(order, 'delivered_date', None) or getattr(order, 'updated_at', None)
    if delivered_date and (timezone.now().date() - delivered_date.date()) > timedelta(days=30):
        return False, "Return window has expired (30 days)"

    if order.returns.filter(status__in=['pending', 'approved', 'in_transit', 'received']).exists():
        return False, "A return request is already in progress for this order"

    return True, "Return can be created"


def get_return_statistics():
    """Get return statistics for dashboard"""
    from django.db.models import Sum

    stats = {
        'total_returns': Return.objects.count(),
        'pending_returns': Return.objects.filter(status='pending').count(),
        'approved_returns': Return.objects.filter(status='approved').count(),
        'completed_returns': Return.objects.filter(status='completed').count(),
        'total_refund_amount': Return.objects.filter(status='completed').aggregate(
            total=Sum('refund_amount')
        )['total'] or Decimal('0.00'),
    }
    return stats

class ChatMessage(models.Model):
    order = models.ForeignKey('Order', on_delete=models.CASCADE, related_name='chat_messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Message from {self.sender.username} for Order #{self.order.id}"


class CustomerComplaint(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    complaint = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)