# accounts/currency_utils.py
"""
Utility functions for currency conversion and exchange rate updates.
Supports multiple API providers for fetching real-time exchange rates.
"""

import logging
import requests
from decimal import Decimal
from django.utils import timezone
from django.conf import settings
from .models import Currency, CurrencyExchangeRate

logger = logging.getLogger(__name__)


class ExchangeRateService:
    """
    Service to fetch and update currency exchange rates from various providers.

    Supported providers:
    - exchangerate-api.com (free tier available)
    - fixer.io
    - openexchangerates.org
    """

    def __init__(self, provider='exchangerate-api', api_key=None):
        self.provider = provider
        self.api_key = api_key or getattr(settings, 'EXCHANGE_RATE_API_KEY', None)

    def fetch_rates(self, base_currency_code='USD'):
        """
        Fetch exchange rates from the configured provider.

        Args:
            base_currency_code: The base currency code (default: USD)

        Returns:
            dict: Dictionary of currency codes to exchange rates
            None: If the request fails
        """
        if self.provider == 'exchangerate-api':
            return self._fetch_from_exchangerate_api(base_currency_code)
        elif self.provider == 'fixer':
            return self._fetch_from_fixer(base_currency_code)
        elif self.provider == 'openexchangerates':
            return self._fetch_from_openexchangerates()
        else:
            logger.error(f"Unknown provider: {self.provider}")
            return None

    def _fetch_from_exchangerate_api(self, base_currency_code):
        """
        Fetch rates from exchangerate-api.com
        Free tier: 1,500 requests/month
        URL: https://www.exchangerate-api.com/
        """
        url = f"https://v6.exchangerate-api.com/v6/{self.api_key}/latest/{base_currency_code}"

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get('result') == 'success':
                return data.get('conversion_rates', {})
            else:
                logger.error(f"Exchange rate API error: {data.get('error-type')}")
                return None

        except requests.RequestException as e:
            logger.error(f"Failed to fetch rates from exchangerate-api: {e}")
            return None

    def _fetch_from_fixer(self, base_currency_code):
        """
        Fetch rates from fixer.io
        Requires API key
        URL: https://fixer.io/
        """
        url = f"http://data.fixer.io/api/latest"
        params = {
            'access_key': self.api_key,
            'base': base_currency_code
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get('success'):
                return data.get('rates', {})
            else:
                logger.error(f"Fixer API error: {data.get('error')}")
                return None

        except requests.RequestException as e:
            logger.error(f"Failed to fetch rates from fixer: {e}")
            return None

    def _fetch_from_openexchangerates(self):
        """
        Fetch rates from openexchangerates.org
        Free tier: 1,000 requests/month
        URL: https://openexchangerates.org/
        Note: Free tier only supports USD as base
        """
        url = f"https://openexchangerates.org/api/latest.json"
        params = {
            'app_id': self.api_key
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            return data.get('rates', {})

        except requests.RequestException as e:
            logger.error(f"Failed to fetch rates from openexchangerates: {e}")
            return None


def update_exchange_rates(base_currency_code=None, provider='exchangerate-api', api_key=None):
    """
    Update all exchange rates in the database.

    Args:
        base_currency_code: Base currency code (if None, uses the base currency from DB)
        provider: API provider to use
        api_key: API key for the provider

    Returns:
        tuple: (success_count, error_count, message)
    """
    # Get base currency
    if base_currency_code:
        try:
            base_currency = Currency.objects.get(code=base_currency_code, is_active=True)
        except Currency.DoesNotExist:
            return (0, 0, f"Base currency {base_currency_code} not found")
    else:
        base_currency = Currency.objects.filter(is_base_currency=True, is_active=True).first()
        if not base_currency:
            base_currency = Currency.objects.filter(code='USD', is_active=True).first()

        if not base_currency:
            return (0, 0, "No base currency configured")

    # Fetch rates
    service = ExchangeRateService(provider=provider, api_key=api_key)
    rates = service.fetch_rates(base_currency.code)

    if not rates:
        return (0, 0, "Failed to fetch exchange rates from API")

    # Update rates in database
    success_count = 0
    error_count = 0

    for to_currency_code, rate_value in rates.items():
        try:
            to_currency = Currency.objects.get(code=to_currency_code, is_active=True)

            # Update or create the exchange rate
            rate_obj, created = CurrencyExchangeRate.objects.update_or_create(
                from_currency=base_currency,
                to_currency=to_currency,
                defaults={
                    'rate': Decimal(str(rate_value)),
                    'source': provider,
                    'valid_from': timezone.now(),
                }
            )
            success_count += 1

            action = "created" if created else "updated"
            logger.info(f"Exchange rate {action}: 1 {base_currency.code} = {rate_value} {to_currency_code}")

        except Currency.DoesNotExist:
            logger.warning(f"Currency {to_currency_code} not found in database, skipping")
            error_count += 1
        except Exception as e:
            logger.error(f"Error updating rate for {to_currency_code}: {e}")
            error_count += 1

    message = f"Updated {success_count} rates successfully"
    if error_count > 0:
        message += f" ({error_count} errors)"

    return (success_count, error_count, message)


def convert_currency(amount, from_currency_code, to_currency_code):
    """
    Convert amount from one currency to another.

    Args:
        amount: Amount to convert (Decimal or float)
        from_currency_code: Source currency code (e.g., 'GMD')
        to_currency_code: Target currency code (e.g., 'USD')

    Returns:
        dict: {
            'success': bool,
            'converted_amount': Decimal or None,
            'rate': Decimal or None,
            'from_currency': str,
            'to_currency': str,
            'original_amount': Decimal,
            'error': str or None
        }
    """
    try:
        from_currency = Currency.objects.get(code=from_currency_code, is_active=True)
        to_currency = Currency.objects.get(code=to_currency_code, is_active=True)

        converted_amount, rate, success = from_currency.convert_to(amount, to_currency)

        if success:
            return {
                'success': True,
                'converted_amount': converted_amount,
                'rate': rate,
                'from_currency': from_currency_code,
                'to_currency': to_currency_code,
                'original_amount': Decimal(str(amount)),
                'error': None
            }
        else:
            return {
                'success': False,
                'converted_amount': None,
                'rate': None,
                'from_currency': from_currency_code,
                'to_currency': to_currency_code,
                'original_amount': Decimal(str(amount)),
                'error': 'Exchange rate not available'
            }

    except Currency.DoesNotExist as e:
        return {
            'success': False,
            'converted_amount': None,
            'rate': None,
            'from_currency': from_currency_code,
            'to_currency': to_currency_code,
            'original_amount': Decimal(str(amount)),
            'error': f'Currency not found: {str(e)}'
        }
    except Exception as e:
        logger.error(f"Currency conversion error: {e}")
        return {
            'success': False,
            'converted_amount': None,
            'rate': None,
            'from_currency': from_currency_code,
            'to_currency': to_currency_code,
            'original_amount': Decimal(str(amount)),
            'error': str(e)
        }


def get_user_currency_preference(user):
    """
    Get the user's preferred currency, falling back to default if not set.

    Args:
        user: User object

    Returns:
        Currency object or None
    """
    if user.is_authenticated and user.preferred_currency:
        return user.preferred_currency

    # Try to get currency from user's country
    if user.is_authenticated:
        address = user.address_set.filter(country__isnull=False).first()
        if address and address.country and address.country.currency:
            return address.country.currency

    # Fall back to default currency (GMD for Gambia or USD)
    default_currency = Currency.objects.filter(code='GMD', is_active=True).first()
    if not default_currency:
        default_currency = Currency.objects.filter(code='USD', is_active=True).first()

    return default_currency


def format_price(amount, currency_code=None, user=None):
    """
    Format a price with the appropriate currency symbol.

    Args:
        amount: The amount to format
        currency_code: Currency code (optional, will use user preference if not provided)
        user: User object (optional, for getting preference)

    Returns:
        str: Formatted price string
    """
    if currency_code:
        try:
            currency = Currency.objects.get(code=currency_code, is_active=True)
        except Currency.DoesNotExist:
            return f"{amount}"
    elif user:
        currency = get_user_currency_preference(user)
    else:
        currency = Currency.objects.filter(code='GMD', is_active=True).first()

    if currency:
        return currency.format_amount(amount)

    return f"{amount}"