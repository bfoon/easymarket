"""
Supply Chain Admin Interface

Admin configuration for managing store-to-logistics transfers and fulfillment.
"""

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
from .models import (
    StoreToLogisticsTransfer, TransferItem, FulfillmentQueue, WarehouseLinkage
)


@admin.register(WarehouseLinkage)
class WarehouseLinkageAdmin(admin.ModelAdmin):
    list_display = (
        'store_warehouse', 'logistics_warehouse', 'is_primary',
        'is_active', 'distance_km', 'estimated_transfer_time_minutes',
        'todays_transfers', 'capacity_status'
    )
    list_filter = ('is_primary', 'is_active', 'logistics_warehouse')
    search_fields = (
        'store_warehouse__name', 'store_warehouse__code',
        'logistics_warehouse__name', 'logistics_warehouse__code'
    )
    readonly_fields = ('created_at', 'updated_at', 'todays_transfers')

    fieldsets = (
        ('Warehouse Link', {
            'fields': ('store_warehouse', 'logistics_warehouse', 'is_primary', 'is_active')
        }),
        ('Logistics', {
            'fields': ('distance_km', 'estimated_transfer_time_minutes')
        }),
        ('Capacity', {
            'fields': ('max_daily_transfers', 'todays_transfers')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def todays_transfers(self, obj):
        count = obj.get_todays_transfer_count()
        return f"{count} / {obj.max_daily_transfers}"

    todays_transfers.short_description = "Today's Transfers"

    def capacity_status(self, obj):
        count = obj.get_todays_transfer_count()
        percentage = (count / obj.max_daily_transfers) * 100 if obj.max_daily_transfers > 0 else 0

        if percentage >= 100:
            color = 'red'
            status = 'AT CAPACITY'
        elif percentage >= 80:
            color = 'orange'
            status = 'NEAR CAPACITY'
        else:
            color = 'green'
            status = 'AVAILABLE'

        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, status
        )

    capacity_status.short_description = 'Status'


class TransferItemInline(admin.TabularInline):
    model = TransferItem
    extra = 0
    readonly_fields = ('transferred', 'transferred_at', 'order_item')
    fields = (
        'product', 'quantity', 'order_item', 'stock_reservation',
        'transferred', 'damaged', 'condition_notes'
    )

    def has_add_permission(self, request, obj=None):
        # Prevent adding items after transfer is created
        if obj and obj.status != 'PENDING':
            return False
        return super().has_add_permission(request, obj)


@admin.register(StoreToLogisticsTransfer)
class StoreToLogisticsTransferAdmin(admin.ModelAdmin):
    list_display = (
        'transfer_number', 'order_link', 'store_warehouse', 'logistics_warehouse',
        'status_display', 'requested_at', 'received_at', 'duration_display'
    )
    list_filter = (
        'status', 'store_warehouse', 'logistics_warehouse',
        'requested_at', 'received_at'
    )
    search_fields = (
        'transfer_number', 'order__id',
        'store_warehouse__name', 'logistics_warehouse__name'
    )
    readonly_fields = (
        'transfer_number', 'requested_at', 'picked_up_at', 'received_at',
        'actual_duration_minutes', 'is_complete', 'is_in_progress'
    )
    inlines = [TransferItemInline]
    date_hierarchy = 'requested_at'

    fieldsets = (
        ('Transfer Details', {
            'fields': ('transfer_number', 'order', 'status')
        }),
        ('Warehouses', {
            'fields': ('store_warehouse', 'logistics_warehouse')
        }),
        ('Timeline', {
            'fields': (
                'requested_at', 'pickup_scheduled', 'picked_up_at',
                'received_at', 'estimated_duration_minutes', 'actual_duration_minutes'
            )
        }),
        ('Personnel', {
            'fields': ('requested_by', 'picked_up_by', 'received_by')
        }),
        ('Logistics', {
            'fields': ('vehicle', 'driver')
        }),
        ('Notes', {
            'fields': ('notes', 'rejection_reason')
        }),
        ('Status Flags', {
            'fields': ('is_complete', 'is_in_progress'),
            'classes': ('collapse',)
        }),
    )

    actions = ['mark_picked_up', 'mark_received', 'cancel_transfer']

    def order_link(self, obj):
        if obj.order:
            url = reverse('admin:orders_order_change', args=[obj.order.id])
            return format_html('<a href="{}">[Order #{}]</a>', url, obj.order.id)
        return '-'

    order_link.short_description = 'Order'

    def status_display(self, obj):
        colors = {
            'PENDING': 'orange',
            'IN_TRANSIT': 'blue',
            'RECEIVED': 'green',
            'CANCELLED': 'red',
            'REJECTED': 'darkred'
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, obj.get_status_display()
        )

    status_display.short_description = 'Status'

    def duration_display(self, obj):
        if obj.actual_duration_minutes:
            hours = obj.actual_duration_minutes // 60
            minutes = obj.actual_duration_minutes % 60
            return f"{hours}h {minutes}m"
        return '-'

    duration_display.short_description = 'Duration'

    def mark_picked_up(self, request, queryset):
        for transfer in queryset.filter(status='PENDING'):
            transfer.mark_picked_up(request.user)
        self.message_user(request, f"{queryset.count()} transfers marked as picked up")

    mark_picked_up.short_description = "Mark selected as picked up"

    def mark_received(self, request, queryset):
        for transfer in queryset.filter(status='IN_TRANSIT'):
            transfer.mark_received(request.user)
        self.message_user(request, f"{queryset.count()} transfers marked as received")

    mark_received.short_description = "Mark selected as received"

    def cancel_transfer(self, request, queryset):
        for transfer in queryset.filter(status__in=['PENDING', 'IN_TRANSIT']):
            transfer.cancel("Cancelled via admin")
        self.message_user(request, f"{queryset.count()} transfers cancelled")

    cancel_transfer.short_description = "Cancel selected transfers"


@admin.register(TransferItem)
class TransferItemAdmin(admin.ModelAdmin):
    list_display = (
        'transfer', 'product', 'quantity', 'order_item',
        'transferred', 'damaged'
    )
    list_filter = ('transferred', 'damaged', 'transfer__status')
    search_fields = (
        'product__name', 'transfer__transfer_number',
        'order_item__order__id'
    )
    readonly_fields = ('transferred_at',)


@admin.register(FulfillmentQueue)
class FulfillmentQueueAdmin(admin.ModelAdmin):
    list_display = (
        'order_link', 'logistics_warehouse', 'status_display',
        'priority_display', 'queued_at', 'picker', 'packer',
        'time_metrics', 'overdue_flag'
    )
    list_filter = (
        'status', 'priority', 'logistics_warehouse',
        'queued_at'
    )
    search_fields = (
        'order__id', 'order__customer__email',
        'logistics_warehouse__name'
    )
    readonly_fields = (
        'queued_at', 'picking_started_at', 'packing_started_at',
        'ready_at', 'shipped_at', 'actual_pick_time_minutes',
        'actual_pack_time_minutes', 'total_fulfillment_time',
        'is_overdue'
    )
    date_hierarchy = 'queued_at'

    fieldsets = (
        ('Order Details', {
            'fields': ('order', 'logistics_warehouse', 'transfer', 'shipment')
        }),
        ('Status & Priority', {
            'fields': ('status', 'priority', 'is_overdue')
        }),
        ('Timeline', {
            'fields': (
                'queued_at', 'picking_started_at', 'packing_started_at',
                'ready_at', 'shipped_at', 'total_fulfillment_time'
            )
        }),
        ('Personnel', {
            'fields': ('picker', 'packer')
        }),
        ('Time Estimates', {
            'fields': (
                'estimated_pick_time_minutes', 'actual_pick_time_minutes',
                'estimated_pack_time_minutes', 'actual_pack_time_minutes'
            )
        }),
        ('Notes', {
            'fields': ('notes',)
        }),
    )

    actions = ['start_picking', 'start_packing', 'mark_ready', 'increase_priority']

    def order_link(self, obj):
        url = reverse('admin:orders_order_change', args=[obj.order.id])
        return format_html('<a href="{}">[Order #{}]</a>', url, obj.order.id)

    order_link.short_description = 'Order'

    def status_display(self, obj):
        colors = {
            'QUEUED': 'orange',
            'PICKING': 'blue',
            'PACKING': 'purple',
            'READY': 'green',
            'SHIPPED': 'darkgreen',
            'CANCELLED': 'red'
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, obj.get_status_display()
        )

    status_display.short_description = 'Status'

    def priority_display(self, obj):
        colors = {
            'LOW': 'gray',
            'NORMAL': 'blue',
            'HIGH': 'orange',
            'URGENT': 'red'
        }
        color = colors.get(obj.priority, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, obj.get_priority_display()
        )

    priority_display.short_description = 'Priority'

    def time_metrics(self, obj):
        metrics = []

        if obj.actual_pick_time_minutes:
            metrics.append(f"Pick: {obj.actual_pick_time_minutes}m")

        if obj.actual_pack_time_minutes:
            metrics.append(f"Pack: {obj.actual_pack_time_minutes}m")

        if obj.total_fulfillment_time:
            metrics.append(f"Total: {obj.total_fulfillment_time}m")

        return " | ".join(metrics) if metrics else '-'

    time_metrics.short_description = 'Time Metrics'

    def overdue_flag(self, obj):
        if obj.is_overdue:
            return format_html('<span style="color: red; font-weight: bold;">⚠ OVERDUE</span>')
        return format_html('<span style="color: green;">✓ On Time</span>')

    overdue_flag.short_description = 'Timeliness'

    def start_picking(self, request, queryset):
        for queue in queryset.filter(status='QUEUED'):
            queue.start_picking(request.user)
        self.message_user(request, f"{queryset.count()} orders started picking")

    start_picking.short_description = "Start picking selected orders"

    def start_packing(self, request, queryset):
        for queue in queryset.filter(status='PICKING'):
            queue.start_packing(request.user)
        self.message_user(request, f"{queryset.count()} orders started packing")

    start_packing.short_description = "Start packing selected orders"

    def mark_ready(self, request, queryset):
        for queue in queryset.filter(status='PACKING'):
            queue.mark_ready()
        self.message_user(request, f"{queryset.count()} orders marked as ready")

    mark_ready.short_description = "Mark selected as ready"

    def increase_priority(self, request, queryset):
        priority_upgrade = {
            'LOW': 'NORMAL',
            'NORMAL': 'HIGH',
            'HIGH': 'URGENT'
        }

        for queue in queryset:
            if queue.priority in priority_upgrade:
                queue.priority = priority_upgrade[queue.priority]
                queue.save()

        self.message_user(request, f"Increased priority for {queryset.count()} orders")

    increase_priority.short_description = "Increase priority"