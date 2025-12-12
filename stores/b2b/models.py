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

    # Optional totals (you can compute dynamically too)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    priced_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"B2BOrder {self.id} ({self.store})"


class B2BOrderItem(models.Model):
    order = models.ForeignKey(B2BOrder, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("marketplace.Product", on_delete=models.CASCADE)
    variant = models.ForeignKey("marketplace.ProductVariant", null=True, blank=True, on_delete=models.SET_NULL)

    quantity = models.PositiveIntegerField(default=1)

    # buyer snapshot + request
    product_name = models.CharField(max_length=255, blank=True)
    requested_unit_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    # seller sets final price (optional). if null => we fall back to default pricing.
    seller_unit_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.quantity} x {self.product_id}"

    def get_default_unit_price(self) -> Decimal:
        """
        Default price logic:
        - use product.b2b_price if available
        - else use product.price (retail)
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
        What the buyer will see if seller hasn't priced yet.
        """
        if self.seller_unit_price is not None:
            return Decimal(self.seller_unit_price)
        return self.get_default_unit_price()

    def line_total(self) -> Decimal:
        return self.get_effective_unit_price() * Decimal(self.quantity)
