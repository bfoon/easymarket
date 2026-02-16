from django.db import models
from django.contrib.auth.models import User
from django.conf import settings
from django.utils import timezone
from decimal import Decimal
import uuid
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models import F, Sum, DecimalField, ExpressionWrapper, Q
from django.db import IntegrityError, transaction
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _

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
    discount_type = models.CharField(
        max_length=20,
        choices=[
            ('percentage', 'Percentage'),
            ('fixed', 'Fixed Amount'),
            ('free_shipping', 'Free Shipping'),
        ],
        default='percentage'
    )
    discount_value = models.DecimalField(max_digits=10, decimal_places=2)
    min_purchase_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Minimum order total required"
    )
    max_uses = models.IntegerField(
        null=True,
        blank=True,
        help_text="Maximum number of times code can be used (null = unlimited)"
    )
    products = models.ManyToManyField('marketplace.Product', blank=True, related_name='promo_codes')
    is_active = models.BooleanField(default=True)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    description = models.TextField(blank=True)
    usage_limit = models.PositiveIntegerField(default=0, help_text="0 means unlimited")
    usage_count = models.PositiveIntegerField(default=0)

    # ========== NEW FIELDS FOR WHEEL INTEGRATION ==========

    source = models.CharField(
        max_length=50,
        choices=[
            ('manual', 'Manual Creation'),
            ('campaign_wheel', 'Campaign Wheel Prize'),
            ('bulk_import', 'Bulk Import'),
            ('api', 'API Generated'),
            ('affiliate', 'Affiliate Program'),
            ('loyalty', 'Loyalty Reward'),
        ],
        default='manual',
        db_index=True,
        help_text="How this promo code was created"
    )

    campaign = models.ForeignKey(
        'marketplace.Campaign',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='generated_promo_codes',  # Changed from 'promo_codes'
        help_text="Associated campaign (if from wheel)"
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_promo_codes',
        help_text="Admin user who created this code"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ========== OPTIONAL ADVANCED RESTRICTION FIELDS ==========
    # Only add these if you need them - they provide fine-grained control

    first_purchase_only = models.BooleanField(
        default=False,
        help_text="Only valid for user's first purchase"
    )

    allowed_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='exclusive_promo_codes',
        help_text="If set, only these users can use this code"
    )

    excluded_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='excluded_from_promo_codes',
        help_text="Users who cannot use this code"
    )

    # FIXED: Changed field names to avoid clash with existing 'products' field
    valid_for_products = models.ManyToManyField(
        'marketplace.Product',
        blank=True,
        related_name='restricted_promo_codes',  # Different related_name
        help_text="If set, code only applies to these specific products"
    )

    valid_for_categories = models.ManyToManyField(
        'marketplace.Category',
        blank=True,
        related_name='category_promo_codes',  # Clear related_name
        help_text="If set, code only applies to products in these categories"
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Promo Code"
        verbose_name_plural = "Promo Codes"
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['is_active', 'valid_from', 'valid_until']),
            models.Index(fields=['source']),
            models.Index(fields=['campaign']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.code} ({self.get_discount_type_display()})"

    def is_valid(self, user=None, cart_total=None, cart_items=None):
        """
        Check if promo code is valid for use.

        Args:
            user: User attempting to use the code
            cart_total: Current cart total (Decimal)
            cart_items: QuerySet of cart items (for product restrictions)

        Returns:
            tuple: (is_valid: bool, error_message: str or None)
        """
        # Check if active
        if not self.is_active:
            return False, "This promo code is not active."

        # Check date validity
        now = timezone.now()
        if self.valid_from and now < self.valid_from:
            return False, "This promo code is not yet valid."
        if self.valid_until and now > self.valid_until:
            return False, "This promo code has expired."

        # Check usage limit
        if self.max_uses and self.uses >= self.max_uses:
            return False, "This promo code has reached its usage limit."

        # Check minimum purchase
        if cart_total and cart_total < self.min_purchase_amount:
            return False, f"Minimum purchase of D{self.min_purchase_amount} required."

        # User-specific validations
        if user:
            # Check if user is excluded
            if self.excluded_users.filter(id=user.id).exists():
                return False, "You are not eligible for this promo code."

            # Check if only certain users allowed
            if self.allowed_users.exists() and not self.allowed_users.filter(id=user.id).exists():
                return False, "This promo code is not available to you."

            # Check first purchase only
            if self.first_purchase_only:
                from orders.models import Order
                if Order.objects.filter(user=user, status='completed').exists():
                    return False, "This code is only valid for first-time customers."

        # Product restrictions
        if cart_items:
            # If specific products are set, at least one cart item must match
            if self.valid_for_products.exists():
                cart_product_ids = set(cart_items.values_list('product_id', flat=True))
                allowed_product_ids = set(self.valid_for_products.values_list('id', flat=True))

                if not cart_product_ids.intersection(allowed_product_ids):
                    return False, "This code is not valid for the products in your cart."

            # If specific categories are set, at least one cart item must match
            if self.valid_for_categories.exists():
                from marketplace.models import Product
                cart_products = Product.objects.filter(
                    id__in=cart_items.values_list('product_id', flat=True)
                )
                cart_category_ids = set(cart_products.values_list('category_id', flat=True))
                allowed_category_ids = set(self.valid_for_categories.values_list('id', flat=True))

                if not cart_category_ids.intersection(allowed_category_ids):
                    return False, "This code is not valid for the categories in your cart."

        # Check if wheel prize already redeemed
        if self.source == 'campaign_wheel':
            if hasattr(self, 'wheel_spin') and self.wheel_spin:
                if self.wheel_spin.is_redeemed:
                    return False, "This wheel prize has already been used."

                # Verify user owns this prize (if user is authenticated)
                if user and self.wheel_spin.user and self.wheel_spin.user != user:
                    return False, "This prize belongs to another user."

        return True, None

    def calculate_discount(self, cart_total, shipping_cost=None):
        """
        Calculate the discount amount for this promo code.

        Args:
            cart_total: Total cart value (Decimal)
            shipping_cost: Shipping cost (Decimal), if applicable

        Returns:
            dict: {
                'cart_discount': Decimal,
                'shipping_discount': Decimal,
                'total_discount': Decimal,
                'final_cart_total': Decimal,
                'final_shipping_cost': Decimal,
            }
        """
        cart_discount = Decimal('0')
        shipping_discount = Decimal('0')

        if self.discount_type == 'percentage':
            # Percentage discount on cart
            cart_discount = (cart_total * self.discount_value / Decimal('100')).quantize(Decimal('0.01'))

        elif self.discount_type == 'fixed':
            # Fixed amount discount on cart (not exceeding cart total)
            cart_discount = min(self.discount_value, cart_total)

        elif self.discount_type == 'free_shipping':
            # Free shipping
            if shipping_cost:
                shipping_discount = shipping_cost

        total_discount = cart_discount + shipping_discount
        final_cart_total = max(cart_total - cart_discount, Decimal('0'))
        final_shipping_cost = max((shipping_cost or Decimal('0')) - shipping_discount, Decimal('0'))

        return {
            'cart_discount': cart_discount,
            'shipping_discount': shipping_discount,
            'total_discount': total_discount,
            'final_cart_total': final_cart_total,
            'final_shipping_cost': final_shipping_cost,
        }

    def increment_usage(self):
        """Increment the usage counter atomically"""
        from django.db.models import F
        PromoCode.objects.filter(pk=self.pk).update(uses=F('uses') + 1)
        self.refresh_from_db()

    def get_usage_percentage(self):
        """Get usage as percentage (if max_uses is set)"""
        if not self.max_uses:
            return None
        return (self.uses / self.max_uses) * 100 if self.max_uses > 0 else 0

    @property
    def is_expired(self):
        """Check if code is expired"""
        if not self.valid_until:
            return False
        return timezone.now() > self.valid_until

    @property
    def is_from_wheel(self):
        """Check if this code came from campaign wheel"""
        return self.source == 'campaign_wheel'

    @property
    def days_until_expiry(self):
        """Get days until expiration"""
        if not self.valid_until:
            return None
        delta = self.valid_until - timezone.now()
        return max(delta.days, 0)

    @property
    def is_fully_used(self):
        """Check if code has reached usage limit"""
        if not self.max_uses:
            return False
        return self.uses >= self.max_uses

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

    payment_date = models.DateTimeField(blank=True, null=True)

    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.0'))
    shipping_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    promo_code = models.ForeignKey('orders.PromoCode', on_delete=models.SET_NULL, null=True, blank=True)

    expected_delivery_date = models.DateField(blank=True, null=True)
    shipped_date = models.DateTimeField(blank=True, null=True)
    delivered_date = models.DateTimeField(blank=True, null=True)

    # ✅ Tracking number like EM0000000001
    tracking_number = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        unique=True,
        db_index=True
    )

    # GPS Coordinates for delivery location (if not already present)
    shipping_latitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        help_text="Delivery location latitude"
    )
    shipping_longitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        help_text="Delivery location longitude"
    )

    shipping_address = models.ForeignKey('orders.ShippingAddress', on_delete=models.SET_NULL, blank=True, null=True)

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

    # NEW: currency used when entering order-level money fields (shipping/discount)
    order_currency = models.ForeignKey(
        'accounts.Currency',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders_priced_in',
        help_text="Currency used when setting shipping/discount (conversion tracking)"
    )

    # OPTIONAL (recommended): save the rate used at the time of conversion
    order_fx_rate = models.DecimalField(
        max_digits=18,
        decimal_places=8,
        default=Decimal('1.0'),
        help_text="FX rate snapshot used when converting to GMD"
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Order #{self.id} - {self.buyer.username}"

    def _get_base_currency(self):
        from accounts.models import Currency
        base = Currency.objects.filter(is_base_currency=True, is_active=True).first()
        if not base:
            base = Currency.objects.filter(code='GMD', is_active=True).first()
        return base

    def _determine_source_currency(self, user, base_currency):
        # Priority: existing order_currency (updates) -> user pref -> buyer pref -> base
        if self.pk and self.order_currency:
            return self.order_currency

        if user and getattr(user, 'preferred_currency', None):
            self.order_currency = user.preferred_currency
            return user.preferred_currency

        if self.buyer and getattr(self.buyer, 'preferred_currency', None):
            self.order_currency = self.buyer.preferred_currency
            return self.buyer.preferred_currency

        self.order_currency = base_currency
        return base_currency

    def _convert_amount(self, amount: Decimal, from_code: str, to_code: str):
        from accounts.currency_utils import convert_currency
        if amount is None:
            return None
        try:
            result = convert_currency(amount, from_code, to_code)
            if result.get('success'):
                fx = result.get('rate')
                # ✅ only set snapshot once (or if it’s still 1.0)
                if fx and (not self.order_fx_rate or self.order_fx_rate == Decimal("1.0")):
                    self.order_fx_rate = Decimal(str(fx))
                return Decimal(str(result['converted_amount']))
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Order currency conversion failed {from_code}->{to_code}: {e}")
        return amount

    def _snapshot_convert_from_gmd(self, amount_gmd: Decimal, target_currency=None):
        """
        Convert a GMD amount to order_currency using the stored order_fx_rate snapshot.

        Assumes order_fx_rate = GMD per 1 unit of order_currency.
        """
        amount_gmd = Decimal(amount_gmd or 0)

        base = self._get_base_currency()
        base_code = base.code if base else "GMD"

        # If no currency tracked, return GMD
        if not self.order_currency or not self.order_fx_rate or self.order_fx_rate in [Decimal("0"), Decimal("0.0")]:
            return amount_gmd, base_code

        # If caller wants a different currency than order_currency, fallback to live conversion
        # (Optional: if you ONLY want order currency always, remove this block)
        if target_currency and getattr(target_currency, "code",
                                       None) and target_currency.code != self.order_currency.code:
            from accounts.currency_utils import convert_currency
            r = convert_currency(amount_gmd, base_code, target_currency.code)
            amt2 = r["converted_amount"] if r.get("success") else amount_gmd
            return Decimal(amt2), target_currency.code

        # Snapshot conversion to order_currency
        if self.order_currency.code == base_code:
            return amount_gmd, base_code

        amt_foreign = (amount_gmd / self.order_fx_rate).quantize(Decimal("0.01"))
        return amt_foreign, self.order_currency.code

    def get_shipping_cost_in_currency(self, user=None, currency_code=None):
        from accounts.models import Currency
        from accounts.currency_utils import format_price

        base = self._get_base_currency()
        base_code = base.code if base else "GMD"

        # Default target: user currency, else order currency, else base
        target = None
        if currency_code:
            target = Currency.objects.filter(code=currency_code, is_active=True).first()
        elif user and getattr(user, 'preferred_currency', None):
            target = user.preferred_currency
        elif self.order_currency:
            target = self.order_currency
        else:
            target = base

        amt_gmd = Decimal(self.shipping_cost or 0)

        # ✅ If target equals order_currency, use snapshot conversion (locked)
        if self.order_currency and target and target.code == self.order_currency.code and target.code != base_code:
            amt2, code = self._snapshot_convert_from_gmd(amt_gmd, target_currency=target)
            return {'amount': amt2, 'currency_code': code, 'formatted': format_price(amt2, code)}

        # Otherwise: show in base (or optionally live convert to other currency)
        if target and target.code == base_code:
            return {'amount': amt_gmd.quantize(Decimal("0.01")), 'currency_code': base_code,
                    'formatted': format_price(amt_gmd, base_code)}

        # OPTIONAL: if you still want user preferred currency != order currency, allow live conversion
        from accounts.currency_utils import convert_currency
        r = convert_currency(amt_gmd, base_code, target.code)
        amt2 = Decimal(str(r['converted_amount'])) if r.get('success') else amt_gmd
        amt2 = amt2.quantize(Decimal("0.01"))
        return {'amount': amt2, 'currency_code': target.code, 'formatted': format_price(amt2, target.code)}

    def display_amount(self, amount_gmd: Decimal, user=None, currency_code=None):
        from accounts.models import Currency
        from accounts.currency_utils import format_price

        base = self._get_base_currency()
        base_code = base.code if base else "GMD"

        # pick target
        if currency_code:
            target = Currency.objects.filter(code=currency_code, is_active=True).first()
        elif user and getattr(user, 'preferred_currency', None):
            target = user.preferred_currency
        elif self.order_currency:
            target = self.order_currency
        else:
            target = base

        amount_gmd = Decimal(amount_gmd or 0)

        # snapshot if showing in order currency
        if self.order_currency and target and target.code == self.order_currency.code and target.code != base_code:
            amt2, code = self._snapshot_convert_from_gmd(amount_gmd, target_currency=target)
            return {'amount': amt2, 'currency_code': code, 'formatted': format_price(amt2, code)}

        # base display
        if target and target.code == base_code:
            amt2 = amount_gmd.quantize(Decimal("0.01"))
            return {'amount': amt2, 'currency_code': base_code, 'formatted': format_price(amt2, base_code)}

        # optional live convert for other currencies
        from accounts.currency_utils import convert_currency
        r = convert_currency(amount_gmd, base_code, target.code)
        amt2 = Decimal(str(r['converted_amount'])) if r.get('success') else amount_gmd
        amt2 = amt2.quantize(Decimal("0.01"))
        return {'amount': amt2, 'currency_code': target.code, 'formatted': format_price(amt2, target.code)}

    def get_subtotal(self):
        return sum(item.get_total_price() for item in self.items.all())

    def get_tax_amount(self):
        return self.get_subtotal() * (self.tax_rate / 100)

    @property
    def is_auction_order(self):
        return self.source_type == 'auction'

    @property
    def get_total(self):
        subtotal = Decimal(self.get_subtotal() or 0)
        tax = Decimal(self.get_tax_amount() or 0)
        shipping = Decimal(self.shipping_cost or 0)
        discount = Decimal(self.discount_amount or 0)
        total = subtotal + tax + shipping - discount
        return total.quantize(Decimal("0.01"))

    def get_item_count(self):
        return sum(item.quantity for item in self.items.all())

    def can_be_cancelled(self):
        return self.status in ['pending', 'processing']

    def can_be_tracked(self):
        return (
            (self.status in ['shipped', 'delivered'] or self.shipments.filter(status='in_transit').exists())
            and self.tracking_number
        )

    def is_completed(self):
        return self.status == 'delivered'

    def get_subtotal_with_tax_and_shipping(self):
        subtotal = self.get_subtotal()
        tax = self.get_tax_amount()
        shipping = self.shipping_cost or Decimal('0')
        return subtotal + tax + shipping

    def get_payment_method_display(self):
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
        self.status = 'shipped'
        # NOTE: your code references collect_time but the field isn't in the model you pasted.
        # If you meant shipped_date, use this:
        if not self.shipped_date:
            self.shipped_date = timezone.now()
        self.save(update_fields=['status', 'shipped_date', 'updated_at'])

    @property
    def is_in_transit(self):
        return self.shipments.filter(status='in_transit').exists()

    def get_shipment_count(self):
        """Get total number of shipments for this order"""
        return self.shipments.count()

    def get_next_shipment_number(self):
        """Get the next shipment number for this order (1, 2, 3, etc.)"""
        return self.shipments.count() + 1

    def has_unshipped_items(self):
        """Check if there are items not yet shipped to warehouse"""
        return self.items.filter(shipped_to_warehouse=False).exists()

    def get_shipped_items_without_shipment(self):
        """Get items marked as shipped but not yet in a shipment"""
        return self.items.filter(
            shipped_to_warehouse=True,
            current_shipment__isnull=True
        )

    def can_create_shipment(self):
        """Check if a new shipment can be created"""
        return self.get_shipped_items_without_shipment().exists()

    def save(self, *args, **kwargs):
        user = kwargs.pop('user', None)  # allow: order.save(user=request.user)

        base_currency = self._get_base_currency()
        if base_currency:
            source_currency = self._determine_source_currency(user, base_currency)

            # Convert ONLY if not already base
            if source_currency and source_currency.code != base_currency.code:
                if self.shipping_cost is not None:
                    self.shipping_cost = self._convert_amount(
                        Decimal(self.shipping_cost),
                        source_currency.code,
                        base_currency.code
                    )
                if self.discount_amount is not None:
                    self.discount_amount = self._convert_amount(
                        Decimal(self.discount_amount),
                        source_currency.code,
                        base_currency.code
                    )

        is_new = self.pk is None

        # Status-based timestamps (only on updates)
        if not is_new:
            old = Order.objects.filter(pk=self.pk).only('status', 'shipped_date', 'delivered_date').first()
            if old and old.status != self.status:
                if self.status == 'shipped' and not self.shipped_date:
                    self.shipped_date = timezone.now()
                elif self.status == 'delivered' and not self.delivered_date:
                    self.delivered_date = timezone.now()

        # First save to get an ID
        super().save(*args, **kwargs)

        # ✅ Generate tracking number after we have self.pk
        if not self.tracking_number:
            tracking = f"EM{self.pk:010d}"  # EM0000000001

            # Safe update (avoids recursion) and helps prevent overwriting
            Order.objects.filter(pk=self.pk, tracking_number__isnull=True).update(tracking_number=tracking)
            self.tracking_number = tracking


class OrderItem(models.Model):
    """
    Order item with automatic shipped_at timestamp.
    When shipped_to_warehouse changes to True, shipped_at is automatically set.
    """

    order = models.ForeignKey('orders.Order', on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('marketplace.Product', related_name='order_items', on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    selected_features = models.JSONField(blank=True, null=True)
    price_at_time = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)

    # Discount fields
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

    # Warehouse shipping tracking
    shipped_to_warehouse = models.BooleanField(default=False)
    shipped_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Automatically set when shipped_to_warehouse becomes True"
    )

    # Track which shipment this item is in
    current_shipment = models.ForeignKey(
        'logistics.Shipment',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='current_items',
        help_text="The shipment this item is currently assigned to"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['order', 'product']

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"

    def save(self, *args, **kwargs):
        """
        Override save to automatically set shipped_at when shipped_to_warehouse becomes True.
        """
        # Check if this is an update (has pk) and shipped_to_warehouse changed to True
        if self.pk:
            try:
                # Get the old instance from database
                old_instance = OrderItem.objects.get(pk=self.pk)

                # If shipped_to_warehouse changed from False to True
                if not old_instance.shipped_to_warehouse and self.shipped_to_warehouse:
                    # Automatically set shipped_at timestamp
                    if not self.shipped_at:
                        self.shipped_at = timezone.now()

            except OrderItem.DoesNotExist:
                # New instance, skip check
                pass
        else:
            # New instance being created
            # If already marked as shipped, set timestamp
            if self.shipped_to_warehouse and not self.shipped_at:
                self.shipped_at = timezone.now()

        # Lock in snapshot price if missing
        if self.price_at_time is None:
            self.price_at_time = self.product.price

        # Run validations
        self.full_clean()
        super().save(*args, **kwargs)

    # Pricing helpers
    @property
    def base_unit_price(self) -> Decimal:
        p = self.price_at_time if self.price_at_time is not None else self.product.price
        return (p if isinstance(p, Decimal) else Decimal(str(p))).quantize(Decimal('0.01'))

    def get_unit_discount_amount(self) -> Decimal:
        if self.discount_type == self.DISCOUNT_PERCENT:
            pct = max(Decimal('0'), min(Decimal('100'), self.discount_value or Decimal('0')))
            return (self.base_unit_price * pct / Decimal('100')).quantize(Decimal('0.01'))
        elif self.discount_type == self.DISCOUNT_AMOUNT:
            amt = max(Decimal('0.00'), self.discount_value or Decimal('0.00'))
            return min(amt, self.base_unit_price).quantize(Decimal('0.01'))
        return Decimal('0.00')

    @property
    def discounted_unit_price(self) -> Decimal:
        return (self.base_unit_price - self.get_unit_discount_amount()).quantize(Decimal('0.01'))

    def get_total_price(self) -> Decimal:
        return (self.discounted_unit_price * self.quantity).quantize(Decimal('0.01'))


class ShippingAddress(models.Model):
    """
    Shipping address with geolocation support for precise delivery tracking.

    Supports multiple location capture methods:
    - Manual entry with optional postal code geocoding
    - GPS device location with accuracy tracking
    - Geocoded from address using Google Maps API
    """

    # Location Method Choices
    LOCATION_METHOD_CHOICES = [
        ('manual', 'Manual Entry'),
        ('gps', 'GPS Device'),
        ('geocoded', 'Geocoded from Address'),
    ]

    # Basic Information
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='shipping_addresses',
        verbose_name=_("User")
    )

    # Contact Details
    full_name = models.CharField(
        max_length=100,
        verbose_name=_("Full Name"),
        help_text=_("Recipient's full name")
    )

    phone_number = models.CharField(
        max_length=20,
        validators=[
            RegexValidator(
                regex=r'^\+?1?\d{7,15}$',
                message=_("Phone number must be in format: '+220XXXXXXX' or '7XXXXXXX'")
            )
        ],
        verbose_name=_("Phone Number"),
        help_text=_("Contact phone number for delivery")
    )

    # Address Fields
    street = models.CharField(
        max_length=255,
        verbose_name=_("Street Address"),
        help_text=_("House number and street name, or landmark description")
    )

    city = models.CharField(
        max_length=100,
        verbose_name=_("City"),
        help_text=_("City or town name")
    )

    region = models.CharField(
        max_length=100,
        verbose_name=_("Region/State"),
        help_text=_("Administrative region or state")
    )

    postal_code = models.CharField(
        max_length=20,
        blank=True,
        verbose_name=_("Postal Code"),
        help_text=_("Postal code or area code for geocoding")
    )

    country = models.CharField(
        max_length=100,
        default="The Gambia",
        verbose_name=_("Country")
    )

    # Geolocation Fields
    latitude = models.DecimalField(
        max_digits=11,
        decimal_places=8,
        null=True,
        blank=True,
        verbose_name=_("Latitude"),
        help_text=_("GPS latitude coordinate (e.g., 13.4549153)")
    )

    longitude = models.DecimalField(
        max_digits=11,
        decimal_places=8,
        null=True,
        blank=True,
        verbose_name=_("Longitude"),
        help_text=_("GPS longitude coordinate (e.g., -16.5790323)")
    )

    location_accuracy = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Location Accuracy"),
        help_text=_("GPS accuracy in meters")
    )

    location_method = models.CharField(
        max_length=20,
        choices=LOCATION_METHOD_CHOICES,
        default='manual',
        verbose_name=_("Location Method"),
        help_text=_("How the location was captured")
    )

    geocoded_address = models.TextField(
        blank=True,
        verbose_name=_("Geocoded Address"),
        help_text=_("Full formatted address from geocoding service")
    )

    is_gambia = models.BooleanField(
        default=False,
        verbose_name=_("Is in Gambia"),
        help_text=_("Whether this address is within The Gambia boundaries")
    )

    location_timestamp = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Location Timestamp"),
        help_text=_("When the GPS location was captured")
    )

    # Additional Fields
    delivery_instructions = models.TextField(
        blank=True,
        verbose_name=_("Delivery Instructions"),
        help_text=_("Additional notes for delivery driver (landmarks, gate color, etc.)")
    )

    is_default = models.BooleanField(
        default=False,
        verbose_name=_("Default Address"),
        help_text=_("Set as default delivery address")
    )

    # Timestamps
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Created At")
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Updated At")
    )

    class Meta:
        verbose_name = _("Shipping Address")
        verbose_name_plural = _("Shipping Addresses")
        ordering = ['-is_default', '-created_at']
        indexes = [
            models.Index(fields=['user', '-is_default']),
            models.Index(fields=['is_gambia']),
            models.Index(fields=['location_method']),
        ]

    def __str__(self):
        return f"{self.full_name} - {self.street}, {self.city}"

    def save(self, *args, **kwargs):
        """Override save to ensure only one default address per user."""
        if self.is_default:
            # Set all other addresses for this user to non-default
            ShippingAddress.objects.filter(
                user=self.user,
                is_default=True
            ).exclude(pk=self.pk).update(is_default=False)

        super().save(*args, **kwargs)

    @property
    def has_coordinates(self):
        """Check if address has valid GPS coordinates."""
        return self.latitude is not None and self.longitude is not None

    @property
    def coordinates(self):
        """Return coordinates as tuple (lat, lng) or None."""
        if self.has_coordinates:
            return (float(self.latitude), float(self.longitude))
        return None

    @property
    def accuracy_status(self):
        """Return human-readable accuracy status."""
        if not self.location_accuracy:
            return "Unknown"

        accuracy = float(self.location_accuracy)
        if accuracy <= 20:
            return "Excellent"
        elif accuracy <= 50:
            return "Good"
        elif accuracy <= 100:
            return "Fair"
        else:
            return "Poor"

    @property
    def short_address(self):
        """Return shortened address for display."""
        return f"{self.street}, {self.city}"

    @property
    def full_address(self):
        """Return full formatted address."""
        parts = [
            self.street,
            self.city,
            self.region,
            self.country
        ]
        if self.postal_code:
            parts.insert(-1, self.postal_code)

        return ", ".join(filter(None, parts))

    def get_location_method_display_icon(self):
        """Return icon class for location method."""
        icons = {
            'manual': 'fa-keyboard',
            'gps': 'fa-map-marker-alt',
            'geocoded': 'fa-search-location'
        }
        return icons.get(self.location_method, 'fa-map-marker')

    def calculate_distance_to(self, other_address):
        """
        Calculate distance in kilometers to another address with coordinates.
        Uses Haversine formula.
        """
        if not self.has_coordinates or not other_address.has_coordinates:
            return None

        from math import radians, cos, sin, asin, sqrt

        lat1, lon1 = self.coordinates
        lat2, lon2 = other_address.coordinates

        # Convert to radians
        lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])

        # Haversine formula
        dlon = lon2 - lon1
        dlat = lat2 - lat1
        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        c = 2 * asin(sqrt(a))

        # Radius of earth in kilometers
        km = 6371 * c
        return round(km, 2)


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
    tracking_number = models.CharField(max_length=100, unique=True, blank=True, null=True)
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
        constraints = [
            models.CheckConstraint(check=Q(total_return_amount__gte=0), name='return_total_nonneg'),
            models.CheckConstraint(check=Q(discount_applied__gte=0), name='return_discount_nonneg'),
            models.CheckConstraint(check=Q(refund_amount__gte=0), name='return_refund_nonneg'),
            models.CheckConstraint(check=Q(refund_amount__lte=F('total_return_amount')), name='refund_lte_total'),
        ]
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['buyer']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Return {self.return_number} - Order #{self.order.id}"


    # ---- Lifecycle helpers ----

    def save(self, *args, **kwargs):
        # Generate return number if not exists
        if not self.return_number:
            for _ in range(5):
                self.return_number = self.generate_return_number()
                try:
                    with transaction.atomic():
                        return super().save(*args, **kwargs)
                except IntegrityError:
                    self.return_number = None
            raise

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

    def move_to(self, new_status, changed_by=None, notes=''):
        old_status = self.status
        if old_status == new_status:
            return

        self.status = new_status
        now = timezone.now()

        if new_status == 'approved' and not self.approved_at:
            self.approved_at = now
        elif new_status == 'received' and not self.received_at_store_date:
            self.received_at_store_date = now
        elif new_status == 'completed' and not self.completed_at:
            self.completed_at = now

        self.save()

        ReturnStatusHistory.objects.create(
            return_request=self,
            status=new_status,
            changed_by=changed_by,
            notes=notes
        )

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

        line_total = ExpressionWrapper(
            F('price_at_return') * F('quantity'),
            output_field=DecimalField(max_digits=12, decimal_places=2)
        )
        total = (
                self.items
                .exclude(return_request__status__in=['rejected', 'cancelled'])
                .aggregate(total=Sum(line_total))['total'] or Decimal('0.00')
        )
        self.total_return_amount = q2(total)
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

    def clean(self):
        if self.discount_applied and self.discount_applied < 0:
            raise ValidationError("discount_applied cannot be negative.")
        if self.refund_amount and self.refund_amount < 0:
            raise ValidationError("refund_amount cannot be negative.")
        if self.refund_amount and self.total_return_amount and self.refund_amount > self.total_return_amount:
            raise ValidationError("refund_amount cannot exceed total_return_amount.")


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
        """
        Total qty already returned for this same OrderItem across all *other* return items,
        excluding cancelled/rejected returns and this row itself.
        """
        return (
                ReturnItem.objects
                .filter(order_item=self.order_item)
                .exclude(pk=self.pk)
                .exclude(return_request__status__in=['rejected', 'cancelled'])
                .aggregate(total=Sum('quantity'))['total'] or 0
        )

    @property
    def remaining_returnable_qty(self):
        """
        Max additional qty that can be returned for this OrderItem = ordered - previously returned.
        """
        original_qty = getattr(self.order_item, 'quantity', 0) or 0
        return max(original_qty - self.previously_returned_qty, 0)

    def save(self, *args, **kwargs):
        if not self.price_at_return:
            fallback_price = getattr(self.order_item, 'price_at_time', None) or getattr(self.product, 'price',
                                                                                        Decimal('0.00'))
            self.price_at_return = q2(fallback_price)
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.quantity <= 0:
            raise ValidationError("Quantity must be greater than zero.")
        if self.quantity > self.remaining_returnable_qty:
            raise ValidationError(f"Quantity exceeds remaining returnable quantity ({self.remaining_returnable_qty}).")


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
        with transaction.atomic():
            # Optionally: assert amount
            self.refund_amount = q2(self.refund_amount)
            # do gateway call here...
            self.status = 'processing'
            self.processed_by = processed_by
            self.processed_at = timezone.now()
            if transaction_id:
                self.transaction_id = transaction_id
            if gateway_response is not None:
                self.gateway_response = gateway_response
            self.save()

            # simulate success
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

def validate_image_size(f):
    max_mb = 5
    if f.size > max_mb * 1024 * 1024:
        raise ValidationError(f"Image too large (>{max_mb}MB).")

class ChatMessage(models.Model):
    order = models.ForeignKey('Order', on_delete=models.CASCADE, related_name='chat_messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    content = models.TextField(blank=True)
    image = models.ImageField(
        upload_to='chat/images/%Y/%m/%d/',
        blank=True, null=True,
        validators=[FileExtensionValidator(['jpg','jpeg','png','webp','gif']), validate_image_size]
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['created_at']              # oldest → newest; good if you auto-scroll bottom
        indexes = [                            # speed up queries
            models.Index(fields=['order', 'created_at']),
        ]

    def clean(self):
        if not self.content and not self.image:
            raise ValidationError("Message cannot be empty—type text or attach an image.")

    def __str__(self):
        return f"Message from {self.sender.username} for Order #{self.order.id}"


class CustomerComplaint(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    complaint = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)