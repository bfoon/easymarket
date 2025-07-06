from django.shortcuts import render, get_object_or_404, redirect
from .models import Category, Product, ProductView, CartItem, Cart, CelebrityFeature
import re
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from decimal import Decimal
import json
from datetime import timedelta
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models import Q, Count, F, Sum
# Create your views here!

def all_products(request):
    categories = Category.objects.all()
    category_products = []

    for category in categories:
        products = Product.objects.filter(category=category).order_by('?')[:8]

        if products:
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

        if products.exists():
            hot_products_by_category.append({
                'category': category,
                'products': products
            })

    return render(request, 'marketplace/hot_picks.html', {
        'hot_products_by_category': hot_products_by_category
    })

def category_products(request, slug):
    category = get_object_or_404(Category, id=slug)
    products = Product.objects.filter(category=category)

    return render(request, 'marketplace/category_products.html', {
        'category': category,
        'products': products,
    })


def category_detail(request, pk):
    category = get_object_or_404(Category, pk=pk)
    products = Product.objects.filter(category=category)
    subcategories = category.get_subcategories()

    return render(request, 'marketplace/category_detail.html', {
        'category': category,
        'products': products,
        'subcategories': subcategories
    })

@csrf_exempt
def add_to_cart(request, product_id):
    """
    Add product to cart and return updated cart information for real-time updates
    """
    try:
        product = get_object_or_404(Product, id=product_id)
        quantity = int(request.POST.get('quantity', 1))

        if quantity < 1:
            quantity = 1
        elif quantity > 99:
            quantity = 99

        if request.user.is_authenticated:
            # Handle authenticated users
            cart, created = Cart.objects.get_or_create(user=request.user)
            cart_item, item_created = CartItem.objects.get_or_create(
                cart=cart,
                product=product,
                defaults={'quantity': 0}
            )

            if not item_created:
                cart_item.quantity += quantity
            else:
                cart_item.quantity = quantity

            # Ensure quantity doesn't exceed maximum
            if cart_item.quantity > 99:
                cart_item.quantity = 99

            cart_item.save()

            # Calculate cart totals for real-time updates
            cart_items = CartItem.objects.filter(cart=cart)
            cart_count = sum(item.quantity for item in cart_items)
            cart_total = sum(item.product.price * item.quantity for item in cart_items)

            # Calculate tax (8.5% - adjust as needed)
            tax_rate = Decimal('0.085')
            tax_amount = cart_total * tax_rate
            final_total = cart_total + tax_amount

            return JsonResponse({
                'success': True,
                'message': f'{product.name} added to cart successfully!',
                'cart_count': cart_count,
                'cart_total': f"{cart_total:.2f}",
                'tax_amount': f"{tax_amount:.2f}",
                'final_total': f"{final_total:.2f}",
                'item_quantity': cart_item.quantity,
                'item_was_updated': not item_created,
                'product_name': product.name
            })

        else:
            # Handle anonymous users with session cart
            cart = request.session.get('cart', {})
            product_key = str(product_id)

            if product_key in cart:
                cart[product_key]['quantity'] += quantity
                if cart[product_key]['quantity'] > 99:
                    cart[product_key]['quantity'] = 99
                item_was_updated = True
            else:
                cart[product_key] = {
                    'quantity': quantity,
                    'name': product.name,
                    'price': str(product.price)
                }
                item_was_updated = False

            request.session['cart'] = cart
            request.session.modified = True

            # Calculate cart totals
            cart_count = sum(item['quantity'] for item in cart.values())
            cart_total = Decimal('0')

            for pid, item in cart.items():
                try:
                    prod = Product.objects.get(id=pid)
                    cart_total += prod.price * item['quantity']
                except Product.DoesNotExist:
                    continue

            # Calculate tax
            tax_rate = Decimal('0.085')
            tax_amount = cart_total * tax_rate
            final_total = cart_total + tax_amount

            return JsonResponse({
                'success': True,
                'message': f'{product.name} added to cart successfully!',
                'cart_count': cart_count,
                'cart_total': f"{cart_total:.2f}",
                'tax_amount': f"{tax_amount:.2f}",
                'final_total': f"{final_total:.2f}",
                'item_quantity': cart[product_key]['quantity'],
                'item_was_updated': item_was_updated,
                'product_name': product.name
            })

    except ValueError:
        return JsonResponse({
            'success': False,
            'message': 'Invalid quantity specified'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error adding item to cart: {str(e)}'
        })


