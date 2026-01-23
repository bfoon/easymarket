from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.db.models import Avg, F
from decimal import Decimal
from django.utils import timezone
import os, uuid, secrets, string, random
from django.utils.text import slugify
from django.db import transaction
from django.db.models.functions import Lower
from django.core.validators import FileExtensionValidator
from django.db.models import UniqueConstraint

# ============================================================
# HELPER FUNCTIONS (Add at module level, before models)
# ============================================================

def _generate_invite_code():
    """Generate unique invite code for social cart"""
    return secrets.token_urlsafe(10)


class Category(models.Model):
    name = models.CharField(max_length=100)
    icon = models.CharField(
        max_length=100,
        blank=True,
        help_text="Font Awesome or similar icon class (optional)"
    )
    description = models.TextField(blank=True)
    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        related_name='children',
        on_delete=models.SET_NULL
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ['name']
        indexes = [
            models.Index(fields=['parent']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

    def clean(self):
        """Validate the category to prevent circular references"""
        if self.parent:
            if self.parent == self:
                raise ValidationError("A category cannot be its own parent")

            # Check for circular references
            parent = self.parent
            ancestors = []
            while parent:
                if parent == self:
                    raise ValidationError("Circular reference detected in category hierarchy")
                if parent in ancestors:
                    raise ValidationError("Circular reference detected in parent hierarchy")
                ancestors.append(parent)
                parent = parent.parent

    def is_root(self):
        """Check if this category is a root category (has no parent)"""
        return self.parent is None

    def get_subcategories(self):
        """Get all direct children of this category"""
        return self.children.filter(is_active=True)

    def get_all_subcategories(self):
        """Get all descendants (children, grandchildren, etc.) of this category"""
        subcategories = []
        for child in self.children.filter(is_active=True):
            subcategories.append(child)
            subcategories.extend(child.get_all_subcategories())
        return subcategories

    def get_ancestors(self):
        """Get all ancestors (parent, grandparent, etc.) of this category"""
        ancestors = []
        current = self.parent
        while current:
            ancestors.append(current)
            current = current.parent
        return list(reversed(ancestors))

    def get_root(self):
        """Get the root category of this category's hierarchy"""
        current = self
        while current.parent:
            current = current.parent
        return current

    def get_breadcrumb_path(self):
        """Get the full path from root to this category"""
        ancestors = self.get_ancestors()
        ancestors.append(self)
        return ancestors

    def get_full_name(self):
        """Get the full hierarchical name (e.g., 'Electronics > Computers > Laptops')"""
        path = self.get_breadcrumb_path()
        return ' > '.join([category.name for category in path])

    def get_level(self):
        """Get the depth level of this category (root = 0)"""
        level = 0
        current = self.parent
        while current:
            level += 1
            current = current.parent
        return level

    def has_children(self):
        """Check if this category has any active children"""
        return self.children.filter(is_active=True).exists()

    def get_siblings(self):
        """Get all sibling categories (categories with the same parent)"""
        if self.parent:
            return self.parent.children.filter(is_active=True).exclude(pk=self.pk)
        else:
            return Category.objects.filter(parent=None, is_active=True).exclude(pk=self.pk)

    def get_absolute_url(self):
        """
        Default category URL used in menus.
        Using the pk-based route to avoid needing a slug field.
        """
        return reverse('marketplace:category_detail', kwargs={'pk': self.pk})

    def get_latest_product(self, include_descendants=True):
        """
        Return the most recently created active product in this category
        (and optionally in all its subcategories).
        """
        from .models import Product  # safe: resolved at runtime

        category_ids = [self.pk]
        if include_descendants:
            category_ids.extend(c.pk for c in self.get_all_subcategories())

        return (
            Product.objects
            .filter(category_id__in=category_ids, is_active=True)
            .order_by('-created_at')
            .first()
        )

    def get_latest_product_image_url(self, include_descendants=True):
        """
        Return the best image URL for the latest product:
        - primary ProductImage if available
        - else Product.image
        - else None
        """
        product = self.get_latest_product(include_descendants=include_descendants)
        if not product:
            return None

        # Use ProductImage if you have any
        primary = product.images.filter(is_primary=True).first()
        if primary and primary.image:
            try:
                return primary.image.url
            except ValueError:
                pass  # file missing

        # Fallback: the product's main image
        if product.image:
            try:
                return product.image.url
            except ValueError:
                pass

        return None

    @classmethod
    def get_root_categories(cls):
        """Get all root categories"""
        return cls.objects.filter(parent=None, is_active=True)

    @classmethod
    def get_tree(cls):
        """Get all categories organized in a tree structure"""

        def build_tree(parent=None):
            categories = cls.objects.filter(parent=parent, is_active=True)
            tree = []
            for category in categories:
                tree.append({
                    'category': category,
                    'children': build_tree(category)
                })
            return tree

        return build_tree()



    def get_product_count(self):
        """Get count of products in this category (assumes you have a Product model)"""
        # This method assumes you have a Product model with a category field
        # Uncomment and modify based on your Product model
        # return self.products.filter(is_active=True).count()
        pass

    def get_total_product_count(self):
        """Get count of products in this category and all subcategories"""
        # This method assumes you have a Product model with a category field
        # Uncomment and modify based on your Product model
        # count = self.get_product_count()
        # for subcategory in self.get_all_subcategories():
        #     count += subcategory.get_product_count()
        # return count
        pass

class ActiveProductManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)


class Product(models.Model):
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )
    name = models.CharField(max_length=200)
    category = models.ForeignKey(
        'Category',
        on_delete=models.SET_NULL,
        null=True
    )

    price = models.DecimalField(max_digits=1000, decimal_places=2)
    original_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True
    )

    # ===== NEW FIELD FOR CURRENCY CONVERSION =====
    price_currency = models.ForeignKey(
        'accounts.Currency',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products_priced_in',
        help_text="Currency used when setting the price (for conversion tracking)"
    )
    # ==============================================

    description = models.TextField(blank=True,
        null=True)
    specifications = models.TextField(blank=True,
        null=True)
    image = models.ImageField(upload_to='products/')
    video = models.FileField(
        upload_to='product_videos/',
        blank=True,
        null=True
    )

    # Visibility / marketing flags
    is_featured = models.BooleanField(default=False)
    is_trending = models.BooleanField(default=False)
    has_30_day_return = models.BooleanField(
        default=False,
        help_text="Enable if product is eligible for 30-day return policy."
    )
    free_shipping = models.BooleanField(default=False)
    used = models.BooleanField(default=False)
    sold_count = models.PositiveIntegerField(default=0)

    # Store relationship
    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.CASCADE,
        related_name='products',
        blank=True,
        null=True
    )
    is_active = models.BooleanField(default=True)

    # ---- B2C / B2B visibility flags ----
    visible_in_b2c = models.BooleanField(
        default=True,
        help_text="Show product on normal EasyMarket (retail) site."
    )
    visible_in_b2b = models.BooleanField(
        default=False,
        help_text="Show product in B2B marketplace for store-to-store buying."
    )

    # ---- B2B / wholesale settings ----
    is_available_b2b = models.BooleanField(
        default=False,
        help_text="If true, product can be sold wholesale via B2B."
    )
    b2b_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Default wholesale price per unit (if any)."
    )
    b2b_min_quantity = models.PositiveIntegerField(
        default=1,
        help_text="Minimum quantity for B2B orders."
    )
    b2b_tier_price = models.JSONField(
        null=True,
        blank=True,
        help_text=(
            'Optional tier pricing as a mapping of min_qty -> price. '
            'Example: {"10": "480.00", "50": "450.00"}'
        )
    )

    # Auction fields
    available_for_auction = models.BooleanField(default=True)
    auction_reserve_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )
    auction_starting_bid = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )
    sku = models.CharField(
        max_length=50,
        unique=True,
        editable=False,
        help_text="Auto-generated SKU in format: EM-XXXXXXXX"
    )

    active_campaign = models.ForeignKey(
        'Campaign',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products',
        help_text='Current active campaign for this product'
    )
    show_in_trending = models.BooleanField(
        default=False,
        help_text='Show in trending section (requires active trending campaign)'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    # ========== CURRENCY CONVERSION METHODS (NEW) ==========

    def _convert_prices_to_base_currency(self, user=None):
        """
        Convert price, original_price, b2b_price to GMD (base currency) if needed

        Args:
            user: User object to get currency preference from
        """
        from accounts.models import Currency
        from accounts.currency_utils import convert_currency

        # Get base currency (GMD)
        base_currency = Currency.objects.filter(is_base_currency=True, is_active=True).first()
        if not base_currency:
            base_currency = Currency.objects.filter(code='GMD', is_active=True).first()

        if not base_currency:
            # No base currency configured, cannot convert
            return

        # Determine source currency
        source_currency = self._determine_source_currency(user, base_currency)

        # If already in GMD, no conversion needed
        if source_currency.code == base_currency.code:
            return

        # Convert main price
        if self.price is not None:
            self.price = self._convert_price_field(
                self.price,
                source_currency.code,
                base_currency.code
            )

        # Convert original_price
        if self.original_price is not None:
            self.original_price = self._convert_price_field(
                self.original_price,
                source_currency.code,
                base_currency.code
            )

        # Convert B2B price
        if self.b2b_price is not None:
            self.b2b_price = self._convert_price_field(
                self.b2b_price,
                source_currency.code,
                base_currency.code
            )

        # Convert auction prices
        if self.auction_reserve_price is not None:
            self.auction_reserve_price = self._convert_price_field(
                self.auction_reserve_price,
                source_currency.code,
                base_currency.code
            )

        if self.auction_starting_bid is not None:
            self.auction_starting_bid = self._convert_price_field(
                self.auction_starting_bid,
                source_currency.code,
                base_currency.code
            )

        # Convert B2B tier pricing
        if self.b2b_tier_price:
            converted_tiers = {}
            for min_qty, tier_price in self.b2b_tier_price.items():
                converted_price = self._convert_price_field(
                    Decimal(str(tier_price)),
                    source_currency.code,
                    base_currency.code
                )
                converted_tiers[min_qty] = str(converted_price)
            self.b2b_tier_price = converted_tiers

    def _determine_source_currency(self, user, base_currency):
        """
        Determine which currency the price is currently in

        Priority (CORRECTED):
        1. Use user's preferred currency if provided (CRITICAL for correct updates)
        2. Use price_currency if already set (for updates without user context)
        3. Use seller's preferred currency (fallback)
        4. Assume base currency (GMD)
        """
        from accounts.models import Currency

        # Check user's preferred currency FIRST
        # This ensures when a GMD user updates a product, we know the input is in GMD
        if user and hasattr(user, 'preferred_currency') and user.preferred_currency:
            # Update price_currency to reflect current input currency
            self.price_currency = user.preferred_currency
            return user.preferred_currency

        # Check if this is an update and price_currency is set
        # Only use this if no user context was provided
        if self.pk and self.price_currency:
            return self.price_currency

        # Use seller's preferred currency
        if self.seller and hasattr(self.seller, 'preferred_currency') and self.seller.preferred_currency:
            self.price_currency = self.seller.preferred_currency
            return self.seller.preferred_currency

        # Default to base currency (GMD)
        self.price_currency = base_currency
        return base_currency

    def _convert_price_field(self, amount, from_code, to_code):
        """
        Convert a price amount from one currency to another

        Returns:
            Decimal: Converted amount or original amount if conversion fails
        """
        from accounts.currency_utils import convert_currency

        if amount is None:
            return amount

        try:
            result = convert_currency(amount, from_code, to_code)
            if result.get('success'):
                return result['converted_amount']
        except Exception as e:
            # Log error but don't fail the save
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Currency conversion failed for {from_code} to {to_code}: {e}")

        # Return original amount if conversion fails
        return amount

    def get_price_in_currency(self, currency_code=None, user=None):
        """
        Get the product price in a specific currency

        Args:
            currency_code: Target currency code (e.g., 'USD')
            user: User object (to use their preferred currency)

        Returns:
            dict: {'amount': Decimal, 'currency_code': str, 'formatted': str}
        """
        from accounts.models import Currency
        from accounts.currency_utils import convert_currency, format_price

        # Determine target currency
        if currency_code:
            try:
                target_currency = Currency.objects.get(code=currency_code, is_active=True)
            except Currency.DoesNotExist:
                target_currency = None
        elif user and hasattr(user, 'preferred_currency') and user.preferred_currency:
            target_currency = user.preferred_currency
        else:
            # Default to base currency
            target_currency = Currency.objects.filter(is_base_currency=True, is_active=True).first()

        if not target_currency:
            return {
                'amount': self.price,
                'currency_code': 'GMD',
                'formatted': f'D {self.price}'
            }

        # Get base currency (prices are stored in GMD)
        base_currency = Currency.objects.filter(is_base_currency=True, is_active=True).first()
        if not base_currency:
            base_currency = Currency.objects.filter(code='GMD', is_active=True).first()

        # Convert from GMD to target currency
        if base_currency.code == target_currency.code:
            amount = round(self.price, 2)
        else:
            result = convert_currency(round(self.price, 2), base_currency.code, target_currency.code)
            amount = result['converted_amount'] if result.get('success') else round(self.price, 2)

        return {
            'amount': round(amount, 2),
            'currency_code': target_currency.code,
            'formatted': format_price((round(amount, 2)) , currency_code=target_currency.code)
        }

    def get_display_price(self, user=None):
        """
        Get formatted price for display to user (in their preferred currency)

        Args:
            user: User object

        Returns:
            str: Formatted price string (e.g., "$12.50" or "D 625.00")
        """
        price_info = self.get_price_in_currency(user=user)
        return price_info['formatted']

    # ========== END CURRENCY CONVERSION METHODS ==========

    # ---------- AUCTION HELPERS ----------

    def create_auction(self, seller, starting_bid, end_date, **kwargs):
        from auction.models import Auction
        auction_data = {
            'title': self.name,
            'description': self.description,
            'starting_bid': starting_bid,
            'end_date': end_date,
            'seller': seller,
            'marketplace_product': self,
            'image': self.image,
            'shipping_cost': 0.00,
            **kwargs
        }
        return Auction.objects.create(**auction_data)

    # ---------- STOCK HELPERS ----------

    @property
    def stock(self):
        return self.stock_records.first()

    @property
    def stock_quantity(self):
        stock_record = self.stock
        return stock_record.quantity if stock_record else 0

    @property
    def is_in_stock(self):
        return self.stock_quantity > 0

    def get_stock_status(self):
        quantity = self.stock_quantity
        if quantity == 0:
            return "Out of Stock"
        elif quantity <= 5:
            return f"Low Stock ({quantity} remaining)"
        return f"In Stock ({quantity} available)"

    def reduce_stock(self, quantity):
        stock_record = self.stock
        if stock_record and stock_record.quantity >= quantity:
            stock_record.quantity -= quantity
            stock_record.save()
            return True
        return False

    def increase_stock(self, quantity):
        stock_record = self.stock
        if stock_record:
            stock_record.quantity += quantity
            stock_record.save()
        else:
            from stock.models import Stock
            Stock.objects.create(product=self, quantity=quantity)

    def get_or_create_stock(self):
        stock_record = self.stock
        if not stock_record:
            from stock.models import Stock
            stock_record = Stock.objects.create(product=self, quantity=0)
        return stock_record

    # ---------- URLS / META ----------

    def get_absolute_url(self):
        return reverse('marketplace:product_detail', kwargs={'product_id': self.pk})

    # ---------- RATINGS / REVIEWS ----------

    @property
    def average_rating(self):
        avg = self.reviews.aggregate(Avg('rating'))['rating__avg']
        return round(avg or 0, 1)

    @property
    def review_count(self):
        return self.reviews.count()

    # ---------- PRICING HELPERS ----------

    @property
    def discount_percentage(self):
        if self.original_price and self.original_price > self.price:
            return int(((self.original_price - self.price) / self.original_price) * 100)
        return None

    @property
    def amount_saved(self):
        if self.original_price and self.original_price > self.price:
            return self.original_price - self.price
        return Decimal('0.00')

    @property
    def is_new(self):
        from django.utils import timezone
        two_days_ago = timezone.now() - timezone.timedelta(days=2)
        return self.created_at >= two_days_ago

    @property
    def display_image_url(self):
        """
        Primary ProductImage -> first ProductImage -> Product.image
        """
        imgs = getattr(self, "_prefetched_objects_cache", {}).get("images")
        if imgs is not None:
            primary = next((im for im in imgs if im.is_primary), None)
            if primary and primary.image:
                return primary.image.url
            first = imgs[0] if len(imgs) else None
            if first and first.image:
                return first.image.url
        else:
            primary = self.images.filter(is_primary=True).first()
            if primary and primary.image:
                return primary.image.url
            first = self.images.first()
            if first and first.image:
                return first.image.url

        return self.image.url if self.image else ""

    def get_b2b_price_for_quantity(self, quantity):
        """
        Return the best B2B unit price for a given quantity using tier pricing if present,
        else fallback to b2b_price, else normal price.
        """
        if not self.is_available_b2b:
            return self.price

        if self.b2b_tier_price:
            applicable = []
            for min_qty_str, unit_price in self.b2b_tier_price.items():
                try:
                    min_qty = int(min_qty_str)
                except (TypeError, ValueError):
                    continue
                if quantity >= min_qty:
                    applicable.append((min_qty, Decimal(str(unit_price))))
            if applicable:
                applicable.sort(key=lambda x: x[0], reverse=True)
                return applicable[0][1]

        return self.b2b_price or self.price

    # ---------- IMAGES / COLORS ----------

    def get_image_for_color(self, color=None):
        from .models import ProductImage
        if color:
            color_image = ProductImage.get_primary_image_for_color(self, color)
            if color_image:
                return color_image.image
            color_images = ProductImage.get_images_by_color(self, color)
            if color_images.exists():
                return color_images.first().image
        return self.image

    def get_images_by_color(self, color=None):
        from .models import ProductImage
        return ProductImage.get_images_by_color(self, color)

    def get_available_image_colors(self):
        from .models import ProductImage
        return ProductImage.get_available_colors(self)

    def has_color_images(self):
        return self.images.filter(color__isnull=False).exists()

    # ---------- GENERATE SKU ----------
    @staticmethod
    def generate_sku():
        """
        Generate a unique SKU in format: EM-XXXXXXXX
        Where X is a random alphanumeric character (uppercase)
        """
        while True:
            random_part = ''.join(
                secrets.choice(string.ascii_uppercase + string.digits)
                for _ in range(8)
            )
            sku = f"EM-{random_part}"

            if not Product.objects.filter(sku=sku).exists():
                return sku

    @staticmethod
    def generate_sku_letters_only():
        """Generate SKU with only letters: EM-ABCDEFGH"""
        while True:
            random_part = ''.join(
                secrets.choice(string.ascii_uppercase)
                for _ in range(8)
            )
            sku = f"EM-{random_part}"
            if not Product.objects.filter(sku=sku).exists():
                return sku

    def generate_sku_with_id(self):
        """Generate SKU with ID: EM-12345-ABC"""
        if self.id:
            random_part = ''.join(
                secrets.choice(string.ascii_uppercase)
                for _ in range(3)
            )
            return f"EM-{self.id}-{random_part}"
        else:
            return self.generate_sku()

    # ---------- Campaign function----------

    def get_campaign_info(self):
        '''Get active campaign information for this product'''
        if self.active_campaign and self.active_campaign.is_running():
            try:
                campaign_product = self.campaign_products.get(campaign=self.active_campaign)
                return {
                    'campaign': self.active_campaign,
                    'campaign_price': campaign_product.get_campaign_price(),
                    'discount_percentage': campaign_product.get_discount_percentage(),
                    'discount_amount': campaign_product.get_discount_amount(),
                    'time_remaining': self.active_campaign.time_remaining(),
                }
            except CampaignProduct.DoesNotExist:
                pass
        return None

    def has_active_campaign(self):
        '''Check if product has an active campaign'''
        return self.active_campaign and self.active_campaign.is_running()

    # ========== MODIFIED SAVE METHOD WITH CURRENCY CONVERSION ==========

    def save(self, *args, **kwargs):
        """
        Enhanced save method with currency conversion

        Usage:
            # Creating/updating with user context
            product.price = 10  # User enters in their currency
            product.save(user=request.user)  # Converts to GMD

            # If no user provided, uses seller's currency preference
            product.save()
        """
        # Extract user from kwargs (used for currency conversion)
        user = kwargs.pop('user', None)

        # ===== CURRENCY CONVERSION HAPPENS FIRST =====
        # This converts all prices to GMD BEFORE any other processing
        self._convert_prices_to_base_currency(user)
        # =============================================

        # Generate SKU if it doesn't exist
        if not self.sku:
            self.sku = self.generate_sku()

        # Track changes for notifications
        is_new = self.pk is None
        changed_fields = []
        old_price = None

        if not is_new:
            try:
                old_instance = self.__class__.objects.get(pk=self.pk)
                old_price = old_instance.price  # This is already in GMD

                for field in self._meta.fields:
                    name = field.name
                    if name in ['updated_at', 'created_at']:
                        continue
                    old_val = getattr(old_instance, name)
                    new_val = getattr(self, name)
                    if old_val != new_val:
                        changed_fields.append(name)
            except self.__class__.DoesNotExist:
                pass

        # Call parent save (prices are now in GMD)
        super().save(*args, **kwargs)

        # Keep track of changed fields
        self._changed_fields = changed_fields or ['__created__']

        # ---- Store follower notifications: new product & price changes ----
        # All prices in notifications are in GMD
        if is_new and self.store:
            # Convert price to float for formatting (handles both Decimal and string)
            try:
                price_value = float(self.price) if self.price else 0.0
            except (ValueError, TypeError):
                price_value = 0.0

            # New product notification
            self.store.notify_followers(
                notification_type='new_product',
                title=f'New Product: {self.name}',
                message=f'Check out our latest product "{self.name}" now available for D{price_value:.2f}!',
                product=self
            )

        elif old_price is not None and old_price != self.price and self.store:
            # Price history (both prices are in GMD)
            from stores.models import ProductPriceHistory
            ProductPriceHistory.objects.create(
                product=self,
                old_price=old_price,
                new_price=self.price
            )

            # Convert prices to float for safe formatting
            try:
                old_price_val = float(old_price) if old_price else 0.0
                new_price_val = float(self.price) if self.price else 0.0
            except (ValueError, TypeError):
                old_price_val = 0.0
                new_price_val = 0.0

            # Store follower notifications on price change
            if self.price < old_price:
                # Calculate discount percentage safely
                if old_price_val > 0:
                    discount_percent = ((old_price_val - new_price_val) / old_price_val) * 100
                    discount_percent = round(discount_percent, 1)
                else:
                    discount_percent = 0.0

                self.store.notify_followers(
                    notification_type='price_decrease',
                    title=f'Price Drop: {self.name}',
                    message=f'Price dropped by {discount_percent}% from D{old_price_val:.2f} to D{new_price_val:.2f}!',
                    product=self,
                    old_price=old_price,
                    new_price=self.price
                )
            else:
                self.store.notify_followers(
                    notification_type='price_increase',
                    title=f'Price Update: {self.name}',
                    message=f'Price updated from D{old_price_val:.2f} to D{new_price_val:.2f}.',
                    product=self,
                    old_price=old_price,
                    new_price=self.price
                )

        # ---- Wishlist price change notifications (threaded / background) ----
        if old_price is not None and old_price != self.price:
            from marketplace.background import submit
            from .notifications import notify_wishlist_price_change_threadsafe

            old_p, new_p, product_id = old_price, self.price, self.pk

            # Ensure this only runs after the transaction commits successfully
            transaction.on_commit(
                lambda: submit(
                    notify_wishlist_price_change_threadsafe,
                    product_id,
                    old_p,
                    new_p
                )
            )

class ProductView(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    viewed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} viewed {self.product.name} on {self.viewed_at.strftime('%Y-%m-%d %H:%M')}"

    class Meta:
        unique_together = ('user', 'product')


class ProductFeature(models.Model):
    name = models.CharField(max_length=100)  # e.g. "Color", "Size"

    def __str__(self):
        return self.name


class ProductFeatureOption(models.Model):
    feature = models.ForeignKey(ProductFeature, related_name='options', on_delete=models.CASCADE)
    value = models.CharField(max_length=100)  # e.g. "Red", "Large"
    color_code = models.CharField(
        max_length=7,
        blank=True,
        null=True,
        help_text='Hex color code (e.g., #FF0000 for red)'
    )

    def clean(self):
        if self.feature.name.lower() == "color" and not self.color_code:
            raise ValidationError("Color variants must have a color code.")

    def __str__(self):
        return f"{self.feature.name}: {self.value}"


class ProductVariant(models.Model):
    product = models.ForeignKey('Product', related_name='variants', on_delete=models.CASCADE)
    feature_option = models.ForeignKey(ProductFeatureOption, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.product.name} - {self.feature_option}"



class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='product_images/')
    variants = models.ManyToManyField(
        ProductFeatureOption,
        blank=True,
        related_name='images',
        help_text="Variants this image represents (e.g., 'Red', 'Large', 'Cotton')"
    )
    is_primary = models.BooleanField(
        default=False,
        help_text="Set as primary image for these variants"
    )
    alt_text = models.CharField(
        max_length=200,
        blank=True,
        help_text="Alternative text for accessibility"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_primary', 'created_at']
        indexes = [
            models.Index(fields=['product', 'is_primary']),
        ]

    def __str__(self):
        variant_info = ""
        if self.variants.exists():
            variant_names = list(self.variants.values_list('value', flat=True))
            variant_info = f" ({', '.join(variant_names)})"
        primary_info = " [Primary]" if self.is_primary else ""
        return f"Image for {self.product.name}{variant_info}{primary_info}"

    def save(self, *args, **kwargs):
        # Auto-generate alt text if not provided
        if not self.alt_text:
            self.alt_text = f"{self.product.name}"

        super().save(*args, **kwargs)

        # Update alt text with variants after save (since M2M relations need the instance to exist)
        if self.variants.exists() and not self.alt_text.endswith(')'):
            variant_names = list(self.variants.values_list('value', flat=True))
            variant_part = f" ({', '.join(variant_names)})"
            self.alt_text = f"{self.product.name}{variant_part}"
            super().save(update_fields=['alt_text'])

    def get_variant_display(self):
        """Get a display string of all variants for this image"""
        if not self.variants.exists():
            return "No variants"

        # Group variants by feature
        variants_by_feature = {}
        for variant in self.variants.select_related('feature'):
            feature_name = variant.feature.name
            if feature_name not in variants_by_feature:
                variants_by_feature[feature_name] = []
            variants_by_feature[feature_name].append(variant.value)

        # Create display string
        display_parts = []
        for feature, values in variants_by_feature.items():
            display_parts.append(f"{feature}: {', '.join(values)}")

        return " | ".join(display_parts)

    def get_color_variants(self):
        """Get color variants specifically"""
        return self.variants.filter(feature__name__iexact='color')

    def get_size_variants(self):
        """Get size variants specifically"""
        return self.variants.filter(feature__name__iexact='size')

    @classmethod
    def get_images_by_variants(cls, product, variant_ids=None):
        """Get images that contain any of the specified variants"""
        queryset = cls.objects.filter(product=product)
        if variant_ids:
            return queryset.filter(variants__in=variant_ids).distinct()
        return queryset

    @classmethod
    def get_images_by_feature_value(cls, product, feature_name, value):
        """Get images for a specific feature value (e.g., color='Red')"""
        return cls.objects.filter(
            product=product,
            variants__feature__name__iexact=feature_name,
            variants__value__iexact=value
        ).distinct()

    @classmethod
    def get_primary_image_for_variants(cls, product, variant_ids=None):
        """Get the primary image for specific variants"""
        queryset = cls.objects.filter(product=product, is_primary=True)
        if variant_ids:
            return queryset.filter(variants__in=variant_ids).first()
        return queryset.first()

    @classmethod
    def get_available_variants(cls, product):
        """Get all variants that have images"""
        return ProductFeatureOption.objects.filter(
            images__product=product
        ).distinct().select_related('feature')

    @classmethod
    def get_images_without_variants(cls, product):
        """Get images that don't have any variants assigned"""
        return cls.objects.filter(
            product=product,
            variants__isnull=True
        )

    def set_as_primary_for_variants(self):
        """Set this image as primary and unset others with same variants"""
        if self.is_primary and self.variants.exists():
            variant_ids = list(self.variants.values_list('id', flat=True))

            # Find other images with overlapping variants
            overlapping_images = ProductImage.objects.filter(
                product=self.product,
                is_primary=True,
                variants__in=variant_ids
            ).exclude(pk=self.pk).distinct()

            # Unset them as primary
            overlapping_images.update(is_primary=False)


class Cart(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='cart')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username}'s Cart"

    def total_items(self, cart_type=None):
        """
        Get total item count
        cart_type: 'normal', 'social', or None for all items
        """
        items = self.items.all()
        if cart_type:
            items = items.filter(cart_type=cart_type)
        return sum(item.quantity for item in items)

    def total_price(self, cart_type=None):
        """
        Get total price
        cart_type: 'normal', 'social', or None for all items
        """
        items = self.items.all()
        if cart_type:
            items = items.filter(cart_type=cart_type)
        return sum(item.product.price * item.quantity for item in items)

    def get_normal_items(self):
        """Get items in normal cart"""
        return self.items.filter(cart_type='normal')

    def get_social_items(self):
        """Get items in social cart"""
        return self.items.filter(cart_type='social')

    def get_user_social_items(self, user):
        """Get social cart items added by specific user"""
        return self.items.filter(cart_type='social', added_by=user)

    def social_guard(self):
        """Check if social cart allows modifications"""
        social = getattr(self, 'social', None)
        if social and social.status in ('locked', 'closed', 'cancelled'):
            raise ValidationError("Cart is locked for checkout.")
        return social


