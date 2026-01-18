from django.contrib import admin
from .models import (Product, Category, ProductImage, ProductView,
                     Cart, CartItem, CelebrityFeature, Wishlist,
                     SearchHistory, PopularSearch, ProductFeature, ProductFeatureOption,
                     ProductVariant, SharedCart, Subscription, Career, CareerApplication,
                     PressRelease, InvestorDocument, InvestorEvent,
                     SocialCart, CartMember, CartInvite, PaymentShare, Contribution, Campaign, CampaignProduct,
                     WheelSpin)
from django.utils.html import format_html
from django.urls import path
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
import csv
from django.urls import reverse


class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'parent',)
    list_filter = ('parent',)
    search_fields = ('name',)


admin.site.register(Category, CategoryAdmin)
admin.site.register(Product)
admin.site.register(ProductImage)
admin.site.register(ProductView)
admin.site.register(Cart)
admin.site.register(CartItem)
admin.site.register(CelebrityFeature)
admin.site.register(Wishlist)


@admin.register(ProductFeature)
class ProductFeatureAdmin(admin.ModelAdmin):
    list_display = ('name', 'get_options_count')
    search_fields = ('name',)

    def get_options_count(self, obj):
        """Display count of options for this feature"""
        count = obj.options.count()
        return format_html(
            '<a href="/admin/marketplace/productfeatureoption/?feature__id__exact={}">{} option{}</a>',
            obj.id,
            count,
            's' if count != 1 else ''
        )

    get_options_count.short_description = "Options"


@admin.register(ProductFeatureOption)
class ProductFeatureOptionAdmin(admin.ModelAdmin):
    list_display = ('feature', 'value', 'color_preview', 'color_code')
    list_filter = ('feature',)
    search_fields = ('value', 'feature__name')
    list_editable = ('color_code',)

    def color_preview(self, obj):
        """Display color preview if color_code exists"""
        if obj.color_code:
            return format_html(
                '<div style="width: 30px; height: 30px; background-color: {}; border: 2px solid #ddd; border-radius: 4px; display: inline-block;"></div>',
                obj.color_code
            )
        return "-"

    color_preview.short_description = "Color"


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ('product', 'get_feature_name', 'get_option_value', 'get_image_preview')
    list_filter = ('feature_option__feature',)
    search_fields = ('product__name', 'feature_option__value')
    raw_id_fields = ('product',)

    def get_feature_name(self, obj):
        """Display feature name"""
        return obj.feature_option.feature.name

    get_feature_name.short_description = "Feature"
    get_feature_name.admin_order_field = 'feature_option__feature__name'

    def get_option_value(self, obj):
        """Display option value with color preview if applicable"""
        if obj.feature_option.color_code:
            return format_html(
                '<div style="display: flex; align-items: center; gap: 8px;">'
                '<div style="width: 20px; height: 20px; background-color: {}; border: 2px solid #ddd; border-radius: 50%;"></div>'
                '<span>{}</span>'
                '</div>',
                obj.feature_option.color_code,
                obj.feature_option.value
            )
        return obj.feature_option.value

    get_option_value.short_description = "Value"
    get_option_value.admin_order_field = 'feature_option__value'

    def get_image_preview(self, obj):
        """Display variant image if exists"""
        if hasattr(obj, 'image') and obj.image:
            return format_html(
                '<img src="{}" style="width: 40px; height: 40px; object-fit: cover; border-radius: 4px;" />',
                obj.image.url
            )
        return "-"

    get_image_preview.short_description = "Image"


admin.site.register(SharedCart)


@admin.register(SearchHistory)
class SearchHistoryAdmin(admin.ModelAdmin):
    list_display = ['query', 'user', 'results_count', 'timestamp', 'ip_address']
    list_filter = ['timestamp', 'results_count']
    search_fields = ['query', 'user__username']
    readonly_fields = ['timestamp']
    date_hierarchy = 'timestamp'


@admin.register(PopularSearch)
class PopularSearchAdmin(admin.ModelAdmin):
    list_display = ['query', 'search_count', 'last_searched']
    list_filter = ['last_searched']
    search_fields = ['query']
    readonly_fields = ['last_searched']
    ordering = ['-search_count']


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ('image', 'is_primary', 'alt_text', 'image_preview')
    readonly_fields = ('image_preview',)

    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="width: 50px; height: 50px; object-fit: cover; border-radius: 4px;" />',
                obj.image.url
            )
        return "No image"

    image_preview.short_description = "Preview"


