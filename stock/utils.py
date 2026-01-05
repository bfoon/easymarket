from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum, Avg, F, Q, Count
from django.utils import timezone
from datetime import timedelta, date
from decimal import Decimal
from .models import (
    Stock, StockMovement, Warehouse, StockAlert, StockReservation,
    StockCount, StockCountItem, BatchTracking, StockAnalytics,
    PurchaseOrder, PurchaseOrderItem
)


# ==================== STOCK OPERATIONS ====================

@transaction.atomic
def adjust_stock(product, warehouse, quantity, movement_type, user=None, reference_number='', 
                 unit_cost=0.00, notes='', destination_warehouse=None):
    """
    Universal function to adjust stock with full audit trail.
    
    Args:
        product: Product instance
        warehouse: Warehouse instance
        quantity: Change in quantity (positive or negative)
        movement_type: Type of movement (see StockMovement.MOVEMENT_TYPES)
        user: User making the change
        reference_number: PO, SO, or other reference
        unit_cost: Cost per unit
        notes: Additional notes
        destination_warehouse: For transfers only
    
    Returns:
        tuple: (Stock instance, StockMovement instance)
    """
    # Get or create stock record
    stock, created = Stock.objects.get_or_create(
        product=product,
        warehouse=warehouse,
        defaults={'unit_cost': unit_cost}
    )
    
    # Validate stock reduction
    if quantity < 0 and stock.quantity + quantity < 0:
        raise ValidationError(
            f"Insufficient stock. Available: {stock.quantity}, "
            f"Attempting to reduce by: {abs(quantity)}"
        )
    
    # Update stock quantity
    stock.quantity = F('quantity') + quantity
    stock.save()
    stock.refresh_from_db()
    
    # Create movement record
    movement = StockMovement.objects.create(
        product=product,
        warehouse=warehouse,
        movement_type=movement_type,
        quantity=quantity,
        reference_number=reference_number,
        unit_cost=unit_cost,
        notes=notes,
        created_by=user,
        destination_warehouse=destination_warehouse
    )
    
    # Check for alerts
    check_stock_alerts(stock)
    
    return stock, movement


def receive_stock(product, warehouse, quantity, unit_cost, user=None, reference_number='', 
                  batch_number=None, expiry_date=None):
    """Receive stock from purchase order or supplier."""
    stock, movement = adjust_stock(
        product=product,
        warehouse=warehouse,
        quantity=quantity,
        movement_type='PURCHASE',
        user=user,
        reference_number=reference_number,
        unit_cost=unit_cost,
        notes=f'Stock received - PO: {reference_number}'
    )
    
    # Create batch tracking if provided
    if batch_number:
        BatchTracking.objects.create(
            product=product,
            batch_number=batch_number,
            warehouse=warehouse,
            quantity=quantity,
            expiry_date=expiry_date,
            supplier_reference=reference_number
        )
    
    return stock, movement


def dispatch_stock(product, warehouse, quantity, user=None, order_reference='', unit_cost=0.00):
    """Dispatch stock for sale or order fulfillment."""
    return adjust_stock(
        product=product,
        warehouse=warehouse,
        quantity=-quantity,
        movement_type='SALE',
        user=user,
        reference_number=order_reference,
        unit_cost=unit_cost,
        notes=f'Stock dispatched for order: {order_reference}'
    )


@transaction.atomic
def transfer_stock(product, from_warehouse, to_warehouse, quantity, user=None, notes=''):
    """Transfer stock between warehouses."""
    # Reduce from source
    stock_out, movement_out = adjust_stock(
        product=product,
        warehouse=from_warehouse,
        quantity=-quantity,
        movement_type='TRANSFER',
        user=user,
        notes=f'Transfer to {to_warehouse.code}: {notes}',
        destination_warehouse=to_warehouse
    )
    
    # Add to destination
    stock_in, movement_in = adjust_stock(
        product=product,
        warehouse=to_warehouse,
        quantity=quantity,
        movement_type='TRANSFER',
        user=user,
        notes=f'Transfer from {from_warehouse.code}: {notes}'
    )
    
    return (stock_out, stock_in), (movement_out, movement_in)


# ==================== STOCK RESERVATION ====================

