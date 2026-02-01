# crossroad_deals/admin.py

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe

from .models import (
    CrossroadDealConfig,
    PrivacyDisclosureRule,
    CrossroadListing,
    ListingSaleRecord,
    CrossroadOrder,
    CrossroadReceipt,
    CrossroadReview,
    SellerSuspension,
    DeviceActivityLog,
    ListingInterest,
)


class ReadOnlyAllFieldsAdmin(admin.ModelAdmin):
    """
    Makes all model fields read-only in the admin.
    Fixes admin.E034 (readonly_fields must be list/tuple, not '__all__').
    """

    def get_readonly_fields(self, request, obj=None):
        # concrete fields (db columns)
        fields = [f.name for f in self.model._meta.fields]
        # include many-to-many if any
        m2m = [m.name for m in self.model._meta.many_to_many]
        return fields + m2m


@admin.register(CrossroadDealConfig)
class CrossroadDealConfigAdmin(admin.ModelAdmin):
    list_display = ['id', 'listing_fee', 'vetting_fee', 'pickup_base_fee', 'bad_review_threshold', 'updated_at']
    fieldsets = (
        ('Fees', {
            'fields': ('listing_fee', 'vetting_fee', 'pickup_base_fee')
        }),
        ('Suspension Settings', {
            'fields': ('bad_review_threshold', 'review_rating_bad')
        }),
        ('Listing Settings', {
            'fields': ('max_listing_duration_days', 'auto_delete_sold_items')
        }),
        ('Platform Settings', {
            'fields': ('require_geocode', 'allow_buyer_listings')
        }),
    )

    def has_add_permission(self, request):
        # Only allow one config
        return not CrossroadDealConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PrivacyDisclosureRule)
class PrivacyDisclosureRuleAdmin(admin.ModelAdmin):
    list_display = ['field_name', 'default_disclosure', 'is_required']
    list_filter = ['default_disclosure', 'is_required']
    search_fields = ['field_name', 'description']


@admin.register(CrossroadListing)
class CrossroadListingAdmin(admin.ModelAdmin):
    list_display = [
        'listing_id_short',
        'title',
        'seller_link',
        'price',
        'quantity_info',
        'status_badge',
        'is_vetted',
        'created_at',
    ]
    list_filter = ['status', 'is_vetted', 'condition', 'created_at']
    search_fields = ['title', 'seller__username', 'seller__email', 'listing_id']
    readonly_fields = [
        'listing_id',
        'quantity_sold',
        'created_at',
        'updated_at',
        'published_at',
        'sold_out_at',
        'image_preview',
    ]

    fieldsets = (
        ('Basic Info', {
            'fields': ('listing_id', 'seller', 'status')
        }),
        ('Product Details', {
            'fields': ('title', 'description', 'condition', 'quantity', 'quantity_sold', 'price')
        }),
        ('Images', {
            'fields': ('image_1', 'image_2', 'image_preview')
        }),
        ('Location', {
            'fields': ('geocode', 'location_description')
        }),
        ('Privacy Controls', {
            'fields': (
                'show_seller_name',
                'show_exact_location',
                'price_disclosure',
                'contact_disclosure',
                'location_disclosure',
            )
        }),
        ('Contact Info', {
            'fields': ('contact_phone', 'contact_email')
        }),
        ('Vetting', {
            'fields': ('is_vetted', 'vetted_at', 'vetted_by')
        }),
        ('Fees', {
            'fields': ('listing_fee_paid', 'vetting_fee_paid')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'published_at', 'sold_out_at', 'expires_at', 'updated_at')
        }),
    )

    actions = ['mark_as_vetted', 'suspend_listings', 'activate_listings']

    def listing_id_short(self, obj):
        return str(obj.listing_id)[:8]

    listing_id_short.short_description = 'ID'

    def seller_link(self, obj):
        url = reverse('admin:accounts_user_change', args=[obj.seller.pk])
        return format_html('<a href="{}">{}</a>', url, obj.seller.username)

    seller_link.short_description = 'Seller'

    def quantity_info(self, obj):
        sold = obj.quantity_sold
        total = obj.quantity
        available = obj.quantity_available
        color = 'green' if available > 0 else 'red'
        return format_html(
            '<span style="color: {};">{}/{} sold ({} left)</span>',
            color, sold, total, available
        )

    quantity_info.short_description = 'Quantity'

    def status_badge(self, obj):
        colors = {
            'draft': 'gray',
            'active': 'green',
            'sold_out': 'blue',
            'suspended': 'orange',
            'banned': 'red',
            'expired': 'darkgray',
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{}</span>',
            color, obj.get_status_display()
        )

    status_badge.short_description = 'Status'

    def image_preview(self, obj):
        html = ''
        if obj.image_1:
            html += f'<img src="{obj.image_1.url}" style="max-width: 200px; max-height: 200px; margin-right: 10px;"/>'
        if obj.image_2:
            html += f'<img src="{obj.image_2.url}" style="max-width: 200px; max-height: 200px;"/>'
        return mark_safe(html) if html else 'No images'

    image_preview.short_description = 'Images'

    def mark_as_vetted(self, request, queryset):
        from django.utils import timezone
        count = queryset.update(
            is_vetted=True,
            vetted_at=timezone.now(),
            vetted_by=request.user
        )
        self.message_user(request, f'{count} listing(s) marked as vetted.')

    mark_as_vetted.short_description = 'Mark selected as vetted'

    def suspend_listings(self, request, queryset):
        count = queryset.filter(status='active').update(status='suspended')
        self.message_user(request, f'{count} listing(s) suspended.')

    suspend_listings.short_description = 'Suspend selected listings'

    def activate_listings(self, request, queryset):
        count = queryset.filter(status__in=['draft', 'suspended']).update(status='active')
        self.message_user(request, f'{count} listing(s) activated.')

    activate_listings.short_description = 'Activate selected listings'