class ProductImageAdmin(admin.ModelAdmin):
    list_display = ('product', 'get_variants_display', 'is_primary', 'image_preview', 'created_at')
    list_filter = ('is_primary', 'created_at')
    search_fields = ('product__name', 'alt_text')
    list_editable = ('is_primary',)
    filter_horizontal = ('variants',)

    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="width: 60px; height: 60px; object-fit: cover; border-radius: 4px;" />',
                obj.image.url
            )
        return "No image"

    image_preview.short_description = "Preview"

    def get_variants_display(self, obj):
        """Display variants associated with this image"""
        variants = obj.variants.all()
        if variants.exists():
            variant_list = ', '.join([f"{v.feature.name}: {v.value}" for v in variants[:3]])
            if variants.count() > 3:
                variant_list += f" (+{variants.count() - 3} more)"
            return variant_list
        return "No variants"

    get_variants_display.short_description = "Variants"


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("email", "active", "subscribed_at", "source")
    list_filter = ("active", "source", "subscribed_at")
    search_fields = ("email",)
    actions = ["export_subscriptions_csv"]

    @admin.action(description="Export selected subscriptions to CSV")
    def export_subscriptions_csv(self, request, queryset):
        """
        Exports the selected rows. If the user clicks 'Select all' in the admin,
        Django passes the *entire filtered* queryset here.
        """
        # Prepare response
        ts = timezone.now().strftime("%Y%m%d_%H%M%S")
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="subscriptions_{ts}.csv"'

        writer = csv.writer(response)
        # Header
        writer.writerow(["email", "active", "subscribed_at", "source"])

        # Body (stream in chunks for large exports)
        for s in queryset.iterator(chunk_size=2000):
            # Localize/format datetime nicely
            dt = timezone.localtime(s.subscribed_at).strftime("%Y-%m-%d %H:%M:%S")
            writer.writerow([s.email, "yes" if s.active else "no", dt, s.source or ""])

        return response


@admin.register(Career)
class CareerAdmin(admin.ModelAdmin):
    list_display = ("title", "department", "location", "employment_type", "is_active", "created_at")
    list_filter = ("department", "employment_type", "is_active", "remote_friendly", "location")
    search_fields = ("title", "location", "slug", "summary", "description")
    prepopulated_fields = {"slug": ("title",)}
    date_hierarchy = "created_at"


@admin.register(CareerApplication)
class CareerApplicationAdmin(admin.ModelAdmin):
    list_display = ("application_code", "full_name", "job", "status", "created_at")
    list_filter = ("status", "job__department")
    search_fields = ("application_code", "full_name", "email", "job__title")
    readonly_fields = ("application_code", "created_at", "updated_at", "ip_address", "user_agent")


@admin.register(PressRelease)
class PressReleaseAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "is_published", "publish_at")
    list_filter = ("is_published", "category", "publish_at")
    search_fields = ("title", "subtitle", "summary", "body", "slug")
    prepopulated_fields = {"slug": ("title",)}
    date_hierarchy = "publish_at"
    readonly_fields = ("created_at", "updated_at")


@admin.register(InvestorDocument)
class InvestorDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "is_published", "publish_at")
    list_filter = ("category", "is_published")
    search_fields = ("title", "summary", "slug")
    prepopulated_fields = {"slug": ("title",)}
    date_hierarchy = "publish_at"
    readonly_fields = ("created_at", "updated_at")


@admin.register(InvestorEvent)
class InvestorEventAdmin(admin.ModelAdmin):
    list_display = ("title", "event_type", "start_at", "is_public")
    list_filter = ("event_type", "is_public")
    search_fields = ("title", "location", "notes")
    date_hierarchy = "start_at"


@admin.register(SocialCart)
class SocialCartAdmin(admin.ModelAdmin):
    list_display = ('id', 'cart', 'owner', 'status', 'is_active', 'created_at')
    search_fields = ('invite_code', 'owner__username')


@admin.register(CartMember)
class CartMemberAdmin(admin.ModelAdmin):
    list_display = ('social_cart', 'user', 'role', 'status', 'joined_at')
    list_filter = ('role', 'status')


@admin.register(PaymentShare)
class PaymentShareAdmin(admin.ModelAdmin):
    list_display = (
    'social_cart', 'member', 'percentage', 'fixed_amount', 'items_total_amount', 'amount_due', 'is_active')


