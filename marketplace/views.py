from django.shortcuts import render, get_object_or_404, redirect
from .models import Category, Product, ProductView, CartItem, Cart
import re
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
# Create your views here!

from marketplace.models import Product, ProductView, Category

def all_products(request):
    categories = Category.objects.all()
    category_products = []

    for category in categories:
        products = Product.objects.filter(category=category).order_by('?')[:8]  # Random order

        if products:
            # Find the actual latest product by created_at
            latest_product = Product.objects.filter(category=category).order_by('-created_at').first()

            products = list(products)
            for product in products:
                product.is_new = (product.id == latest_product.id)

            category_products.append({
                'category': category,
                'products': products
            })

    return render(request, 'marketplace/all_products.html', {
        'category_products': category_products
    })

def product_list(request):
    categories = Category.objects.all()[:6]
    products = Product.objects.all()
    featured_products = Product.objects.filter(is_featured=True)[:6]
    trending_products = Product.objects.filter(is_trending=True)

    recently_viewed = []
    similar_items = []

    # Handle logged-in user
    if request.user.is_authenticated:
        recently_viewed = Product.objects.filter(productview__user=request.user).distinct().order_by(
            '-productview__viewed_at')[:8]

    # Handle anonymous user via session
    else:
        session_recently_viewed = request.session.get('recently_viewed', [])
        recently_viewed = Product.objects.filter(id__in=session_recently_viewed)

    # Similar items logic
    if recently_viewed:
        last_viewed_product = recently_viewed.first() if request.user.is_authenticated else recently_viewed.first()
        similar_items = Product.objects.filter(category=last_viewed_product.category).exclude(
            id=last_viewed_product.id)[:8]

    return render(request, 'marketplace/product_list.html', {
        'categories': categories,
        'featured_products': featured_products,
        'trending_products': trending_products,
        'products': products,
        'recently_viewed': recently_viewed,
        'similar_items': similar_items,
    })

def product_detail(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    product_images = product.images.all()

    # Record view
    if request.user.is_authenticated:
        ProductView.objects.get_or_create(user=request.user, product=product)
    else:
        recently_viewed = request.session.get('recently_viewed', [])
        if product.id not in recently_viewed:
            recently_viewed.insert(0, product.id)
            if len(recently_viewed) > 10:
                recently_viewed = recently_viewed[:10]
            request.session['recently_viewed'] = recently_viewed

    # Recommend similar items
    recommended_items = Product.objects.filter(category=product.category).exclude(id=product.id)[:4]

    # Clean specifications
    cleaned_specs = []
    if product.specifications:
        for line in product.specifications.splitlines():
            if ':' in line:
                raw_key, value = line.split(':', 1)
                clean_key = re.sub(r'^[^a-zA-Z0-9]*(.*?)[^a-zA-Z0-9]*$', r'\1', raw_key).strip()
                cleaned_specs.append((clean_key, value.strip()))

    # Truncate description
    description_text = product.description or ""
    short_description = description_text[:800]
    description_truncated = len(description_text) > 800

    # Prevent cutting mid-word if truncated
    if description_truncated:
        last_space = short_description.rfind(' ')
        if last_space != -1:
            short_description = short_description[:last_space]

    return render(request, 'marketplace/product_detail.html', {
        'product': product,
        'product_images': product_images,
        'recommended_items': recommended_items,
        'specifications': cleaned_specs,
        'short_description': short_description,
        'description_truncated': description_truncated,
    })

def hot_picks(request):
    categories = Category.objects.all()
    hot_products_by_category = []

    for category in categories:
        products = Product.objects.filter(category=category, is_featured=True).order_by('-created_at')[:8]

        if products:
            products = list(products)
            latest_product = Product.objects.filter(category=category).order_by('-created_at').first()

            for product in products:
                # Mark latest product as 'new'
                product.is_new = product.id == latest_product.id

                # Calculate discount percentage if applicable
                if product.original_price and product.original_price > product.price:
                    discount = ((product.original_price - product.price) / product.original_price) * 100
                    product.discount_percentage = round(discount)
                else:
                    product.discount_percentage = None

            hot_products_by_category.append({
                'category': category,
                'products': products
            })

    return render(request, 'marketplace/hot_picks.html', {
        'hot_products_by_category': hot_products_by_category
    })

@csrf_exempt
def add_to_cart(request, product_id):
    product = get_object_or_404(Product, id=product_id)

    if request.user.is_authenticated:
        cart, created = Cart.objects.get_or_create(user=request.user)
        cart_item, created = CartItem.objects.get_or_create(cart=cart, product=product)

        if not created:
            cart_item.quantity += 1
        else:
            cart_item.quantity = 1

        cart_item.save()
    else:
        cart = request.session.get('cart', {})

        if str(product_id) in cart:
            cart[str(product_id)]['quantity'] += 1
        else:
            cart[str(product_id)] = {'quantity': 1}

        request.session['cart'] = cart

    return JsonResponse({'success': True, 'message': 'Added to cart successfully!'})

def cart_view(request):
    cart_items = []
    total_price = 0

    if request.user.is_authenticated:
        cart = Cart.objects.filter(user=request.user).first()
        if cart:
            cart_items = cart.items.select_related('product')
            total_price = sum(item.product.price * item.quantity for item in cart_items)
    else:
        session_cart = request.session.get('cart', {})
        product_ids = session_cart.keys()
        products = Product.objects.filter(id__in=product_ids)

        for product in products:
            quantity = session_cart[str(product.id)]['quantity']
            subtotal = product.price * quantity
            cart_items.append({
                'product': product,
                'quantity': quantity,
                'subtotal': subtotal
            })
            total_price += subtotal

    return render(request, 'marketplace/cart.html', {
        'cart_items': cart_items,
        'total_price': total_price,
    })