@transaction.atomic
def reserve_stock(product, warehouse, quantity, order_reference, user=None, hours_valid=24):
    """Reserve stock for an order."""
    stock = Stock.objects.get(product=product, warehouse=warehouse)
    
    if stock.available_quantity < quantity:
        raise ValidationError(
            f"Insufficient available stock. Available: {stock.available_quantity}, "
            f"Requested: {quantity}"
        )
    
    expires_at = timezone.now() + timedelta(hours=hours_valid)
    
    reservation = StockReservation.objects.create(
        stock=stock,
        quantity=quantity,
        order_reference=order_reference,
        reserved_by=user,
        expires_at=expires_at
    )
    
    # Update reserved quantity
    stock.reserved_quantity = F('reserved_quantity') + quantity
    stock.save()
    stock.refresh_from_db()
    
    return reservation


@transaction.atomic
def release_reservation(reservation):
    """Release a stock reservation."""
    if not reservation.is_active:
        return False
    
    stock = reservation.stock
    stock.reserved_quantity = F('reserved_quantity') - reservation.quantity
    stock.save()
    
    reservation.is_active = False
    reservation.save()
    
    return True


@transaction.atomic
def fulfill_reservation(reservation, user=None):
    """Fulfill a reservation by dispatching stock."""
    if not reservation.is_active:
        raise ValidationError("Reservation is not active")
    
    # Dispatch the stock
    dispatch_stock(
        product=reservation.stock.product,
        warehouse=reservation.stock.warehouse,
        quantity=reservation.quantity,
        user=user,
        order_reference=reservation.order_reference
    )
    
    # Update reservation
    reservation.fulfilled_at = timezone.now()
    reservation.is_active = False
    reservation.save()
    
    # Update reserved quantity
    stock = reservation.stock
    stock.reserved_quantity = F('reserved_quantity') - reservation.quantity
    stock.save()
    
    return True


def cleanup_expired_reservations():
    """Release all expired reservations."""
    expired = StockReservation.objects.filter(
        is_active=True,
        expires_at__lt=timezone.now(),
        fulfilled_at__isnull=True
    )
    
    count = 0
    for reservation in expired:
        release_reservation(reservation)
        count += 1
    
    return count


# ==================== STOCK COUNTING ====================

@transaction.atomic
def create_stock_count(warehouse, count_date, counted_by, products=None):
    """Create a new stock count session."""
    stock_count = StockCount.objects.create(
        warehouse=warehouse,
        count_date=count_date,
        counted_by=counted_by,
        status='PLANNED'
    )
    
    # Add products to count
    if products is None:
        products = Stock.objects.filter(warehouse=warehouse).select_related('product')
    
    for stock in products:
        StockCountItem.objects.create(
            stock_count=stock_count,
            product=stock.product,
            expected_quantity=stock.quantity,
            counted_quantity=0
        )
    
    return stock_count


@transaction.atomic
def complete_stock_count(stock_count, auto_adjust=True):
    """Complete stock count and optionally adjust discrepancies."""
    if stock_count.status != 'IN_PROGRESS':
        stock_count.status = 'IN_PROGRESS'
        stock_count.save()
    
    adjustments_made = []
    
    for item in stock_count.items.all():
        if item.variance != 0 and auto_adjust:
            # Create adjustment movement
            stock, movement = adjust_stock(
                product=item.product,
                warehouse=stock_count.warehouse,
                quantity=item.variance,
                movement_type='ADJUSTMENT',
                user=stock_count.counted_by,
                reference_number=f'COUNT-{stock_count.id}',
                notes=f'Stock count adjustment: Expected {item.expected_quantity}, Counted {item.counted_quantity}'
            )
            adjustments_made.append({
                'product': item.product,
                'variance': item.variance,
                'stock': stock
            })
            
            # Update last counted date
            stock.last_counted = stock_count.count_date
            stock.save()
    
    stock_count.status = 'COMPLETED'
    stock_count.completed_at = timezone.now()
    stock_count.save()
    
    return adjustments_made


# ==================== ALERTS & MONITORING ====================

