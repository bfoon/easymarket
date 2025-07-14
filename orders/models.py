from django.db import models
from django.contrib.auth.models import User
from django.conf import settings
from django.utils import timezone
from decimal import Decimal
import uuid

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
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('8.5'))  # 8.5% default tax
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
    def get_total(self):
        """Calculate the final total including tax and shipping"""
        subtotal = self.get_subtotal()
        tax = self.get_tax_amount()
        shipping = self.shipping_cost or Decimal('0.00')
        discount = self.discount_amount or Decimal('0.00')
        return round(subtotal + tax + shipping - discount, 2)

    def get_item_count(self):
        """Get total number of items in the order"""
        return sum(item.quantity for item in self.items.all())

    def can_be_cancelled(self):
        """Check if order can be cancelled"""
        return self.status in ['pending', 'processing']

    def can_be_tracked(self):
        """Check if order can be tracked"""
        return self.status in ['shipped', 'delivered'] and self.tracking_number

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
        if not self.shipped_date:
            self.shipped_date = timezone.now()
        self.save()


    def save(self, *args, **kwargs):
        # Auto-set dates based on status changes
        if self.pk:  # Only for existing orders
            old_order = Order.objects.get(pk=self.pk)
            if old_order.status != self.status:
                if self.status == 'shipped' and not self.shipped_date:
                    self.shipped_date = timezone.now()
                elif self.status == 'delivered' and not self.delivered_date:
                    self.delivered_date = timezone.now()

        super().save(*args, **kwargs)


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('marketplace.Product', related_name='order_items', on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    selected_features = models.JSONField(blank=True, null=True)
    price_at_time = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)

    shipped_to_warehouse = models.BooleanField(default=False)  # ✅ New field

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['order', 'product']

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"

    def get_total_price(self):
        price = self.price_at_time if self.price_at_time else self.product.price
        return price * self.quantity

    def save(self, *args, **kwargs):
        if not self.price_at_time:
            self.price_at_time = self.product.price
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
    order = models.ForeignKey('Order', on_delete=models.CASCADE, related_name='returns')
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='returns')

    # Return Details
    status = models.CharField(max_length=20, choices=RETURN_STATUS_CHOICES, default='pending')
    reason = models.CharField(max_length=20, choices=RETURN_REASON_CHOICES)
    reason_description = models.TextField(help_text="Detailed explanation for the return")

    # Financial Information
    total_return_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    discount_applied = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    refund_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

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

    def save(self, *args, **kwargs):
        # Generate return number if not exists
        if not self.return_number:
            self.return_number = self.generate_return_number()

        # Auto-set dates based on status changes
        if self.pk:  # Only for existing returns
            old_return = Return.objects.get(pk=self.pk)
            if old_return.status != self.status:
                if self.status == 'approved' and not self.approved_at:
                    self.approved_at = timezone.now()
                elif self.status == 'completed' and not self.completed_at:
                    self.completed_at = timezone.now()
                elif self.status == 'received' and not self.received_at_store_date:
                    self.received_at_store_date = timezone.now()

        super().save(*args, **kwargs)

    def generate_return_number(self):
        """Generate unique return number"""
        import random
        import string
        while True:
            number = 'RET-' + ''.join(random.choices(string.digits, k=6))
            if not Return.objects.filter(return_number=number).exists():
                return number

    def calculate_refund_amount(self):
        """Calculate the total refund amount"""
        total = sum(item.get_refund_amount() for item in self.items.all())
        self.refund_amount = total - self.discount_applied
        return self.refund_amount

    def can_be_approved(self):
        """Check if return can be approved"""
        return self.status == 'pending'

    def can_be_cancelled(self):
        """Check if return can be cancelled"""
        return self.status in ['pending', 'approved']

    def get_store(self):
        """Get the store associated with this return"""
        # Get store from the first product in return items
        return self.items.first().product.store if self.items.exists() else None

    def approve_return(self, approved_by=None, estimated_pickup=None):
        """Approve the return"""
        if self.can_be_approved():
            self.status = 'approved'
            self.approved_by = approved_by
            self.approved_at = timezone.now()
            if estimated_pickup:
                self.estimated_pickup_date = estimated_pickup
            # Generate tracking number
            self.tracking_number = f"EM-TRACK-{timezone.now().strftime('%Y%m%d')}-{self.return_number[-4:]}"
            self.save()

            # Create status history
            ReturnStatusHistory.objects.create(
                return_request=self,
                status='approved',
                changed_by=approved_by,
                notes=f"Return approved. Pickup scheduled for {estimated_pickup}"
            )

    def reject_return(self, rejected_by=None, reason=''):
        """Reject the return"""
        if self.can_be_approved():
            self.status = 'rejected'
            self.rejection_reason = reason
            self.save()

            # Create status history
            ReturnStatusHistory.objects.create(
                return_request=self,
                status='rejected',
                changed_by=rejected_by,
                notes=reason
            )

    def complete_return(self, discount_applied=0):
        """Complete the return and process refund"""
        if self.status == 'received':
            self.discount_applied = discount_applied
            self.refund_amount = self.calculate_refund_amount()
            self.status = 'completed'
            self.completed_at = timezone.now()
            self.save()

            # Update store inventory
            self.update_store_inventory()

            # Create status history
            ReturnStatusHistory.objects.create(
                return_request=self,
                status='completed',
                notes=f"Return completed. Refund amount: ${self.refund_amount}"
            )

    def update_store_inventory(self):
        """Update store inventory when return is completed"""
        for item in self.items.all():
            # Create or update store inventory record
            inventory, created = StoreInventory.objects.get_or_create(
                store=item.product.store,
                defaults={
                    'store_name': item.product.store.name,
                    'regular_stock': 0,
                    'returned_stock': 0,
                    'discounted_stock': 0
                }
            )

            inventory.returned_stock += item.quantity
            if self.discount_applied > 0:
                inventory.discounted_stock += item.quantity
            inventory.save()

            # Create inventory tracking record using store app model
            from stores.models import StoreInventoryTracking
            StoreInventoryTracking.objects.create(
                store=item.product.store,
                product=item.product,
                transaction_type='return_received',
                quantity_change=item.quantity,
                return_request=self,
                condition=item.condition,
                reference_id=self.return_number,
                notes=f"Return completed: {self.reason_description}",
                performed_by=self.approved_by
            )


