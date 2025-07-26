from django.contrib import admin
from .models import (Product, Category, ProductImage, ProductView,
                     Cart, CartItem, CelebrityFeature, Wishlist,
                     SearchHistory, PopularSearch, ProductFeature, ProductFeatureOption,
                     ProductVariant, SharedCart)
from django.utils.html import format_html
from django.urls import path
from django.http import JsonResponse
from .utils import ColorUtils

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