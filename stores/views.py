from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q, OuterRef, Subquery, IntegerField, Value
from django.utils import timezone
from django.db import models
from datetime import datetime, timedelta
from django.urls import reverse
import calendar
import json
from django.views.decorators.http import require_http_methods
from django.http import Http404, HttpResponse
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import HttpResponseRedirect
from django.utils.text import slugify
from django.db.models import Q, Avg, F, FloatField, DecimalField, ExpressionWrapper
from django.db.models.functions import Coalesce
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST
from django.forms import modelformset_factory
from chat.models import ChatThread, ChatMessage
from django.contrib.auth import get_user_model
from marketplace.models import Product, ProductImage, ProductVariant, ProductView
from .forms import ProductForm, ProductImageForm, ProductVariantForm, ProductFeatureOption, StoreThemeForm, StoreThemePresetForm
from django.db import transaction
from accounts.models import AdminLog
import re
from decimal import Decimal, InvalidOperation
from accounts.utils import log_admin_action
from .models import Store, StoreFollow, StoreNotification, StoreFavorite, B2BInquiry
from reviews.models import Review
from marketplace.models import Product, Category, ProductImage
from orders.models import ChatMessage
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from orders.models import Order, OrderItem, PromoCode
from django.http import HttpResponseForbidden
from functools import wraps
from .forms import ProductForm, ProductImageForm
from stock.models import Warehouse, Stock, StockMovement
import csv
import threading
from django.conf import settings
from django.core.mail import send_mail
from itertools import groupby
from operator import attrgetter
from django.apps import apps

from .models import (
    Store, StoreHours, StoreShippingZone, StoreReturnSettings,
    StoreInventoryTracking, StoreMetrics, StoreReferral, PromotionPlan,
     PromotionSubscription, PromotionCampaign, PromotionPlacement, B2BCart, B2BOrder,
)
from .forms import (
    StoreSettingsForm, StoreHoursFormSet, StoreShippingZoneFormSet,
    StoreReturnSettingsForm, StoreFinancialForm, StoreReferralForm
)

from marketplace.notifications import send_email, send_whatsapp
from orders.notifications import notify_new_order_message
import logging

logger = logging.getLogger(__name__)

def notify_referrer_referral_used(referral):
    """Send notification to referrer that their referral was used."""
    subject = f"🎉 Your referral for {referral.store.name} was used!"
    message = (
        f"Hi {referral.referrer.get_full_name()},\n\n"
        f"Someone just used your referral link for {referral.store.name} on EasyMarket.\n"
        f"If they complete a purchase, you may earn a reward.\n\n"
        f"Keep referring and enjoy more benefits!\n\n"
        f"- EasyMarket Team"
    )
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [referral.referrer.email])


def notify_referrer_referral_used_async(referral):
    thread = threading.Thread(target=notify_referrer_referral_used, args=(referral,))
    thread.start()

def notify_logistics_shipment_to_warehouse(order, store, items):
    logistics_team_email = settings.LOGISTICS_EMAIL
    logistics_whatsapp = settings.LOGISTICS_PHONE

    item_list = "\n".join(
        [f"- {item.product.name} x{item.quantity}" for item in items]
    )

    msg = (
        f"📦 The store '{store.name}' has shipped items for Order #{order.id} to the warehouse.\n\n"
        f"Items:\n{item_list}\n\n"
        f"Total items: {items.count()}\n"
        f"Time: {timezone.now().strftime('%Y-%m-%d %H:%M')}"
    )

    send_email("New Shipment to Warehouse", msg, [logistics_team_email])
    send_whatsapp(logistics_whatsapp, msg)

def group_store_hours(hours):
    grouped = []
    # Prepare hours with display names
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    day_abbr = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    structured = []

    for i, h in enumerate(hours):
        structured.append({
            'day': day_abbr[i],
            'full': days[i],
            'from': h.opening_time.strftime("%H:%M") if not h.is_closed else 'Closed',
            'to': h.closing_time.strftime("%H:%M") if not h.is_closed else 'Closed',
        })

    # Group by opening and closing times
    for k, g in groupby(structured, key=lambda x: (x['from'], x['to'])):
        group = list(g)
        if len(group) == 1:
            label = group[0]['day']
        else:
            label = f"{group[0]['day']} - {group[-1]['day']}"
        grouped.append({
            'days': label,
            'from': k[0],
            'to': k[1]
        })
    return grouped

def store_owner_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, store_id, *args, **kwargs):
        store = Store.objects.filter(id=store_id).first()
        if not store:
            return HttpResponseForbidden("Store not found.")
        if request.user == store.owner or request.user.is_superuser or getattr(request.user, 'is_seller', False):
            return view_func(request, store_id, *args, **kwargs)
        return HttpResponseForbidden("You are not authorized to access this store.")
    return _wrapped_view


def validate_store_data(data, files=None):
    """Validate store data and return errors if any."""
    errors = {}

    # Required fields validation
    required_fields = ['name', 'slug', 'email']
    for field in required_fields:
        if not data.get(field) or not data.get(field).strip():
            errors[field] = f'{field.replace("_", " ").title()} is required.'

    # Email validation
    email = data.get('email')
    if email and not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        errors['email'] = 'Please enter a valid email address.'

    # Slug validation
    slug = data.get('slug')
    if slug:
        if not re.match(r'^[a-z0-9-]+$', slug):
            errors['slug'] = 'Slug can only contain lowercase letters, numbers, and hyphens.'
        if Store.objects.filter(slug=slug).exists():
            errors['slug'] = 'This slug is already taken. Please choose another.'

    # Phone validation (basic)
    phone = data.get('phone')
    if phone and not re.match(r'^[\+]?[1-9][\d\s\-\(\)]{7,15}$', phone):
        errors['phone'] = 'Please enter a valid phone number.'

    # Website validation
    website = data.get('website')
    if website and not re.match(r'^https?://', website):
        errors['website'] = 'Website URL must start with http:// or https://'

    # File validation
    if files:
        for file_field in ['logo', 'banner']:
            file_obj = files.get(file_field)
            if file_obj:
                # Check file size (2MB limit)
                if file_obj.size > 2 * 1024 * 1024:
                    errors[file_field] = f'{file_field.title()} must be less than 2MB.'

                # Check file type
                allowed_types = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
                if file_obj.content_type not in allowed_types:
                    errors[file_field] = f'{file_field.title()} must be a JPEG, PNG, GIF, or WebP image.'

    return errors


def store_list(request):
    """
    Display all stores with search and filtering functionality
    """
    search_query = request.GET.get('q', '').strip()
    category_filter = request.GET.get('category', '')
    sort_by = request.GET.get('sort', 'name')  # name, rating, products_count

    # Base queryset with annotations
    stores = Store.objects.select_related('owner').annotate(
        products_count=Count('products', distinct=True),
        avg_rating=Avg('reviews__rating')
    ).filter(status='active')

    # Search functionality
    if search_query:
        stores = stores.filter(
            Q(name__icontains=search_query) |
            Q(owner__username__icontains=search_query) |
            Q(owner__email__icontains=search_query)
        )

    # Category filtering
    if category_filter:
        stores = stores.filter(category=category_filter)

    # Sorting
    sort_options = {
        'name': 'name',
        '-name': '-name',
        'rating': '-avg_rating',
        'products': '-products_count',
        'newest': '-created_at',
        'oldest': 'created_at'
    }

    if sort_by in sort_options:
        stores = stores.order_by(sort_options[sort_by])
    else:
        stores = stores.order_by('name')

    # Get categories for filter dropdown
    categories = Store.objects.filter(status='active').values_list('category__name', flat=True).distinct()

    # Get user's favorite stores if authenticated
    user_favorites = []
    if request.user.is_authenticated:
        user_favorites = list(
            StoreFavorite.objects.filter(user=request.user)
            .values_list('store_id', flat=True)
        )

    # Pagination
    paginator = Paginator(stores, 12)  # 12 stores per page
    page_number = request.GET.get('page')
    stores_page = paginator.get_page(page_number)

    context = {
        'stores': stores_page,
        'search_query': search_query,
        'category_filter': category_filter,
        'sort_by': sort_by,
        'categories': sorted([cat for cat in categories if cat]),
        'user_favorites': user_favorites,
        'total_stores': paginator.count,
    }

    return render(request, 'stores/store_list.html', context)


@login_required
def my_favorite_stores(request):
    """
    Display user's favorite stores
    """
    search_query = request.GET.get('q', '').strip()

    # Get user's favorite stores
    favorite_stores = Store.objects.select_related('owner').annotate(
        products_count=Count('products', distinct=True),
        avg_rating=Avg('reviews__rating')
    ).filter(
        storefavorite__user=request.user,
        status='active'
    ).order_by('-storefavorite__created_at')

    # Search within favorites
    if search_query:
        favorite_stores = favorite_stores.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(category__icontains=search_query)
        )

    # Pagination
    paginator = Paginator(favorite_stores, 12)
    page_number = request.GET.get('page')
    stores_page = paginator.get_page(page_number)

    context = {
        'stores': stores_page,
        'search_query': search_query,
        'total_favorites': paginator.count,
        'is_favorites_page': True,
    }

    return render(request, 'stores/my_favorite_stores.html', context)


@login_required
@require_POST
def toggle_store_favorite(request):
    """
    AJAX endpoint to add/remove store from favorites
    """
    try:
        data = json.loads(request.body)
        store_id = data.get('store_id')

        if not store_id:
            return JsonResponse({'success': False, 'error': 'Store ID required'})

        store = get_object_or_404(Store, id=store_id, status='active')

        favorite, created = StoreFavorite.objects.get_or_create(
            user=request.user,
            store=store
        )

        if not created:
            # Remove from favorites
            favorite.delete()
            is_favorited = False
            message = f"Removed {store.name} from your favorites"
        else:
            # Added to favorites
            is_favorited = True
            message = f"Added {store.name} to your favorites"

        # Get updated favorite count for user
        favorite_count = StoreFavorite.objects.filter(user=request.user).count()

        return JsonResponse({
            'success': True,
            'is_favorited': is_favorited,
            'message': message,
            'favorite_count': favorite_count
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


def store_search_suggestions(request):
    """
    AJAX endpoint for store search suggestions
    """
    query = request.GET.get('q', '').strip()

    if len(query) < 2:
        return JsonResponse({'suggestions': []})

    stores = Store.objects.filter(
        Q(name__icontains=query) |
        Q(category__icontains=query),
        status='active'
    ).annotate(
        products_count=Count('product')
    )[:8]

    suggestions = []
    for store in stores:
        suggestions.append({
            'id': store.id,
            'name': store.name,
            'category': store.category or 'General',
            'products_count': store.products_count,
            'image': store.logo.url if store.logo else None,
            'url': f'/stores/{store.id}/',
        })

    return JsonResponse({'suggestions': suggestions})


@login_required
def get_user_store_counts(request):
    """
    API endpoint to get user's store-related counts for navbar updates
    """
    try:
        favorite_stores_count = StoreFavorite.objects.filter(user=request.user).count()

        return JsonResponse({
            'success': True,
            'favorite_stores_count': favorite_stores_count,
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@login_required
def create_store(request):
    if Store.objects.filter(owner=request.user).exists():
        messages.warning(request, 'You already own a store.')
        return redirect('stores:manage_stores')

    if request.user.is_seller == False:
        messages.error(request, 'Only buyers can create a store.')
        return redirect('marketplace:product_list')

    if request.method == 'POST':
        # Validate data
        errors = validate_store_data(request.POST, request.FILES)

        if errors:
            # Add error messages
            for field, error in errors.items():
                messages.error(request, error)
            return render(request, 'stores/create_store.html', {
                'form_data': request.POST,
                'errors': errors
            })

        try:
            # Create store
            store = Store.objects.create(
                owner=request.user,
                name=request.POST.get('name').strip(),
                slug=request.POST.get('slug').strip().lower(),
                description=request.POST.get('description', '').strip(),
                short_description=request.POST.get('short_description', '').strip(),
                email=request.POST.get('email').strip(),
                phone=request.POST.get('phone', '').strip(),
                website=request.POST.get('website', '').strip(),
                address_line_1=request.POST.get('address_line_1', '').strip(),
                address_line_2=request.POST.get('address_line_2', '').strip(),
                city=request.POST.get('city', '').strip(),
                region=request.POST.get('region', '').strip(),
                postal_code=request.POST.get('postal_code', '').strip(),
                country=request.POST.get('country', 'Gambia').strip(),
                logo=request.FILES.get('logo'),
                banner=request.FILES.get('banner'),
            )

            messages.success(request, 'Store created successfully.')
            return redirect('stores:manage_stores')

        except IntegrityError as e:
            messages.error(request, 'A store with this slug already exists.')
            return render(request, 'stores/create_store.html', {
                'form_data': request.POST,
                'errors': {'slug': 'This slug is already taken.'}
            })
        except Exception as e:
            messages.error(request, 'An error occurred while creating the store. Please try again.')
            return render(request, 'stores/create_store.html', {
                'form_data': request.POST
            })

    return render(request, 'stores/create_store.html')


@login_required
def manage_stores(request):
    stores = Store.objects.filter(owner=request.user).order_by('-created_at')
    return render(request, 'stores/manage_stores.html', {'stores': stores})


@login_required
@store_owner_required
def update_store(request, store_id):
    store = get_object_or_404(Store, id=store_id, owner=request.user)

    if request.method == 'POST':
        # Validate data (excluding slug uniqueness check for current store)
        errors = validate_store_data(request.POST, request.FILES)

        # Remove slug uniqueness error if it's the same slug
        if 'slug' in errors and request.POST.get('slug') == store.slug:
            errors.pop('slug')

        if errors:
            for field, error in errors.items():
                messages.error(request, error)
            return render(request, 'stores/update_store.html', {
                'store': store,
                'form_data': request.POST,
                'errors': errors
            })

        try:
            # Update store fields
            store.name = request.POST.get('name').strip()
            store.slug = request.POST.get('slug').strip().lower()
            store.description = request.POST.get('description', '').strip()
            store.short_description = request.POST.get('short_description', '').strip()
            store.email = request.POST.get('email').strip()
            store.phone = request.POST.get('phone', '').strip()
            store.website = request.POST.get('website', '').strip()
            store.address_line_1 = request.POST.get('address_line_1', '').strip()
            store.address_line_2 = request.POST.get('address_line_2', '').strip()
            store.city = request.POST.get('city', '').strip()
            store.region = request.POST.get('region', '').strip()
            store.postal_code = request.POST.get('postal_code', '').strip()
            store.country = request.POST.get('country', 'Gambia').strip()

            # Handle file uploads
            if request.FILES.get('logo'):
                store.logo = request.FILES.get('logo')
            if request.FILES.get('banner'):
                store.banner = request.FILES.get('banner')

            store.save()
            messages.success(request, 'Store updated successfully.')
            return redirect('stores:manage_stores')

        except IntegrityError:
            messages.error(request, 'A store with this slug already exists.')
            return render(request, 'stores/update_store.html', {
                'store': store,
                'form_data': request.POST,
                'errors': {'slug': 'This slug is already taken.'}
            })
        except Exception as e:
            messages.error(request, 'An error occurred while updating the store. Please try again.')
            return render(request, 'stores/update_store.html', {
                'store': store,
                'form_data': request.POST
            })

    return render(request, 'stores/update_store.html', {'store': store})


@login_required
@store_owner_required
def delete_store(request, store_id):
    """Delete a store (you might want to add this functionality)."""
    store = get_object_or_404(Store, id=store_id, owner=request.user)

    if request.method == 'POST':
        try:
            store_name = store.name
            store.delete()
            messages.success(request, f'Store "{store_name}" deleted successfully.')
        except Exception as e:
            messages.error(request, 'An error occurred while deleting the store.')

        return redirect('stores:manage_stores')

    return render(request, 'stores/confirm_delete.html', {'store': store})

# Store management views

@login_required
@store_owner_required
def toggle_store_status(request, store_id):
    store = get_object_or_404(Store, id=store_id, owner=request.user)
    store.is_active = not store.is_active_store
    store.save()
    status = "activated" if store.is_active_store else "deactivated"
    messages.success(request, f'Store "{store.name}" {status} successfully.')
    return redirect('stores:manage_stores')


@login_required
def add_product(request, store_id):
    """Add a product to a specific store."""
    store = get_object_or_404(Store, id=store_id, owner=request.user)

    # Get all categories for the dropdown
    categories = Category.objects.all()

    if request.method == 'POST':
        # Validate and process form data
        errors = validate_product_data(request.POST, request.FILES)

        if errors:
            # Add error messages
            for field, error in errors.items():
                messages.error(request, error)
            return render(request, 'stores/add_product.html', {
                'store': store,
                'categories': categories,
                'form_data': request.POST,
                'errors': errors
            })

        try:
            # Create the product with seller and store
            product = Product.objects.create(
                seller=request.user,
                store=store,  # ✅ Ensure store is assigned here
                name=request.POST.get('name').strip(),
                category_id=request.POST.get('category') if request.POST.get('category') else None,
                price=request.POST.get('price'),
                original_price=request.POST.get('original_price') if request.POST.get('original_price') else None,
                description=request.POST.get('description', '').strip(),
                specifications=request.POST.get('specifications', '').strip(),
                image=request.FILES.get('image'),
                video=request.FILES.get('video'),
                is_featured=bool(request.POST.get('is_featured')),
                is_trending=bool(request.POST.get('is_trending')),
                has_30_day_return=bool(request.POST.get('has_30_day_return')),
                free_shipping=bool(request.POST.get('free_shipping')),
            )

            # Set initial stock if provided
            initial_stock = request.POST.get('initial_stock')
            if initial_stock:
                try:
                    stock_quantity = int(initial_stock)
                    product.increase_stock(stock_quantity)
                except (ValueError, TypeError):
                    pass

            messages.success(request, f'Product "{product.name}" added successfully.')
            return redirect('stores:store_dashboard', store_id=store.id)

        except Exception as e:
            messages.error(request, 'An error occurred while creating the product. Please try again.')
            return render(request, 'stores/add_product.html', {
                'store': store,
                'categories': categories,
                'form_data': request.POST
            })

    return render(request, 'stores/add_product.html', {
        'store': store,
        'categories': categories
    })


def validate_product_data(data, files=None):
    """Validate product form data and return errors if any."""
    errors = {}

    # Required fields validation
    required_fields = ['name', 'price', 'description']
    for field in required_fields:
        if not data.get(field) or not data.get(field).strip():
            errors[field] = f'{field.replace("_", " ").title()} is required.'

    # Price validation
    price = data.get('price')
    if price:
        try:
            price_value = float(price)
            if price_value <= 0:
                errors['price'] = 'Price must be greater than 0.'
        except (ValueError, TypeError):
            errors['price'] = 'Please enter a valid price.'

    # Original price validation
    original_price = data.get('original_price')
    if original_price:
        try:
            original_price_value = float(original_price)
            if original_price_value <= 0:
                errors['original_price'] = 'Original price must be greater than 0.'
            elif price and float(price) >= original_price_value:
                errors['original_price'] = 'Original price must be higher than the current price.'
        except (ValueError, TypeError):
            errors['original_price'] = 'Please enter a valid original price.'

    # Initial stock validation
    initial_stock = data.get('initial_stock')
    if initial_stock:
        try:
            stock_value = int(initial_stock)
            if stock_value < 0:
                errors['initial_stock'] = 'Stock quantity cannot be negative.'
        except (ValueError, TypeError):
            errors['initial_stock'] = 'Please enter a valid stock quantity.'

    # File validation
    if files:
        # Image validation
        image_file = files.get('image')
        if image_file:
            # Check file size (5MB limit)
            if image_file.size > 5 * 1024 * 1024:
                errors['image'] = 'Image must be less than 5MB.'

            # Check file type
            allowed_image_types = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
            if image_file.content_type not in allowed_image_types:
                errors['image'] = 'Image must be a JPEG, PNG, GIF, or WebP file.'

        # Video validation
        video_file = files.get('video')
        if video_file:
            # Check file size (50MB limit)
            if video_file.size > 50 * 1024 * 1024:
                errors['video'] = 'Video must be less than 50MB.'

            # Check file type
            allowed_video_types = ['video/mp4', 'video/avi', 'video/mov', 'video/wmv']
            if video_file.content_type not in allowed_video_types:
                errors['video'] = 'Video must be an MP4, AVI, MOV, or WMV file.'

    return errors


@login_required
def manage_store_products(request, store_id):
    """Manage products for a specific store with pagination and review/sales stats."""
    store = get_object_or_404(Store, id=store_id, owner=request.user)

    # Annotate each product with review info and quantity sold
    products_list = Product.objects.filter(seller=request.user).annotate(
        total_sold=Sum('order_items__quantity')
    ).order_by('-created_at')

    # Set up pagination - 12 products per page
    paginator = Paginator(products_list, 12)
    page_number = request.GET.get('page', 1)

    try:
        products = paginator.page(page_number)
    except PageNotAnInteger:
        products = paginator.page(1)
    except EmptyPage:
        products = paginator.page(paginator.num_pages)

    total_products = products_list.count()

    context = {
        'store': store,
        'products': products,
        'total_products': total_products,
        'paginator': paginator,
        'page_obj': products,
    }

    return render(request, 'stores/manage_products.html', context)

@login_required
def store_orders(request, store_id):
    store = get_object_or_404(Store, id=store_id, owner=request.user)

    # Get all order items for products in this store
    order_items = OrderItem.objects.filter(
        product__seller=store.owner
    ).select_related('order', 'product', 'order__buyer').order_by('-order__created_at')

    # Group by order
    orders_set = {item.order for item in order_items}
    sorted_orders = sorted(orders_set, key=lambda o: o.created_at, reverse=True)

    # Apply pagination
    paginator = Paginator(sorted_orders, 15)  # 20 orders per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'stores/store_orders.html', {
        'store': store,
        'page_obj': page_obj,
    })

@login_required
def set_shipping_cost(request, store_id, order_id):
    if request.method == 'POST':
        store = get_object_or_404(Store, id=store_id, owner=request.user)
        order = get_object_or_404(Order, id=order_id)

        try:
            cost = request.POST.get('shipping_cost', '').strip()
            if cost == '':
                order.shipping_cost = Decimal('0.00')
            else:
                cost_value = Decimal(cost)
                if cost_value < 0:
                    raise ValueError("Shipping cost must be positive")
                order.shipping_cost = cost_value

            order.save()
            messages.success(request, "Shipping cost updated successfully.")
        except Exception as e:
            messages.error(request, f"Failed to update shipping cost: {e}")

        return redirect('stores:store_order_detail', store_id=store.id, order_id=order.id)

def product_detail(request, product_id):
    """
    Display detailed information about a specific product.
    """
    product = get_object_or_404(Product, id=product_id)

    # Get the seller's store (assuming one store per seller)
    try:
        seller_store = Store.objects.get(owner=product.seller, status='active')
    except Store.DoesNotExist:
        seller_store = None

    # Get related products (same category, different product)
    related_products = Product.objects.filter(
        category=product.category
    ).exclude(id=product.id).order_by('-created_at')[:8]

    # Get seller's other products
    seller_products = Product.objects.filter(
        seller=product.seller
    ).exclude(id=product.id).order_by('-created_at')[:6]

    # Get product reviews
    reviews = Review.objects.filter(product=product).order_by('-created_at')

    # Pagination for reviews
    paginator = Paginator(reviews, 5)  # Show 5 reviews per page
    page_number = request.GET.get('page')
    reviews_page = paginator.get_page(page_number)

    # Calculate review statistics
    review_stats = reviews.aggregate(
        average_rating=Avg('rating'),
        total_reviews=models.Count('id')
    )

    # Rating breakdown (1-5 stars)
    rating_breakdown = {}
    for i in range(1, 6):
        rating_breakdown[i] = reviews.filter(rating=i).count()

    # Check if user has already reviewed this product
    user_has_reviewed = False
    if request.user.is_authenticated:
        user_has_reviewed = reviews.filter(user=request.user).exists()

    # Get product images if you have multiple images
    # Assuming you might extend your model later
    product_images = [product.image] if product.image else []

    # Track product view (optional - for analytics)
    if hasattr(product, 'view_count'):
        product.view_count += 1
        product.save(update_fields=['view_count'])

    if request.user.is_authenticated:
        ProductView.objects.get_or_create(user=request.user, product=product)
        log_admin_action(
            request.user,
            action_type='product_view',
            message=f"Viewed product: {product.name}",
            model='Product',
            object_id=product.id
        )

    context = {
        'product': product,
        'seller_store': seller_store,
        'related_products': related_products,
        'seller_products': seller_products,
        'reviews': reviews_page,
        'review_stats': review_stats,
        'rating_breakdown': rating_breakdown,
        'user_has_reviewed': user_has_reviewed,
        'product_images': product_images,
        # Stock information
        'stock_quantity': product.stock_quantity,
        'is_in_stock': product.is_in_stock,
        'stock_status': product.get_stock_status(),
        # Pricing
        'discount_percentage': product.discount_percentage,
        'amount_saved': product.amount_saved,
        # Product features
        'is_new': product.is_new,
        # Breadcrumbs
        'breadcrumbs': [
            {'name': 'Home', 'url': '/'},
            {'name': product.category.name if product.category else 'Products', 'url': '#'},
            {'name': product.name, 'url': None}
        ]
    }

    return render(request, 'marketplace/product_detail.html', context)


@login_required
@require_POST
def follow_store_by_slug(request, slug):
    """
    Toggle follow/unfollow for a store using slug (for public store pages)
    This is the view that the template calls
    """
    try:
        store = get_object_or_404(Store, slug=slug, status='active')

        # Check if follow exists
        follow = StoreFollow.objects.filter(user=request.user, store=store).first()

        if follow:
            # Toggle existing follow
            follow.is_active = not follow.is_active
            follow.save()
            created = False
        else:
            # Create new follow
            follow = StoreFollow.objects.create(user=request.user, store=store, is_active=True)
            created = True

        followers_count = store.get_followers_count()

        return JsonResponse({
            'success': True,
            'status': 'success',  # Added for compatibility
            'is_following': follow.is_active,
            'following': follow.is_active,  # Added for compatibility
            'followers_count': followers_count,
            'message': f'You are now {"following" if follow.is_active else "no longer following"} {store.name}'
        })

    except Store.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Store not found.'
        }, status=404)

    except Exception as e:
        print(f"Error in follow_store_by_slug: {e}")  # Debug logging
        return JsonResponse({
            'success': False,
            'message': 'An error occurred while updating your follow status.'
        }, status=500)


