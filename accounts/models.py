from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

class User(AbstractUser):
    verify_doc = models.FileField(upload_to='company/', blank=True, null=True)
    profile_pic = models.ImageField(upload_to='profile/', blank=True, null=True)
    telephone = models.CharField(max_length=200, blank=True, null=True)
    is_buyer = models.BooleanField(default=False)
    is_seller = models.BooleanField(default=False)
    is_logistic = models.BooleanField(default=False)
    is_finance = models.BooleanField(default=False)
    is_driver = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)

    class Meta:
        swappable = 'AUTH_USER_MODEL'

    def get_full_name(self):
        full_name = f"{self.first_name} {self.last_name}".strip()
        return full_name if full_name else self.username

    def get_store_name(self):
        return self.owned_stores.first().name if self.owned_stores.exists() else "Unknown"

    def __str__(self):
        return self.get_full_name() or self.username


class Address(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    country = models.CharField(max_length=200, blank=True, null=True)
    address1 = models.TextField(blank=True, null=True)
    address2 = models.TextField(blank=True, null=True)

    # New geo code field (e.g., a unique code on the compound wall)
    geo_code = models.CharField(max_length=100, blank=True, null=True)

    def full_address(self):
        parts = [self.address1, self.address2, self.country]
        return ', '.join(filter(None, parts))

    def __str__(self):
        return self.user.get_full_name() or self.username


class AdminLog(models.Model):
    ACTION_TYPES = [
        ('product_add', 'Product Added'),
        ('product_edit', 'Product Updated'),
        ('product_delete', 'Product Deleted'),
        ('variant_update', 'Product Variant Updated'),
        ('stock_update', 'Stock Updated'),
        ('bad_rating', 'Bad Product Rating'),
        ('store_edit', 'Store Settings Updated'),
        ('complaint', 'Customer Complaint'),
    ]

    action_type = models.CharField(max_length=50, choices=ACTION_TYPES)
    related_object_id = models.CharField(max_length=100, null=True, blank=True)
    related_model = models.CharField(max_length=100, null=True, blank=True)
    message = models.TextField()
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    reviewed = models.BooleanField(default=False)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='reviewed_logs'
    )
    is_flagged = models.BooleanField(default=False)
    flagged_at = models.DateTimeField(null=True, blank=True)
    flagged_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='flagged_logs'
    )
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.get_action_type_display()} @ {self.created_at.strftime('%Y-%m-%d %H:%M')}"

    def get_icon(self):
        icon_map = {
            'product_add': 'plus',
            'product_delete': 'trash',
            'product_edit': 'edit',
            'bad_rating': 'exclamation-triangle',
            'store_edit': 'store',
            'complaint': 'comment-alt',
            'variant_update': 'sliders-h',
            'stock_update': 'boxes',
        }
        return icon_map.get(self.action_type, 'info-circle')

    def get_status(self):
        status_map = {
            'product_add': 'success',
            'product_delete': 'danger',
            'product_edit': 'info',
            'bad_rating': 'warning',
            'store_edit': 'info',
            'complaint': 'warning',
            'variant_update': 'info',
            'stock_update': 'info',
        }
        return status_map.get(self.action_type, 'info')