from django.shortcuts import render, get_object_or_404, redirect
from .models import (Category, Product, ProductView,
                     CartItem, Cart, CelebrityFeature, Wishlist)
from chat.models import ChatThread, ChatMessage
from accounts.models import Address
from reviews.models import Review
from reviews.forms import ReviewForm
import re
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from decimal import Decimal
import json
from datetime import timedelta
from django.utils import timezone
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q, Count, F, Sum, Avg
# Create your views here!

def all_products(request):
    parent_categories = Category.objects.filter(parent__isnull=True, is_active=True)
    category_products = []

    for category in parent_categories:
        # Get all subcategories recursively
        all_subcategories = category.get_all_subcategories()
        related_category_ids = [category.id] + [sub.id for sub in all_subcategories]

        # Fetch products from parent and subcategories
        products = Product.objects.filter(
            category_id__in=related_category_ids,
            category__is_active=True
        ).order_by('?')[:8]

        if products.exists():
            category_products.append({
                'category': category,
                'products': products,
                'subcategories': all_subcategories  # Optional for template use
            })

    return render(request, 'marketplace/all_products.html', {
        'category_products': category_products
    })


def product_list(request):
    categories = Category.objects.filter(parent__isnull=True)[:6]  # Only parent categories
    products = Product.objects.all()
    featured_products = Product.objects.filter(is_featured=True)[:6]
    trending_products = Product.objects.filter(is_trending=True)

    recently_viewed = []
    similar_items = []

    # Handle logged-in user
    if request.user.is_authenticated:
        recently_viewed = Product.objects.filter(productview__user=request.user).distinct().order_by(
            '-productview__viewed_at')[:8]
    else:
        session_recently_viewed = request.session.get('recently_viewed', [])
        recently_viewed = Product.objects.filter(id__in=session_recently_viewed)

    # Similar items logic - consider main category and its subcategories
    if recently_viewed:
        last_viewed_product = recently_viewed.first()

        # Determine main category
        if last_viewed_product.category:
            main_category = last_viewed_product.category.parent or last_viewed_product.category

            # Get IDs of main category and its subcategories
            related_category_ids = [main_category.id] + list(main_category.children.values_list('id', flat=True))

            similar_items = Product.objects.filter(
                category_id__in=related_category_ids
            ).exclude(id=last_viewed_product.id)[:8]

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

    # Recommended items with annotated review stats
    recommended_items = (
        Product.objects
        .filter(category=product.category)
        .exclude(id=product.id)
        .annotate(avg_rating=Avg('reviews__rating'), review_count=Count('reviews'))
        [:4]
    )

    featured_celebrities = CelebrityFeature.objects.filter(products=product)[:8]

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
    if description_truncated:
        last_space = short_description.rfind(' ')
        if last_space != -1:
            short_description = short_description[:last_space]

    # Review data
    reviews = Review.objects.filter(product=product)
    user_review = Review.objects.filter(product=product, user=request.user).first() if request.user.is_authenticated else None
    form = ReviewForm(instance=user_review)

    avg_rating = reviews.aggregate(avg=Avg('rating'))['avg'] or 0
    review_count = reviews.count()

    user_rating = user_review.rating if user_review else 0

    # Address display
    address_display = ""
    address = None
    if request.user.is_authenticated:
        address = Address.objects.filter(user=request.user).first()
        if address:
            parts = [address.address1, address.address2, address.country]
            address_display = ', '.join(part for part in parts if part)

    # Chat messages
    messages = []
    if request.user.is_authenticated and request.user != product.seller:
        thread = ChatThread.objects.filter(participants=request.user).filter(participants=product.seller).first()
        if thread:
            messages = ChatMessage.objects.filter(thread=thread).select_related('sender').order_by('timestamp')

    return render(request, 'marketplace/product_detail.html', {
        'product': product,
        'product_images': product_images,
        'recommended_items': recommended_items,
        'specifications': cleaned_specs,
        'short_description': short_description,
        'description_truncated': description_truncated,
        'featured_celebrities': featured_celebrities,
        'messages': messages,
        'address': address,
        'address_display': address_display,
        'reviews': reviews,
        'user_review': user_review,
        'review_form': form,
        'avg_rating': round(avg_rating, 1),
        'review_count': review_count,
        'user_rating': user_rating,
        'rating_range': range(1, 6),
    })

