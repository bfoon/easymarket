from django.contrib import admin
from .models import (Product, Category, ProductImage, ProductView,
                     Cart, CartItem, CelebrityFeature, Wishlist,
                     SearchHistory, PopularSearch, ProductFeature, ProductFeatureOption,
                     ProductVariant, SharedCart, Subscription, Career, CareerApplication,
                     PressRelease, InvestorDocument, InvestorEvent)
from django.utils.html import format_html
from django.urls import path
from django.http import JsonResponse
from .utils import ColorUtils
from django.http import HttpResponse
from django.utils import timezone
import csv

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
