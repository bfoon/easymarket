# crossroad_deals/models.py

from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from decimal import Decimal
import uuid


class CrossroadDealConfig(models.Model):
    """
    Admin configuration for platform fees and settings
    """
    # Fees
    listing_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('5.00'),
        help_text="Fee for listing an item (for buyers who want to sell)"
    )

    vetting_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('10.00'),
        help_text="Fee for Easy Move to vet the product"
    )

    pickup_base_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('15.00'),
        help_text="Base fee for direct pickup"
    )

    # Suspension thresholds
    bad_review_threshold = models.PositiveIntegerField(
        default=3,
        help_text="Number of bad reviews before suspension"
    )

    review_rating_bad = models.PositiveIntegerField(
        default=2,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Rating considered 'bad' (e.g., 2 stars or below)"
    )

    # Listing settings
    max_listing_duration_days = models.PositiveIntegerField(
        default=30,
        help_text="Maximum days a listing stays active"
    )

    auto_delete_sold_items = models.BooleanField(
        default=True,
        help_text="Auto-delete sold items after recording stats"
    )

    # Platform settings
    require_geocode = models.BooleanField(
        default=True,
        help_text="Require geocode for all listings"
    )

    allow_buyer_listings = models.BooleanField(
        default=True,
        help_text="Allow buyers to list items"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Crossroad Deal Configuration"
        verbose_name_plural = "Crossroad Deal Configuration"

    def __str__(self):
        return f"Config - Updated: {self.updated_at.strftime('%Y-%m-%d')}"

    @classmethod
    def get_config(cls):
        """Get or create the config singleton"""
        config, _ = cls.objects.get_or_create(pk=1)
        return config


class PrivacyDisclosureRule(models.Model):
    """
    Defines when certain information should be disclosed
    """
    DISCLOSURE_TRIGGERS = [
        ('immediately', 'Immediately (Public)'),
        ('after_interest', 'After Express Interest'),
        ('after_add_to_cart', 'After Add to Cart'),
        ('after_payment', 'After Payment'),
        ('after_order_complete', 'After Order Complete'),
        ('never', 'Never (Keep Private)'),
    ]

    FIELD_TYPES = [
        ('contact_phone', 'Contact Phone'),
        ('contact_email', 'Contact Email'),
        ('price', 'Price'),
        ('exact_location', 'Exact Location'),
        ('geocode', 'Geocode'),
        ('seller_name', 'Seller Name'),
        ('product_condition', 'Product Condition'),
        ('quantity_available', 'Quantity Available'),
    ]

    field_name = models.CharField(max_length=50, choices=FIELD_TYPES, unique=True)
    default_disclosure = models.CharField(
        max_length=30,
        choices=DISCLOSURE_TRIGGERS,
        default='immediately',
        help_text="Default disclosure timing for this field"
    )
    description = models.TextField(blank=True)
    is_required = models.BooleanField(default=False, help_text="Must be disclosed at some point")

    class Meta:
        verbose_name = "Privacy Disclosure Rule"
        verbose_name_plural = "Privacy Disclosure Rules"

    def __str__(self):
        return f"{self.get_field_name_display()} - {self.get_default_disclosure_display()}"


class CrossroadListing(models.Model):
    """
    Main listing model for Crossroad Deals
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('sold_out', 'Sold Out'),
        ('suspended', 'Suspended'),
        ('banned', 'Banned'),
        ('expired', 'Expired'),
    ]

    CONDITION_CHOICES = [
        ('new', 'Brand New'),
        ('like_new', 'Like New'),
        ('good', 'Good Condition'),
        ('fair', 'Fair Condition'),
        ('poor', 'Poor Condition'),
    ]

    # Basic Info
    listing_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='crossroad_listings'
    )

    # Product Info
    title = models.CharField(max_length=200)
    description = models.TextField()
    condition = models.CharField(max_length=20, choices=CONDITION_CHOICES, default='good')

    # Images (max 2)
    image_1 = models.ImageField(upload_to='crossroad_deals/listings/', help_text="Primary image")
    image_2 = models.ImageField(
        upload_to='crossroad_deals/listings/',
        blank=True,
        null=True,
        help_text="Secondary image (optional)"
    )

    # Quantity & Pricing
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    quantity_sold = models.PositiveIntegerField(default=0)
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])

    # Location
    geocode = models.CharField(max_length=100, help_text="Required geocode for pickup/delivery")
    location_description = models.CharField(
        max_length=200,
        blank=True,
        help_text="General area (e.g., 'Serekunda Market Area')"
    )

    # Privacy Controls
    show_seller_name = models.BooleanField(default=False)
    show_exact_location = models.BooleanField(default=False)

    # Conditional disclosure settings
    price_disclosure = models.CharField(
        max_length=30,
        choices=PrivacyDisclosureRule.DISCLOSURE_TRIGGERS,
        default='immediately'
    )
    contact_disclosure = models.CharField(
        max_length=30,
        choices=PrivacyDisclosureRule.DISCLOSURE_TRIGGERS,
        default='after_add_to_cart'
    )
    location_disclosure = models.CharField(
        max_length=30,
        choices=PrivacyDisclosureRule.DISCLOSURE_TRIGGERS,
        default='after_order_complete'
    )

    # Contact Info
    contact_phone = models.CharField(max_length=20, blank=True)
    contact_email = models.EmailField(blank=True)

    # Status & Tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    is_vetted = models.BooleanField(default=False)
    vetted_at = models.DateTimeField(null=True, blank=True)
    vetted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vetted_crossroad_listings'
    )

    # Fees
    listing_fee_paid = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    vetting_fee_paid = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)
    sold_out_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['seller', '-created_at']),
            models.Index(fields=['listing_id']),
        ]

    def __str__(self):
        return f"{self.title} - {self.seller.username}"

    def save(self, *args, **kwargs):
        # Set expiry date on first publish
        if self.status == 'active' and not self.published_at:
            self.published_at = timezone.now()
            config = CrossroadDealConfig.get_config()
            self.expires_at = self.published_at + timezone.timedelta(days=config.max_listing_duration_days)

        # Mark as sold out if quantity sold equals quantity
        if self.quantity_sold >= self.quantity and self.status == 'active':
            self.status = 'sold_out'
            self.sold_out_at = timezone.now()

        super().save(*args, **kwargs)

        # Auto-delete if sold out and config allows
        if self.status == 'sold_out':
            config = CrossroadDealConfig.get_config()
            if config.auto_delete_sold_items:
                # Record stats before deletion
                ListingSaleRecord.record_sale(self)

    @property
    def quantity_available(self):
        return self.quantity - self.quantity_sold

    @property
    def is_available(self):
        return self.status == 'active' and self.quantity_available > 0

    @property
    def time_to_sell_out(self):
        """Calculate time taken to sell out"""
        if self.sold_out_at and self.published_at:
            return self.sold_out_at - self.published_at
        return None

    def can_disclose_field(self, field_name, disclosure_stage):
        """
        Check if a field can be disclosed at the current stage

        Args:
            field_name: 'price', 'contact', or 'location'
            disclosure_stage: current stage ('immediately', 'after_add_to_cart', etc.)

        Returns:
            bool: True if field can be disclosed
        """
        disclosure_order = [
            'immediately',
            'after_interest',
            'after_add_to_cart',
            'after_payment',
            'after_order_complete',
            'never'
        ]

        # Get the disclosure setting for this field
        if field_name == 'price':
            required_stage = self.price_disclosure
        elif field_name == 'contact':
            required_stage = self.contact_disclosure
        elif field_name == 'location':
            required_stage = self.location_disclosure
        else:
            return False

        # Never disclose if set to 'never'
        if required_stage == 'never':
            return False

        # Check if current stage meets requirement
        try:
            required_index = disclosure_order.index(required_stage)
            current_index = disclosure_order.index(disclosure_stage)
            return current_index >= required_index
        except ValueError:
            return False

    def get_disclosed_data(self, disclosure_stage='immediately'):
        """
        Get data that should be disclosed at the current stage
        """
        data = {
            'listing_id': str(self.listing_id),
            'title': self.title,
            'description': self.description,
            'condition': self.condition,
            'image_1': self.image_1.url if self.image_1 else None,
            'image_2': self.image_2.url if self.image_2 else None,
            'quantity_available': self.quantity_available if self.can_disclose_field('quantity',
                                                                                     disclosure_stage) else None,
        }

        # Conditionally add fields based on disclosure stage
        if self.can_disclose_field('price', disclosure_stage):
            data['price'] = float(self.price)

        if self.can_disclose_field('contact', disclosure_stage):
            data['contact_phone'] = self.contact_phone
            data['contact_email'] = self.contact_email

        if self.can_disclose_field('location', disclosure_stage):
            data['geocode'] = self.geocode
            data['location_description'] = self.location_description

        if self.show_seller_name:
            data['seller_name'] = self.seller.get_full_name()

        return data


class ListingSaleRecord(models.Model):
    """
    Records statistics about sold listings (for admin analytics)
    """
    listing_id = models.UUIDField()
    title = models.CharField(max_length=200)
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='crossroad_sale_records'
    )

    quantity_listed = models.PositiveIntegerField()
    quantity_sold = models.PositiveIntegerField()
    price_per_unit = models.DecimalField(max_digits=10, decimal_places=2)
    total_revenue = models.DecimalField(max_digits=12, decimal_places=2)

    published_at = models.DateTimeField()
    sold_out_at = models.DateTimeField()
    time_to_sell_out = models.DurationField(help_text="Time taken to sell out")

    was_vetted = models.BooleanField(default=False)
    listing_fee = models.DecimalField(max_digits=10, decimal_places=2)
    vetting_fee = models.DecimalField(max_digits=10, decimal_places=2)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-sold_out_at']
        indexes = [
            models.Index(fields=['-sold_out_at']),
            models.Index(fields=['seller', '-sold_out_at']),
        ]

    def __str__(self):
        return f"{self.title} - Sold in {self.time_to_sell_out}"

    @classmethod
    def record_sale(cls, listing):
        """Create a sale record from a sold-out listing"""
        if listing.sold_out_at and listing.published_at:
            cls.objects.create(
                listing_id=listing.listing_id,
                title=listing.title,
                seller=listing.seller,
                quantity_listed=listing.quantity,
                quantity_sold=listing.quantity_sold,
                price_per_unit=listing.price,
                total_revenue=listing.price * listing.quantity_sold,
                published_at=listing.published_at,
                sold_out_at=listing.sold_out_at,
                time_to_sell_out=listing.time_to_sell_out,
                was_vetted=listing.is_vetted,
                listing_fee=listing.listing_fee_paid,
                vetting_fee=listing.vetting_fee_paid,
            )


class CrossroadOrder(models.Model):
    """
    Order for Crossroad Deals items
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('pickup_scheduled', 'Pickup Scheduled'),
        ('in_transit', 'In Transit'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
        ('disputed', 'Disputed'),
    ]

    DELIVERY_METHODS = [
        ('easy_move', 'Easy Move Logistics'),
        ('direct_pickup', 'Direct Pickup'),
    ]

    # Order Info
    order_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    listing = models.ForeignKey(CrossroadListing, on_delete=models.PROTECT, related_name='orders')
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='crossroad_orders'
    )

    # Order Details
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)

    # Delivery
    delivery_method = models.CharField(max_length=20, choices=DELIVERY_METHODS, default='easy_move')
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    # Vetting
    requested_vetting = models.BooleanField(default=False)
    vetting_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    vetting_completed = models.BooleanField(default=False)
    vetting_notes = models.TextField(blank=True)

    # Total
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)

    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    payment_method = models.CharField(max_length=20, blank=True, null=True)  # wave/qmoney/afrimoney/verve/waychit
    payment_reference = models.CharField(max_length=120, blank=True, null=True)
    paid_at = models.DateTimeField(blank=True, null=True)

    # Buyer Info (captured at order time)
    buyer_geocode = models.CharField(max_length=100, blank=True)
    buyer_phone = models.CharField(max_length=20)
    buyer_email = models.EmailField(blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Device tracking
    buyer_device = models.ForeignKey(
        'accounts.Device',
        on_delete=models.SET_NULL,
        null=True,
        related_name='crossroad_orders'
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['buyer', '-created_at']),
            models.Index(fields=['listing', '-created_at']),
            models.Index(fields=['status', '-created_at']),
        ]

    def __str__(self):
        return f"Order {self.order_id} - {self.buyer.username}"

    def save(self, *args, **kwargs):
        # Calculate totals
        self.subtotal = self.unit_price * self.quantity
        self.total_amount = self.subtotal + self.delivery_fee + self.vetting_fee

        # Update listing quantity sold when order is confirmed
        if self.status == 'confirmed' and not self.confirmed_at:
            self.confirmed_at = timezone.now()
            self.listing.quantity_sold += self.quantity
            self.listing.save()

        super().save(*args, **kwargs)

    def generate_receipt(self):
        """Generate receipt for this order"""
        return CrossroadReceipt.objects.create(order=self)


