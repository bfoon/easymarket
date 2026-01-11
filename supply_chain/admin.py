# supply_chain/admin.py

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.db.models import Count, Q
from django.utils import timezone

from .models import (
    WarehouseLinkage,
    StoreToLogisticsTransfer,
    TransferItem,
    FulfillmentQueue,
    CountryShippingConfig,
    ShippingCompany,
    ShippingCompanyCountry,
    B2BShipment,
    ShipmentTracking
)


# ==================== INLINES ====================

class TransferItemInline(admin.TabularInline):
    model = TransferItem
    extra = 0
    fields = ('product', 'quantity', 'order_item', 'stock_reservation')
    readonly_fields = ('product', 'quantity', 'order_item')
    can_delete = False


class ShippingCompanyCountryInline(admin.TabularInline):
    model = ShippingCompanyCountry
    extra = 0
    fields = (
        'country', 'service_level', 'base_rate', 'per_kg_rate',
        'estimated_days', 'priority', 'is_active'
    )
    ordering = ['country', 'priority']


class ShipmentTrackingInline(admin.TabularInline):
    model = ShipmentTracking
    extra = 0
    fields = ('timestamp', 'status', 'location', 'description')
    readonly_fields = ('timestamp', 'created_at')
    ordering = ['-timestamp']


# ==================== WAREHOUSE LINKAGE ====================

@admin.register(WarehouseLinkage)
class WarehouseLinkageAdmin(admin.ModelAdmin):
    list_display = (
        'linkage_route',
        'status_badge',
        'priority_badge',
        'distance_km',
        'estimated_transfer_time_minutes',
        'max_daily_transfers',
        'created_at'
    )
    list_filter = (
        'is_active',
        'is_primary',
        'store_warehouse',
        'logistics_warehouse',
        'priority'
    )
    search_fields = (
        'store_warehouse__name',
        'store_warehouse__code',
        'logistics_warehouse__name',
        'notes'
    )
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Warehouse Route', {
            'fields': ('store_warehouse', 'logistics_warehouse')
        }),
        ('Configuration', {
            'fields': ('is_primary', 'is_active', 'priority')
        }),
        ('Logistics Details', {
            'fields': (
                'distance_km',
                'estimated_transfer_time_minutes',
                'max_daily_transfers'
            )
        }),
        ('Operating Hours', {
            'fields': ('operating_hours_start', 'operating_hours_end')
        }),
        ('Additional Information', {
            'fields': ('notes',),
            'classes': ('collapse',)
        })
    )

    def linkage_route(self, obj):
        return format_html(
            '<strong>{}</strong> → <strong>{}</strong>',
            obj.store_warehouse.code if hasattr(obj.store_warehouse, 'code') else obj.store_warehouse.name,
            obj.logistics_warehouse.name
        )

    linkage_route.short_description = 'Route'

    def status_badge(self, obj):
        if obj.is_active:
            return format_html(
                '<span style="background: #d1fae5; color: #065f46; padding: 4px 12px; '
                'border-radius: 12px; font-weight: 600; font-size: 11px;">✓ ACTIVE</span>'
            )
        return format_html(
            '<span style="background: #fee2e2; color: #991b1b; padding: 4px 12px; '
            'border-radius: 12px; font-weight: 600; font-size: 11px;">✗ INACTIVE</span>'
        )

    status_badge.short_description = 'Status'

    def priority_badge(self, obj):
        colors = {
            1: ('#fef3c7', '#92400e'),  # High priority - yellow
            2: ('#dbeafe', '#1e40af'),  # Medium - blue
        }
        bg, text = colors.get(obj.priority, ('#f3f4f6', '#6b7280'))

        return format_html(
            '<span style="background: {}; color: {}; padding: 4px 12px; '
            'border-radius: 12px; font-weight: 600; font-size: 11px;">★ P{}</span>',
            bg, text, obj.priority
        )

    priority_badge.short_description = 'Priority'


