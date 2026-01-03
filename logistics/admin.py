from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import (
    LogisticOffice, Warehouse, Driver, Vehicle,
    Shipment, ShipmentBox, BoxItem
)


# ---------------------------------------------------------------------
# Helpers (safe related_name handling)
# ---------------------------------------------------------------------
def _rel(obj, preferred: str, fallback: str):
    """
    Return a related manager (works with custom related_name or default *_set).
    Example: _rel(vehicle, "shipments", "shipment_set")
    """
    return getattr(obj, preferred, None) or getattr(obj, fallback, None)


def _shipment_manager(obj):
    # Shipment FK related_name might be "shipments" or default "shipment_set"
    return _rel(obj, "shipments", "shipment_set")


def _vehicle_manager(obj):
    # Vehicle FK related_name might be "vehicles" or default "vehicle_set"
    return _rel(obj, "vehicles", "vehicle_set")


ACTIVE_STATUSES = ["pending", "in_transit", "shipped"]


# ---------------------------------------------------------------------
# LogisticOffice Admin
# ---------------------------------------------------------------------
@admin.register(LogisticOffice)
class LogisticOfficeAdmin(admin.ModelAdmin):
    list_display = ("name", "location", "shipment_count_link")
    search_fields = ("name", "location")
    ordering = ("name",)

    @admin.display(description="Shipments")
    def shipment_count_link(self, obj):
        mgr = _shipment_manager(obj)
        count = mgr.count() if mgr is not None else 0
        url = reverse("admin:logistics_shipment_changelist") + f"?logistic_office__id__exact={obj.id}"
        return format_html('<a href="{}">{} shipments</a>', url, count)


# ---------------------------------------------------------------------
# Warehouse Admin
# ---------------------------------------------------------------------
@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ("name", "address", "shipment_count_link", "active_shipments")
    search_fields = ("name", "address")
    ordering = ("name",)

    @admin.display(description="Total Shipments")
    def shipment_count_link(self, obj):
        mgr = _shipment_manager(obj)
        count = mgr.count() if mgr is not None else 0
        url = reverse("admin:logistics_shipment_changelist") + f"?warehouse__id__exact={obj.id}"
        return format_html('<a href="{}">{} shipments</a>', url, count)

    @admin.display(description="Active", ordering=None)
    def active_shipments(self, obj):
        mgr = _shipment_manager(obj)
        count = mgr.filter(status__in=ACTIVE_STATUSES).count() if mgr is not None else 0
        if count > 0:
            return format_html('<span style="color: orange; font-weight: 600;">{}</span>', count)
        return count


# ---------------------------------------------------------------------
# Driver Admin
# ---------------------------------------------------------------------
@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ("full_name", "phone", "license_number", "vehicle_count_link", "active_shipments", "is_active", "user_active")
    list_filter = ("is_active", "user__is_active")
    search_fields = ("user__first_name", "user__last_name", "user__username", "phone", "license_number")
    ordering = ("user__first_name", "user__last_name")
    raw_id_fields = ("user",)

    @admin.display(description="Full Name")
    def full_name(self, obj):
        return obj.user.get_full_name() or obj.user.username

    @admin.display(description="Vehicles")
    def vehicle_count_link(self, obj):
        mgr = _vehicle_manager(obj)
        count = mgr.count() if mgr is not None else 0
        url = reverse("admin:logistics_vehicle_changelist") + f"?driver__id__exact={obj.id}"
        return format_html('<a href="{}">{} vehicles</a>', url, count)

    @admin.display(description="Active Shipments")
    def active_shipments(self, obj):
        mgr = _shipment_manager(obj)
        count = mgr.filter(status__in=ACTIVE_STATUSES).count() if mgr is not None else 0
        if count > 0:
            return format_html('<span style="color: orange; font-weight: 600;">{}</span>', count)
        return count

    @admin.display(boolean=True, description="User Active")
    def user_active(self, obj):
        return bool(obj.user and obj.user.is_active)


