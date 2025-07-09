from django.contrib import admin
from .models import (Product, Category, ProductImage, ProductView,
                     Cart, CartItem, CelebrityFeature, Wishlist, SearchHistory, PopularSearch)

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