# ADD THIS NEW VIEW (slug-based) - get follow status
@login_required
def get_follow_status_by_slug(request, slug):
    """Get follow status using store slug"""
    try:
        store = get_object_or_404(Store, slug=slug, status='active')

        follow = StoreFollow.objects.filter(
            user=request.user,
            store=store,
            is_active=True
        ).exists()

        return JsonResponse({
            'success': True,
            'is_following': follow,
            'followers_count': store.get_followers_count()
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)


@login_required
@require_http_methods(["POST"])
def toggle_store_follow(request, store_id):
    """Toggle follow/unfollow for a store"""
    try:
        store = get_object_or_404(Store, id=store_id)

        follow = StoreFollow.objects.filter(user=request.user, store=store).first()

        if follow:
            follow.is_active = not follow.is_active
            follow.save()
            created = False
        else:
            follow = StoreFollow.objects.create(user=request.user, store=store, is_active=True)
            created = True

        followers_count = store.get_followers_count()

        return JsonResponse({
            'success': True,
            'is_following': follow.is_active,
            'followers_count': followers_count,
            'message': f'You are now {"following" if follow.is_active else "no longer following"} {store.name}'
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': 'An error occurred while updating your follow status.'
        }, status=500)


@login_required
def get_user_notifications(request):
    """Get user's store notifications"""
    notifications = StoreNotification.objects.filter(
        user=request.user
    ).select_related('store', 'product').order_by('-created_at')

    # Pagination
    page_number = request.GET.get('page', 1)
    paginator = Paginator(notifications, 20)
    page_obj = paginator.get_page(page_number)

    notifications_data = []
    for notification in page_obj:
        notifications_data.append({
            'id': notification.id,
            'type': notification.notification_type,
            'title': notification.title,
            'message': notification.message,
            'store_name': notification.store.name,
            'store_id': notification.store.id,
            'product_name': notification.product.name if notification.product else None,
            'product_id': notification.product.id if notification.product else None,
            'old_price': str(notification.old_price) if notification.old_price else None,
            'new_price': str(notification.new_price) if notification.new_price else None,
            'created_at': notification.created_at.isoformat(),
            'is_read': notification.is_read,
            'time_ago': notification.created_at
        })

    return JsonResponse({
        'success': True,
        'notifications': notifications_data,
        'has_next': page_obj.has_next(),
        'has_previous': page_obj.has_previous(),
        'total_count': paginator.count,
        'unread_count': notifications.filter(is_read=False).count()
    })


@login_required
@require_http_methods(["POST"])
def mark_notification_read(request, notification_id):
    """Mark a notification as read"""
    try:
        notification = get_object_or_404(
            StoreNotification,
            id=notification_id,
            user=request.user
        )
        notification.is_read = True
        notification.save()

        unread_count = StoreNotification.objects.filter(
            user=request.user,
            is_read=False
        ).count()

        return JsonResponse({
            'success': True,
            'unread_count': unread_count
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': 'Failed to mark notification as read.'
        }, status=500)


@login_required
@require_http_methods(["POST"])
def mark_all_notifications_read(request):
    """Mark all notifications as read"""
    try:
        StoreNotification.objects.filter(
            user=request.user,
            is_read=False
        ).update(is_read=True)

        return JsonResponse({
            'success': True,
            'message': 'All notifications marked as read.'
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': 'Failed to mark notifications as read.'
        }, status=500)


@login_required
def get_followed_stores(request):
    """Get stores followed by the user"""
    follows = StoreFollow.objects.filter(
        user=request.user,
        is_active=True
    ).select_related('store').order_by('-followed_at')

    stores_data = []
    for follow in follows:
        store = follow.store
        stores_data.append({
            'id': store.id,
            'name': store.name,
            'slug': store.slug,
            'logo': store.logo.url if store.logo else None,
            'city': store.city,
            'country': store.country,
            'followers_count': store.get_followers_count(),
            'products_count': store.products.filter(is_active=True).count(),
            'followed_at': follow.followed_at.isoformat()
        })

    return JsonResponse({
        'success': True,
        'stores': stores_data
    })


@login_required
@require_http_methods(["GET", "POST"])
def notification_preferences(request, store_id):
    """Get or update notification preferences for a followed store"""
    try:
        store = get_object_or_404(Store, id=store_id)
        follow = get_object_or_404(StoreFollow, user=request.user, store=store, is_active=True)

        if request.method == "GET":
            return JsonResponse({
                'success': True,
                'preferences': {
                    'notify_new_products': follow.notify_new_products,
                    'notify_price_changes': follow.notify_price_changes,
                    'notify_discounts': follow.notify_discounts,
                }
            })

        # POST: update preferences
        data = json.loads(request.body)
        follow.notify_new_products = data.get('notify_new_products', True)
        follow.notify_price_changes = data.get('notify_price_changes', True)
        follow.notify_discounts = data.get('notify_discounts', True)
        follow.save()

        return JsonResponse({
            'success': True,
            'message': 'Notification preferences updated successfully.'
        })

    except StoreFollow.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Follow relationship not found.'
        }, status=404)
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'Invalid JSON.'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': 'Failed to process preferences.'
        }, status=500)



def get_store_follow_status(request, store_id):
    """Get follow status for a store (for authenticated users)"""
    store = get_object_or_404(Store, id=store_id)

    data = {
        'store_id': store.id,
        'followers_count': store.get_followers_count(),
        'is_following': False
    }

    if request.user.is_authenticated:
        data['is_following'] = store.is_followed_by(request.user)

    return JsonResponse(data)


def store_detail(request, slug):
    """
    Public store detail page with theme support.

    This view displays a store's profile page with:
    - Store information and branding
    - Products (filtered by store owner's seller account)
    - Reviews and ratings
    - Categories
    - Follow/unfollow functionality
    - Theme customization applied
    - Referral tracking
    """
    # Get the store
    store = get_object_or_404(Store, slug=slug, status='active')

    # ✅ Handle referral code tracking
    ref_code = request.GET.get('ref')
    if ref_code and hasattr(store, 'allow_referrals') and store.allow_referrals:
        # Store referral code in session
        request.session['store_referral_code'] = ref_code
        request.session['store_referral_store_id'] = str(store.id)

        # Mark referral as used
        try:
            referral = StoreReferral.objects.get(
                referral_code=ref_code,
                store=store,
                is_used=False
            )
            referral.is_used = True
            referral.save()
            notify_referrer_referral_used_async(referral)
        except StoreReferral.DoesNotExist:
            pass

    # 🛍️ Get store products
    # IMPORTANT: Products are linked to seller (User), not Store directly in marketplace
    # We filter by seller = store.owner to get all products from this store's owner
    products_queryset = Product.objects.filter(
        seller=store.owner,
        is_active=True,
        visible_in_b2c=True  # Only show B2C products on store page
    ).select_related('category', 'seller').prefetch_related('images').order_by('-created_at')

    # Get product IDs for reviews
    product_ids = products_queryset.values_list('id', flat=True)

    # 📦 Featured products (if theme setting enabled)
    featured_products = None
    if getattr(store, 'enable_featured_products', True):
        featured_products = products_queryset.filter(is_featured=True)[:8]

    # 🆕 New arrivals (if theme setting enabled)
    new_products = None
    if getattr(store, 'enable_new_arrivals', True):
        new_products = products_queryset.order_by('-created_at')[:8]

    # 🔥 Best sellers (if theme setting enabled)
    best_sellers = None
    if getattr(store, 'enable_best_sellers', True):
        # Get products with their total sold count from orders
        best_sellers = products_queryset.annotate(
            total_sold=Sum('order_items__quantity')
        ).order_by('-total_sold')[:8]

    # 📄 Pagination for main product list
    products_per_row = getattr(store, 'products_per_row', 4)
    items_per_page = products_per_row * 3  # Show 3 rows per page

    paginator = Paginator(products_queryset, items_per_page)
    page_number = request.GET.get('page', 1)
    products_page = paginator.get_page(page_number)

    # ⭐ Reviews and ratings
    reviews = Review.objects.filter(product_id__in=product_ids)
    review_count = reviews.count()
    average_rating = reviews.aggregate(avg=Avg('rating'))['avg'] or 0

    # Rating breakdown (1-5 stars)
    rating_breakdown = {i: reviews.filter(rating=i).count() for i in range(1, 6)}

    # Recent reviews for display
    recent_reviews = Review.objects.filter(
        product_id__in=product_ids
    ).select_related('user', 'product').order_by('-created_at')[:5]

    # 🏷️ Categories
    # Get unique categories from store's products
    categories = (
        Category.objects
        .filter(product__seller=store.owner, product__is_active=True)
        .annotate(product_count=Count('product'))
        .distinct()
        .order_by('name')
    )

    # ❤️ Follow status
    is_following = False
    followers_count = 0

    if request.user.is_authenticated:
        # Check if user is following this store
        from .models import StoreFollow
        is_following = StoreFollow.objects.filter(
            user=request.user,
            store=store,
            is_active=True
        ).exists()

    # Get followers count
    if hasattr(store, 'followers'):
        followers_count = store.followers.filter(is_active=True).count()
    elif hasattr(store, 'get_followers_count'):
        followers_count = store.get_followers_count()

    # 🕒 Store hours (grouped for better display)
    store_hours = None
    grouped_hours = []

    if hasattr(store, 'hours'):
        store_hours = store.hours.order_by('day_of_week')
        grouped_hours = group_store_hours(store_hours)

    # 📊 Store statistics
    products_count = products_queryset.count()

    # 🎨 Theme configuration
    # Get theme-related data if available, with fallbacks
    theme_colors = getattr(store, 'get_theme_colors', lambda: {
        'primary': '#2563eb',
        'secondary': '#64748b',
        'accent': '#f59e0b',
        'background': '#ffffff',
        'text': '#1e293b',
    })()

    font_urls = getattr(store, 'get_font_urls', lambda: None)()
    enable_animations = getattr(store, 'enable_animations', True)
    enable_lazy_loading = getattr(store, 'enable_lazy_loading', True)

    # 📦 Context for template
    context = {
        'store': store,
        'products': products_page,
        'featured_products': featured_products,
        'new_products': new_products,
        'best_sellers': best_sellers,
        'products_count': products_count,

        # Reviews & Ratings
        'review_count': review_count,
        'average_rating': round(average_rating, 1),
        'rating_breakdown': rating_breakdown,
        'rating_order': [5, 4, 3, 2, 1],  # For template iteration
        'recent_reviews': recent_reviews,

        # Categories
        'categories': categories,

        # Social & Following
        'is_following': is_following,
        'followers_count': followers_count,

        # Store Hours
        'grouped_hours': grouped_hours,
        'store_hours': store_hours,

        # Theme & Customization
        'theme_colors': theme_colors,
        'font_urls': font_urls,
        'enable_animations': enable_animations,
        'enable_lazy_loading': enable_lazy_loading,

        # Additional theme settings (with safe fallbacks)
        'show_product_ratings': getattr(store, 'show_product_ratings', True),
        'show_product_badges': getattr(store, 'show_product_badges', True),
        'show_quick_view': getattr(store, 'show_quick_view', True),
        'show_store_description': getattr(store, 'show_store_description', True),
        'show_store_stats': getattr(store, 'show_store_stats', True),
        'show_social_links': getattr(store, 'show_social_links', True),
        'show_operating_hours': getattr(store, 'show_operating_hours', True),
        'product_layout': getattr(store, 'product_layout', 'grid'),
        'products_per_row': products_per_row,
    }

    return render(request, 'stores/store_detail.html', context)