@admin.register(ListingSaleRecord)
class ListingSaleRecordAdmin(ReadOnlyAllFieldsAdmin):
    list_display = [
        'listing_id_short',
        'title',
        'seller_link',
        'quantity_sold',
        'total_revenue',
        'time_to_sell_out',
        'was_vetted',
        'sold_out_at',
    ]
    list_filter = ['was_vetted', 'sold_out_at']
    search_fields = ['title', 'seller__username', 'listing_id']

    def listing_id_short(self, obj):
        return str(obj.listing_id)[:8]

    listing_id_short.short_description = 'Listing ID'

    def seller_link(self, obj):
        if obj.seller:
            url = reverse('admin:accounts_user_change', args=[obj.seller.pk])
            return format_html('<a href="{}">{}</a>', url, obj.seller.username)
        return 'N/A'

    seller_link.short_description = 'Seller'

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CrossroadOrder)
class CrossroadOrderAdmin(admin.ModelAdmin):
    list_display = [
        'order_id_short',
        'buyer_link',
        'listing_link',
        'quantity',
        'total_amount',
        'delivery_method',
        'status_badge',
        'created_at',
    ]
    list_filter = ['status', 'delivery_method', 'requested_vetting', 'created_at']
    search_fields = ['order_id', 'buyer__username', 'listing__title']
    readonly_fields = [
        'order_id',
        'subtotal',
        'total_amount',
        'created_at',
        'updated_at',
        'confirmed_at',
        'delivered_at',
    ]

    fieldsets = (
        ('Order Info', {
            'fields': ('order_id', 'listing', 'buyer', 'status')
        }),
        ('Order Details', {
            'fields': ('quantity', 'unit_price', 'subtotal')
        }),
        ('Delivery', {
            'fields': ('delivery_method', 'delivery_fee')
        }),
        ('Vetting', {
            'fields': ('requested_vetting', 'vetting_fee', 'vetting_completed', 'vetting_notes')
        }),
        ('Total', {
            'fields': ('total_amount',)
        }),
        ('Buyer Info', {
            'fields': ('buyer_geocode', 'buyer_phone', 'buyer_email')
        }),
        ('Tracking', {
            'fields': ('buyer_device',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'confirmed_at', 'delivered_at', 'updated_at')
        }),
    )

    def order_id_short(self, obj):
        return str(obj.order_id)[:8]

    order_id_short.short_description = 'Order ID'

    def buyer_link(self, obj):
        url = reverse('admin:accounts_user_change', args=[obj.buyer.pk])
        return format_html('<a href="{}">{}</a>', url, obj.buyer.username)

    buyer_link.short_description = 'Buyer'

    def listing_link(self, obj):
        url = reverse('admin:crossroad_deals_crossroadlisting_change', args=[obj.listing.pk])
        return format_html('<a href="{}">{}</a>', url, obj.listing.title)

    listing_link.short_description = 'Listing'

    def status_badge(self, obj):
        colors = {
            'pending': 'orange',
            'confirmed': 'blue',
            'pickup_scheduled': 'purple',
            'in_transit': 'teal',
            'delivered': 'green',
            'cancelled': 'red',
            'disputed': 'darkred',
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{}</span>',
            color, obj.get_status_display()
        )

    status_badge.short_description = 'Status'


