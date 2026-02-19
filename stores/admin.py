from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse

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
    StoreFollow,
    StoreNotification,
    ProductPriceHistory,
    PromotionPlan,
    PromotionSubscription,
    PromotionCampaign,
    B2BCart,
    B2BCartItem,
    B2BOrder,
    B2BOrderItem,
    B2BShippingAddress,
)


# -------------------------------------------------------------------
# Inlines
# -------------------------------------------------------------------
class StoreManagerInline(admin.TabularInline):
    model = StoreManager
    extra = 1
    fields = ("user", "role", "permissions", "added_by")
    readonly_fields = ("added_at",)
    autocomplete_fields = ("user", "added_by")


class StoreHoursInline(admin.TabularInline):
    model = StoreHours
    extra = 1
    fields = ("day_of_week", "opening_time", "closing_time", "is_closed")


class StoreFollowInline(admin.TabularInline):
    model = StoreFollow
    extra = 0
    readonly_fields = ("followed_at",)
    fields = (
        "user",
        "is_active",
        "notify_new_products",
        "notify_price_changes",
        "notify_discounts",
        "followed_at",
    )
    autocomplete_fields = ("user",)
    verbose_name = "Follower"
    verbose_name_plural = "Followers"


# ✅ B2B Inlines inside Store (quick view of latest orders)
class B2BOrderInline(admin.TabularInline):
    model = B2BOrder
    extra = 0
    fields = ("id", "buyer", "status", "subtotal", "created_at")
    readonly_fields = ("id", "created_at")
    autocomplete_fields = ("buyer",)
    show_change_link = True
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


# -------------------------------------------------------------------
# Store Admin
# -------------------------------------------------------------------
@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "owner",
        "status",
        "store_type",
        "country",
        "allows_b2b",
        "is_b2b_only",
        "is_international_supplier",
        "is_featured",
        "followers_count_display",
        "created_at",
    )
    list_filter = (
        "status",
        "store_type",
        "is_featured",
        "category",
        "country",
        "allows_b2b",
        "is_b2b_only",
        "is_international_supplier",
        "created_at",
    )
    search_fields = ("name", "owner__username", "owner__email", "email", "phone", "city", "country")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("owner", "category")
    inlines = [StoreManagerInline, StoreHoursInline, StoreFollowInline, B2BOrderInline]
    readonly_fields = ("approved_at", "created_at", "updated_at", "followers_count_display")

    fieldsets = (
        ("Basic Information", {
            "fields": (
                "name", "slug", "description", "short_description",
                "owner", "store_type", "category", "status",
            )
        }),
        ("Contact Information", {"fields": ("email", "phone", "website")}),
        ("Address", {
            "fields": ("address_line_1", "address_line_2", "city", "region", "postal_code", "country")
        }),
        ("Business Details", {
            "fields": ("business_registration_number", "tax_identification_number", "bank_account_number", "bank_name")
        }),
        ("Location", {"fields": ("geo_code", "latitude", "longitude", "show_map_location")}),
        ("Media", {"fields": ("logo", "banner")}),
        ("Settings", {
            "fields": (
                "is_featured",
                "allow_reviews",
                "auto_approve_products",
                "allow_auctions",
                "auto_approve_auctions",
                "allow_referrals",
                "email_verified",
            )
        }),
        ("B2B / Wholesale", {
            "fields": (
                "allows_b2b",
                "is_b2b_only",
                "is_international_supplier",
                "b2b_min_order_amount",
                "b2b_description",
            )
        }),
        ("Financial Settings", {
            "fields": ("commission_rate", "auction_commission_rate", "minimum_order_amount")
        }),
        ("Policies", {"fields": ("processing_time", "return_policy_days", "accept_cash_risk")}),
        ("Social Media", {"fields": ("facebook_url", "twitter_url", "instagram_url")}),
        ("Follow Statistics", {"fields": ("followers_count_display",), "classes": ("collapse",)}),
        ("Timestamps", {"fields": ("created_at", "updated_at", "approved_at"), "classes": ("collapse",)}),
    )

    def followers_count_display(self, obj):
        count = obj.get_followers_count()
        if count > 0:
            url = reverse("admin:stores_storefollow_changelist") + f"?store__id__exact={obj.id}"
            return format_html('<a href="{}">{} followers</a>', url, count)
        return "0 followers"

    followers_count_display.short_description = "Followers"


# -------------------------------------------------------------------
# Store Category
# -------------------------------------------------------------------
@admin.register(StoreCategory)
class StoreCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "stores_count", "created_at")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "description")
    list_filter = ("is_active", "created_at")
    readonly_fields = ("created_at", "updated_at")

    def stores_count(self, obj):
        count = obj.store_set.filter(status="active").count()
        if count > 0:
            url = reverse("admin:stores_store_changelist") + f"?category__id__exact={obj.id}"
            return format_html('<a href="{}">{} stores</a>', url, count)
        return "0 stores"

    stores_count.short_description = "Active Stores"


