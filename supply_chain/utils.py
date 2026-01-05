"""
Supply Chain Utilities

Functions for managing the flow from store warehouses to logistics warehouses
and finally to customer shipment.
"""

from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db.models import Sum, Avg, F, Q, Count
from decimal import Decimal


# ==================== ORDER FULFILLMENT WORKFLOW ====================

@transaction.atomic
def initiate_order_fulfillment(order, user=None):
    """
    Initiate order fulfillment process.
    
    Steps:
    1. Reserve stock at store warehouses
    2. Create transfer to logistics warehouse
    3. Add to fulfillment queue
    
    Args:
        order: Order instance
        user: User initiating fulfillment
    
    Returns:
        dict: {
            'transfers': list of StoreToLogisticsTransfer instances,
            'reservations': list of StockReservation instances,
            'queue_entry': FulfillmentQueue instance
        }
    """
    from .models import (
        StoreToLogisticsTransfer, TransferItem,
        FulfillmentQueue, WarehouseLinkage
    )
    from stock.utils import reserve_stock
    from stock.models import Stock
    
    transfers = []
    reservations = []
    
    # Group order items by store
    items_by_store = {}
    for item in order.items.all():
        store = item.product.store
        if store not in items_by_store:
            items_by_store[store] = []
        items_by_store[store].append(item)
    
    # Process each store
    for store, order_items in items_by_store.items():
        # Get store warehouse (assuming one warehouse per store)
        store_warehouse = store.warehouse if hasattr(store, 'warehouse') else None
        
        if not store_warehouse:
            raise ValidationError(f"Store {store.name} has no warehouse configured")
        
        # Get optimal logistics warehouse
        logistics_warehouse = WarehouseLinkage.get_optimal_logistics_warehouse(store_warehouse)
        
        if not logistics_warehouse:
            raise ValidationError(
                f"No available logistics warehouse for store {store.name}"
            )
        
        # Create transfer
        transfer = StoreToLogisticsTransfer.objects.create(
            store_warehouse=store_warehouse,
            logistics_warehouse=logistics_warehouse,
            order=order,
            requested_by=user
        )
        
        # Process each item
        for order_item in order_items:
            # Check stock availability
            try:
                stock = Stock.objects.get(
                    product=order_item.product,
                    warehouse=store_warehouse
                )
                
                if stock.available_quantity < order_item.quantity:
                    raise ValidationError(
                        f"Insufficient stock for {order_item.product.name} at "
                        f"{store_warehouse.code}. Available: {stock.available_quantity}, "
                        f"Needed: {order_item.quantity}"
                    )
                
                # Reserve stock
                reservation = reserve_stock(
                    product=order_item.product,
                    warehouse=store_warehouse,
                    quantity=order_item.quantity,
                    order_reference=f"ORDER-{order.id}",
                    user=user,
                    hours_valid=72  # 3 days for transfer
                )
                
                reservations.append(reservation)
                
                # Create transfer item
                TransferItem.objects.create(
                    transfer=transfer,
                    product=order_item.product,
                    order_item=order_item,
                    quantity=order_item.quantity,
                    stock_reservation=reservation
                )
                
            except Stock.DoesNotExist:
                raise ValidationError(
                    f"No stock record for {order_item.product.name} at "
                    f"{store_warehouse.code}"
                )
        
        transfers.append(transfer)
    
    # Create fulfillment queue entry for the first logistics warehouse
    # (or merge if multiple stores use same logistics warehouse)
    primary_logistics_wh = transfers[0].logistics_warehouse
    
    queue_entry = FulfillmentQueue.objects.create(
        order=order,
        logistics_warehouse=primary_logistics_wh,
        transfer=transfers[0] if len(transfers) == 1 else None,
        priority=_determine_order_priority(order)
    )
    
    return {
        'transfers': transfers,
        'reservations': reservations,
        'queue_entry': queue_entry
    }


def _determine_order_priority(order):
    """Determine order priority based on various factors"""
    # Premium customers
    if hasattr(order.customer, 'is_premium') and order.customer.is_premium:
        return 'HIGH'
    
    # Express shipping
    if order.shipping_method and 'express' in order.shipping_method.lower():
        return 'URGENT'
    
    # Large orders
    total_items = sum(item.quantity for item in order.items.all())
    if total_items > 10:
        return 'HIGH'
    
    # Old orders (more than 2 days)
    if (timezone.now() - order.created_at).days > 2:
        return 'HIGH'
    
    return 'NORMAL'


