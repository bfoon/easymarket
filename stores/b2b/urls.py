from django.urls import path
from . import views

app_name = "stores_b2b"

urlpatterns = [
    path("cart/", views.b2b_cart, name="cart"),
    path("cart/add/", views.b2b_cart_add, name="cart_add"),
    path("cart/place-order/", views.b2b_place_order, name="place_order"),

    path("orders/<uuid:order_id>/", views.store_b2b_order_detail, name="order_detail"),
]
