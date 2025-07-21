from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Address

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User
    list_display = ('username', 'email', 'is_seller', 'is_buyer', 'is_finance', 'is_logistic', 'is_driver', 'is_verified')
    fieldsets = UserAdmin.fieldsets + (
        (None, {'fields': ('verify_doc', 'profile_pic', 'telephone', 'is_buyer', 'is_seller','is_finance', 'is_logistic', 'is_driver', 'is_verified')}),
    )

admin.site.register(Address)