@transaction.atomic
def execute_pickup(transfer_id, user, vehicle=None, driver=None):
    """
    Execute pickup of goods from store warehouse.
    
    Args:
        transfer_id: StoreToLogisticsTransfer ID
        user: User executing pickup
        vehicle: Optional Vehicle instance
        driver: Optional Driver instance
    
    Returns:
        StoreToLogisticsTransfer instance
    """
    from .models import StoreToLogisticsTransfer
    
    transfer = StoreToLogisticsTransfer.objects.get(id=transfer_id)
    transfer.mark_picked_up(user, vehicle, driver)
    
    # Notify store
    _notify_store_pickup(transfer)
    
    return transfer


@transaction.atomic
def execute_receiving(transfer_id, user, condition_notes=None):
    """
    Execute receiving of goods at logistics warehouse.
    
    Args:
        transfer_id: StoreToLogisticsTransfer ID
        user: User receiving goods
        condition_notes: Optional notes about condition
    
    Returns:
        StoreToLogisticsTransfer instance
    """
    from .models import StoreToLogisticsTransfer
    
    transfer = StoreToLogisticsTransfer.objects.get(id=transfer_id)
    
    # Record condition notes if provided
    if condition_notes:
        transfer.notes = f"{transfer.notes}\nReceiving notes: {condition_notes}".strip()
        transfer.save()
    
    # Mark as received (this triggers stock transfer)
    transfer.mark_received(user)
    
    # Update fulfillment queue
    if hasattr(transfer.order, 'fulfillment_queue'):
        queue = transfer.order.fulfillment_queue
        if queue.status == 'QUEUED':
            # Ready for picking now
            queue.notes = f"{queue.notes}\nTransfer received: {transfer.transfer_number}".strip()
            queue.save()
    
    # Notify fulfillment team
    _notify_fulfillment_team(transfer)
    
    return transfer


@transaction.atomic
def start_order_picking(queue_id, picker):
    """
    Start picking an order from the queue.
    
    Args:
        queue_id: FulfillmentQueue ID
        picker: User doing the picking
    
    Returns:
        FulfillmentQueue instance
    """
    from .models import FulfillmentQueue
    
    queue = FulfillmentQueue.objects.select_for_update().get(id=queue_id)
    queue.start_picking(picker)
    
    return queue


@transaction.atomic
def complete_picking_start_packing(queue_id, packer):
    """
    Complete picking and start packing.
    
    Args:
        queue_id: FulfillmentQueue ID
        packer: User doing the packing
    
    Returns:
        FulfillmentQueue instance
    """
    from .models import FulfillmentQueue
    
    queue = FulfillmentQueue.objects.get(id=queue_id)
    queue.start_packing(packer)
    
    return queue


@transaction.atomic
def complete_packing(queue_id):
    """
    Complete packing and mark ready for shipment.
    
    Args:
        queue_id: FulfillmentQueue ID
    
    Returns:
        FulfillmentQueue instance
    """
    from .models import FulfillmentQueue
    
    queue = FulfillmentQueue.objects.get(id=queue_id)
    queue.mark_ready()
    
    return queue


@transaction.atomic
def create_shipment_from_queue(queue_id, shipping_details):
    """
    Create shipment for a ready order.
    
    Args:
        queue_id: FulfillmentQueue ID
        shipping_details: dict with shipment details
            {
                'carrier': str,
                'driver': Driver instance,
                'vehicle': Vehicle instance,
                'estimated_delivery': datetime,
                ...
            }
    
    Returns:
        Shipment instance
    """
    from .models import FulfillmentQueue
    from logistics.models import Shipment
    
    queue = FulfillmentQueue.objects.get(id=queue_id)
    
    if queue.status != 'READY':
        raise ValidationError("Order must be ready before creating shipment")
    
    # Create shipment
    shipment = Shipment.objects.create(
        order=queue.order,
        warehouse=queue.logistics_warehouse,
        driver=shipping_details.get('driver'),
        vehicle=shipping_details.get('vehicle'),
        carrier=shipping_details.get('carrier', 'EasyMarket'),
        estimated_dropoff_time=shipping_details.get('estimated_delivery'),
        status='pending'
    )
    
    # Update queue
    queue.mark_shipped(shipment)
    
    # Update order status
    order = queue.order
    order.status = 'shipped'
    order.save()
    
    return shipment


# ==================== ANALYTICS & REPORTING ====================