class CrossroadReceipt(models.Model):
    """
    Receipt for Crossroad order
    """
    receipt_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    order = models.OneToOneField(CrossroadOrder, on_delete=models.PROTECT, related_name='receipt')

    # Receipt details (snapshot at time of receipt generation)
    receipt_data = models.JSONField(help_text="Complete order details at receipt time")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Receipt {self.receipt_id}"


class CrossroadReview(models.Model):
    """
    Reviews for completed orders
    """
    order = models.OneToOneField(CrossroadOrder, on_delete=models.CASCADE, related_name='review')
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='crossroad_reviews_given'
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='crossroad_reviews_received'
    )

    # Rating
    rating = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="1-5 stars"
    )

    # Review
    title = models.CharField(max_length=200, blank=True)
    comment = models.TextField()

    # Product accuracy
    product_as_described = models.BooleanField(default=True)
    would_buy_again = models.BooleanField(default=True)

    # Flags
    is_flagged = models.BooleanField(default=False, help_text="Flagged for review")
    flagged_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['seller', '-created_at']),
            models.Index(fields=['rating']),
        ]

    def __str__(self):
        return f"{self.rating}⭐ - {self.seller.username} by {self.reviewer.username}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        # Check if seller should be suspended
        self.check_seller_suspension()

    def check_seller_suspension(self):
        """Check if seller should be suspended based on bad reviews"""
        config = CrossroadDealConfig.get_config()

        # Count recent bad reviews
        bad_reviews = CrossroadReview.objects.filter(
            seller=self.seller,
            rating__lte=config.review_rating_bad
        ).count()

        if bad_reviews >= config.bad_review_threshold:
            # Suspend all active listings
            CrossroadListing.objects.filter(
                seller=self.seller,
                status='active'
            ).update(status='suspended')

            # Create suspension record
            SellerSuspension.objects.create(
                seller=self.seller,
                reason='bad_reviews',
                bad_review_count=bad_reviews,
                auto_suspended=True
            )


