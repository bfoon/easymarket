from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
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
    StoreReferral,
    StoreFollow,  # Added missing model
    StoreNotification,  # Added missing model
    ProductPriceHistory,  # Added missing model
)


class StoreManagerInline(admin.TabularInline):
    model = StoreManager
    extra = 1
    fields = ('user', 'role', 'permissions', 'added_by')
    readonly_fields = ('added_at',)


class StoreHoursInline(admin.TabularInline):
    model = StoreHours
    extra = 1
    fields = ('day_of_week', 'opening_time', 'closing_time', 'is_closed')


class StoreFollowInline(admin.TabularInline):
    """Inline to show followers in store admin"""
    model = StoreFollow
    extra = 0
    readonly_fields = ('followed_at',)
    fields = ('user', 'is_active', 'notify_new_products', 'notify_price_changes', 'notify_discounts', 'followed_at')
    verbose_name = "Follower"
    verbose_name_plural = "Followers"


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'status', 'store_type', 'is_featured', 'followers_count_display', 'created_at')
    list_filter = ('status', 'store_type', 'is_featured', 'category', 'created_at', 'country')
    search_fields = ('name', 'owner__username', 'email', 'phone', 'city', 'country')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [StoreManagerInline, StoreHoursInline, StoreFollowInline]
    readonly_fields = ('approved_at', 'created_at', 'updated_at', 'followers_count_display')

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'slug', 'description', 'short_description', 'owner', 'store_type', 'category', 'status')
        }),
        ('Contact Information', {
            'fields': ('email', 'phone', 'website')
        }),
        ('Address', {
            'fields': ('address_line_1', 'address_line_2', 'city', 'region', 'postal_code', 'country')
        }),
        ('Business Details', {
            'fields': ('business_registration_number', 'tax_identification_number', 'bank_account_number', 'bank_name')
        }),
        ('Media', {
            'fields': ('logo', 'banner')
        }),
        ('Settings', {
            'fields': (
            'is_featured', 'allow_reviews', 'auto_approve_products', 'allow_auctions', 'auto_approve_auctions',
            'allow_referrals')
        }),
        ('Financial Settings', {
            'fields': ('commission_rate', 'auction_commission_rate', 'minimum_order_amount')
        }),
        ('Policies', {
            'fields': ('processing_time', 'return_policy_days', 'accept_cash_risk')
        }),
        ('Social Media', {
            'fields': ('facebook_url', 'twitter_url', 'instagram_url')
        }),
        ('Follow Statistics', {
            'fields': ('followers_count_display',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'approved_at'),
            'classes': ('collapse',)
        })
    )

    def followers_count_display(self, obj):
        """Display followers count with link to followers list"""
        count = obj.get_followers_count()
        if count > 0:
            url = reverse('admin:stores_storefollow_changelist') + f'?store__id__exact={obj.id}'
            return format_html('<a href="{}">{} followers</a>', url, count)
        return "0 followers"

    followers_count_display.short_description = "Followers"


@admin.register(StoreCategory)
class StoreCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'stores_count', 'created_at')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name', 'description')
    list_filter = ('is_active', 'created_at')
    readonly_fields = ('created_at', 'updated_at')

    def stores_count(self, obj):
        """Display count of stores in this category"""
        count = obj.store_set.filter(status='active').count()
        if count > 0:
            url = reverse('admin:stores_store_changelist') + f'?category__id__exact={obj.id}'
            return format_html('<a href="{}">{} stores</a>', url, count)
        return "0 stores"

    stores_count.short_description = "Active Stores"


@admin.register(StoreFollow)
class StoreFollowAdmin(admin.ModelAdmin):
    list_display = ('user', 'store', 'is_active', 'notifications_enabled', 'followed_at')
    list_filter = ('is_active', 'notify_new_products', 'notify_price_changes', 'notify_discounts', 'followed_at')
    search_fields = ('user__username', 'user__email', 'store__name')
    readonly_fields = ('followed_at',)

    fieldsets = (
        ('Follow Information', {
            'fields': ('user', 'store', 'is_active', 'followed_at')
        }),
        ('Notification Preferences', {
            'fields': ('notify_new_products', 'notify_price_changes', 'notify_discounts')
        })
    )

    def notifications_enabled(self, obj):
        """Show which notifications are enabled"""
        notifications = []
        if obj.notify_new_products:
            notifications.append("Products")
        if obj.notify_price_changes:
            notifications.append("Prices")
        if obj.notify_discounts:
            notifications.append("Discounts")

        if notifications:
            return ", ".join(notifications)
        return "None"

    notifications_enabled.short_description = "Notifications"


@admin.register(StoreNotification)
class StoreNotificationAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'store', 'notification_type', 'is_read', 'is_sent', 'created_at')
    list_filter = ('notification_type', 'is_read', 'is_sent', 'created_at')
    search_fields = ('title', 'message', 'user__username', 'store__name')
    readonly_fields = ('created_at',)

    fieldsets = (
        ('Notification Details', {
            'fields': ('user', 'store', 'product', 'notification_type', 'title', 'message')
        }),
        ('Price Information', {
            'fields': ('old_price', 'new_price'),
            'classes': ('collapse',)
        }),
        ('Status', {
            'fields': ('is_read', 'is_sent', 'created_at')
        })
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'store', 'product')