# -------------------------------------------------------------------
# Store Follow / Notifications / Price history (unchanged, just improved)
# -------------------------------------------------------------------
@admin.register(StoreFollow)
class StoreFollowAdmin(admin.ModelAdmin):
    list_display = ("user", "store", "is_active", "notifications_enabled", "followed_at")
    list_filter = ("is_active", "notify_new_products", "notify_price_changes", "notify_discounts", "followed_at")
    search_fields = ("user__username", "user__email", "store__name")
    readonly_fields = ("followed_at",)
    autocomplete_fields = ("user", "store")

    fieldsets = (
        ("Follow Information", {"fields": ("user", "store", "is_active", "followed_at")}),
        ("Notification Preferences", {"fields": ("notify_new_products", "notify_price_changes", "notify_discounts")}),
    )

    def notifications_enabled(self, obj):
        parts = []
        if obj.notify_new_products: parts.append("Products")
        if obj.notify_price_changes: parts.append("Prices")
        if obj.notify_discounts: parts.append("Discounts")
        return ", ".join(parts) if parts else "None"

    notifications_enabled.short_description = "Notifications"

@admin.register(StoreNotification)
class StoreNotificationAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'user',
        'store',
        'notification_type',
        'is_read',
        'is_sent',
        'created_at',
    )
    list_filter = ('notification_type', 'is_read', 'is_sent', 'created_at')
    search_fields = ()  # ✅ optional
    readonly_fields = ('created_at',)

    # ❌ REMOVE autocomplete_fields
    # autocomplete_fields = ("user", "store", "product")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'user', 'store', 'product'
        )

@admin.register(ProductPriceHistory)
class ProductPriceHistoryAdmin(admin.ModelAdmin):
    list_display = (
        'product',
        'old_price',
        'new_price',
        'price_change_display',
        'changed_by',
        'changed_at',
    )
    list_filter = ('changed_at',)
    search_fields = ()  # ✅ optional, safe
    readonly_fields = ('changed_at',)

    # ❌ REMOVE autocomplete_fields COMPLETELY
    # autocomplete_fields = ("product", "changed_by")

    def price_change_display(self, obj):
        if obj.new_price > obj.old_price:
            return format_html(
                '<span style="color:red;">+D{:.2f}</span>',
                obj.new_price - obj.old_price
            )
        return format_html(
            '<span style="color:green;">-D{:.2f}</span>',
            obj.old_price - obj.new_price
        )

    price_change_display.short_description = "Price Change"



@admin.register(StoreManager)
class StoreManagerAdmin(admin.ModelAdmin):
    list_display = ("store", "user", "role", "added_by", "added_at")
    list_filter = ("role", "added_at")
    search_fields = ("store__name", "user__username", "added_by__username")
    readonly_fields = ("added_at",)
    autocomplete_fields = ("store", "user", "added_by")


@admin.register(StoreHours)
class StoreHoursAdmin(admin.ModelAdmin):
    list_display = ("store", "get_day_of_week_display", "opening_time", "closing_time", "is_closed")
    list_filter = ("store", "day_of_week", "is_closed")
    search_fields = ("store__name",)
    autocomplete_fields = ("store",)


@admin.register(StoreReview)
class StoreReviewAdmin(admin.ModelAdmin):
    list_display = ("store", "user", "rating", "is_approved", "created_at")
    list_filter = ("rating", "is_approved", "created_at")
    search_fields = ("store__name", "user__username", "title", "comment")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("store", "user")

    actions = ["approve_reviews", "reject_reviews"]

    def approve_reviews(self, request, queryset):
        queryset.update(is_approved=True)
        self.message_user(request, f"{queryset.count()} reviews approved.")

    def reject_reviews(self, request, queryset):
        queryset.update(is_approved=False)
        self.message_user(request, f"{queryset.count()} reviews rejected.")


@admin.register(StoreShippingZone)
class StoreShippingZoneAdmin(admin.ModelAdmin):
    list_display = ("store", "name", "base_cost", "per_kg_cost", "free_shipping_threshold", "estimated_delivery_days", "is_active")
    list_filter = ("is_active", "estimated_delivery_days")
    search_fields = ("store__name", "name", "regions")
    autocomplete_fields = ("store",)

@admin.register(StoreInventoryTracking)
class StoreInventoryTrackingAdmin(admin.ModelAdmin):
    list_display = (
        'store',
        'product',
        'transaction_type',
        'quantity_change',
        'condition',
        'timestamp',
        'performed_by',
    )
    list_filter = ('transaction_type', 'condition', 'timestamp')
    search_fields = ()  # ✅ optional
    readonly_fields = ('timestamp',)





