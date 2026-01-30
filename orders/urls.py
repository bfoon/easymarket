from django.urls import path, register_converter
from uuid import UUID
from . import views

app_name = 'orders'

urlpatterns = [
    # Core order views
    path('checkout/', views.checkout_cart, name='checkout_cart'),
    path('checkout/social/', views.checkout_social_cart, name='checkout_social_cart'),
    path('checkout_redirect/', views.checkout_redirect, name='checkout_redirect'),
    path('quick-checkout/', views.quick_checkout, name='quick_checkout'),
    path('detail/<int:order_id>/', views.order_detail, name='order_detail'),
    path('send-chat-message/', views.send_chat_message, name='send_chat_message'),
    path('chat/fetch/<int:order_id>/', views.fetch_chat_messages, name='fetch_chat_messages'),
    path('history/', views.order_history, name='order_history'),
    path('complete/<int:order_id>/', views.complete_order, name='complete_order'),
    path(
        "order/item/<int:item_id>/update-discount/",
        views.update_item_discount,
        name="update_item_discount",
    ),


    # Payment and processing
    # path('process-payment/<int:order_id>/', views.process_payment, name='process_payment'),
    path('track/<int:order_id>/', views.track_order, name='track_order'),
    path('reorder/<int:order_id>/', views.reorder_items, name='reorder_items'),
    path('cancel/<int:order_id>/', views.cancel_order, name='cancel_order'),
    path('store/<uuid:store_id>/invoice/<int:order_id>/', views.store_order_invoice, name='store_order_invoice'),


    # Public tracking (no login required)
    path('track/', views.track_order_public, name='track_order_public'),
    path('track-ajax/', views.track_order_ajax, name='track_order_ajax'),

    # Additional features
    path('invoice/<int:order_id>/', views.order_invoice, name='order_invoice'),
    path('invoice/download/<int:order_id>/', views.download_invoice_pdf, name='download_invoice'),
    path('update-status/<int:order_id>/', views.update_order_status, name='update_order_status'),
    path('stats/', views.order_stats, name='order_stats'),
    path('validate-promo/', views.validate_promo, name='validate_promo'),
    path('copy-order/<uuid:order_id>/', views.copy_order_to_cart, name='copy_order_to_cart'),


    # API endpoints
    path('api/pending-orders-count/', views.pending_orders_count_api, name='pending_orders_count_api'),

    # NEW: Geolocation API endpoints
    path('api/geocode/', views.geocode_address, name='geocode_address'),
    path('api/reverse-geocode/', views.reverse_geocode, name='reverse_geocode'),
    path('api/save-shipping-address/', views.save_shipping_address_with_location, name='save_shipping_address'),

    # Logistics Agent Chat URLs
    path(
        'manage/<uuid:store_id>/orders/<int:order_id>/agent-chat/send/',
        views.send_agent_message,
        name='send_agent_message'
    ),
    path(
        'manage/<uuid:store_id>/orders/<int:order_id>/agent-chat/messages/',
        views.fetch_agent_messages,
        name='fetch_agent_messages'
    ),
    path(
        'manage/<uuid:store_id>/orders/<int:order_id>/agent-chat/unread-count/',
        views.get_unread_agent_messages_count,
        name='get_unread_agent_messages_count'
    ),
    path(
        'manage/<uuid:store_id>/orders/<int:order_id>/get-agent-status/',
        views.get_agent_status,
        name='get_agent_status'
    ),

]