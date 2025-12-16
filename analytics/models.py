# analytics/models.py
from django.conf import settings
from django.db import models
from django.utils import timezone
from decimal import Decimal


class PageView(models.Model):
    """Legacy model - consider migrating to AnalyticsEvent"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    session_key = models.CharField(max_length=40, blank=True, db_index=True)
    path = models.CharField(max_length=255, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["created_at", "session_key"]),
            models.Index(fields=["path", "created_at"]),
        ]

    def __str__(self):
        return f"{self.path} - {self.created_at}"


class VisitSession(models.Model):
    """
    Tracks user sessions for bounce rate & return customer calculations
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    session_key = models.CharField(max_length=40, unique=True, db_index=True)
    page_views = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    last_activity = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "started_at"]),
        ]

    def __str__(self):
        return f"Session {self.session_key} - {self.page_views} views"


class CartEvent(models.Model):
    """Legacy model - consider migrating to AnalyticsEvent"""
    EVENT_CHOICES = (
        ("add", "Add to Cart"),
        ("remove", "Remove from Cart"),
        ("checkout", "Checkout"),
        ("abandoned", "Abandoned"),
        ("completed", "Completed"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    session_key = models.CharField(max_length=40, db_index=True)
    event = models.CharField(max_length=20, choices=EVENT_CHOICES, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["event", "created_at"]),
            models.Index(fields=["session_key", "event"]),
        ]

    def __str__(self):
        return f"{self.get_event_display()} - {self.created_at}"


class AnalyticsEvent(models.Model):
    """
    Universal event tracking model - replaces PageView and CartEvent
    """
    EVENT_CHOICES = [
        ("page_view", "Page View"),
        ("product_view", "Product View"),
        ("add_to_cart", "Add To Cart"),
        ("remove_from_cart", "Remove From Cart"),
        ("checkout", "Checkout"),
        ("paid", "Paid"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        db_index=True
    )
    session_key = models.CharField(max_length=64, db_index=True)
    event = models.CharField(max_length=32, choices=EVENT_CHOICES, db_index=True)

    # Optional dimensions (fill when relevant)
    path = models.CharField(max_length=255, blank=True, db_index=True)
    referrer = models.CharField(max_length=255, blank=True)
    store = models.ForeignKey(
        "stores.Store",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="analytics_events"
    )
    product = models.ForeignKey(
        "marketplace.Product",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="analytics_events"
    )
    order = models.ForeignKey(
        "orders.Order",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="analytics_events"
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["event", "created_at"]),
            models.Index(fields=["store", "event", "created_at"]),
            models.Index(fields=["product", "event", "created_at"]),
            models.Index(fields=["session_key", "created_at"]),
            models.Index(fields=["user", "event", "created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_event_display()} - {self.created_at}"


class AnalyticsDailySummary(models.Model):
    """
    Daily rollup of platform-wide analytics
    """
    date = models.DateField(unique=True, db_index=True)

    # Traffic metrics
    page_views = models.PositiveIntegerField(default=0)
    unique_visitors = models.PositiveIntegerField(default=0)
    returning_visitors = models.PositiveIntegerField(default=0)

    # Funnel metrics
    add_to_cart = models.PositiveIntegerField(default=0)
    checkout = models.PositiveIntegerField(default=0)
    paid = models.PositiveIntegerField(default=0)

    # Performance metrics (stored as percentages)
    conversion_rate = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00")
    )
    bounce_rate = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00")
    )
    cart_abandonment = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00")
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]
        verbose_name_plural = "Analytics Daily Summaries"

    def __str__(self):
        return f"Analytics Summary - {self.date}"


class StoreDailySummary(models.Model):
    """
    Daily rollup of store-specific analytics
    """
    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.CASCADE,
        related_name="daily_analytics"
    )
    date = models.DateField(db_index=True)

    # Traffic metrics
    page_views = models.PositiveIntegerField(default=0)
    unique_visitors = models.PositiveIntegerField(default=0)
    returning_visitors = models.PositiveIntegerField(default=0)

    # Funnel counts
    view_product = models.PositiveIntegerField(default=0)
    add_to_cart = models.PositiveIntegerField(default=0)
    checkout = models.PositiveIntegerField(default=0)
    paid = models.PositiveIntegerField(default=0)

    # Performance rates (stored as percentages)
    conversion_rate = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00")
    )
    bounce_rate = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00")
    )
    cart_abandonment = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00")
    )

    # Revenue
    revenue = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00")
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("store", "date")
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["store", "date"]),
            models.Index(fields=["date", "revenue"]),
        ]
        verbose_name_plural = "Store Daily Summaries"

    def __str__(self):
        return f"{self.store.name} - {self.date}"