# supply_chain/urls.py

from django.urls import path
from . import views

app_name = 'supply_chain'

urlpatterns = [
    # Dashboard
    path('', views.supply_chain_dashboard, name='dashboard'),

    # Warehouse Linkages
    path('linkages/', views.warehouse_linkages, name='warehouse_linkages'),
    path('linkages/add/', views.add_linkage, name='add_linkage'),
    path('linkages/<int:pk>/edit/', views.edit_linkage, name='edit_linkage'),
    path('linkages/<int:pk>/toggle/', views.toggle_linkage_status, name='toggle_linkage_status'),
    path('linkages/create/', views.create_linkage, name='create_linkage'),

    # Transfers
    path('transfers/', views.transfer_list, name='transfer_list'),
    path('transfers/<uuid:transfer_id>/', views.transfer_detail, name='transfer_detail'),
    path('transfers/<uuid:transfer_id>/pickup/', views.mark_transfer_picked_up, name='mark_picked_up'),
    path('transfers/<uuid:transfer_id>/receive/', views.mark_transfer_received, name='mark_received'),

    # Fulfillment Queue
    path("fulfillment/", views.fulfillment_queue, name="fulfillment_queue"),
    path("fulfillment/<uuid:b2b_order_id>/start-picking/", views.start_picking_b2b, name="start_picking_b2b"),
    path("fulfillment/<uuid:b2b_order_id>/complete-picking/", views.complete_picking_b2b, name="complete_picking_b2b"),
    path("fulfillment/<uuid:b2b_order_id>/complete-packing/", views.complete_packing_b2b, name="complete_packing_b2b"),

    # B2B Shipping Configuration
    path('shipping/config/', views.shipping_config, name='shipping_config'),
    path('shipping/country/<uuid:country_id>/', views.country_detail, name='country_detail'),

    # B2B Shipments
    path('shipments/', views.b2b_shipments, name='b2b_shipments'),
    path('shipments/create/<uuid:order_id>/', views.create_b2b_shipment, name='create_b2b_shipment'),
    path('shipments/<uuid:shipment_id>/', views.shipment_detail, name='shipment_detail'),
    path('shipments/<uuid:shipment_id>/ship/', views.mark_shipment_shipped, name='mark_shipment_shipped'),

    # Analytics
    path('analytics/', views.supply_chain_analytics, name='analytics'),

    # API Endpoints
    path('api/shipping-cost/', views.api_shipping_cost, name='api_shipping_cost'),
    path("api/origin-companies/", views.api_origin_shipping_companies, name="api_origin_shipping_companies"),

    # Country Management
    path('countries/add/', views.add_country, name='add_country'),
    path('countries/<int:pk>/', views.country_detail, name='country_detail'),
    path('countries/<int:pk>/edit/', views.edit_country, name='edit_country'),
    path('countries/<int:pk>/delete/', views.delete_country, name='delete_country'),

    # Shipping Company Management
    path('shipping-companies/add/', views.add_shipping_company, name='add_shipping_company'),
    path('shipping-companies/<int:pk>/edit/', views.edit_shipping_company, name='edit_shipping_company'),
    path('shipping-companies/<int:pk>/delete/', views.delete_shipping_company, name='delete_shipping_company'),

    # Company-Country Configuration
    path('countries/<int:country_id>/add-company/', views.add_company_to_country, name='add_company_to_country'),
    path('company-configs/<int:pk>/edit/', views.edit_company_config, name='edit_company_config'),
    path('company-configs/<int:pk>/delete/', views.delete_company_config, name='delete_company_config'),
]