from django.urls import path
from . import views

app_name = 'logistics'

urlpatterns = [
    # Dashboard
    path('', views.DashboardView.as_view(), name='dashboard'),

    # Shipments
    path('shipments/', views.ShipmentListView.as_view(), name='shipment_list'),
    path('shipments/<int:pk>/', views.ShipmentDetailView.as_view(), name='shipment_detail'),
    path('shipments/create/', views.ShipmentCreateView.as_view(), name='shipment_create'),
    path('shipments/<int:pk>/edit/', views.ShipmentUpdateView.as_view(), name='shipment_edit'),
    path('shipments/<int:pk>/update-status/', views.update_shipment_status, name='update_shipment_status'),

    # Order Delivery Management
    path('shipments/<int:shipment_pk>/mark-delivered/', views.mark_order_as_delivered, name='mark_order_delivered'),
    path('shipments/<int:shipment_pk>/order-status/', views.get_shipment_order_status, name='get_order_status'),

    # Box Management
    path('shipments/<int:shipment_pk>/boxes/create/', views.ShipmentBoxCreateView.as_view(), name='box_create'),
    path('shipments/<int:shipment_pk>/boxes/manage/', views.manage_shipment_boxes, name='manage_boxes'),
    path('boxes/<int:pk>/edit/', views.ShipmentBoxUpdateView.as_view(), name='box_edit'),
    path('boxes/<int:pk>/delete/', views.ShipmentBoxDeleteView.as_view(), name='box_delete'),

    # Box Items
    path('boxes/<int:box_pk>/items/create/', views.BoxItemCreateView.as_view(), name='box_item_create'),
    path('box-items/<int:pk>/edit/', views.BoxItemUpdateView.as_view(), name='box_item_edit'),
    path('box-items/<int:pk>/delete/', views.BoxItemDeleteView.as_view(), name='box_item_delete'),

    # Box Labels
    path('shipments/<int:shipment_id>/boxes/<int:box_id>/generate-label/',
         views.generate_box_label, name='generate_box_label'),

    # Drivers
    path('drivers/', views.DriverListView.as_view(), name='driver_list'),
    path('drivers/<int:pk>/', views.DriverDetailView.as_view(), name='driver_detail'),

    # Vehicles
    path('vehicles/', views.VehicleListView.as_view(), name='vehicle_list'),

    # Warehouses
    path('warehouses/', views.WarehouseListView.as_view(), name='warehouse_list'),
]