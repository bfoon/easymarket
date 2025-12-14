# chat/models.py
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone


class ChatThreadManager(models.Manager):
    def get_or_create_between(self, user1, user2, *, store=None, product=None, order=None):
        """
        Backwards compatible:
          - If you call get_or_create_between(u1, u2) -> old behavior (one thread per pair)
        Upgraded:
          - If you pass store/product/order -> one thread per (buyer, store, context)
        Context rules:
          - product chat: product is set, order is None
          - order chat: order is set, product is None
        """

        # --- NEW context mode ---
        if store is not None or product is not None or order is not None:
            if store is None:
                raise ValidationError("store is required when using contextual chat threads.")

            # Exactly one of product/order must be provided
            if (product is None and order is None) or (product is not None and order is not None):
                raise ValidationError("Provide exactly one: product OR order.")

            # Find existing thread for this context (participants must include both users)
            qs = (
                self.filter(store=store)
                .filter(participants=user1)
                .filter(participants=user2)
            )

            if product is not None:
                qs = qs.filter(product=product, order__isnull=True)
            else:
                qs = qs.filter(order=order, product__isnull=True)

            thread = qs.first()
            if thread:
                return thread, False

            thread = self.create(store=store, product=product, order=order)
            thread.participants.add(user1, user2)
            return thread, True

        # --- OLD mode (pair-only) ---
        threads = self.filter(participants=user1).filter(participants=user2).filter(store__isnull=True, product__isnull=True, order__isnull=True)
        if threads.exists():
            return threads.first(), False
        thread = self.create()
        thread.participants.add(user1, user2)
        return thread, True


class ChatThread(models.Model):
    participants = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="chat_threads")

    # ✅ NEW: context fields
    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="chat_threads",
        help_text="Store context for chat (required for product/order chats)."
    )
    product = models.ForeignKey(
        "marketplace.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chat_threads",
        help_text="Product context (pre-order chat)."
    )
    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chat_threads",
        help_text="Order context (post-order chat)."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ChatThreadManager()

    class Meta:
        indexes = [
            models.Index(fields=["store", "-updated_at"]),
            models.Index(fields=["order"]),
            models.Index(fields=["product"]),
        ]
        constraints = [
            # If order is set, product must be null
            models.CheckConstraint(
                check=Q(order__isnull=True) | Q(product__isnull=True),
                name="thread_not_both_product_and_order",
            ),
            # If product is set, store must be set (same for order)
            models.CheckConstraint(
                check=(Q(product__isnull=True) | Q(store__isnull=False)),
                name="thread_product_requires_store",
            ),
            models.CheckConstraint(
                check=(Q(order__isnull=True) | Q(store__isnull=False)),
                name="thread_order_requires_store",
            ),
        ]

    def clean(self):
        super().clean()

        # If product/order is present, store must exist
        if (self.product_id or self.order_id) and not self.store_id:
            raise ValidationError("Store is required for product/order chat threads.")

        # Cannot link both product and order
        if self.product_id and self.order_id:
            raise ValidationError("Thread cannot be linked to both product and order.")

    @property
    def context_label(self):
        if self.order_id:
            return f"Order #{self.order_id}"
        if self.product_id and hasattr(self.product, "name"):
            return f"Product: {self.product.name}"
        return "Direct chat"

    def get_other_participant(self, user):
        return self.participants.exclude(id=user.id).first()

    def __str__(self):
        return f"ChatThread ({self.id}) - {self.context_label}"


class ChatMessage(models.Model):
    thread = models.ForeignKey("ChatThread", on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_sent_messages")

    # keep your existing field names to avoid breaking templates
    message = models.TextField()

    timestamp = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["timestamp"]
        indexes = [
            models.Index(fields=["thread", "timestamp"]),
            models.Index(fields=["thread", "is_read"]),
        ]

    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at"])

    def __str__(self):
        return f"{self.sender.username}: {self.message[:30]}"

