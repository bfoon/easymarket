from .models import Shipment, WarehouseShipmentNotification
from stores.b2b.models import B2BOrder

def logistics_nav_counts(request):
    """
    Global counts for sidebar badges
    """
    if not request.user.is_authenticated:
        return {}

    active_shipments_count = Shipment.objects.filter(
        status__in=['pending', 'in_transit']
    ).count()

    nav_b2b_shipments_count = B2BOrder.objects.filter(status__iexact="shipped").count()

    return {
        'nav_active_shipments_count': active_shipments_count,
        'nav_b2b_shipments_count': nav_b2b_shipments_count,
    }


def notification_context(request):
    """
    Add notification count to all templates.
    """
    if request.user.is_authenticated and hasattr(request.user, 'is_logistic') and request.user.is_logistic:
        unread_count = WarehouseShipmentNotification.get_unread_count(request.user)
        return {
            'notification_unread_count': unread_count,
        }
    return {
        'notification_unread_count': 0,
    }