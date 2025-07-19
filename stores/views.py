from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q
from django.utils import timezone
from django.db import models
from datetime import datetime, timedelta
import calendar
import json
from django.views.decorators.http import require_http_methods
from django.http import Http404
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import HttpResponseRedirect
from django.utils.text import slugify
from django.db.models import Q, Avg, F, FloatField, DecimalField, ExpressionWrapper
from django.db.models.functions import Coalesce
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.forms import modelformset_factory
from chat.models import ChatThread, ChatMessage
from django.contrib.auth import get_user_model
from marketplace.models import Product, ProductImage, ProductVariant
from .forms import ProductForm, ProductImageForm, ProductVariantForm
from django.db import transaction
import re
from .models import Store
from reviews.models import Review
from marketplace.models import Product, Category, ProductImage
from orders.models import ChatMessage
from orders.models import Order, OrderItem, PromoCode
from django.http import HttpResponseForbidden
from functools import wraps
from .forms import ProductForm, ProductImageForm
from stock.models import Stock
import csv

from .models import (
    Store, StoreHours, StoreShippingZone, StoreReturnSettings,
    StoreInventoryTracking, StoreMetrics
)
from .forms import (
    StoreSettingsForm, StoreHoursFormSet, StoreShippingZoneFormSet,
    StoreReturnSettingsForm, StoreFinancialForm
)

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

# Add these public store views as well
def store_detail(request, slug):
    """Public store detail page."""
    store = get_object_or_404(Store, slug=slug, status='active')

    # Get products by this store owner
    products = Product.objects.filter(seller=store.owner).order_by('-created_at')[:8]
    product_ids = products.values_list('id', flat=True)

    # Recent reviews
    recent_reviews = Review.objects.filter(product_id__in=product_ids).select_related('user').order_by('-created_at')[:5]

    # All reviews for this store's products
    reviews = Review.objects.filter(product_id__in=product_ids)
    review_count = reviews.count()
    average_rating = reviews.aggregate(avg=Avg('rating'))['avg'] or 0

    # Rating breakdown
    rating_breakdown = {i: reviews.filter(rating=i).count() for i in range(1, 6)}

    # Get store's product categories with product counts
    categories = (
        Category.objects
        .filter(product__seller=store.owner)
        .annotate(product_count=Count('product'))
        .distinct()
    )

    context = {
        'store': store,
        'products': products,
        'review_count': review_count,
        'average_rating': round(average_rating, 1),
        'rating_breakdown': rating_breakdown,
        'rating_order': [5, 4, 3, 2, 1],
        'recent_reviews': recent_reviews,
        'categories': categories,
    }
    return render(request, 'stores/store_detail.html', context)


