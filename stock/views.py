from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import Stock
import json

@require_POST
@csrf_exempt
def update_stock_quantity(request, stock_id):
    try:
        data = json.loads(request.body)
        stock = Stock.objects.get(id=stock_id)
        quantity = int(data.get('quantity', 0))

        if quantity < 0:
            return JsonResponse({'success': False, 'message': 'Invalid quantity'})

        stock.quantity = quantity
        stock.save()

        return JsonResponse({'success': True, 'quantity': stock.quantity})
    except Stock.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Stock not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})