def store_products(request, slug):
    """
    Dedicated products page for a store with filtering and sorting
    """
    store = get_object_or_404(Store, slug=slug, status='active')

    # Get all store products
    products = Product.objects.filter(
        seller=store.owner,
        is_active=True,
        visible_in_b2c=True
    ).select_related('category', 'seller').prefetch_related('images')

    # Filter by category if specified
    category_id = request.GET.get('category')
    if category_id:
        products = products.filter(category_id=category_id)

    # Search
    search_query = request.GET.get('q')
    if search_query:
        products = products.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    # Sorting
    sort_by = request.GET.get('sort', '-created_at')
    valid_sorts = {
        'price_low': 'price',
        'price_high': '-price',
        'name': 'name',
        'newest': '-created_at',
        'popular': '-sold_count',
        'rating': '-average_rating',
    }

    if sort_by in valid_sorts:
        products = products.order_by(valid_sorts[sort_by])
    else:
        products = products.order_by('-created_at')

    # Price range filter
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    if min_price:
        products = products.filter(price__gte=min_price)
    if max_price:
        products = products.filter(price__lte=max_price)

    # Pagination
    products_per_row = getattr(store, 'products_per_row', 4)
    items_per_page = products_per_row * 4  # 4 rows

    paginator = Paginator(products, items_per_page)
    page_number = request.GET.get('page', 1)
    products_page = paginator.get_page(page_number)

    # Categories for filter
    categories = Category.objects.filter(
        product__seller=store.owner,
        product__is_active=True
    ).annotate(
        product_count=Count('product')
    ).distinct().order_by('name')

    context = {
        'store': store,
        'products': products_page,
        'categories': categories,
        'search_query': search_query,
        'current_category': category_id,
        'current_sort': sort_by,
        'min_price': min_price,
        'max_price': max_price,

        # Theme
        'theme_colors': getattr(store, 'get_theme_colors', lambda: {})(),
        'font_urls': getattr(store, 'get_font_urls', lambda: None)(),
    }

    return render(request, 'stores/store_products.html', context)


# @login_required
# def manage_store_products(request, store_id):
#     """Display all products for a specific store"""
#     store = get_object_or_404(Store, id=store_id, owner=request.user)
#     products = Product.objects.filter(store=store).order_by('-created_at')
#
#     context = {
#         'store': store,
#         'products': products,
#     }
#     return render(request, 'stores/manage_products.html', context)
@login_required
def edit_product(request, store_id, product_id):
    store = get_object_or_404(Store, id=store_id, owner=request.user)
    product = get_object_or_404(Product, id=product_id, seller=request.user)
    stock, _ = Stock.objects.get_or_create(product=product)

    ImageFormSet = modelformset_factory(ProductImage, form=ProductImageForm, extra=3, can_delete=False)

    if request.method == 'POST':
        product_form = ProductForm(request.POST, request.FILES, instance=product)
        image_formset = ImageFormSet(request.POST, request.FILES, queryset=ProductImage.objects.none())
        stock_quantity = request.POST.get('stock_quantity')

        # Get selected variants from the dual listbox
        selected_variant_ids = request.POST.getlist('selected_variants[]')

        original = Product.objects.get(pk=product.pk)
        changed_fields = []
        field_diffs = []

        for field in [
            'name', 'price', 'original_price', 'description', 'specifications',
            'is_active', 'used', 'is_featured', 'is_trending', 'has_30_day_return', 'free_shipping'
        ]:
            old = getattr(original, field)
            new = request.POST.get(field)

            if isinstance(old, bool):
                new = field in request.POST
            elif isinstance(old, Decimal):
                try:
                    new = Decimal(new) if new else None
                except:
                    continue

            if old != new:
                changed_fields.append(field)
                field_diffs.append(f"{field}: '{old}' → '{new}'")

        product._changed_fields = changed_fields
        product._log_user = request.user

        # Handle promo code removals
        for promo in product.promo_codes.all():
            if request.POST.get(f'remove_promo_{promo.id}'):
                product.promo_codes.remove(promo)
                AdminLog.objects.create(
                    action_type='promo_remove',
                    related_model='PromoCode',
                    related_object_id=str(promo.id),
                    message=f"Promo '{promo.code}' removed from product '{product.name}'",
                    created_by=request.user
                )

        # Assign existing promo
        existing_promo_id = request.POST.get('existing_promo')
        if existing_promo_id:
            try:
                promo = PromoCode.objects.get(id=existing_promo_id)
                promo.products.add(product)
                AdminLog.objects.create(
                    action_type='promo_add',
                    related_model='PromoCode',
                    related_object_id=str(promo.id),
                    message=f"Promo '{promo.code}' assigned to product '{product.name}'",
                    created_by=request.user
                )
            except PromoCode.DoesNotExist:
                pass

        # Create new promo
        new_code = request.POST.get('promo_code')
        new_discount = request.POST.get('promo_discount')
        if new_code and new_discount:
            try:
                promo = PromoCode.objects.create(
                    code=new_code.strip(),
                    discount_percentage=int(new_discount),
                    is_active=True
                )
                promo.products.add(product)
                AdminLog.objects.create(
                    action_type='promo_create',
                    related_model='PromoCode',
                    related_object_id=str(promo.id),
                    message=f"New promo '{promo.code}' created and linked to '{product.name}'",
                    created_by=request.user
                )
            except (ValueError, TypeError):
                messages.error(request, 'Invalid discount percentage')

        if product_form.is_valid() and image_formset.is_valid():
            with transaction.atomic():
                # Save the old price before updating
                old_price = product.price

                product = product_form.save(commit=False)
                product._log_user = request.user
                product.is_active = 'is_active' in request.POST
                product.used = 'used' in request.POST
                product.save()

                if field_diffs:
                    AdminLog.objects.create(
                        action_type='product_edit',
                        related_model='Product',
                        related_object_id=str(product.id),
                        message=f"Updated product '{product.name}':\n" + "\n".join(field_diffs),
                        created_by=request.user
                    )

                # Stock update
                if stock_quantity and stock_quantity.isdigit():
                    old_quantity = stock.quantity
                    new_quantity = int(stock_quantity)
                    if old_quantity != new_quantity:
                        AdminLog.objects.create(
                            action_type='stock_update',
                            related_model='Stock',
                            related_object_id=str(stock.id),
                            message=f"Stock for '{product.name}' updated: {old_quantity} → {new_quantity}",
                            created_by=request.user
                        )
                        stock.quantity = new_quantity
                        stock.save()

                # Save product images
                for form in image_formset:
                    if form.is_valid() and form.cleaned_data:
                        image_file = form.cleaned_data.get('image')
                        if image_file:
                            image = form.save(commit=False)
                            image.product = product
                            image.save()

                # Handle image variant assignments and updates
                handle_image_variant_assignments(request, product)

                # Handle variant updates with dual listbox data
                # Track current variants before changes
                old_variants = set(
                    ProductVariant.objects.filter(product=product)
                    .select_related('feature_option__feature')
                    .values_list('feature_option__value', flat=True)
                )

                # Clear existing variants
                ProductVariant.objects.filter(product=product).delete()

                # Create new variants from selected IDs
                new_variants = set()
                variant_names = []

                for variant_id in selected_variant_ids:
                    try:
                        feature_option = ProductFeatureOption.objects.get(id=variant_id)
                        ProductVariant.objects.get_or_create(
                            product=product,
                            feature_option=feature_option
                        )
                        new_variants.add(feature_option.value)
                        variant_names.append(f"{feature_option.feature.name}: {feature_option.value}")
                    except ProductFeatureOption.DoesNotExist:
                        continue

                # Log variant changes if there are any
                if old_variants != new_variants:
                    added = new_variants - old_variants
                    removed = old_variants - new_variants
                    msg_parts = []

                    if added:
                        msg_parts.append(f"Added: {', '.join(sorted(added))}")
                    if removed:
                        msg_parts.append(f"Removed: {', '.join(sorted(removed))}")

                    if msg_parts:
                        AdminLog.objects.create(
                            action_type='variant_update',
                            related_model='ProductVariant',
                            related_object_id=str(product.id),
                            message=f"Variants updated for product '{product.name}'. {' | '.join(msg_parts)}",
                            created_by=request.user
                        )

                # Note: Price change notification is now handled automatically in the Product.save() method
                # No need to manually call notify_followers here

                messages.success(request, f'Product updated successfully! {len(variant_names)} variants selected.')
                return redirect('stores:manage_store_products', store_id=store.id)
        else:
            # Handle form errors
            error_messages = []
            if not product_form.is_valid():
                error_messages.append(f'Product form errors: {dict(product_form.errors)}')
            if not image_formset.is_valid():
                error_messages.append(f'Image formset errors: {image_formset.errors}')

            for error in error_messages:
                messages.error(request, error)

    else:
        # GET request - initialize forms
        product_form = ProductForm(instance=product)
        image_formset = ImageFormSet(queryset=ProductImage.objects.none())

    # Prepare boolean fields for template
    boolean_fields = [
        {"field": product_form['is_featured'], "icon": "fa-star", "text": "Featured Product", "color": "warning"},
        {"field": product_form['is_trending'], "icon": "fa-fire", "text": "Trending Product", "color": "danger"},
        {"field": product_form['has_30_day_return'], "icon": "fa-undo", "text": "30-Day Return", "color": "info"},
        {"field": product_form['free_shipping'], "icon": "fa-shipping-fast", "text": "Free Shipping",
         "color": "success"},
    ]

    # Get all available feature options for the dual listbox
    all_feature_options = ProductFeatureOption.objects.select_related('feature').all().order_by('feature__name',
                                                                                                'value')

    # Get all active promo codes
    all_promos = PromoCode.objects.filter(is_active=True)

    context = {
        'store': store,
        'product': product,
        'product_form': product_form,
        'image_formset': image_formset,
        'boolean_fields': boolean_fields,
        'all_promos': all_promos,
        'all_feature_options': all_feature_options,  # For dual listbox
        'stock_quantity': stock.quantity,
    }

    return render(request, 'stores/edit_product.html', context)


def handle_image_variant_assignments(request, product):
    """Handle variant assignments for existing images only"""
    import json

    # Handle existing image variant updates
    for image in product.images.all():
        # Get variant assignments for this image
        variant_field_name = f'image_{image.id}_variants'
        selected_variants = request.POST.getlist(variant_field_name)

        # Update variants for this image
        if selected_variants:
            variant_objects = ProductFeatureOption.objects.filter(id__in=selected_variants)
            image.variants.set(variant_objects)
        else:
            image.variants.clear()

        # Handle primary image setting
        is_primary_field = f'image_{image.id}_primary'
        image.is_primary = is_primary_field in request.POST

        if image.is_primary:
            # Ensure only one primary image per variant combination
            image.set_as_primary_for_variants()

        image.save()

    # Note: New images will need to have variants assigned manually after upload
    # since we simplified the interface to only show 3 upload slots without variant assignment


@login_required
@require_http_methods(["POST"])
def delete_product_image(request, store_id, product_id, image_id):
    """View to delete a product image"""
    try:
        store = get_object_or_404(Store, id=store_id, owner=request.user)
        product = get_object_or_404(Product, id=product_id, seller=request.user)
        image = get_object_or_404(ProductImage, id=image_id, product=product)

        image_name = str(image)
        image.delete()

        AdminLog.objects.create(
            action_type='image_delete',
            related_model='ProductImage',
            related_object_id=str(image_id),
            message=f"Deleted image: {image_name}",
            created_by=request.user
        )

        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
@require_POST
def delete_product(request, store_id, product_id):
    """Delete a product via AJAX call."""

    try:
        store = get_object_or_404(Store, id=store_id, owner=request.user)
        product = get_object_or_404(Product, id=product_id, seller=request.user)

        if product.seller != request.user or product.seller != store.owner:
            return JsonResponse({'success': False, 'message': 'Unauthorized to delete this product.'}, status=403)

        product_name = product.name
        product.delete()

        return JsonResponse({
            'success': True,
            'message': f'Product "{product_name}" was deleted successfully.'
        })

    except Product.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Product not found.'}, status=404)

    except Exception as e:
        # Optional: log the error if needed
        print(f"Error deleting product: {e}")
        return JsonResponse({'success': False, 'message': 'Server error occurred.'}, status=500)

@login_required
@require_POST
def delete_product_image(request, store_id, product_id, image_id):
    """Delete a product image via AJAX request."""
    try:
        store = get_object_or_404(Store, id=store_id, owner=request.user)
        product = get_object_or_404(Product, id=product_id, seller=store.owner)

        # Ensure the image belongs to this product
        image = get_object_or_404(ProductImage, id=image_id, product=product)

        image.delete()

        return JsonResponse({
            'success': True,
            'message': 'Image deleted successfully.'
        })

    except ProductImage.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Image not found.'
        }, status=404)

    except Exception as e:
        print(f"Image deletion error: {e}")  # optional logging
        return JsonResponse({
            'success': False,
            'message': 'An error occurred while deleting the image.'
        }, status=500)


@login_required
@store_owner_required
def toggle_store_status(request, store_id):
    """Toggle store active/inactive status."""
    store = get_object_or_404(Store, id=store_id, owner=request.user)

    if request.method == 'POST':
        # Fix: Use store.status, not store.is_active or store.is_active_store
        if store.status == 'active':
            store.status = 'inactive'
            messages.success(request, f'Store "{store.name}" has been deactivated.')
        else:
            store.status = 'active'
            messages.success(request, f'Store "{store.name}" has been activated.')

        store.save()

    return redirect('stores:manage_stores')

@login_required
@require_http_methods(["GET", "POST"])
def store_order_detail(request, store_id, order_id):
    store = get_object_or_404(Store, id=store_id, owner=request.user)
    order = get_object_or_404(Order, id=order_id)

    # Get order items related to this store
    store_order_items = order.items.filter(product__seller=store.owner).select_related('product')

    if not store_order_items.exists():
        raise Http404("No items in this order belong to your store.")

    # Capture "ship to warehouse" action
    if request.method == "POST" and 'ship_to_warehouse' in request.POST:
        store_order_items.update(shipped_to_warehouse=True, shipped_at=timezone.now())

        try:
            notify_logistics_shipment_to_warehouse(order, store, store_order_items)
        except Exception as e:
            print("Failed to notify logistics:", e)

        messages.success(request, "Items marked as shipped to warehouse.")

    # Calculate subtotal
    subtotal_qs = store_order_items.annotate(
        item_total=ExpressionWrapper(
            F('product__price') * F('quantity'),
            output_field=DecimalField()
        )
    ).aggregate(total=Sum('item_total'))
    subtotal = subtotal_qs['total'] or 0

    context = {
        'store': store,
        'order': order,
        'order_items': store_order_items,
        'buyer': order.buyer,
        'store_subtotal': subtotal,
    }
    return render(request, 'stores/store_order_detail.html', context)

@require_POST
@login_required
def update_order_status(request, order_id):
    try:
        order = Order.objects.get(id=order_id)
        store = Store.objects.get(owner=request.user)

        # Filter only the order items belonging to this store
        order_items = order.items.filter(product__seller=store.owner)

        if not order_items.exists():
            return JsonResponse({'success': False, 'message': 'No items for your store in this order.'})

        # Update each item to be marked as shipped to warehouse
        order_items.update(shipped_to_warehouse=True)

        return JsonResponse({'success': True})

    except Order.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Order not found.'})
    except Store.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Store not found.'})

User = get_user_model()

@login_required
def start_store_chat(request, store_id, buyer_id, order_id=None):
    """
    Allows store owner to initiate chat with a buyer from the order view.
    """
    store = get_object_or_404(Store, id=store_id, owner=request.user)
    buyer = get_object_or_404(User, id=buyer_id)

    if buyer == request.user:
        return redirect('stores:store_dashboard', store_id=store.id)

    # Create or get chat thread
    thread, _ = ChatThread.objects.get_or_create_between(request.user, buyer)

    # Optional: create message if submitted
    if request.method == 'POST':
        message = request.POST.get('message', '').strip()
        if message:
            ChatMessage.objects.create(
                thread=thread,
                sender=request.user,
                message=message
            )
        if order_id:
            return redirect('stores:store_order_detail', store_id=store.id, order_id=order_id)
        return redirect('stores:store_dashboard', store_id=store.id)

    # Default fallback
    return redirect('stores:store_dashboard', store_id=store.id)

