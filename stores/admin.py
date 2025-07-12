from django.contrib import admin
from .models import (
    StoreCategory,
    Store,
    StoreManager,
    StoreHours,
    StoreReview,
    StoreShippingZone,
    StoreInventoryTracking,
    StoreReturnSettings,
    StoreMetrics,
)


class StoreManagerInline(admin.TabularInline):
    model = StoreManager
    extra = 1


class StoreHoursInline(admin.TabularInline):
    model = StoreHours
    extra = 1


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'status', 'store_type', 'is_featured', 'created_at')
    list_filter = ('status', 'store_type', 'is_featured', 'created_at')
    search_fields = ('name', 'owner__username', 'email', 'phone', 'city', 'country')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [StoreManagerInline, StoreHoursInline]
    readonly_fields = ('approved_at', 'created_at', 'updated_at')


@admin.register(StoreCategory)
class StoreCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'created_at')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)
    list_filter = ('is_active',)


@admin.register(StoreManager)
class StoreManagerAdmin(admin.ModelAdmin):
    list_display = ('store', 'user', 'role', 'added_by', 'added_at')
    list_filter = ('role',)
    search_fields = ('store__name', 'user__username', 'added_by__username')


@admin.register(StoreHours)
class StoreHoursAdmin(admin.ModelAdmin):
    list_display = ('store', 'day_of_week', 'opening_time', 'closing_time', 'is_closed')
    list_filter = ('store', 'day_of_week', 'is_closed')


@admin.register(StoreReview)
class StoreReviewAdmin(admin.ModelAdmin):
    list_display = ('store', 'customer', 'rating', 'is_approved', 'created_at')
    list_filter = ('rating', 'is_approved', 'created_at')
    search_fields = ('store__name', 'customer__username', 'title', 'comment')


@admin.register(StoreShippingZone)
class StoreShippingZoneAdmin(admin.ModelAdmin):
    list_display = ('store', 'name', 'base_cost', 'per_kg_cost', 'free_shipping_threshold', 'estimated_delivery_days', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('store__name', 'name')


@admin.register(StoreInventoryTracking)
class StoreInventoryTrackingAdmin(admin.ModelAdmin):
    list_display = ('store', 'product', 'transaction_type', 'quantity_change', 'timestamp', 'performed_by')
    list_filter = ('transaction_type', 'timestamp')
    search_fields = ('store__name', 'product__name', 'reference_id', 'notes')


@admin.register(StoreReturnSettings)
class StoreReturnSettingsAdmin(admin.ModelAdmin):
    list_display = ('store', 'return_window_days', 'auto_approve_returns', 'provide_return_label', 'pickup_service_available')
    search_fields = ('store__name',)


@admin.register(StoreMetrics)
class StoreMetricsAdmin(admin.ModelAdmin):
    list_display = ('store', 'date', 'total_orders', 'total_sales', 'total_returns', 'return_rate_percentage')
    list_filter = ('date',)
    search_fields = ('store__name',)
