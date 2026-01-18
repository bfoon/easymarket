"""
Store Signals Module

This module handles automatic warehouse creation and stock management
for stores and products. All operations happen in the background.

Author: Store Management Team
Version: 2.0.0
"""

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.db import transaction
from django.utils import timezone
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender='stores.Store')
def create_store_warehouse(sender, instance, created, **kwargs):
    """
    Automatically create a warehouse for a new store.
    
    This runs in the background whenever a store is created.
    Ensures every store has an associated warehouse for inventory tracking.
    """
    if created:
        try:
            from stock.models import Warehouse
            
            # Generate unique warehouse code
            warehouse_code = f"STORE-{instance.id}"
            
            # Build warehouse address from store data
            warehouse_address = (
                instance.address_line_1 or 
                getattr(instance, 'address', '') or 
                "Store Location"
            )
            
            # Create the warehouse
            warehouse = Warehouse.objects.create(
                code=warehouse_code,
                name=f"{instance.name} Warehouse",
                address=warehouse_address,
                city=instance.city or '',
                state=instance.region or '',
                country=instance.country or 'Gambia',
                postal_code=instance.postal_code or '',
                manager=instance.owner,
                is_active=True,
                description=f"Automatic warehouse for {instance.name}"
            )
            
            # Link warehouse to store
            instance.warehouse = warehouse
            instance.save(update_fields=['warehouse'])
            
            logger.info(
                f"✅ Created warehouse {warehouse_code} for store '{instance.name}' (ID: {instance.id})"
            )
            
        except Exception as e:
            logger.error(
                f"❌ Failed to create warehouse for store '{instance.name}' (ID: {instance.id}): {str(e)}",
                exc_info=True
            )


@receiver(post_save, sender='marketplace.Product')
def create_product_stock(sender, instance, created, **kwargs):
    """
    Automatically create stock entry when a product is added.
    
    This runs in the background whenever a product is created.
    Links the product to the store's warehouse with initial stock of 0.
    """
    if created and hasattr(instance, 'store') and instance.store:
        try:
            from stock.models import Stock, Warehouse
            
            # Get or create store warehouse if it doesn't exist
            if not instance.store.warehouse:
                warehouse_code = f"STORE-{instance.store.id}"
                warehouse, warehouse_created = Warehouse.objects.get_or_create(
                    code=warehouse_code,
                    defaults={
                        "name": f"{instance.store.name} Warehouse",
                        "address": instance.store.address_line_1 or "Store Location",
                        "city": instance.store.city or '',
                        "state": instance.store.region or '',
                        "country": instance.store.country or 'Gambia',
                        "postal_code": instance.store.postal_code or '',
                        "manager": instance.store.owner,
                        "is_active": True,
                    }
                )
                
                if warehouse_created:
                    instance.store.warehouse = warehouse
                    instance.store.save(update_fields=['warehouse'])
                    logger.info(f"✅ Created missing warehouse for store '{instance.store.name}'")
            else:
                warehouse = instance.store.warehouse
            
            # Create stock entry for this product
            stock, stock_created = Stock.objects.get_or_create(
                product=instance,
                warehouse=warehouse,
                defaults={
                    "quantity": 0,
                    "reserved_quantity": 0,
                    "reorder_level": 10,
                    "reorder_quantity": 50,
                    "unit_cost": Decimal('0.00'),
                    "last_counted": None,
                }
            )
            
            if stock_created:
                logger.info(
                    f"✅ Created stock entry for product '{instance.name}' "
                    f"(ID: {instance.id}) in warehouse '{warehouse.code}'"
                )
            
        except Exception as e:
            logger.error(
                f"❌ Failed to create stock for product '{instance.name}' (ID: {instance.id}): {str(e)}",
                exc_info=True
            )


@receiver(pre_save, sender='marketplace.Product')
def track_product_price_changes(sender, instance, **kwargs):
    """
    Track price changes for products to notify followers.
    
    This runs before a product is saved to detect price changes.
    """
    if not instance.pk:
        # New product, skip price tracking
        return
    
    try:
        from stores.models import ProductPriceHistory
        
        # Get the old product data
        old_product = sender.objects.get(pk=instance.pk)
        
        # Check if price changed
        if old_product.price != instance.price:
            # Create price history record
            ProductPriceHistory.objects.create(
                product=instance,
                old_price=old_product.price,
                new_price=instance.price,
                changed_by=getattr(instance, '_current_user', None)
            )
            
            logger.info(
                f"📊 Price changed for '{instance.name}': "
                f"${old_product.price} → ${instance.price}"
            )
            
    except sender.DoesNotExist:
        # Product doesn't exist yet
        pass
    except Exception as e:
        logger.error(
            f"❌ Failed to track price change for product '{instance.name}': {str(e)}",
            exc_info=True
        )


