from django.urls import path
from . import views

app_name = 'orders'

urlpatterns = [
    # Core order views
    path('checkout/', views.checkout_cart, name='checkout_cart'),
    path('detail/<int:order_id>/', views.order_detail, name='order_detail'),
    path('history/', views.order_history, name='order_history'),
    path('complete/<int:order_id>/', views.complete_order, name='complete_order'),

    # Payment and processing
    path('process-payment/<int:order_id>/', views.process_payment, name='process_payment'),
    path('track/<int:order_id>/', views.track_order, name='track_order'),
    path('reorder/<int:order_id>/', views.reorder_items, name='reorder_items'),
    path('cancel/<int:order_id>/', views.cancel_order, name='cancel_order'),

    # Additional features
    path('invoice/<int:order_id>/', views.order_invoice, name='order_invoice'),
    path('update-status/<int:order_id>/', views.update_order_status, name='update_order_status'),
    path('stats/', views.order_stats, name='order_stats'),
]