from .models import Shipment, WarehouseShipmentNotification
from stores.b2b.models import B2BOrder
from crossroad_deals.models import CrossroadOrder

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


def nav_counts(request):
    """
    Provides counts for navigation badges

    Returns:
        dict: Context variables with navigation counts

    Available context variables:
        - nav_active_shipments_count: Count of active regular shipments
        - nav_b2b_shipments_count: Count of active B2B shipments
        - nav_black_market_count: Count of active Black Market (Crossroad) orders
        - pending_warehouse_count: Count of pending warehouse receipts
    """
    context = {}

    try:
        # Regular Shipments - Count active shipments (not delivered/cancelled)
        active_shipment_statuses = [
            'pending',
            'picked_up',
            'in_transit',
            'at_warehouse',
            'out_for_delivery',
        ]
        context['nav_active_shipments_count'] = Shipment.objects.filter(
            status__in=active_shipment_statuses
        ).count()

    except Exception as e:
        print(f"Error counting active shipments: {e}")
        context['nav_active_shipments_count'] = 0

    try:
        # B2B Shipments - Count active B2B shipments
        # Assuming you have a b2b field or separate model
        # Adjust this based on your actual B2B implementation
        context['nav_b2b_shipments_count'] = Shipment.objects.filter(
            is_b2b=True,  # Adjust field name as needed
            status__in=active_shipment_statuses
        ).count()

    except Exception as e:
        print(f"Error counting B2B shipments: {e}")
        context['nav_b2b_shipments_count'] = 0

    try:
        # Black Market (Crossroad) Shipments
        # Count orders that are not yet delivered or cancelled
        active_crossroad_statuses = [
            'pending',
            'confirmed',
            'pickup_scheduled',
            'in_transit',
        ]
        context['nav_black_market_count'] = CrossroadOrder.objects.filter(
            delivery_method='easy_move',  # Only Easy Move logistics orders
            status__in=active_crossroad_statuses
        ).count()

    except Exception as e:
        print(f"Error counting Black Market shipments: {e}")
        context['nav_black_market_count'] = 0

    try:
        # Warehouse Receiving - Count pending warehouse receipts
        # Adjust based on your actual warehouse receiving model
        from logistics.models import WarehouseReceipt  # If you have this model
        context['pending_warehouse_count'] = WarehouseReceipt.objects.filter(
            status='pending'
        ).count()

    except Exception as e:
        print(f"Error counting warehouse receipts: {e}")
        context['pending_warehouse_count'] = 0

    return context