@login_required
def store_chat_panel(request, store_id):
    store = get_object_or_404(Store, id=store_id)

    # Permission (adjust as needed)
    is_owner = getattr(store, "owner_id", None) == request.user.id
    if not (is_owner or request.user.is_superuser):
        raise PermissionDenied

    # Orders that include this store's products AND have chat messages
    orders_qs = (
        Order.objects
        .filter(items__product__store=store)          # assumes Product.store FK exists
        .filter(chat_messages__isnull=False)          # related_name='chat_messages'
        .distinct()
    )

    # last message per order
    last_msg_qs = (
        ChatMessage.objects
        .filter(order_id=OuterRef("pk"))
        .order_by("-created_at")
    )

    orders_qs = (
        orders_qs
        .select_related("buyer")
        .annotate(
            last_message=Subquery(last_msg_qs.values("content")[:1]),
            last_message_time=Subquery(last_msg_qs.values("created_at")[:1]),
        )
        .order_by("-last_message_time")
    )

    threads = [{
        "thread_id": o.id,          # ✅ keep the name "thread_id" for your URL
        "order": o,
        "participant": o.buyer,
        "last_message": o.last_message,
        "last_message_time": o.last_message_time,
    } for o in orders_qs]

    return render(request, "stores/chat_panel.html", {
        "store": store,
        "threads": threads,
    })

@login_required
def chat_thread_detail(request, store_id, thread_id):
    """
    thread_id = Order.id
    Buyer is viewing a chat for a specific store + order.
    """
    store = get_object_or_404(Store, id=store_id)

    # Order must belong to this buyer AND include items from this store
    order = get_object_or_404(
        Order.objects.select_related("buyer"),
        id=thread_id,
        buyer=request.user,
        items__product__store=store,
    )

    messages = (
        ChatMessage.objects
        .filter(order=order)
        .select_related("sender")
        .order_by("created_at")
    )

    # Mark store messages as read (optional)
    ChatMessage.objects.filter(order=order).exclude(sender=request.user).update(is_read=True)

    return render(request, "chat/thread_detail.html", {
        "store": store,
        "order": order,
        "messages": messages,
        "thread_id": order.id,
    })


@login_required
def store_order_detail(request, store_id, order_id):
    store = get_object_or_404(Store, id=store_id, owner=request.user)
    order = get_object_or_404(Order, id=order_id)

    store_order_items = (
        order.items
        .filter(product__seller=store.owner)
        .select_related('product')
    )

    if not store_order_items.exists():
        raise Http404("No items in this order belong to your store.")

    chat_messages = order.chat_messages.all().select_related('sender')

    store_subtotal = sum(
        (Decimal(item.get_total_price()) for item in store_order_items),
        Decimal("0.00")
    )

    context = {
        "store": store,
        "order": order,
        "order_items": store_order_items,
        "buyer": order.buyer,
        "store_subtotal": store_subtotal,
        "chat_messages": chat_messages,
    }
    return render(request, "stores/store_order_detail.html", context)

def _get_order_seller_users(order):
    """Return queryset of seller Users tied to items in this order."""
    User = get_user_model()
    seller_ids = (
        order.items
        .select_related('product__seller')
        .values_list('product__seller', flat=True)
        .distinct()
    )
    return User.objects.filter(id__in=seller_ids)

def _user_can_chat_on_order(user, order):
    """Allow the buyer or any seller on this order (or superuser)."""
    if user.is_superuser:
        return True
    if getattr(order, "buyer_id", None) == user.id:
        return True
    return _get_order_seller_users(order).filter(id=user.id).exists()

def _parse_body(request):
    """Parse JSON or form-encoded body into a dict."""
    if request.content_type and "application/json" in request.content_type:
        try:
            return json.loads(request.body.decode("utf-8"))
        except json.JSONDecodeError:
            return None
    return request.POST  # QueryDict (acts like a dict)

@require_POST
@login_required
def send_chat_message(request):
    # Optional: keep accepting only AJAX, but don’t crash if header missing
    if request.headers.get("x-requested-with") not in (None, "", "XMLHttpRequest"):
        pass  # header is present (good). If you want to enforce, check equality.

    data = _parse_body(request)
    if data is None:
        return HttpResponseBadRequest("Invalid JSON")

    order_id = (data.get("order_id") or "").strip()
    content = (data.get("message") or "").strip()

    if not order_id or not content:
        return JsonResponse(
            {"success": False, "message": "Missing content or order ID."},
            status=400,
        )

    order = get_object_or_404(Order, id=order_id)

    # Permission: must be buyer or seller on the order
    if not _user_can_chat_on_order(request.user, order):
        return JsonResponse({"success": False, "message": "Not allowed."}, status=403)

    # Create message
    chat = ChatMessage.objects.create(
        order=order,
        sender=request.user,
        content=content,
    )

    # Trigger notifications (comment this out if you are using a post_save signal instead)
    try:
        notify_new_order_message(chat)
    except Exception as notify_err:
        logger.exception("notify_new_order_message failed: %s", notify_err)

    return JsonResponse(
        {
            "success": True,
            "message": {
                "id": chat.id,
                "order_id": order.id,
                "sender_name": request.user.get_full_name() or request.user.username,
                "content": chat.content,
                "created_at": timezone.localtime(chat.created_at).strftime("%Y-%m-%d %H:%M"),
                "is_read": chat.is_read,
                "is_me": True,
            },
        },
        status=201,
    )

@login_required
def fetch_chat_messages(request, order_id):
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        try:
            order = Order.objects.get(id=order_id)
            messages = order.chat_messages.select_related('sender').order_by('created_at')

            data = []
            for msg in messages:
                data.append({
                    'sender_id': msg.sender.id,
                    'sender_name': msg.sender.get_full_name() or msg.sender.username,
                    'content': msg.content,
                    'timestamp': msg.created_at.strftime('%b %d, %H:%M'),
                    'is_self': msg.sender == request.user,
                })

            return JsonResponse({'success': True, 'messages': data})
        except Order.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Order not found'})
    return JsonResponse({'success': False, 'message': 'Invalid request'})

@login_required
def chat_thread_detail(request, store_id, thread_id):
    store = get_object_or_404(Store, id=store_id, owner=request.user)
    thread = get_object_or_404(ChatThread, id=thread_id, participants=request.user)

    messages = thread.messages.select_related('sender').order_by('timestamp')

    # Determine other participant
    other_user = thread.participants.exclude(id=request.user.id).first()

    # Prepare thread summaries
    threads = []
    for t in ChatThread.objects.filter(participants=request.user).order_by('-updated_at'):
        last_msg = t.messages.last()
        other = t.participants.exclude(id=request.user.id).first()
        unread_count = t.messages.filter(sender=other, thread=t).exclude(sender=request.user).count()
        threads.append({
            'thread': t,
            'participant': other,
            'last_message': last_msg.message if last_msg else '',
            'timestamp': last_msg.timestamp if last_msg else None,
            'unread_count': unread_count,
        })

    return render(request, 'stores/chat_thread_detail.html', {
        'store': store,
        'threads': threads,
        'current_thread': thread,
        'other_user': other_user,
        'messages': messages,
    })

@require_POST
@login_required
def send_store_chat_message(request):
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        recipient_id = request.POST.get('recipient_id')
        content = request.POST.get('message', '').strip()

        if not content or not recipient_id:
            return JsonResponse({'success': False, 'message': 'Missing recipient or message.'})

        try:
            recipient = User.objects.get(id=recipient_id)
            thread, _ = ChatThread.objects.get_or_create_between(request.user, recipient)

            ChatMessage.objects.create(
                thread=thread,
                sender=request.user,
                message=content
            )

            return JsonResponse({'success': True})
        except User.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'User not found.'})
    return JsonResponse({'success': False, 'message': 'Invalid request.'})


@login_required
def fetch_store_chat_messages(request, recipient_id):
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        try:
            recipient = User.objects.get(id=recipient_id)
            thread, _ = ChatThread.objects.get_or_create_between(request.user, recipient)

            messages = thread.messages.select_related('sender').order_by('timestamp')

            data = [
                {
                    'sender_id': msg.sender.id,
                    'sender_name': msg.sender.get_full_name() or msg.sender.username,
                    'content': msg.message,
                    'timestamp': msg.timestamp.strftime('%b %d, %H:%M'),
                    'is_self': msg.sender == request.user,
                }
                for msg in messages
            ]

            return JsonResponse({'success': True, 'messages': data})

        except User.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'User not found.'})
    return JsonResponse({'success': False, 'message': 'Invalid request'})

@require_POST
@login_required
def update_order_item_quantity(request, item_id):
    try:
        item = OrderItem.objects.select_related('product', 'order').get(id=item_id)
        product = item.product

        if product.seller != request.user:
            return JsonResponse({'success': False, 'message': 'Unauthorized'})

        new_quantity = int(request.POST.get('quantity', item.quantity))
        if new_quantity < 1:
            return JsonResponse({'success': False, 'message': 'Invalid quantity'})

        quantity_diff = new_quantity - item.quantity

        # Update the product stock
        if product.stock.quantity - quantity_diff < 0:
            return JsonResponse({'success': False, 'message': 'Not enough stock available.'})

        product.stock.quantity -= quantity_diff
        product.save()

        # Update order item quantity
        item.quantity = new_quantity
        item.save()

        return JsonResponse({
            'success': True,
            'quantity': item.quantity,
            'product_stock': product.stock.quantity
        })

    except OrderItem.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Item not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})

@login_required
def store_dashboard(request, store_id):
    store = get_object_or_404(Store, id=store_id)

    # 🔒 Access Control Check
    if not (request.user == store.owner or request.user.is_superuser or getattr(request.user, 'is_seller', False)):
        return HttpResponseForbidden("You do not have permission to view this dashboard.")

    now = timezone.now()
    current_month = now.replace(day=1)
    pending_orders_count = Order.objects.filter(items__product__store=store, status='processing').count()

    # Get all products for the current store
    store_products = Product.objects.filter(store=store)

    # Get reviews for all those products
    product_reviews = Review.objects.filter(product__in=store_products).select_related('user', 'product')

    # Pending orders
    pending_orders = Order.objects.filter(
        status='pending',
        items__product__store=store
    ).distinct()
    pending_orders_count = pending_orders.count()

    # Use Subquery to annotate stock level from stock_records
    low_stock_products = Product.objects.annotate(
        stock_level=Subquery(
            Stock.objects.filter(product=OuterRef('pk')).values('quantity')[:1]
        )
    ).filter(store=store, stock_level__lt=5)

    # Unread messages
    unread_messages = ChatMessage.objects.filter(
        order__items__product__store=store,
        is_read=False,
        sender__is_staff=False  # Optional: ignore messages sent by the store owner/admin
    ).distinct().count()

    try:
        user_products = Product.objects.filter(seller=store.owner)
        total_products = user_products.count()

        # Recent products
        recent_products = user_products.order_by('-created_at')[:5]

        # Top products with total sold and revenue
        top_products = user_products.annotate(
            total_sold=Coalesce(Sum('order_items__quantity'), 0),
            total_revenue=Coalesce(
                Sum(F('order_items__quantity') * F('order_items__price_at_time'), output_field=FloatField()), 0.0),
            avg_rating=Coalesce(Avg('reviews__rating'), 0.0)
        ).order_by('-total_sold')[:5]

        # Seller's orders
        seller_orders = Order.objects.filter(
            items__product__seller=store.owner
        ).distinct()

        total_orders = seller_orders.count()
        monthly_orders = seller_orders.filter(created_at__gte=current_month).count()

        # Revenue
        seller_order_items = OrderItem.objects.filter(product__seller=store.owner)
        total_revenue = sum(item.get_total_price() for item in seller_order_items)
        monthly_revenue = sum(
            item.get_total_price() for item in seller_order_items.filter(order__created_at__gte=current_month)
        )

        # Get all reviews for this store's products
        product_ids = user_products.values_list('id', flat=True)
        reviews = Review.objects.filter(product_id__in=product_ids)

        review_count = reviews.count()
        average_rating = reviews.aggregate(avg=Avg('rating'))['avg'] or 0

        # Rating breakdown
        rating_breakdown = {}
        for i in range(1, 6):
            rating_breakdown[i] = reviews.filter(rating=i).count()

        recent_orders = seller_orders.order_by('-created_at')[:5]

        # Category distribution
        category_data = user_products.values('category__name').annotate(
            count=Count('id')
        ).order_by('-count')[:6]

        category_labels = [cat['category__name'] or 'Uncategorized' for cat in category_data] if category_data else [
            'No Products']
        category_counts = [cat['count'] for cat in category_data] if category_data else [1]

        # Monthly sales chart data
        now = datetime.now()

        monthly_sales_data = []
        monthly_labels = []

        for i in range(11, -1, -1):  # Go backwards 12 months
            month_date = (now.replace(day=15) - timedelta(days=30 * i))  # Use middle of the month for stability
            month_start = month_date.replace(day=1)
            next_month = (month_start + timedelta(days=32)).replace(day=1)
            month_end = next_month - timedelta(days=1)

            sales = sum(
                item.get_total_price() for item in seller_order_items.filter(
                    order__created_at__gte=month_start,
                    order__created_at__lte=month_end
                )
            )
            monthly_sales_data.append(float(sales))
            monthly_labels.append(month_start.strftime('%b'))

        store_views = 0
        weekly_views = 0

    except Exception as e:
        print(f"Dashboard error: {e}")
        total_products = 0
        recent_products = top_products = recent_orders = []
        total_orders = monthly_orders = 0
        total_revenue = monthly_revenue = 0
        store_views = weekly_views = 0
        monthly_sales_data = [0] * 12
        monthly_labels = [''] * 12
        category_labels = ['No Data']
        category_counts = [1]
        review_count = 0
        average_rating = 0
        rating_breakdown = {}
        
    # --- Store health score (0 - 100) ---
    store_health_score = 0

    # Profile completeness
    if store.phone:
        store_health_score += 15
    if store.email_verified:
        store_health_score += 15
    if store.store_type:
        store_health_score += 10
    if store.logo:
        store_health_score += 10
    if store.banner:
        store_health_score += 5

    # Activity / inventory
    if total_products >= 10:
        store_health_score += 25
    elif total_products >= 1:
        store_health_score += 15

    if total_orders >= 5:
        store_health_score += 20
    elif total_orders >= 1:
        store_health_score += 10

    store_health_score = max(0, min(100, int(store_health_score)))

    context = {
        'store': store,
        'total_products': total_products,
        'store_health_score': store_health_score,
        'recent_products': recent_products,
        'total_orders': total_orders,
        'monthly_orders': monthly_orders,
        'total_revenue': total_revenue,
        'monthly_revenue': monthly_revenue,
        'store_views': store_views,
        "product_reviews": product_reviews,
        'weekly_views': weekly_views,
        'recent_orders': recent_orders,
        'top_products': top_products,
        'monthly_sales_data': json.dumps(monthly_sales_data),
        'monthly_labels': json.dumps(monthly_labels),
        'category_labels': json.dumps(category_labels),
        'category_data': json.dumps(category_counts),
        'review_count': review_count,
        'average_rating': round(average_rating, 1),
        'rating_breakdown': rating_breakdown,
        'pending_orders_count': pending_orders_count,
        "low_stock_products": low_stock_products,
        "unread_messages": unread_messages,

    }

    return render(request, 'stores/store_dashboard.html', context)


@login_required
@store_owner_required
def store_settings(request, store_id):
    """Comprehensive store settings management"""
    store = get_object_or_404(Store, id=store_id, owner=request.user)

    # Get or create related return settings
    return_settings, _ = StoreReturnSettings.objects.get_or_create(store=store)

    # Create or fetch store hours defaults
    store_hours = []
    for day in range(7):
        hour, _ = StoreHours.objects.get_or_create(
            store=store,
            day_of_week=day,
            defaults={'is_closed': True}
        )
        store_hours.append(hour)

    if request.method == 'POST':
        tab = request.POST.get('tab', 'basic')
        # Add this theme handling
        if tab == 'theme':
            try:
                # Preset
                store.theme_preset = request.POST.get('theme_preset', store.theme_preset or 'modern')

                # Colors
                store.primary_color = request.POST.get('primary_color', '#2563eb')
                store.secondary_color = request.POST.get('secondary_color', '#64748b')
                store.accent_color = request.POST.get('accent_color', '#f59e0b')
                store.background_color = request.POST.get('background_color', '#ffffff')
                store.text_color = request.POST.get('text_color', '#1e293b')

                # Fonts
                store.font_heading = request.POST.get('font_heading', 'poppins')
                store.font_body = request.POST.get('font_body', 'inter')

                # Layout / UI (safe defaults)
                store.product_layout = request.POST.get('product_layout', store.product_layout or 'grid')
                store.products_per_row = int(request.POST.get('products_per_row', store.products_per_row or 4))
                store.product_card_style = request.POST.get('product_card_style', store.product_card_style or 'shadow')
                store.product_image_shape = request.POST.get('product_image_shape',
                                                             store.product_image_shape or 'square')
                store.mobile_menu_style = request.POST.get('mobile_menu_style', store.mobile_menu_style or 'bottom')

                # Features (checkboxes)
                store.show_product_ratings = 'show_product_ratings' in request.POST
                store.show_product_badges = 'show_product_badges' in request.POST
                store.enable_animations = 'enable_animations' in request.POST
                store.enable_hover_effects = 'enable_hover_effects' in request.POST
                store.enable_featured_products = 'enable_featured_products' in request.POST
                store.enable_new_arrivals = 'enable_new_arrivals' in request.POST
                store.enable_best_sellers = 'enable_best_sellers' in request.POST
                store.enable_testimonials = 'enable_testimonials' in request.POST

                store.save()
                messages.success(request, 'Theme settings saved successfully!')
                return redirect('stores:store_settings', store_id=store.id)

            except Exception as e:
                messages.error(request, f'Error saving theme: {str(e)}')

        if tab == 'basic':
            form = StoreSettingsForm(request.POST, request.FILES, instance=store)
            if form.is_valid():
                form.save()
                messages.success(request, 'Store details updated successfully!')
                return redirect('stores:store_settings', store_id=store.id)

        elif tab == 'hours':
            hours_formset = StoreHoursFormSet(request.POST, queryset=StoreHours.objects.filter(store=store))
            if hours_formset.is_valid():
                for form in hours_formset:
                    if form.is_valid():
                        hour = form.save(commit=False)
                        hour.store = store
                        hour.save()
                messages.success(request, 'Store hours updated successfully!')
                return redirect('stores:store_settings', store_id=store.id)

        elif tab == 'shipping':
            shipping_formset = StoreShippingZoneFormSet(
                request.POST,
                queryset=StoreShippingZone.objects.filter(store=store)
            )
            if shipping_formset.is_valid():
                with transaction.atomic():
                    for form in shipping_formset:
                        if form.cleaned_data:
                            if form.cleaned_data.get('DELETE') and form.instance.pk:
                                form.instance.delete()
                            else:
                                zone = form.save(commit=False)
                                zone.store = store
                                zone.save()
                messages.success(request, 'Shipping zones updated successfully!')
                return redirect('stores:store_settings', store_id=store.id)

        elif tab == 'returns':
            returns_form = StoreReturnSettingsForm(request.POST, instance=return_settings)
            if returns_form.is_valid():
                returns_form.save()
                messages.success(request, 'Return policy updated successfully!')
                return redirect('stores:store_settings', store_id=store.id)

        elif tab == 'financial':
            financial_form = StoreFinancialForm(request.POST, instance=store)
            if financial_form.is_valid():
                financial_form.save()
                messages.success(request, 'Financial settings updated successfully!')
                return redirect('stores:store_settings', store_id=store.id)

    # Initial load of all forms
    basic_form = StoreSettingsForm(instance=store)
    hours_formset = StoreHoursFormSet(queryset=StoreHours.objects.filter(store=store).order_by('day_of_week'))
    shipping_formset = StoreShippingZoneFormSet(queryset=StoreShippingZone.objects.filter(store=store))
    returns_form = StoreReturnSettingsForm(instance=return_settings)
    financial_form = StoreFinancialForm(instance=store)

    context = {
        'store': store,
        'basic_form': basic_form,
        'hours_formset': hours_formset,
        'shipping_formset': shipping_formset,
        'returns_form': returns_form,
        'financial_form': financial_form,
        'active_tab': request.GET.get('tab', 'basic'),
    }

    return render(request, 'stores/store_settings.html', context)


