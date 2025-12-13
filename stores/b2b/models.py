# b2b/models.py
from django.conf import settings
from django.db import models
from django.db.models import UniqueConstraint
from django.utils import timezone
from decimal import Decimal
import uuid


class B2BCart(models.Model):
    """
    One active B2B cart per buyer.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="b2b_carts")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["buyer"], condition=models.Q(is_active=True), name="uniq_active_b2b_cart_per_buyer")
        ]

    def __str__(self):
        return f"B2B Cart ({self.buyer})"


class B2BCartItem(models.Model):
    cart = models.ForeignKey(B2BCart, on_delete=models.CASCADE, related_name="items")

    # Assuming your product model is marketplace.Product
    product = models.ForeignKey("marketplace.Product", on_delete=models.CASCADE)

    # Optional: support variants if you use ProductVariant
    variant = models.ForeignKey("marketplace.ProductVariant", null=True, blank=True, on_delete=models.SET_NULL)

    quantity = models.PositiveIntegerField(default=1)

    # Buyer can propose / request a price (optional)
    requested_unit_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    # Snapshot fields (optional but recommended)
    product_name = models.CharField(max_length=255, blank=True)
    store = models.ForeignKey("stores.Store", null=True, blank=True, on_delete=models.SET_NULL)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["cart", "product", "variant"], name="uniq_b2b_cart_line")
        ]

    def __str__(self):
        return f"{self.quantity} x {self.product_id}"

    def clean(self):
        # If you have MOQ on product, enforce it here (optional)
        moq = getattr(self.product, "moq", None)
        if moq and self.quantity < moq:
            from django.core.exceptions import ValidationError
            raise ValidationError({"quantity": f"Minimum order quantity is {moq}."})

    def save(self, *args, **kwargs):
        if self.product and not self.product_name:
            self.product_name = getattr(self.product, "name", "") or ""
        if self.product and not self.store_id:
            # Adjust this based on your product->store relation name
            store = getattr(self.product, "store", None)
            if store:
                self.store = store
        super().save(*args, **kwargs)


class B2BOrder(models.Model):
    STATUS_CHOICES = (
        ("submitted", "Submitted"),
        ("priced", "Priced by seller"),
        ("accepted", "Accepted by buyer"),
        ("rejected", "Rejected by buyer"),
        ("cancelled", "Cancelled"),
        ("processing", "Processing"),
        ("completed", "Completed"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="b2b_orders")
    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="b2b_orders")

    cart_source = models.ForeignKey(B2BCart, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="submitted")
    buyer_note = models.TextField(blank=True)

    # B2B Shipping cost (store sets later)
    shipping_cost = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    shipping_note = models.TextField(blank=True)

    # Optional totals (you can compute dynamically too)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    priced_at = models.DateTimeField(null=True, blank=True)

    @property
    def items_total(self):
        return sum((it.line_total() for it in self.items.all()), Decimal("0.00"))

    @property
    def grand_total(self):
        return (self.items_total or Decimal("0.00")) + (self.shipping_cost or Decimal("0.00"))

    def __str__(self):
        return f"B2BOrder {self.id} ({self.store})"


class B2BOrderItem(models.Model):

    STATUS_PENDING = "pending"
    STATUS_SHIPPED = "shipped"

    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_SHIPPED, "Shipped"),
    )

    order = models.ForeignKey(
        "B2BOrder",
        on_delete=models.CASCADE,
        related_name="items"
    )

    product = models.ForeignKey(
        "marketplace.Product",
        on_delete=models.CASCADE
    )

    variant = models.ForeignKey(
        "marketplace.ProductVariant",
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )

    quantity = models.PositiveIntegerField(default=1)

    # buyer snapshot + request
    product_name = models.CharField(max_length=255, blank=True)
    requested_unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True
    )

    # seller / locked pricing
    seller_unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True
    )

    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Locked unit price used for totals and invoices"
    )

    # ✅ NEW: item shipping status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True
    )

    shipped_at = models.DateTimeField(
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.quantity} × {self.product_name or self.product_id}"

    # ---------------------------
    # Pricing helpers
    # ---------------------------

    def get_default_unit_price(self) -> Decimal:
        """
        Default price logic:
        - product.b2b_price if available
        - else product.price (retail)
        """
        b2b_price = getattr(self.product, "b2b_price", None)
        retail_price = getattr(self.product, "price", None)

        if b2b_price is not None:
            return Decimal(b2b_price)
        if retail_price is not None:
            return Decimal(retail_price)

        return Decimal("0.00")

    def get_effective_unit_price(self) -> Decimal:
        """
        Price priority:
        1. locked unit_price
        2. seller_unit_price
        3. default product price
        """
        if self.unit_price is not None:
            return self.unit_price
        if self.seller_unit_price is not None:
            return self.seller_unit_price
        return self.get_default_unit_price()

    def line_total(self) -> Decimal:
        return self.get_effective_unit_price() * Decimal(self.quantity)

    # ---------------------------
    # Shipping helpers
    # ---------------------------

    def mark_shipped(self, when=None):
        """
        Safely mark item as shipped
        """
        self.status = self.STATUS_SHIPPED
        self.shipped_at = when or timezone.now()
        self.save(update_fields=["status", "shipped_at"])

class B2BShippingAddress(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    order = models.OneToOneField(
        "B2BOrder",
        related_name="shipping",
        on_delete=models.CASCADE
    )

    # Contact
    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)

    # Company / warehouse
    company_name = models.CharField(max_length=255, blank=True)

    # Address
    address_line = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    region = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, default="Gambia")

    # Logistics
    delivery_instructions = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"B2B Shipping for Order {self.order.id}"

class B2BOrderMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    order = models.ForeignKey("B2BOrder", on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="b2b_sent_messages")
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"B2B msg {self.id} on {self.order_id}"