# ============================================================
# UPDATE CartItem MODEL
# ============================================================

class CartItem(models.Model):
    """
    CartItem can belong to either 'normal' or 'social' cart type
    """
    CART_TYPE_CHOICES = [
        ('normal', 'Normal Cart'),
        ('social', 'Social Cart'),
    ]

    cart = models.ForeignKey('Cart', on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('Product', on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    selected_features = models.JSONField(default=dict, blank=True)

    # NEW: Specifies if item is in normal cart or social cart
    cart_type = models.CharField(
        max_length=10,
        choices=CART_TYPE_CHOICES,
        default='normal',
        help_text='Whether this item belongs to normal cart or social cart'
    )

    # Who added this item (important for social cart permissions)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='cart_items_added'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['cart', 'product', 'selected_features', 'cart_type'],
                name='uniq_cart_product_features_type'
            ),
        ]
        indexes = [
            models.Index(fields=['cart', 'cart_type']),
            models.Index(fields=['added_by']),
        ]

    def __str__(self):
        cart_label = f"[{self.cart_type.upper()}]"
        return f"{cart_label} {self.quantity} x {self.product.name}"

    def subtotal(self):
        return self.product.price * self.quantity

    def can_user_modify(self, user):
        """Check if user can modify (update/remove) this cart item"""
        # For normal cart items, only cart owner can modify
        if self.cart_type == 'normal':
            return self.cart.user == user

        # For social cart items
        if self.cart_type == 'social':
            social = getattr(self.cart, 'social', None)
            if not social or not social.is_active:
                return False

            # Owner can always modify
            if social.owner == user:
                return True

            # Check if user is blocked
            member = social.members.filter(user=user, status='joined').first()
            if not member:
                return False

            blocked_member = social.members.filter(user=user, status='blocked').first()
            if blocked_member:
                return False  # Blocked users cannot modify

            # Users can modify items they added
            return self.added_by == user

        return False

    @property
    def features_dict(self):
        import json
        sf = self.selected_features
        if isinstance(sf, str):
            try:
                return json.loads(sf)
            except Exception:
                return {}
        return sf or {}


