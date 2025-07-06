from django.core.exceptions import ValidationError
from .models import Stock


def reduce_stock(product, quantity):
    """
    Reduce stock for a product by the specified quantity.
    Raises ValidationError if insufficient stock.
    """
    try:
        # Get the latest stock record for this product
        stock_record = product.stock_records.first()

        if not stock_record:
            raise ValidationError("No stock record found for this product.")

        if stock_record.quantity < quantity:
            raise ValidationError(
                f"Insufficient stock. Only {stock_record.quantity} items available."
            )

        # Reduce the stock
        stock_record.quantity -= quantity
        stock_record.save()

        return True

    except Exception as e:
        raise ValidationError(f"Failed to reduce stock: {str(e)}")


def increase_stock(product, quantity):
    """
    Increase stock for a product by the specified amount.
    Creates new stock record if none exists.
    """
    try:
        # Get existing stock record or create new one
        stock_record = product.stock_records.first()

        if stock_record:
            stock_record.quantity += quantity
            stock_record.save()
        else:
            # Create new stock record
            Stock.objects.create(product=product, quantity=quantity)

        return True

    except Exception as e:
        raise ValidationError(f"Failed to increase stock: {str(e)}")


def get_stock_quantity(product):
    """
    Get current stock quantity for a product.
    Returns 0 if no stock record exists.
    """
    stock_record = product.stock_records.first()
    return stock_record.quantity if stock_record else 0


def is_in_stock(product):
    """
    Check if product is currently in stock.
    """
    return get_stock_quantity(product) > 0


def get_stock_status(product):
    """
    Get human-readable stock status for a product.
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
    Set exact stock quantity for a product.
    Creates new stock record if none exists.
    """
    try:
        stock_record = product.stock_records.first()

        if stock_record:
            stock_record.quantity = quantity
            stock_record.save()
        else:
            Stock.objects.create(product=product, quantity=quantity)

        return True

    except Exception as e:
        raise ValidationError(f"Failed to set stock quantity: {str(e)}")


def transfer_stock(from_product, to_product, quantity):
    """
    Transfer stock from one product to another.
    """
    try:
        # Check if source product has enough stock
        if not reduce_stock(from_product, quantity):
            return False

        # Add stock to destination product
        increase_stock(to_product, quantity)

        return True

    except ValidationError:
        return False


def get_low_stock_products(threshold=5):
    """
    Get all products with stock below the specified threshold.
    """
    from marketplace.models import Product

    low_stock_products = []

    for product in Product.objects.all():
        if 0 < get_stock_quantity(product) <= threshold:
            low_stock_products.append({
                'product': product,
                'quantity': get_stock_quantity(product)
            })

    return low_stock_products


def get_out_of_stock_products():
    """
    Get all products that are completely out of stock.
    """
    from marketplace.models import Product

    out_of_stock_products = []

    for product in Product.objects.all():
        if get_stock_quantity(product) == 0:
            out_of_stock_products.append(product)

    return out_of_stock_products


def bulk_update_stock(stock_data):
    """
    Bulk update stock for multiple products.
    stock_data should be a list of dictionaries: [{'product_id': 1, 'quantity': 10}, ...]
    """
    from marketplace.models import Product

    updated_count = 0
    errors = []

    for item in stock_data:
        try:
            product = Product.objects.get(id=item['product_id'])
            set_stock_quantity(product, item['quantity'])
            updated_count += 1
        except Product.DoesNotExist:
            errors.append(f"Product with ID {item['product_id']} not found")
        except Exception as e:
            errors.append(f"Error updating product {item['product_id']}: {str(e)}")

    return {
        'updated_count': updated_count,
        'errors': errors
    }


# Management command to check stock levels
# marketplace/management/commands/check_stock.py

from django.core.management.base import BaseCommand
from stock.utils import get_low_stock_products, get_out_of_stock_products


class Command(BaseCommand):
    help = 'Check stock levels and report low/out of stock products'

    def add_arguments(self, parser):
        parser.add_argument(
            '--threshold',
            type=int,
            default=5,
            help='Low stock threshold (default: 5)'
        )

    def handle(self, *args, **options):
        threshold = options['threshold']

        # Check low stock products
        low_stock = get_low_stock_products(threshold)
        out_of_stock = get_out_of_stock_products()

        self.stdout.write(
            self.style.WARNING(f'LOW STOCK PRODUCTS (≤ {threshold}):')
        )

        if low_stock:
            for item in low_stock:
                self.stdout.write(
                    f"  • {item['product'].name}: {item['quantity']} remaining"
                )
        else:
            self.stdout.write("  No low stock products found.")

        self.stdout.write(
            self.style.ERROR('\nOUT OF STOCK PRODUCTS:')
        )

        if out_of_stock:
            for product in out_of_stock:
                self.stdout.write(f"  • {product.name}")
        else:
            self.stdout.write("  No out of stock products found.")

        self.stdout.write(
            self.style.SUCCESS(
                f'\nStock check complete. '
                f'Low stock: {len(low_stock)}, '
                f'Out of stock: {len(out_of_stock)}'
            )
        )

# Usage: python manage.py check_stock --threshold 10