class SellerSuspension(models.Model):
    """
    Track seller suspensions and bans
    """
    SUSPENSION_REASONS = [
        ('bad_reviews', 'Multiple Bad Reviews'),
        ('illegal_activity', 'Illegal Activity'),
        ('fraud', 'Fraudulent Behavior'),
        ('multiple_complaints', 'Multiple Complaints'),
        ('admin_decision', 'Admin Decision'),
    ]

    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='crossroad_suspensions'
    )

    reason = models.CharField(max_length=50, choices=SUSPENSION_REASONS)
    description = models.TextField()
    bad_review_count = models.PositiveIntegerField(default=0)

    is_permanent_ban = models.BooleanField(default=False)
    auto_suspended = models.BooleanField(default=False, help_text="Auto-suspended by system")

    suspended_at = models.DateTimeField(auto_now_add=True)
    suspended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='suspensions_issued'
    )

    # If temporary suspension
    suspended_until = models.DateTimeField(null=True, blank=True)
    is_lifted = models.BooleanField(default=False)
    lifted_at = models.DateTimeField(null=True, blank=True)
    lifted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='suspensions_lifted'
    )

    class Meta:
        ordering = ['-suspended_at']

    def __str__(self):
        return f"{self.seller.username} - {self.get_reason_display()}"


