from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.conf import settings
from django.utils.timezone import now, timedelta
from django.core.exceptions import ValidationError

class User(AbstractUser):
    verify_doc = models.FileField(upload_to='company/', blank=True, null=True)
    profile_pic = models.ImageField(upload_to='profile/', blank=True, null=True)
    telephone = models.CharField(max_length=20, unique=True)
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

    def clean(self):
        super().clean()
        # Enforce email uniqueness only if provided (case-insensitive)
        if self.email:
            qs = type(self).objects.filter(email__iexact=self.email)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError({"email": "This email is already in use."})

    def __str__(self):
        return self.username or (self.phone or "")


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
        return self.user.get_full_name() or self.user.username


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

class Device(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="devices")
    device_id = models.CharField(max_length=128, db_index=True)  # fingerprint hash
    user_agent = models.TextField(blank=True)
    browser = models.CharField(max_length=50, blank=True)
    os = models.CharField(max_length=50, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    is_trusted = models.BooleanField(default=False)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "device_id")

    def __str__(self):
        return f"{self.user} - {self.browser} on {self.os} ({'trusted' if self.is_trusted else 'untrusted'})"

class OneTimeCode(models.Model):
    PURPOSE_LOGIN = "login"
    PURPOSES = [(PURPOSE_LOGIN, "Login")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="otps")
    device = models.ForeignKey(Device, null=True, blank=True, on_delete=models.SET_NULL)
    code = models.CharField(max_length=6)
    purpose = models.CharField(max_length=20, choices=PURPOSES, default=PURPOSE_LOGIN)
    expires_at = models.DateTimeField()
    attempts = models.PositiveIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def make(cls, user, device, ttl_minutes=10):
        import secrets
        code = f"{secrets.randbelow(1000000):06d}"
        return cls.objects.create(
            user=user,
            device=device,
            code=code,
            expires_at=now() + timedelta(minutes=ttl_minutes),
        )

    def is_valid(self, candidate: str) -> bool:
        if self.consumed_at or now() > self.expires_at:
            return False
        return self.code == candidate