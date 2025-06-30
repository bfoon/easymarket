from django.shortcuts import render, get_object_or_404
from .models import Category, Product
# Create your views here!

def product_list(request):
    categories = Category.objects.all()
    products = Product.objects.all()
    featured_products = Product.objects.filter(is_featured=True)[:8]
    trending_products = Product.objects.filter(is_trending=True)[:8]
    return render(request, 'marketplace/product_list.html',
                  {
                      'categories': categories,
                      'featured_products': featured_products,
                      'trending_products': trending_products,
                      'products': products
                   })


def product_detail(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    product_images = product.images.all()
    recommended_items = Product.objects.filter(is_featured=True).exclude(id=product.id)[:4]

    return render(request, 'marketplace/product_detail.html', {
        'product': product,
        'product_images': product_images,
        'recommended_items': recommended_items,
    })
