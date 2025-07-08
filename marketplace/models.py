from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone


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
    original_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    video = models.FileField(upload_to='product_videos/', blank=True, null=True)
    sold_count = models.PositiveIntegerField(default=0)

    # Remove this line:
    # stock = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

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



class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='product_images/')

    def __str__(self):
        return f"Image for {self.product.name}"


class ProductView(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    viewed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} viewed {self.product.name} on {self.viewed_at.strftime('%Y-%m-%d %H:%M')}"

    class Meta:
        unique_together = ('user', 'product')


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

    class Meta:
        unique_together = ('cart', 'product')

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"

    def subtotal(self):
        return self.product.price * self.quantity


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