@login_required
@store_owner_required
@login_required
@store_owner_required
def stock_management(request, store_id):
    """
    Main stock management view with warehouse management.
    """
    store = get_object_or_404(Store, id=store_id)

    # ✅ Your architecture: Store -> OneToOne -> Warehouse
    warehouse = getattr(store, "warehouse", None)

    # Only show stock if warehouse exists
    if warehouse:
        products = Product.objects.filter(store=store, is_active=True)

        # Filters
        search_query = request.GET.get('search', '')
        stock_filter = request.GET.get('stock_filter', 'all')
        category_filter = request.GET.get('category', '')

        if search_query:
            products = products.filter(
                Q(name__icontains=search_query) |
                Q(sku__icontains=search_query)
            )

        products_with_stock = []

        for product in products:
            # ✅ Don’t assign to product.stock_quantity (it’s a property)
            qty = (
                Stock.objects
                .filter(product=product, warehouse=warehouse)
                .values_list("quantity", flat=True)
                .first()
            ) or 0

            # ✅ attach a safe temporary attribute for template display
            setattr(product, "warehouse_stock_qty", qty)

            # Apply stock level filter using qty
            if stock_filter == 'available' and qty == 0:
                continue
            elif stock_filter == 'low' and qty > 5:
                continue
            elif stock_filter == 'out' and qty > 0:
                continue

            products_with_stock.append(product)

        # Category filter
        if category_filter:
            products_with_stock = [
                p for p in products_with_stock
                if str(p.category_id) == category_filter
            ]

        # Pagination
        paginator = Paginator(products_with_stock, 20)
        page_number = request.GET.get('page', 1)
        products_page = paginator.get_page(page_number)

        categories = products.values('category_id', 'category__name').distinct()

        # Stats (use warehouse_stock_qty)
        total_products = len(products_with_stock)
        in_stock_count = len([p for p in products_with_stock if p.warehouse_stock_qty > 5])
        low_stock_count = len([p for p in products_with_stock if 0 < p.warehouse_stock_qty <= 5])
        out_of_stock_count = len([p for p in products_with_stock if p.warehouse_stock_qty == 0])

        stock_value = (
            Stock.objects
            .filter(warehouse=warehouse)
            .aggregate(total=Sum(F('quantity') * F('unit_cost')))['total']
        ) or Decimal('0.00')

    else:
        products_page = []
        categories = []
        total_products = in_stock_count = low_stock_count = out_of_stock_count = 0
        stock_value = Decimal('0.00')
        search_query = stock_filter = category_filter = ''

    context = {
        'store': store,
        'warehouse': warehouse,
        'products': products_page,
        'categories': categories,
        'total_products': total_products,
        'in_stock_count': in_stock_count,
        'low_stock_count': low_stock_count,
        'out_of_stock_count': out_of_stock_count,
        'stock_value': stock_value,
        'search_query': search_query,
        'stock_filter': stock_filter,
        'category_filter': category_filter,
    }

    return render(request, 'stores/stock_management.html', context)

@login_required
@require_POST
@transaction.atomic
def manage_warehouse(request, store_id):
    """
    Create or update store warehouse (one per store).
    """
    store = get_object_or_404(Store, id=store_id)

    warehouse_name = request.POST.get('warehouse_name', '').strip()
    warehouse_code = request.POST.get('warehouse_code', '').strip()
    address = request.POST.get('address', '').strip()
    city = request.POST.get('city', '').strip()
    state = request.POST.get('state', '').strip()
    country = request.POST.get('country', '').strip()
    postal_code = request.POST.get('postal_code', '').strip()
    latitude = request.POST.get('latitude', '').strip()
    longitude = request.POST.get('longitude', '').strip()

    # Validation
    if not all([warehouse_name, warehouse_code, address, city, country]):
        messages.error(request, 'Please fill in all required fields.')
        return redirect('stores:stock_management', store_id=store_id)

    current_warehouse = store.warehouse  # ✅ OneToOne via Store

    # Warehouse code must be unique (exclude current warehouse if updating)
    existing = Warehouse.objects.filter(code=warehouse_code)
    if current_warehouse:
        existing = existing.exclude(pk=current_warehouse.pk)

    if existing.exists():
        messages.error(request, f'Warehouse code "{warehouse_code}" is already in use.')
        return redirect('stores:stock_management', store_id=store_id)

    # Create or update
    if not current_warehouse:
        warehouse = Warehouse.objects.create(
            name=warehouse_name,
            code=warehouse_code,
            address=address,
            city=city,
            state=state,
            country=country,
            postal_code=postal_code,
            manager=request.user,
            is_active=True,
        )
        store.warehouse = warehouse
        store.save(update_fields=["warehouse"])
        created = True
    else:
        warehouse = current_warehouse
        warehouse.name = warehouse_name
        warehouse.code = warehouse_code
        warehouse.address = address
        warehouse.city = city
        warehouse.state = state
        warehouse.country = country
        warehouse.postal_code = postal_code
        warehouse.manager = warehouse.manager or request.user
        created = False

    # Geocode
    if latitude and longitude:
        try:
            warehouse.latitude = Decimal(latitude)
            warehouse.longitude = Decimal(longitude)
        except (ValueError, TypeError, InvalidOperation):
            messages.warning(request, 'Invalid geocode coordinates provided.')

    warehouse.save()

    messages.success(
        request,
        f'Warehouse "{warehouse_name}" {"created" if created else "updated"} successfully!'
    )
    return redirect('stores:stock_management', store_id=store_id)

@login_required
@require_POST
@transaction.atomic
def update_stock(request, store_id, product_id):
    """
    Update stock for a product with optional shipping to logistics warehouse.
    """
    store = get_object_or_404(Store, id=store_id, user=request.user)
    product = get_object_or_404(Product, id=product_id, store=store)

    # Get warehouse
    try:
        warehouse = Warehouse.objects.get(store=store)
    except Warehouse.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Please create a warehouse first.'
        })

    # Get form data
    adjustment_type = request.POST.get('type', 'set')
    quantity = request.POST.get('quantity', '0')
    notes = request.POST.get('notes', '').strip()
    ship_to_warehouse = request.POST.get('ship_to_warehouse', 'false').lower() == 'true'

    try:
        quantity = int(quantity)
        if quantity < 0:
            raise ValueError("Quantity cannot be negative")
    except (ValueError, TypeError):
        return JsonResponse({
            'success': False,
            'message': 'Invalid quantity provided.'
        })

    # Get or create stock record
    stock_record, created = Stock.objects.get_or_create(
        product=product,
        warehouse=warehouse,
        defaults={
            'quantity': 0,
            'unit_cost': product.price * Decimal('0.6')  # Default cost
        }
    )

    old_quantity = stock_record.quantity
    new_quantity = old_quantity
    movement_quantity = 0
    movement_type = 'ADJUSTMENT'

    # Calculate new quantity based on adjustment type
    if adjustment_type == 'set':
        new_quantity = quantity
        movement_quantity = quantity - old_quantity
        movement_type = 'ADJUSTMENT'
    elif adjustment_type == 'add':
        new_quantity = old_quantity + quantity
        movement_quantity = quantity
        movement_type = 'PURCHASE'
    elif adjustment_type == 'subtract':
        new_quantity = max(0, old_quantity - quantity)
        movement_quantity = -(min(quantity, old_quantity))
        movement_type = 'SALE'

    # Update stock
    stock_record.quantity = new_quantity
    stock_record.save()

    # Create stock movement record
    movement_notes = notes or f"Stock {adjustment_type}: {abs(movement_quantity)} units"

    StockMovement.objects.create(
        product=product,
        warehouse=warehouse,
        movement_type=movement_type,
        quantity=movement_quantity,
        reference_number=f'ADJ-{stock_record.id}-{timezone.now().timestamp()}',
        unit_cost=stock_record.unit_cost,
        notes=movement_notes,
        created_by=request.user
    )

    # Handle shipping to logistics warehouse
    if ship_to_warehouse and movement_quantity < 0:  # Only for reductions/dispatches
        try:
            # Find primary logistics warehouse
            from supply_chain.models import WarehouseLinkage

            linkage = WarehouseLinkage.objects.filter(
                store_warehouse=warehouse,
                is_primary=True,
                is_active=True
            ).first()

            if linkage:
                # Create transfer to logistics warehouse
                from supply_chain.utils import initiate_transfer

                transfer = initiate_transfer(
                    store_warehouse=warehouse,
                    logistics_warehouse=linkage.logistics_warehouse,
                    product=product,
                    quantity=abs(movement_quantity),
                    user=request.user,
                    notes=f"Stock update transfer: {notes}"
                )

                movement_notes += f" | Transfer created: {transfer.transfer_number}"
            else:
                movement_notes += " | No logistics warehouse linked for transfer"

        except Exception as e:
            # If supply chain not set up, just log it
            movement_notes += f" | Note: Transfer not created ({str(e)})"

    return JsonResponse({
        'success': True,
        'message': f'Stock updated successfully. New quantity: {new_quantity}',
        'new_quantity': new_quantity,
        'old_quantity': old_quantity,
        'movement_created': True,
        'shipped_to_warehouse': ship_to_warehouse and movement_quantity < 0
    })


@login_required
def inventory_history(request, store_id):
    """
    View stock movement history for the store.
    """
    store = get_object_or_404(Store, id=store_id, user=request.user)

    try:
        warehouse = Warehouse.objects.get(store=store)
    except Warehouse.DoesNotExist:
        messages.warning(request, 'Please create a warehouse first.')
        return redirect('stores:stock_management', store_id=store_id)

    # Get all movements for this warehouse
    movements = StockMovement.objects.filter(
        warehouse=warehouse
    ).select_related('product', 'created_by').order_by('-created_at')

    # Apply filters
    product_filter = request.GET.get('product')
    movement_type_filter = request.GET.get('movement_type')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    if product_filter:
        movements = movements.filter(product_id=product_filter)

    if movement_type_filter:
        movements = movements.filter(movement_type=movement_type_filter)

    if date_from:
        movements = movements.filter(created_at__date__gte=date_from)

    if date_to:
        movements = movements.filter(created_at__date__lte=date_to)

    # Pagination
    paginator = Paginator(movements, 50)
    page_number = request.GET.get('page', 1)
    movements_page = paginator.get_page(page_number)

    # Get products for filter dropdown
    products = Product.objects.filter(store=store, is_active=True).order_by('name')

    # Get movement types
    movement_types = StockMovement.MOVEMENT_TYPES

    context = {
        'store': store,
        'warehouse': warehouse,
        'movements': movements_page,
        'products': products,
        'movement_types': movement_types,
        'product_filter': product_filter,
        'movement_type_filter': movement_type_filter,
        'date_from': date_from,
        'date_to': date_to,
    }

    return render(request, 'stores/inventory_history.html', context)


@login_required
def export_stock(request, store_id):
    """
    Export stock data as CSV.
    """
    import csv
    from django.http import HttpResponse
    from django.utils import timezone

    store = get_object_or_404(Store, id=store_id, user=request.user)

    try:
        warehouse = Warehouse.objects.get(store=store)
    except Warehouse.DoesNotExist:
        messages.error(request, 'No warehouse found.')
        return redirect('stores:stock_management', store_id=store_id)

    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response[
        'Content-Disposition'] = f'attachment; filename="stock_{store.slug}_{timezone.now().strftime("%Y%m%d")}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Product Name', 'SKU', 'Category', 'Current Stock',
        'Unit Cost', 'Stock Value', 'Reorder Level', 'Status'
    ])

    # Get all stock records
    stocks = Stock.objects.filter(warehouse=warehouse).select_related('product')

    for stock in stocks:
        status = 'Out of Stock' if stock.quantity == 0 else 'Low Stock' if stock.quantity <= 5 else 'In Stock'

        writer.writerow([
            stock.product.name,
            stock.product.sku or 'N/A',
            stock.product.category.name if stock.product.category else 'N/A',
            stock.quantity,
            f"${stock.unit_cost:.2f}",
            f"${stock.stock_value:.2f}",
            stock.reorder_level,
            status
        ])

    return response


@login_required
@store_owner_required
def financial_dashboard(request, store_id):
    """Financial overview and management for the store"""
    store = get_object_or_404(Store, id=store_id, owner=request.user)

    # Date range for analysis
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=30)

    # Get date range from request if provided
    if request.GET.get('date_from'):
        start_date = datetime.strptime(request.GET.get('date_from'), '%Y-%m-%d').date()
    if request.GET.get('date_to'):
        end_date = datetime.strptime(request.GET.get('date_to'), '%Y-%m-%d').date()

    # Sales data
    order_items = OrderItem.objects.filter(
        product__seller=store.owner,
        order__created_at__date__gte=start_date,
        order__created_at__date__lte=end_date,
        order__status__in=['delivered', 'shipped', 'processing']
    )

    total_revenue = sum(item.get_total_price() for item in order_items)
    total_orders = order_items.values('order').distinct().count()
    total_items_sold = order_items.aggregate(total=Sum('quantity'))['total'] or 0

    # Commission calculations
    commission_amount = total_revenue * (store.commission_rate / 100)
    net_revenue = total_revenue - commission_amount

    # Monthly breakdown
    monthly_data = []
    current_date = start_date
    while current_date <= end_date:
        month_start = current_date.replace(day=1)
        if current_date.month == 12:
            month_end = current_date.replace(year=current_date.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            month_end = current_date.replace(month=current_date.month + 1, day=1) - timedelta(days=1)

        month_orders = OrderItem.objects.filter(
            product__seller=store.owner,
            order__created_at__date__gte=month_start,
            order__created_at__date__lte=month_end,
            order__status__in=['delivered', 'shipped', 'processing']
        )

        month_revenue = sum(item.get_total_price() for item in month_orders)
        month_commission = month_revenue * (store.commission_rate / 100)

        monthly_data.append({
            'month': month_start.strftime('%B %Y'),
            'revenue': float(month_revenue),
            'commission': float(month_commission),
            'net': float(month_revenue - month_commission),
            'orders': month_orders.values('order').distinct().count()
        })

        if current_date.month == 12:
            current_date = current_date.replace(year=current_date.year + 1, month=1)
        else:
            current_date = current_date.replace(month=current_date.month + 1)

    # Top selling products
    top_products = Product.objects.filter(
        seller=store.owner
    ).annotate(
        total_sold=Sum('order_items__quantity'),
        total_revenue=Sum(
            ExpressionWrapper(
                F('order_items__quantity') * F('order_items__price_at_time'),
                output_field=DecimalField()
            )
        )
    ).filter(total_sold__gt=0).order_by('-total_revenue')[:10]

    # Recent transactions
    recent_orders = Order.objects.filter(
        items__product__seller=store.owner
    ).distinct().order_by('-created_at')[:5]

    context = {
        'store': store,
        'start_date': start_date,
        'end_date': end_date,
        'total_revenue': total_revenue,
        'commission_amount': commission_amount,
        'net_revenue': net_revenue,
        'total_orders': total_orders,
        'total_items_sold': total_items_sold,
        'monthly_data': json.dumps(monthly_data),
        'top_products': top_products,
        'recent_orders': recent_orders,
        'commission_rate': store.commission_rate,
    }

    return render(request, 'stores/financial_dashboard.html', context)


@login_required
@store_owner_required
def sales_analytics(request, store_id):
    """Detailed sales analytics and reporting"""
    store = get_object_or_404(Store, id=store_id, owner=request.user)

    # Date range
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=30)

    if request.GET.get('period') == '7days':
        start_date = end_date - timedelta(days=7)
    elif request.GET.get('period') == '90days':
        start_date = end_date - timedelta(days=90)
    elif request.GET.get('period') == 'year':
        start_date = end_date - timedelta(days=365)

    # Daily sales data for charts
    daily_sales = []
    current_date = start_date
    while current_date <= end_date:
        day_orders = OrderItem.objects.filter(
            product__seller=store.owner,
            order__created_at__date=current_date,
            order__status__in=['delivered', 'shipped', 'processing']
        )

        day_revenue = sum(item.get_total_price() for item in day_orders)
        day_orders_count = day_orders.values('order').distinct().count()

        daily_sales.append({
            'date': current_date.strftime('%Y-%m-%d'),
            'revenue': float(day_revenue),
            'orders': day_orders_count,
            'items': day_orders.aggregate(total=Sum('quantity'))['total'] or 0
        })

        current_date += timedelta(days=1)

    # Category performance
    category_performance = Product.objects.filter(
        seller=store.owner
    ).values(
        'category__name'
    ).annotate(
        total_sold=Sum('order_items__quantity'),
        revenue=Sum(
            ExpressionWrapper(
                F('order_items__quantity') * F('order_items__price_at_time'),
                output_field=DecimalField()
            )
        ),
        total_revenue=F('revenue'),
        avg_price=Avg('price')
    ).filter(total_sold__gt=0).order_by('-total_revenue')
    total_revenue = sum(day['revenue'] for day in daily_sales)

    context = {
         'store': store,
        'start_date': start_date,
        'end_date': end_date,
        'daily_sales': json.dumps(daily_sales),
        'category_performance': category_performance,
        'period': request.GET.get('period', '30days'),
        'total_revenue': total_revenue,  # ✅ now included
    }

    return render(request, 'stores/sales_analytics.html', context)


