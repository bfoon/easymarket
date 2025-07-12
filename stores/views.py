from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q
from django.utils import timezone
from django.db import models
from datetime import datetime, timedelta
import json
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils.text import slugify
from django.db.models import Q, Avg
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.forms import modelformset_factory
from django.db import transaction
import re
from .models import Store
from reviews.models import Review
from marketplace.models import Product, Category, ProductImage
from orders.models import Order, OrderItem
from django.http import HttpResponseForbidden
from functools import wraps
from .forms import ProductForm, ProductImageForm

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
            # Create the product
            product = Product.objects.create(
                seller=request.user,
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
    """View and manage products for a specific store."""
    store = get_object_or_404(Store, id=store_id, owner=request.user)

    # Get all products by this seller (since products are linked to seller, not store)
    products = Product.objects.filter(seller=request.user).order_by('-created_at')

    # Add pagination if you have many products
    from django.core.paginator import Paginator
    paginator = Paginator(products, 12)  # Show 12 products per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'stores/manage_products.html', {
        'store': store,
        'products': page_obj,
        'total_products': products.count()
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
    products = Product.objects.filter(seller=store.owner).order_by('-created_at')

    # Add pagination
    from django.core.paginator import Paginator
    paginator = Paginator(products, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'store': store,
        'products': page_obj,
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
    """Edit a product and manage its images"""
    store = get_object_or_404(Store, id=store_id, owner=request.user)
    # Fix: Product is linked to seller, not store
    product = get_object_or_404(Product, id=product_id, seller=request.user)

    # Create a formset for product images
    ImageFormSet = modelformset_factory(
        ProductImage,
        form=ProductImageForm,
        extra=3,  # Allow 3 new images to be added
        can_delete=True
    )

    if request.method == 'POST':
        product_form = ProductForm(request.POST, request.FILES, instance=product)
        image_formset = ImageFormSet(
            request.POST,
            request.FILES,
            queryset=ProductImage.objects.filter(product=product)
        )

        if product_form.is_valid() and image_formset.is_valid():
            with transaction.atomic():
                # Save the product
                product = product_form.save()

                # Save the images
                for form in image_formset:
                    if form.cleaned_data and not form.cleaned_data.get('DELETE'):
                        if form.cleaned_data.get('image'):
                            image = form.save(commit=False)
                            image.product = product
                            image.save()
                    elif form.cleaned_data.get('DELETE'):
                        # Delete the image if marked for deletion
                        if form.instance.pk:
                            form.instance.delete()

                messages.success(request, 'Product updated successfully!')
                return redirect('stores:manage_store_products', store_id=store.id)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        product_form = ProductForm(instance=product)
        image_formset = ImageFormSet(queryset=ProductImage.objects.filter(product=product))

    context = {
        'store': store,
        'product': product,
        'product_form': product_form,
        'image_formset': image_formset,
    }
    return render(request, 'stores/edit_product.html', context)


@login_required
def delete_product_image(request, store_id, product_id, image_id):
    """Delete a specific product image via AJAX"""
    if request.method == 'POST':
        store = get_object_or_404(Store, id=store_id, owner=request.user)
        # Fix: Product is linked to seller, not store
        product = get_object_or_404(Product, id=product_id, seller=request.user)
        image = get_object_or_404(ProductImage, id=image_id, product=product)

        image.delete()
        return JsonResponse({'success': True})

    return JsonResponse({'success': False})

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
@store_owner_required
def store_dashboard(request, store_id):
    store = get_object_or_404(Store, id=store_id)

    # 🔒 Access Control Check
    if not (request.user == store.owner or request.user.is_superuser or getattr(request.user, 'is_seller', False)):
        return HttpResponseForbidden("You do not have permission to view this dashboard.")

    now = timezone.now()
    current_month = now.replace(day=1)

    try:
        user_products = Product.objects.filter(seller=store.owner)
        total_products = user_products.count()

        # Top and recent products
        recent_products = user_products.order_by('-created_at')[:5]
        top_products = user_products.annotate(
            avg_rating=Count('reviews__rating')
        ).order_by('-sold_count')[:5]

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

        category_labels = [cat['category__name'] or 'Uncategorized' for cat in category_data] if category_data else ['No Products']
        category_counts = [cat['count'] for cat in category_data] if category_data else [1]

        # Monthly sales chart data
        monthly_sales_data = []
        for i in range(12):
            month_start = (now.replace(day=1) - timedelta(days=30 * i)).replace(day=1)
            month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            sales = sum(
                item.get_total_price() for item in seller_order_items.filter(
                    order__created_at__gte=month_start,
                    order__created_at__lte=month_end
                )
            )
            monthly_sales_data.insert(0, float(sales))

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
        category_labels = ['No Data']
        category_counts = [1]

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
        'category_labels': json.dumps(category_labels),
        'category_data': json.dumps(category_counts),
        'review_count': review_count,
        'average_rating': round(average_rating, 1),
        'rating_breakdown': rating_breakdown,
    }

    return render(request, 'stores/store_dashboard.html', context)