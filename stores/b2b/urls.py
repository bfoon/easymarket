# stores/b2b/urls.py - ADD these URL patterns

from django.urls import path
from . import views

app_name = "stores_b2b"

urlpatterns = [
    # ==================== CART ====================
    path("cart/", views.b2b_cart, name="cart"),
    path("cart/add/", views.b2b_cart_add, name="cart_add"),

    # ✅ NEW: Quantity management endpoints
    path("cart/update-quantity/", views.b2b_update_quantity, name="update_quantity"),
    path("cart/remove-item/", views.b2b_remove_item, name="remove_item"),

    path("cart/place-order/", views.b2b_place_order, name="place_order"),

    # ==================== ORDERS ====================
    path("orders/", views.b2b_my_orders, name="my_orders"),
    path("orders/<uuid:order_id>/", views.store_b2b_order_detail, name="order_detail"),

    # Order management endpoints
    path("orders/<uuid:order_id>/update-status/", views.b2b_update_order_status, name="update_order_status"),
    path("orders/<uuid:order_id>/save-prices/", views.b2b_save_prices, name="save_prices"),
    path("orders/<uuid:order_id>/send-message/", views.b2b_order_send_message, name="send_message"),
    path("b2b/orders/<uuid:order_id>/save-unit-prices/", views.b2b_save_unit_prices, name="save_unit_prices"),
    path("orders/<uuid:order_id>/mark-items-shipped/", views.b2b_mark_items_shipped, name="mark_items_shipped"),
    path("orders/<uuid:order_id>/set-shipping-cost/", views.b2b_set_shipping_cost, name="set_shipping_cost"),
    path("my/<uuid:order_id>/cancel/", views.b2b_buyer_cancel_order, name="cancel_order"),

    # Invoice
    path("orders/<uuid:order_id>/invoice/", views.order_invoice, name="invoice"),
    path("invoice/verify/<uuid:order_id>/", views.invoice_verify, name="invoice_verify"),
    path("invoice/qr/<uuid:order_id>/", views.invoice_qr, name="invoice_qr"),

    # ==================== BUYER VIEWS ====================
    path("my/", views.b2b_my_personal_orders, name="my_personal_orders"),
    path("my/<uuid:order_id>/", views.b2b_my_personal_order_detail, name="my_personal_order_detail"),

    # Buyer chat endpoint
    path('my-orders/<uuid:order_id>/send-message/', views.b2b_buyer_send_message_ajax, name='buyer_send_message_ajax'),

    # Buyer actions (JSON)
    path("my/<uuid:order_id>/send-message/", views.b2b_buyer_send_message, name="buyer_send_message"),
    path("my/<uuid:order_id>/accept/", views.b2b_buyer_accept_offer, name="buyer_accept_offer"),
    path("my/<uuid:order_id>/reject/", views.b2b_buyer_reject_offer, name="buyer_reject_offer"),
    path("my/<uuid:order_id>/chat/fetch/", views.b2b_buyer_fetch_messages, name="buyer_fetch_messages"),
]