# ==================== STORE TO LOGISTICS TRANSFER ====================

@admin.register(StoreToLogisticsTransfer)
class StoreToLogisticsTransferAdmin(admin.ModelAdmin):
    list_display = (
        'transfer_number',
        'status_badge',
        'route_display',
        'order_link',
        'requested_at',
        'duration_display',
    )
    list_filter = (
        'status',
        'store_warehouse',
        'logistics_warehouse',
        'requested_at'
    )
    search_fields = (
        'transfer_number',
        'order__id',
        'b2b_order__id'
    )
    date_hierarchy = 'requested_at'
    inlines = [TransferItemInline]

    readonly_fields = (
        'id',
        'transfer_number',
        'requested_at',
        'actual_duration_minutes'
    )

    fieldsets = (
        ('Transfer Information', {
            'fields': ('id', 'transfer_number', 'status')
        }),
        ('Route', {
            'fields': ('store_warehouse', 'logistics_warehouse')
        }),
        ('Related Orders', {
            'fields': ('order', 'b2b_order'),
            'description': 'Link to either a B2C order OR a B2B order (not both)'
        }),
        ('Timeline', {
            'fields': (
                'requested_at', 'requested_by',
                'actual_duration_minutes',
            )
        }),
        ('Notes', {
            'fields': ('notes',),
            'classes': ('collapse',)
        })
    )

    def route_display(self, obj):
        return format_html(
            '<span style="color: #6b7280;">{}</span> → <span style="color: #1f2937;">{}</span>',
            obj.store_warehouse.name if hasattr(obj.store_warehouse, 'name') else str(obj.store_warehouse),
            obj.logistics_warehouse.name
        )

    route_display.short_description = 'Route'

    def status_badge(self, obj):
        colors = {
            'PENDING': ('#fef3c7', '#92400e'),
            'PICKED_UP': ('#dbeafe', '#1e40af'),
            'RECEIVED': ('#d1fae5', '#065f46'),
            'CANCELLED': ('#fee2e2', '#991b1b')
        }
        bg, text = colors.get(obj.status, ('#f3f4f6', '#6b7280'))

        return format_html(
            '<span style="background: {}; color: {}; padding: 4px 12px; '
            'border-radius: 12px; font-weight: 600; font-size: 11px;">{}</span>',
            bg, text, obj.get_status_display()
        )

    status_badge.short_description = 'Status'

    def order_link(self, obj):
        if obj.order:
            url = reverse('admin:orders_order_change', args=[obj.order.id])
            return format_html(
                '<a href="{}" style="color: #667eea; text-decoration: none; font-weight: 600;">B2C #{}</a>',
                url, obj.order.id
            )
        elif obj.b2b_order:
            url = reverse('admin:stores_b2border_change', args=[obj.b2b_order.id])
            return format_html(
                '<a href="{}" style="color: #8b5cf6; text-decoration: none; font-weight: 600;">B2B #{}</a>',
                url, obj.b2b_order.id
            )
        return '-'

    order_link.short_description = 'Order'

    def duration_display(self, obj):
        if obj.actual_duration_minutes:
            minutes = obj.actual_duration_minutes
            if minutes <= 60:
                color = '#10b981'  # Green
            elif minutes <= 120:
                color = '#f59e0b'  # Yellow
            else:
                color = '#ef4444'  # Red

            return format_html(
                '<span style="color: {}; font-weight: 600;">{} min</span>',
                color, minutes
            )
        return '-'

    duration_display.short_description = 'Duration'


# ==================== FULFILLMENT QUEUE ====================