def cart_view(request):
    """
    Display cart with all items and totals
    """
    cart_items = []
    total_price = Decimal('0')

    if request.user.is_authenticated:
        cart = Cart.objects.filter(user=request.user).first()
        if cart:
            cart_item_qs = CartItem.objects.filter(cart=cart).select_related('product')
            for item in cart_item_qs:
                subtotal = item.product.price * item.quantity
                cart_items.append({
                    'id': item.id,  # Add item ID for frontend reference
                    'product': item.product,
                    'quantity': item.quantity,
                    'subtotal': subtotal
                })
                total_price += subtotal
    else:
        session_cart = request.session.get('cart', {})
        product_ids = session_cart.keys()
        products = Product.objects.filter(id__in=product_ids)

        for product in products:
            quantity = session_cart[str(product.id)]['quantity']
            subtotal = product.price * quantity
            cart_items.append({
                'id': product.id,  # Use product ID for session carts
                'product': product,
                'quantity': quantity,
                'subtotal': subtotal
            })
            total_price += subtotal

    # Calculate tax and final total
    tax_rate = Decimal('0.085')
    tax_amount = total_price * tax_rate
    final_total = total_price + tax_amount

    # Get cart count for badge
    cart_count = sum(item['quantity'] for item in cart_items)

    return render(request, 'marketplace/cart_detail.html', {
        'cart_items': cart_items,
        'total_price': total_price,
        'tax_amount': tax_amount,
        'final_total': final_total,
        'cart_count': cart_count,
    })


# Optional: Add this view to get current cart count for consistency
@csrf_exempt
def get_cart_count(request):
    """
    Get current cart count and total - useful for page load synchronization
    """
    try:
        if request.user.is_authenticated:
            cart = Cart.objects.filter(user=request.user).first()
            if cart:
                cart_items = CartItem.objects.filter(cart=cart)
                cart_count = sum(item.quantity for item in cart_items)
                cart_total = sum(item.product.price * item.quantity for item in cart_items)
            else:
                cart_count = 0
                cart_total = Decimal('0')
        else:
            cart = request.session.get('cart', {})
            cart_count = sum(item['quantity'] for item in cart.values())
            cart_total = Decimal('0')

            for pid, item in cart.items():
                try:
                    prod = Product.objects.get(id=pid)
                    cart_total += prod.price * item['quantity']
                except Product.DoesNotExist:
                    continue

        # Calculate tax
        tax_rate = Decimal('0.085')
        tax_amount = cart_total * tax_rate
        final_total = cart_total + tax_amount

        return JsonResponse({
            'success': True,
            'cart_count': cart_count,
            'cart_total': f"{cart_total:.2f}",
            'tax_amount': f"{tax_amount:.2f}",
            'final_total': f"{final_total:.2f}"
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error getting cart count: {str(e)}'
        })


# Helper function to get cart context for templates
def get_cart_context(request):
    """
    Helper function to get cart data for template context
    Use this in other views that need cart information
    """
    if request.user.is_authenticated:
        cart = Cart.objects.filter(user=request.user).first()
        if cart:
            cart_items = CartItem.objects.filter(cart=cart)
            cart_count = sum(item.quantity for item in cart_items)
            cart_total = sum(item.product.price * item.quantity for item in cart_items)
        else:
            cart_count = 0
            cart_total = Decimal('0')
    else:
        cart = request.session.get('cart', {})
        cart_count = sum(item['quantity'] for item in cart.values())
        cart_total = Decimal('0')

        for pid, item in cart.items():
            try:
                prod = Product.objects.get(id=pid)
                cart_total += prod.price * item['quantity']
            except Product.DoesNotExist:
                continue

    return {
        'cart_count': cart_count,
        'cart_total': cart_total
    }

