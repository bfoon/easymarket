from django.urls import path
from . import views

app_name = 'marketplace'
urlpatterns = [
    path('', views.product_list, name='product_list'),
    path('product/<int:product_id>/', views.product_detail, name='product_detail'),
    path('all-products/', views.all_products, name='all_products'),
    path('hot-picks/', views.hot_picks, name='hot_picks'),
    path('cart/', views.cart_view, name='cart'),
    path('add-to-cart/<int:product_id>/', views.add_to_cart, name='add_to_cart'),
]