@admin.register(FulfillmentQueue)
class FulfillmentQueueAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'status_badge',
        'priority_badge',
        'order_link',
        'logistics_warehouse',
        'queued_at',
        'total_time_display'
    )
    list_filter = (
        'status',
        'priority',
        'logistics_warehouse',
        'queued_at'
    )
    search_fields = (
        'order__id',
        'b2b_order__id'
    )
    date_hierarchy = 'queued_at'

    readonly_fields = (
        'id',
        'queued_at',
        'actual_pick_time_minutes',
        'actual_pack_time_minutes'
    )

    fieldsets = (
        ('Queue Information', {
            'fields': ('id', 'priority', 'status')
        }),
        ('Related Items', {
            'fields': ('order', 'b2b_order', 'logistics_warehouse', 'transfer')
        }),
        ('Picking', {
            'fields': (
                'picking_started_at', 'picking_completed_at',
                'picked_by', 'estimated_pick_time_minutes',
                'actual_pick_time_minutes'
            )
        }),
        ('Packing', {
            'fields': (
                'packing_started_at', 'packing_completed_at',
                'packed_by', 'estimated_pack_time_minutes',
                'actual_pack_time_minutes'
            )
        }),
        ('Timeline', {
            'fields': ('queued_at',)
        }),
        ('Notes', {
            'fields': ('notes',),
            'classes': ('collapse',)
        })
    )

    def status_badge(self, obj):
        colors = {
            'QUEUED': ('#fef3c7', '#92400e'),
            'PICKING': ('#dbeafe', '#1e40af'),
            'PACKING': ('#e0e7ff', '#3730a3'),
            'READY': ('#d1fae5', '#065f46'),
            'SHIPPED': ('#a7f3d0', '#047857'),
            'CANCELLED': ('#fee2e2', '#991b1b')
        }
        bg, text = colors.get(obj.status, ('#f3f4f6', '#6b7280'))

        return format_html(
            '<span style="background: {}; color: {}; padding: 4px 12px; '
            'border-radius: 12px; font-weight: 600; font-size: 11px;">{}</span>',
            bg, text, obj.get_status_display()
        )

    status_badge.short_description = 'Status'

    def priority_badge(self, obj):
        colors = {
            'URGENT': ('#fee2e2', '#991b1b'),
            'HIGH': ('#fef3c7', '#92400e'),
            'NORMAL': ('#dbeafe', '#1e40af'),
            'LOW': ('#f3f4f6', '#6b7280')
        }
        bg, text = colors.get(obj.priority, ('#f3f4f6', '#6b7280'))

        return format_html(
            '<span style="background: {}; color: {}; padding: 4px 12px; '
            'border-radius: 12px; font-weight: 600; font-size: 11px;">{}</span>',
            bg, text, obj.get_priority_display()
        )

    priority_badge.short_description = 'Priority'

    def order_link(self, obj):
        if obj.order:
            url = reverse('admin:orders_order_change', args=[obj.order.id])
            return format_html('<a href="{}" style="color: #667eea;">Order #{}</a>', url, obj.order.id)
        elif obj.b2b_order:
            url = reverse('admin:stores_b2border_change', args=[obj.b2b_order.id])
            return format_html('<a href="{}" style="color: #8b5cf6;">B2B #{}</a>', url, obj.b2b_order.id)
        return '-'

    order_link.short_description = 'Order'

    def total_time_display(self, obj):
        total = 0
        if obj.actual_pick_time_minutes:
            total += obj.actual_pick_time_minutes
        if obj.actual_pack_time_minutes:
            total += obj.actual_pack_time_minutes

        if total > 0:
            return format_html('<strong>{} min</strong>', total)
        return '-'

    total_time_display.short_description = 'Total Time'


# ==================== COUNTRY SHIPPING CONFIG ====================