def hot_picks(request):
    """
    Display hot picks for each parent category including products from all subcategories
    """
    parent_categories = Category.get_root_categories()  # Only active top-level categories
    hot_products_by_category = []

    for category in parent_categories:
        # Get all subcategories recursively using the model method
        all_subcategories = category.get_all_subcategories()

        # Create list of category IDs (parent + all descendants)
        related_category_ids = [category.id] + [sub.id for sub in all_subcategories]

        # Fetch featured products from parent category and all subcategories
        products = Product.objects.filter(
            category_id__in=related_category_ids,
            is_featured=True,
            category__is_active=True  # Assuming you have an is_active field on Product
        ).select_related('category').order_by('-created_at')[:8]

        if products.exists():
            hot_products_by_category.append({
                'category': category,
                'products': products,
                'subcategories': all_subcategories,  # Include subcategories for template use
                'total_categories': len(related_category_ids)  # Total categories included
            })

    return render(request, 'marketplace/hot_picks.html', {
        'hot_products_by_category': hot_products_by_category
    })

def category_products(request, slug):
    category = get_object_or_404(Category, id=slug)

    # Get IDs of the category and its subcategories
    subcategories = category.children.all()
    related_category_ids = [category.id] + list(subcategories.values_list('id', flat=True))

    # Fetch products belonging to the category and its subcategories
    products = Product.objects.filter(category_id__in=related_category_ids)

    return render(request, 'marketplace/category_products.html', {
        'category': category,
        'subcategories': subcategories,
        'products': products,
    })


def category_detail(request, pk):
    category = get_object_or_404(Category, pk=pk)

    # Get search query
    search_query = request.GET.get('q', '').strip()

    # Get sort parameter
    sort_by = request.GET.get('sort', '')

    # Get all subcategories at any depth (children, grandchildren, etc.)
    all_descendants = category.get_all_subcategories()

    # Collect category IDs: main + all descendant IDs
    related_category_ids = [category.id] + [subcat.id for subcat in all_descendants]

    # Base queryset with products in this category and all subcategories
    products_queryset = Product.objects.filter(
        category_id__in=related_category_ids,
        is_active=True  # Only show active products
    ).select_related('category', 'brand').prefetch_related('stock')

    # Apply search filter if query exists
    if search_query:
        products_queryset = products_queryset.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(brand__name__icontains=search_query) |
            Q(tags__icontains=search_query)
        ).distinct()

    # Apply sorting
    if sort_by == 'name':
        products_queryset = products_queryset.order_by('name')
    elif sort_by == '-name':
        products_queryset = products_queryset.order_by('-name')
    elif sort_by == 'price':
        products_queryset = products_queryset.order_by('price')
    elif sort_by == '-price':
        products_queryset = products_queryset.order_by('-price')
    elif sort_by == '-created_at':
        products_queryset = products_queryset.order_by('-created_at')
    elif sort_by == 'popularity':
        # Sort by review count and average rating
        products_queryset = products_queryset.annotate(
            review_count=Count('reviews'),
            avg_rating=Avg('reviews__rating')
        ).order_by('-review_count', '-avg_rating')
    else:
        # Default sorting: featured first, then by creation date
        products_queryset = products_queryset.order_by('-is_featured', '-created_at')

    # Pagination
    paginator = Paginator(products_queryset, 24)  # 24 products per page
    page = request.GET.get('page', 1)

    try:
        products = paginator.page(page)
    except PageNotAnInteger:
        products = paginator.page(1)
    except EmptyPage:
        products = paginator.page(paginator.num_pages)

    # Only direct subcategories for navigation
    subcategories = category.get_subcategories().annotate(
        product_count=Count('products', filter=Q(products__is_active=True))
    )

    # Get sibling categories if this category has a parent
    sibling_categories = None
    if category.parent:
        sibling_categories = Category.objects.filter(
            parent=category.parent,
            is_active=True
        ).annotate(
            product_count=Count('products', filter=Q(products__is_active=True))
        ).exclude(id=category.id)

    # Get related categories (categories with similar products or tags)
    related_categories = Category.objects.filter(
        is_active=True
    ).exclude(
        id__in=related_category_ids
    ).annotate(
        product_count=Count('products', filter=Q(products__is_in_stock=True))
    ).filter(
        product_count__gt=0
    )[:8]  # Limit to 8 related categories

    # Get recently viewed products from session
    recently_viewed_ids = request.session.get('recently_viewed', [])
    recently_viewed = Product.objects.filter(
        id__in=recently_viewed_ids
    )[:6] if recently_viewed_ids else None

    # Prepare context
    context = {
        'category': category,
        'products': products,
        'subcategories': subcategories,
        'sibling_categories': sibling_categories,
        'related_categories': related_categories,
        'recently_viewed': recently_viewed,
        'search_query': search_query,
        'current_sort': sort_by,
        'is_paginated': products.has_other_pages(),
        'page_obj': products,
    }

    # Add some category statistics
    total_products_in_category = Product.objects.filter(
        category_id__in=related_category_ids
    ).count()

    context['total_products'] = total_products_in_category

    # AJAX request handling for infinite scroll or dynamic loading
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # Return JSON response for AJAX requests
        products_data = []
        for product in products:
            products_data.append({
                'id': product.id,
                'name': product.name,
                'price': str(product.price),
                'image_url': product.image.url if product.image else None,
                'detail_url': product.get_absolute_url(),
                'is_in_stock': product.is_in_stock(),
                'discount_percentage': product.discount_percentage if hasattr(product, 'discount_percentage') else None,
                'is_featured': product.is_featured if hasattr(product, 'is_featured') else False,
                'is_new': product.is_new() if hasattr(product, 'is_new') else False,
                'average_rating': product.get_average_rating() if hasattr(product, 'get_average_rating') else None,
                'review_count': product.get_review_count() if hasattr(product, 'get_review_count') else 0,
            })

        return JsonResponse({
            'products': products_data,
            'has_next': products.has_next(),
            'has_previous': products.has_previous(),
            'current_page': products.number,
            'total_pages': products.paginator.num_pages,
            'total_products': products.paginator.count,
        })

    return render(request, 'marketplace/category_detail.html', context)


