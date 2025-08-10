from django import template

register = template.Library()


@register.filter
def badge_class(status: str):
    mapping = {
        "open": "bg-primary",
        "pending": "bg-warning",
        "waiting": "bg-secondary",
        "solved": "bg-success",
        "closed": "bg-dark",
    }
    return mapping.get(status, "bg-light")