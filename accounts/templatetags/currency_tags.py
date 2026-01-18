# accounts/templatetags/currency_tags.py
"""
Template tags for currency conversion and formatting in Django templates.

Usage in templates:
    {% load currency_tags %}

    {{ price|format_currency:user }}
    {{ price|convert_currency:"GMD,USD" }}
    {{ 100|in_user_currency:user }}
"""

from django import template
from django.utils.safestring import mark_safe
from decimal import Decimal
from accounts.models import Currency
from django.conf import settings
from accounts.currency_utils import convert_currency, get_user_currency_preference

register = template.Library()


def _get_base_currency_code():
    # Prefer DB "base" currency if you have it; otherwise fallback
    base = Currency.objects.filter(is_base_currency=True, is_active=True).first()
    if base:
        return base.code
    return getattr(settings, "BASE_CURRENCY_CODE", "GMD")


def format_price_with_commas(amount, currency_code=None, user=None):
    """
    Enhanced format_price that includes thousand separators.

    Args:
        amount: The amount to format
        currency_code: Currency code (e.g., 'GMD', 'USD')
        user: User object (will use their preferred currency)

    Returns:
        Formatted string like "D1,234.56" or "$1,234.56"
    """
    if amount is None:
        return ""

    try:
        amount = Decimal(str(amount))
    except:
        return str(amount)

    # Get currency
    currency = None
    if user and hasattr(user, 'preferred_currency') and user.preferred_currency:
        currency = user.preferred_currency
    elif currency_code:
        try:
            currency = Currency.objects.get(code=currency_code, is_active=True)
        except Currency.DoesNotExist:
            # Fallback to GMD
            currency = Currency.objects.filter(code='GMD', is_active=True).first()
    else:
        # Default to GMD
        currency = Currency.objects.filter(code='GMD', is_active=True).first()

    if not currency:
        return str(amount)

    # Format with thousand separators
    # Round to currency's decimal places
    decimal_places = getattr(currency, 'decimal_places', 2)
    rounded_amount = round(amount, decimal_places)

    # Split into integer and decimal parts
    int_part = int(rounded_amount)
    dec_part = rounded_amount - int_part

    # Format integer part with commas
    formatted_int = "{:,}".format(int_part)

    # Add decimal part if needed
    if decimal_places > 0 and dec_part > 0:
        # Format decimal part
        dec_str = str(dec_part)[2:]  # Remove "0."
        dec_str = dec_str.ljust(decimal_places, '0')[:decimal_places]
        formatted_number = f"{formatted_int}.{dec_str}"
    elif decimal_places > 0:
        # Always show decimal places even if zero
        formatted_number = f"{formatted_int}.{'0' * decimal_places}"
    else:
        formatted_number = formatted_int

    # Add currency symbol
    symbol = getattr(currency, 'symbol', currency.code)
    return f"{symbol}{formatted_number}"


@register.simple_tag(takes_context=True)
def display_money(context, amount):
    """
    Usage:
        {% display_money product.price %}
    Converts from base currency -> user's preferred currency and formats with symbol and commas.
    """
    request = context.get("request")
    user = getattr(request, "user", None)

    if amount is None:
        return ""

    # Ensure Decimal
    try:
        amount = Decimal(str(amount))
    except Exception:
        return str(amount)

    # If no user (guest) just format as base currency
    base_code = _get_base_currency_code()
    if not user or not getattr(user, "is_authenticated", False):
        return format_price_with_commas(amount, currency_code=base_code)

    preferred = get_user_currency_preference(user)
    if not preferred:
        return format_price_with_commas(amount, currency_code=base_code)

    # If same currency, no conversion needed
    if preferred.code == base_code:
        return format_price_with_commas(amount, currency_code=base_code)

    # Convert
    result = convert_currency(amount, base_code, preferred.code)
    if result.get("success"):
        return format_price_with_commas(result["converted_amount"], currency_code=preferred.code)

    # Fallback (if rate missing)
    return format_price_with_commas(amount, currency_code=base_code)


@register.simple_tag(takes_context=True)
def display_cart_money(context, amount):
    """
    Usage:
        {% display_cart_money item.subtotal %}
    Converts cart subtotal from base currency to user's preferred currency with commas.
    """
    request = context.get("request")
    user = getattr(request, "user", None)

    if amount is None:
        return ""

    try:
        amount = Decimal(str(amount))
    except Exception:
        return str(amount)

    base_code = _get_base_currency_code()

    # Guest user → show base currency
    if not user or not user.is_authenticated:
        return format_price_with_commas(amount, currency_code=base_code)

    preferred = get_user_currency_preference(user)
    if not preferred:
        return format_price_with_commas(amount, currency_code=base_code)

    # Same currency → no conversion
    if preferred.code == base_code:
        return format_price_with_commas(amount, currency_code=base_code)

    # Convert
    result = convert_currency(amount, base_code, preferred.code)
    if result.get("success"):
        return format_price_with_commas(
            result["converted_amount"],
            currency_code=preferred.code
        )

    # Fallback
    return format_price_with_commas(amount, currency_code=base_code)


@register.filter
def format_currency(amount, currency_or_user=None):
    """
    Format an amount with currency symbol and thousand separators.

    Usage:
        {{ 1000|format_currency:"GMD" }}  -> D1,000.00
        {{ 1000|format_currency:user }}   -> D1,000.00 (or user's currency)
    """
    if amount is None:
        return ""

    try:
        amount = Decimal(str(amount))
    except:
        return str(amount)

    # If it's a string, treat as currency code
    if isinstance(currency_or_user, str):
        return format_price_with_commas(amount, currency_code=currency_or_user)

    # If it's a user object, get their preference
    return format_price_with_commas(amount, user=currency_or_user)