# ============================================================
# UPDATE SocialCart MODEL
# ============================================================

class SocialCart(models.Model):
    SPLIT_BY_ITEMS = 'by_items'
    SPLIT_BY_PERCENT = 'by_percent'
    SPLIT_SINGLE_PAYER = 'single_payer'
    SPLIT_CHOICES = (
        (SPLIT_BY_ITEMS, 'Each pays their items'),
        (SPLIT_BY_PERCENT, 'Pay by percentage'),
        (SPLIT_SINGLE_PAYER, 'One person pays full'),
    )

    cart = models.OneToOneField('marketplace.Cart', on_delete=models.CASCADE, related_name='social')
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='owned_social_carts')

    # FIXED: Use function reference instead of lambda
    invite_code = models.CharField(max_length=64, unique=True, default=_generate_invite_code)

    is_active = models.BooleanField(default=True)
    status = models.CharField(max_length=20, default='open', choices=[
        ('open', 'Open'),
        ('checkout', 'Checkout In Progress'),
        ('locked', 'Locked'),
        ('closed', 'Closed'),
        ('cancelled', 'Cancelled'),
    ])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # NEW: Track when cart was completed/closed
    completed_at = models.DateTimeField(null=True, blank=True)

    # Split settings
    split_mode = models.CharField(max_length=20, choices=SPLIT_CHOICES, default=SPLIT_BY_ITEMS)
    single_payer = models.ForeignKey(
        'marketplace.CartMember',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='as_single_payer_for'
    )

    class Meta:
        indexes = [
            models.Index(fields=['is_active', 'status']),
            models.Index(fields=['owner']),
        ]

    def __str__(self):
        return f"Social Cart {self.id} - Owner: {self.owner.username}"

    def total(self) -> Decimal:
        """Calculate total for social cart items only"""
        subtotal = sum(
            (i.product.price * i.quantity for i in self.cart.items.filter(cart_type='social')),
            Decimal('0')
        )
        tax_rate = getattr(settings, "CART_TAX_RATE", Decimal("0.00"))
        return subtotal + (subtotal * tax_rate)

    def can_user_checkout(self, user):
        """Check if user can checkout this social cart"""
        # Only owner can checkout social cart
        return self.owner == user and self.is_active and self.status in ('open', 'checkout')

    def can_user_modify(self, user):
        """Check if user can add/modify items in social cart"""
        if not self.is_active or self.status not in ('open', 'checkout'):
            return False

        # Check if user is blocked
        member = self.members.filter(user=user, status='blocked').first()
        if member:
            return False

        # Owner and joined members can modify
        if self.owner == user:
            return True

        member = self.members.filter(user=user, status='joined').first()
        return bool(member)

    def can_user_view(self, user):
        """Check if user can view social cart (even if blocked)"""
        if self.owner == user:
            return True

        # Any member (including blocked) can view
        member = self.members.filter(user=user).first()
        return bool(member)

    def deactivate_and_create_orders(self):
        """
        Deactivate social cart and create individual orders for each member
        Called when: owner checks out OR owner leaves the cart
        """
        from orders.models import Order, OrderItem
        from django.db import transaction

        with transaction.atomic():
            # Mark as closed
            self.is_active = False
            self.status = 'closed'
            self.completed_at = timezone.now()
            self.save(update_fields=['is_active', 'status', 'completed_at', 'updated_at'])

            # Get all social cart items
            social_items = self.cart.items.filter(cart_type='social')

            # Group items by who added them
            items_by_user = {}
            for item in social_items:
                user = item.added_by or self.owner
                if user not in items_by_user:
                    items_by_user[user] = []
                items_by_user[user].append(item)

            # Create orders for each user
            created_orders = {}
            for user, items in items_by_user.items():
                if not items:
                    continue

                # Calculate total for this user's items
                total = sum(item.subtotal() for item in items)

                # Create order
                order = Order.objects.create(
                    user=user,
                    total_amount=total,
                    status='pending',
                    payment_status='pending',
                    source='social_cart',
                    notes=f'Order from Social Cart #{self.id}'
                )

                # Create order items
                for cart_item in items:
                    OrderItem.objects.create(
                        order=order,
                        product=cart_item.product,
                        quantity=cart_item.quantity,
                        price=cart_item.product.price,
                        selected_features=cart_item.selected_features
                    )

                created_orders[user] = order

            # Delete all social cart items (they're now in orders)
            social_items.delete()

            # Deactivate all members
            self.members.all().update(status='left')

            return created_orders

    def clear_active_shares(self):
        self.payment_shares.filter(is_active=True).update(is_active=False)

    def _member_for_user_id(self, user_id):
        return self.members.filter(user_id=user_id, status='joined').first()

    def compute_shares_by_items(self):
        """
        Each pays for the items they added. Falls back to owner if we can't map an item.
        """
        from django.db.models import Sum, F
        self.clear_active_shares()

        # Sum by added_by (user) for social cart items only
        lines = (
            self.cart.items.filter(cart_type='social')
            .select_related('added_by', 'product')
            .values('added_by_id')
            .annotate(amount=Sum(F('quantity') * F('product__price')))
        )

        # If no added_by is set, everything falls to owner
        owner_member = self.members.filter(user_id=self.owner_id, status='joined').first()

        for row in lines:
            uid = row['added_by_id']
            amt = row['amount'] or Decimal('0')
            member = self._member_for_user_id(uid) if uid else None
            if not member:
                member = owner_member
            if not member:
                continue

            from .models import PaymentShare
            PaymentShare.objects.update_or_create(
                social_cart=self, member=member,
                defaults={
                    'fixed_amount': None,
                    'percentage': None,
                    'items_total_amount': amt,
                    'amount_due': Decimal('0'),
                    'is_active': True,
                }
            )
        # Recalc
        self.recalc_members_due()

    def compute_shares_by_percentage(self, allocations: dict):
        """
        allocations: {member_id: percentage (0..100)}, must sum to 100.
        """
        self.clear_active_shares()

        total_pct = sum(Decimal(str(p or 0)) for p in allocations.values())
        if total_pct != Decimal('100'):
            raise ValueError("Percentages must sum to 100")

        from .models import PaymentShare
        # Create percentage shares only for members in allocations
        for member_id, pct in allocations.items():
            member = self.members.filter(id=member_id, status='joined').first()
            if not member:
                continue
            PaymentShare.objects.update_or_create(
                social_cart=self, member=member,
                defaults={
                    'fixed_amount': None,
                    'items_total_amount': None,
                    'percentage': Decimal(str(pct)),
                    'amount_due': Decimal('0'),
                    'is_active': True,
                }
            )
        self.recalc_members_due()

    def compute_shares_single_payer(self, payer_member_id: int):
        """
        One member pays full amount.
        """
        self.clear_active_shares()
        self.single_payer_id = payer_member_id
        self.save(update_fields=['single_payer'])

        total = self.total()
        payer = self.members.filter(id=payer_member_id, status='joined').first()
        if not payer:
            raise ValueError("Invalid single payer")

        from .models import PaymentShare
        # Give payer fixed_amount = total, others None
        for m in self.members.filter(status='joined'):
            if m.id == payer_member_id:
                PaymentShare.objects.update_or_create(
                    social_cart=self, member=m,
                    defaults={
                        'fixed_amount': total,
                        'percentage': None,
                        'items_total_amount': None,
                        'amount_due': Decimal('0'),
                        'is_active': True,
                    }
                )
            else:
                PaymentShare.objects.update_or_create(
                    social_cart=self, member=m,
                    defaults={
                        'fixed_amount': None,
                        'percentage': None,
                        'items_total_amount': None,
                        'amount_due': Decimal('0'),
                        'is_active': True,
                    }
                )
        self.recalc_members_due()

    def set_split_mode(self, mode: str, allocations: dict = None, payer_member_id: int = None):
        """
        Public helper to switch modes and recompute shares.
        """
        if mode not in dict(self.SPLIT_CHOICES):
            raise ValueError("Invalid split mode")

        self.split_mode = mode
        updates = ['split_mode']

        if mode == self.SPLIT_BY_ITEMS:
            self.single_payer = None
            updates.append('single_payer')
            self.save(update_fields=updates)
            self.compute_shares_by_items()

        elif mode == self.SPLIT_BY_PERCENT:
            self.single_payer = None
            updates.append('single_payer')
            self.save(update_fields=updates)
            self.compute_shares_by_percentage(allocations or {})

        elif mode == self.SPLIT_SINGLE_PAYER:
            self.save(update_fields=updates)
            if not payer_member_id:
                raise ValueError("payer_member_id is required for single_payer mode")
            self.compute_shares_single_payer(payer_member_id)

    def recalc_members_due(self):
        total = self.total()
        shares = self.payment_shares.filter(is_active=True)
        if not shares.exists():
            return

        perc_total = sum((s.percentage or Decimal('0')) for s in shares)
        fixed_total = sum((s.fixed_amount or Decimal('0')) for s in shares)
        items_total = sum((s.items_total_amount or Decimal('0')) for s in shares)

        remaining = total - (fixed_total + items_total)
        per_unit = Decimal('0')
        if perc_total and remaining > 0:
            per_unit = remaining / perc_total

        for s in shares:
            due = Decimal('0')
            if s.fixed_amount:
                due += s.fixed_amount
            if s.items_total_amount:
                due += s.items_total_amount
            if s.percentage:
                due += (s.percentage * per_unit)
            s.amount_due = max(due, Decimal('0'))
            s.save(update_fields=['amount_due'])

