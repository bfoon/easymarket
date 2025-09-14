from django.urls import path
from . import views
from . import views_subscriptions

app_name = 'marketplace'

urlpatterns = [
    path('', views.product_list, name='product_list'),
    path('about/', views.about, name='about'),

    path('product/<int:product_id>/', views.product_detail, name='product_detail'),
    path('product/<int:product_id>/quick-view/', views.product_quick_view, name='product_quick_view'),

    path('all-products/', views.all_products, name='all_products'),
    path('hot-picks/', views.hot_picks, name='hot_picks'),
    path('used/', views.used_products_view, name='used_products'),

    # Cart
    path('cart/', views.cart_view, name='cart'),                  # primary
    path('cart/view/', views.cart_view, name='cart_view'),        # optional alias (kept to avoid breaking links)
    path('cart/preview/', views.cart_preview, name='cart_preview'),

    path('add-to-cart/<int:product_id>/', views.add_to_cart, name='add_to_cart'),
    path('get-cart-count/', views.get_cart_count, name='get_cart_count'),

    # Wishlist
    path('wishlist/toggle/<int:product_id>/', views.toggle_wishlist, name='toggle_wishlist'),
    path('my-wishlist/', views.my_wishlist, name='my_wishlist'),

    # Discovery/search
    path('recommended/', views.recommended_products_view, name='recommended_products'),
    path('category/<slug:slug>/', views.category_products, name='category_products'),
    path('category/<int:pk>/', views.category_detail, name='category_detail'),
    path('update-cart-quantity/', views.update_cart_quantity, name='update_cart_quantity'),
    path('remove-cart-item/', views.remove_cart_item, name='remove_cart_item'),
    path('apply-promo-code/', views.apply_promo_code, name='apply_promo_code'),
    path('trending/', views.trending_products_view, name='trending_products'),

    path('search/', views.search_products, name='search_products'),
    path('search/suggestions/', views.search_suggestions, name='search_suggestions'),
    path('search/popular/', views.get_popular_searches, name='popular_searches'),
    path('search/clear-history/', views.clear_search_history, name='clear_search_history'),

    # Sharing & subscriptions
    path('share-cart/', views.share_cart, name='share_cart'),
    path('copy-shared-cart/<uuid:token>/', views.copy_shared_cart, name='copy_shared_cart'),
    path('subscribe/', views_subscriptions.subscribe_email, name='subscribe'),

    # Careers
    path('careers/', views.careers_list, name='careers'),
    path('careers/apply/', views.careers_apply, name='career_apply'),
    path('careers/apply/success/<str:code>/', views.careers_apply_success, name='career_apply_success'),
    path('careers/<slug:slug>/', views.career_detail, name='career_detail'),

    # PRESS — order matters!
    path("press/", views.press_list, name="press_list"),
    path("press/new/", views.press_create, name="press_create"),
    path("press/<slug:slug>/", views.press_detail, name="press_detail"),

    path("investors/", views.investors_home, name="investors_home"),

]
