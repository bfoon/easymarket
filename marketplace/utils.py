from django.db.models import Q
from django.urls import reverse
from .models import Cart, CartItem
from .models import Product, SearchHistory, PopularSearch  # adjust app name if needed
from decimal import Decimal

def get_client_ip(request):
    """Get client IP address from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def log_search(request, query, results_count):
    """Log search query for analytics"""
    if not query.strip():
        return

    # Log to search history
    SearchHistory.objects.create(
        user=request.user if request.user.is_authenticated else None,
        query=query,
        results_count=results_count,
        ip_address=get_client_ip(request)
    )

    # Update popular searches
    popular_search, created = PopularSearch.objects.get_or_create(
        query=query,
        defaults={'search_count': 1}
    )
    if not created:
        popular_search.search_count += 1
        popular_search.save()


def get_search_suggestions_with_history(request, query):
    """Get search suggestions including user history"""
    suggestions = []

    # Product suggestions (existing functionality)
    products = Product.objects.filter(
        Q(name__icontains=query) |
        Q(description__icontains=query) |
        Q(category__name__icontains=query)
    ).select_related('category')[:5]

    for product in products:
        suggestions.append({
            'type': 'product',
            'id': product.id,
            'name': product.name,
            'price': str(product.price),
            'category': product.category.name,
            'image': product.image.url if product.image else None,
            'url': reverse('marketplace:product_detail', kwargs={'pk': product.pk})
        })

    # Recent searches by user
    if request.user.is_authenticated:
        recent_searches = SearchHistory.objects.filter(
            user=request.user,
            query__icontains=query
        ).values_list('query', flat=True).distinct()[:3]

        for search_query in recent_searches:
            suggestions.append({
                'type': 'recent',
                'query': search_query,
                'url': reverse('marketplace:search_products') + f'?q={search_query}'
            })

    # Popular searches
    popular_searches = PopularSearch.objects.filter(
        query__icontains=query
    ).values_list('query', flat=True)[:3]

    for popular_query in popular_searches:
        suggestions.append({
            'type': 'popular',
            'query': popular_query,
            'url': reverse('marketplace:search_products') + f'?q={popular_query}'
        })

    return suggestions[:10]  # Limit total suggestions

def migrate_session_cart_to_user(request, user):
    session_cart = request.session.get('cart', {})
    if not session_cart:
        return

    cart, _ = Cart.objects.get_or_create(user=user)

    for key, item in session_cart.items():
        try:
            product_id = int(key.split("::")[0])
            product = Product.objects.get(id=product_id)
        except (ValueError, Product.DoesNotExist):
            continue

        quantity = item.get('quantity', 1)
        selected_features = item.get('selected_features', {})

        existing = CartItem.objects.filter(cart=cart, product=product, selected_features=selected_features).first()
        if existing:
            existing.quantity += quantity
            existing.save()
        else:
            CartItem.objects.create(cart=cart, product=product, quantity=quantity, selected_features=selected_features)

    request.session['cart'] = {}
    request.session.modified = True