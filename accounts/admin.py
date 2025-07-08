from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Address

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User
    list_display = ('username', 'email', 'is_seller', 'is_buyer')
    fieldsets = UserAdmin.fieldsets + (
        (None, {'fields': ('verify_doc', 'profile_pic', 'telephone', 'is_buyer', 'is_seller')}),
    )

admin.site.register(Address)