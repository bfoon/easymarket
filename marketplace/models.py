from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.db.models import Avg
from decimal import Decimal
from django.utils import timezone
import uuid


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
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    category = models.ForeignKey('Category', on_delete=models.SET_NULL, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField()
    specifications = models.TextField()
    image = models.ImageField(upload_to='products/')
    is_featured = models.BooleanField(default=False)
    is_trending = models.BooleanField(default=False)
    has_30_day_return = models.BooleanField(default=False,
                                            help_text="Enable if product is eligible for 30-day return policy.")
    free_shipping = models.BooleanField(default=False)
    used = models.BooleanField(default=False) #is for used products

    original_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    video = models.FileField(upload_to='product_videos/', blank=True, null=True)
    sold_count = models.PositiveIntegerField(default=0)
    store = models.ForeignKey('stores.Store', on_delete=models.CASCADE, related_name='products' , blank=True, null=True)
    is_active = models.BooleanField(default=True)

    available_for_auction = models.BooleanField(default=True)
    auction_reserve_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Suggested reserve price for auctions"
    )
    auction_starting_bid = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Suggested starting bid for auctions"
    )

    # Remove this line:
    # stock = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def create_auction(self, seller, starting_bid, end_date, **kwargs):
        """Helper method to create an auction from this product"""
        from auction.models import Auction

        auction_data = {
            'title': self.name,
            'description': self.description,
            'starting_bid': starting_bid,
            'end_date': end_date,
            'seller': seller,
            'marketplace_product': self,
            'image': self.image,
            'shipping_cost': 0.00,  # You can calculate this based on your logic
            **kwargs
        }

        return Auction.objects.create(**auction_data)

    @property
    def stock(self):
        """
        Get the latest stock record for this product.
        Returns the Stock instance or None if not found.
        """
        return self.stock_records.first()

    @property
    def stock_quantity(self):
        """
        Get the current stock quantity for this product.
        Returns the quantity as an integer.
        """
        stock_record = self.stock
        return stock_record.quantity if stock_record else 0

    @property
    def is_in_stock(self):
        """
        Check if the product is currently in stock.
        """
        return self.stock_quantity > 0

    @property
    def discount_percentage(self):
        """
        Calculates the discount percentage if original price exists and is greater than price.
        """
        if self.original_price and self.original_price > self.price:
            return int(((self.original_price - self.price) / self.original_price) * 100)
        return None

    @property
    def is_new(self):
        """
        Determines if product is considered 'new' (added within last 2 days).
        """
        from django.utils import timezone
        two_days_ago = timezone.now() - timezone.timedelta(days=2)
        return self.created_at >= two_days_ago

    def get_stock_status(self):
        """
        Get a human-readable stock status.
        """
        quantity = self.stock_quantity
        if quantity == 0:
            return "Out of Stock"
        elif quantity <= 5:
            return f"Low Stock ({quantity} remaining)"
        else:
            return f"In Stock ({quantity} available)"

    def reduce_stock(self, quantity):
        """
        Reduce stock quantity by the specified amount.
        Returns True if successful, False if insufficient stock.
        """
        stock_record = self.stock
        if stock_record and stock_record.quantity >= quantity:
            stock_record.quantity -= quantity
            stock_record.save()
            return True
        return False

    def increase_stock(self, quantity):
        """
        Increase stock quantity by the specified amount.
        """
        stock_record = self.stock
        if stock_record:
            stock_record.quantity += quantity
            stock_record.save()
        else:
            # Create new stock record if it doesn't exist
            from stock.models import Stock
            Stock.objects.create(product=self, quantity=quantity)

    def get_or_create_stock(self):
        """
        Get existing stock record or create a new one with 0 quantity.
        """
        stock_record = self.stock
        if not stock_record:
            from stock.models import Stock
            stock_record = Stock.objects.create(product=self, quantity=0)
        return stock_record

    def get_absolute_url(self):
        return reverse('product_detail', kwargs={'pk': self.pk})

    @property
    def average_rating(self):
        avg = self.reviews.aggregate(Avg('rating'))['rating__avg']
        return round(avg or 0, 1)

    @property
    def review_count(self):
        return self.reviews.count()

    @property
    def amount_saved(self):
        if self.original_price and self.original_price > self.price:
            return self.original_price - self.price
        return Decimal('0.00')

    def get_image_for_color(self, color=None):
        """Get the primary image for a specific color, fallback to main image"""
        if color:
            color_image = ProductImage.get_primary_image_for_color(self, color)
            if color_image:
                return color_image.image

            # Fallback to any image with that color
            color_images = ProductImage.get_images_by_color(self, color)
            if color_images.exists():
                return color_images.first().image

        # Fallback to main product image
        return self.image

    def get_images_by_color(self, color=None):
        """Get all images for a specific color"""
        return ProductImage.get_images_by_color(self, color)

    def get_available_image_colors(self):
        """Get all colors that have images"""
        return ProductImage.get_available_colors(self)

    def has_color_images(self):
        """Check if product has color-specific images"""
        return self.images.filter(color__isnull=False).exists()

    def save(self, *args, **kwargs):
        is_update = self.pk is not None
        changed_fields = []

        if is_update:
            # Fetch old state from the DB
            old = Product.objects.get(pk=self.pk)
            for field in self._meta.fields:
                field_name = field.name
                if field_name in ['updated_at', 'created_at']:
                    continue
                old_value = getattr(old, field_name)
                new_value = getattr(self, field_name)
                if old_value != new_value:
                    changed_fields.append(field_name)

        super().save(*args, **kwargs)

        # Save changed fields to a temporary attribute for signal use
        if is_update:
            self._changed_fields = changed_fields
        else:
            self._changed_fields = ['__created__']


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

    def __str__(self):
        return f"{self.user.username}'s Cart"

    def total_items(self):
        return sum(item.quantity for item in self.items.all())

    def total_price(self):
        return sum(item.product.price * item.quantity for item in self.items.all())


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    selected_features = models.JSONField(null=True, blank=True)

    class Meta:
        unique_together = ('cart', 'product')

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"

    def subtotal(self):
        return self.product.price * self.quantity

class Wishlist(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wishlist_items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='wishlisted_by')
    added_at = models.DateTimeField(auto_now_add=True)

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