class ReturnItem(models.Model):
    """Individual items within a return"""

    return_request = models.ForeignKey(Return, on_delete=models.CASCADE, related_name='items')
    order_item = models.ForeignKey('OrderItem', on_delete=models.CASCADE)
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
    """Track store inventory including returned items"""

    store = models.ForeignKey('stores.Store', on_delete=models.CASCADE, related_name='inventory_summary')
    store_name = models.CharField(max_length=255)  # Denormalized for performance
    regular_stock = models.PositiveIntegerField(default=0)
    returned_stock = models.PositiveIntegerField(default=0)
    discounted_stock = models.PositiveIntegerField(default=0)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Store Inventory'
        verbose_name_plural = 'Store Inventories'
        unique_together = ['store']

    def __str__(self):
        return f"{self.store_name} - Inventory"

    @property
    def total_stock(self):
        return self.regular_stock + self.returned_stock + self.discounted_stock


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
    refund_amount = models.DecimalField(max_digits=10, decimal_places=2)
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
        return f"Refund for {self.return_request.return_number} - ${self.refund_amount}"

    def process_refund(self, processed_by=None):
        """Process the refund"""
        self.status = 'processing'
        self.processed_by = processed_by
        self.processed_at = timezone.now()
        self.save()

        # Here you would integrate with your payment gateway
        # For now, we'll mark it as completed
        self.status = 'completed'
        self.save()


# Additional utility functions

def can_create_return(order):
    """Check if a return can be created for an order"""
    # Define your business rules here
    if order.status not in ['delivered']:
        return False, "Order must be delivered to create a return"

    # Check if return window is still open (e.g., 30 days)
    from datetime import timedelta
    if order.delivered_date and (timezone.now().date() - order.delivered_date.date()) > timedelta(days=30):
        return False, "Return window has expired (30 days)"

    # Check if return already exists
    if order.returns.filter(status__in=['pending', 'approved', 'in_transit', 'received']).exists():
        return False, "A return request is already in progress for this order"

    return True, "Return can be created"


def get_return_statistics():
    """Get return statistics for dashboard"""
    from django.db.models import Count, Sum

    stats = {
        'total_returns': Return.objects.count(),
        'pending_returns': Return.objects.filter(status='pending').count(),
        'approved_returns': Return.objects.filter(status='approved').count(),
        'completed_returns': Return.objects.filter(status='completed').count(),
        'total_refund_amount': Return.objects.filter(status='completed').aggregate(
            total=Sum('refund_amount')
        )['total'] or 0,
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