from django.db.models import Q, Sum, F
from django.urls import reverse
from .models import Cart, CartItem
from .models import Product, SearchHistory, PopularSearch  # adjust app name if needed
from decimal import Decimal
import webcolors
from PIL import Image, ImageStat
import requests
from io import BytesIO

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


class ColorUtils:

    @staticmethod
    def extract_dominant_color_from_image(image_url):
        """Extract dominant color from an image URL"""
        try:
            response = requests.get(image_url)
            img = Image.open(BytesIO(response.content))

            # Resize image for faster processing
            img = img.resize((50, 50))

            # Convert to RGB if necessary
            if img.mode != 'RGB':
                img = img.convert('RGB')

            # Get dominant color
            stat = ImageStat.Stat(img)
            dominant_color = tuple(map(int, stat.mean))

            return ColorUtils.rgb_to_hex(dominant_color)
        except Exception as e:
            print(f"Error extracting color from image: {e}")
            return None

    @staticmethod
    def rgb_to_hex(rgb_tuple):
        """Convert RGB tuple to hex color"""
        return '#{:02x}{:02x}{:02x}'.format(*rgb_tuple)

    @staticmethod
    def hex_to_rgb(hex_color):
        """Convert hex color to RGB tuple"""
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))

    @staticmethod
    def get_color_name(hex_color):
        """Get closest color name for a hex color"""
        try:
            return webcolors.hex_to_name(hex_color)
        except ValueError:
            # Find closest named color
            rgb = ColorUtils.hex_to_rgb(hex_color)
            min_colors = {}

            for key, name in webcolors.CSS3_HEX_TO_NAMES.items():
                r_c, g_c, b_c = ColorUtils.hex_to_rgb(key)
                rd = (r_c - rgb[0]) ** 2
                gd = (g_c - rgb[1]) ** 2
                bd = (b_c - rgb[2]) ** 2
                min_colors[(rd + gd + bd)] = name

            return min_colors[min(min_colors.keys())]

    @staticmethod
    def suggest_color_from_image(product_image):
        """Suggest a color name based on the product image"""
        if not product_image.image:
            return None

        try:
            dominant_hex = ColorUtils.extract_dominant_color_from_image(product_image.image.url)
            if dominant_hex:
                return ColorUtils.get_color_name(dominant_hex)
        except Exception as e:
            print(f"Error suggesting color: {e}")

        return None


def build_cart_context(request, limit=None):
    """
    Reusable cart context for full cart and mini‑cart preview.
    Adds:
      - item_type: 'db' or 'session'
      - remove_id: CartItem.id (db) OR exact session key (session)
    """
    cart_items = []
    total_price = Decimal('0.00')

    if request.user.is_authenticated:
        cart = Cart.objects.filter(user=request.user).first()
        if cart:
            # For accurate "has_more", count on full qs
            base_qs = CartItem.objects.filter(cart=cart).select_related('product').order_by('-id')
            total_items_count = base_qs.count()

            items_qs = base_qs[:limit] if limit else base_qs
            for item in items_qs:
                if not item.product:
                    continue
                subtotal = item.product.price * item.quantity
                cart_items.append({
                    'id': item.id,
                    'product': item.product,
                    'quantity': item.quantity,
                    'subtotal': subtotal,
                    'selected_features': getattr(item, 'selected_features', {}) or {},
                    'item_type': 'db',           # <-- needed by template/JS
                    'remove_id': str(item.id),   # <-- needed by template/JS
                })
                total_price += subtotal
        else:
            total_items_count = 0

    else:
        session_cart = request.session.get('cart', {})
        tmp_items = []
        product_key_map = {}

        # Group keys by product id (keys look like "123::{}" or "123::{...}")
        for key in session_cart.keys():
            try:
                pid = int(key.split("::")[0])
                product_key_map.setdefault(pid, []).append(key)
            except (ValueError, IndexError):
                continue

        product_ids = list(product_key_map.keys())
        products = {p.id: p for p in Product.objects.filter(id__in=product_ids, is_active=True)}

        for pid, keys in product_key_map.items():
            product = products.get(pid)
            if not product:
                continue
            for key in keys:
                cart_data = session_cart.get(key, {})
                quantity = cart_data.get('quantity', 1)
                selected_features = cart_data.get('selected_features', {})
                subtotal = product.price * quantity
                tmp_items.append({
                    'id': pid,  # reference only
                    'product': product,
                    'quantity': quantity,
                    'subtotal': subtotal,
                    'selected_features': selected_features,
                    'item_type': 'session',  # <-- needed
                    'remove_id': key,        # <-- exact session key; may include braces/quotes
                })

        total_items_count = len(tmp_items)
        items_iter = tmp_items[:limit] if limit else tmp_items
        for entry in items_iter:
            cart_items.append(entry)
            total_price += entry['subtotal']

    # Use the same tax rate you use elsewhere (0.15 in your earlier view)
    tax_rate = Decimal('0.0')
    tax_amount = total_price * tax_rate
    final_total = total_price + tax_amount

    cart_count = sum(i['quantity'] for i in cart_items)
    has_more = total_items_count > len(cart_items)
    remaining = max(total_items_count - len(cart_items), 0)

    return {
        'cart_items': cart_items,
        'total_price': total_price,
        'tax_amount': tax_amount,
        'final_total': final_total,
        'cart_count': cart_count,
        'has_more': has_more,
        'remaining': remaining,
        'total_items_count': total_items_count,
    }