@admin.register(Contribution)
class ContributionAdmin(admin.ModelAdmin):
    list_display = ('social_cart', 'member', 'provider', 'amount', 'status', 'provider_ref', 'created_at')
    list_filter = ('provider', 'status')


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'campaign_type', 'status_badge', 'start_date',
        'end_date', 'total_views', 'total_spins', 'total_conversions',
        'product_count', 'actions_column'
    ]
    list_filter = ['status', 'campaign_type', 'is_active', 'start_date', 'end_date']
    search_fields = ['name', 'title', 'description', 'slug']  # REQUIRED for autocomplete
    readonly_fields = [
        'slug', 'total_views', 'total_spins', 'total_conversions',
        'created_at', 'updated_at', 'created_by'
    ]

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'slug', 'title', 'description', 'campaign_type')
        }),
        ('Schedule', {
            'fields': ('start_date', 'end_date', 'status', 'is_active')
        }),
        ('Display Settings', {
            'fields': ('banner_image', 'background_color', 'text_color')
        }),
        ('Wheel Configuration', {
            'fields': ('enable_wheel', 'wheel_prizes', 'max_spins_per_user', 'require_login'),
            'description': 'Configure the spinning wheel settings for this campaign.'
        }),
        ('Analytics', {
            'fields': ('total_views', 'total_spins', 'total_conversions'),
            'classes': ('collapse',)
        }),
        ('Meta', {
            'fields': ('created_at', 'updated_at', 'created_by'),
            'classes': ('collapse',)
        })
    )

    def status_badge(self, obj):
        colors = {
            'draft': 'gray',
            'scheduled': 'blue',
            'active': 'green',
            'ended': 'orange',
            'cancelled': 'red'
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="background: {}; color: white; padding: 4px 12px; '
            'border-radius: 12px; font-size: 0.85rem; font-weight: 600;">{}</span>',
            color, obj.get_status_display()
        )

    status_badge.short_description = 'Status'

    def product_count(self, obj):
        count = obj.campaign_products.count()
        url = reverse('admin:marketplace_campaignproduct_changelist') + f'?campaign__id__exact={obj.id}'
        return format_html('<a href="{}">{} products</a>', url, count)

    product_count.short_description = 'Products'

    def actions_column(self, obj):
        if obj.is_running():
            return format_html(
                '<a class="button" href="{}">View Campaign</a>',
                reverse('marketplace:campaign_detail', args=[obj.slug])
            )
        return '-'

    actions_column.short_description = 'Actions'

    def save_model(self, request, obj, form, change):
        if not change:  # New object
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    class Media:
        css = {
            'all': ('admin/css/campaign_admin.css',)
        }


class CampaignProductInline(admin.TabularInline):
    model = CampaignProduct
    extra = 1
    fields = ['product', 'discount_type', 'discount_value', 'position', 'is_featured', 'campaign_stock', 'stock_sold']
    readonly_fields = ['stock_sold']
    # Remove autocomplete_fields from inline to avoid errors
    raw_id_fields = ['product']  # Use raw_id instead


@admin.register(CampaignProduct)
class CampaignProductAdmin(admin.ModelAdmin):
    list_display = [
        'product', 'campaign', 'discount_display', 'campaign_price_display',
        'position', 'is_featured', 'stock_display', 'created_at'
    ]
    list_filter = ['campaign', 'discount_type', 'is_featured', 'created_at']
    search_fields = ['product__name', 'campaign__name', 'campaign__title']  # REQUIRED for autocomplete
    # Use raw_id_fields instead of autocomplete_fields to avoid the error
    raw_id_fields = ['campaign', 'product']
    readonly_fields = ['stock_sold', 'created_at']

    fieldsets = (
        ('Product & Campaign', {
            'fields': ('campaign', 'product')
        }),
        ('Discount Configuration', {
            'fields': ('discount_type', 'discount_value')
        }),
        ('Display Settings', {
            'fields': ('position', 'is_featured')
        }),
        ('Stock Management', {
            'fields': ('campaign_stock', 'stock_sold')
        }),
        ('Meta', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        })
    )

    def discount_display(self, obj):
        if obj.discount_type == 'percentage':
            return f'{obj.discount_value}%'
        elif obj.discount_type == 'fixed':
            return f'D{obj.discount_value}'
        else:
            return f'D{obj.discount_value} (Special)'

    discount_display.short_description = 'Discount'

    def campaign_price_display(self, obj):
        price = obj.get_campaign_price()
        original = obj.product.price
        savings = original - price
        return format_html(
            '<strong>D{}</strong> <small>(was D{}, save D{})</small>',
            price, original, savings
        )

    campaign_price_display.short_description = 'Campaign Price'

    def stock_display(self, obj):
        if obj.campaign_stock is None:
            return format_html('<span style="color: green;">Unlimited</span>')

        remaining = obj.remaining_stock()
        if remaining == 0:
            return format_html('<span style="color: red;">Sold Out ({}/{})</span>',
                               obj.stock_sold, obj.campaign_stock)
        elif remaining <= 5:
            return format_html('<span style="color: orange;">Low Stock ({}/{})</span>',
                               obj.stock_sold, obj.campaign_stock)
        else:
            return format_html('{}/{}', obj.stock_sold, obj.campaign_stock)

    stock_display.short_description = 'Stock'