@admin.register(CountryShippingConfig)
class CountryShippingConfigAdmin(admin.ModelAdmin):
    list_display = (
        'country_flag',
        'country_name',
        'country_code',
        'status_badge',
        'customs_badge',
        'estimated_delivery_days',
        'companies_count',
        'created_at'
    )
    list_filter = (
        'is_active',
        'requires_customs',
        'estimated_delivery_days'
    )
    search_fields = (
        'country_name',
        'country_code',
        'notes'
    )
    date_hierarchy = 'created_at'
    inlines = [ShippingCompanyCountryInline]

    fieldsets = (
        ('Country Information', {
            'fields': ('country_code', 'country_name', 'is_active')
        }),
        ('Shipping Configuration', {
            'fields': (
                'requires_customs',
                'estimated_delivery_days',
                'max_package_weight_kg'
            )
        }),
        ('Restrictions', {
            'fields': ('restricted_items',)
        }),
        ('Additional Information', {
            'fields': ('notes',),
            'classes': ('collapse',)
        })
    )

    def country_flag(self, obj):
        # Using country code to display flag emoji (simplified)
        return format_html('<span style="font-size: 1.5rem;">🌍</span>')

    country_flag.short_description = ''

    def status_badge(self, obj):
        if obj.is_active:
            return format_html(
                '<span style="background: #d1fae5; color: #065f46; padding: 4px 12px; '
                'border-radius: 12px; font-weight: 600; font-size: 11px;">✓ ACTIVE</span>'
            )
        return format_html(
            '<span style="background: #fee2e2; color: #991b1b; padding: 4px 12px; '
            'border-radius: 12px; font-weight: 600; font-size: 11px;">✗ INACTIVE</span>'
        )

    status_badge.short_description = 'Status'

    def customs_badge(self, obj):
        if obj.requires_customs:
            return format_html(
                '<span style="background: #fef3c7; color: #92400e; padding: 4px 12px; '
                'border-radius: 12px; font-weight: 600; font-size: 11px;">📋 YES</span>'
            )
        return format_html(
            '<span style="background: #f3f4f6; color: #6b7280; padding: 4px 12px; '
            'border-radius: 12px; font-weight: 600; font-size: 11px;">- NO</span>'
        )

    customs_badge.short_description = 'Customs'

    def companies_count(self, obj):
        count = obj.shipping_companies.count()
        return format_html('<strong>{}</strong> companies', count)

    companies_count.short_description = 'Shipping Companies'


# ==================== SHIPPING COMPANY ====================

@admin.register(ShippingCompany)
class ShippingCompanyAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'code',
        'status_badge',
        'features_display',
        'countries_count',
        'created_at'
    )
    list_filter = (
        'is_active',
        'has_api_integration',
        'supports_tracking',
        'supports_insurance',
        'supports_cod'
    )
    search_fields = (
        'name',
        'code',
        'contact_email',
        'notes'
    )
    date_hierarchy = 'created_at'
    inlines = [ShippingCompanyCountryInline]

    fieldsets = (
        ('Company Information', {
            'fields': ('name', 'code', 'logo', 'is_active')
        }),
        ('Contact Details', {
            'fields': ('contact_email', 'contact_phone', 'website')
        }),
        ('API Integration', {
            'fields': ('has_api_integration', 'api_endpoint', 'api_key'),
            'classes': ('collapse',)
        }),
        ('Capabilities', {
            'fields': (
                'supports_tracking',
                'supports_insurance',
                'supports_cod',
                'supported_modes'
            )
        }),
        ('Additional Information', {
            'fields': ('notes',),
            'classes': ('collapse',)
        })
    )

    def status_badge(self, obj):
        if obj.is_active:
            return format_html(
                '<span style="background: #d1fae5; color: #065f46; padding: 4px 12px; '
                'border-radius: 12px; font-weight: 600; font-size: 11px;">✓ ACTIVE</span>'
            )
        return format_html(
            '<span style="background: #fee2e2; color: #991b1b; padding: 4px 12px; '
            'border-radius: 12px; font-weight: 600; font-size: 11px;">✗ INACTIVE</span>'
        )

    status_badge.short_description = 'Status'

    def features_display(self, obj):
        features = []
        if obj.supports_tracking:
            features.append(
                '<span style="background: #dbeafe; color: #1e40af; padding: 2px 8px; border-radius: 8px; font-size: 10px;">📍 Track</span>')
        if obj.supports_insurance:
            features.append(
                '<span style="background: #d1fae5; color: #065f46; padding: 2px 8px; border-radius: 8px; font-size: 10px;">🛡️ Ins</span>')
        if obj.supports_cod:
            features.append(
                '<span style="background: #fef3c7; color: #92400e; padding: 2px 8px; border-radius: 8px; font-size: 10px;">💵 COD</span>')
        if obj.has_api_integration:
            features.append(
                '<span style="background: #e0e7ff; color: #3730a3; padding: 2px 8px; border-radius: 8px; font-size: 10px;">🔌 API</span>')

        return format_html(' '.join(features) if features else '-')

    features_display.short_description = 'Features'

    def countries_count(self, obj):
        count = obj.countries.count()
        return format_html('<strong>{}</strong> countries', count)

    countries_count.short_description = 'Service Countries'


