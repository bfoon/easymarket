from django.contrib import admin
from .models import (Order, OrderItem, ShippingAddress,
                     OrderStatusHistory, PromoCode, ChatMessage)

admin.site.register(Order)
admin.site.register(OrderItem)
admin.site.register(ShippingAddress)
admin.site.register(OrderStatusHistory)
admin.site.register(PromoCode)


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ['order', 'sender', 'content_preview', 'created_at', 'is_read']
    list_filter = ['created_at', 'is_read', 'order__status']
    search_fields = ['content', 'sender__username', 'order__id']
    raw_id_fields = ['order', 'sender']
    readonly_fields = ['created_at']

    def content_preview(self, obj):
        return obj.content[:50] + "..." if len(obj.content) > 50 else obj.content

    content_preview.short_description = 'Message Preview'
