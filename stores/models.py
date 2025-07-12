from django.db import models
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal
from django.db.models import Avg, Sum, F, ExpressionWrapper, DecimalField
import uuid
from django.db.models.signals import post_save
from django.dispatch import receiver
from PIL import Image


class StoreCategory(models.Model):
    """Category for organizing stores"""
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    image = models.ImageField(upload_to='store_categories/', blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Store Category'
        verbose_name_plural = 'Store Categories'
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('store:category_detail', kwargs={'slug': self.slug})


class Store(models.Model):
    """Main store model"""

    STORE_STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('active', 'Active'),
        ('suspended', 'Suspended'),
        ('closed', 'Closed'),
    ]

    STORE_TYPE_CHOICES = [
        ('individual', 'Individual Seller'),
        ('business', 'Business'),
        ('corporation', 'Corporation'),
        ('marketplace', 'Marketplace Vendor'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    description = models.TextField()
    short_description = models.CharField(max_length=500, blank=True, null=True)

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='owned_stores')
    managers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='StoreManager',
        through_fields=('store', 'user'),
        related_name='managed_stores',
        blank=True
    )

    store_type = models.CharField(max_length=20, choices=STORE_TYPE_CHOICES, default='individual')
    category = models.ForeignKey(StoreCategory, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STORE_STATUS_CHOICES, default='pending')

    email = models.EmailField()
    phone = models.CharField(max_length=20)
    website = models.URLField(blank=True, null=True)

    address_line_1 = models.CharField(max_length=255)
    address_line_2 = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100)
    region = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    country = models.CharField(max_length=100, default='Gambia')

    business_registration_number = models.CharField(max_length=100, blank=True, null=True)
    tax_identification_number = models.CharField(max_length=100, blank=True, null=True)
    bank_account_number = models.CharField(max_length=100, blank=True, null=True)
    bank_name = models.CharField(max_length=100, blank=True, null=True)

    logo = models.ImageField(upload_to='store_logos/', blank=True, null=True)
    banner = models.ImageField(upload_to='store_banners/', blank=True, null=True)

    is_featured = models.BooleanField(default=False)
    allow_reviews = models.BooleanField(default=True)
    auto_approve_products = models.BooleanField(default=False)

    commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('5.00'))
    minimum_order_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    processing_time = models.PositiveIntegerField(default=2, help_text="Days to process orders")
    return_policy_days = models.PositiveIntegerField(default=30, help_text="Return policy in days")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    approved_at = models.DateTimeField(blank=True, null=True)

    facebook_url = models.URLField(blank=True, null=True)
    twitter_url = models.URLField(blank=True, null=True)
    instagram_url = models.URLField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Store'
        verbose_name_plural = 'Stores'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.pk:
            old_store = Store.objects.get(pk=self.pk)
            if old_store.status != self.status and self.status == 'active' and not self.approved_at:
                self.approved_at = timezone.now()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('store:store_detail', kwargs={'slug': self.slug})

    @property
    def is_active_store(self):
        return self.status == 'active'

    def get_total_products(self):
        return self.products.filter(is_active=True).count()

    def get_total_orders(self):
        from orders.models import OrderItem
        return OrderItem.objects.filter(product__store=self).count()

    def get_average_rating(self):
        reviews = self.reviews.filter(is_approved=True)
        return reviews.aggregate(avg_rating=Avg('rating'))['avg_rating'] or 0

    def get_total_sales(self):
        from orders.models import OrderItem
        total = OrderItem.objects.filter(
            product__store=self,
            order__status='delivered'
        ).aggregate(
            total=Sum(ExpressionWrapper(F('quantity') * F('price_at_time'), output_field=DecimalField()))
        )['total']
        return total or Decimal('0.00')

    def can_process_returns(self):
        return self.is_active_store and self.return_policy_days > 0


class StoreManager(models.Model):
    """Through model for store managers"""

    ROLE_CHOICES = [
        ('manager', 'Manager'),
        ('admin', 'Admin'),
        ('staff', 'Staff'),
    ]

    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='manager')
    permissions = models.JSONField(default=dict, blank=True)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='added_managers'
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['store', 'user']
        verbose_name = 'Store Manager'
        verbose_name_plural = 'Store Managers'

    def __str__(self):
        return f"{self.user.username} - {self.store.name} ({self.role})"


