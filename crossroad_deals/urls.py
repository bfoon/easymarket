# crossroad_deals/urls.py

from django.urls import path
from . import views

app_name = 'crossroad_deals'

urlpatterns = [
    # Browse listings
    path('', views.listing_list, name='listing_list'),
    path('listing/<uuid:listing_id>/', views.listing_detail, name='listing_detail'),

    # Create & manage listings
    path('create/', views.create_listing, name='create_listing'),
    path('my-listings/', views.my_listings, name='my_listings'),

    # Express interest (unlock more info)
    path('listing/<uuid:listing_id>/interest/', views.express_interest, name='express_interest'),

    # Orders
    path('order/create/', views.create_order, name='create_order'),
    path('order/<uuid:order_id>/', views.order_detail, name='order_detail'),
    path('my-orders/', views.my_orders, name='my_orders'),

    # Reviews
    path('review/create/', views.create_review, name='create_review'),
    path("cart/", views.cart_view, name="cart_view"),
    path("cart/add/", views.cart_add, name="cart_add"),
    path("cart/remove/<uuid:listing_id>/", views.cart_remove, name="cart_remove"),
    path("cart/checkout/", views.cart_checkout, name="cart_checkout"),

    path("listing/<uuid:listing_id>/offer/", views.make_offer, name="make_offer"),

    path("order/<uuid:order_id>/pay/", views.order_pay, name="order_pay"),
    path("payment/callback/<str:provider>/", views.payment_callback, name="payment_callback"),
    path("payment/webhook/<str:provider>/", views.payment_webhook, name="payment_webhook"),

]
