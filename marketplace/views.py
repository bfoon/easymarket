from django.shortcuts import render
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