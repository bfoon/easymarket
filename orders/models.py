from django.db import models
from django.conf import settings
from django.utils import timezone
from decimal import Decimal

class PromoCode(models.Model):
    code = models.CharField(max_length=50, unique=True)
    discount_percentage = models.PositiveIntegerField(help_text="Percentage discount, e.g., 10 for 10%")
    influencer = models.ForeignKey('marketplace.CelebrityFeature', on_delete=models.SET_NULL, null=True, blank=True, related_name='promo_codes')
    is_active = models.BooleanField(default=True)
    usage_limit = models.PositiveIntegerField(default=0, help_text="0 means unlimited")
    usage_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.code} - {self.discount_percentage}% ({self.influencer.celebrity_name if self.influencer else 'General'})"

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


class Order(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('shipped', 'Shipped'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
    ]

    # PAYMENT_METHOD_CHOICES = [
    #     ('credit_card', 'Credit Card'),
    #     ('paypal', 'PayPal'),
    #     ('bank_transfer', 'Bank Transfer'),
    #     ('cash_on_delivery', 'Cash on Delivery'),
    # ]

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
    product = models.ForeignKey('marketplace.Product', on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    price_at_time = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['order', 'product']

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"

    def get_total_price(self):
        """Get total price for this item"""
        price = self.price_at_time if self.price_at_time else self.product.price
        return price * self.quantity

    def save(self, *args, **kwargs):
        # Store the price at time of order
        if not self.price_at_time:
            self.price_at_time = self.product.price
        super().save(*args, **kwargs)


class ShippingAddress(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='shipping_addresses')
    full_name = models.CharField(max_length=100)
    street = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    zip_code = models.CharField(max_length=20)
    country = models.CharField(max_length=100, default='United States')
    phone_number = models.CharField(max_length=20, blank=True, null=True)
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

#
# class OrderPayment(models.Model):
#     """Track payment information for orders"""
#     PAYMENT_STATUS_CHOICES = [
#         ('pending', 'Pending'),
#         ('processing', 'Processing'),
#         ('completed', 'Completed'),
#         ('failed', 'Failed'),
#         ('refunded', 'Refunded'),
#     ]
#
#     order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='payment')
#     payment_method = models.CharField(max_length=20, choices=Order.PAYMENT_METHOD_CHOICES)
#     payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
#     transaction_id = models.CharField(max_length=100, blank=True, null=True)
#     amount = models.DecimalField(max_digits=10, decimal_places=2)
#     payment_date = models.DateTimeField(blank=True, null=True)
#     refund_date = models.DateTimeField(blank=True, null=True)
#     refund_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
#     notes = models.TextField(blank=True, null=True)
#     created_at = models.DateTimeField(auto_now_add=True)
#
#     def __str__(self):
#         return f"Payment for Order #{self.order.id} - {self.get_payment_status_display()}"
#
#     def is_successful(self):
#         return self.payment_status == 'completed'
#
#     def can_be_refunded(self):
#         return self.payment_status == 'completed' and self.refund_amount < self.amount
#
#
