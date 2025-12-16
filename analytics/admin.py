from django.contrib import admin
from django.urls import path
from django.template.response import TemplateResponse
from django.utils import timezone
from django.db.models import Sum, Avg, Count
from datetime import timedelta
from decimal import Decimal

from .models import (
    PageView,
    VisitSession,
    CartEvent,
    AnalyticsEvent,
    AnalyticsDailySummary,
    StoreDailySummary,
)

# =========================
# PageView Admin
# =========================

@admin.register(PageView)
class PageViewAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "path_short",
        "user",
        "session_key_short",
        "ip_address",
    )
    list_filter = ("created_at",)
    search_fields = ("path", "session_key", "user__email", "user__username")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    readonly_fields = ("created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="Path")
    def path_short(self, obj):
        return obj.path if len(obj.path) <= 50 else f"{obj.path[:47]}…"

    @admin.display(description="Session")
    def session_key_short(self, obj):
        return obj.session_key[:10] + "…" if obj.session_key else "-"


# =========================
# VisitSession Admin
# =========================

@admin.register(VisitSession)
class VisitSessionAdmin(admin.ModelAdmin):
    list_display = (
        "session_key_short",
        "user",
        "page_views",
        "started_at",
        "last_activity",
    )
    search_fields = ("session_key", "user__email", "user__username")
    date_hierarchy = "started_at"
    ordering = ("-last_activity",)

    readonly_fields = (
        "session_key",
        "user",
        "page_views",
        "started_at",
        "last_activity",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="Session")
    def session_key_short(self, obj):
        return obj.session_key[:12] + "…"


# =========================
# CartEvent Admin
# =========================

@admin.register(CartEvent)
class CartEventAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "event",
        "user",
        "session_key_short",
    )
    list_filter = ("event", "created_at")
    search_fields = ("session_key", "user__email", "user__username")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    readonly_fields = ("created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="Session")
    def session_key_short(self, obj):
        return obj.session_key[:12] + "…"


# =========================
# AnalyticsEvent Admin
# =========================

@admin.register(AnalyticsEvent)
class AnalyticsEventAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "event",
        "path_short",
        "user",
        "store",
        "product",
        "order",
    )
    list_filter = ("event", "store", "created_at")
    search_fields = (
        "path",
        "session_key",
        "user__email",
        "product__name",
        "store__name",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    readonly_fields = (
        "created_at",
        "event",
        "path",
        "referrer",
        "session_key",
        "user",
        "store",
        "product",
        "order",
    )

    fieldsets = (
        ("Event", {"fields": ("event", "created_at")}),
        ("User / Session", {"fields": ("user", "session_key")}),
        ("Navigation", {"fields": ("path", "referrer")}),
        ("Context", {"fields": ("store", "product", "order")}),
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="Path")
    def path_short(self, obj):
        if not obj.path:
            return "-"
        return obj.path if len(obj.path) <= 45 else f"{obj.path[:42]}…"


# =========================
# AnalyticsDailySummary Admin (GLOBAL)
# =========================

@admin.register(AnalyticsDailySummary)
class AnalyticsDailySummaryAdmin(admin.ModelAdmin):
    list_display = (
        "date",
        "page_views",
        "unique_visitors",
        "returning_visitors",
        "conversion_rate_pct",
        "bounce_rate_pct",
        "cart_abandonment_pct",
    )
    list_filter = ("date",)
    date_hierarchy = "date"
    ordering = ("-date",)

    readonly_fields = (
        "date",
        "page_views",
        "unique_visitors",
        "returning_visitors",
        "add_to_cart",
        "checkout",
        "paid",
        "conversion_rate",
        "bounce_rate",
        "cart_abandonment",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    @admin.display(description="Conversion")
    def conversion_rate_pct(self, obj):
        return f"{obj.conversion_rate:.2f}%"

    @admin.display(description="Bounce")
    def bounce_rate_pct(self, obj):
        return f"{obj.bounce_rate:.2f}%"

    @admin.display(description="Cart Abandon")
    def cart_abandonment_pct(self, obj):
        return f"{obj.cart_abandonment:.2f}%"


# =========================
# StoreDailySummary Admin (PER STORE)
# =========================

@admin.register(StoreDailySummary)
class StoreDailySummaryAdmin(admin.ModelAdmin):
    list_display = (
        "date",
        "store",
        "page_views",
        "unique_visitors",
        "add_to_cart",
        "checkout",
        "paid",
        "revenue",
        "conversion_rate_pct",
    )
    list_filter = ("store", "date")
    search_fields = ("store__name",)
    date_hierarchy = "date"
    ordering = ("-date", "-paid")

    readonly_fields = (
        "store",
        "date",
        "page_views",
        "unique_visitors",
        "returning_visitors",
        "view_product",
        "add_to_cart",
        "checkout",
        "paid",
        "conversion_rate",
        "bounce_rate",
        "cart_abandonment",
        "revenue",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    @admin.display(description="Conversion")
    def conversion_rate_pct(self, obj):
        return f"{obj.conversion_rate:.2f}%"

