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
from accounts.currency_utils import convert_currency, format_price, get_user_currency_preference

register = template.Library()


@register.filter
def format_currency(amount, currency_or_user=None):
    """
    Format an amount with currency symbol.

    Usage:
        {{ 100|format_currency:"GMD" }}
        {{ 100|format_currency:user }}
    """
    if amount is None:
        return ""

    try:
        amount = Decimal(str(amount))
    except:
        return str(amount)

    # If it's a string, treat as currency code
    if isinstance(currency_or_user, str):
        return format_price(amount, currency_code=currency_or_user)

    # If it's a user object, get their preference
    return format_price(amount, user=currency_or_user)


@register.filter
def convert_currency_filter(amount, conversion_pair):
    """
    Convert currency from one to another.

    Usage:
        {{ 100|convert_currency_filter:"GMD,USD" }}
        Returns formatted string: "$1.50" (example)
    """
    if not amount or not conversion_pair:
        return ""

    try:
        from_code, to_code = conversion_pair.split(',')
        from_code = from_code.strip()
        to_code = to_code.strip()

        result = convert_currency(amount, from_code, to_code)

        if result['success']:
            return format_price(result['converted_amount'], currency_code=to_code)
        else:
            return f"Error: {result['error']}"
    except Exception as e:
        return f"Error: {str(e)}"


@register.filter
def in_user_currency(amount, user):
    """
    Convert amount to user's preferred currency.

    Usage:
        {{ product.price|in_user_currency:user }}
    """
    if not amount or not user:
        return format_price(amount)

    user_currency = get_user_currency_preference(user)
    if not user_currency:
        return format_price(amount)

    # Assuming the amount is in the base currency (GMD)
    base_currency = Currency.objects.filter(is_base_currency=True).first()
    if not base_currency:
        base_currency = Currency.objects.filter(code='GMD').first()

    if not base_currency:
        return format_price(amount)

    result = convert_currency(amount, base_currency.code, user_currency.code)

    if result['success']:
        return format_price(result['converted_amount'], currency_code=user_currency.code)

    return format_price(amount, currency_code=base_currency.code)


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
def currency_symbol(currency_code):
    """
    Get currency symbol from code.

    Usage:
        {{ "USD"|currency_symbol }}  -> $
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