class StoreHours(models.Model):
    """Store operating hours"""

    DAYS_OF_WEEK = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
        (5, 'Saturday'),
        (6, 'Sunday'),
    ]

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='hours')
    day_of_week = models.IntegerField(choices=DAYS_OF_WEEK)
    opening_time = models.TimeField(blank=True, null=True)
    closing_time = models.TimeField(blank=True, null=True)
    is_closed = models.BooleanField(default=False)

    class Meta:
        unique_together = ['store', 'day_of_week']
        ordering = ['day_of_week']
        verbose_name = 'Store Hours'
        verbose_name_plural = 'Store Hours'

    def __str__(self):
        day_name = dict(self.DAYS_OF_WEEK)[self.day_of_week]
        if self.is_closed:
            return f"{self.store.name} - {day_name}: Closed"
        return f"{self.store.name} - {day_name}: {self.opening_time} - {self.closing_time}"


class StoreReview(models.Model):
    """Customer reviews for stores"""

    RATING_CHOICES = [
        (1, '1 Star'),
        (2, '2 Stars'),
        (3, '3 Stars'),
        (4, '4 Stars'),
        (5, '5 Stars'),
    ]

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='reviews')
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    rating = models.IntegerField(choices=RATING_CHOICES)
    title = models.CharField(max_length=255)
    comment = models.TextField()
    is_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['store', 'customer']
        ordering = ['-created_at']
        verbose_name = 'Store Review'
        verbose_name_plural = 'Store Reviews'

    def __str__(self):
        return f"{self.store.name} - {self.rating} stars by {self.customer.username}"


class StoreShippingZone(models.Model):
    """Shipping zones for stores"""

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='shipping_zones')
    name = models.CharField(max_length=100)
    regions = models.TextField(help_text="Comma-separated list of regions")
    base_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    per_kg_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    free_shipping_threshold = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Order amount for free shipping"
    )
    estimated_delivery_days = models.PositiveIntegerField(default=3)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ['store', 'name']
        verbose_name = 'Shipping Zone'
        verbose_name_plural = 'Shipping Zones'

    def __str__(self):
        return f"{self.store.name} - {self.name}"


class StoreInventoryTracking(models.Model):
    """Track inventory changes for stores - enhanced for returns"""

    TRANSACTION_TYPES = [
        ('sale', 'Sale'),
        ('restock', 'Restock'),
        ('return_received', 'Return Received'),
        ('return_restocked', 'Return Restocked'),
        ('return_discounted', 'Return Discounted'),
        ('damage', 'Damage/Loss'),
        ('adjustment', 'Manual Adjustment'),
    ]

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='inventory_tracking')
    product = models.ForeignKey('marketplace.Product', on_delete=models.CASCADE)
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    quantity_change = models.IntegerField()  # Can be negative

    # Additional fields for returns
    return_request = models.ForeignKey(
        'orders.Return',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inventory_transactions'
    )
    condition = models.CharField(
        max_length=20,
        choices=[
            ('new', 'Like New'),
            ('good', 'Good Condition'),
            ('fair', 'Fair Condition'),
            ('poor', 'Poor Condition'),
            ('damaged', 'Damaged'),
        ],
        blank=True,
        null=True
    )

    # Reference information
    reference_id = models.CharField(max_length=100, blank=True, null=True)  # Order ID, Return ID, etc.
    notes = models.TextField(blank=True, null=True)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Store Inventory Tracking'
        verbose_name_plural = 'Store Inventory Tracking'

    def __str__(self):
        return f"{self.store.name} - {self.product.name} - {self.transaction_type} ({self.quantity_change})"


class StoreReturnSettings(models.Model):
    """Return policy settings for each store"""

    store = models.OneToOneField(Store, on_delete=models.CASCADE, related_name='return_settings')

    # Return window
    return_window_days = models.PositiveIntegerField(default=30)

    # Accepted reasons
    accept_defective = models.BooleanField(default=True)
    accept_wrong_item = models.BooleanField(default=True)
    accept_wrong_size = models.BooleanField(default=True)
    accept_damaged_shipping = models.BooleanField(default=True)
    accept_not_as_described = models.BooleanField(default=True)
    accept_changed_mind = models.BooleanField(default=False)
    accept_quality_issues = models.BooleanField(default=True)

    # Return processing
    auto_approve_returns = models.BooleanField(default=False)
    require_original_packaging = models.BooleanField(default=True)
    require_photos = models.BooleanField(default=True)

    # Logistics
    provide_return_label = models.BooleanField(default=True)
    pickup_service_available = models.BooleanField(default=True)

    # Financial policies
    restocking_fee_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Percentage fee for returns (0-100)"
    )
    refund_shipping_cost = models.BooleanField(default=False)

    # Custom policies
    custom_return_policy = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Store Return Settings'
        verbose_name_plural = 'Store Return Settings'

    def __str__(self):
        return f"Return Settings - {self.store.name}"

    def can_accept_return_reason(self, reason):
        """Check if store accepts a specific return reason"""
        reason_mapping = {
            'defective': self.accept_defective,
            'wrong_item': self.accept_wrong_item,
            'wrong_size': self.accept_wrong_size,
            'damaged_shipping': self.accept_damaged_shipping,
            'not_as_described': self.accept_not_as_described,
            'changed_mind': self.accept_changed_mind,
            'quality_issues': self.accept_quality_issues,
        }
        return reason_mapping.get(reason, False)


