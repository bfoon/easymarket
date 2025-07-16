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
    path('ajax/addresses/', views.ajax_addresses_for_order, name='ajax_addresses_for_order'),
    path('ajax/orders/', views.ajax_orders_for_address, name='ajax_orders_for_address'),

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
    path('drivers/create/', views.DriverCreateView.as_view(), name='driver_create'),
    path('drivers/<int:pk>/', views.DriverDetailView.as_view(), name='driver_detail'),
    path('drivers/<int:pk>/edit/', views.DriverUpdateView.as_view(), name='driver_edit'),

    # Vehicles
    path('vehicles/', views.VehicleListView.as_view(), name='vehicle_list'),
    path('vehicles/create/', views.VehicleCreateView.as_view(), name='vehicle_create'),
    path('vehicles/<int:pk>/', views.VehicleDetailView.as_view(), name='vehicle_detail'),
    path('vehicles/<int:pk>/edit/', views.VehicleUpdateView.as_view(), name='vehicle_edit'),

    # Warehouses
    path('warehouses/', views.WarehouseListView.as_view(), name='warehouse_list'),
    path('warehouses/create/', views.WarehouseCreateView.as_view(), name='warehouse_create'),
    path('warehouses/<int:pk>/', views.WarehouseDetailView.as_view(), name='warehouse_detail'),
    path('warehouses/<int:pk>/edit/', views.WarehouseUpdateView.as_view(), name='warehouse_edit'),

    # Logistic Offices
    path('offices/', views.LogisticOfficeListView.as_view(), name='logistic_office_list'),
    path('offices/create/', views.LogisticOfficeCreateView.as_view(), name='logistic_office_create'),
    path('offices/<int:pk>/edit/', views.LogisticOfficeUpdateView.as_view(), name='logistic_office_edit'),

    # Assignment Management URLs
    path('assignments/', views.AssignmentDashboardView.as_view(), name='assignment_dashboard'),
    path('assignments/vehicles/', views.VehicleAssignmentListView.as_view(), name='vehicle_assignment_list'),
    path('assignments/drivers/', views.DriverAssignmentListView.as_view(), name='driver_assignment_list'),
    path('assignments/report/', views.assignment_report, name='assignment_report'),
    path('assignments/analytics/', views.AssignmentAnalyticsView.as_view(), name='assignment_analytics'),

    # Export URLs
    path('assignments/report/export/', views.assignment_report_export, name='assignment_report_export'),
    path('assignments/report/json/', views.assignment_report_json, name='assignment_report_json'),

    # Export Shipping List
    path('shipments/export/csv/', views.export_shipments_csv, name='shipment_export_csv'),
    path('shipments/export/excel/', views.export_shipments_excel, name='shipment_export_excel'),

    # Assignment Actions
    path('assignments/assign/', views.assign_vehicle_to_driver, name='assign_vehicle_to_driver'),
    path('assignments/quick-assign/', views.quick_assign_vehicle, name='quick_assign_vehicle'),
    path('assignments/bulk-assign/', views.bulk_assign_vehicles, name='bulk_assign_vehicles'),
    path('assignments/unassign/<int:vehicle_id>/', views.unassign_vehicle, name='unassign_vehicle'),

    # AJAX endpoints
    path('api/driver/<int:driver_id>/vehicles/', views.get_driver_vehicles_ajax, name='api_driver_vehicles'),
    path('api/unassigned-vehicles/', views.get_unassigned_vehicles_ajax, name='api_unassigned_vehicles'),
]