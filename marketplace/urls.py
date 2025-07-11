from django.urls import path
from . import views

app_name = 'marketplace'
urlpatterns = [
    path('', views.product_list, name='product_list'),
    path('product/<int:product_id>/', views.product_detail, name='product_detail'),
    path('all-products/', views.all_products, name='all_products'),
    path('hot-picks/', views.hot_picks, name='hot_picks'),
    path('cart/', views.cart_view, name='cart'),
    path('cart/', views.cart_view, name='cart_view'),
    path('add-to-cart/<int:product_id>/', views.add_to_cart, name='add_to_cart'),
    path('wishlist/toggle/<int:product_id>/', views.toggle_wishlist, name='toggle_wishlist'),
    path('my-wishlist/', views.my_wishlist, name='my_wishlist'),
    path('recommended/', views.recommended_products_view, name='recommended_products'),
    path('category/<int:slug>/', views.category_products, name='category_products'),
    path('category/<int:pk>/', views.category_detail, name='category_detail'),
    path('update-cart-quantity/', views.update_cart_quantity, name='update_cart_quantity'),
    path('remove-cart-item/', views.remove_cart_item, name='remove_cart_item'),
    path('apply-promo-code/', views.apply_promo_code, name='apply_promo_code'),
    path('trending/', views.trending_products_view, name='trending_products'),
    path('search/', views.search_products, name='search_products'),
    path('search/suggestions/', views.search_suggestions, name='search_suggestions'),
    path('search/popular/', views.get_popular_searches, name='popular_searches'),
    path('search/clear-history/', views.clear_search_history, name='clear_search_history'),
]