class CartActivity(models.Model):
    EVENT_CHOICES = [
        ("item_added", "Item Added"),
        ("item_removed", "Item Removed"),
        ("qty_changed", "Quantity Changed"),
        ("member_joined", "Member Joined"),
        ("member_left", "Member Left"),
        ("member_removed", "Member Removed"),
        ("invite_sent", "Invite Sent"),
        ("invite_accepted", "Invite Accepted"),
        ("member_approved", "Member Approved"),
        ("split_changed", "Split Changed"),
        ("share_changed", "Share Changed"),
    ]

    social_cart = models.ForeignKey("SocialCart", on_delete=models.CASCADE, related_name="activities")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    event = models.CharField(max_length=30, choices=EVENT_CHOICES)
    message = models.CharField(max_length=255, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    ACCESS_PUBLIC = "public"
    ACCESS_INVITE_ONLY = "invite_only"
    ACCESS_CHOICES = (
        (ACCESS_PUBLIC, "Public"),
        (ACCESS_INVITE_ONLY, "Invite Only"),
    )

    access_type = models.CharField(
        max_length=20,
        choices=ACCESS_CHOICES,
        default=ACCESS_PUBLIC,
        db_index=True,
        help_text="Public carts can be joined with link/QR. Invite-only carts require a valid invite."
    )

    scheduled_for = models.DateTimeField(
        null=True, blank=True,
        help_text="If set, this cart is scheduled to start at this time."
    )

    is_live = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Owner has come online for this social cart session."
    )

    live_started_at = models.DateTimeField(null=True, blank=True)

    def is_scheduled(self):
        return bool(self.scheduled_for)

    def is_join_allowed_now(self):
        """
        For invite-only scheduled carts: joining is allowed only from scheduled time onward (optional rule).
        Public carts can always join when open/checkout.
        """
        if self.status not in ("open", "checkout") or not self.is_active:
            return False
        if self.access_type == self.ACCESS_PUBLIC:
            return True
        # invite-only:
        if not self.scheduled_for:
            return True
        return timezone.now() >= self.scheduled_for

    class Meta:
        ordering = ["-id"]


