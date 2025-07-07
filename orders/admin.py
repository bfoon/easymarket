from django.contrib import admin
from .models import (Order, OrderItem, ShippingAddress,
                     OrderStatusHistory, PromoCode)

admin.site.register(Order)
admin.site.register(OrderItem)
admin.site.register(ShippingAddress)
admin.site.register(OrderStatusHistory)
admin.site.register(PromoCode)