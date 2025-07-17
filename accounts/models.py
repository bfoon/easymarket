from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    verify_doc = models.FileField(upload_to='company/', blank=True, null=True)
    profile_pic = models.ImageField(upload_to='profile/', blank=True, null=True)
    telephone = models.CharField(max_length=200, blank=True, null=True)
    is_buyer = models.BooleanField(default=False)
    is_seller = models.BooleanField(default=False)
    is_logistic = models.BooleanField(default=False)
    is_finance = models.BooleanField(default=False)
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


