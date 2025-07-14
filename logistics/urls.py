from django.urls import path
from . import views

app_name = 'logistics'

urlpatterns = [
    # Shipment management
    path('', views.shipment_list, name='shipment_list'),
    path('shipment/<int:shipment_id>/', views.shipment_detail, name='shipment_detail'),
    path('shipment/create/', views.create_shipment, name='create_shipment'),

    # Status updates - fixed naming for clarity
    # path('shipment/<int:shipment_id>/mark-shipped/<int:order_id>/', views.mark_shipment_as_shipped, name='mark_as_shipped'),
    path('order/<int:order_id>/mark-shipped/', views.mark_order_as_shipped, name='mark_order_as_shipped'),
    path('shipment/<int:shipment_id>/mark-shipped/', views.mark_shipment_as_shipped, name='mark_as_shipped'),

    # AJAX endpoints
    path('ajax/get-shipping-address/', views.get_shipping_address, name='get_shipping_address'),
]