def store_products(request, slug):
    """Public store products page."""
    store = get_object_or_404(Store, slug=slug, status='active')  # Using status field

    # Get all products by this store owner
    products = Product.objects.filter(seller=store.owner, is_active=True).order_by('-created_at')
    # Get all categories used by this store's products
    categories = (
        Category.objects
        .filter(product__seller=store.owner)
        .annotate(product_count=Count('product'))
        .distinct()
    )
    # Add pagination
    from django.core.paginator import Paginator
    paginator = Paginator(products, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'store': store,
        'products': page_obj,
        'categories': categories,

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
    """Edit a product, including images, variants, stock, and visibility."""
    store = get_object_or_404(Store, id=store_id, owner=request.user)
    product = get_object_or_404(Product, id=product_id, seller=request.user)
    stock, _ = Stock.objects.get_or_create(product=product)

    ImageFormSet = modelformset_factory(ProductImage, form=ProductImageForm, extra=5, can_delete=False)
    VariantFormSet = modelformset_factory(ProductVariant, form=ProductVariantForm, extra=10, can_delete=False)

    if request.method == 'POST':
        product_form = ProductForm(request.POST, request.FILES, instance=product)
        image_formset = ImageFormSet(request.POST, request.FILES, queryset=ProductImage.objects.none())
        variant_formset = VariantFormSet(request.POST, queryset=ProductVariant.objects.filter(product=product))
        stock_quantity = request.POST.get('stock_quantity')

        # Handle promo code removals
        for promo in product.promo_codes.all():
            if request.POST.get(f'remove_promo_{promo.id}'):
                product.promo_codes.remove(promo)

        # Assign existing promo
        existing_promo_id = request.POST.get('existing_promo')
        if existing_promo_id:
            try:
                promo = PromoCode.objects.get(id=existing_promo_id)
                promo.products.add(product)
            except PromoCode.DoesNotExist:
                pass

        # Create new promo
        new_code = request.POST.get('promo_code')
        new_discount = request.POST.get('promo_discount')
        if new_code and new_discount:
            promo = PromoCode.objects.create(
                code=new_code.strip(),
                discount_percentage=int(new_discount),
                is_active=True
            )
            promo.products.add(product)

        if product_form.is_valid() and image_formset.is_valid() and variant_formset.is_valid():
            with transaction.atomic():
                product = product_form.save(commit=False)

                # Update active or used status from checkbox
                product.is_active = 'is_active' in request.POST
                product.used = 'used' in request.POST

                product.save()

                # Update stock
                if stock_quantity is not None and stock_quantity.isdigit():
                    stock.quantity = int(stock_quantity)
                    stock.save()

                # Save new product images
                for form in image_formset:
                    if form.is_valid() and form.cleaned_data:
                        image_file = form.cleaned_data.get('image')
                        if image_file:
                            image = form.save(commit=False)
                            image.product = product
                            image.save()

                # Clear old variants
                ProductVariant.objects.filter(product=product).delete()

                # Save new variants
                for form in variant_formset:
                    if form.cleaned_data and form.cleaned_data.get('feature_option'):
                        variant = form.save(commit=False)
                        variant.product = product
                        variant.save()

            messages.success(request, 'Product and stock updated successfully!')
            return redirect('stores:manage_store_products', store_id=store.id)

        else:
            if not product_form.is_valid():
                messages.error(request, f'Product form errors: {product_form.errors}')
            if not image_formset.is_valid():
                messages.error(request, f'Image formset errors: {image_formset.errors}')
            if not variant_formset.is_valid():
                messages.error(request, f'Variant formset errors: {variant_formset.errors}')
            messages.error(request, 'Please correct the errors below.')

    else:
        product_form = ProductForm(instance=product)
        image_formset = ImageFormSet(queryset=ProductImage.objects.none())
        variant_formset = VariantFormSet(queryset=ProductVariant.objects.filter(product=product))

    boolean_fields = [
        {"field": product_form['is_featured'], "icon": "fa-star", "text": "Featured Product", "color": "warning"},
        {"field": product_form['is_trending'], "icon": "fa-fire", "text": "Trending Product", "color": "danger"},
        {"field": product_form['has_30_day_return'], "icon": "fa-undo", "text": "30-Day Return", "color": "info"},
        {"field": product_form['free_shipping'], "icon": "fa-shipping-fast", "text": "Free Shipping", "color": "success"},
    ]

    all_promos = PromoCode.objects.filter(is_active=True)

    context = {
        'store': store,
        'product': product,
        'product_form': product_form,
        'image_formset': image_formset,
        'variant_formset': variant_formset,
        'boolean_fields': boolean_fields,
        'all_promos': all_promos,
        'stock_quantity': stock.quantity,
    }

    return render(request, 'stores/edit_product.html', context)


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
    store = get_object_or_404(Store, id=store_id, owner=request.user)

    # Get all threads involving the store owner
    threads = ChatThread.objects.filter(participants=request.user).order_by('-updated_at')

    # Optional: preload the latest message per thread
    thread_data = []
    for thread in threads:
        other = thread.participants.exclude(id=request.user.id).first()
        last_msg = thread.messages.last()
        thread_data.append({
            'thread': thread,
            'participant': other,
            'last_message': last_msg.message if last_msg else 'No messages yet',
            'timestamp': last_msg.timestamp if last_msg else None
        })

    context = {
        'store': store,
        'threads': thread_data,
    }
    return render(request, 'stores/chat_panel.html', context)

@login_required
def chat_thread_detail(request, store_id, thread_id):
    store = get_object_or_404(Store, id=store_id, owner=request.user)
    thread = get_object_or_404(ChatThread, id=thread_id, participants=request.user)

    if request.method == 'POST':
        msg = request.POST.get('message')
        if msg:
            ChatMessage.objects.create(
                thread=thread,
                sender=request.user,
                message=msg
            )
            thread.save()  # triggers `updated_at`
        return HttpResponseRedirect(reverse('stores:chat_thread_detail', args=[store.id, thread.id]))

    messages = thread.messages.select_related('sender').order_by('timestamp')
    context = {
        'store': store,
        'thread': thread,
        'messages': messages,
        'other_user': thread.participants.exclude(id=request.user.id).first()
    }
    return render(request, 'stores/chat_thread_detail.html', context)

@login_required
def store_order_detail(request, store_id, order_id):
    store = get_object_or_404(Store, id=store_id, owner=request.user)
    order = get_object_or_404(Order, id=order_id)

    store_order_items = order.items.filter(product__seller=store.owner).select_related('product')
    if not store_order_items.exists():
        raise Http404("No items in this order belong to your store.")

    # Chat messages related to the order
    chat_messages = order.chat_messages.all().select_related('sender')

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
        'chat_messages': chat_messages,  # Pass to template
    }
    return render(request, 'stores/store_order_detail.html', context)