class CartMember(models.Model):
    ROLE = (('owner', 'Owner'), ('editor', 'Editor'), ('viewer', 'Viewer'))
    STATUS = (
        ('pending', 'Pending'),
        ('invited', 'Invited'),
        ('joined', 'Joined'),
        ('left', 'Left'),
        ('blocked', 'Blocked')
    )

    social_cart = models.ForeignKey(SocialCart, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='social_cart_memberships')
    role = models.CharField(max_length=12, choices=ROLE, default='editor')
    status = models.CharField(max_length=12, choices=STATUS, default='joined')
    joined_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('social_cart', 'user')
        indexes = [
            models.Index(fields=['social_cart', 'status']),
            models.Index(fields=['user', 'status']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.social_cart.id} ({self.status})"

    def can_add_items(self):
        """Check if member can add items to social cart"""
        return (
                self.status == 'joined' and
                self.social_cart.is_active and
                self.social_cart.status in ('open', 'checkout')
        )

    def can_modify_items(self):
        """Check if member can modify items in social cart"""
        if self.status == 'blocked':
            return False
        return self.can_add_items()

# ============================================================
# UPDATE CartInvite MODEL (if not already fixed)
# ============================================================

class CartInvite(models.Model):
    social_cart = models.ForeignKey(SocialCart, on_delete=models.CASCADE, related_name='invites')

    # FIXED: Use function reference instead of lambda
    code = models.CharField(max_length=64, unique=True, default=_generate_invite_code)

    invited_email = models.EmailField(blank=True, null=True)
    invited_phone = models.CharField(max_length=50, blank=True, null=True)
    inviter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_cart_invites')
    accepted_by = models.ForeignKey(settings.AUTH_USER_MODEL, blank=True, null=True, on_delete=models.SET_NULL,
                                    related_name='accepted_cart_invites')
    status = models.CharField(max_length=12, default='pending',
                              choices=[('pending', 'Pending'), ('accepted', 'Accepted'), ('expired', 'Expired')])
    expires_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_valid(self):
        return self.status == 'pending' and (self.expires_at is None or self.expires_at > timezone.now())

# ============================================================
# PaymentShare MODEL
# ============================================================

class PaymentShare(models.Model):
    """
    A member's payment share in social cart
    """
    social_cart = models.ForeignKey(SocialCart, on_delete=models.CASCADE, related_name='payment_shares')
    member = models.ForeignKey(CartMember, on_delete=models.CASCADE, related_name='shares')
    percentage = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    fixed_amount = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    items_total_amount = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    amount_due = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('social_cart', 'member')
        indexes = [
            models.Index(fields=['social_cart', 'is_active']),
        ]

    def __str__(self):
        return f"Share for {self.member.user.username} in Cart {self.social_cart.id}"


class Contribution(models.Model):
    PROVIDERS = (
        ('wave','Wave'),
        ('qmoney','Qmoney'),
        ('afrimoney','Afrimoney'),
        ('gamswitch','Gamswitch'),
        ('cash','Cash'),
    )
    STATUS = (
        ('init','Initiated'), ('pending','Pending'), ('success','Success'),
        ('failed','Failed'), ('refunded','Refunded'),
    )
    social_cart = models.ForeignKey(SocialCart, on_delete=models.CASCADE, related_name='contributions')
    member = models.ForeignKey(CartMember, on_delete=models.CASCADE, related_name='contributions')
    provider = models.CharField(max_length=20, choices=PROVIDERS)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=12, choices=STATUS, default='init')
    provider_ref = models.CharField(max_length=120, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @staticmethod
    def total_paid_for_cart(social_cart_id):
        return Contribution.objects.filter(
            social_cart_id=social_cart_id, status='success'
        ).aggregate(s=models.Sum('amount'))['s'] or Decimal('0')

class Wishlist(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wishlist_items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='wishlisted_by')
    added_at = models.DateTimeField(auto_now_add=True)
    last_known_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    last_known_stock = models.IntegerField(default=0)

    class Meta:
        unique_together = ('user', 'product')  # Prevent duplicates

    def __str__(self):
        return f"{self.user} → {self.product}"

class CelebrityFeature(models.Model):
    celebrity_name = models.CharField(max_length=100)
    celebrity_title = models.CharField(max_length=200, blank=True)
    celebrity_image = models.ImageField(upload_to='celebrities/', blank=True, null=True)
    testimonial = models.TextField()
    products = models.ManyToManyField(Product, related_name='celebrity_features')
    is_active = models.BooleanField(default=True)
    featured_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    # Social media fields
    instagram_link = models.URLField(blank=True, null=True)
    twitter_link = models.URLField(blank=True, null=True)
    facebook_link = models.URLField(blank=True, null=True)
    youtube_link = models.URLField(blank=True, null=True)
    tiktok_link = models.URLField(blank=True, null=True)

    class Meta:
        ordering = ['featured_order', '-created_at']

    def __str__(self):
        return self.celebrity_name


class SearchHistory(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    query = models.CharField(max_length=255)
    results_count = models.IntegerField(default=0)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name_plural = 'Search histories'

    def __str__(self):
        return f"Search: {self.query} ({self.results_count} results)"


class PopularSearch(models.Model):
    query = models.CharField(max_length=255, unique=True)
    search_count = models.IntegerField(default=1)
    last_searched = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-search_count', '-last_searched']

    def __str__(self):
        return f"{self.query} ({self.search_count} searches)"

class SharedCart(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def get_absolute_url(self):
        return reverse('marketplace:copy_shared_cart', kwargs={'token': self.token})


class Subscription(models.Model):
    email = models.EmailField()
    subscribed_at = models.DateTimeField(default=timezone.now)
    active = models.BooleanField(default=True)
    source = models.CharField(max_length=100, blank=True, default="")  # e.g., 'footer', 'popup', 'checkout'

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower('email'),
                name='uniq_subscription_email_ci'
            )
        ]
        indexes = [
            models.Index(Lower('email'), name='idx_subscription_email_ci')
        ]

    def __str__(self):
        return self.email


class CareerQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

class Career(models.Model):
    class Department(models.TextChoices):
        ENGINEERING = "Engineering", "Engineering"
        LOGISTICS = "Logistics", "Logistics"
        OPERATIONS = "Operations", "Operations"
        CUSTOMER_SUPPORT = "Customer Support", "Customer Support"
        SALES_MARKETING = "Sales & Marketing", "Sales & Marketing"
        DESIGN = "Design", "Design"
        FINANCE = "Finance", "Finance"

    class EmploymentType(models.TextChoices):
        FULL_TIME = "Full-time", "Full-time"
        PART_TIME = "Part-time", "Part-time"
        CONTRACT = "Contract", "Contract"
        INTERN = "Internship", "Internship"

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    department = models.CharField(max_length=32, choices=Department.choices)
    location = models.CharField(max_length=120, default="Banjul, GM", help_text="City, Country or Remote")
    employment_type = models.CharField(max_length=16, choices=EmploymentType.choices, default=EmploymentType.FULL_TIME)
    remote_friendly = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    # Display chips in the careers list (e.g., ["Django","Postgres","Docker"])
    tags = models.JSONField(default=list, blank=True)

    # Content
    summary = models.TextField(blank=True, help_text="1–3 sentences shown at top of detail page")
    description = models.TextField(help_text="Full role description in HTML/Markdown allowed")
    responsibilities = models.JSONField(default=list, blank=True, help_text="List of bullet points")
    requirements = models.JSONField(default=list, blank=True, help_text="List of bullet points")
    benefits = models.JSONField(default=list, blank=True)

    # Meta
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CareerQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["is_active", "department"]),
            models.Index(fields=["slug"]),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:200]
            candidate = base
            i = 2
            while Career.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f"{base}-{i}"
                i += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("marketplace:career_detail", args=[self.slug])

