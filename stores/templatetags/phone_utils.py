from django import template
import re

register = template.Library()

@register.filter
def phone_to_wa(value: str) -> str:
    """
    Convert phone like '+220 123-4567' -> '2201234567' for wa.me
    """
    if not value:
        return ''
    # remove non-digits
    digits = re.sub(r'\D+', '', value)
    # If it starts with leading zeros (local format), keep as-is; ideally ensure your DB stores intl numbers.
    return digits