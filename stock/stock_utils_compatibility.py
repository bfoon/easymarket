"""
Stock Utils Compatibility Layer

This module provides backward compatibility for old function names
that may be used in other parts of the codebase.

Add this to the END of stock/utils.py file.
"""

# ==================== BACKWARD COMPATIBILITY ====================
# Legacy function names for compatibility with existing code

def reduce_stock(product, quantity):
    """
    Legacy function - use adjust_stock() instead.
    
    Reduce stock for a product by the specified quantity.
    This is a wrapper around adjust_stock() for backward compatibility.
    
    Args:
        product: Product instance (from marketplace.models)
        quantity: Quantity to reduce (positive number)
    
    Returns:
        tuple: (Stock instance, StockMovement instance)
    
    Raises:
        ValidationError: If insufficient stock
    
    Example:
        from stock.utils import reduce_stock
        from marketplace.models import Product
        
        product = Product.objects.get(id=1)
        stock, movement = reduce_stock(product, 5)
    """
    from stock.models import Stock
    from django.core.exceptions import ValidationError
    
    # Get the product's primary warehouse stock
    # (assumes product has a store with a warehouse)
    try:
        if hasattr(product, 'store') and hasattr(product.store, 'warehouse'):
            warehouse = product.store.warehouse
        else:
            # Fallback: get first available stock record
            stock_record = Stock.objects.filter(product=product, quantity__gt=0).first()
            if not stock_record:
                raise ValidationError(f"No stock found for product: {product.name}")
            warehouse = stock_record.warehouse
        
        # Use adjust_stock with negative quantity
        return adjust_stock(
            product=product,
            warehouse=warehouse,
            quantity=-quantity,  # Negative to reduce
            movement_type='SALE',
            reference_number='',
            notes=f'Stock reduction via legacy reduce_stock function'
        )
    
    except Exception as e:
        raise ValidationError(f"Failed to reduce stock: {str(e)}")


def increase_stock(product, quantity):
    """
    Legacy function - use adjust_stock() instead.
    
    Increase stock for a product by the specified amount.
    This is a wrapper around adjust_stock() for backward compatibility.
    
    Args:
        product: Product instance
        quantity: Quantity to increase (positive number)
    
    Returns:
        tuple: (Stock instance, StockMovement instance)
    
    Example:
        from stock.utils import increase_stock
        stock, movement = increase_stock(product, 10)
    """
    from stock.models import Stock
    from django.core.exceptions import ValidationError
    
    try:
        if hasattr(product, 'store') and hasattr(product.store, 'warehouse'):
            warehouse = product.store.warehouse
        else:
            # Fallback: get first stock record or create new one
            stock_record = Stock.objects.filter(product=product).first()
            if stock_record:
                warehouse = stock_record.warehouse
            else:
                # Need to determine warehouse - raise error
                raise ValidationError(
                    f"No warehouse found for product: {product.name}. "
                    f"Please use adjust_stock() with explicit warehouse parameter."
                )
        
        return adjust_stock(
            product=product,
            warehouse=warehouse,
            quantity=quantity,  # Positive to increase
            movement_type='PURCHASE',
            reference_number='',
            notes=f'Stock increase via legacy increase_stock function'
        )
    
    except Exception as e:
        raise ValidationError(f"Failed to increase stock: {str(e)}")


def get_stock_quantity(product):
    """
    Legacy function - use Stock.objects directly.
    
    Get current stock quantity for a product across all warehouses.
    
    Args:
        product: Product instance
    
    Returns:
        int: Total quantity across all warehouses
    
    Example:
        from stock.utils import get_stock_quantity
        quantity = get_stock_quantity(product)
    """
    from stock.models import Stock
    from django.db.models import Sum
    
    total = Stock.objects.filter(product=product).aggregate(
        total=Sum('quantity')
    )['total']
    
    return total or 0


def is_in_stock(product):
    """
    Legacy function - use Stock.objects directly.
    
    Check if product is currently in stock (any warehouse).
    
    Args:
        product: Product instance
    
    Returns:
        bool: True if in stock
    
    Example:
        from stock.utils import is_in_stock
        if is_in_stock(product):
            print("Product available")
    """
    return get_stock_quantity(product) > 0


def get_stock_status(product):
    """
    Legacy function - use Stock model properties.
    
    Get human-readable stock status for a product.
    
    Args:
        product: Product instance
    
    Returns:
        str: Stock status message
    
    Example:
        from stock.utils import get_stock_status
        status = get_stock_status(product)
        print(status)  # "In Stock (45 available)"
    """
    quantity = get_stock_quantity(product)
    
    if quantity == 0:
        return "Out of Stock"
    elif quantity <= 5:
        return f"Low Stock ({quantity} remaining)"
    else:
        return f"In Stock ({quantity} available)"


def set_stock_quantity(product, quantity):
    """
    Legacy function - use adjust_stock() instead.
    
    Set exact stock quantity for a product.
    
    Args:
        product: Product instance
        quantity: Exact quantity to set
    
    Returns:
        tuple: (Stock instance, StockMovement instance)
    
    Example:
        from stock.utils import set_stock_quantity
        stock, movement = set_stock_quantity(product, 100)
    """
    from stock.models import Stock
    from django.core.exceptions import ValidationError
    
    try:
        if hasattr(product, 'store') and hasattr(product.store, 'warehouse'):
            warehouse = product.store.warehouse
        else:
            stock_record = Stock.objects.filter(product=product).first()
            if stock_record:
                warehouse = stock_record.warehouse
            else:
                raise ValidationError(
                    f"No warehouse found for product: {product.name}"
                )
        
        # Get current quantity
        stock_record = Stock.objects.filter(
            product=product,
            warehouse=warehouse
        ).first()
        
        current_qty = stock_record.quantity if stock_record else 0
        adjustment = quantity - current_qty
        
        return adjust_stock(
            product=product,
            warehouse=warehouse,
            quantity=adjustment,
            movement_type='ADJUSTMENT',
            reference_number='',
            notes=f'Stock set to {quantity} via legacy set_stock_quantity function'
        )
    
    except Exception as e:
        raise ValidationError(f"Failed to set stock quantity: {str(e)}")


# Export compatibility functions
__all__ = [
    # Main functions
    'adjust_stock',
    'receive_stock',
    'dispatch_stock',
    'transfer_stock',
    
    # Reservations
    'reserve_stock',
    'release_reservation',
    'fulfill_reservation',
    'cleanup_expired_reservations',
    
    # Stock counting
    'create_stock_count',
    'complete_stock_count',
    
    # Alerts
    'check_stock_alerts',
    'check_expiring_batches',
    'get_reorder_suggestions',
    
    # Analytics
    'calculate_stock_turnover',
    'calculate_days_of_stock',
    'generate_daily_analytics',
    'get_stock_valuation_report',
    'get_movement_summary',
    'get_slow_moving_products',
    'get_fast_moving_products',
    'perform_abc_analysis',
    
    # Purchase orders
    'receive_purchase_order',
    
    # Legacy compatibility functions
    'reduce_stock',
    'increase_stock',
    'get_stock_quantity',
    'is_in_stock',
    'get_stock_status',
    'set_stock_quantity',
]