# ==================== SHIPPING COMPANY COUNTRY ====================

@admin.register(ShippingCompanyCountry)
class ShippingCompanyCountryAdmin(admin.ModelAdmin):
    list_display = (
        'shipping_company',
        'country',
        'service_level_badge',
        'rate_display',
        'estimated_days',
        'priority_badge',
        'status_badge'
    )
    list_filter = (
        'service_level',
        'is_active',
        'shipping_company',
        'country'
    )
    search_fields = (
        'shipping_company__name',
        'country__country_name'
    )

    fieldsets = (
        ('Configuration', {
            'fields': ('shipping_company', 'country', 'is_active')
        }),
        ('Service Details', {
            'fields': ('service_level', 'estimated_days', 'priority')
        }),
        ('Pricing', {
            'fields': ('base_rate', 'per_kg_rate')
        }),
        ('Weight Constraints', {
            'fields': ('min_weight_kg', 'max_weight_kg')
        })
    )

    def service_level_badge(self, obj):
        colors = {
            'STANDARD': ('#dbeafe', '#1e40af'),
            'EXPRESS': ('#fef3c7', '#92400e'),
            'ECONOMY': ('#e0e7ff', '#3730a3')
        }
        bg, text = colors.get(obj.service_level, ('#f3f4f6', '#6b7280'))

        return format_html(
            '<span style="background: {}; color: {}; padding: 4px 12px; '
            'border-radius: 12px; font-weight: 600; font-size: 11px;">{}</span>',
            bg, text, obj.get_service_level_display()
        )

    service_level_badge.short_description = 'Service Level'

    def rate_display(self, obj):
        return format_html(
            '<strong>${}</strong> + <strong>${}/kg</strong>',
            obj.base_rate, obj.per_kg_rate
        )

    rate_display.short_description = 'Rate'

    def priority_badge(self, obj):
        return format_html(
            '<span style="background: #f3f4f6; color: #374151; padding: 4px 10px; '
            'border-radius: 10px; font-weight: 600; font-size: 11px;">P{}</span>',
            obj.priority
        )

    priority_badge.short_description = 'Priority'

    def status_badge(self, obj):
        if obj.is_active:
            return format_html(
                '<span style="background: #d1fae5; color: #065f46; padding: 4px 12px; '
                'border-radius: 12px; font-weight: 600; font-size: 11px;">✓</span>'
            )
        return format_html(
            '<span style="background: #fee2e2; color: #991b1b; padding: 4px 12px; '
            'border-radius: 12px; font-weight: 600; font-size: 11px;">✗</span>'
        )

    status_badge.short_description = 'Active'


# ==================== B2B SHIPMENT ====================