@login_required
@require_POST
def export_financial_report(request, store_id):
    """Export financial report as CSV"""
    store = get_object_or_404(Store, id=store_id, owner=request.user)

    # This would implement CSV export functionality
    # For now, return a JSON response
    return JsonResponse({
        'success': True,
        'message': 'Report export initiated. You will receive an email when ready.'
    })

# Store API management
@login_required
def store_metrics_api(request, store_id):
    """API endpoint for real-time store metrics"""
    store = get_object_or_404(Store, id=store_id, owner=request.user)

    # Calculate current metrics
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    # Today's metrics
    today_orders = OrderItem.objects.filter(
        product__seller=store.owner,
        order__created_at__date=today,
        order__status__in=['delivered', 'shipped', 'processing']
    )

    today_revenue = sum(item.get_total_price() for item in today_orders)
    today_orders_count = today_orders.values('order').distinct().count()

    # Weekly metrics
    week_orders = OrderItem.objects.filter(
        product__seller=store.owner,
        order__created_at__date__gte=week_ago,
        order__status__in=['delivered', 'shipped', 'processing']
    )

    week_revenue = sum(item.get_total_price() for item in week_orders)
    week_orders_count = week_orders.values('order').distinct().count()

    # Stock alerts
    low_stock_products = Product.objects.filter(
        seller=store.owner,
        stock__quantity__lte=10,
        stock__quantity__gt=0
    ).count()

    out_of_stock_products = Product.objects.filter(
        seller=store.owner,
        stock__quantity=0
    ).count()

    # Recent activity
    recent_inventory_changes = StoreInventoryTracking.objects.filter(
        store=store
    ).order_by('-timestamp')[:5]

    recent_changes = []
    for change in recent_inventory_changes:
        recent_changes.append({
            'product_name': change.product.name,
            'transaction_type': change.get_transaction_type_display(),
            'quantity_change': change.quantity_change,
            'timestamp': change.timestamp.strftime('%Y-%m-%d %H:%M'),
        })

    data = {
        'store_id': str(store.id),
        'store_name': store.name,
        'today': {
            'revenue': float(today_revenue),
            'orders': today_orders_count,
            'date': today.strftime('%Y-%m-%d')
        },
        'week': {
            'revenue': float(week_revenue),
            'orders': week_orders_count,
            'period': f"{week_ago.strftime('%Y-%m-%d')} to {today.strftime('%Y-%m-%d')}"
        },
        'stock_alerts': {
            'low_stock': low_stock_products,
            'out_of_stock': out_of_stock_products
        },
        'recent_activity': recent_changes,
        'last_updated': timezone.now().isoformat()
    }

    return JsonResponse(data)