def resume_upload_to(instance, filename):
    base, ext = os.path.splitext(filename.lower())
    ext = ext if ext in [".pdf", ".doc", ".docx"] else ".pdf"
    return f"careers/resumes/{instance.application_code}{ext}"

class CareerApplication(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "New"
        IN_REVIEW = "in_review", "In review"
        SHORTLISTED = "shortlisted", "Shortlisted"
        REJECTED = "rejected", "Rejected"
        HIRED = "hired", "Hired"

    application_code = models.CharField(max_length=20, unique=True, editable=False)
    job = models.ForeignKey("marketplace.Career", on_delete=models.CASCADE, related_name="applications")

    full_name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=50, blank=True)

    resume = models.FileField(
        upload_to=resume_upload_to,
        validators=[FileExtensionValidator(allowed_extensions=["pdf", "doc", "docx"])],
    )
    cover_letter = models.TextField(blank=True)
    portfolio_url = models.URLField(blank=True)
    linkedin_url = models.URLField(blank=True)
    github_url = models.URLField(blank=True)

    source = models.CharField(max_length=120, blank=True, help_text="How did you hear about us?")
    consent_privacy = models.BooleanField(default=False)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    notes = models.TextField(blank=True)

    # Basic tracking
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["application_code"]),
        ]

    def __str__(self):
        return f"{self.full_name} → {self.job.title}"

    def save(self, *args, **kwargs):
        if not self.application_code:
            # short readable token (8 chars from uuid)
            self.application_code = uuid.uuid4().hex[:8].upper()
        super().save(*args, **kwargs)



class PressReleaseQuerySet(models.QuerySet):
    def published(self):
        return self.filter(is_published=True, publish_at__lte=timezone.now())


def press_hero_upload(instance, filename):
    base, ext = os.path.splitext(filename.lower())
    return f"press/heroes/{instance.slug or slugify(instance.title)}{ext or '.jpg'}"