def add_initial_stock(product, quantity, user=None, notes=""):
    """
    Helper function to add initial stock to a product.
    
    This should be called from views after product creation
    to add the initial stock quantity.
    
    Args:
        product: Product instance
        quantity: Initial stock quantity (int)
        user: User who added the stock (optional)
        notes: Additional notes (optional)
    
    Returns:
        tuple: (success: bool, message: str)
    """
    if quantity <= 0:
        return False, "Quantity must be greater than 0"
    
    try:
        from stock.models import Stock, StockMovement
        
        # Get the store's warehouse
        if not product.store or not product.store.warehouse:
            return False, "Product store or warehouse not found"
        
        warehouse = product.store.warehouse
        
        # Get or create stock entry
        stock, created = Stock.objects.get_or_create(
            product=product,
            warehouse=warehouse,
            defaults={
                "quantity": 0,
                "reserved_quantity": 0,
                "reorder_level": 10,
                "reorder_quantity": 50,
                "unit_cost": Decimal('0.00'),
            }
        )
        
        # Update stock quantity
        with transaction.atomic():
            stock.quantity = int(stock.quantity or 0) + quantity
            stock.updated_at = timezone.now()
            stock.save(update_fields=["quantity", "updated_at"])
            
            # Create stock movement record
            movement = StockMovement.objects.create(
                stock=stock,
                movement_type='IN',
                quantity=quantity,
                reference_number=f"INITIAL-{product.id}",
                notes=notes or f"Initial stock for new product: {product.name}",
                created_by=user
            )
            
            logger.info(
                f"✅ Added {quantity} units of stock for '{product.name}' "
                f"in warehouse '{warehouse.code}' (Movement ID: {movement.id})"
            )
        
        return True, f"Successfully added {quantity} units to stock"
        
    except Exception as e:
        error_msg = f"Failed to add initial stock: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg


def update_product_stock(product, quantity_change, movement_type='IN', 
                        reference_number='', notes='', user=None):
    """
    Update product stock (add or remove).
    
    Args:
        product: Product instance
        quantity_change: Quantity to add (positive) or remove (negative)
        movement_type: 'IN' for stock in, 'OUT' for stock out
        reference_number: Reference number for the movement
        notes: Additional notes
        user: User performing the action
    
    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        from stock.models import Stock, StockMovement
        
        if not product.store or not product.store.warehouse:
            return False, "Product store or warehouse not found"
        
        warehouse = product.store.warehouse
        
        # Get stock entry
        stock = Stock.objects.filter(
            product=product,
            warehouse=warehouse
        ).first()
        
        if not stock:
            return False, f"Stock entry not found for product '{product.name}'"
        
        # Validate quantity for OUT movements
        if movement_type == 'OUT' and abs(quantity_change) > stock.quantity:
            return False, f"Insufficient stock. Available: {stock.quantity}, Requested: {abs(quantity_change)}"
        
        # Update stock
        with transaction.atomic():
            if movement_type == 'IN':
                stock.quantity += abs(quantity_change)
            else:  # OUT
                stock.quantity -= abs(quantity_change)
            
            stock.updated_at = timezone.now()
            stock.save(update_fields=["quantity", "updated_at"])
            
            # Create movement record
            movement = StockMovement.objects.create(
                stock=stock,
                movement_type=movement_type,
                quantity=abs(quantity_change),
                reference_number=reference_number or f"MANUAL-{timezone.now().strftime('%Y%m%d%H%M%S')}",
                notes=notes,
                created_by=user
            )
            
            logger.info(
                f"✅ Stock {movement_type}: {abs(quantity_change)} units of '{product.name}' "
                f"(Movement ID: {movement.id}). New quantity: {stock.quantity}"
            )
        
        return True, f"Stock updated successfully. New quantity: {stock.quantity}"
        
    except Exception as e:
        error_msg = f"Failed to update stock: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg


def get_product_stock(product):
    """
    Get current stock quantity for a product.
    
    Args:
        product: Product instance
    
    Returns:
        int: Current stock quantity, or 0 if not found
    """
    try:
        from stock.models import Stock
        
        if not product.store or not product.store.warehouse:
            return 0
        
        stock = Stock.objects.filter(
            product=product,
            warehouse=product.store.warehouse
        ).first()
        
        return int(stock.quantity) if stock else 0
        
    except Exception as e:
        logger.error(f"Failed to get stock for product '{product.name}': {str(e)}")
        return 0