@admin.register(WheelSpin)
class WheelSpinAdmin(admin.ModelAdmin):
    """Admin interface for WheelSpin model"""

    list_display = [
        'id',
        'campaign',
        'user_display',
        'prize_won',
        'prize_type',
        'promo_code_display',
        'is_redeemed',
        'spun_at'  # Changed from 'created_at' to 'spun_at'
    ]

    list_filter = [
        'campaign',
        'prize_type',
        'is_redeemed',
        'spun_at'  # Changed from 'created_at' to 'spun_at'
    ]

    search_fields = [
        'user__username',
        'user__email',
        'session_key',
        'prize_won',
        'promo_code__code'
    ]

    readonly_fields = [
        'spun_at',  # Changed from 'created_at'
        'redeemed_at',
        'ip_address',
        'user_agent',
        'prize_won',
        'prize_type',
        'prize_value',
        'session_key',
    ]

    raw_id_fields = ['user', 'campaign', 'promo_code', 'order']

    date_hierarchy = 'spun_at'  # Changed from 'created_at' to 'spun_at'

    fieldsets = (
        ('Campaign & User', {
            'fields': ('campaign', 'user', 'session_key')
        }),
        ('Prize Details', {
            'fields': ('prize_won', 'prize_type', 'prize_value', 'promo_code')
        }),
        ('Redemption Status', {
            'fields': ('is_redeemed', 'redeemed_at', 'order')
        }),
        ('Tracking Information', {
            'fields': ('spun_at', 'ip_address', 'user_agent'),
            'classes': ('collapse',)
        }),
    )

    def user_display(self, obj):
        """Display user or session info"""
        if obj.user:
            return f"{obj.user.username} ({obj.user.email})"
        return f"Anonymous ({obj.session_key[:8]}...)" if obj.session_key else "Anonymous"

    user_display.short_description = 'User'
    user_display.admin_order_field = 'user'

    def promo_code_display(self, obj):
        """Display promo code if exists"""
        if obj.promo_code:
            return obj.promo_code.code
        return "-"

    promo_code_display.short_description = 'Promo Code'
    promo_code_display.admin_order_field = 'promo_code__code'

    def has_add_permission(self, request):
        """Prevent manual creation - spins should only come from wheel"""
        return False

    def get_queryset(self, request):
        """Optimize queries"""
        qs = super().get_queryset(request)
        return qs.select_related('campaign', 'user', 'promo_code', 'order')

    actions = ['mark_as_redeemed', 'mark_as_unredeemed']

    def mark_as_redeemed(self, request, queryset):
        """Admin action to mark spins as redeemed"""
        count = 0
        for spin in queryset:
            if not spin.is_redeemed:
                spin.mark_redeemed()
                count += 1
        self.message_user(request, f"{count} wheel spin(s) marked as redeemed.")

    mark_as_redeemed.short_description = "Mark selected spins as redeemed"

    def mark_as_unredeemed(self, request, queryset):
        """Admin action to mark spins as unredeemed (careful!)"""
        count = queryset.update(is_redeemed=False, redeemed_at=None, order=None)
        self.message_user(request, f"{count} wheel spin(s) marked as unredeemed.")

    mark_as_unredeemed.short_description = "Mark selected spins as unredeemed"


# Optional: Custom admin actions for campaigns
@admin.action(description='Activate selected campaigns')
def activate_campaigns(modeladmin, request, queryset):
    queryset.update(is_active=True)


@admin.action(description='Deactivate selected campaigns')
def deactivate_campaigns(modeladmin, request, queryset):
    queryset.update(is_active=False)


@admin.action(description='Cancel selected campaigns')
def cancel_campaigns(modeladmin, request, queryset):
    queryset.update(status=Campaign.Status.CANCELLED, is_active=False)


# Add these actions to CampaignAdmin
CampaignAdmin.actions = [activate_campaigns, deactivate_campaigns, cancel_campaigns]