class PressRelease(models.Model):
    class Category(models.TextChoices):
        COMPANY = "company", "Company"
        PRODUCT = "product", "Product"
        PARTNERSHIP = "partnership", "Partnership"
        LOGISTICS = "logistics", "Logistics"
        FINANCE = "finance", "Finance"
        CSR = "csr", "CSR"
        OTHER = "other", "Other"

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    subtitle = models.CharField(max_length=240, blank=True)
    summary = models.TextField(help_text="1–3 sentences shown on listing.")
    body = models.TextField(help_text="Full body (HTML/Markdown allowed).")

    category = models.CharField(max_length=20, choices=Category.choices, default=Category.COMPANY)
    tags = models.JSONField(default=list, blank=True)

    author = models.CharField(max_length=120, blank=True)
    source_url = models.URLField(blank=True)

    hero_image = models.ImageField(upload_to=press_hero_upload, blank=True, null=True)

    # Publication
    is_published = models.BooleanField(default=False)
    publish_at = models.DateTimeField(default=timezone.now)

    # SEO (optional)
    meta_title = models.CharField(max_length=70, blank=True)
    meta_description = models.CharField(max_length=160, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PressReleaseQuerySet.as_manager()

    class Meta:
        ordering = ["-publish_at"]
        indexes = [
            models.Index(fields=["is_published", "publish_at"]),
            models.Index(fields=["slug"]),
            models.Index(fields=["category"]),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:200]
            candidate = base
            i = 2
            while PressRelease.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f"{base}-{i}"
                i += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("marketplace:press_detail", args=[self.slug])

    @property
    def display_meta_title(self):
        return self.meta_title or f"{self.title} | Press | EasyMarket"

# ---------- Investor Documents ----------
class InvestorDocumentQuerySet(models.QuerySet):
    def published(self):
        return self.filter(is_published=True, publish_at__lte=timezone.now())

def investor_doc_upload(instance, filename):
    base, ext = os.path.splitext(filename.lower())
    safe = slugify(instance.title)[:80]
    return f"investors/docs/{safe}{ext or '.pdf'}"

class InvestorDocument(models.Model):
    class Category(models.TextChoices):
        FINANCIAL_REPORT = "financial_report", "Financial Report"
        SHAREHOLDER_LETTER = "shareholder_letter", "Shareholder Letter"
        PRESENTATION = "presentation", "Presentation"
        GOVERNANCE = "governance", "Governance & Policies"
        PRESS_KIT = "press_kit", "Press Kit"
        OTHER = "other", "Other"

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    category = models.CharField(max_length=32, choices=Category.choices, default=Category.FINANCIAL_REPORT)
    summary = models.TextField(blank=True)
    file = models.FileField(upload_to=investor_doc_upload, blank=True, null=True)
    external_url = models.URLField(blank=True, help_text="Optional external link if file is hosted elsewhere.")
    is_published = models.BooleanField(default=True)
    publish_at = models.DateTimeField(default=timezone.now)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = InvestorDocumentQuerySet.as_manager()

    class Meta:
        ordering = ["-publish_at"]
        indexes = [
            models.Index(fields=["is_published", "publish_at"]),
            models.Index(fields=["slug"]),
            models.Index(fields=["category"]),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:200]
            cand, i = base, 2
            while InvestorDocument.objects.filter(slug=cand).exclude(pk=self.pk).exists():
                cand = f"{base}-{i}"; i += 1
            self.slug = cand
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("marketplace:investors_home") + f"#doc-{self.slug}"

    @property
    def download_url(self):
        return self.file.url if self.file else (self.external_url or "")


# ---------- Investor Events ----------
class InvestorEventQuerySet(models.QuerySet):
    def upcoming(self):
        return self.filter(start_at__gte=timezone.now()).order_by("start_at")
    def past(self):
        return self.filter(start_at__lt=timezone.now()).order_by("-start_at")

class InvestorEvent(models.Model):
    class EventType(models.TextChoices):
        EARNINGS = "earnings", "Earnings Call"
        AGM = "agm", "Annual General Meeting"
        INVESTOR_CALL = "investor_call", "Investor Call"
        OTHER = "other", "Other"

    title = models.CharField(max_length=180)
    event_type = models.CharField(max_length=32, choices=EventType.choices, default=EventType.OTHER)
    start_at = models.DateTimeField()
    end_at = models.DateTimeField(blank=True, null=True)
    location = models.CharField(max_length=140, blank=True)
    registration_url = models.URLField(blank=True)
    replay_url = models.URLField(blank=True)
    is_public = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    objects = InvestorEventQuerySet.as_manager()

    class Meta:
        ordering = ["start_at"]

    def __str__(self):
        return self.title


class Campaign(models.Model):
    """
    Marketing campaign model for flash promotions and special offers
    """

    class CampaignType(models.TextChoices):
        FLASH_SALE = "flash_sale", "Flash Sale"
        TRENDING = "trending", "Trending Promotion"
        SEASONAL = "seasonal", "Seasonal Offer"
        BUNDLE = "bundle", "Bundle Deal"
        CLEARANCE = "clearance", "Clearance Sale"
        NEW_ARRIVAL = "new_arrival", "New Arrival"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SCHEDULED = "scheduled", "Scheduled"
        ACTIVE = "active", "Active"
        ENDED = "ended", "Ended"
        CANCELLED = "cancelled", "Cancelled"

    name = models.CharField(max_length=200, help_text="Campaign name (internal)")
    slug = models.SlugField(max_length=220, unique=True, blank=True)

    # Campaign Details
    title = models.CharField(max_length=200, help_text="Public-facing campaign title")
    description = models.TextField(help_text="Campaign description for customers")
    campaign_type = models.CharField(max_length=20, choices=CampaignType.choices, default=CampaignType.FLASH_SALE)

    # Timing
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()

    # Status
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    is_active = models.BooleanField(default=True)

    # Display Settings
    banner_image = models.ImageField(upload_to='campaigns/banners/', blank=True, null=True)
    background_color = models.CharField(max_length=7, default="#FF6B35", help_text="Hex color code")
    text_color = models.CharField(max_length=7, default="#FFFFFF", help_text="Hex color code")

    # Wheel Settings (for flash promotions)
    enable_wheel = models.BooleanField(default=True, help_text="Show spinning wheel for this campaign")
    wheel_prizes = models.JSONField(
        default=list,
        blank=True,
        help_text='List of prizes like [{"label": "10% OFF", "probability": 0.3}, ...]'
    )

    # Engagement Limits
    max_spins_per_user = models.IntegerField(default=1, help_text="Maximum spins per user")
    require_login = models.BooleanField(default=False, help_text="Require login to participate")

    # Analytics
    total_views = models.IntegerField(default=0)
    total_spins = models.IntegerField(default=0)
    total_conversions = models.IntegerField(default=0)

    # Meta
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='campaigns_created'
    )

    class Meta:
        ordering = ['-start_date']
        indexes = [
            models.Index(fields=['status', 'start_date']),
            models.Index(fields=['slug']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:200]
            candidate = base
            i = 2
            while Campaign.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f"{base}-{i}"
                i += 1
            self.slug = candidate

        # Auto-update status based on dates
        now = timezone.now()
        if self.status != self.Status.CANCELLED:
            if now < self.start_date:
                self.status = self.Status.SCHEDULED
            elif self.start_date <= now <= self.end_date:
                self.status = self.Status.ACTIVE
            elif now > self.end_date:
                self.status = self.Status.ENDED

        super().save(*args, **kwargs)

    def is_running(self):
        """Check if campaign is currently active"""
        now = timezone.now()
        return (
                self.is_active and
                self.status == self.Status.ACTIVE and
                self.start_date <= now <= self.end_date
        )

    def time_remaining(self):
        """Get time remaining in the campaign"""
        if not self.is_running():
            return None
        return self.end_date - timezone.now()

    def get_active_products(self):
        """Get all active products in this campaign"""
        return self.products.filter(is_active=True)

    def increment_views(self):
        """Increment view counter"""
        self.total_views = F('total_views') + 1
        self.save(update_fields=['total_views'])

    def increment_spins(self):
        """Increment spin counter"""
        self.total_spins = F('total_spins') + 1
        self.save(update_fields=['total_spins'])

    def increment_conversions(self):
        """Increment conversion counter"""
        self.total_conversions = F('total_conversions') + 1
        self.save(update_fields=['total_conversions'])


class CampaignProduct(models.Model):
    """
    Link products to campaigns with specific promotion details
    """
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='campaign_products')
    product = models.ForeignKey('Product', on_delete=models.CASCADE, related_name='campaign_products')

    # Promotion Details
    discount_type = models.CharField(
        max_length=20,
        choices=[
            ('percentage', 'Percentage Off'),
            ('fixed', 'Fixed Amount Off'),
            ('special_price', 'Special Price'),
        ],
        default='percentage'
    )
    discount_value = models.DecimalField(max_digits=10, decimal_places=2)

    # Display
    position = models.IntegerField(default=0, help_text="Display order (lower = first)")
    is_featured = models.BooleanField(default=False, help_text="Feature this product in the campaign")

    # Stock
    campaign_stock = models.IntegerField(null=True, blank=True, help_text="Limited stock for campaign")
    stock_sold = models.IntegerField(default=0)

    # Meta
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['position', '-created_at']
        unique_together = ['campaign', 'product']
        indexes = [
            models.Index(fields=['campaign', 'is_featured']),
            models.Index(fields=['position']),
        ]

    def __str__(self):
        return f"{self.product.name} in {self.campaign.name}"

    def get_campaign_price(self):
        """Calculate the campaign price based on discount"""
        base_price = self.product.price

        if self.discount_type == 'percentage':
            discount_amount = base_price * (self.discount_value / Decimal('100'))
            return base_price - discount_amount
        elif self.discount_type == 'fixed':
            return max(base_price - self.discount_value, Decimal('0'))
        elif self.discount_type == 'special_price':
            return self.discount_value

        return base_price

    def get_discount_amount(self):
        """Get the actual discount amount"""
        return self.product.price - self.get_campaign_price()

    def get_discount_percentage(self):
        """Calculate discount percentage"""
        if self.product.price > 0:
            return int((self.get_discount_amount() / self.product.price) * 100)
        return 0

    def is_in_stock(self):
        """Check if campaign stock is available"""
        if self.campaign_stock is None:
            return True  # Unlimited stock
        return self.stock_sold < self.campaign_stock

    def remaining_stock(self):
        """Get remaining campaign stock"""
        if self.campaign_stock is None:
            return None  # Unlimited
        return max(self.campaign_stock - self.stock_sold, 0)