def check_stock_alerts(stock):
    """Check and create alerts for stock issues."""
    alerts_to_create = []
    
    # Low stock alert
    if stock.is_below_reorder_level and stock.quantity > 0:
        if not StockAlert.objects.filter(
            stock=stock,
            alert_type='LOW_STOCK',
            status='ACTIVE'
        ).exists():
            alerts_to_create.append(StockAlert(
                stock=stock,
                alert_type='LOW_STOCK',
                message=f'Stock level ({stock.quantity}) is below reorder level ({stock.reorder_level})'
            ))
    
    # Out of stock alert
    if stock.quantity == 0:
        if not StockAlert.objects.filter(
            stock=stock,
            alert_type='OUT_OF_STOCK',
            status='ACTIVE'
        ).exists():
            alerts_to_create.append(StockAlert(
                stock=stock,
                alert_type='OUT_OF_STOCK',
                message=f'Product is out of stock'
            ))
    
    # Negative stock error (should never happen)
    if stock.quantity < 0:
        alerts_to_create.append(StockAlert(
            stock=stock,
            alert_type='NEGATIVE_STOCK',
            message=f'CRITICAL: Negative stock detected ({stock.quantity})'
        ))
    
    if alerts_to_create:
        StockAlert.objects.bulk_create(alerts_to_create)
    
    return len(alerts_to_create)


def check_expiring_batches(days_ahead=30):
    """Check for batches expiring soon."""
    cutoff_date = timezone.now().date() + timedelta(days=days_ahead)
    expiring_batches = BatchTracking.objects.filter(
        expiry_date__lte=cutoff_date,
        expiry_date__gte=timezone.now().date(),
        quantity__gt=0
    )
    
    for batch in expiring_batches:
        stock = Stock.objects.get(product=batch.product, warehouse=batch.warehouse)
        if not StockAlert.objects.filter(
            stock=stock,
            alert_type='EXPIRING_SOON',
            status='ACTIVE'
        ).exists():
            StockAlert.objects.create(
                stock=stock,
                alert_type='EXPIRING_SOON',
                message=f'Batch {batch.batch_number} expires in {batch.days_until_expiry} days'
            )
    
    return expiring_batches


def get_reorder_suggestions():
    """Get products that need reordering across all warehouses."""
    stocks_to_reorder = Stock.objects.filter(
        quantity__lte=F('reorder_level'),
        warehouse__is_active=True
    ).select_related('product', 'warehouse')
    
    suggestions = []
    for stock in stocks_to_reorder:
        suggestions.append({
            'product': stock.product,
            'warehouse': stock.warehouse,
            'current_quantity': stock.quantity,
            'reorder_level': stock.reorder_level,
            'suggested_quantity': stock.reorder_quantity,
            'unit_cost': stock.unit_cost,
            'estimated_cost': stock.unit_cost * stock.reorder_quantity
        })
    
    return suggestions


# ==================== ANALYTICS & REPORTING ====================

def calculate_stock_turnover(product, warehouse=None, days=30):
    """Calculate stock turnover rate."""
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=days)
    
    query = StockMovement.objects.filter(
        product=product,
        movement_type='SALE',
        created_at__date__gte=start_date,
        created_at__date__lte=end_date
    )
    
    if warehouse:
        query = query.filter(warehouse=warehouse)
    
    total_sold = abs(query.aggregate(total=Sum('quantity'))['total'] or 0)
    
    if warehouse:
        current_stock = Stock.objects.get(product=product, warehouse=warehouse).quantity
    else:
        current_stock = Stock.objects.filter(product=product).aggregate(
            total=Sum('quantity')
        )['total'] or 0
    
    if current_stock == 0:
        return float('inf') if total_sold > 0 else 0
    
    turnover_rate = (total_sold / current_stock) / days
    return round(turnover_rate, 4)


def calculate_days_of_stock(product, warehouse=None, days_average=30):
    """Calculate how many days of stock remaining at current sales rate."""
    turnover = calculate_stock_turnover(product, warehouse, days_average)
    
    if turnover == 0:
        return float('inf')
    
    if warehouse:
        current_stock = Stock.objects.get(product=product, warehouse=warehouse).quantity
    else:
        current_stock = Stock.objects.filter(product=product).aggregate(
            total=Sum('quantity')
        )['total'] or 0
    
    days_remaining = current_stock / (turnover * current_stock) if turnover > 0 else float('inf')
    return round(days_remaining, 1)