@require_POST
@login_required
def send_chat_message(request):
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        order_id = request.POST.get('order_id')
        content = request.POST.get('message')

        if not content or not order_id:
            return JsonResponse({'success': False, 'message': 'Missing content or order ID.'})

        try:
            order = Order.objects.get(id=order_id)
            ChatMessage.objects.create(
                order=order,
                sender=request.user,
                content=content
            )
            return JsonResponse({'success': True, 'message': content})
        except Order.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Order not found.'})
    else:
        return JsonResponse({'success': False, 'message': 'Invalid request type.'})

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

    context = {
        'store': store,
        'total_products': total_products,
        'recent_products': recent_products,
        'total_orders': total_orders,
        'monthly_orders': monthly_orders,
        'total_revenue': total_revenue,
        'monthly_revenue': monthly_revenue,
        'store_views': store_views,
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

    }

    return render(request, 'stores/store_dashboard.html', context)


@login_required
@store_owner_required
def store_settings(request, store_id):
    """Comprehensive store settings management"""
    store = get_object_or_404(Store, id=store_id, owner=request.user)

    # Get or create related settings
    return_settings, created = StoreReturnSettings.objects.get_or_create(store=store)

    # Get existing store hours or create default ones
    store_hours = []
    for day in range(7):
        hour, created = StoreHours.objects.get_or_create(
            store=store,
            day_of_week=day,
            defaults={'is_closed': True}
        )
        store_hours.append(hour)

    if request.method == 'POST':
        tab = request.POST.get('tab', 'basic')

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
                        if form.is_valid() and form.cleaned_data:
                            if form.cleaned_data.get('DELETE'):
                                if form.instance.pk:
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

    # Initialize forms
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
def stock_management(request, store_id):
    """Comprehensive stock management for store products"""
    store = get_object_or_404(Store, id=store_id, owner=request.user)

    # Use prefetch_related for reverse relation 'stock_records'
    products = Product.objects.filter(seller=store.owner).select_related('category', 'store').prefetch_related('stock_records')

    # Apply filters
    search_query = request.GET.get('search', '')
    stock_filter = request.GET.get('stock_filter', 'all')
    category_filter = request.GET.get('category', '')

    if search_query:
        products = products.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    if stock_filter == 'low':
        products = products.filter(stock_records__quantity__lte=10, stock_records__quantity__gt=0)
    elif stock_filter == 'out':
        products = products.filter(stock_records__quantity=0)
    elif stock_filter == 'available':
        products = products.filter(stock_records__quantity__gt=0)

    if category_filter:
        products = products.filter(category_id=category_filter)

    # Pagination
    paginator = Paginator(products, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Stock summary
    total_products = products.count()
    low_stock_count = Product.objects.filter(
        seller=store.owner,
        stock_records__quantity__lte=10,
        stock_records__quantity__gt=0
    ).count()
    out_of_stock_count = Product.objects.filter(
        seller=store.owner,
        stock_records__quantity=0
    ).count()

    in_stock_count = Product.objects.filter(
        seller=store.owner,
        stock_records__quantity__gte=10,
        stock_records__quantity__gt=0
    ).count()

    # Categories for filter
    categories = products.values('category__name', 'category_id').distinct()

    context = {
        'store': store,
        'page_obj': page_obj,
        'total_products': total_products,
        'low_stock_count': low_stock_count,
        'in_stock_count': in_stock_count,
        'out_of_stock_count': out_of_stock_count,
        'search_query': search_query,
        'stock_filter': stock_filter,
        'category_filter': category_filter,
        'categories': categories,
    }

    return render(request, 'stores/stock_management.html', context)

@login_required
@require_POST
def update_stock(request, store_id, product_id):
    """Update stock quantity for a specific product"""
    store = get_object_or_404(Store, id=store_id, owner=request.user)
    product = get_object_or_404(Product, id=product_id, seller=store.owner)

    try:
        new_quantity = int(request.POST.get('quantity', 0))
        adjustment_type = request.POST.get('type', 'set')  # 'set', 'add', 'subtract'
        notes = request.POST.get('notes', '')

        stock, created = Stock.objects.get_or_create(product=product)
        old_quantity = stock.quantity

        if adjustment_type == 'set':
            stock.quantity = new_quantity
            quantity_change = new_quantity - old_quantity
        elif adjustment_type == 'add':
            stock.quantity += new_quantity
            quantity_change = new_quantity
        elif adjustment_type == 'subtract':
            stock.quantity = max(0, stock.quantity - new_quantity)
            quantity_change = -(new_quantity)

        stock.save()

        # Create inventory tracking record
        StoreInventoryTracking.objects.create(
            store=store,
            product=product,
            transaction_type='adjustment',
            quantity_change=quantity_change,
            notes=notes or f'Stock {adjustment_type}: {new_quantity}',
            performed_by=request.user
        )

        return JsonResponse({
            'success': True,
            'new_quantity': stock.quantity,
            'message': f'Stock updated successfully. New quantity: {stock.quantity}'
        })

    except (ValueError, TypeError):
        return JsonResponse({
            'success': False,
            'message': 'Invalid quantity provided'
        })


@login_required
@store_owner_required
def inventory_history(request, store_id):
    """View inventory transaction history"""
    store = get_object_or_404(Store, id=store_id, owner=request.user)

    transactions = StoreInventoryTracking.objects.filter(
        store=store
    ).select_related('product', 'performed_by').order_by('-timestamp')

    # Apply filters
    product_filter = request.GET.get('product')
    transaction_type = request.GET.get('type')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    # Get filter display names
    selected_product_name = None
    selected_type_name = None

    if product_filter:
        transactions = transactions.filter(product_id=product_filter)
        try:
            selected_product = Product.objects.get(id=product_filter, seller=store.owner)
            selected_product_name = selected_product.name
        except Product.DoesNotExist:
            pass

    if transaction_type:
        transactions = transactions.filter(transaction_type=transaction_type)
        # Get display name for transaction type
        type_choices = dict(StoreInventoryTracking.TRANSACTION_TYPES)
        selected_type_name = type_choices.get(transaction_type, transaction_type)

    if date_from:
        transactions = transactions.filter(timestamp__date__gte=date_from)

    if date_to:
        transactions = transactions.filter(timestamp__date__lte=date_to)

    # Pagination
    paginator = Paginator(transactions, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Get products for filter dropdown
    products = Product.objects.filter(seller=store.owner).values('id', 'name')

    # Calculate summary stats
    positive_transactions = transactions.filter(quantity_change__gt=0).count()
    negative_transactions = transactions.filter(quantity_change__lt=0).count()

    context = {
        'store': store,
        'page_obj': page_obj,
        'products': products,
        'transaction_types': StoreInventoryTracking.TRANSACTION_TYPES,
        'filters': {
            'product': product_filter,
            'product_name': selected_product_name,
            'type': transaction_type,
            'type_name': selected_type_name,
            'date_from': date_from,
            'date_to': date_to,
        },
        'positive_transactions': positive_transactions,
        'negative_transactions': negative_transactions,
    }

    return render(request, 'stores/inventory_history.html', context)

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