@register.filter
def convert_currency_filter(amount, conversion_pair):
    """
    Convert currency from one to another with comma formatting.

    Usage:
        {{ 1000|convert_currency_filter:"GMD,USD" }}
        Returns formatted string: "$14.60" (example with commas if over 1000)
    """
    if not amount or not conversion_pair:
        return ""

    try:
        from_code, to_code = conversion_pair.split(',')
        from_code = from_code.strip()
        to_code = to_code.strip()

        result = convert_currency(amount, from_code, to_code)

        if result['success']:
            return format_price_with_commas(result['converted_amount'], currency_code=to_code)
        else:
            return f"Error: {result['error']}"
    except Exception as e:
        return f"Error: {str(e)}"


@register.filter
def in_user_currency(amount, user):
    """
    Convert amount to user's preferred currency with comma formatting.

    Usage:
        {{ product.price|in_user_currency:user }}
        Returns: "D1,234.56"
    """
    if not amount or not user:
        return format_price_with_commas(amount)

    user_currency = get_user_currency_preference(user)
    if not user_currency:
        return format_price_with_commas(amount)

    # Assuming the amount is in the base currency (GMD)
    base_currency = Currency.objects.filter(is_base_currency=True).first()
    if not base_currency:
        base_currency = Currency.objects.filter(code='GMD').first()

    if not base_currency:
        return format_price_with_commas(amount)

    result = convert_currency(amount, base_currency.code, user_currency.code)

    if result['success']:
        return format_price_with_commas(result['converted_amount'], currency_code=user_currency.code)

    return format_price_with_commas(amount, currency_code=base_currency.code)


@register.simple_tag
def currency_converter(amount, from_currency, to_currency):
    """
    Convert and return detailed conversion information.

    Usage:
        {% currency_converter 100 "GMD" "USD" as conversion %}
        Amount: {{ conversion.converted_amount }}
        Rate: {{ conversion.rate }}
    """
    return convert_currency(amount, from_currency, to_currency)


@register.simple_tag
def get_exchange_rate(from_currency_code, to_currency_code):
    """
    Get the current exchange rate between two currencies.

    Usage:
        {% get_exchange_rate "GMD" "USD" as rate %}
        Exchange rate: {{ rate }}
    """
    try:
        from_curr = Currency.objects.get(code=from_currency_code)
        to_curr = Currency.objects.get(code=to_currency_code)
        return from_curr.get_exchange_rate_to(to_curr)
    except Currency.DoesNotExist:
        return None


@register.inclusion_tag('accounts/currency_selector.html', takes_context=True)
def currency_selector(context):
    """
    Render a currency selector dropdown.

    Usage:
        {% currency_selector %}
    """
    request = context.get('request')
    user = request.user if request else None

    currencies = Currency.objects.filter(is_active=True).order_by('code')
    current_currency = get_user_currency_preference(user) if user and user.is_authenticated else None

    return {
        'currencies': currencies,
        'current_currency': current_currency,
        'user': user,
    }


@register.filter
def multiply(value, arg):
    """
    Multiply two values.

    Usage:
        {{ price|multiply:quantity }}
    """
    try:
        return Decimal(str(value)) * Decimal(str(arg))
    except:
        return ""


@register.filter
def format_with_commas(value):
    """
    Format number with thousand separators (no currency symbol).

    Usage:
        {{ 1000|format_with_commas }}  -> 1,000
        {{ 1234567.89|format_with_commas }}  -> 1,234,567.89
    """
    try:
        # Convert to Decimal for precise handling
        num = Decimal(str(value))

        # Split into integer and decimal parts
        str_num = str(num)
        if '.' in str_num:
            int_part, dec_part = str_num.split('.')
            # Format integer part with commas
            formatted_int = "{:,}".format(int(int_part))
            return f"{formatted_int}.{dec_part}"
        else:
            # No decimal part
            return "{:,}".format(int(num))
    except:
        return str(value)


@register.filter
def currency_symbol(currency_code):
    """
    Get currency symbol from code.

    Usage:
        {{ "USD"|currency_symbol }}  -> $
        {{ "GMD"|currency_symbol }}  -> D
    """
    try:
        currency = Currency.objects.get(code=currency_code)
        return currency.symbol
    except Currency.DoesNotExist:
        return currency_code


@register.filter
def split(value, separator=','):
    """
    Split a string by a separator.

    Usage:
        {% for item in "a,b,c"|split:"," %}
            {{ item }}
        {% endfor %}
    """
    if not value:
        return []
    return str(value).split(separator)


@register.filter
def get_item(dictionary, key):
    """
    Get an item from a dictionary.

    Usage:
        {{ mydict|get_item:"mykey" }}
    """
    if not dictionary:
        return None
    return dictionary.get(key)


@register.simple_tag
def get_currency_by_code(code):
    """
    Get currency object by code.

    Usage:
        {% get_currency_by_code "USD" as usd_currency %}
        {{ usd_currency.name }}
    """
    try:
        return Currency.objects.get(code=code, is_active=True)
    except Currency.DoesNotExist:
        return None


@register.filter
def default_currency(value):
    """
    Return GMD currency if value is None.

    Usage:
        {{ user.preferred_currency|default_currency }}
    """
    if value:
        return value
    try:
        return Currency.objects.get(code='GMD', is_active=True)
    except Currency.DoesNotExist:
        return Currency.objects.filter(is_active=True).first()


@register.filter
def money(value, currency_code='GMD'):
    """
    Simple money formatter with commas.

    Usage:
        {{ 1000|money }}  -> D1,000.00
        {{ 1000|money:"USD" }}  -> $1,000.00
    """
    return format_price_with_commas(value, currency_code=currency_code)