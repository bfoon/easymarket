from .models import Cart
from django.db.models import Sum

def cart_count(request):
    count = 0

    if request.user.is_authenticated:
        cart = Cart.objects.filter(user=request.user).first()
        if cart:
            count = cart.items.aggregate(total=Sum('quantity'))['total'] or 0
    else:
        session_cart = request.session.get('cart', {})
        count = sum(item['quantity'] for item in session_cart.values())

    return {'cart_count': count}