def category_products_ajax(request, pk):
    """
    Separate view for AJAX product loading (infinite scroll, filtering, etc.)
    """
    category = get_object_or_404(Category, pk=pk)

    # Get parameters
    page = request.GET.get('page', 1)
    search_query = request.GET.get('q', '').strip()
    sort_by = request.GET.get('sort', '')

    # Get all subcategories
    all_descendants = category.get_all_subcategories()
    related_category_ids = [category.id] + [subcat.id for subcat in all_descendants]

    # Build queryset
    products_queryset = Product.objects.filter(
        category_id__in=related_category_ids,
        is_active=True
    ).select_related('category', 'brand').prefetch_related('stock')

    # Apply search
    if search_query:
        products_queryset = products_queryset.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(brand__name__icontains=search_query)
        ).distinct()

    # Apply sorting
    if sort_by == 'name':
        products_queryset = products_queryset.order_by('name')
    elif sort_by == '-name':
        products_queryset = products_queryset.order_by('-name')
    elif sort_by == 'price':
        products_queryset = products_queryset.order_by('price')
    elif sort_by == '-price':
        products_queryset = products_queryset.order_by('-price')
    elif sort_by == '-created_at':
        products_queryset = products_queryset.order_by('-created_at')
    elif sort_by == 'popularity':
        products_queryset = products_queryset.annotate(
            review_count=Count('reviews'),
            avg_rating=Avg('reviews__rating')
        ).order_by('-review_count', '-avg_rating')
    else:
        products_queryset = products_queryset.order_by('-is_featured', '-created_at')

    # Pagination
    paginator = Paginator(products_queryset, 24)

    try:
        products = paginator.page(page)
    except (PageNotAnInteger, EmptyPage):
        products = paginator.page(1)

    # Prepare product data
    products_data = []
    for product in products:
        products_data.append({
            'id': product.id,
            'name': product.name,
            'price': str(product.price),
            'original_price': str(product.original_price) if hasattr(product,
                                                                     'original_price') and product.original_price else None,
            'image_url': product.image.url if product.image else None,
            'detail_url': product.get_absolute_url(),
            'is_in_stock': product.is_in_stock(),
            'stock_quantity': product.get_stock_quantity() if hasattr(product, 'get_stock_quantity') else 0,
            'discount_percentage': product.discount_percentage if hasattr(product, 'discount_percentage') else None,
            'is_featured': product.is_featured if hasattr(product, 'is_featured') else False,
            'is_new': product.is_new() if hasattr(product, 'is_new') else False,
            'average_rating': product.get_average_rating() if hasattr(product, 'get_average_rating') else None,
            'review_count': product.get_review_count() if hasattr(product, 'get_review_count') else 0,
            'brand': product.brand.name if hasattr(product, 'brand') and product.brand else None,
        })

    return JsonResponse({
        'success': True,
        'products': products_data,
        'pagination': {
            'has_next': products.has_next(),
            'has_previous': products.has_previous(),
            'current_page': products.number,
            'total_pages': products.paginator.num_pages,
            'total_products': products.paginator.count,
            'next_page_number': products.next_page_number() if products.has_next() else None,
            'previous_page_number': products.previous_page_number() if products.has_previous() else None,
        },
        'filters': {
            'search_query': search_query,
            'sort_by': sort_by,
        }
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


@login_required
def toggle_wishlist(request, product_id):
    product = Product.objects.filter(id=product_id).first()
    if not product:
        return JsonResponse({'success': False, 'error': 'Product not found'})

    wishlist_item, created = Wishlist.objects.get_or_create(user=request.user, product=product)

    if not created:
        # Already in wishlist → remove it
        wishlist_item.delete()
        return JsonResponse({'success': True, 'status': 'removed'})

    return JsonResponse({'success': True, 'status': 'added'})

@login_required
def my_wishlist(request):
    items = Wishlist.objects.filter(user=request.user).select_related('product')
    return render(request, 'wishlist/my_wishlist.html', {'items': items})

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