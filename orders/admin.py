from django.contrib import admin
from .models import (
    PromoCode, Order, OrderItem, ShippingAddress,
    Return, ReturnItem, ReturnRefund,
    OrderStatusHistory, ReturnStatusHistory, ReturnImage,
    StoreInventory, ChatMessage
)


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('product', 'quantity', 'price_at_time')


class ReturnItemInline(admin.TabularInline):
    model = ReturnItem
    extra = 0


class ReturnImageInline(admin.TabularInline):
    model = ReturnImage
    extra = 0


@admin.register(PromoCode)
class PromoCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'discount_percentage', 'influencer', 'is_active', 'usage_limit', 'usage_count', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('code', 'influencer__celebrity_name')
    filter_horizontal = ('products',)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'buyer', 'status', 'created_at', 'get_total', 'promo_code')
    list_filter = ('status', 'created_at')
    search_fields = ('id', 'buyer__username', 'tracking_number')
    inlines = [OrderItemInline]
    readonly_fields = ('created_at', 'updated_at', 'shipped_date', 'delivered_date', 'payment_date')


@admin.register(OrderStatusHistory)
class OrderStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ('order', 'status', 'changed_by', 'timestamp')
    list_filter = ('status', 'timestamp')
    search_fields = ('order__id', 'changed_by__username')


@admin.register(ShippingAddress)
class ShippingAddressAdmin(admin.ModelAdmin):
    list_display = ('user', 'full_name', 'city', 'region', 'country', 'is_default')
    list_filter = ('is_default', 'country', 'created_at')
    search_fields = ('user__username', 'full_name', 'street', 'city')


@admin.register(Return)
class ReturnAdmin(admin.ModelAdmin):
    list_display = ('return_number', 'order', 'buyer', 'status', 'refund_amount', 'created_at')
    list_filter = ('status', 'logistics_method', 'created_at')
    search_fields = ('return_number', 'order__id', 'buyer__username', 'tracking_number')
    inlines = [ReturnItemInline, ReturnImageInline]
    readonly_fields = ('return_number', 'created_at', 'updated_at', 'approved_at', 'completed_at')


@admin.register(ReturnItem)
class ReturnItemAdmin(admin.ModelAdmin):
    list_display = ('return_request', 'product', 'quantity', 'condition', 'price_at_return')
    list_filter = ('condition',)
    search_fields = ('return_request__return_number', 'product__name')


@admin.register(ReturnRefund)
class ReturnRefundAdmin(admin.ModelAdmin):
    list_display = ('return_request', 'refund_amount', 'refund_method', 'status', 'processed_at')
    list_filter = ('status', 'refund_method', 'processed_at')
    search_fields = ('return_request__return_number',)


@admin.register(ReturnStatusHistory)
class ReturnStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ('return_request', 'status', 'changed_by', 'timestamp')
    list_filter = ('status',)
    search_fields = ('return_request__return_number', 'changed_by__username')


@admin.register(ReturnImage)
class ReturnImageAdmin(admin.ModelAdmin):
    list_display = ('return_request', 'image', 'description', 'uploaded_at')
    readonly_fields = ('uploaded_at',)


@admin.register(StoreInventory)
class StoreInventoryAdmin(admin.ModelAdmin):
    list_display = ('store_name', 'regular_stock', 'returned_stock', 'discounted_stock', 'last_updated')
    search_fields = ('store_name',)
    readonly_fields = ('last_updated',)


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('order', 'sender', 'created_at', 'is_read')
    list_filter = ('is_read', 'created_at')
    search_fields = ('order__id', 'sender__username', 'content')