@admin.register(CrossroadReceipt)
class CrossroadReceiptAdmin(ReadOnlyAllFieldsAdmin):
    list_display = ['receipt_id_short', 'order_link', 'created_at']
    search_fields = ['receipt_id', 'order__order_id']

    def receipt_id_short(self, obj):
        return str(obj.receipt_id)[:8]

    receipt_id_short.short_description = 'Receipt ID'

    def order_link(self, obj):
        url = reverse('admin:crossroad_deals_crossroadorder_change', args=[obj.order.pk])
        return format_html('<a href="{}">Order {}</a>', url, str(obj.order.order_id)[:8])

    order_link.short_description = 'Order'

    def has_add_permission(self, request):
        return False


@admin.register(CrossroadReview)
class CrossroadReviewAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'rating_stars',
        'seller_link',
        'reviewer_link',
        'product_as_described',
        'is_flagged',
        'created_at',
    ]
    list_filter = ['rating', 'product_as_described', 'would_buy_again', 'is_flagged', 'created_at']
    search_fields = ['seller__username', 'reviewer__username', 'comment']
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        ('Review Info', {
            'fields': ('order', 'reviewer', 'seller')
        }),
        ('Rating', {
            'fields': ('rating', 'title', 'comment')
        }),
        ('Feedback', {
            'fields': ('product_as_described', 'would_buy_again')
        }),
        ('Moderation', {
            'fields': ('is_flagged', 'flagged_reason')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )

    def rating_stars(self, obj):
        stars = '⭐' * obj.rating
        color = 'green' if obj.rating >= 4 else ('orange' if obj.rating >= 3 else 'red')
        return format_html('<span style="color: {};">{}</span>', color, stars)

    rating_stars.short_description = 'Rating'

    def seller_link(self, obj):
        url = reverse('admin:accounts_user_change', args=[obj.seller.pk])
        return format_html('<a href="{}">{}</a>', url, obj.seller.username)

    seller_link.short_description = 'Seller'

    def reviewer_link(self, obj):
        url = reverse('admin:accounts_user_change', args=[obj.reviewer.pk])
        return format_html('<a href="{}">{}</a>', url, obj.reviewer.username)

    reviewer_link.short_description = 'Reviewer'


@admin.register(SellerSuspension)
class SellerSuspensionAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'seller_link',
        'reason',
        'bad_review_count',
        'is_permanent_ban',
        'is_lifted',
        'suspended_at',
    ]
    list_filter = ['reason', 'is_permanent_ban', 'is_lifted', 'auto_suspended', 'suspended_at']
    search_fields = ['seller__username', 'description']
    readonly_fields = ['suspended_at', 'auto_suspended']

    fieldsets = (
        ('Suspension Info', {
            'fields': ('seller', 'reason', 'description', 'bad_review_count')
        }),
        ('Type', {
            'fields': ('is_permanent_ban', 'auto_suspended')
        }),
        ('Suspension', {
            'fields': ('suspended_at', 'suspended_by', 'suspended_until')
        }),
        ('Lift Status', {
            'fields': ('is_lifted', 'lifted_at', 'lifted_by')
        }),
    )

    def seller_link(self, obj):
        url = reverse('admin:accounts_user_change', args=[obj.seller.pk])
        return format_html('<a href="{}">{}</a>', url, obj.seller.username)

    seller_link.short_description = 'Seller'


@admin.register(DeviceActivityLog)
class DeviceActivityLogAdmin(ReadOnlyAllFieldsAdmin):
    list_display = ['id', 'user_link', 'action_type', 'ip_address', 'created_at']
    list_filter = ['action_type', 'created_at']
    search_fields = ['user__username', 'ip_address']

    def user_link(self, obj):
        url = reverse('admin:accounts_user_change', args=[obj.user.pk])
        return format_html('<a href="{}">{}</a>', url, obj.user.username)

    user_link.short_description = 'User'

    def has_add_permission(self, request):
        return False


@admin.register(ListingInterest)
class ListingInterestAdmin(ReadOnlyAllFieldsAdmin):
    list_display = ['id', 'user_link', 'listing_link', 'created_at']
    list_filter = ['created_at']
    search_fields = ['user__username', 'listing__title']

    def user_link(self, obj):
        url = reverse('admin:accounts_user_change', args=[obj.user.pk])
        return format_html('<a href="{}">{}</a>', url, obj.user.username)

    user_link.short_description = 'User'

    def listing_link(self, obj):
        url = reverse('admin:crossroad_deals_crossroadlisting_change', args=[obj.listing.pk])
        return format_html('<a href="{}">{}</a>', url, obj.listing.title)

    listing_link.short_description = 'Listing'

    def has_add_permission(self, request):
        return False
