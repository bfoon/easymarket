# payments/urls.py
from django.urls import path
from . import views

app_name = 'payments'

urlpatterns = [
    # Payment processing
    path('process/<int:order_id>/', views.process_payment, name='process_payment'),

    # Payment status and history
    path('status/<uuid:payment_id>/', views.payment_status, name='payment_status'),
    path('history/<int:order_id>/', views.payment_history, name='payment_history'),

    # Refunds
    path('refund/<uuid:payment_id>/', views.refund_payment, name='refund_payment'),

    # Webhooks
    path('webhook/', views.payment_webhook, name='payment_webhook'),
]