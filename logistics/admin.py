from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import (
    LogisticOffice, Warehouse, Driver, Vehicle,
    Shipment, ShipmentBox, BoxItem
)


@admin.register(LogisticOffice)
class LogisticOfficeAdmin(admin.ModelAdmin):
    list_display = ('name', 'location', 'shipment_count')
    search_fields = ('name', 'location')
    ordering = ('name',)

    def shipment_count(self, obj):
        count = obj.shipment_set.count()
        url = reverse('admin:logistics_shipment_changelist') + f'?logistic_office__id__exact={obj.id}'
        return format_html('<a href="{}">{} shipments</a>', url, count)
    shipment_count.short_description = 'Shipments'


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ('name', 'address', 'shipment_count', 'active_shipments')
    search_fields = ('name', 'address')
    ordering = ('name',)

    def shipment_count(self, obj):
        count = obj.shipment_set.count()
        url = reverse('admin:logistics_shipment_changelist') + f'?warehouse__id__exact={obj.id}'
        return format_html('<a href="{}">{} shipments</a>', url, count)
    shipment_count.short_description = 'Total Shipments'

    def active_shipments(self, obj):
        count = obj.shipment_set.exclude(status='shipped').count()
        if count > 0:
            return format_html('<span style="color: orange;">{}</span>', count)
        return count
    active_shipments.short_description = 'Active'


@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ('get_full_name', 'phone', 'license_number', 'vehicle_count', 'active_shipments', 'is_active')
    list_filter = ('user__is_active',)
    search_fields = ('user__first_name', 'user__last_name', 'phone', 'license_number')
    ordering = ('user__first_name', 'user__last_name')
    raw_id_fields = ('user',)

    def get_full_name(self, obj):
        return obj.user.get_full_name()
    get_full_name.short_description = 'Full Name'

    def vehicle_count(self, obj):
        count = obj.vehicle_set.count()
        url = reverse('admin:logistics_vehicle_changelist') + f'?driver__id__exact={obj.id}'
        return format_html('<a href="{}">{} vehicles</a>', url, count)
    vehicle_count.short_description = 'Vehicles'

    def active_shipments(self, obj):
        count = obj.shipment_set.exclude(status='shipped').count()
        if count > 0:
            return format_html('<span style="color: orange;">{}</span>', count)
        return count
    active_shipments.short_description = 'Active Shipments'

    def is_active(self, obj):
        return obj.user.is_active
    is_active.boolean = True
    is_active.short_description = 'Active'


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ('plate_number', 'model', 'driver_name', 'capacity_kg', 'active_shipments', 'status_indicator')
    list_filter = ('model',)
    search_fields = ('plate_number', 'model', 'driver__user__first_name', 'driver__user__last_name')
    ordering = ('plate_number',)
    raw_id_fields = ('driver',)

    def driver_name(self, obj):
        if obj.driver:
            url = reverse('admin:logistics_driver_change', args=[obj.driver.pk])
            return format_html('<a href="{}">{}</a>', url, obj.driver.user.get_full_name())
        return '-'
    driver_name.short_description = 'Driver'

    def active_shipments(self, obj):
        count = obj.shipment_set.exclude(status='shipped').count()
        if count > 0:
            url = reverse('admin:logistics_shipment_changelist') + f'?vehicle__id__exact={obj.id}&status__exact=in_transit'
            return format_html('<a href="{}" style="color: orange;">{}</a>', url, count)
        return count
    active_shipments.short_description = 'Active Shipments'

    def status_indicator(self, obj):
        active_count = obj.shipment_set.exclude(status='shipped').count()
        if active_count > 0:
            return format_html('<span style="color: red;">● In Use</span>')
        return format_html('<span style="color: green;">● Available</span>')
    status_indicator.short_description = 'Status'


class BoxItemInline(admin.TabularInline):
    model = BoxItem
    extra = 0
    raw_id_fields = ('order_item',)


