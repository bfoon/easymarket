from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Sum, F
from django.urls import reverse
from django.utils import timezone
from .models import (
    Warehouse, Stock, StockMovement, StockCount, StockCountItem,
    StockAlert, StockReservation, BatchTracking, StockAnalytics,
    Supplier, PurchaseOrder, PurchaseOrderItem
)


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = (
    'code', 'name', 'city', 'state', 'country', 'manager', 'has_geocode_display', 'is_active', 'total_stock_value',
    'created_at')
    list_filter = ('is_active', 'country', 'state', 'created_at')
    search_fields = ('name', 'code', 'address', 'city', 'state', 'country', 'postal_code')
    readonly_fields = ('created_at', 'full_address', 'has_geocode', 'coordinates_display')

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'code', 'is_active')
        }),
        ('Address', {
            'fields': ('address', 'city', 'state', 'country', 'postal_code', 'full_address')
        }),
        ('Geocoding', {
            'fields': ('latitude', 'longitude', 'has_geocode', 'coordinates_display'),
            'description': 'Geographic coordinates for location-based features'
        }),
        ('Management', {
            'fields': ('manager',)
        }),
        ('Metadata', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )

    def total_stock_value(self, obj):
        total = obj.stock_items.annotate(
            value=F('quantity') * F('unit_cost')
        ).aggregate(total=Sum('value'))['total'] or 0
        return f"D{total:,.2f}"

    total_stock_value.short_description = 'Total Stock Value'

    def has_geocode_display(self, obj):
        if obj.has_geocode:
            return format_html('<span style="color: green;">✓ Yes</span>')
        return format_html('<span style="color: orange;">✗ No</span>')

    has_geocode_display.short_description = 'Geocoded'

    def coordinates_display(self, obj):
        if obj.has_geocode:
            coords = obj.get_coordinates()
            return f"{coords[0]}, {coords[1]}"
        return 'Not set'

    coordinates_display.short_description = 'Coordinates (Lat, Lon)'


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = (
        'product', 'warehouse', 'quantity_display', 'available_quantity',
        'reserved_quantity', 'stock_status', 'unit_cost', 'stock_value_display',
        'updated_at'
    )
    list_filter = ('warehouse', 'updated_at')
    search_fields = ('product__name', 'product__sku', 'warehouse__code')
    readonly_fields = ('updated_at', 'available_quantity', 'stock_value', 'last_counted')

    fieldsets = (
        ('Product & Location', {
            'fields': ('product', 'warehouse')
        }),
        ('Quantity Information', {
            'fields': ('quantity', 'reserved_quantity', 'available_quantity')
        }),
        ('Reorder Settings', {
            'fields': ('reorder_level', 'reorder_quantity')
        }),
        ('Financial', {
            'fields': ('unit_cost', 'stock_value')
        }),
        ('Metadata', {
            'fields': ('updated_at', 'last_counted'),
            'classes': ('collapse',)
        }),
    )

    def quantity_display(self, obj):
        color = 'red' if obj.quantity == 0 else 'orange' if obj.is_below_reorder_level else 'green'
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, obj.quantity
        )

    quantity_display.short_description = 'Quantity'

    def stock_status(self, obj):
        if obj.quantity == 0:
            color = 'red'
            status = 'OUT OF STOCK'
        elif obj.is_below_reorder_level:
            color = 'orange'
            status = 'LOW STOCK'
        else:
            color = 'green'
            status = 'IN STOCK'

        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, status
        )

    stock_status.short_description = 'Status'

    def stock_value_display(self, obj):
        return f"D{obj.stock_value:,.2f}"

    stock_value_display.short_description = 'Stock Value'


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = (
        'created_at', 'product', 'warehouse', 'movement_type',
        'quantity_display', 'reference_number', 'created_by', 'total_value_display'
    )
    list_filter = ('movement_type', 'warehouse', 'created_at')
    search_fields = ('product__name', 'reference_number', 'notes')
    readonly_fields = ('created_at', 'total_value')
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Movement Details', {
            'fields': ('product', 'warehouse', 'movement_type', 'quantity')
        }),
        ('Financial', {
            'fields': ('unit_cost', 'total_value')
        }),
        ('Reference', {
            'fields': ('reference_number', 'destination_warehouse', 'notes')
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at'),
            'classes': ('collapse',)
        }),
    )

    def quantity_display(self, obj):
        color = 'green' if obj.quantity > 0 else 'red'
        prefix = '+' if obj.quantity > 0 else ''
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}{}</span>',
            color, prefix, obj.quantity
        )

    quantity_display.short_description = 'Quantity'

    def total_value_display(self, obj):
        return f"D{obj.total_value:,.2f}"

    total_value_display.short_description = 'Total Value'


