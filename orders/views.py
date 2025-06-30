from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from stock.utils import reduce_stock
from .models import Order, OrderItem
from marketplace.models import Product

def create_order(request, product_id, quantity):
    product = get_object_or_404(Product, id=product_id)

    try:
        reduce_stock(product, quantity)
    except ValidationError as e:
        return JsonResponse({'error': str(e)}, status=400)

    order = Order.objects.create(buyer=request.user)
    OrderItem.objects.create(order=order, product=product, quantity=quantity)

    return JsonResponse({'message': 'Order placed successfully'})
