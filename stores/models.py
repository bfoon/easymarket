from django.db import models
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal
from django.db.models import Avg, Sum, F, ExpressionWrapper, DecimalField
import uuid
import re
import random
import string
from django.db.models.signals import post_save
from django.dispatch import receiver
from PIL import Image
from django.contrib.auth import get_user_model
from marketplace.models import Product
import threading
from django.core.mail import send_mail
from django.core.validators import MinValueValidator, RegexValidator, MaxValueValidator
from django.contrib.postgres.fields import ArrayField

from django.apps import apps

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

    def get_followers_count(self):
        return self.storefollow_set.filter(is_active=True).count()

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

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='owned_stores'
    )
    managers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='StoreManager',
        through_fields=('store', 'user'),
        related_name='managed_stores',
        blank=True
    )

    store_type = models.CharField(
        max_length=20,
        choices=STORE_TYPE_CHOICES,
        default='individual'
    )
    category = models.ForeignKey(
        'StoreCategory',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    status = models.CharField(
        max_length=20,
        choices=STORE_STATUS_CHOICES,
        default='pending'
    )
    warehouse = models.OneToOneField(
        'stock.Warehouse',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='store',
        help_text="Store's inventory warehouse"
    )
    email = models.EmailField()
    email_verified = models.BooleanField(default=False)

    phone = models.CharField(max_length=20)
    website = models.URLField(blank=True, null=True)

    address_line_1 = models.CharField(max_length=255)
    address_line_2 = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100)
    region = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    country = models.CharField(max_length=100, default='Gambia')

    # Business / finance info
    business_registration_number = models.CharField(max_length=100, blank=True, null=True)
    tax_identification_number = models.CharField(max_length=100, blank=True, null=True)
    bank_account_number = models.CharField(max_length=100, blank=True, null=True)
    bank_name = models.CharField(max_length=100, blank=True, null=True)

    logo = models.ImageField(upload_to='store_logos/', blank=True, null=True)
    banner = models.ImageField(upload_to='store_banners/', blank=True, null=True)

    is_featured = models.BooleanField(default=False)
    allow_reviews = models.BooleanField(default=True)
    auto_approve_products = models.BooleanField(default=False)

    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('5.00')
    )
    minimum_order_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00')
    )

    processing_time = models.PositiveIntegerField(
        default=2,
        help_text="Days to process orders"
    )
    return_policy_days = models.PositiveIntegerField(
        default=30,
        help_text="Return policy in days"
    )

    # --- B2B / Wholesale fields ---
    allows_b2b = models.BooleanField(
        default=False,
        help_text="If enabled, this store can sell in the B2B marketplace."
    )
    is_b2b_only = models.BooleanField(
        default=False,
        help_text="If true, store appears ONLY in B2B listings (hidden from normal marketplace)."
    )
    is_international_supplier = models.BooleanField(
        default=False,
        help_text="Highlight this store as an international B2B supplier."
    )
    b2b_min_order_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Minimum order amount for B2B transactions (optional)."
    )
    b2b_description = models.TextField(
        blank=True,
        null=True,
        help_text="Short description for B2B buyers (MOQ, special terms, etc.)."
    )
    # 🔹 NEW FIELDS
    b2b_contact_email = models.EmailField(
        blank=True,
        null=True,
        help_text="Email address where B2B inquiries should be sent. Defaults to owner email if empty."
    )
    b2b_whatsapp_number = models.CharField(
        max_length=30,
        blank=True,
        help_text="WhatsApp number for B2B negotiations (include country code)."
    )

    B2B_CHANNEL_CHOICES = [
        ("email", "Email"),
        ("whatsapp", "WhatsApp"),
        ("both", "Email & WhatsApp"),
    ]
    b2b_preferred_channel = models.CharField(
        max_length=10,
        choices=B2B_CHANNEL_CHOICES,
        default="email",
        help_text="Preferred channel for B2B negotiations."
    )

    # # Social & marketing
    # facebook_url = models.URLField(blank=True, null=True)
    # twitter_url = models.URLField(blank=True, null=True)
    # instagram_url = models.URLField(blank=True, null=True)

    # Auctions
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

    # Risk / referrals
    accept_cash_risk = models.BooleanField(default=False)
    allow_referrals = models.BooleanField(
        default=False,
        help_text="Allow buyers to refer this store and earn rewards."
    )
    # ✅ Location / Geo
    geo_code = models.CharField(
        max_length=120,
        blank=True,
        null=True,
        help_text="Optional geo code. Accepts formats like '13.4543,-16.5775' or 'lat:13.45,lng:-16.57'"
    )

    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        blank=True,
        null=True,
        validators=[MinValueValidator(Decimal("-90.0")), MaxValueValidator(Decimal("90.0"))],
        help_text="Latitude (-90 to 90). Example: 13.454900"
    )

    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        blank=True,
        null=True,
        validators=[MinValueValidator(Decimal("-180.0")), MaxValueValidator(Decimal("180.0"))],
        help_text="Longitude (-180 to 180). Example: -16.579000"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    approved_at = models.DateTimeField(blank=True, null=True)

    # Theme Configuration
    THEME_CHOICES = [
        ('modern', 'Modern & Clean'),
        ('elegant', 'Elegant & Luxury'),
        ('vibrant', 'Vibrant & Bold'),
        ('minimal', 'Minimal & Simple'),
        ('dark', 'Dark Mode'),
        ('classic', 'Classic Business'),
        ('creative', 'Creative & Artistic'),
        ('professional', 'Professional Corporate'),
    ]

    LAYOUT_CHOICES = [
        ('grid', 'Grid Layout'),
        ('list', 'List Layout'),
        ('masonry', 'Masonry Layout'),
        ('carousel', 'Carousel Layout'),
    ]

    FONT_CHOICES = [
        ('inter', 'Inter (Modern Sans-Serif)'),
        ('roboto', 'Roboto (Clean & Professional)'),
        ('playfair', 'Playfair Display (Elegant Serif)'),
        ('montserrat', 'Montserrat (Bold & Modern)'),
        ('lato', 'Lato (Friendly & Readable)'),
        ('poppins', 'Poppins (Geometric & Modern)'),
        ('raleway', 'Raleway (Elegant Sans-Serif)'),
        ('merriweather', 'Merriweather (Classic Serif)'),
    ]

    COLOR_VALIDATOR = RegexValidator(
        regex=r'^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$',
        message='Enter a valid hex color code (e.g., #FF5733)'
    )

    # Theme & Branding
    theme_preset = models.CharField(
        max_length=20,
        choices=THEME_CHOICES,
        default='modern',
        help_text='Choose a pre-designed theme for your store'
    )

    # Color Scheme
    primary_color = models.CharField(
        max_length=7,
        default='#2563eb',
        validators=[COLOR_VALIDATOR],
        help_text='Main brand color (hex code)'
    )
    secondary_color = models.CharField(
        max_length=7,
        default='#64748b',
        validators=[COLOR_VALIDATOR],
        help_text='Secondary accent color'
    )
    accent_color = models.CharField(
        max_length=7,
        default='#f59e0b',
        validators=[COLOR_VALIDATOR],
        help_text='Accent color for highlights and CTAs'
    )
    background_color = models.CharField(
        max_length=7,
        default='#ffffff',
        validators=[COLOR_VALIDATOR],
        help_text='Main background color'
    )
    text_color = models.CharField(
        max_length=7,
        default='#1e293b',
        validators=[COLOR_VALIDATOR],
        help_text='Primary text color'
    )

    # Typography
    font_heading = models.CharField(
        max_length=20,
        choices=FONT_CHOICES,
        default='poppins',
        help_text='Font for headings and titles'
    )
    font_body = models.CharField(
        max_length=20,
        choices=FONT_CHOICES,
        default='inter',
        help_text='Font for body text'
    )

    # Layout & Display
    product_layout = models.CharField(
        max_length=20,
        choices=LAYOUT_CHOICES,
        default='grid',
        help_text='How products are displayed on your store page'
    )
    products_per_row = models.IntegerField(
        default=4,
        choices=[(2, '2 products'), (3, '3 products'), (4, '4 products'), (5, '5 products')],
        help_text='Number of products per row'
    )
    show_product_ratings = models.BooleanField(
        default=True,
        help_text='Display star ratings on product cards'
    )
    show_product_badges = models.BooleanField(
        default=True,
        help_text='Show "New", "Sale", "Bestseller" badges'
    )
    show_quick_view = models.BooleanField(
        default=True,
        help_text='Enable quick view button on products'
    )

    # Store Page Features
    show_store_description = models.BooleanField(
        default=True,
        help_text='Display store description on store page'
    )
    show_store_stats = models.BooleanField(
        default=True,
        help_text='Show total products, reviews, ratings'
    )
    show_social_links = models.BooleanField(
        default=True,
        help_text='Display social media links'
    )
    show_operating_hours = models.BooleanField(
        default=True,
        help_text='Display business hours on store page'
    )
    show_map_location = models.BooleanField(
        default=False,
        help_text='Show store location on map'
    )

    # Social Media Links
    facebook_url = models.URLField(blank=True, null=True, help_text='Facebook page URL')
    instagram_url = models.URLField(blank=True, null=True, help_text='Instagram profile URL')
    twitter_url = models.URLField(blank=True, null=True, help_text='Twitter/X profile URL')
    linkedin_url = models.URLField(blank=True, null=True, help_text='LinkedIn company page URL')
    youtube_url = models.URLField(blank=True, null=True, help_text='YouTube channel URL')
    tiktok_url = models.URLField(blank=True, null=True, help_text='TikTok profile URL')

    # Advanced Customization
    custom_css = models.TextField(
        blank=True,
        null=True,
        help_text='Add custom CSS to further customize your store appearance'
    )
    header_message = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text='Announcement message displayed at top of store (e.g., "Free shipping on orders over $50!")'
    )
    show_header_message = models.BooleanField(
        default=False,
        help_text='Display header announcement message'
    )

    # Banner Customization
    banner_overlay_opacity = models.IntegerField(
        default=30,
        choices=[(i, f'{i}%') for i in range(0, 101, 10)],
        help_text='Darkness of overlay on banner image'
    )
    banner_height = models.CharField(
        max_length=10,
        default='medium',
        choices=[
            ('small', 'Small (300px)'),
            ('medium', 'Medium (400px)'),
            ('large', 'Large (500px)'),
            ('xlarge', 'Extra Large (600px)'),
        ],
        help_text='Height of store banner'
    )

    # Call-to-Action Settings
    cta_button_text = models.CharField(
        max_length=50,
        default='Shop Now',
        help_text='Text for main call-to-action buttons'
    )
    cta_button_style = models.CharField(
        max_length=20,
        default='rounded',
        choices=[
            ('rounded', 'Rounded Corners'),
            ('square', 'Square Corners'),
            ('pill', 'Pill Shape'),
        ],
        help_text='Style of buttons throughout store'
    )

    # Product Card Styling
    product_card_style = models.CharField(
        max_length=20,
        default='shadow',
        choices=[
            ('shadow', 'Card with Shadow'),
            ('border', 'Card with Border'),
            ('minimal', 'Minimal (No Border)'),
            ('elevated', 'Elevated (Deep Shadow)'),
        ],
        help_text='Style of product cards'
    )
    product_image_shape = models.CharField(
        max_length=20,
        default='square',
        choices=[
            ('square', 'Square'),
            ('rounded', 'Rounded Corners'),
            ('circle', 'Circle'),
        ],
        help_text='Shape of product images'
    )

    # Animation & Effects
    enable_animations = models.BooleanField(
        default=True,
        help_text='Enable smooth animations and transitions'
    )
    enable_hover_effects = models.BooleanField(
        default=True,
        help_text='Enable hover effects on products and buttons'
    )
    enable_parallax_banner = models.BooleanField(
        default=False,
        help_text='Enable parallax scrolling effect on banner'
    )

    # Store Sections
    enable_featured_products = models.BooleanField(
        default=True,
        help_text='Show featured products section'
    )
    enable_new_arrivals = models.BooleanField(
        default=True,
        help_text='Show new arrivals section'
    )
    enable_best_sellers = models.BooleanField(
        default=True,
        help_text='Show best sellers section'
    )
    enable_testimonials = models.BooleanField(
        default=False,
        help_text='Show customer testimonials section'
    )

    # Trust Badges & Icons
    show_secure_checkout_badge = models.BooleanField(
        default=True,
        help_text='Display "Secure Checkout" badge'
    )
    show_free_shipping_badge = models.BooleanField(
        default=False,
        help_text='Display "Free Shipping" badge'
    )
    show_money_back_guarantee = models.BooleanField(
        default=False,
        help_text='Display "Money Back Guarantee" badge'
    )
    show_customer_support_badge = models.BooleanField(
        default=True,
        help_text='Display "24/7 Customer Support" badge'
    )

    # Mobile Optimization
    mobile_menu_style = models.CharField(
        max_length=20,
        default='bottom',
        choices=[
            ('bottom', 'Bottom Navigation'),
            ('sidebar', 'Sidebar Menu'),
            ('top', 'Top Dropdown'),
        ],
        help_text='Mobile navigation style'
    )

    # SEO & Marketing
    meta_title = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        help_text='Custom SEO title (leave blank to use store name)'
    )
    meta_description = models.CharField(
        max_length=160,
        blank=True,
        null=True,
        help_text='Custom SEO description'
    )
    meta_keywords = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text='SEO keywords (comma-separated)'
    )

    # Store Performance Settings
    enable_lazy_loading = models.BooleanField(
        default=True,
        help_text='Lazy load images for better performance'
    )
    enable_image_optimization = models.BooleanField(
        default=True,
        help_text='Automatically optimize images'
    )

    # Theme last updated tracker
    theme_updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Store'
        verbose_name_plural = 'Stores'
        indexes = [
            # ... existing indexes
            models.Index(fields=['theme_preset', 'status']),
            models.Index(fields=['product_layout']),
        ]


    def __str__(self):
        return self.name

    # ---------- PROPERTIES / HELPERS ----------

    @property
    def is_active_store(self):
        return self.status == 'active'

    @property
    def is_local(self):
        """
        Convenience flag to check if this is a local (Gambian) store.
        Useful when highlighting international suppliers in B2B views.
        """
        return self.country.strip().lower() in ['gambia', 'the gambia']

    def get_absolute_url(self):
        return reverse('stores:store_detail', kwargs={'slug': self.slug})

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
            total=Sum(
                ExpressionWrapper(
                    F('quantity') * F('price_at_time'),
                    output_field=DecimalField()
                )
            )
        )['total']
        return total or Decimal('0.00')

    def can_process_returns(self):
        return self.is_active_store and self.return_policy_days > 0

    def get_active_auctions(self):
        """Get active auctions for this store."""
        return self.auctions.filter(status='active')

    def get_auction_sales(self):
        """Get total auction sales for this store."""
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

        from .models import StoreFollow
        return StoreFollow.objects.filter(user=user, store=self, is_active=True).exists()

    def get_followers_count(self):
        from .models import StoreFollow
        return StoreFollow.objects.filter(store=self, is_active=True).count()

    def get_theme_colors(self):
        """Returns dictionary of theme colors for easy template access"""
        return {
            'primary': self.primary_color,
            'secondary': self.secondary_color,
            'accent': self.accent_color,
            'background': self.background_color,
            'text': self.text_color,
        }

    def get_font_urls(self):
        """Generate Google Fonts URLs for selected fonts"""
        fonts = set()
        if self.font_heading:
            fonts.add(self.font_heading.replace('_', '+'))
        if self.font_body:
            fonts.add(self.font_body.replace('_', '+'))

        font_map = {
            'inter': 'Inter:wght@300;400;500;600;700;800',
            'roboto': 'Roboto:wght@300;400;500;700',
            'playfair': 'Playfair+Display:wght@400;500;600;700',
            'montserrat': 'Montserrat:wght@300;400;500;600;700;800',
            'lato': 'Lato:wght@300;400;700',
            'poppins': 'Poppins:wght@300;400;500;600;700;800',
            'raleway': 'Raleway:wght@300;400;500;600;700',
            'merriweather': 'Merriweather:wght@300;400;700',
        }

        font_params = [font_map.get(f, f) for f in fonts if f in font_map]
        if font_params:
            return f"https://fonts.googleapis.com/css2?{'&'.join([f'family={f}' for f in font_params])}&display=swap"
        return None

    def get_banner_height_px(self):
        """Convert banner height choice to pixels"""
        height_map = {
            'small': '300px',
            'medium': '400px',
            'large': '500px',
            'xlarge': '600px',
        }
        return height_map.get(self.banner_height, '400px')

    def parse_geo_code(self):
        """
        Try to parse geo_code into (lat, lng).
        Supports:
          - "13.4543,-16.5775"
          - "lat:13.45,lng:-16.57"
          - "GEO:13.45,-16.57"
        Returns: (lat, lng) floats or (None, None)
        """
        if not self.geo_code:
            return (None, None)

        s = str(self.geo_code).strip()

        # match: "lat,lng"
        m = re.search(r"(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)", s)
        if m:
            try:
                return (float(m.group(1)), float(m.group(2)))
            except Exception:
                return (None, None)

        # match: "lat:xx ... lng:yy"
        m2 = re.search(r"lat[:\s]*(-?\d+(?:\.\d+)?).+lng[:\s]*(-?\d+(?:\.\d+)?)", s, flags=re.I)
        if m2:
            try:
                return (float(m2.group(1)), float(m2.group(2)))
            except Exception:
                return (None, None)

        return (None, None)

    @property
    def has_coordinates(self):
        return self.latitude is not None and self.longitude is not None

    @property
    def map_latlng(self):
        """
        Returns (lat, lng) for mapping.
        Priority: latitude/longitude fields, fallback: geo_code parsing.
        """
        if self.has_coordinates:
            return (float(self.latitude), float(self.longitude))

        lat, lng = self.parse_geo_code()
        if lat is not None and lng is not None:
            return (lat, lng)

        return (None, None)


    # ---------- NOTIFICATIONS / EMAILS ----------

    def notify_followers(self, notification_type, title, message, product=None, **kwargs):
        """
        Notify all users who follow this store with HTML emails.
        """
        from stores.models import StoreFollow, StoreNotification
        import threading
        from django.db import transaction

        followers = StoreFollow.objects.filter(store=self, is_active=True).select_related('user')

        notifications_to_create = []
        email_jobs = []  # collect jobs and run after DB commit

        for follow in followers:
            should_notify = (
                    (notification_type == 'new_product' and follow.notify_new_products) or
                    (notification_type in ['price_decrease', 'price_increase'] and follow.notify_price_changes) or
                    (notification_type == 'discount' and follow.notify_discounts)
            )

            if not should_notify:
                continue

            notifications_to_create.append(
                StoreNotification(
                    user=follow.user,
                    store=self,
                    product=product,
                    notification_type=notification_type,
                    title=title,
                    message=message,
                    old_price=kwargs.get('old_price'),
                    new_price=kwargs.get('new_price'),
                )
            )

            if follow.user.email:
                # run after transaction commits (prevents "email sent but DB rolled back" issues)
                email_jobs.append((follow.user.id, product.id if product else None, notification_type, title, kwargs))

        if notifications_to_create:
            StoreNotification.objects.bulk_create(notifications_to_create)

            def _run_emails():
                # start background threads AFTER commit
                for user_id, product_id, ntype, subj_title, extra in email_jobs:
                    t = threading.Thread(
                        target=self.send_html_notification_email,
                        args=(user_id, product_id, ntype, subj_title, extra),
                        daemon=True
                    )
                    t.start()

            transaction.on_commit(_run_emails)

        return len(notifications_to_create)

    # ============================================================================
    # EMAIL SENDING FUNCTION WITH HTML TEMPLATES (INSTANCE METHOD)
    # ============================================================================

    def send_html_notification_email(self, user_id, product_id, notification_type, title, extra_data):
        """
        Send HTML email notification to a user with ABSOLUTE image URLs.
        """
        from django.core.mail import EmailMultiAlternatives
        from django.template.loader import render_to_string
        from django.utils.html import strip_tags
        from django.conf import settings
        from django.contrib.auth import get_user_model
        from marketplace.models import Product
        import datetime
        import logging

        logger = logging.getLogger(__name__)
        User = get_user_model()

        try:
            user = User.objects.get(id=user_id)
            product = Product.objects.filter(id=product_id).select_related('category',
                                                                           'store').first() if product_id else None

            # Similar products
            similar_products = []
            if product and product.category:
                similar_products = Product.objects.filter(
                    category=product.category,
                    is_active=True,
                    store=self
                ).exclude(id=product.id).order_by('-created_at')[:3]

            # ============================================================
            # FIX 1: Better base URL building
            # ============================================================

            # Try to get base URL from settings
            # Priority: SITE_URL > SITE_DOMAIN > Fallback
            site_url = getattr(settings, 'SITE_URL', None)

            if site_url:
                # SITE_URL should be complete: 'https://yourdomain.com'
                base_url = site_url.rstrip('/')
            else:
                # Fallback to building from SITE_DOMAIN
                domain = getattr(settings, 'SITE_DOMAIN', 'localhost:8000')
                protocol = 'https' if getattr(settings, 'USE_HTTPS', False) else 'http'
                base_url = f"{protocol}://{domain}"

            # ============================================================
            # FIX 2: Improved absolutize function
            # ============================================================

            def absolutize(path_or_url):
                """Convert any path/URL to absolute URL for emails."""
                if not path_or_url:
                    return ""

                # Convert to string (handles ImageFieldFile objects)
                url_str = str(path_or_url)

                # If it has .url attribute (ImageField), get the URL
                if hasattr(path_or_url, 'url'):
                    url_str = path_or_url.url

                # Already absolute?
                if url_str.startswith('http://') or url_str.startswith('https://'):
                    return url_str

                # Ensure it starts with /
                if not url_str.startswith('/'):
                    url_str = '/' + url_str

                # Combine with base URL
                return f"{base_url}{url_str}"

            # ============================================================
            # FIX 3: Build URLs properly
            # ============================================================

            product_url = absolutize(product.get_absolute_url()) if product else ""
            store_url = absolutize(self.get_absolute_url())
            unsubscribe_url = absolutize('/account/notifications/')

            # ============================================================
            # FIX 4: Get product image with proper absolute URL
            # ============================================================

            product_image = ""
            if product:
                # Try display_image_url first (property that gets primary image)
                if hasattr(product, 'display_image_url') and product.display_image_url:
                    product_image = absolutize(product.display_image_url)
                # Fallback to main image field
                elif hasattr(product, 'image') and product.image:
                    product_image = absolutize(product.image)

            logger.info(f"Product image URL: {product_image}")  # Debug log

            # Template context
            context = {
                'user_name': user.get_full_name() or user.username,
                'store_name': self.name,
                'store_url': store_url,
                'unsubscribe_url': unsubscribe_url,
                'current_year': datetime.datetime.now().year,
                'title': title,
            }

            if product:
                context.update({
                    'product_name': product.name,
                    'product_description': product.description or '',
                    'product_url': product_url,
                    'product_image': product_image,  # Now absolute URL
                    'product_price': round(float(product.price), 2),
                    'original_price': round(float(product.original_price), 2) if product.original_price else None,
                    'discount_percentage': product.discount_percentage,
                })

                if hasattr(product, 'specifications') and product.specifications:
                    specs_lines = product.specifications.split('\n')
                    context['product_features'] = [line.strip() for line in specs_lines if line.strip()][:3]

            # Price change data
            if 'old_price' in extra_data and 'new_price' in extra_data:
                old_price = extra_data.get('old_price')
                new_price = extra_data.get('new_price')

                if old_price and new_price:
                    try:
                        old_price_float = float(old_price)
                        new_price_float = float(new_price)
                        savings = old_price_float - new_price_float
                        discount = ((savings / old_price_float) * 100) if old_price_float > 0 else 0

                        context.update({
                            'old_price': round(old_price_float, 2),
                            'new_price': round(new_price_float, 2),
                            'savings_amount': round(savings, 2),
                            'discount_percentage': round(discount, 1),
                        })
                    except (ValueError, TypeError) as e:
                        logger.error(f"Error processing prices: {e}")

            # ============================================================
            # FIX 5: Similar products with absolute URLs
            # ============================================================

            if similar_products:
                similar_list = []
                for p in similar_products:
                    # Get image URL
                    img_url = ""
                    if hasattr(p, 'display_image_url') and p.display_image_url:
                        img_url = absolutize(p.display_image_url)
                    elif hasattr(p, 'image') and p.image:
                        img_url = absolutize(p.image)

                    similar_list.append({
                        'name': p.name,
                        'price': round(float(p.price), 2),
                        'url': absolutize(p.get_absolute_url()),
                        'image': img_url,  # Absolute URL
                    })

                context['similar_products'] = similar_list

            # Select template
            template_map = {
                'new_product': 'emails/new_product_email.html',
                'price_decrease': 'emails/price_drop_email.html',
                'price_increase': 'emails/price_update_email.html',
            }
            template_name = template_map.get(notification_type, 'emails/new_product_email.html')

            # Render email
            html_content = render_to_string(template_name, context)
            text_content = strip_tags(html_content)

            # Send email
            subject = f"{self.name}: {title}"
            from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@easymarket.gm')

            email = EmailMultiAlternatives(subject, text_content, from_email, [user.email])
            email.attach_alternative(html_content, "text/html")
            email.send(fail_silently=False)

            logger.info(f"✅ Sent {notification_type} email to {user.email}")
            return True

        except Exception as e:
            logger.exception(f"❌ Failed to send HTML email (store={self.id}) to user_id={user_id}: {e}")
            return False

    # ---------- OVERRIDES ----------

    def save(self, *args, **kwargs):
        """
        Auto-set approved_at when store becomes active.
        Also: auto-fill latitude/longitude from geo_code if lat/lng missing.
        """
        # ✅ fill lat/lng from geo_code if missing
        if (self.latitude is None or self.longitude is None) and self.geo_code:
            lat, lng = self.parse_geo_code()
            if lat is not None and lng is not None:
                if self.latitude is None:
                    self.latitude = Decimal(str(lat))
                if self.longitude is None:
                    self.longitude = Decimal(str(lng))

        # existing approved_at logic
        if not self._state.adding:
            old_store = Store.objects.filter(pk=self.pk).first()
            if old_store and old_store.status != self.status and self.status == 'active' and not self.approved_at:
                self.approved_at = timezone.now()

        super().save(*args, **kwargs)