@admin.register(StockCount)
class StockCountAdmin(admin.ModelAdmin):
    list_display = ('warehouse', 'count_date', 'status', 'counted_by', 'variance_summary', 'created_at')
    list_filter = ('status', 'warehouse', 'count_date')
    search_fields = ('warehouse__code', 'notes')
    readonly_fields = ('created_at', 'completed_at', 'variance_summary')
    inlines = []

    fieldsets = (
        ('Count Details', {
            'fields': ('warehouse', 'count_date', 'status')
        }),
        ('Personnel', {
            'fields': ('counted_by',)
        }),
        ('Summary', {
            'fields': ('variance_summary',)
        }),
        ('Notes', {
            'fields': ('notes',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'completed_at'),
            'classes': ('collapse',)
        }),
    )

    def variance_summary(self, obj):
        if obj.status != 'COMPLETED':
            return 'N/A (Not completed)'

        variances = obj.items.aggregate(
            positive=Sum('variance', filter=F('variance__gt', 0)),
            negative=Sum('variance', filter=F('variance__lt', 0))
        )

        positive = variances['positive'] or 0
        negative = abs(variances['negative'] or 0)

        return format_html(
            '<span style="color: green;">+{}</span> / <span style="color: red;">-{}</span>',
            positive, negative
        )

    variance_summary.short_description = 'Variance (+/-)'


class StockCountItemInline(admin.TabularInline):
    model = StockCountItem
    extra = 0
    readonly_fields = ('variance', 'variance_percentage')
    fields = ('product', 'expected_quantity', 'counted_quantity', 'variance', 'notes')


@admin.register(StockCountItem)
class StockCountItemAdmin(admin.ModelAdmin):
    list_display = (
        'stock_count', 'product', 'expected_quantity',
        'counted_quantity', 'variance_display', 'variance_percentage_display'
    )
    list_filter = ('stock_count__warehouse', 'stock_count__count_date')
    search_fields = ('product__name', 'stock_count__warehouse__code')
    readonly_fields = ('variance', 'variance_percentage')

    def variance_display(self, obj):
        color = 'green' if obj.variance > 0 else 'red' if obj.variance < 0 else 'gray'
        prefix = '+' if obj.variance > 0 else ''
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}{}</span>',
            color, prefix, obj.variance
        )

    variance_display.short_description = 'Variance'

    def variance_percentage_display(self, obj):
        pct = obj.variance_percentage
        color = 'green' if pct > 0 else 'red' if pct < 0 else 'gray'
        prefix = '+' if pct > 0 else ''
        return format_html(
            '<span style="color: {};">{}{:.1f}%</span>',
            color, prefix, pct
        )

    variance_percentage_display.short_description = 'Variance %'