@csrf_exempt
@require_POST
def update_cart_quantity(request):
    """
    Update cart item quantity - handles both direct quantity updates and increase/decrease actions
    Expects: product_id, and either 'quantity' or 'action' parameter
    """
    try:
        product_id = request.POST.get('product_id')
        quantity = request.POST.get('quantity')
        action = request.POST.get('action')  # 'increase' or 'decrease'

        if not product_id:
            return JsonResponse({
                'success': False,
                'message': 'Product ID is required'
            })

        product = get_object_or_404(Product, id=product_id)

        # Handle authenticated users
        if request.user.is_authenticated:
            cart = Cart.objects.filter(user=request.user).first()
            if not cart:
                return JsonResponse({
                    'success': False,
                    'message': 'Cart not found'
                })

            cart_item = CartItem.objects.filter(cart=cart, product=product).first()
            if not cart_item:
                return JsonResponse({
                    'success': False,
                    'message': 'Item not found in cart'
                })

            # Determine new quantity
            if quantity:
                # Direct quantity update
                new_quantity = int(quantity)
                if new_quantity < 1:
                    new_quantity = 1
                elif new_quantity > 99:
                    new_quantity = 99
                cart_item.quantity = new_quantity
            elif action:
                # Action-based update
                if action == 'increase':
                    cart_item.quantity = min(cart_item.quantity + 1, 99)
                elif action == 'decrease':
                    cart_item.quantity = max(cart_item.quantity - 1, 1)
                else:
                    return JsonResponse({
                        'success': False,
                        'message': 'Invalid action'
                    })
            else:
                return JsonResponse({
                    'success': False,
                    'message': 'Either quantity or action is required'
                })

            cart_item.save()

            # Calculate totals
            subtotal = cart_item.product.price * cart_item.quantity
            cart_items = CartItem.objects.filter(cart=cart)
            total_price = sum(item.product.price * item.quantity for item in cart_items)
            item_count = sum(item.quantity for item in cart_items)

            # Calculate tax (assuming 8.5% tax rate, adjust as needed)
            tax_rate = Decimal('0.085')
            tax_amount = total_price * tax_rate
            final_total = total_price + tax_amount

            return JsonResponse({
                'success': True,
                'quantity': cart_item.quantity,
                'subtotal': f"{subtotal:.2f}",
                'total_price': f"{total_price:.2f}",
                'tax_amount': f"{tax_amount:.2f}",
                'final_total': f"{final_total:.2f}",
                'item_count': item_count,
                'message': 'Cart updated successfully'
            })

        # Handle session-based cart for anonymous users
        else:
            cart = request.session.get('cart', {})
            product_key = str(product_id)

            if product_key not in cart:
                return JsonResponse({
                    'success': False,
                    'message': 'Item not found in cart'
                })

            # Determine new quantity
            if quantity:
                # Direct quantity update
                new_quantity = int(quantity)
                if new_quantity < 1:
                    new_quantity = 1
                elif new_quantity > 99:
                    new_quantity = 99
                cart[product_key]['quantity'] = new_quantity
            elif action:
                # Action-based update
                current_qty = cart[product_key]['quantity']
                if action == 'increase':
                    cart[product_key]['quantity'] = min(current_qty + 1, 99)
                elif action == 'decrease':
                    cart[product_key]['quantity'] = max(current_qty - 1, 1)
                else:
                    return JsonResponse({
                        'success': False,
                        'message': 'Invalid action'
                    })
            else:
                return JsonResponse({
                    'success': False,
                    'message': 'Either quantity or action is required'
                })

            request.session['cart'] = cart
            request.session.modified = True

            # Calculate totals
            quantity = cart[product_key]['quantity']
            subtotal = product.price * quantity

            total_price = Decimal('0')
            item_count = 0
            for pid, item in cart.items():
                try:
                    prod = Product.objects.get(id=pid)
                    item_total = prod.price * item['quantity']
                    total_price += item_total
                    item_count += item['quantity']
                except Product.DoesNotExist:
                    continue

            # Calculate tax
            tax_rate = Decimal('0.085')
            tax_amount = total_price * tax_rate
            final_total = total_price + tax_amount

            return JsonResponse({
                'success': True,
                'quantity': quantity,
                'subtotal': f"{subtotal:.2f}",
                'total_price': f"{total_price:.2f}",
                'tax_amount': f"{tax_amount:.2f}",
                'final_total': f"{final_total:.2f}",
                'item_count': item_count,
                'message': 'Cart updated successfully'
            })

    except ValueError as e:
        return JsonResponse({
            'success': False,
            'message': 'Invalid quantity value'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'An error occurred: {str(e)}'
        })