class B2BInquiry(models.Model):
    CHANNEL_CHOICES = [
        ("email", "Email"),
        ("whatsapp", "WhatsApp"),
        ("both", "Email + WhatsApp"),
    ]

    STATUS_CHOICES = [
        ("new", "New"),
        ("contacted", "Contacted"),
        ("closed", "Closed"),
    ]

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="b2b_inquiries")
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="b2b_inquiries")
    product = models.ForeignKey("marketplace.Product", on_delete=models.SET_NULL, null=True, blank=True)

    message = models.TextField()
    preferred_channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES, default="email")

    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="new")

    def __str__(self):
        return f"B2B Inquiry #{self.id} – {self.store.name}"

class StoreFavorite(models.Model):
    """
    Model representing a user's favorite store
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'store')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['store']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.user.username} favorites {self.store.name}"

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


class PromotionPlacement(models.TextChoices):
    HOMEPAGE_BANNER = "homepage_banner", "Homepage Banner"
    CATEGORY_FEATURE = "category_feature", "Category Feature"
    TRENDING_CAROUSEL = "trending_carousel", "Trending Carousel"
    PUSH_NOTIFICATION = "push_notification", "Push Notification"
    EMAIL_CAMPAIGN = "email_campaign", "Email Campaign"
    DEALS_PAGE = "deals_page", "Deals Page"
    STORE_SPOTLIGHT = "store_spotlight", "Store Spotlight"


class PromotionPlan(models.Model):
    """Config for what a subscription offers."""
    name = models.CharField(max_length=50, unique=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    duration_days = models.PositiveIntegerField(default=30)
    max_placements = models.PositiveIntegerField(default=1)
    max_concurrent_campaigns = models.PositiveIntegerField(default=1)
    max_products_per_campaign = models.PositiveIntegerField(default=8)

    def __str__(self):
        return f"{self.name} ({self.duration_days} days)"


class PromotionSubscription(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="promo_subscriptions")
    plan = models.ForeignKey(PromotionPlan, on_delete=models.PROTECT, related_name="subscriptions")
    allowed_placements = ArrayField(
        base_field=models.CharField(max_length=50, choices=PromotionPlacement.choices),
        default=list,
        blank=True,
        help_text="Which placements this subscription can use"
    )
    start_at = models.DateTimeField(default=timezone.now)
    end_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.store.name} → {self.plan.name} ({'active' if self.is_active else 'inactive'})"

    def clean(self):
        super().clean()
        if self.end_at <= self.start_at:
            from django.core.exceptions import ValidationError
            raise ValidationError("end_at must be after start_at")

    @property
    def active(self):
        now = timezone.now()
        return self.is_active and self.start_at <= now <= self.end_at

    def active_campaigns_count(self):
        now = timezone.now()
        return self.campaigns.filter(
            status__in=[PromotionCampaign.Status.APPROVED, PromotionCampaign.Status.LIVE],
            scheduled_at__lte=now,
            expires_at__gt=now
        ).count()


class PromotionCampaign(models.Model):
    class Audience(models.TextChoices):
        ALL_BUYERS = "all_buyers", "All Buyers"
        STORE_FOLLOWERS = "store_followers", "Store Followers"
        SUBSCRIBERS = "subscribers", "Email Subscribers"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING = "pending", "Pending Review"
        APPROVED = "approved", "Approved"
        LIVE = "live", "Live"
        REJECTED = "rejected", "Rejected"
        EXPIRED = "expired", "Expired"

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="promo_campaigns")
    subscription = models.ForeignKey(PromotionSubscription, on_delete=models.PROTECT, related_name="campaigns")
    placement = models.CharField(max_length=50, choices=PromotionPlacement.choices)
    audience = models.CharField(max_length=50, choices=Audience.choices, default=Audience.ALL_BUYERS)

    title = models.CharField(max_length=120)
    headline = models.CharField(max_length=180)
    message = models.TextField()
    # Optional creative/banner image path if you handle uploads separately
    banner_image = models.ImageField(upload_to="promotions/banners/", blank=True, null=True)

    scheduled_at = models.DateTimeField()
    expires_at = models.DateTimeField()

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_campaigns"
    )
    review_note = models.CharField(max_length=255, blank=True)
    products = models.ManyToManyField(
        'marketplace.Product',  # adjust if your Product lives elsewhere
        related_name='promotion_campaigns',
        blank=True,
        help_text="Products featured in this campaign"
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["placement", "status"]),
            models.Index(fields=["scheduled_at", "expires_at"]),
        ]

    def __str__(self):
        return f"{self.store.name} – {self.title} ({self.get_status_display()})"

    def clean(self):
        super().clean()
        if self.expires_at <= self.scheduled_at:
            from django.core.exceptions import ValidationError
            raise ValidationError("expires_at must be after scheduled_at")

    @property
    def is_live_window(self):
        now = timezone.now()
        return self.scheduled_at <= now < self.expires_at

    def can_go_live(self):
        # Validate subscription & placement eligibility
        if not self.subscription.active:
            return False, "Subscription inactive or expired."
        if self.placement not in (self.subscription.allowed_placements or []):
            return False, "Placement not allowed for this subscription."
        # Enforce plan concurrency
        if self.subscription.active_campaigns_count() >= self.subscription.plan.max_concurrent_campaigns:
            return False, "Max concurrent campaigns reached for this plan."
        # Time window
        if not self.is_live_window:
            return False, "Campaign not in live window."
        return True, ""

    def validate_products(self):
        """Ensure all products belong to this campaign's store."""
        qs = self.products.all().select_related('store')
        invalid = [p.id for p in qs if getattr(p, 'store_id', None) != self.store_id]
        if invalid:
            from django.core.exceptions import ValidationError
            raise ValidationError(f"Some products do not belong to store {self.store_id}: {invalid}")

from .b2b.models import *  # noqa
