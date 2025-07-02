from django.contrib import admin
from .models import Product, Category, ProductImage, ProductView, Cart, CartItem

admin.site.register(Product)
admin.site.register(Category)
admin.site.register(ProductImage)
admin.site.register(ProductView)
admin.site.register(Cart)
admin.site.register(CartItem)