class ShipmentBoxInline(admin.TabularInline):
    model = ShipmentBox
    extra = 0
    readonly_fields = ('label_preview',)

    def label_preview(self, obj):
        if obj.label:
            return format_html('<img src="{}" style="width: 50px; height: 50px;">', obj.label.url)
        return '-'
    label_preview.short_description = 'QR Label'


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'shipping_destination', 'driver_name', 'vehicle_info',
        'weight_kg', 'status_colored', 'shipment_type', 'created_at'
    )
    list_filter = ('status', 'shipment_type', 'material_type', 'created_at')
    search_fields = (
        'id', 'shipping_address__address', 'shipping_address__city',
        'driver__user__first_name', 'driver__user__last_name',
        'vehicle__plate_number'
    )
    ordering = ('-created_at',)
    raw_id_fields = ('shipping_address', 'warehouse', 'driver', 'vehicle', 'logistic_office', 'order')
    readonly_fields = ('created_at', 'boxes_count')
    inlines = [ShipmentBoxInline]

    fieldsets = (
        ('Basic Information', {
            'fields': ('shipping_address', 'order', 'weight_kg', 'size_cubic_meters', 'created_at')
        }),
        ('Shipment Details', {
            'fields': ('material_type', 'shipment_type', 'packing_type', 'container_type', 'status')
        }),
        ('Assignment', {
            'fields': ('warehouse', 'driver', 'vehicle', 'logistic_office')
        }),
        ('Schedule', {
            'fields': ('collect_time', 'estimated_dropoff_time')
        }),
        ('Statistics', {
            'fields': ('boxes_count',),
            'classes': ('collapse',)
        })
    )

    def shipping_destination(self, obj):
        return f"{obj.shipping_address.city}, {obj.shipping_address.region}"
    shipping_destination.short_description = 'Destination'

    def driver_name(self, obj):
        if obj.driver:
            return obj.driver.user.get_full_name()
        return '-'
    driver_name.short_description = 'Driver'

    def vehicle_info(self, obj):
        if obj.vehicle:
            return f"{obj.vehicle.plate_number} ({obj.vehicle.model})"
        return '-'
    vehicle_info.short_description = 'Vehicle'

    def status_colored(self, obj):
        colors = {
            'pending': '#ffc107',
            'in_transit': '#17a2b8',
            'shipped': '#28a745'
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="color: {}; font-weight: bold;">● {}</span>',
            color, obj.get_status_display()
        )
    status_colored.short_description = 'Status'

    def boxes_count(self, obj):
        count = obj.boxes.count()
        if count > 0:
            return f"{count} boxes"
        return "No boxes"
    boxes_count.short_description = 'Boxes'

    actions = ['mark_as_in_transit', 'mark_as_shipped']

    def mark_as_in_transit(self, request, queryset):
        updated = queryset.update(status='in_transit')
        self.message_user(request, f'{updated} shipments marked as in transit.')
    mark_as_in_transit.short_description = 'Mark selected shipments as in transit'

    def mark_as_shipped(self, request, queryset):
        updated = queryset.update(status='shipped')
        self.message_user(request, f'{updated} shipments marked as shipped.')
    mark_as_shipped.short_description = 'Mark selected shipments as shipped'


@admin.register(ShipmentBox)
class ShipmentBoxAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'shipment_id', 'box_number', 'weight_kg', 'items_count', 'label_status', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('shipment__id', 'box_number')
    ordering = ('shipment', 'box_number')
    raw_id_fields = ('shipment',)
    readonly_fields = ('label_preview', 'items_count')
    inlines = [BoxItemInline]

    def shipment_id(self, obj):
        url = reverse('admin:logistics_shipment_change', args=[obj.shipment.pk])
        return format_html('<a href="{}">#{}</a>', url, obj.shipment.id)
    shipment_id.short_description = 'Shipment'

    def items_count(self, obj):
        count = obj.items.count()
        return f"{count} items"
    items_count.short_description = 'Items'

    def label_status(self, obj):
        if obj.label:
            return format_html('<span style="color: green;">● Generated</span>')
        return format_html('<span style="color: red;">● Not Generated</span>')
    label_status.short_description = 'QR Label'

    def label_preview(self, obj):
        if obj.label:
            return format_html(
                '<img src="{}" style="width: 100px; height: 100px;"><br><a href="{}" target="_blank">View Full Size</a>',
                obj.label.url, obj.label.url
            )
        return 'No label generated'
    label_preview.short_description = 'QR Label Preview'

    actions = ['generate_labels']

    def generate_labels(self, request, queryset):
        count = 0
        for box in queryset:
            if not box.label:
                box.generate_qr_label()
                box.save()
                count += 1
        self.message_user(request, f'Generated QR labels for {count} boxes.')
    generate_labels.short_description = 'Generate QR labels for selected boxes'


@admin.register(BoxItem)
class BoxItemAdmin(admin.ModelAdmin):
    list_display = ('box_info', 'product_name', 'quantity', 'order_item_price')
    list_filter = ('box__shipment__created_at',)
    search_fields = ('box__shipment__id', 'order_item__product__name')
    ordering = ('box__shipment', 'box__box_number')
    raw_id_fields = ('box', 'order_item')

    def box_info(self, obj):
        return f"Shipment #{obj.box.shipment.id} - Box #{obj.box.box_number}"
    box_info.short_description = 'Box'

    def product_name(self, obj):
        return obj.order_item.product.name
    product_name.short_description = 'Product'

    def order_item_price(self, obj):
        return f"${obj.order_item.price}"
    order_item_price.short_description = 'Unit Price'