@admin.register(B2BShipment)
class B2BShipmentAdmin(admin.ModelAdmin):
    list_display = (
        'shipment_number',
        'status_badge',
        'b2b_order_link',
        'shipping_company',
        'country',
        'total_weight_kg',
        'total_cost',
        'created_at'
    )
    list_filter = (
        'status',
        'shipping_company',
        'country',
        'created_at'
    )
    search_fields = (
        'shipment_number',
        'tracking_number',
        'b2b_order__id'
    )
    date_hierarchy = 'created_at'
    inlines = [ShipmentTrackingInline]

    readonly_fields = (
        'shipment_number',
        'total_cost',
        'created_at'
    )

    fieldsets = (
        ('Shipment Information', {
            'fields': (
                'shipment_number',
                'b2b_order',
                'status'
            )
        }),
        ('Shipping Details', {
            'fields': (
                'shipping_company',
                'company_config',
                'country'
            )
        }),
        ('Package Details', {
            'fields': (
                'total_weight_kg',
                'package_count',
                'dimensions_cm'
            )
        }),
        ('Costs', {
            'fields': (
                'shipping_cost',
                'insurance_cost',
                'customs_fee',
                'total_cost'
            )
        }),
        ('Tracking', {
            'fields': (
                'tracking_number',
                'carrier_tracking_url'
            )
        }),
        ('Timeline', {
            'fields': (
                'created_at',
                'shipped_at',
                'estimated_delivery',
                'delivered_at'
            )
        }),
        ('Documents', {
            'fields': (
                'commercial_invoice',
                'packing_list',
                'customs_declaration'
            ),
            'classes': ('collapse',)
        }),
        ('Notes', {
            'fields': ('notes', 'customs_notes'),
            'classes': ('collapse',)
        })
    )

    def status_badge(self, obj):
        colors = {
            'PENDING': ('#fef3c7', '#92400e'),
            'PROCESSING': ('#dbeafe', '#1e40af'),
            'SHIPPED': ('#e0e7ff', '#3730a3'),
            'IN_TRANSIT': ('#ddd6fe', '#5b21b6'),
            'CUSTOMS': ('#fed7aa', '#9a3412'),
            'OUT_FOR_DELIVERY': ('#a7f3d0', '#047857'),
            'DELIVERED': ('#d1fae5', '#065f46'),
            'FAILED': ('#fee2e2', '#991b1b'),
            'RETURNED': ('#fee2e2', '#991b1b')
        }
        bg, text = colors.get(obj.status, ('#f3f4f6', '#6b7280'))

        return format_html(
            '<span style="background: {}; color: {}; padding: 4px 12px; '
            'border-radius: 12px; font-weight: 600; font-size: 11px;">{}</span>',
            bg, text, obj.get_status_display()
        )

    status_badge.short_description = 'Status'

    def b2b_order_link(self, obj):
        url = reverse('admin:stores_b2border_change', args=[obj.b2b_order.id])
        return format_html(
            '<a href="{}" style="color: #8b5cf6; text-decoration: none; font-weight: 600;">B2B #{}</a>',
            url, obj.b2b_order.id
        )

    b2b_order_link.short_description = 'B2B Order'


# ==================== SHIPMENT TRACKING ====================

@admin.register(ShipmentTracking)
class ShipmentTrackingAdmin(admin.ModelAdmin):
    list_display = (
        'shipment_number',
        'status',
        'location',
        'timestamp',
        'created_at'
    )
    list_filter = (
        'status',
        'timestamp'
    )
    search_fields = (
        'shipment__shipment_number',
        'status',
        'location',
        'description'
    )
    date_hierarchy = 'timestamp'

    readonly_fields = ('created_at',)

    fieldsets = (
        ('Tracking Information', {
            'fields': ('shipment', 'status', 'location')
        }),
        ('Details', {
            'fields': ('description', 'timestamp')
        }),
        ('Metadata', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        })
    )

    def shipment_number(self, obj):
        return obj.shipment.shipment_number

    shipment_number.short_description = 'Shipment'