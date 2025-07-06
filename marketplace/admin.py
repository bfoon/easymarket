from django.contrib import admin
from .models import Product, Category, ProductImage, ProductView, Cart, CartItem, CelebrityFeature
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