@login_required
@require_POST
def bulk_inventory_update(request, store_id):
    """API endpoint for bulk inventory updates"""
    store = get_object_or_404(Store, id=store_id, owner=request.user)

    try:
        data = json.loads(request.body)
        product_ids = data.get('product_ids', [])
        adjustment_type = data.get('type', 'set')  # 'set', 'add', 'subtract'
        quantity = int(data.get('quantity', 0))
        notes = data.get('notes', 'Bulk inventory update')

        if not product_ids or quantity < 0:
            return JsonResponse({'success': False, 'message': 'Invalid data provided'})

        updated_products = []
        failed_products = []

        with transaction.atomic():
            for product_id in product_ids:
                try:
                    product = Product.objects.get(id=product_id, seller=store.owner)
                    stock, created = Stock.objects.get_or_create(product=product)

                    old_quantity = stock.quantity

                    if adjustment_type == 'set':
                        stock.quantity = quantity
                        quantity_change = quantity - old_quantity
                    elif adjustment_type == 'add':
                        stock.quantity += quantity
                        quantity_change = quantity
                    elif adjustment_type == 'subtract':
                        stock.quantity = max(0, stock.quantity - quantity)
                        quantity_change = -(min(quantity, old_quantity))

                    stock.save()

                    # Create inventory tracking record
                    StoreInventoryTracking.objects.create(
                        store=store,
                        product=product,
                        transaction_type='adjustment',
                        quantity_change=quantity_change,
                        notes=notes,
                        performed_by=request.user
                    )

                    updated_products.append({
                        'id': product.id,
                        'name': product.name,
                        'old_quantity': old_quantity,
                        'new_quantity': stock.quantity
                    })

                except Product.DoesNotExist:
                    failed_products.append({'id': product_id, 'error': 'Product not found'})
                except Exception as e:
                    failed_products.append({'id': product_id, 'error': str(e)})

        return JsonResponse({
            'success': True,
            'updated_count': len(updated_products),
            'failed_count': len(failed_products),
            'updated_products': updated_products,
            'failed_products': failed_products
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


@login_required
def export_store_data(request, store_id, data_type):
    """Export various store data as CSV"""
    store = get_object_or_404(Store, id=store_id, owner=request.user)

    response = HttpResponse(content_type='text/csv')

    if data_type == 'products':
        response['Content-Disposition'] = f'attachment; filename="{store.slug}_products.csv"'

        writer = csv.writer(response)
        writer.writerow([
            'ID', 'Name', 'Category', 'Price', 'Original Price', 'Stock Quantity',
            'Is Active', 'Is Featured', 'Created At', 'Updated At'
        ])

        products = Product.objects.filter(seller=store.owner).select_related('category', 'stock')
        for product in products:
            writer.writerow([
                product.id,
                product.name,
                product.category.name if product.category else '',
                product.price,
                product.original_price or '',
                product.stock.quantity if hasattr(product, 'stock') else 0,
                product.is_active,
                product.is_featured,
                product.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                product.updated_at.strftime('%Y-%m-%d %H:%M:%S')
            ])

    elif data_type == 'inventory':
        response['Content-Disposition'] = f'attachment; filename="{store.slug}_inventory_history.csv"'

        writer = csv.writer(response)
        writer.writerow([
            'Date', 'Product ID', 'Product Name', 'Transaction Type', 'Quantity Change',
            'Condition', 'Reference ID', 'Notes', 'Performed By'
        ])

        transactions = StoreInventoryTracking.objects.filter(store=store).select_related(
            'product', 'performed_by'
        ).order_by('-timestamp')

        for transaction in transactions:
            writer.writerow([
                transaction.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                transaction.product.id,
                transaction.product.name,
                transaction.get_transaction_type_display(),
                transaction.quantity_change,
                transaction.get_condition_display() if transaction.condition else '',
                transaction.reference_id or '',
                transaction.notes or '',
                transaction.performed_by.username if transaction.performed_by else 'System'
            ])

    elif data_type == 'sales':
        response['Content-Disposition'] = f'attachment; filename="{store.slug}_sales_report.csv"'

        writer = csv.writer(response)
        writer.writerow([
            'Order Date', 'Order ID', 'Product ID', 'Product Name', 'Quantity',
            'Unit Price', 'Total Price', 'Customer', 'Order Status'
        ])

        order_items = OrderItem.objects.filter(
            product__seller=store.owner
        ).select_related('order', 'product', 'order__buyer').order_by('-order__created_at')

        for item in order_items:
            writer.writerow([
                item.order.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                item.order.order_number,
                item.product.id,
                item.product.name,
                item.quantity,
                item.price_at_time,
                item.get_total_price(),
                item.order.buyer.username,
                item.order.get_status_display()
            ])

    else:
        return JsonResponse({'error': 'Invalid data type'}, status=400)

    return response


@login_required
def store_analytics_data(request, store_id):
    """Get detailed analytics data for charts and reports"""
    store = get_object_or_404(Store, id=store_id, owner=request.user)

    # Date range
    days = int(request.GET.get('days', 30))
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=days)

    # Daily sales data
    daily_sales = []
    current_date = start_date
    while current_date <= end_date:
        day_orders = OrderItem.objects.filter(
            product__seller=store.owner,
            order__created_at__date=current_date,
            order__status__in=['delivered', 'shipped', 'processing']
        )

        day_revenue = sum(item.get_total_price() for item in day_orders)
        day_orders_count = day_orders.values('order').distinct().count()
        day_items_sold = day_orders.aggregate(total=Sum('quantity'))['total'] or 0

        daily_sales.append({
            'date': current_date.strftime('%Y-%m-%d'),
            'revenue': float(day_revenue),
            'orders': day_orders_count,
            'items_sold': day_items_sold
        })

        current_date += timedelta(days=1)

    # Category performance
    category_performance = Product.objects.filter(
        seller=store.owner
    ).values(
        'category__name'
    ).annotate(
        total_sold=Sum('order_items__quantity'),
        total_revenue=Sum(F('order_items__quantity') * F('order_items__price_at_time')),
        product_count=Count('id')
    ).filter(total_sold__gt=0).order_by('-total_revenue')

    # Convert to list for JSON serialization
    category_data = []
    for cat in category_performance:
        category_data.append({
            'name': cat['category__name'] or 'Uncategorized',
            'total_sold': cat['total_sold'],
            'total_revenue': float(cat['total_revenue'] or 0),
            'product_count': cat['product_count']
        })

    # Top customers
    top_customers = OrderItem.objects.filter(
        product__seller=store.owner
    ).values(
        'order__buyer__username',
        'order__buyer__first_name',
        'order__buyer__last_name'
    ).annotate(
        total_orders=Count('order', distinct=True),
        total_spent=Sum(F('quantity') * F('price_at_time')),
        total_items=Sum('quantity')
    ).order_by('-total_spent')[:10]

    customer_data = []
    for customer in top_customers:
        customer_data.append({
            'username': customer['order__buyer__username'],
            'name': f"{customer['order__buyer__first_name'] or ''} {customer['order__buyer__last_name'] or ''}".strip() or
                    customer['order__buyer__username'],
            'total_orders': customer['total_orders'],
            'total_spent': float(customer['total_spent']),
            'total_items': customer['total_items']
        })

    return JsonResponse({
        'daily_sales': daily_sales,
        'category_performance': category_data,
        'top_customers': customer_data,
        'period': {
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d'),
            'days': days
        }
    })


@login_required
@require_POST
def calculate_store_metrics(request, store_id):
    """Manually trigger calculation of store metrics"""
    store = get_object_or_404(Store, id=store_id, owner=request.user)

    try:
        date = request.POST.get('date')
        if date:
            calc_date = datetime.strptime(date, '%Y-%m-%d').date()
        else:
            calc_date = timezone.now().date()

        metrics = StoreMetrics.calculate_daily_metrics(store, calc_date)

        return JsonResponse({
            'success': True,
            'message': f'Metrics calculated for {calc_date}',
            'metrics': {
                'date': metrics.date.strftime('%Y-%m-%d'),
                'total_orders': metrics.total_orders,
                'total_sales': float(metrics.total_sales),
                'total_returns': metrics.total_returns,
                'return_rate': float(metrics.return_rate_percentage),
                'low_stock_items': metrics.low_stock_items,
                'out_of_stock_items': metrics.out_of_stock_items
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error calculating metrics: {str(e)}'
        })


# Utility functions for store management

def get_store_statistics(store, days=30):
    """Get comprehensive store statistics"""
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=days)

    # Sales data
    order_items = OrderItem.objects.filter(
        product__seller=store.owner,
        order__created_at__date__gte=start_date,
        order__status__in=['delivered', 'shipped', 'processing']
    )

    total_revenue = sum(item.get_total_price() for item in order_items)
    total_orders = order_items.values('order').distinct().count()
    total_items_sold = order_items.aggregate(total=Sum('quantity'))['total'] or 0

    # Product statistics
    total_products = Product.objects.filter(seller=store.owner).count()
    active_products = Product.objects.filter(seller=store.owner, is_active=True).count()

    # Stock statistics
    low_stock = Product.objects.filter(
        seller=store.owner,
        stock__quantity__lte=10,
        stock__quantity__gt=0
    ).count()

    out_of_stock = Product.objects.filter(
        seller=store.owner,
        stock__quantity=0
    ).count()

    return {
        'period_days': days,
        'revenue': {
            'total': float(total_revenue),
            'average_per_day': float(total_revenue / days),
            'average_per_order': float(total_revenue / total_orders) if total_orders > 0 else 0
        },
        'orders': {
            'total': total_orders,
            'average_per_day': total_orders / days,
            'items_per_order': total_items_sold / total_orders if total_orders > 0 else 0
        },
        'products': {
            'total': total_products,
            'active': active_products,
            'inactive': total_products - active_products
        },
        'stock': {
            'low_stock': low_stock,
            'out_of_stock': out_of_stock,
            'total_tracked': total_products
        }
    }


def validate_store_permissions(user, store):
    """Check if user has permission to manage the store"""
    if user == store.owner:
        return True

    if user.is_superuser:
        return True

    # Check if user is a store manager
    if hasattr(user, 'managed_stores') and store in user.managed_stores.all():
        return True

    return False


def get_store_dashboard_data(store):
    """Get all data needed for store dashboard"""
    stats = get_store_statistics(store)

    # Recent orders
    recent_orders = Order.objects.filter(
        items__product__seller=store.owner
    ).distinct().order_by('-created_at')[:5]

    # Top products
    top_products = Product.objects.filter(
        seller=store.owner
    ).annotate(
        total_sold=Sum('order_items__quantity'),
        total_revenue=Sum(F('order_items__quantity') * F('order_items__price_at_time'))
    ).filter(total_sold__gt=0).order_by('-total_revenue')[:5]

    return {
        'statistics': stats,
        'recent_orders': recent_orders,
        'top_products': top_products,
        'store': store
    }


@login_required
def create_store_referral(request, store_id):
    store = get_object_or_404(Store, id=store_id, status='active')

    if request.method == "POST":
        form = StoreReferralForm(request.POST)
        if form.is_valid():
            referred_email = form.cleaned_data['referred_email']

            # Avoid duplicate referral
            if StoreReferral.objects.filter(referrer=request.user, referred_email=referred_email, store=store).exists():
                messages.warning(request, "You already referred this email to this store.")
            else:
                referral = StoreReferral.objects.create(
                    referrer=request.user,
                    referred_email=referred_email,
                    store=store
                )

                referral_url = request.build_absolute_uri(
                    reverse("stores:store_detail", args=[store.slug]) + f"?ref={referral.referral_code}"
                )

                # Send referral email
                message = (
                    f"👋 {request.user.get_full_name()} has invited you to shop at {store.name} on EasyMarket!\n\n"
                    f"Use this referral link to visit the store and get special deals:\n{referral_url}\n\n"
                    f"Thanks for joining EasyMarket!"
                )

                send_email(
                    subject=f"{request.user.get_full_name()} invited you to EasyMarket",
                    message=message,
                    recipient_list=[referred_email]
                )

                messages.success(request, f"Referral sent to {referred_email}.")
        else:
            messages.error(request, "Please provide a valid email address.")

        return redirect("stores:store_detail", store.slug)

    # Fallback if accessed via GET (not intended)
    return redirect("stores:store_detail", store.slug)

def _user_owns_store(user, store):
    # Adjust according to your Store ownership fields
    return hasattr(store, "owner") and store.owner_id == user.id

@login_required
def store_promote(request, slug):
    store = get_object_or_404(Store, slug=slug)
    if not _user_owns_store(request.user, store) and not request.user.is_staff:
        return HttpResponseForbidden("You do not own this store.")

    plans = PromotionPlan.objects.all().order_by("price")
    active_sub = (PromotionSubscription.objects
                  .filter(store=store, is_active=True, start_at__lte=timezone.now(), end_at__gte=timezone.now())
                  .order_by("-created_at")
                  .first())
    campaigns = store.promo_campaigns.select_related("subscription", "store").prefetch_related("products")[:25]

    # products owned by this store (adjust filters to your schema: status/stock/etc.)
    store_products = Product.objects.filter(store=store).order_by("-id")[:500]

    return render(request, "stores/store_promote.html", {
        "store": store,
        "plans": plans,
        "active_sub": active_sub,
        "campaigns": campaigns,
        "placements": PromotionPlacement.choices,
        "store_products": store_products,  # NEW
    })

@login_required
@transaction.atomic
def create_subscription(request, slug):
    if request.method != "POST":
        raise Http404
    store = get_object_or_404(Store, slug=slug)
    if not _user_owns_store(request.user, store) and not request.user.is_staff:
        return HttpResponseForbidden("You do not own this store.")

    plan_id = request.POST.get("plan_id")
    plan = get_object_or_404(PromotionPlan, pk=plan_id)

    # Get requested placements from the form (checkboxes)
    requested_placements = request.POST.getlist("placements")
    if not requested_placements:
        messages.error(request, "Select at least one placement.")
        return redirect("stores:store_promote", slug=store.slug)
    if len(requested_placements) > plan.max_placements:
        messages.error(request, f"You can select up to {plan.max_placements} placements for {plan.name}.")
        return redirect("stores:store_promote", slug=store.slug)

    start_at = timezone.now()
    end_at = start_at + timedelta(days=plan.duration_days)

    # Deactivate overlapping subs if needed (business choice)
    PromotionSubscription.objects.filter(store=store, is_active=True, end_at__gte=start_at).update(is_active=False)

    sub = PromotionSubscription.objects.create(
        store=store,
        plan=plan,
        allowed_placements=requested_placements,
        start_at=start_at,
        end_at=end_at,
        is_active=True,
    )
    messages.success(request, f"Subscribed to {plan.name}. Valid until {end_at:%Y-%m-%d %H:%M}.")
    return redirect("stores:store_promote", slug=store.slug)

@login_required
@transaction.atomic
def create_campaign(request, slug):
    if request.method != "POST":
        raise Http404
    store = get_object_or_404(Store, slug=slug)
    if not _user_owns_store(request.user, store) and not request.user.is_staff:
        return HttpResponseForbidden("You do not own this store.")

    sub_id = request.POST.get("subscription_id")
    subscription = get_object_or_404(PromotionSubscription, pk=sub_id, store=store, is_active=True)

    placement = request.POST.get("placement")
    if placement not in (subscription.allowed_placements or []):
        messages.error(request, "This placement is not allowed by your subscription.")
        return redirect("stores:store_promote", slug=store.slug)

    title = (request.POST.get("title") or "").strip()
    headline = (request.POST.get("headline") or "").strip()
    message_body = (request.POST.get("message") or "").strip()
    audience = request.POST.get("audience") or PromotionCampaign.Audience.ALL_BUYERS

    # NEW: collect selected product IDs (multi-select)
    product_ids = request.POST.getlist("product_ids")
    # Sanitize to ints
    product_ids = [int(pid) for pid in product_ids if pid.isdigit()]

    try:
        scheduled_at = timezone.make_aware(timezone.datetime.fromisoformat(request.POST.get("scheduled_at")))
        expires_at = timezone.make_aware(timezone.datetime.fromisoformat(request.POST.get("expires_at")))
    except Exception:
        messages.error(request, "Invalid schedule window.")
        return redirect("stores:store_promote", slug=store.slug)

    if not title or not headline or not message_body:
        messages.error(request, "Please fill in title, headline, and message.")
        return redirect("stores:store_promote", slug=store.slug)

    # NEW: Validate products belong to this store
    if product_ids:
        qs = Product.objects.filter(id__in=product_ids, store=store)
        if qs.count() != len(product_ids):
            messages.error(request, "One or more selected products are invalid or not in your store.")
            return redirect("stores:store_promote", slug=store.slug)
        # enforce plan limit
        max_products = getattr(subscription.plan, "max_products_per_campaign", 8)
        if len(product_ids) > max_products:
            messages.error(request, f"You can attach up to {max_products} products to a campaign for your plan.")
            return redirect("stores:store_promote", slug=store.slug)

    campaign = PromotionCampaign.objects.create(
        store=store,
        subscription=subscription,
        placement=placement,
        audience=audience,
        title=title,
        headline=headline,
        message=message_body,
        scheduled_at=scheduled_at,
        expires_at=expires_at,
        status=PromotionCampaign.Status.PENDING,
    )

    # NEW: attach products
    if product_ids:
        campaign.products.add(*product_ids)

    messages.success(request, "Campaign submitted for review. We’ll refine the copy and approve it.")
    return redirect("stores:store_promote", slug=store.slug)

@login_required
@transaction.atomic
def push_campaign(request, slug, pk):
    """Admin/staff action to approve & push a campaign.
       You can expose this behind a staff-only button in the UI or just use the admin."""
    store = get_object_or_404(Store, slug=slug)
    campaign = get_object_or_404(PromotionCampaign, pk=pk, store=store)

    if not request.user.is_staff:
        return HttpResponseForbidden("Only staff can push campaigns.")

    ok, reason = campaign.can_go_live()
    if not ok:
        messages.error(request, f"Cannot go live: {reason}")
        return redirect("stores:store_promote", slug=store.slug)

    # Mark approved/live
    campaign.status = PromotionCampaign.Status.LIVE
    campaign.reviewer = request.user
    campaign.review_note = "Approved & pushed."
    campaign.save(update_fields=["status", "reviewer", "review_note", "updated_at"])

    # --- PLACEHOLDER PUSH ACTIONS ---
    # Implement your real integrations here:
    # - Homepage/Category/Trending: pull via templatetag into those pages
    # - Push notifications: OneSignal/Firebase
    # - Email: your mail backend & subscriber list
    # - Deals page / Spotlight: page sections read active campaigns
    # --------------------------------

    messages.success(request, "Campaign is now LIVE.")
    return redirect("stores:store_promote", slug=store.slug)


@login_required
def campaign_detail(request, slug, campaign_id):
    """
    Display detailed view of a specific campaign
    """
    store = get_object_or_404(Store, slug=slug)

    # Check permissions - store owner or staff
    if not (request.user == store.owner or request.user.is_staff):
        messages.error(request, "You don't have permission to view this campaign.")
        return redirect('stores:store_promote', slug=slug)

    campaign = get_object_or_404(PromotionCampaign, id=campaign_id, store=store)

    # Calculate additional metrics (you might have these fields in your model)
    # If not, you can remove or modify these calculations
    context = {
        'store': store,
        'campaign': campaign,
        'can_edit': request.user == store.owner or request.user.is_staff,
        'can_approve': request.user.is_staff and campaign.status == 'pending',
    }

    return render(request, 'stores/campaign_detail.html', context)


@login_required
@require_POST
def campaign_submit_review(request, slug, campaign_id):
    """
    Submit campaign for review
    """
    store = get_object_or_404(Store, slug=slug)

    if request.user != store.owner and not request.user.is_staff:
        return JsonResponse({'success': False, 'message': 'Permission denied'})

    campaign = get_object_or_404(PromotionCampaign, id=campaign_id, store=store)

    if campaign.status != 'draft':
        return JsonResponse({'success': False, 'message': 'Campaign is not in draft status'})

    campaign.status = PromotionCampaign.Status.PENDING
    campaign.save(update_fields=['status', 'updated_at'])

    return JsonResponse({'success': True, 'message': 'Campaign submitted for review'})


@login_required
@require_POST
def campaign_approve(request, slug, campaign_id):
    """
    Approve campaign (staff only)
    """
    if not request.user.is_staff:
        return JsonResponse({'success': False, 'message': 'Permission denied'})

    store = get_object_or_404(Store, slug=slug)
    campaign = get_object_or_404(PromotionCampaign, id=campaign_id, store=store)

    if campaign.status != 'pending':
        return JsonResponse({'success': False, 'message': 'Campaign is not pending approval'})

    # Check if campaign can go live
    can_go_live, reason = campaign.can_go_live()
    if not can_go_live:
        return JsonResponse({'success': False, 'message': f'Cannot approve: {reason}'})

    campaign.status = PromotionCampaign.Status.APPROVED
    campaign.reviewer = request.user
    campaign.review_note = "Campaign approved and ready to go live"
    campaign.save(update_fields=['status', 'reviewer', 'review_note', 'updated_at'])

    return JsonResponse({'success': True, 'message': 'Campaign approved successfully'})


@login_required
@require_POST
def campaign_reject(request, slug, campaign_id):
    """
    Reject campaign (staff only)
    """
    if not request.user.is_staff:
        return JsonResponse({'success': False, 'message': 'Permission denied'})

    store = get_object_or_404(Store, slug=slug)
    campaign = get_object_or_404(PromotionCampaign, id=campaign_id, store=store)

    if campaign.status != 'pending':
        return JsonResponse({'success': False, 'message': 'Campaign is not pending review'})

    try:
        data = json.loads(request.body)
        reason = data.get('reason', 'No reason provided')
    except json.JSONDecodeError:
        reason = 'No reason provided'

    campaign.status = PromotionCampaign.Status.REJECTED
    campaign.reviewer = request.user
    campaign.review_note = f"Campaign rejected: {reason}"
    campaign.save(update_fields=['status', 'reviewer', 'review_note', 'updated_at'])

    return JsonResponse({'success': True, 'message': 'Campaign rejected'})


@login_required
@require_POST
def campaign_pause(request, slug, campaign_id):
    """
    Pause a live campaign
    """
    store = get_object_or_404(Store, slug=slug)

    if request.user != store.owner and not request.user.is_staff:
        return JsonResponse({'success': False, 'message': 'Permission denied'})

    campaign = get_object_or_404(PromotionCampaign, id=campaign_id, store=store)

    if campaign.status != 'live':
        return JsonResponse({'success': False, 'message': 'Campaign is not currently live'})

    # You might want to add a 'paused' status to your model
    # For now, we'll set it back to approved
    campaign.status = PromotionCampaign.Status.APPROVED
    campaign.review_note = f"Campaign paused by {request.user.get_full_name() or request.user.username}"
    campaign.save(update_fields=['status', 'review_note', 'updated_at'])

    return JsonResponse({'success': True, 'message': 'Campaign paused successfully'})


@login_required
@require_POST
def campaign_stop(request, slug, campaign_id):
    """
    Stop a campaign permanently
    """
    store = get_object_or_404(Store, slug=slug)

    if request.user != store.owner and not request.user.is_staff:
        return JsonResponse({'success': False, 'message': 'Permission denied'})

    campaign = get_object_or_404(PromotionCampaign, id=campaign_id, store=store)

    if campaign.status not in ['live', 'approved']:
        return JsonResponse({'success': False, 'message': 'Campaign cannot be stopped'})

    campaign.status = PromotionCampaign.Status.EXPIRED
    campaign.expires_at = timezone.now()  # Set expiry to now
    campaign.review_note = f"Campaign stopped by {request.user.get_full_name() or request.user.username}"
    campaign.save(update_fields=['status', 'expires_at', 'review_note', 'updated_at'])

    return JsonResponse({'success': True, 'message': 'Campaign stopped successfully'})


@login_required
@require_POST
def campaign_duplicate(request, slug, campaign_id):
    """
    Create a duplicate of the campaign
    """
    store = get_object_or_404(Store, slug=slug)

    if request.user != store.owner and not request.user.is_staff:
        return JsonResponse({'success': False, 'message': 'Permission denied'})

    original_campaign = get_object_or_404(PromotionCampaign, id=campaign_id, store=store)

    try:
        with transaction.atomic():
            # Create a duplicate campaign
            new_campaign = PromotionCampaign.objects.create(
                store=store,
                subscription=original_campaign.subscription,
                placement=original_campaign.placement,
                audience=original_campaign.audience,
                title=f"Copy of {original_campaign.title}",
                headline=original_campaign.headline,
                message=original_campaign.message,
                banner_image=original_campaign.banner_image,
                scheduled_at=timezone.now() + timedelta(hours=24),  # Schedule for tomorrow
                expires_at=timezone.now() + timedelta(days=7),  # 1 week campaign
                status=PromotionCampaign.Status.DRAFT,
            )

            return JsonResponse({
                'success': True,
                'message': 'Campaign duplicated successfully',
                'new_campaign_id': new_campaign.id
            })

    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Error duplicating campaign: {str(e)}'})


@login_required
@require_http_methods(["DELETE"])
def campaign_delete(request, slug, campaign_id):
    """
    Delete a campaign (only draft or rejected campaigns)
    """
    store = get_object_or_404(Store, slug=slug)

    if request.user != store.owner and not request.user.is_staff:
        return JsonResponse({'success': False, 'message': 'Permission denied'})

    campaign = get_object_or_404(PromotionCampaign, id=campaign_id, store=store)

    if campaign.status not in ['draft', 'rejected']:
        return JsonResponse({'success': False, 'message': 'Only draft or rejected campaigns can be deleted'})

    try:
        campaign_title = campaign.title
        campaign.delete()
        return JsonResponse({'success': True, 'message': f'Campaign "{campaign_title}" deleted successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Error deleting campaign: {str(e)}'})


@login_required
def campaign_download_report(request, slug, campaign_id):
    """
    Download campaign performance report
    """
    store = get_object_or_404(Store, slug=slug)

    if request.user != store.owner and not request.user.is_staff:
        messages.error(request, "You don't have permission to download this report.")
        return redirect('stores:campaign_detail', slug=slug, campaign_id=campaign_id)

    campaign = get_object_or_404(PromotionCampaign, id=campaign_id, store=store)

    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="campaign_{campaign.id}_report.csv"'

    import csv
    writer = csv.writer(response)

    # Write campaign details
    writer.writerow(['Campaign Report'])
    writer.writerow(['Campaign ID', campaign.id])
    writer.writerow(['Campaign Title', campaign.title])
    writer.writerow(['Campaign Headline', campaign.headline])
    writer.writerow(['Store', campaign.store.name])
    writer.writerow(['Status', campaign.get_status_display()])
    writer.writerow(['Placement', campaign.get_placement_display()])
    writer.writerow(['Audience', campaign.get_audience_display()])
    writer.writerow(['Created', campaign.created_at.strftime('%Y-%m-%d %H:%M')])
    writer.writerow(['Scheduled', campaign.scheduled_at.strftime('%Y-%m-%d %H:%M')])
    writer.writerow(['Expires', campaign.expires_at.strftime('%Y-%m-%d %H:%M')])
    writer.writerow([])

    # Write performance metrics (if you have these fields)
    writer.writerow(['Performance Metrics'])
    writer.writerow(['Metric', 'Value'])
    writer.writerow(['Impressions', getattr(campaign, 'impressions', 0)])
    writer.writerow(['Clicks', getattr(campaign, 'clicks', 0)])
    writer.writerow(
        ['Click Rate', f"{(getattr(campaign, 'clicks', 0) / max(getattr(campaign, 'impressions', 1), 1) * 100):.2f}%"])
    writer.writerow(['Budget Spent', f"D{getattr(campaign, 'budget_spent', 0):.2f}"])
    writer.writerow(['Conversions', getattr(campaign, 'conversions', 0)])
    writer.writerow(['ROI', f"{getattr(campaign, 'roi', 0):.1f}%"])

    return response


@login_required
@require_POST
def campaign_request_changes(request, slug, campaign_id):
    """
    Request changes to a campaign (staff only)
    """
    if not request.user.is_staff:
        return JsonResponse({'success': False, 'message': 'Permission denied'})

    store = get_object_or_404(Store, slug=slug)
    campaign = get_object_or_404(PromotionCampaign, id=campaign_id, store=store)

    if campaign.status != 'pending':
        return JsonResponse({'success': False, 'message': 'Campaign is not pending review'})

    try:
        data = json.loads(request.body)
        changes = data.get('changes', 'No changes specified')
    except json.JSONDecodeError:
        changes = 'No changes specified'

    campaign.status = PromotionCampaign.Status.DRAFT  # Send back to draft
    campaign.reviewer = request.user
    campaign.review_note = f"Changes requested: {changes}"
    campaign.save(update_fields=['status', 'reviewer', 'review_note', 'updated_at'])

    return JsonResponse({'success': True, 'message': 'Changes requested successfull'})


def _user_has_store_access(user):
    """
    Helper: check if user is a store owner or manager.
    Adjust logic if you have a custom store-owner profile.
    """
    if not user.is_authenticated:
        return False

    # Owner or manager of at least one store
    return Store.objects.filter(
        Q(owner=user) | Q(managers=user)
    ).exists()


@login_required
def b2b_marketplace(request):
    """
    B2B marketplace view:
    - Only accessible to store owners / managers
    - Shows B2B suppliers (local & international)
    - Shows B2B products with wholesale options
    - If called via AJAX with ?product_id=XX, returns JSON for the modal
    """
    user = request.user

    # Restrict to users who have a store relationship
    if not _user_has_store_access(user):
        return redirect("home")

    # ---------- AJAX: Product detail for modal ----------
    product_id = request.GET.get("product_id")
    if request.headers.get("x-requested-with") == "XMLHttpRequest" and product_id:
        product = get_object_or_404(
            Product,
            id=product_id,
            visible_in_b2b=True,
            is_available_b2b=True,
            is_active=True,
            store__allows_b2b=True,
            store__status="active",
        )

        # Decide which price to show
        price = product.b2b_price if getattr(product, "b2b_price", None) else product.price

        # Handle image URL safely
        image_url = product.image.url if getattr(product, "image", None) else ""

        # Tier pricing – assume it's a dict/JSONField, otherwise send empty
        tier_price = getattr(product, "b2b_tier_price", None) or {}

        data = {
            "id": product.id,
            "name": product.name,
            "store_name": product.store.name,
            "store_id": product.store.id,
            "image": image_url,
            "price": str(price) if price is not None else "",
            "moq": product.b2b_min_quantity or "",
            "description": product.description or "",
            "tier_price": tier_price,
        }
        return JsonResponse(data)

    # ---------- Normal page render ----------
    # --- Filters / search ---
    filter_type = request.GET.get("filter", "all")
    search_query = request.GET.get("q", "").strip()

    # Base queryset: only stores that allow B2B and are active
    store_qs = Store.objects.filter(
        allows_b2b=True,
        status="active",
    )

    # Apply filter for international / local / my_country
    if filter_type == "international":
        store_qs = store_qs.filter(is_international_supplier=True)
    elif filter_type == "local":
        store_qs = store_qs.filter(is_international_supplier=False)
    elif filter_type == "my_country":
        # TODO: use user's real country if you store it
        user_country = "Gambia"
        store_qs = store_qs.filter(country__iexact=user_country)

    # Search across store name and description fields
    if search_query:
        store_qs = store_qs.filter(
            Q(name__icontains=search_query)
            | Q(short_description__icontains=search_query)
            | Q(description__icontains=search_query)
        )

    # Separate for highlighting in template
    international_suppliers = store_qs.filter(is_international_supplier=True)
    local_suppliers = store_qs.filter(is_international_supplier=False)

    # --- B2B products ---
    product_qs = Product.objects.filter(
        visible_in_b2b=True,
        is_available_b2b=True,
        is_active=True,
        store__allows_b2b=True,
        store__status="active",
    ).select_related("store", "category")

    # Only products from the currently-filtered stores
    product_qs = product_qs.filter(store__in=store_qs)

    # Product-level search (name, description, store name)
    if search_query:
        product_qs = product_qs.filter(
            Q(name__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(store__name__icontains=search_query)
        )

    # Order products by something meaningful for B2B
    product_qs = product_qs.order_by(
        "-store__is_international_supplier",
        "-created_at",
    )

    b2b_cart_count = 0
    if request.user.is_authenticated:
        cart = B2BCart.objects.filter(buyer=request.user, is_active=True).first()
        if cart:
            b2b_cart_count = cart.items.count()

    # Pagination for products
    paginator = Paginator(product_qs, 24)  # 24 products per page
    page_number = request.GET.get("page")
    products_page = paginator.get_page(page_number)

    # Your store for "Home" link in breadcrumb
    my_store = Store.objects.filter(owner=user, status="active").first()

    context = {
        "filter_type": filter_type,
        "search_query": search_query,
        "international_suppliers": international_suppliers,
        "local_suppliers": local_suppliers,
        "products_page": products_page,
        "stores_count": store_qs.count(),
        "products_count": product_qs.count(),
        "my_store": my_store,
        "b2b_cart_count": b2b_cart_count,
    }
    return render(request, "b2b/b2b_marketplace.html", context)

@login_required
def b2b_settings(request, slug):
    user = request.user

    store = get_object_or_404(
        Store.objects.filter(
            Q(owner=user) | Q(managers=user),
            status__in=["active", "pending", "suspended"],
        ),
        slug=slug,
    )

    products = Product.objects.filter(store=store).order_by("-created_at")

    if request.method == "POST":
        # ------------- STORE-LEVEL B2B SETTINGS -------------
        store.allows_b2b = request.POST.get("allows_b2b") == "on"
        store.is_b2b_only = request.POST.get("is_b2b_only") == "on"
        store.is_international_supplier = request.POST.get("is_international_supplier") == "on"
        store.b2b_description = request.POST.get("b2b_description", "").strip()

        raw_min_amount = request.POST.get("b2b_min_order_amount", "").strip()
        if raw_min_amount:
            try:
                store.b2b_min_order_amount = Decimal(raw_min_amount)
            except (InvalidOperation, TypeError):
                store.b2b_min_order_amount = None
                messages.warning(request, "Invalid B2B minimum order amount – cleared.")
        else:
            store.b2b_min_order_amount = None

        # 🔹 NEW: contact preferences
        store.b2b_contact_email = request.POST.get("b2b_contact_email", "").strip() or None
        store.b2b_whatsapp_number = request.POST.get("b2b_whatsapp_number", "").strip()
        store.b2b_preferred_channel = request.POST.get("b2b_preferred_channel") or "email"

        store.save()

        # ------------- PRODUCT-LEVEL B2B SETTINGS (unchanged) -------------
        for product in products:
            prefix = f"product_{product.id}_"

            product.visible_in_b2b = request.POST.get(prefix + "visible_in_b2b") == "on"
            product.is_available_b2b = request.POST.get(prefix + "is_available_b2b") == "on"

            raw_b2b_price = request.POST.get(prefix + "b2b_price", "").strip()
            if raw_b2b_price:
                try:
                    product.b2b_price = Decimal(raw_b2b_price)
                except (InvalidOperation, TypeError):
                    product.b2b_price = None
            else:
                product.b2b_price = None

            raw_min_qty = request.POST.get(prefix + "b2b_min_quantity", "").strip()
            try:
                product.b2b_min_quantity = int(raw_min_qty) if raw_min_qty else 1
            except ValueError:
                product.b2b_min_quantity = 1

            raw_tier_json = request.POST.get(prefix + "b2b_tier_price", "").strip()
            if raw_tier_json:
                try:
                    parsed = json.loads(raw_tier_json)
                    if isinstance(parsed, dict):
                        product.b2b_tier_price = parsed
                    else:
                        product.b2b_tier_price = None
                        messages.warning(
                            request,
                            f"Invalid tier pricing format for {product.name}. Expected JSON object."
                        )
                except json.JSONDecodeError:
                    product.b2b_tier_price = None
                    messages.warning(
                        request,
                        f"Could not parse B2B tier pricing JSON for {product.name}."
                    )
            else:
                product.b2b_tier_price = None

            product.save()

        messages.success(request, "B2B settings updated successfully.")
        return redirect("stores:b2b_settings", slug=store.slug)

    context = {
        "store": store,
        "products": products,
    }
    return render(request, "b2b/b2b_settings.html", context)

@login_required
@require_POST
def create_b2b_inquiry(request):
    # ✅ Force JSON response expectation (optional but nice)
    # if request.headers.get("X-Requested-With") != "XMLHttpRequest":
    #     return JsonResponse({"success": False, "error": "AJAX required."}, status=400)

    store_id = (request.POST.get("store_id") or "").strip()
    product_id = (request.POST.get("product_id") or "").strip()  # optional
    message_text = (request.POST.get("message") or "").strip()
    preferred_channel = (request.POST.get("preferred_channel") or "email").strip()

    if not store_id or not message_text:
        return JsonResponse({"success": False, "error": "Missing store or message."}, status=400)

    store = Store.objects.filter(id=store_id, allows_b2b=True).select_related("owner").first()
    if not store:
        return JsonResponse({"success": False, "error": "Store not available for B2B."}, status=404)

    product = None
    if product_id:
        product = Product.objects.filter(id=product_id, store=store).first()

    inquiry = B2BInquiry.objects.create(
        store=store,
        buyer=request.user,
        product=product,
        message=message_text,
        preferred_channel=preferred_channel,
        created_at=timezone.now() if hasattr(B2BInquiry, "created_at") else None,
    )

    # ----------------- EMAIL NOTIFICATION -----------------
    to_email = getattr(store, "b2b_contact_email", None) or getattr(store.owner, "email", None)
    if to_email:
        buyer = request.user
        buyer_email = getattr(buyer, "email", "")
        buyer_phone = getattr(getattr(buyer, "profile", None), "phone_number", "")

        subject = f"New B2B inquiry on EasyMarket – {store.name}"

        lines = [
            f"Dear {store.name},",
            "",
            "You have received a new B2B negotiation request on EasyMarket.",
            "",
            f"Store: {store.name}",
            f"Inquiry ID: #{inquiry.id}",
        ]
        if product:
            lines.append(f"Product: {product.name}")
        lines += [
            "",
            "Message from buyer:",
            message_text,
            "",
            "Buyer contact details:",
            f"Name: {buyer.get_full_name() or buyer.username}",
            f"Email: {buyer_email or 'N/A'}",
            f"Phone / WhatsApp: {buyer_phone or 'N/A'}",
            "",
            "Preferred negotiation channel:",
            f"- Buyer selected: {preferred_channel}",
            f"- Store preference: {getattr(store, 'b2b_preferred_channel', 'N/A')}",
            "",
            "EasyMarket B2B",
        ]
        body = "\n".join(lines)

        send_mail(
            subject,
            body,
            getattr(settings, "DEFAULT_FROM_EMAIL", None),
            [to_email],
            fail_silently=True,
        )

    return JsonResponse({"success": True, "message": "Inquiry sent successfully."})


@login_required
def b2b_counts(request, store_id):
    store = get_object_or_404(Store, id=store_id)

    # orders count (exclude cancelled)
    orders_count = B2BOrder.objects.filter(store=store).exclude(Q(status="cancelled") | Q(status="shipped") | Q(status="delivered")).count()

    # cart count (active cart items for this user)
    cart = B2BCart.objects.filter(buyer=request.user, is_active=True).first()
    cart_count = cart.items.count() if cart else 0

    return JsonResponse({
        "orders": orders_count,
        "cart": cart_count,
    })


@login_required
@require_http_methods(["GET", "POST"])
def store_theme_settings(request, store_id):
    """
    Comprehensive store theme customization view
    """
    store = get_object_or_404(Store, id=store_id)

    # Check if user is owner or manager
    if store.owner != request.user and not store.managers.filter(id=request.user.id).exists():
        messages.error(request, "You don't have permission to edit this store's theme.")
        return redirect('stores:store_detail', slug=store.slug)

    if request.method == 'POST':
        form = StoreThemeForm(request.POST, instance=store)

        if form.is_valid():
            # Save the theme settings
            updated_store = form.save(commit=False)
            updated_store.theme_updated_at = timezone.now()
            updated_store.save()

            messages.success(
                request,
                '🎨 Theme settings saved successfully! Your store has been updated.',
                extra_tags='theme-success'
            )

            # Return JSON for AJAX requests
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': 'Theme updated successfully!',
                    'store_url': store.get_absolute_url()
                })

            # Redirect to preview the changes
            return redirect('stores:store_detail', slug=store.slug)
        else:
            messages.error(
                request,
                'There were errors in your theme settings. Please check the form.',
                extra_tags='theme-error'
            )

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'errors': form.errors
                }, status=400)
    else:
        form = StoreThemeForm(instance=store)

    context = {
        'store': store,
        'theme_form': form,
        'active_tab': 'theme',
        'page_title': f'Theme Settings - {store.name}',
    }

    return render(request, 'stores/store_theme_settings.html', context)