class WheelSpin(models.Model):
    """
    Records when users spin the campaign wheel and what they won.
    Automatically creates PromoCode objects in the orders app for valid prizes.
    """

    campaign = models.ForeignKey(
        'Campaign',
        on_delete=models.CASCADE,
        related_name='spins',
        help_text="The campaign this spin belongs to"
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='wheel_spins',
        help_text="User who spun (null for anonymous)"
    )

    session_key = models.CharField(
        max_length=255,
        blank=True,
        help_text="Session key for anonymous users"
    )

    # Prize Information
    prize_won = models.CharField(
        max_length=200,
        help_text="Display name of prize (e.g., '10% OFF', 'Free Shipping')"
    )

    prize_type = models.CharField(
        max_length=50,
        choices=[
            ('discount', 'Percentage Discount'),
            ('fixed_amount', 'Fixed Amount Discount'),
            ('free_shipping', 'Free Shipping'),
            ('nothing', 'No Prize / Try Again'),
        ],
        default='discount',
        help_text="Type of prize won"
    )

    prize_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Discount percentage (e.g., 10 for 10%) or fixed amount"
    )

    # Link to generated promo code
    promo_code = models.OneToOneField(
        'orders.PromoCode',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='wheel_spin',
        help_text="Auto-generated promo code for this prize"
    )

    # Tracking
    spun_at = models.DateTimeField(auto_now_add=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=1000, blank=True)

    # Redemption tracking
    is_redeemed = models.BooleanField(
        default=False,
        help_text="Has this prize been used in an order?"
    )
    redeemed_at = models.DateTimeField(null=True, blank=True)
    order = models.ForeignKey(
        'orders.Order',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='wheel_prizes_used',
        help_text="Order where this prize was redeemed"
    )

    class Meta:
        ordering = ['-spun_at']
        verbose_name = "Wheel Spin"
        verbose_name_plural = "Wheel Spins"
        indexes = [
            models.Index(fields=['campaign', 'user']),
            models.Index(fields=['campaign', 'session_key']),
            models.Index(fields=['spun_at']),
            models.Index(fields=['is_redeemed']),
        ]

    def __str__(self):
        user_info = f"User {self.user.id}" if self.user else f"Session {self.session_key[:8]}..."
        return f"{user_info} won {self.prize_won} - {self.campaign.name}"

    def generate_promo_code(self):
        """
        Generate a unique promo code in the orders.PromoCode table.

        Returns:
            str: The generated promo code, or None if prize type is 'nothing'
        """
        from orders.models import PromoCode

        # Don't generate codes for "nothing" prizes
        if self.prize_type == 'nothing':
            return None

        # Generate unique code with retry logic
        max_attempts = 10
        code = None

        for attempt in range(max_attempts):
            # Format: WHEEL-XXXXX (5 random chars)
            code_suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
            code = f"WHEEL-{code_suffix}"

            # Check uniqueness
            if not PromoCode.objects.filter(code=code).exists():
                break
        else:
            # Fallback if all attempts fail
            import time
            timestamp = int(time.time())
            code = f"WHEEL-{timestamp % 100000:05d}"

        # Calculate expiration date
        campaign_end = self.campaign.end_date
        thirty_days_from_now = timezone.now() + timezone.timedelta(days=30)

        # Use earlier of campaign end or 30 days
        if campaign_end:
            expiry_date = min(campaign_end, thirty_days_from_now)
        else:
            expiry_date = thirty_days_from_now

        # Map prize type to PromoCode fields
        if self.prize_type == 'discount':
            discount_type = 'percentage'
            discount_value = self.prize_value
        elif self.prize_type == 'fixed_amount':
            discount_type = 'fixed'
            discount_value = self.prize_value
        elif self.prize_type == 'free_shipping':
            discount_type = 'free_shipping'
            discount_value = Decimal('0')
        else:
            discount_type = 'percentage'
            discount_value = Decimal('0')

        # Create the PromoCode
        promo = PromoCode.objects.create(
            code=code,
            discount_type=discount_type,
            discount_value=discount_value,
            min_purchase_amount=Decimal('0'),  # No minimum for wheel prizes
            max_uses=1,  # One-time use only
            uses=0,
            is_active=True,
            valid_from=timezone.now(),
            valid_until=expiry_date,
            description=f"🎡 Wheel Prize: {self.prize_won} (Campaign: {self.campaign.name})",
            # If your PromoCode model has these fields, uncomment:
            # source='campaign_wheel',
            # campaign=self.campaign,
        )

        # Link promo code to this spin
        self.promo_code = promo
        self.save(update_fields=['promo_code'])

        return code

    def mark_redeemed(self, order=None):
        """
        Mark this wheel spin prize as redeemed.

        Args:
            order: Optional Order object where prize was used
        """
        self.is_redeemed = True
        self.redeemed_at = timezone.now()
        if order:
            self.order = order
        self.save(update_fields=['is_redeemed', 'redeemed_at', 'order'])

    def can_be_used(self):
        """Check if this prize can still be used"""
        if self.prize_type == 'nothing':
            return False
        if self.is_redeemed:
            return False
        if self.promo_code and not self.promo_code.is_active:
            return False
        if self.promo_code and self.promo_code.valid_until:
            if timezone.now() > self.promo_code.valid_until:
                return False
        return True

    @property
    def code_string(self):
        """Get the promo code string"""
        return self.promo_code.code if self.promo_code else None

class SocialCartChatMessage(models.Model):
    SCOPE_CHOICES = (
        ("group", "Group"),
        ("item", "Item Thread"),
        ("seller_item", "Seller Item Thread"),
    )

    social_cart = models.ForeignKey("SocialCart", on_delete=models.CASCADE, related_name="chat_messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_chat_sent")

    # NEW: for private seller chat
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="social_chat_received"
    )

    # NEW: thread type
    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default="group")

    # NEW: store product id as string/uuid-safe (works with UUID PKs too)
    product_id = models.CharField(max_length=64, null=True, blank=True, db_index=True)

    # Your message
    message = models.TextField(blank=True, default="")

    # NEW: for “shared item card”
    attach_product = models.BooleanField(default=False)
    product_snapshot = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


    def __str__(self):
        return f"{self.sender} @ {self.created_at:%Y-%m-%d %H:%M}: {self.message[:30]}"

class SocialCartChatThread(models.Model):
    SCOPE_GROUP = "group"           # main social cart room
    SCOPE_ITEM = "item"             # room per product (members only)
    SCOPE_SELLER_ITEM = "seller_item"  # private members + seller for that product

    SCOPE_CHOICES = (
        (SCOPE_GROUP, "Group"),
        (SCOPE_ITEM, "Item"),
        (SCOPE_SELLER_ITEM, "Seller Item"),
    )

    social_cart = models.ForeignKey("marketplace.SocialCart", on_delete=models.CASCADE, related_name="chat_threads")
    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default=SCOPE_GROUP, db_index=True)

    # Optional: tie thread to product
    product = models.ForeignKey("marketplace.Product", null=True, blank=True, on_delete=models.CASCADE, related_name="social_chat_threads")

    # Optional: seller user (if you store seller on Product)
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="seller_social_threads")

    # Participants (members + seller for seller_item)
    participants = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="social_chat_threads_joined", blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["social_cart", "scope"]),
            models.Index(fields=["social_cart", "scope", "product"]),
        ]

    def __str__(self):
        return f"{self.social_cart_id} {self.scope} {self.product_id or ''}"