def generate_daily_analytics(target_date=None):
    """Generate daily analytics for all products and warehouses."""
    if target_date is None:
        target_date = timezone.now().date() - timedelta(days=1)
    
    stocks = Stock.objects.select_related('product', 'warehouse')
    
    for stock in stocks:
        # Get movements for the day
        movements = StockMovement.objects.filter(
            product=stock.product,
            warehouse=stock.warehouse,
            created_at__date=target_date
        )
        
        received = movements.filter(movement_type='PURCHASE').aggregate(
            total=Sum('quantity')
        )['total'] or 0
        
        sold = abs(movements.filter(movement_type='SALE').aggregate(
            total=Sum('quantity')
        )['total'] or 0)
        
        adjusted = movements.filter(movement_type='ADJUSTMENT').aggregate(
            total=Sum('quantity')
        )['total'] or 0
        
        purchase_value = movements.filter(movement_type='PURCHASE').aggregate(
            total=Sum(F('quantity') * F('unit_cost'))
        )['total'] or Decimal('0.00')
        
        sales_value = abs(movements.filter(movement_type='SALE').aggregate(
            total=Sum(F('quantity') * F('unit_cost'))
        )['total'] or Decimal('0.00'))
        
        # Calculate opening stock (current stock - net change)
        net_change = received - sold + adjusted
        opening_stock = stock.quantity - net_change
        
        # Calculate turnover and days of stock
        turnover = calculate_stock_turnover(stock.product, stock.warehouse, 30)
        days_stock = calculate_days_of_stock(stock.product, stock.warehouse, 30)
        
        # Create or update analytics record
        StockAnalytics.objects.update_or_create(
            product=stock.product,
            warehouse=stock.warehouse,
            date=target_date,
            defaults={
                'opening_stock': max(0, opening_stock),
                'closing_stock': stock.quantity,
                'total_received': received,
                'total_sold': sold,
                'total_adjusted': adjusted,
                'total_purchase_value': purchase_value,
                'total_sales_value': sales_value,
                'average_unit_cost': stock.unit_cost,
                'turnover_rate': Decimal(str(turnover)),
                'days_of_stock': int(days_stock) if days_stock != float('inf') else 999
            }
        )


def get_stock_valuation_report(warehouse=None):
    """Get total stock valuation."""
    query = Stock.objects.select_related('product', 'warehouse')
    
    if warehouse:
        query = query.filter(warehouse=warehouse)
    
    stocks = query.annotate(
        value=F('quantity') * F('unit_cost')
    )
    
    total_value = stocks.aggregate(total=Sum('value'))['total'] or Decimal('0.00')
    total_quantity = stocks.aggregate(total=Sum('quantity'))['total'] or 0
    
    by_warehouse = stocks.values('warehouse__name', 'warehouse__code').annotate(
        total_value=Sum('value'),
        total_items=Sum('quantity'),
        product_count=Count('id')
    )
    
    return {
        'total_value': total_value,
        'total_quantity': total_quantity,
        'by_warehouse': list(by_warehouse),
        'stock_count': stocks.count()
    }


def get_movement_summary(start_date, end_date, warehouse=None, movement_type=None):
    """Get summary of stock movements for a period."""
    query = StockMovement.objects.filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date
    )
    
    if warehouse:
        query = query.filter(warehouse=warehouse)
    
    if movement_type:
        query = query.filter(movement_type=movement_type)
    
    summary = query.values('movement_type').annotate(
        total_quantity=Sum('quantity'),
        total_value=Sum(F('quantity') * F('unit_cost')),
        count=Count('id')
    )
    
    return list(summary)


def get_slow_moving_products(days=90, threshold=5):
    """Identify slow-moving products."""
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=days)
    
    # Get products with low sales
    slow_movers = []
    
    for stock in Stock.objects.filter(quantity__gt=0).select_related('product', 'warehouse'):
        sales = StockMovement.objects.filter(
            product=stock.product,
            warehouse=stock.warehouse,
            movement_type='SALE',
            created_at__date__gte=start_date
        ).aggregate(total=Sum('quantity'))['total'] or 0
        
        if abs(sales) <= threshold:
            slow_movers.append({
                'product': stock.product,
                'warehouse': stock.warehouse,
                'current_stock': stock.quantity,
                'units_sold': abs(sales),
                'stock_value': stock.stock_value,
                'days_analyzed': days
            })
    
    return sorted(slow_movers, key=lambda x: x['stock_value'], reverse=True)


