from django import template
register = template.Library()

@register.filter
def dict_get(d, key):
    return d.get(int(key)) if d and key else 0
