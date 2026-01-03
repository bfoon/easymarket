from .models import Shipment

def logistics_nav_counts(request):
    """
    Global counts for sidebar badges
    """
    if not request.user.is_authenticated:
        return {}

    active_shipments_count = Shipment.objects.filter(
        status__in=['pending', 'in_transit']
    ).count()

    return {
        'nav_active_shipments_count': active_shipments_count,
    }
