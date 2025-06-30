from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    is_buyer = models.BooleanField(default=False)
    is_seller = models.BooleanField(default=False)

    class Meta:
        swappable = 'AUTH_USER_MODEL'