@admin.register(StockAlert)
class StockAlertAdmin(admin.ModelAdmin):
    list_display = (
        'created_at', 'alert_type_display', 'product_link', 'warehouse',
        'status', 'acknowledged_by', 'acknowledged_at'
    )
    list_filter = ('alert_type', 'status', 'created_at')
    search_fields = ('stock__product__name', 'message')
    readonly_fields = ('created_at',)

    fieldsets = (
        ('Alert Information', {
            'fields': ('stock', 'alert_type', 'status', 'message')
        }),
        ('Acknowledgment', {
            'fields': ('acknowledged_by', 'acknowledged_at')
        }),
        ('Metadata', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )

    def alert_type_display(self, obj):
        colors = {
            'LOW_STOCK': 'orange',
            'OUT_OF_STOCK': 'red',
            'OVERSTOCK': 'blue',
            'EXPIRING_SOON': 'purple',
            'NEGATIVE_STOCK': 'darkred'
        }
        color = colors.get(obj.alert_type, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, obj.get_alert_type_display()
        )

    alert_type_display.short_description = 'Alert Type'

    def product_link(self, obj):
        return obj.stock.product.name

    product_link.short_description = 'Product'

    def warehouse(self, obj):
        return obj.stock.warehouse.code

    warehouse.short_description = 'Warehouse'


@admin.register(StockReservation)
class StockReservationAdmin(admin.ModelAdmin):
    list_display = (
        'order_reference', 'product', 'warehouse', 'quantity',
        'status_display', 'reserved_at', 'expires_at', 'reserved_by'
    )
    list_filter = ('is_active', 'reserved_at', 'stock__warehouse')
    search_fields = ('order_reference', 'stock__product__name')
    readonly_fields = ('reserved_at', 'is_expired')

    fieldsets = (
        ('Reservation Details', {
            'fields': ('stock', 'quantity', 'order_reference')
        }),
        ('Status & Timing', {
            'fields': ('is_active', 'reserved_at', 'expires_at', 'fulfilled_at', 'is_expired')
        }),
        ('User', {
            'fields': ('reserved_by',)
        }),
    )

    def status_display(self, obj):
        if obj.fulfilled_at:
            return format_html('<span style="color: green;">✓ Fulfilled</span>')
        elif obj.is_expired:
            return format_html('<span style="color: red;">✗ Expired</span>')
        elif obj.is_active:
            return format_html('<span style="color: blue;">◉ Active</span>')
        else:
            return format_html('<span style="color: gray;">○ Released</span>')

    status_display.short_description = 'Status'

    def product(self, obj):
        return obj.stock.product.name

    product.short_description = 'Product'

    def warehouse(self, obj):
        return obj.stock.warehouse.code

    warehouse.short_description = 'Warehouse'


@admin.register(BatchTracking)
class BatchTrackingAdmin(admin.ModelAdmin):
    list_display = (
        'batch_number', 'product', 'warehouse', 'quantity',
        'manufacturing_date', 'expiry_status', 'received_date'
    )
    list_filter = ('warehouse', 'received_date', 'expiry_date')
    search_fields = ('batch_number', 'product__name', 'supplier_reference')
    readonly_fields = ('received_date', 'is_expired', 'days_until_expiry')

    fieldsets = (
        ('Batch Information', {
            'fields': ('product', 'batch_number', 'warehouse', 'quantity')
        }),
        ('Dates', {
            'fields': ('manufacturing_date', 'expiry_date', 'received_date', 'days_until_expiry', 'is_expired')
        }),
        ('Reference', {
            'fields': ('supplier_reference',)
        }),
    )

    def expiry_status(self, obj):
        if not obj.expiry_date:
            return 'N/A'

        if obj.is_expired:
            return format_html('<span style="color: red; font-weight: bold;">EXPIRED</span>')

        days = obj.days_until_expiry
        if days <= 7:
            color = 'red'
        elif days <= 30:
            color = 'orange'
        else:
            color = 'green'

        return format_html(
            '<span style="color: {};">{} days</span>',
            color, days
        )

    expiry_status.short_description = 'Expiry Status'


@admin.register(StockAnalytics)
class StockAnalyticsAdmin(admin.ModelAdmin):
    list_display = (
        'date', 'product', 'warehouse', 'opening_stock', 'closing_stock',
        'total_sold', 'turnover_rate', 'days_of_stock'
    )
    list_filter = ('date', 'warehouse')
    search_fields = ('product__name', 'warehouse__code')
    readonly_fields = ('created_at',)
    date_hierarchy = 'date'

    fieldsets = (
        ('Identity', {
            'fields': ('product', 'warehouse', 'date')
        }),
        ('Quantity Metrics', {
            'fields': ('opening_stock', 'closing_stock', 'total_received', 'total_sold', 'total_adjusted')
        }),
        ('Financial Metrics', {
            'fields': ('total_purchase_value', 'total_sales_value', 'average_unit_cost')
        }),
        ('Velocity Metrics', {
            'fields': ('turnover_rate', 'days_of_stock')
        }),
        ('Metadata', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'contact_person', 'email', 'phone', 'rating', 'is_active')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'code', 'email', 'contact_person')
    readonly_fields = ('created_at',)

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'code', 'is_active', 'rating')
        }),
        ('Contact Details', {
            'fields': ('contact_person', 'email', 'phone', 'address')
        }),
        ('Business Terms', {
            'fields': ('payment_terms',)
        }),
        ('Metadata', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )


