from django import template
from django import template
from datetime import timedelta

register = template.Library()

@register.filter
def mul(value, arg):
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0

@register.filter
def div(value, arg):
    try:
        return float(value) / float(arg) if float(arg) != 0 else 0
    except (ValueError, TypeError):
        return 0

@register.filter
def sub(value, arg):
    try:
        return float(value) - float(arg)
    except (ValueError, TypeError):
        return 0


@register.filter
def add_days(value, days):
    try:
        return value + timedelta(days=int(days))
    except Exception:
        return value