def get_transfer_statistics(start_date, end_date, store_warehouse=None, logistics_warehouse=None):
    """Get transfer statistics for a period"""
    from .models import StoreToLogisticsTransfer
    from django.db.models import Count, Avg, Sum, F, Q
    
    transfers = StoreToLogisticsTransfer.objects.filter(
        requested_at__date__gte=start_date,
        requested_at__date__lte=end_date
    )
    
    if store_warehouse:
        transfers = transfers.filter(store_warehouse=store_warehouse)
    
    if logistics_warehouse:
        transfers = transfers.filter(logistics_warehouse=logistics_warehouse)
    
    stats = transfers.aggregate(
        total_transfers=Count('id'),
        completed=Count('id', filter=Q(status='RECEIVED')),
        in_transit=Count('id', filter=Q(status='IN_TRANSIT')),
        pending=Count('id', filter=Q(status='PENDING')),
        cancelled=Count('id', filter=Q(status='CANCELLED')),
        avg_duration=Avg('actual_duration_minutes', filter=Q(status='RECEIVED')),
        total_items=Sum('items__quantity')
    )
    
    return stats


def get_fulfillment_metrics(start_date, end_date, logistics_warehouse=None):
    """Get fulfillment metrics for a period"""
    from .models import FulfillmentQueue
    from django.db.models import Count, Avg, Q
    
    queues = FulfillmentQueue.objects.filter(
        queued_at__date__gte=start_date,
        queued_at__date__lte=end_date
    )
    
    if logistics_warehouse:
        queues = queues.filter(logistics_warehouse=logistics_warehouse)
    
    metrics = queues.aggregate(
        total_orders=Count('id'),
        shipped=Count('id', filter=Q(status='SHIPPED')),
        ready=Count('id', filter=Q(status='READY')),
        in_progress=Count('id', filter=Q(status__in=['PICKING', 'PACKING'])),
        avg_pick_time=Avg('actual_pick_time_minutes'),
        avg_pack_time=Avg('actual_pack_time_minutes'),
        avg_total_time=Avg(
            F('actual_pick_time_minutes') + F('actual_pack_time_minutes'),
            filter=Q(status='SHIPPED')
        )
    )
    
    return metrics


def get_warehouse_performance(warehouse, period_days=30):
    """
    Get comprehensive performance metrics for a warehouse.
    
    Args:
        warehouse: Warehouse instance (stock or logistics)
        period_days: Number of days to analyze
    
    Returns:
        dict with performance metrics
    """
    from datetime import timedelta
    from .models import StoreToLogisticsTransfer, FulfillmentQueue
    from django.db.models import Avg, Count, Sum
    
    start_date = timezone.now().date() - timedelta(days=period_days)
    
    # Determine warehouse type
    is_stock_warehouse = hasattr(warehouse, 'outbound_transfers')
    
    if is_stock_warehouse:
        # Store warehouse metrics
        transfers = StoreToLogisticsTransfer.objects.filter(
            store_warehouse=warehouse,
            requested_at__date__gte=start_date
        )
        
        return {
            'warehouse_type': 'store',
            'total_transfers': transfers.count(),
            'completed_transfers': transfers.filter(status='RECEIVED').count(),
            'avg_transfer_time': transfers.filter(
                status='RECEIVED'
            ).aggregate(avg=Avg('actual_duration_minutes'))['avg'],
            'total_items_transferred': transfers.aggregate(
                total=Sum('items__quantity')
            )['total'] or 0,
            'pending_transfers': transfers.filter(status='PENDING').count(),
        }
    else:
        # Logistics warehouse metrics
        fulfillments = FulfillmentQueue.objects.filter(
            logistics_warehouse=warehouse,
            queued_at__date__gte=start_date
        )
        
        return {
            'warehouse_type': 'logistics',
            'total_orders': fulfillments.count(),
            'shipped_orders': fulfillments.filter(status='SHIPPED').count(),
            'avg_fulfillment_time': fulfillments.filter(
                status='SHIPPED'
            ).aggregate(
                avg=Avg(F('actual_pick_time_minutes') + F('actual_pack_time_minutes'))
            )['avg'],
            'avg_pick_time': fulfillments.aggregate(
                avg=Avg('actual_pick_time_minutes')
            )['avg'],
            'avg_pack_time': fulfillments.aggregate(
                avg=Avg('actual_pack_time_minutes')
            )['avg'],
            'queued_orders': fulfillments.filter(status='QUEUED').count(),
            'in_progress_orders': fulfillments.filter(
                status__in=['PICKING', 'PACKING']
            ).count(),
        }