@login_required
@require_http_methods(["POST"])
def apply_theme_preset(request, store_id):
    """
    Quick apply a theme preset
    """
    store = get_object_or_404(Store, id=store_id)

    # Check permissions
    if store.owner != request.user and not store.managers.filter(id=request.user.id).exists():
        return JsonResponse({
            'success': False,
            'message': "You don't have permission to edit this store."
        }, status=403)

    preset_name = request.POST.get('preset')

    # Theme presets configuration
    THEME_PRESETS = {
        'modern': {
            'theme_preset': 'modern',
            'primary_color': '#2563eb',
            'secondary_color': '#64748b',
            'accent_color': '#f59e0b',
            'background_color': '#ffffff',
            'text_color': '#1e293b',
            'font_heading': 'poppins',
            'font_body': 'inter',
            'product_card_style': 'shadow',
            'cta_button_style': 'rounded',
        },
        'elegant': {
            'theme_preset': 'elegant',
            'primary_color': '#1f2937',
            'secondary_color': '#d4af37',
            'accent_color': '#b8860b',
            'background_color': '#faf9f6',
            'text_color': '#1f2937',
            'font_heading': 'playfair',
            'font_body': 'lato',
            'product_card_style': 'border',
            'cta_button_style': 'square',
        },
        'vibrant': {
            'theme_preset': 'vibrant',
            'primary_color': '#ec4899',
            'secondary_color': '#8b5cf6',
            'accent_color': '#f59e0b',
            'background_color': '#ffffff',
            'text_color': '#111827',
            'font_heading': 'montserrat',
            'font_body': 'roboto',
            'product_card_style': 'elevated',
            'cta_button_style': 'pill',
        },
        'minimal': {
            'theme_preset': 'minimal',
            'primary_color': '#000000',
            'secondary_color': '#6b7280',
            'accent_color': '#ffffff',
            'background_color': '#ffffff',
            'text_color': '#000000',
            'font_heading': 'inter',
            'font_body': 'inter',
            'product_card_style': 'minimal',
            'cta_button_style': 'square',
        },
        'dark': {
            'theme_preset': 'dark',
            'primary_color': '#3b82f6',
            'secondary_color': '#6366f1',
            'accent_color': '#10b981',
            'background_color': '#111827',
            'text_color': '#f9fafb',
            'font_heading': 'inter',
            'font_body': 'roboto',
            'product_card_style': 'shadow',
            'cta_button_style': 'rounded',
        },
        'classic': {
            'theme_preset': 'classic',
            'primary_color': '#1e40af',
            'secondary_color': '#475569',
            'accent_color': '#dc2626',
            'background_color': '#f8fafc',
            'text_color': '#1e293b',
            'font_heading': 'merriweather',
            'font_body': 'lato',
            'product_card_style': 'border',
            'cta_button_style': 'rounded',
        },
        'creative': {
            'theme_preset': 'creative',
            'primary_color': '#7c3aed',
            'secondary_color': '#ec4899',
            'accent_color': '#f59e0b',
            'background_color': '#fef3c7',
            'text_color': '#1f2937',
            'font_heading': 'montserrat',
            'font_body': 'poppins',
            'product_card_style': 'elevated',
            'cta_button_style': 'pill',
        },
        'professional': {
            'theme_preset': 'professional',
            'primary_color': '#0f172a',
            'secondary_color': '#334155',
            'accent_color': '#0ea5e9',
            'background_color': '#ffffff',
            'text_color': '#0f172a',
            'font_heading': 'raleway',
            'font_body': 'roboto',
            'product_card_style': 'shadow',
            'cta_button_style': 'square',
        },
    }

    if preset_name not in THEME_PRESETS:
        return JsonResponse({
            'success': False,
            'message': 'Invalid theme preset selected.'
        }, status=400)

    # Apply the preset
    preset_data = THEME_PRESETS[preset_name]
    for field, value in preset_data.items():
        setattr(store, field, value)

    store.theme_updated_at = timezone.now()
    store.save()

    return JsonResponse({
        'success': True,
        'message': f'{preset_name.title()} theme applied successfully!',
        'preset_data': preset_data,
        'store_url': store.get_absolute_url()
    })


@login_required
@require_http_methods(["GET"])
def preview_theme(request, store_id):
    """
    Generate a preview of theme changes without saving
    """
    store = get_object_or_404(Store, id=store_id)

    # Check permissions
    if store.owner != request.user and not store.managers.filter(id=request.user.id).exists():
        return JsonResponse({
            'success': False,
            'message': "You don't have permission to preview this store."
        }, status=403)

    # Get preview parameters from query string
    theme_data = {
        'primary_color': request.GET.get('primary_color', store.primary_color),
        'secondary_color': request.GET.get('secondary_color', store.secondary_color),
        'accent_color': request.GET.get('accent_color', store.accent_color),
        'background_color': request.GET.get('background_color', store.background_color),
        'text_color': request.GET.get('text_color', store.text_color),
        'font_heading': request.GET.get('font_heading', store.font_heading),
        'font_body': request.GET.get('font_body', store.font_body),
        'product_card_style': request.GET.get('product_card_style', store.product_card_style),
        'cta_button_style': request.GET.get('cta_button_style', store.cta_button_style),
    }

    return JsonResponse({
        'success': True,
        'theme_data': theme_data,
        'css_variables': {
            '--store-primary': theme_data['primary_color'],
            '--store-secondary': theme_data['secondary_color'],
            '--store-accent': theme_data['accent_color'],
            '--store-background': theme_data['background_color'],
            '--store-text': theme_data['text_color'],
        }
    })


@login_required
@require_http_methods(["POST"])
def reset_theme(request, store_id):
    """
    Reset store theme to default settings
    """
    store = get_object_or_404(Store, id=store_id)

    # Check permissions
    if store.owner != request.user and not store.managers.filter(id=request.user.id).exists():
        return JsonResponse({
            'success': False,
            'message': "You don't have permission to edit this store."
        }, status=403)

    # Reset to default theme
    default_theme = {
        'theme_preset': 'modern',
        'primary_color': '#2563eb',
        'secondary_color': '#64748b',
        'accent_color': '#f59e0b',
        'background_color': '#ffffff',
        'text_color': '#1e293b',
        'font_heading': 'poppins',
        'font_body': 'inter',
        'product_layout': 'grid',
        'products_per_row': 4,
        'product_card_style': 'shadow',
        'product_image_shape': 'square',
        'cta_button_style': 'rounded',
        'cta_button_text': 'Shop Now',
        'banner_overlay_opacity': 30,
        'banner_height': 'medium',
        'enable_animations': True,
        'enable_hover_effects': True,
        'enable_parallax_banner': False,
        'show_product_ratings': True,
        'show_product_badges': True,
        'show_quick_view': True,
        'show_store_description': True,
        'show_store_stats': True,
        'show_social_links': True,
        'show_operating_hours': True,
        'custom_css': '',
    }

    for field, value in default_theme.items():
        setattr(store, field, value)

    store.theme_updated_at = timezone.now()
    store.save()

    messages.success(request, 'Theme has been reset to default settings.')

    return JsonResponse({
        'success': True,
        'message': 'Theme reset to default successfully!',
        'redirect_url': reverse('stores:store_theme_settings', kwargs={'store_id': store_id})
    })


@login_required
@require_http_methods(["POST"])
def duplicate_theme(request, source_store_id, target_store_id):
    """
    Copy theme settings from one store to another
    """
    source_store = get_object_or_404(Store, id=source_store_id)
    target_store = get_object_or_404(Store, id=target_store_id)

    # Check permissions for both stores
    if (target_store.owner != request.user and
            not target_store.managers.filter(id=request.user.id).exists()):
        return JsonResponse({
            'success': False,
            'message': "You don't have permission to edit the target store."
        }, status=403)

    # Theme fields to copy
    theme_fields = [
        'theme_preset', 'primary_color', 'secondary_color', 'accent_color',
        'background_color', 'text_color', 'font_heading', 'font_body',
        'product_layout', 'products_per_row', 'product_card_style',
        'product_image_shape', 'cta_button_style', 'cta_button_text',
        'banner_overlay_opacity', 'banner_height', 'enable_animations',
        'enable_hover_effects', 'enable_parallax_banner', 'show_product_ratings',
        'show_product_badges', 'show_quick_view', 'show_store_description',
        'show_store_stats', 'show_social_links', 'show_operating_hours',
        'enable_featured_products', 'enable_new_arrivals', 'enable_best_sellers',
        'custom_css',
    ]

    # Copy theme settings
    for field in theme_fields:
        setattr(target_store, field, getattr(source_store, field))

    target_store.theme_updated_at = timezone.now()
    target_store.save()

    messages.success(
        request,
        f'Theme copied from {source_store.name} to {target_store.name} successfully!'
    )

    return JsonResponse({
        'success': True,
        'message': 'Theme duplicated successfully!',
        'redirect_url': reverse('stores:store_theme_settings', kwargs={'store_id': target_store_id})
    })