@admin.register(ProductPriceHistory)
class ProductPriceHistoryAdmin(admin.ModelAdmin):
    list_display = ('product', 'old_price', 'new_price', 'price_change_display', 'changed_by', 'changed_at')
    list_filter = ('changed_at',)
    search_fields = ('product__name', 'product__store__name', 'changed_by__username')
    readonly_fields = ('changed_at',)

    def price_change_display(self, obj):
        """Display price change with color coding"""
        if obj.new_price > obj.old_price:
            return format_html(
                '<span style="color: red;">+${:.2f}</span>',
                obj.new_price - obj.old_price
            )
        else:
            return format_html(
                '<span style="color: green;">-${:.2f}</span>',
                obj.old_price - obj.new_price
            )

    price_change_display.short_description = "Price Change"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('product', 'product__store', 'changed_by')


@admin.register(StoreManager)
class StoreManagerAdmin(admin.ModelAdmin):
    list_display = ('store', 'user', 'role', 'added_by', 'added_at')
    list_filter = ('role', 'added_at')
    search_fields = ('store__name', 'user__username', 'added_by__username')
    readonly_fields = ('added_at',)


@admin.register(StoreHours)
class StoreHoursAdmin(admin.ModelAdmin):
    list_display = ('store', 'get_day_of_week_display', 'opening_time', 'closing_time', 'is_closed')
    list_filter = ('store', 'day_of_week', 'is_closed')
    search_fields = ('store__name',)


@admin.register(StoreReview)
class StoreReviewAdmin(admin.ModelAdmin):
    list_display = ('store', 'customer', 'rating', 'is_approved', 'created_at')
    list_filter = ('rating', 'is_approved', 'created_at')
    search_fields = ('store__name', 'customer__username', 'title', 'comment')
    readonly_fields = ('created_at', 'updated_at')

    actions = ['approve_reviews', 'reject_reviews']

    def approve_reviews(self, request, queryset):
        queryset.update(is_approved=True)
        self.message_user(request, f"{queryset.count()} reviews approved.")

    approve_reviews.short_description = "Approve selected reviews"

    def reject_reviews(self, request, queryset):
        queryset.update(is_approved=False)
        self.message_user(request, f"{queryset.count()} reviews rejected.")

    reject_reviews.short_description = "Reject selected reviews"


@admin.register(StoreShippingZone)
class StoreShippingZoneAdmin(admin.ModelAdmin):
    list_display = (
    'store', 'name', 'base_cost', 'per_kg_cost', 'free_shipping_threshold', 'estimated_delivery_days', 'is_active')
    list_filter = ('is_active', 'estimated_delivery_days')
    search_fields = ('store__name', 'name', 'regions')


@admin.register(StoreInventoryTracking)
class StoreInventoryTrackingAdmin(admin.ModelAdmin):
    list_display = ('store', 'product', 'transaction_type', 'quantity_change', 'condition', 'timestamp', 'performed_by')
    list_filter = ('transaction_type', 'condition', 'timestamp')
    search_fields = ('store__name', 'product__name', 'reference_id', 'notes')
    readonly_fields = ('timestamp',)


@admin.register(StoreReturnSettings)
class StoreReturnSettingsAdmin(admin.ModelAdmin):
    list_display = (
    'store', 'return_window_days', 'auto_approve_returns', 'provide_return_label', 'pickup_service_available')
    search_fields = ('store__name',)
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        ('Return Window', {
            'fields': ('store', 'return_window_days')
        }),
        ('Accepted Reasons', {
            'fields': ('accept_defective', 'accept_wrong_item', 'accept_wrong_size',
                       'accept_damaged_shipping', 'accept_not_as_described', 'accept_changed_mind',
                       'accept_quality_issues')
        }),
        ('Processing Settings', {
            'fields': ('auto_approve_returns', 'require_original_packaging', 'require_photos')
        }),
        ('Logistics', {
            'fields': ('provide_return_label', 'pickup_service_available')
        }),
        ('Financial Policies', {
            'fields': ('restocking_fee_percentage', 'refund_shipping_cost')
        }),
        ('Custom Policy', {
            'fields': ('custom_return_policy',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )


@admin.register(StoreMetrics)
class StoreMetricsAdmin(admin.ModelAdmin):
    list_display = (
    'store', 'date', 'total_orders', 'total_sales', 'total_returns', 'return_rate_percentage', 'average_rating')
    list_filter = ('date', 'store')
    search_fields = ('store__name',)
    readonly_fields = ('date',)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('store')


@admin.register(StoreReferral)
class StoreReferralAdmin(admin.ModelAdmin):
    list_display = ('referrer', 'referred_email', 'store', 'referral_code', 'is_used', 'reward_issued', 'created_at')
    list_filter = ('is_used', 'reward_issued', 'store', 'created_at')
    search_fields = ('referrer__username', 'referrer__email', 'referred_email', 'referral_code', 'store__name')
    readonly_fields = ('referral_code', 'created_at')
    ordering = ('-created_at',)

    fieldsets = (
        ('Referral Details', {
            'fields': ('referrer', 'referred_email', 'store', 'referral_code')
        }),
        ('Status', {
            'fields': ('is_used', 'reward_issued', 'created_at')
        })
    )

    def has_add_permission(self, request):
        # Optional: Only allow add through code logic, not admin
        return True

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('referrer', 'store')