from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Address, AdminLog


class UserTypeFilter(admin.SimpleListFilter):
    title = 'User Role'
    parameter_name = 'user_type'

    def lookups(self, request, model_admin):
        return [
            ('buyer', 'Buyers'),
            ('seller', 'Sellers'),
            ('finance', 'Finance'),
            ('logistic', 'Logistics'),
            ('driver', 'Drivers'),
            ('verified', 'Verified Users'),
        ]

    def queryset(self, request, queryset):
        value = self.value()
        if value == 'buyer':
            return queryset.filter(is_buyer=True)
        elif value == 'seller':
            return queryset.filter(is_seller=True)
        elif value == 'finance':
            return queryset.filter(is_finance=True)
        elif value == 'logistic':
            return queryset.filter(is_logistic=True)
        elif value == 'driver':
            return queryset.filter(is_driver=True)
        elif value == 'verified':
            return queryset.filter(is_verified=True)
        return queryset


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User
    list_display = (
        'username', 'email', 'is_buyer', 'is_seller',
        'is_finance', 'is_logistic', 'is_driver', 'is_verified'
    )
    list_filter = (
        'is_active', 'is_verified', UserTypeFilter, 'is_superuser', 'is_staff'
    )

    fieldsets = UserAdmin.fieldsets + (
        ('User Info', {
            'fields': ('telephone', 'profile_pic', 'verify_doc')
        }),
        ('User Roles', {
            'fields': (
                'is_buyer', 'is_seller', 'is_finance',
                'is_logistic', 'is_driver', 'is_verified'
            )
        }),
    )

    search_fields = ('username', 'email', 'telephone')
    ordering = ('username',)


admin.site.register(Address)
admin.site.register(AdminLog)