class PurchaseOrderItemInline(admin.TabularInline):
    model = PurchaseOrderItem
    extra = 1
    readonly_fields = ('quantity_pending', 'line_total')
    fields = ('product', 'quantity_ordered', 'quantity_received', 'quantity_pending', 'unit_price', 'line_total')


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = (
        'po_number', 'supplier', 'warehouse', 'status_display',
        'order_date', 'expected_delivery_date', 'total_amount_display'
    )
    list_filter = ('status', 'warehouse', 'order_date')
    search_fields = ('po_number', 'supplier__name')
    readonly_fields = ('created_at',)
    inlines = [PurchaseOrderItemInline]

    fieldsets = (
        ('PO Details', {
            'fields': ('po_number', 'supplier', 'warehouse', 'status')
        }),
        ('Dates', {
            'fields': ('order_date', 'expected_delivery_date', 'actual_delivery_date')
        }),
        ('Financial', {
            'fields': ('total_amount',)
        }),
        ('Additional Information', {
            'fields': ('notes',)
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at'),
            'classes': ('collapse',)
        }),
    )

    def status_display(self, obj):
        colors = {
            'DRAFT': 'gray',
            'SUBMITTED': 'blue',
            'APPROVED': 'green',
            'SENT': 'purple',
            'PARTIALLY_RECEIVED': 'orange',
            'RECEIVED': 'green',
            'CANCELLED': 'red'
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, obj.get_status_display()
        )

    status_display.short_description = 'Status'

    def total_amount_display(self, obj):
        return f"D{obj.total_amount:,.2f}"

    total_amount_display.short_description = 'Total Amount'


@admin.register(PurchaseOrderItem)
class PurchaseOrderItemAdmin(admin.ModelAdmin):
    list_display = (
        'purchase_order', 'product', 'quantity_ordered',
        'quantity_received', 'quantity_pending', 'unit_price',
        'line_total_display', 'received_status'
    )
    list_filter = ('purchase_order__status', 'purchase_order__warehouse')
    search_fields = ('product__name', 'purchase_order__po_number')
    readonly_fields = ('quantity_pending', 'line_total', 'is_fully_received')

    def line_total_display(self, obj):
        return f"D{obj.line_total:,.2f}"

    line_total_display.short_description = 'Line Total'

    def received_status(self, obj):
        if obj.is_fully_received:
            return format_html('<span style="color: green;">✓ Complete</span>')
        elif obj.quantity_received > 0:
            pct = (obj.quantity_received / obj.quantity_ordered * 100)
            return format_html(
                '<span style="color: orange;">{:.0f}% Received</span>',
                pct
            )
        else:
            return format_html('<span style="color: gray;">Pending</span>')

    received_status.short_description = 'Status'