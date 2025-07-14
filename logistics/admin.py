from django.contrib import admin
from .models import (
    LogisticOffice, Warehouse, Driver, Vehicle, Shipment
)

@admin.register(LogisticOffice)
class LogisticOfficeAdmin(admin.ModelAdmin):
    list_display = ('name', 'location')
    search_fields = ('name', 'location')

@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ('name', 'address')
    search_fields = ('name',)

@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ('user', 'phone', 'license_number')
    search_fields = ('user__username', 'phone', 'license_number')

@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ('plate_number', 'model', 'driver', 'capacity_kg')
    search_fields = ('plate_number', 'model')
    list_filter = ('driver',)

@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'order', 'status', 'driver', 'vehicle',
        'collect_time', 'estimated_dropoff_time',
        'material_type', 'shipment_type', 'created_at'
    )
    list_filter = ('status', 'shipment_type', 'material_type', 'created_at')
    search_fields = ('order__id', 'driver__user__username', 'vehicle__plate_number')
    autocomplete_fields = ('order', 'shipping_address', 'driver', 'vehicle', 'logistic_office', 'warehouse')
    readonly_fields = ('created_at',)