@csrf_exempt
@require_POST
def remove_cart_item(request):
    """
    Remove an item from the cart
    Expects: product_id
    """
    try:
        product_id = request.POST.get('product_id')

        if not product_id:
            return JsonResponse({
                'success': False,
                'message': 'Product ID is required'
            })

        product = get_object_or_404(Product, id=product_id)

        # Handle authenticated users
        if request.user.is_authenticated:
            cart = Cart.objects.filter(user=request.user).first()
            if not cart:
                return JsonResponse({
                    'success': False,
                    'message': 'Cart not found'
                })

            cart_item = CartItem.objects.filter(cart=cart, product=product).first()
            if not cart_item:
                return JsonResponse({
                    'success': False,
                    'message': 'Item not found in cart'
                })

            cart_item.delete()

            # Calculate new totals
            cart_items = CartItem.objects.filter(cart=cart)
            total_price = sum(item.product.price * item.quantity for item in cart_items)
            item_count = sum(item.quantity for item in cart_items)

            # Calculate tax
            tax_rate = Decimal('0.085')
            tax_amount = total_price * tax_rate
            final_total = total_price + tax_amount

            return JsonResponse({
                'success': True,
                'total_price': f"{total_price:.2f}",
                'tax_amount': f"{tax_amount:.2f}",
                'final_total': f"{final_total:.2f}",
                'item_count': item_count,
                'message': 'Item removed from cart'
            })

        # Handle session-based cart for anonymous users
        else:
            cart = request.session.get('cart', {})
            product_key = str(product_id)

            if product_key not in cart:
                return JsonResponse({
                    'success': False,
                    'message': 'Item not found in cart'
                })

            del cart[product_key]
            request.session['cart'] = cart
            request.session.modified = True

            # Calculate new totals
            total_price = Decimal('0')
            item_count = 0
            for pid, item in cart.items():
                try:
                    prod = Product.objects.get(id=pid)
                    item_total = prod.price * item['quantity']
                    total_price += item_total
                    item_count += item['quantity']
                except Product.DoesNotExist:
                    continue

            # Calculate tax
            tax_rate = Decimal('0.085')
            tax_amount = total_price * tax_rate
            final_total = total_price + tax_amount

            return JsonResponse({
                'success': True,
                'total_price': f"{total_price:.2f}",
                'tax_amount': f"{tax_amount:.2f}",
                'final_total': f"{final_total:.2f}",
                'item_count': item_count,
                'message': 'Item removed from cart'
            })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'An error occurred: {str(e)}'
        })


