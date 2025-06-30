from django.core.exceptions import ValidationError
from .models import Stock

def reduce_stock(product, quantity):
    """
    Deducts stock for a product. Raises ValidationError if insufficient stock.
    """
    try:
        stock = product.stock
    except Stock.DoesNotExist:
        raise ValidationError("Stock information missing for this product.")

    if stock.quantity < quantity:
        raise ValidationError(f"Insufficient stock. Only {stock.quantity} available.")

    stock.quantity -= quantity
    stock.save()