def get_bottlenecks_report():
    """Identify bottlenecks in the supply chain"""
    from .models import StoreToLogisticsTransfer, FulfillmentQueue
    from django.db.models import Count, Avg, F
    
    bottlenecks = []
    
    # Check for pending transfers
    pending_transfers = StoreToLogisticsTransfer.objects.filter(
        status='PENDING'
    ).values('store_warehouse__name').annotate(
        count=Count('id'),
        avg_wait_time=Avg(
            F('picked_up_at') - F('requested_at'),
            filter=F('status') != 'PENDING'
        )
    ).order_by('-count')
    
    for item in pending_transfers[:5]:
        if item['count'] > 5:
            bottlenecks.append({
                'type': 'Pending Transfers',
                'location': item['store_warehouse__name'],
                'count': item['count'],
                'severity': 'HIGH' if item['count'] > 10 else 'MEDIUM'
            })
    
    # Check for slow fulfillment
    slow_fulfillment = FulfillmentQueue.objects.filter(
        status__in=['QUEUED', 'PICKING', 'PACKING']
    ).values('logistics_warehouse__name').annotate(
        count=Count('id')
    ).order_by('-count')
    
    for item in slow_fulfillment[:5]:
        if item['count'] > 10:
            bottlenecks.append({
                'type': 'Slow Fulfillment',
                'location': item['logistics_warehouse__name'],
                'count': item['count'],
                'severity': 'HIGH' if item['count'] > 20 else 'MEDIUM'
            })
    
    return bottlenecks


# ==================== HELPER FUNCTIONS ====================

def _notify_store_pickup(transfer):
    """Send notification to store about pickup"""
    # TODO: Implement notification system
    pass


def _notify_fulfillment_team(transfer):
    """Send notification to fulfillment team"""
    # TODO: Implement notification system
    pass


def get_estimated_fulfillment_time(order):
    """
    Estimate total fulfillment time for an order.
    
    Returns:
        dict: {
            'transfer_time_minutes': int,
            'pick_time_minutes': int,
            'pack_time_minutes': int,
            'total_minutes': int,
            'estimated_ship_date': datetime
        }
    """
    from .models import WarehouseLinkage
    
    # Calculate transfer time (max across all stores)
    max_transfer_time = 0
    
    for item in order.items.all():
        store = item.product.store
        if hasattr(store, 'warehouse'):
            linkage = WarehouseLinkage.objects.filter(
                store_warehouse=store.warehouse,
                is_active=True
            ).first()
            
            if linkage:
                max_transfer_time = max(
                    max_transfer_time,
                    linkage.estimated_transfer_time_minutes
                )
    
    # Estimate pick/pack time based on item count
    total_items = sum(item.quantity for item in order.items.all())
    pick_time = 10 + (total_items * 2)  # 2 min per item + 10 min base
    pack_time = 10 + (total_items * 1)  # 1 min per item + 10 min base
    
    total_minutes = max_transfer_time + pick_time + pack_time
    
    estimated_ship_date = timezone.now() + timezone.timedelta(minutes=total_minutes)
    
    return {
        'transfer_time_minutes': max_transfer_time,
        'pick_time_minutes': pick_time,
        'pack_time_minutes': pack_time,
        'total_minutes': total_minutes,
        'estimated_ship_date': estimated_ship_date
    }


def bulk_create_warehouse_linkages(store_warehouses, logistics_warehouse, is_primary=True):
    """
    Bulk create linkages between store warehouses and a logistics warehouse.
    
    Args:
        store_warehouses: List of stock.Warehouse instances
        logistics_warehouse: logistics.Warehouse instance
        is_primary: Whether this is the primary logistics warehouse
    
    Returns:
        List of created WarehouseLinkage instances
    """
    from .models import WarehouseLinkage
    from stock.geocoding_utils import calculate_distance
    
    linkages = []
    
    for store_wh in store_warehouses:
        # Calculate distance if both have geocodes
        distance_km = None
        if store_wh.has_geocode and logistics_warehouse.latitude and logistics_warehouse.longitude:
            store_coords = store_wh.get_coordinates()
            distance_km = calculate_distance(
                store_coords[0], store_coords[1],
                float(logistics_warehouse.latitude),
                float(logistics_warehouse.longitude)
            )
        
        # Estimate transfer time based on distance
        # Assume 40 km/h average speed + 15 min loading/unloading
        transfer_time = 15
        if distance_km:
            transfer_time += int((distance_km / 40) * 60)
        
        linkage = WarehouseLinkage.objects.create(
            store_warehouse=store_wh,
            logistics_warehouse=logistics_warehouse,
            is_primary=is_primary,
            distance_km=distance_km,
            estimated_transfer_time_minutes=transfer_time
        )
        
        linkages.append(linkage)
    
    return linkages
