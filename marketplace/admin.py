from django.contrib import admin
from .models import (Product, Category, ProductImage, ProductView,
                     Cart, CartItem, CelebrityFeature, Wishlist,
                     SearchHistory, PopularSearch, ProductFeature, ProductFeatureOption,
                     ProductVariant, SharedCart, Subscription, Career, CareerApplication,
                     PressRelease, InvestorDocument, InvestorEvent,
                     SocialCart, CartMember, CartInvite, PaymentShare, Contribution, Campaign, CampaignProduct, WheelSpin)
from django.utils.html import format_html
from django.urls import path
from django.http import JsonResponse
from .utils import ColorUtils
from django.http import HttpResponse
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
admin.site.register(ProductFeature)
admin.site.register(ProductFeatureOption)
admin.site.register(ProductVariant)
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
    fields = ('image', 'color', 'is_primary', 'alt_text', 'image_preview', 'suggest_color_link')
    readonly_fields = ('image_preview', 'suggest_color_link')

    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="width: 50px; height: 50px; object-fit: cover; border-radius: 4px;" />',
                obj.image.url
            )
        return "No image"

    image_preview.short_description = "Preview"

    def suggest_color_link(self, obj):
        if obj.pk and obj.image:
            return format_html(
                '<a href="#" onclick="suggestColor({})" class="button">Suggest Color</a>',
                obj.pk
            )
        return "Save first"

    suggest_color_link.short_description = "AI Suggestion"


class ProductImageAdmin(admin.ModelAdmin):
    list_display = ('product', 'color', 'is_primary', 'image_preview', 'created_at')
    list_filter = ('color', 'is_primary', 'created_at')
    search_fields = ('product__name', 'color', 'alt_text')
    list_editable = ('is_primary',)
    actions = ['suggest_colors_for_selected']

    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="width: 60px; height: 60px; object-fit: cover; border-radius: 4px;" />',
                obj.image.url
            )
        return "No image"

    image_preview.short_description = "Preview"

    def suggest_colors_for_selected(self, request, queryset):
        """Admin action to suggest colors for selected images"""
        updated = 0
        for image in queryset:
            if not image.color:
                suggested_color = ColorUtils.suggest_color_from_image(image)
                if suggested_color:
                    image.color = suggested_color
                    image.save()
                    updated += 1

        self.message_user(request, f'Updated {updated} images with color suggestions.')

    suggest_colors_for_selected.short_description = "Suggest colors for selected images"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('suggest-color/<int:image_id>/', self.suggest_color_view, name='suggest-color'),
        ]
        return custom_urls + urls

    def suggest_color_view(self, request, image_id):
        """AJAX view to suggest color for an image"""
        try:
            image = ProductImage.objects.get(id=image_id)
            suggested_color = ColorUtils.suggest_color_from_image(image)
            return JsonResponse({
                'success': True,
                'suggested_color': suggested_color
            })
        except ProductImage.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Image not found'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })

    class Media:
        js = ('admin/js/color_suggestions.js',)


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
    list_display = ('id','cart','owner','status','is_active','created_at')
    search_fields = ('invite_code','owner__username')

@admin.register(CartMember)
class CartMemberAdmin(admin.ModelAdmin):
    list_display = ('social_cart','user','role','status','joined_at')
    list_filter = ('role','status')

@admin.register(PaymentShare)
class PaymentShareAdmin(admin.ModelAdmin):
    list_display = ('social_cart','member','percentage','fixed_amount','items_total_amount','amount_due','is_active')

@admin.register(Contribution)
class ContributionAdmin(admin.ModelAdmin):
    list_display = ('social_cart','member','provider','amount','status','provider_ref','created_at')
    list_filter = ('provider','status')


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
    list_display = [
        'user_display', 'campaign', 'prize_won', 'prize_type',
        'prize_value', 'promo_code', 'is_redeemed', 'created_at'
    ]
    list_filter = ['campaign', 'prize_type', 'is_redeemed', 'created_at']
    search_fields = ['user__email', 'user__username', 'session_key', 'prize_won', 'promo_code']  # Added search_fields
    readonly_fields = [
        'campaign', 'user', 'session_key', 'prize_won', 'prize_type',
        'prize_value', 'promo_code', 'is_redeemed', 'redeemed_at',
        'ip_address', 'user_agent', 'created_at'
    ]

    date_hierarchy = 'created_at'

    fieldsets = (
        ('Spin Information', {
            'fields': ('campaign', 'user', 'session_key', 'created_at')
        }),
        ('Prize Details', {
            'fields': ('prize_won', 'prize_type', 'prize_value', 'promo_code')
        }),
        ('Redemption', {
            'fields': ('is_redeemed', 'redeemed_at')
        }),
        ('Technical', {
            'fields': ('ip_address', 'user_agent'),
            'classes': ('collapse',)
        })
    )

    def user_display(self, obj):
        if obj.user:
            return obj.user.email
        return f'Guest ({obj.session_key[:8]}...)'

    user_display.short_description = 'User'

    def has_add_permission(self, request):
        # Prevent manual creation of spins
        return False

    def has_change_permission(self, request, obj=None):
        # Only allow viewing, not editing
        return False


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