# ---------------------------------------------------------------------
# Vehicle Admin
# ---------------------------------------------------------------------
@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ("plate_number", "model", "driver_link", "capacity_kg", "active_shipments_link", "status_indicator")
    list_filter = ("fuel_type", "model")
    search_fields = ("plate_number", "model", "driver__user__first_name", "driver__user__last_name", "driver__user__username")
    ordering = ("plate_number",)
    raw_id_fields = ("driver",)

    @admin.display(description="Driver")
    def driver_link(self, obj):
        if obj.driver_id:
            url = reverse("admin:logistics_driver_change", args=[obj.driver.pk])
            name = obj.driver.user.get_full_name() or obj.driver.user.username
            return format_html('<a href="{}">{}</a>', url, name)
        return "-"

    @admin.display(description="Active Shipments")
    def active_shipments_link(self, obj):
        mgr = _shipment_manager(obj)
        count = mgr.filter(status__in=ACTIVE_STATUSES).count() if mgr is not None else 0
        if count > 0:
            url = reverse("admin:logistics_shipment_changelist") + f"?vehicle__id__exact={obj.id}&status__in={','.join(ACTIVE_STATUSES)}"
            return format_html('<a href="{}" style="color: orange; font-weight: 700;">{}</a>', url, count)
        return count

    @admin.display(description="Status")
    def status_indicator(self, obj):
        mgr = _shipment_manager(obj)
        active_count = mgr.filter(status__in=ACTIVE_STATUSES).count() if mgr is not None else 0
        if active_count > 0:
            return format_html('<span style="color: #dc2626; font-weight: 700;">● In Use</span>')
        return format_html('<span style="color: #16a34a; font-weight: 700;">● Available</span>')


# ---------------------------------------------------------------------
# Inlines
# ---------------------------------------------------------------------
class BoxItemInline(admin.TabularInline):
    model = BoxItem
    extra = 0
    raw_id_fields = ("order_item",)


class ShipmentBoxInline(admin.TabularInline):
    model = ShipmentBox
    extra = 0
    readonly_fields = ("label_preview",)

    @admin.display(description="QR Label")
    def label_preview(self, obj):
        if getattr(obj, "label", None):
            return format_html('<img src="{}" style="width: 50px; height: 50px; object-fit: cover;">', obj.label.url)
        return "-"


# ---------------------------------------------------------------------
# Shipment Admin
# ---------------------------------------------------------------------
@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = (
        "id", "shipping_destination", "driver_name", "vehicle_info",
        "weight_kg", "status_colored", "shipment_type", "created_at"
    )
    list_filter = ("status", "shipment_type", "material_type", "created_at")
    search_fields = (
        "id",
        "shipping_address__address", "shipping_address__city",
        "driver__user__first_name", "driver__user__last_name", "driver__user__username",
        "vehicle__plate_number",
    )
    ordering = ("-created_at",)
    raw_id_fields = ("shipping_address", "warehouse", "driver", "vehicle", "logistic_office", "order")
    readonly_fields = ("created_at", "boxes_count", "verification_preview")
    inlines = [ShipmentBoxInline]

    fieldsets = (
        ("Basic Information", {
            "fields": ("shipping_address", "order", "weight_kg", "size_cubic_meters", "created_at")
        }),
        ("Shipment Details", {
            "fields": ("material_type", "shipment_type", "packing_type", "container_type", "status", "verification_photo")
        }),
        ("Assignment", {
            "fields": ("warehouse", "driver", "vehicle", "logistic_office")
        }),
        ("Schedule", {
            "fields": ("collect_time", "estimated_dropoff_time")
        }),
        ("Statistics", {
            "fields": ("boxes_count", "verification_preview"),
            "classes": ("collapse",)
        }),
    )

    @admin.display(description="Destination")
    def shipping_destination(self, obj):
        # Safe: region might be missing depending on your address model
        city = getattr(obj.shipping_address, "city", "") if obj.shipping_address else ""
        region = getattr(obj.shipping_address, "region", "") if obj.shipping_address else ""
        if city and region:
            return f"{city}, {region}"
        return city or region or "-"

    @admin.display(description="Driver")
    def driver_name(self, obj):
        if obj.driver_id:
            return obj.driver.user.get_full_name() or obj.driver.user.username
        return "-"

    @admin.display(description="Vehicle")
    def vehicle_info(self, obj):
        if obj.vehicle_id:
            return f"{obj.vehicle.plate_number} ({obj.vehicle.model})"
        return "-"

    @admin.display(description="Status")
    def status_colored(self, obj):
        colors = {
            "pending": "#f59e0b",
            "in_transit": "#0ea5e9",
            "shipped": "#22c55e",
            "delivered": "#16a34a",
            "cancelled": "#ef4444",
        }
        color = colors.get(obj.status, "#6b7280")
        label = obj.get_status_display() if hasattr(obj, "get_status_display") else obj.status
        return format_html('<span style="color:{}; font-weight:700;">● {}</span>', color, label)

    @admin.display(description="Boxes")
    def boxes_count(self, obj):
        mgr = getattr(obj, "boxes", None)
        count = mgr.count() if mgr is not None else 0
        return f"{count} boxes" if count > 0 else "No boxes"

    @admin.display(description="Verification Photo")
    def verification_preview(self, obj):
        if getattr(obj, "verification_photo", None):
            return format_html('<img src="{}" width="110" style="border-radius:10px; border:1px solid #e5e7eb;"/>', obj.verification_photo.url)
        return "-"

    actions = ["mark_as_in_transit", "mark_as_shipped"]

    @admin.action(description="Mark selected shipments as in transit")
    def mark_as_in_transit(self, request, queryset):
        updated = queryset.update(status="in_transit")
        self.message_user(request, f"{updated} shipments marked as in transit.")

    @admin.action(description="Mark selected shipments as shipped")
    def mark_as_shipped(self, request, queryset):
        updated = queryset.update(status="shipped")
        self.message_user(request, f"{updated} shipments marked as shipped.")


