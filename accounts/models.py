from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.conf import settings
from django.utils.timezone import now, timedelta
from django.core.exceptions import ValidationError
from decimal import Decimal


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

    # Currency preference
    preferred_currency = models.ForeignKey(
        'Currency',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users_preferring',
        help_text="User's preferred currency for pricing"
    )

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


class Country(models.Model):
    """
    Comprehensive country list with currency support
    """
    name = models.CharField(max_length=200, unique=True)
    code = models.CharField(max_length=3, unique=True, help_text="ISO 3166-1 alpha-2 code (e.g., GM, CN, US)")
    code3 = models.CharField(max_length=3, blank=True, help_text="ISO 3166-1 alpha-3 code (e.g., GMB, CHN, USA)")
    numeric_code = models.CharField(max_length=3, blank=True, help_text="ISO 3166-1 numeric code")
    phone_code = models.CharField(max_length=10, blank=True, help_text="International dialing code (e.g., +220)")
    currency = models.ForeignKey('Currency', on_delete=models.SET_NULL, null=True, blank=True, related_name='countries')
    flag_emoji = models.CharField(max_length=10, blank=True, help_text="Flag emoji for the country")
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "Countries"
        ordering = ['name']

    def __str__(self):
        return self.name


class Currency(models.Model):
    """
    Currency model with real-time exchange rate support
    """
    code = models.CharField(max_length=3, unique=True, help_text="ISO 4217 currency code (e.g., GMD, USD, EUR, CNY)")
    name = models.CharField(max_length=100)
    symbol = models.CharField(max_length=10, help_text="Currency symbol (e.g., D, $, €, ¥)")
    decimal_places = models.PositiveSmallIntegerField(default=2, help_text="Number of decimal places")
    is_base_currency = models.BooleanField(
        default=False,
        help_text="Set one currency as base for exchange rates (typically USD or your main currency)"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Currencies"
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.name}"

    def save(self, *args, **kwargs):
        # Ensure only one base currency
        if self.is_base_currency:
            Currency.objects.filter(is_base_currency=True).exclude(pk=self.pk).update(is_base_currency=False)
        super().save(*args, **kwargs)

    def format_amount(self, amount):
        """Format amount with currency symbol"""
        formatted = f"{amount:.{self.decimal_places}f}"
        return f"{self.symbol}{formatted}"

    def get_exchange_rate_to(self, target_currency):
        """
        Get the exchange rate from this currency to target currency
        Returns the rate or None if not available
        """
        if self.code == target_currency.code:
            return Decimal('1.0')

        # Try to get direct rate
        rate = CurrencyExchangeRate.objects.filter(
            from_currency=self,
            to_currency=target_currency
        ).order_by('-updated_at').first()

        if rate and rate.is_valid():
            return rate.rate

        # Try inverse rate
        inverse_rate = CurrencyExchangeRate.objects.filter(
            from_currency=target_currency,
            to_currency=self
        ).order_by('-updated_at').first()

        if inverse_rate and inverse_rate.is_valid():
            return Decimal('1.0') / inverse_rate.rate

        return None

    def convert_to(self, amount, target_currency):
        """
        Convert an amount from this currency to target currency
        Returns tuple: (converted_amount, exchange_rate, success)
        """
        if self.code == target_currency.code:
            return (amount, Decimal('1.0'), True)

        rate = self.get_exchange_rate_to(target_currency)

        if rate:
            converted = Decimal(str(amount)) * rate
            return (converted, rate, True)

        return (None, None, False)


class CurrencyExchangeRate(models.Model):
    """
    Store exchange rates between currencies
    Rates should be updated regularly from external API
    """
    from_currency = models.ForeignKey(Currency, on_delete=models.CASCADE, related_name='rates_from')
    to_currency = models.ForeignKey(Currency, on_delete=models.CASCADE, related_name='rates_to')
    rate = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        help_text="Exchange rate: 1 from_currency = rate × to_currency"
    )
    source = models.CharField(
        max_length=50,
        default='manual',
        help_text="Source of the rate (e.g., 'exchangerate-api', 'manual', 'fixer.io')"
    )
    valid_from = models.DateTimeField(default=timezone.now)
    valid_until = models.DateTimeField(null=True, blank=True, help_text="Rate expiry (if applicable)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Currency Exchange Rate"
        verbose_name_plural = "Currency Exchange Rates"
        ordering = ['-updated_at']
        unique_together = ['from_currency', 'to_currency']
        indexes = [
            models.Index(fields=['from_currency', 'to_currency']),
            models.Index(fields=['-updated_at']),
        ]

    def __str__(self):
        return f"1 {self.from_currency.code} = {self.rate} {self.to_currency.code}"

    def is_valid(self):
        """Check if the rate is still valid"""
        if self.valid_until:
            return timezone.now() <= self.valid_until
        return True

    def clean(self):
        if self.from_currency == self.to_currency:
            raise ValidationError("Cannot create exchange rate for the same currency")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class Address(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    country = models.ForeignKey(
        Country,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Select country from the list"
    )
    # Keep the old country field for backwards compatibility during migration
    country_name = models.CharField(max_length=200, blank=True, null=True, help_text="Deprecated: Use country field")
    address1 = models.TextField(blank=True, null=True)
    address2 = models.TextField(blank=True, null=True)

    # New geo code field (e.g., a unique code on the compound wall)
    geo_code = models.CharField(max_length=100, blank=True, null=True)

    def full_address(self):
        parts = [self.address1, self.address2]
        if self.country:
            parts.append(self.country.name)
        elif self.country_name:
            parts.append(self.country_name)
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