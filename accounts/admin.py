# accounts/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from .models import (
    User, Address, AdminLog, Device, OneTimeCode,
    Country, Currency, CurrencyExchangeRate
)


# ── User Role filter ────────────────────────────────────────────────────────────
class UserTypeFilter(admin.SimpleListFilter):
    title = _("User Role")
    parameter_name = "user_type"

    def lookups(self, request, model_admin):
        return [
            ("buyer", _("Buyers")),
            ("seller", _("Sellers")),
            ("finance", _("Finance")),
            ("logistic", _("Logistics")),
            ("driver", _("Drivers")),
            ("verified", _("Verified Users")),
        ]

    def queryset(self, request, qs):
        v = self.value()
        if v == "buyer":    return qs.filter(is_buyer=True)
        if v == "seller":   return qs.filter(is_seller=True)
        if v == "finance":  return qs.filter(is_finance=True)
        if v == "logistic": return qs.filter(is_logistic=True)
        if v == "driver":   return qs.filter(is_driver=True)
        if v == "verified": return qs.filter(is_verified=True)
        return qs


# ── Device inline on User ──────────────────────────────────────────────────────
class DeviceInline(admin.TabularInline):
    model = Device
    extra = 0
    fields = ("device_id", "browser", "os", "ip", "is_trusted", "first_seen", "last_seen")
    readonly_fields = ("device_id", "user_agent", "browser", "os", "ip", "first_seen", "last_seen")
    can_delete = True
    verbose_name = "Device"
    verbose_name_plural = "Devices"


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User
    list_display = (
        "username", "email", "telephone", "preferred_currency",
        "is_buyer", "is_seller", "is_finance", "is_logistic", "is_driver",
        "is_verified", "is_active", "is_staff", "is_superuser",
    )
    list_filter = (
        "is_active", "is_verified",
        "is_buyer", "is_seller", "is_finance", "is_logistic", "is_driver",
        "is_superuser", "is_staff",
        "preferred_currency",
        UserTypeFilter,
    )
    search_fields = ("username", "email", "telephone")
    ordering = ("username",)
    fieldsets = UserAdmin.fieldsets + (
        (_("User Info"), {"fields": ("telephone", "profile_pic", "verify_doc")}),
        (_("User Roles"), {"fields": (
            "is_buyer", "is_seller", "is_finance", "is_logistic", "is_driver", "is_verified"
        )}),
        (_("Preferences"), {"fields": ("preferred_currency",)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (_("User Info"), {"classes": ("wide",), "fields": ("telephone", "profile_pic", "verify_doc")}),
        (_("User Roles"), {"classes": ("wide",), "fields": (
            "is_buyer", "is_seller", "is_finance", "is_logistic", "is_driver", "is_verified"
        )}),
        (_("Preferences"), {"classes": ("wide",), "fields": ("preferred_currency",)}),
    )
    inlines = [DeviceInline]


# ── Country admin ──────────────────────────────────────────────────────────────
@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "code3", "phone_code", "currency", "is_active")
    list_filter = ("is_active", "currency")
    search_fields = ("name", "code", "code3", "phone_code")
    ordering = ("name",)
    list_editable = ("is_active",)

    fieldsets = (
        (_("Basic Information"), {
            "fields": ("name", "code", "code3", "numeric_code")
        }),
        (_("Contact & Currency"), {
            "fields": ("phone_code", "currency", "is_active")
        }),
    )


# ── Currency admin ─────────────────────────────────────────────────────────────
@admin.register(Currency)
class CurrencyAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "symbol", "decimal_places", "is_base_currency", "is_active", "updated_at")
    list_filter = ("is_base_currency", "is_active")
    search_fields = ("code", "name", "symbol")
    ordering = ("code",)
    list_editable = ("is_active",)

    fieldsets = (
        (_("Currency Details"), {
            "fields": ("code", "name", "symbol", "decimal_places")
        }),
        (_("Settings"), {
            "fields": ("is_base_currency", "is_active")
        }),
        (_("Timestamps"), {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )
    readonly_fields = ("created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.is_base_currency:
            # Show a message about base currency change
            self.message_user(request, f"{obj.code} is now set as the base currency.")


# ── Currency Exchange Rate admin ───────────────────────────────────────────────
@admin.register(CurrencyExchangeRate)
class CurrencyExchangeRateAdmin(admin.ModelAdmin):
    list_display = (
        "exchange_pair", "rate", "source", "valid_status", "valid_from", "valid_until", "updated_at"
    )
    list_filter = ("source", "from_currency", "to_currency", "valid_from", "updated_at")
    search_fields = ("from_currency__code", "to_currency__code", "source")
    ordering = ("-updated_at",)
    date_hierarchy = "updated_at"

    fieldsets = (
        (_("Exchange Pair"), {
            "fields": ("from_currency", "to_currency", "rate")
        }),
        (_("Validity"), {
            "fields": ("source", "valid_from", "valid_until")
        }),
        (_("Timestamps"), {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Exchange Pair")
    def exchange_pair(self, obj):
        return f"{obj.from_currency.code} → {obj.to_currency.code}"

    @admin.display(description="Status", boolean=True)
    def valid_status(self, obj):
        return obj.is_valid()

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change:
            self.message_user(
                request,
                f"Exchange rate created: 1 {obj.from_currency.code} = {obj.rate} {obj.to_currency.code}"
            )


# ── Address admin ──────────────────────────────────────────────────────────────
@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "address1", "address2", "country", "geo_code")
    list_filter = ("country",)
    search_fields = (
        "user__username", "user__email",
        "address1", "address2",
        "country__name", "country_name",
        "geo_code"
    )
    raw_id_fields = ("user",)

    fieldsets = (
        (_("User"), {
            "fields": ("user",)
        }),
        (_("Address Details"), {
            "fields": ("address1", "address2", "country", "geo_code")
        }),
        (_("Legacy"), {
            "fields": ("country_name",),
            "classes": ("collapse",),
            "description": "Deprecated field. Use 'country' instead."
        }),
    )


# ── AdminLog admin ─────────────────────────────────────────────────────────────
@admin.register(AdminLog)
class AdminLogAdmin(admin.ModelAdmin):
    list_display = (
        "id", "action_type", "related_model", "related_object_id",
        "created_by", "created_at", "reviewed", "is_flagged",
    )
    list_filter = ("action_type", "reviewed", "is_flagged", "created_at", "created_by", "reviewed_by", "flagged_by")
    search_fields = (
        "message", "notes", "related_model", "related_object_id",
        "created_by__username", "created_by__email",
        "reviewed_by__username", "reviewed_by__email",
        "flagged_by__username", "flagged_by__email",
    )
    raw_id_fields = ("created_by", "reviewed_by", "flagged_by")
    date_hierarchy = "created_at"
    list_select_related = ("created_by", "reviewed_by", "flagged_by")
    readonly_fields = ("created_at", "reviewed_at", "flagged_at")

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


# ── Device admin ───────────────────────────────────────────────────────────────
@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "short_fp", "browser", "os", "ip", "is_trusted", "first_seen", "last_seen")
    list_filter = ("is_trusted", "browser", "os", "first_seen", "last_seen")
    search_fields = ("user__username", "user__email", "device_id", "ip", "user_agent")
    raw_id_fields = ("user",)
    list_select_related = ("user",)
    readonly_fields = ("device_id", "user_agent", "first_seen", "last_seen")

    @admin.display(description="fingerprint")
    def short_fp(self, obj):
        return obj.device_id[:12] + "…" if obj.device_id else ""


# ── OneTimeCode admin ─────────────────────────────────────────────────────────
@admin.register(OneTimeCode)
class OneTimeCodeAdmin(admin.ModelAdmin):
    list_display = (
    "id", "user", "device", "purpose", "code", "is_active", "expires_at", "attempts", "consumed_at", "created_at")
    list_filter = ("purpose", "expires_at", "consumed_at", "created_at")
    search_fields = ("user__username", "user__email", "device__device_id", "code")
    raw_id_fields = ("user", "device")
    list_select_related = ("user", "device")
    readonly_fields = ("created_at",)

    @admin.display(boolean=True)
    def is_active(self, obj):
        from django.utils.timezone import now
        return obj.consumed_at is None and now() <= obj.expires_at