class DeviceActivityLog(models.Model):
    """
    Log all device activities for security and tracking
    """
    ACTION_TYPES = [
        ('listing_create', 'Created Listing'),
        ('listing_view', 'Viewed Listing'),
        ('order_create', 'Created Order'),
        ('order_view', 'Viewed Order'),
        ('payment_attempt', 'Payment Attempt'),
        ('review_submit', 'Submitted Review'),
    ]

    device = models.ForeignKey(
        'accounts.Device',
        on_delete=models.CASCADE,
        related_name='crossroad_activities'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='crossroad_device_activities'
    )

    action_type = models.CharField(max_length=30, choices=ACTION_TYPES)

    # Related objects
    listing = models.ForeignKey(
        CrossroadListing,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    order = models.ForeignKey(
        CrossroadOrder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    # Request data
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()

    # Metadata
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['device', '-created_at']),
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['action_type', '-created_at']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.get_action_type_display()}"


class ListingInterest(models.Model):
    """
    Track when users express interest in a listing
    (for privacy disclosure progression)
    """
    listing = models.ForeignKey(
        CrossroadListing,
        on_delete=models.CASCADE,
        related_name='interests'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='crossroad_interests'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    # ✅ negotiation fields
    offer_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    offer_note = models.TextField(blank=True, default="")

    class Meta:
        unique_together = ['listing', 'user']
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} interested in {self.listing.title}"