# ---------------------------------------------------------------------
# ShipmentBox Admin
# ---------------------------------------------------------------------
@admin.register(ShipmentBox)
class ShipmentBoxAdmin(admin.ModelAdmin):
    list_display = ("__str__", "shipment_link", "box_number", "weight_kg", "items_count", "label_status", "created_at")
    list_filter = ("created_at",)
    search_fields = ("shipment__id", "box_number")
    ordering = ("shipment", "box_number")
    raw_id_fields = ("shipment",)
    readonly_fields = ("label_preview", "items_count")
    inlines = [BoxItemInline]

    @admin.display(description="Shipment")
    def shipment_link(self, obj):
        url = reverse("admin:logistics_shipment_change", args=[obj.shipment.pk])
        return format_html('<a href="{}">#{} </a>', url, obj.shipment.id)

    @admin.display(description="Items")
    def items_count(self, obj):
        mgr = getattr(obj, "items", None)
        count = mgr.count() if mgr is not None else 0
        return f"{count} items"

    @admin.display(description="QR Label")
    def label_status(self, obj):
        if getattr(obj, "label", None):
            return format_html('<span style="color:#16a34a; font-weight:700;">● Generated</span>')
        return format_html('<span style="color:#dc2626; font-weight:700;">● Not Generated</span>')

    @admin.display(description="QR Label Preview")
    def label_preview(self, obj):
        if getattr(obj, "label", None):
            return format_html(
                '<img src="{}" style="width: 110px; height: 110px; object-fit: cover; border-radius: 10px; border: 1px solid #e5e7eb;"><br>'
                '<a href="{}" target="_blank">View Full Size</a>',
                obj.label.url, obj.label.url
            )
        return "No label generated"

    actions = ["generate_labels"]

    @admin.action(description="Generate QR labels for selected boxes")
    def generate_labels(self, request, queryset):
        count = 0
        for box in queryset:
            if not getattr(box, "label", None):
                box.generate_qr_label()
                box.save()
                count += 1
        self.message_user(request, f"Generated QR labels for {count} boxes.")


# ---------------------------------------------------------------------
# BoxItem Admin
# ---------------------------------------------------------------------
@admin.register(BoxItem)
class BoxItemAdmin(admin.ModelAdmin):
    list_display = ("box_info", "product_name", "quantity", "order_item_price")
    list_filter = ("box__shipment__created_at",)
    search_fields = ("box__shipment__id", "order_item__product__name")
    ordering = ("box__shipment", "box__box_number")
    raw_id_fields = ("box", "order_item")

    @admin.display(description="Box")
    def box_info(self, obj):
        return f"Shipment #{obj.box.shipment.id} - Box #{obj.box.box_number}"

    @admin.display(description="Product")
    def product_name(self, obj):
        return obj.order_item.product.name

    @admin.display(description="Unit Price")
    def order_item_price(self, obj):
        return f"${obj.order_item.price}"