class StoreMetrics(models.Model):
    """Daily metrics for stores"""

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='metrics')
    date = models.DateField()

    # Sales metrics
    total_orders = models.PositiveIntegerField(default=0)
    total_sales = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_items_sold = models.PositiveIntegerField(default=0)

    # Return metrics
    total_returns = models.PositiveIntegerField(default=0)
    total_return_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    return_rate_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))

    # Inventory metrics
    total_inventory_value = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    low_stock_items = models.PositiveIntegerField(default=0)
    out_of_stock_items = models.PositiveIntegerField(default=0)

    # Customer metrics
    new_customers = models.PositiveIntegerField(default=0)
    repeat_customers = models.PositiveIntegerField(default=0)
    total_reviews = models.PositiveIntegerField(default=0)
    average_rating = models.DecimalField(max_digits=3, decimal_places=2, default=Decimal('0.00'))

    class Meta:
        unique_together = ['store', 'date']
        ordering = ['-date']
        verbose_name = 'Store Metrics'
        verbose_name_plural = 'Store Metrics'

    def __str__(self):
        return f"{self.store.name} - {self.date}"

    @classmethod
    def calculate_daily_metrics(cls, store, date=None):
        """Calculate and store daily metrics for a store"""
        if date is None:
            date = timezone.now().date()

        from orders.models import OrderItem, Return
        from django.db.models import Sum, Avg, Count

        # Get or create metrics record
        metrics, created = cls.objects.get_or_create(
            store=store,
            date=date,
            defaults={}
        )

        # Calculate sales metrics
        daily_orders = OrderItem.objects.filter(
            product__store=store,
            order__created_at__date=date,
            order__status__in=['delivered', 'shipped', 'processing']
        )

        metrics.total_orders = daily_orders.values('order').distinct().count()
        metrics.total_sales = daily_orders.aggregate(
            total=Sum(models.F('quantity') * models.F('price_at_time'))
        )['total'] or Decimal('0.00')
        metrics.total_items_sold = daily_orders.aggregate(
            total=Sum('quantity')
        )['total'] or 0

        # Calculate return metrics
        daily_returns = Return.objects.filter(
            items__product__store=store,
            created_at__date=date
        ).distinct()

        metrics.total_returns = daily_returns.count()
        metrics.total_return_amount = daily_returns.aggregate(
            total=Sum('total_return_amount')
        )['total'] or Decimal('0.00')

        # Calculate return rate
        if metrics.total_sales > 0:
            metrics.return_rate_percentage = (
                                                     metrics.total_return_amount / metrics.total_sales
                                             ) * 100

        metrics.save()
        return metrics


# Signal handlers for automatic inventory tracking
@receiver(post_save, sender='orders.Return')
def handle_return_inventory(sender, instance, created, **kwargs):
    """Handle inventory changes when returns are processed"""
    if instance.status == 'completed':
        for return_item in instance.items.all():
            # Create inventory tracking record
            StoreInventoryTracking.objects.create(
                store=return_item.product.store,
                product=return_item.product,
                transaction_type='return_received',
                quantity_change=return_item.quantity,
                return_request=instance,
                condition=return_item.condition,
                reference_id=instance.return_number,
                notes=f"Return completed: {instance.reason_description}",
                performed_by=instance.approved_by
            )

            # Create another record if item is being discounted
            if instance.discount_applied > 0:
                StoreInventoryTracking.objects.create(
                    store=return_item.product.store,
                    product=return_item.product,
                    transaction_type='return_discounted',
                    quantity_change=0,  # No quantity change, just status change
                    return_request=instance,
                    condition=return_item.condition,
                    reference_id=instance.return_number,
                    notes=f"Item marked for discount sale due to return condition",
                    performed_by=instance.approved_by
                )


# Utility functions for store management

def get_store_by_slug(slug):
    """Get active store by slug"""
    try:
        return Store.objects.get(slug=slug, status='active')
    except Store.DoesNotExist:
        return None


def get_stores_by_category(category_slug):
    """Get active stores by category"""
    return Store.objects.filter(
        category__slug=category_slug,
        status='active'
    ).order_by('-is_featured', '-created_at')


def get_featured_stores(limit=10):
    """Get featured active stores"""
    return Store.objects.filter(
        status='active',
        is_featured=True
    ).order_by('-created_at')[:limit]