def get_fast_moving_products(days=30, min_sales=50):
    """Identify fast-moving products."""
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=days)
    
    fast_movers = []
    
    for stock in Stock.objects.select_related('product', 'warehouse'):
        sales = StockMovement.objects.filter(
            product=stock.product,
            warehouse=stock.warehouse,
            movement_type='SALE',
            created_at__date__gte=start_date
        ).aggregate(total=Sum('quantity'))['total'] or 0
        
        if abs(sales) >= min_sales:
            turnover = calculate_stock_turnover(stock.product, stock.warehouse, days)
            fast_movers.append({
                'product': stock.product,
                'warehouse': stock.warehouse,
                'current_stock': stock.quantity,
                'units_sold': abs(sales),
                'turnover_rate': turnover,
                'days_analyzed': days
            })
    
    return sorted(fast_movers, key=lambda x: x['turnover_rate'], reverse=True)


# ==================== ABC ANALYSIS ====================

def perform_abc_analysis(warehouse=None):
    """
    Perform ABC analysis on inventory.
    A items: Top 20% of value (typically 80% of total value)
    B items: Next 30% of value (typically 15% of total value)
    C items: Bottom 50% of value (typically 5% of total value)
    """
    query = Stock.objects.select_related('product', 'warehouse').annotate(
        value=F('quantity') * F('unit_cost')
    )
    
    if warehouse:
        query = query.filter(warehouse=warehouse)
    
    # Sort by value descending
    stocks = list(query.order_by('-value'))
    total_value = sum(s.value for s in stocks)
    
    cumulative_value = 0
    results = {'A': [], 'B': [], 'C': []}
    
    for stock in stocks:
        cumulative_value += stock.value
        cumulative_percentage = (cumulative_value / total_value * 100) if total_value > 0 else 0
        
        item_data = {
            'product': stock.product,
            'warehouse': stock.warehouse,
            'quantity': stock.quantity,
            'unit_cost': stock.unit_cost,
            'total_value': stock.value,
            'cumulative_percentage': round(cumulative_percentage, 2)
        }
        
        if cumulative_percentage <= 80:
            results['A'].append(item_data)
        elif cumulative_percentage <= 95:
            results['B'].append(item_data)
        else:
            results['C'].append(item_data)
    
    return results


# ==================== PURCHASE ORDER MANAGEMENT ====================

@transaction.atomic
def receive_purchase_order(po_id, items_received, user=None):
    """
    Process receipt of purchase order items.
    
    Args:
        po_id: Purchase order ID
        items_received: List of dicts with product_id and quantity_received
        user: User processing the receipt
    
    Returns:
        dict: Summary of received items
    """
    po = PurchaseOrder.objects.get(id=po_id)
    
    if po.status not in ['APPROVED', 'SENT', 'PARTIALLY_RECEIVED']:
        raise ValidationError(f"Cannot receive items for PO in {po.status} status")
    
    received_items = []
    
    for item_data in items_received:
        po_item = po.items.get(product_id=item_data['product_id'])
        quantity = item_data['quantity_received']
        
        if po_item.quantity_pending < quantity:
            raise ValidationError(
                f"Cannot receive {quantity} units of {po_item.product.name}. "
                f"Only {po_item.quantity_pending} units pending."
            )
        
        # Receive stock
        stock, movement = receive_stock(
            product=po_item.product,
            warehouse=po.warehouse,
            quantity=quantity,
            unit_cost=po_item.unit_price,
            user=user,
            reference_number=po.po_number,
            batch_number=item_data.get('batch_number'),
            expiry_date=item_data.get('expiry_date')
        )
        
        # Update PO item
        po_item.quantity_received += quantity
        po_item.save()
        
        received_items.append({
            'product': po_item.product,
            'quantity': quantity,
            'stock': stock
        })
    
    # Update PO status
    all_received = all(item.is_fully_received for item in po.items.all())
    any_received = any(item.quantity_received > 0 for item in po.items.all())
    
    if all_received:
        po.status = 'RECEIVED'
        po.actual_delivery_date = timezone.now().date()
    elif any_received:
        po.status = 'PARTIALLY_RECEIVED'
    
    po.save()
    
    return {
        'po': po,
        'items_received': received_items,
        'fully_received': all_received
    }
