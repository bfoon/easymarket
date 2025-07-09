from .models import Cart, Wishlist, Product, Category
from django.db.models import Sum, Q

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

def wishlist_count(request):
    count = 0
    wishlist_product_ids = set()

    if request.user.is_authenticated:
        from .models import Wishlist
        wishlist_qs = Wishlist.objects.filter(user=request.user)
        count = wishlist_qs.count()
        wishlist_product_ids = set(wishlist_qs.values_list('product_id', flat=True))

    return {
        'wishlist_count': count,
        'user_wishlist_product_ids': wishlist_product_ids,
    }


def search_context(request):
    """
    Context processor to handle product search functionality
    """
    search_query = request.GET.get('q', '')
    search_results = []

    if search_query:
        # Search in product name, description, and category
        search_results = Product.objects.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(category__name__icontains=search_query)
        ).distinct()

    # Get all categories for dropdown/filter
    categories = Category.objects.all()

    return {
        'search_query': search_query,
        'search_results': search_results,
        'categories': categories,
        'search_results_count': search_results.count() if search_results else 0,
    }