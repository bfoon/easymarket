from django.urls import path
from . import views

app_name = 'orders'

urlpatterns = [
    # Core order views
    path('checkout/', views.checkout_cart, name='checkout_cart'),
    path('checkout_redirect/', views.checkout_redirect, name='checkout_redirect'),
    path('quick-checkout/', views.quick_checkout, name='quick_checkout'),
    path('detail/<int:order_id>/', views.order_detail, name='order_detail'),
    path('send-chat-message/', views.send_chat_message, name='send_chat_message'),
    path('history/', views.order_history, name='order_history'),
    path('complete/<int:order_id>/', views.complete_order, name='complete_order'),

    # Payment and processing
    # path('process-payment/<int:order_id>/', views.process_payment, name='process_payment'),
    path('track/<int:order_id>/', views.track_order, name='track_order'),
    path('reorder/<int:order_id>/', views.reorder_items, name='reorder_items'),
    path('cancel/<int:order_id>/', views.cancel_order, name='cancel_order'),

    # Public tracking (no login required)
    path('track/', views.track_order_public, name='track_order_public'),
    path('track-ajax/', views.track_order_ajax, name='track_order_ajax'),

    # Additional features
    path('invoice/<int:order_id>/', views.order_invoice, name='order_invoice'),
    path('invoice/download/<int:order_id>/', views.download_invoice_pdf, name='download_invoice'),
    path('update-status/<int:order_id>/', views.update_order_status, name='update_order_status'),
    path('stats/', views.order_stats, name='order_stats'),
    path('validate-promo/', views.validate_promo, name='validate_promo'),

    # API endpoints
    path('api/pending-orders-count/', views.pending_orders_count_api, name='pending_orders_count_api'),
]