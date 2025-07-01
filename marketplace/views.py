from django.shortcuts import render, get_object_or_404
from .models import Category, Product, ProductView
import re
# Create your views here!

from marketplace.models import Product, ProductView, Category


def product_list(request):
    categories = Category.objects.all()
    products = Product.objects.all()
    featured_products = Product.objects.filter(is_featured=True)[:8]
    trending_products = Product.objects.filter(is_trending=True)[:8]

    recently_viewed = []
    similar_items = []

    if request.user.is_authenticated:
        recently_viewed = Product.objects.filter(productview__user=request.user).distinct().order_by(
            '-productview__viewed_at')[:8]

        if recently_viewed.exists():
            last_viewed_product = recently_viewed.first()
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

    # Record user view
    if request.user.is_authenticated:
        ProductView.objects.get_or_create(user=request.user, product=product)

    # Recommend similar items (same category, excluding current product)
    recommended_items = Product.objects.filter(category=product.category).exclude(id=product.id)[:4]

    # Process Specifications
    cleaned_specs = []
    for line in product.specifications.splitlines():
        if ':' in line:
            raw_key, value = line.split(':', 1)
            clean_key = re.sub(r'^[^a-zA-Z0-9]*(.*?)[^a-zA-Z0-9]*$', r'\1', raw_key).strip()
            cleaned_specs.append((clean_key, value.strip()))

    # Process Description for truncation
    description_text = product.description or ""
    short_description = description_text[:800]

    if len(description_text) > 800:
        last_newline = short_description.rfind('\n')
        if last_newline != -1:
            short_description = short_description[:last_newline]
        description_truncated = True
    else:
        description_truncated = False

    return render(request, 'marketplace/product_detail.html', {
        'product': product,
        'product_images': product_images,
        'recommended_items': recommended_items,
        'specifications': cleaned_specs,
        'short_description': short_description,
        'description_truncated': description_truncated,
    })