@csrf_exempt
@require_POST
def apply_promo_code(request):
    """
    Apply a promo code to the cart
    Expects: promo_code
    """
    try:
        promo_code = request.POST.get('promo_code', '').strip().upper()

        if not promo_code:
            return JsonResponse({
                'success': False,
                'message': 'Promo code is required'
            })

        # Define your promo codes here or get from database
        PROMO_CODES = {
            'SAVE10': {'discount_percent': 10, 'description': '10% off'},
            'SAVE20': {'discount_percent': 20, 'description': '20% off'},
            'WELCOME': {'discount_percent': 15, 'description': '15% off for new customers'},
            'FREESHIP': {'discount_percent': 0, 'free_shipping': True, 'description': 'Free shipping'},
        }

        if promo_code not in PROMO_CODES:
            return JsonResponse({
                'success': False,
                'message': 'Invalid promo code'
            })

        promo_data = PROMO_CODES[promo_code]

        # Calculate current cart total
        if request.user.is_authenticated:
            cart = Cart.objects.filter(user=request.user).first()
            if not cart:
                return JsonResponse({
                    'success': False,
                    'message': 'Cart is empty'
                })

            cart_items = CartItem.objects.filter(cart=cart)
            subtotal = sum(item.product.price * item.quantity for item in cart_items)
            item_count = sum(item.quantity for item in cart_items)
        else:
            cart = request.session.get('cart', {})
            if not cart:
                return JsonResponse({
                    'success': False,
                    'message': 'Cart is empty'
                })

            subtotal = Decimal('0')
            item_count = 0
            for pid, item in cart.items():
                try:
                    prod = Product.objects.get(id=pid)
                    subtotal += prod.price * item['quantity']
                    item_count += item['quantity']
                except Product.DoesNotExist:
                    continue

        # Apply discount
        discount_amount = Decimal('0')
        if 'discount_percent' in promo_data and promo_data['discount_percent'] > 0:
            discount_percent = Decimal(str(promo_data['discount_percent'])) / 100
            discount_amount = subtotal * discount_percent

        # Calculate final totals
        discounted_subtotal = subtotal - discount_amount
        tax_rate = Decimal('0.085')
        tax_amount = discounted_subtotal * tax_rate
        final_total = discounted_subtotal + tax_amount

        # Store promo code in session
        request.session['applied_promo'] = {
            'code': promo_code,
            'discount_amount': str(discount_amount),
            'discount_percent': promo_data.get('discount_percent', 0)
        }

        return JsonResponse({
            'success': True,
            'discount': f"{discount_amount:.2f}",
            'total_price': f"{discounted_subtotal:.2f}",
            'tax_amount': f"{tax_amount:.2f}",
            'final_total': f"{final_total:.2f}",
            'item_count': item_count,
            'message': f'Promo code "{promo_code}" applied successfully!'
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'An error occurred: {str(e)}'
        })

def trending_products_view(request):
    """
    Display trending products with celebrity features and sorting options
    """
    sort_by = request.GET.get('sort', 'trending')

    # Annotate products with total stock
    trending_products = Product.objects.filter(is_trending=True).annotate(
        total_stock=Sum('stock_records__quantity')
    ).filter(total_stock__gt=0)  # Only show products with stock

    # Apply sorting
    if sort_by == 'price_low':
        trending_products = trending_products.order_by('price')
    elif sort_by == 'price_high':
        trending_products = trending_products.order_by('-price')
    elif sort_by == 'newest':
        trending_products = trending_products.order_by('-created_at')
    else:
        trending_products = trending_products.order_by('-sold_count', '-created_at')

    paginator = Paginator(trending_products, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    celebrity_features = get_celebrity_features()
    trending_categories = get_trending_categories()

    context = {
        'trending_products': page_obj,
        'celebrity_features': celebrity_features,
        'trending_categories': trending_categories,
        'current_sort': sort_by,
        'page_obj': page_obj,
    }

    return render(request, 'marketplace/trending_products.html', context)


def get_celebrity_features():
    """
    Fetch active celebrity features from the database, ordered by featured_order and created_at.
    """
    return CelebrityFeature.objects.filter(is_active=True).prefetch_related('products').order_by('featured_order', '-created_at')


def get_trending_categories():
    """
    Get trending categories with mock statistics
    """
    categories = Category.objects.annotate(
        product_count=Count('product')
    ).filter(product_count__gt=0)[:4]

    # Add mock trending stats
    trending_stats = ['230%', '180%', '156%', '145%']
    icons = ['fas fa-tshirt', 'fas fa-spa', 'fas fa-mobile-alt', 'fas fa-home']
    descriptions = [
        'Celeb-inspired outfits',
        'Red carpet ready',
        'Celebrity must-haves',
        'Designer favorites'
    ]

    trending_categories = []
    for i, category in enumerate(categories):
        trending_categories.append({
            'category': category,
            'increase': trending_stats[i] if i < len(trending_stats) else '100%',
            'icon': icons[i] if i < len(icons) else 'fas fa-star',
            'description': descriptions[i] if i < len(descriptions) else 'Trending now'
        })

    return trending_categories