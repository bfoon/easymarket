from django.core.exceptions import ValidationError

def reduce_stock(product, quantity):
    stock = product.stock_records.first()

    if stock is None:
        raise ValidationError(f"Stock information missing for product '{product.name}'.")

    if stock.quantity < quantity:
        raise ValidationError(f"Only {stock.quantity} items available for '{product.name}'.")

    stock.quantity -= quantity
    stock.save()


