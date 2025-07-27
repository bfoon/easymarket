from django.db import models
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal
from django.db.models import Avg, Sum, F, ExpressionWrapper, DecimalField
import uuid
import random
import string
from django.db.models.signals import post_save
from django.dispatch import receiver
from PIL import Image
from django.contrib.auth import get_user_model
from marketplace.models import Product
import threading
from django.core.mail import send_mail

User = get_user_model()


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


class StoreFollow(models.Model):
    """Track which users follow which stores"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='store_follows')
    store = models.ForeignKey('Store', on_delete=models.CASCADE, related_name='followers')
    followed_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    # Notification preferences
    notify_new_products = models.BooleanField(default=True)
    notify_price_changes = models.BooleanField(default=True)
    notify_discounts = models.BooleanField(default=True)

    class Meta:
        unique_together = ['user', 'store']
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['store', 'is_active']),
        ]

    def __str__(self):
        return f"{self.user.username} follows {self.store.name}"


class StoreNotification(models.Model):
    """Store notifications for followers"""
    NOTIFICATION_TYPES = [
        ('new_product', 'New Product'),
        ('price_increase', 'Price Increase'),
        ('price_decrease', 'Price Decrease'),
        ('discount', 'Discount Available'),
        ('back_in_stock', 'Back in Stock'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='store_notifications')
    store = models.ForeignKey('Store', on_delete=models.CASCADE, related_name='notifications')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, null=True, blank=True)

    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES)
    title = models.CharField(max_length=200)
    message = models.TextField()

    # Metadata
    old_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    new_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    is_sent = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read']),
            models.Index(fields=['store', 'created_at']),
        ]

    def __str__(self):
        return f"{self.notification_type}: {self.title}"


class ProductPriceHistory(models.Model):
    """Track price changes for notifications"""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='price_history')
    old_price = models.DecimalField(max_digits=10, decimal_places=2)
    new_price = models.DecimalField(max_digits=10, decimal_places=2)
    changed_at = models.DateTimeField(auto_now_add=True)
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-changed_at']
        indexes = [
            models.Index(fields=['product', 'changed_at']),
        ]

    def __str__(self):
        return f"{self.product.name}: ${self.old_price} → ${self.new_price}"


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
    allow_auctions = models.BooleanField(default=True)
    auction_commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('5.00'),
        help_text="Commission rate for auctions (%)"
    )
    auto_approve_auctions = models.BooleanField(
        default=False,
        help_text="Automatically approve auctions without admin review"
    )
    accept_cash_risk = models.BooleanField(default=False)
    allow_referrals = models.BooleanField(
        default=False,
        help_text="Allow buyers to refer this store and earn rewards."
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Store'
        verbose_name_plural = 'Stores'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self._state.adding:
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

    def get_active_auctions(self):
        """Get active auctions for this store"""
        return self.auctions.filter(status='active')

    def get_auction_sales(self):
        """Get total auction sales for this store"""
        from auction.models import Auction
        from django.db.models import Sum

        return self.auctions.filter(
            status__in=['sold', 'ended'],
            winner__isnull=False
        ).aggregate(
            total=Sum('current_bid')
        )['total'] or Decimal('0.00')

    def is_followed_by(self, user):
        """
        Checks if this store is followed by the given user.
        """
        if not user or not user.is_authenticated:
            return False

        return StoreFollow.objects.filter(user=user, store=self).exists()

    def get_followers_count(self):
        from .models import StoreFollow  # or adjust the import if StoreFollow is elsewhere
        return StoreFollow.objects.filter(store=self).count()

    def send_bulk_emails_threaded(emails_data, store_name):
        for email_data in emails_data:
            try:
                send_mail(
                    subject=f"{store_name}: {email_data['title']}",
                    message=f"Hi {email_data['name']},\n\n{email_data['message']}\n\nBest regards,\n{store_name}",
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[email_data['email']],
                    fail_silently=True,
                )
            except Exception as e:
                print(f"Failed to send email to {email_data['email']}: {e}")

    def notify_followers(self, notification_type, title, message, product=None, **kwargs):
        """
        Notify all users who follow this store (DB + Email in background thread).
        """
        from .models import StoreFollow, StoreNotification

        followers = StoreFollow.objects.filter(
            store=self,
            is_active=True
        ).select_related('user')

        notifications_to_create = []
        emails_to_send = []

        for follow in followers:
            should_notify = False
            if notification_type == 'new_product' and follow.notify_new_products:
                should_notify = True
            elif notification_type in ['price_decrease', 'price_increase'] and follow.notify_price_changes:
                should_notify = True
            elif notification_type == 'discount' and follow.notify_discounts:
                should_notify = True

            if should_notify:
                # Notification DB entry
                notifications_to_create.append(
                    StoreNotification(
                        user=follow.user,
                        store=self,
                        product=product,
                        notification_type=notification_type,
                        title=title,
                        message=message,
                        old_price=kwargs.get('old_price'),
                        new_price=kwargs.get('new_price')
                    )
                )

                # Prepare email data
                if follow.user.email:
                    emails_to_send.append({
                        'email': follow.user.email,
                        'name': follow.user.get_full_name() or follow.user.username,
                        'title': title,
                        'message': message
                    })

        if notifications_to_create:
            StoreNotification.objects.bulk_create(notifications_to_create)

        if emails_to_send:
            threading.Thread(
                target=send_bulk_emails_threaded,
                args=(emails_to_send, self.name)
            ).start()

        return len(notifications_to_create)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            old_store = Store.objects.get(pk=self.pk)
            if old_store.status != self.status and self.status == 'active' and not self.approved_at:
                self.approved_at = timezone.now()
        super().save(*args, **kwargs)

    # Also fix the notify_followers method to actually send notifications:
    def notify_followers(self, notification_type, title, message, product=None, **kwargs):
        """
        Notify all users who follow this store.
        """
        from .models import StoreFollow, StoreNotification
        from django.core.mail import send_mail
        from django.conf import settings

        # Get followers with their notification preferences
        followers = StoreFollow.objects.filter(
            store=self,
            is_active=True
        ).select_related('user')

        notifications_to_create = []
        emails_to_send = []

        for follow in followers:
            # Check notification preferences
            should_notify = False
            if notification_type == 'new_product' and follow.notify_new_products:
                should_notify = True
            elif notification_type in ['price_decrease', 'price_increase'] and follow.notify_price_changes:
                should_notify = True
            elif notification_type == 'discount' and follow.notify_discounts:
                should_notify = True

            if should_notify:
                # Create notification record
                notifications_to_create.append(
                    StoreNotification(
                        user=follow.user,
                        store=self,
                        product=product,
                        notification_type=notification_type,
                        title=title,
                        message=message,
                        old_price=kwargs.get('old_price'),
                        new_price=kwargs.get('new_price')
                    )
                )

                # Prepare email
                if follow.user.email:
                    emails_to_send.append({
                        'email': follow.user.email,
                        'name': follow.user.get_full_name() or follow.user.username,
                        'title': title,
                        'message': message
                    })

        # Bulk create notifications
        if notifications_to_create:
            StoreNotification.objects.bulk_create(notifications_to_create)

        # Send emails
        for email_data in emails_to_send:
            try:
                send_mail(
                    subject=f"{self.name}: {email_data['title']}",
                    message=f"Hi {email_data['name']},\n\n{email_data['message']}\n\nBest regards,\n{self.name}",
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[email_data['email']],
                    fail_silently=True,
                )
            except Exception as e:
                print(f"Failed to send email to {email_data['email']}: {e}")

        return len(notifications_to_create)


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

def generate_referral_code(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

class StoreReferral(models.Model):
    referrer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='store_referrals')
    referred_email = models.EmailField()
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='referrals')
    referral_code = models.CharField(max_length=10, unique=True, blank=True)
    is_used = models.BooleanField(default=False)
    reward_issued = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('referrer', 'referred_email', 'store')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.referrer} referred {self.referred_email} to {self.store}"

    def save(self, *args, **kwargs):
        if not self.referral_code:
            self.referral_code = generate_referral_code()
        super().save(*args, **kwargs)