@admin.register(StoreReturnSettings)
class StoreReturnSettingsAdmin(admin.ModelAdmin):
    list_display = ("store", "return_window_days", "auto_approve_returns", "provide_return_label", "pickup_service_available")
    search_fields = ("store__name",)
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("store",)

    fieldsets = (
        ("Return Window", {"fields": ("store", "return_window_days")}),
        ("Accepted Reasons", {
            "fields": (
                "accept_defective", "accept_wrong_item", "accept_wrong_size", "accept_damaged_shipping",
                "accept_not_as_described", "accept_changed_mind", "accept_quality_issues",
            )
        }),
        ("Processing Settings", {"fields": ("auto_approve_returns", "require_original_packaging", "require_photos")}),
        ("Logistics", {"fields": ("provide_return_label", "pickup_service_available")}),
        ("Financial Policies", {"fields": ("restocking_fee_percentage", "refund_shipping_cost")}),
        ("Custom Policy", {"fields": ("custom_return_policy",), "classes": ("collapse",)}),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(StoreMetrics)
class StoreMetricsAdmin(admin.ModelAdmin):
    list_display = ("store", "date", "total_orders", "total_sales", "total_returns", "return_rate_percentage", "average_rating")
    list_filter = ("date", "store")
    search_fields = ("store__name",)
    readonly_fields = ("date",)
    autocomplete_fields = ("store",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("store")


@admin.register(StoreReferral)
class StoreReferralAdmin(admin.ModelAdmin):
    list_display = ("referrer", "referred_email", "store", "referral_code", "is_used", "reward_issued", "created_at")
    list_filter = ("is_used", "reward_issued", "store", "created_at")
    search_fields = ("referrer__username", "referrer__email", "referred_email", "referral_code", "store__name")
    readonly_fields = ("referral_code", "created_at")
    ordering = ("-created_at",)
    autocomplete_fields = ("referrer", "store")

    fieldsets = (
        ("Referral Details", {"fields": ("referrer", "referred_email", "store", "referral_code")}),
        ("Status", {"fields": ("is_used", "reward_issued", "created_at")}),
    )


@admin.register(PromotionPlan)
class PromotionPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "duration_days", "max_placements", "max_concurrent_campaigns")
    search_fields = ("name",)


@admin.register(PromotionSubscription)
class PromotionSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("store", "plan", "active", "start_at", "end_at", "is_active")
    list_filter = ("is_active", "plan")
    search_fields = ("store__name",)
    autocomplete_fields = ("store", "plan")


@admin.register(PromotionCampaign)
class PromotionCampaignAdmin(admin.ModelAdmin):
    list_display = ("title", "store", "placement", "status", "scheduled_at", "expires_at")
    list_filter = ("placement", "status")
    search_fields = ("title", "store__name", "headline")
    autocomplete_fields = ("subscription", "store", "reviewer")


# -------------------------------------------------------------------
# ✅ B2B Admins
# -------------------------------------------------------------------

class B2BOrderItemInline(admin.TabularInline):
    model = B2BOrderItem
    extra = 0
    fields = ("product", "variant", "quantity", "requested_unit_price", "seller_unit_price")
    can_delete = False


class B2BShippingInline(admin.StackedInline):
    model = B2BShippingAddress
    extra = 0
    can_delete = False


@admin.register(B2BOrder)
class B2BOrderAdmin(admin.ModelAdmin):
    list_display = ("store", "buyer", "status", "subtotal", "created_at", "priced_at", "tracking_number")
    list_filter = ("status", "created_at", "priced_at", "store", "tracking_number")
    search_fields = ("id", "store__name", "buyer__username", "buyer__email")
    readonly_fields = ("created_at", "updated_at", "priced_at", "tracking_number")
    autocomplete_fields = ("store", "buyer", "cart_source")
    inlines = [B2BOrderItemInline, B2BShippingInline]
    ordering = ("-created_at",)

    fieldsets = (
        ("Core", {"fields": ("store", "buyer", "status", "buyer_note")}),
        ("Totals", {"fields": ("subtotal",)}),
        ("Links", {"fields": ("cart_source",)}),
        ("Timestamps", {"fields": ("created_at", "updated_at", "priced_at")}),
        ("Tracking Number", {"fields": ("tracking_number", "tracking_note")}),
    )

@admin.register(B2BOrderItem)
class B2BOrderItemAdmin(admin.ModelAdmin):
    list_display = ("order", "product", "variant", "quantity", "requested_unit_price", "seller_unit_price", "created_at")
    list_filter = ("created_at", "order__status")
    search_fields = (
        "order__id",
        "product__name",
        "product__id",
        "variant__id",
    )
    readonly_fields = ("created_at",)

@admin.register(B2BCart)
class B2BCartAdmin(admin.ModelAdmin):
    list_display = ("id", "buyer", "is_active", "created_at", "updated_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("id", "buyer__username", "buyer__email")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("buyer",)


@admin.register(B2BCartItem)
class B2BCartItemAdmin(admin.ModelAdmin):
    list_display = ("id", "cart", "product", "variant", "quantity", "requested_unit_price", "created_at")
    list_filter = ("created_at",)
    search_fields = (
        "cart__id",
        "product__name",
        "product__id",
        "variant__id",
    )
    readonly_fields = ("created_at",)


@admin.register(B2BShippingAddress)
class B2BShippingAddressAdmin(admin.ModelAdmin):
    list_display = ("order", "full_name", "phone", "email", "city", "country", "created_at")
    list_filter = ("country", "created_at")
    search_fields = ("order__id", "full_name", "phone", "email", "city")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("order",)
