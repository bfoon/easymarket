"""
Logistics URLs Configuration

This module defines all URL patterns for the logistics application,
organized by functional areas for better maintainability.

Author: Logistics Team
Version: 2.0.0
"""

from django.urls import path, include
from . import views

app_name = 'logistics'

# ============================================================================
# DASHBOARD & ANALYTICS URLS
# ============================================================================

dashboard_patterns = [
    path('', views.DashboardView.as_view(), name='dashboard'),
    path('analytics/', views.AssignmentAnalyticsView.as_view(), name='analytics'),
]

# ============================================================================
# SHIPMENT MANAGEMENT URLS
# ============================================================================

shipment_patterns = [
    # List and Detail Views
    path('', views.ShipmentListView.as_view(), name='shipment_list'),
    path('<int:pk>/', views.ShipmentDetailView.as_view(), name='shipment_detail'),

    # CRUD Operations
    path('create/', views.ShipmentCreateView.as_view(), name='shipment_create'),
    path('<int:pk>/edit/', views.ShipmentUpdateView.as_view(), name='shipment_edit'),
    path('<int:pk>/delete/', views.ShipmentDeleteView.as_view(), name='shipment_delete'),

    # Status Management
    path('<int:pk>/update-status/', views.update_shipment_status, name='update_shipment_status'),
    path('<int:shipment_pk>/mark-delivered/', views.mark_order_as_delivered, name='mark_order_delivered'),
    path('<int:shipment_pk>/cancel/', views.cancel_shipment, name='cancel_shipment'),
    path('<int:shipment_pk>/order-status/', views.get_shipment_order_status, name='get_order_status'),

    # Export Operations
    path('export/csv/', views.export_shipments_csv, name='shipment_export_csv'),
    path('export/excel/', views.export_shipments_excel, name='shipment_export_excel'),
    path('export/pdf/', views.export_shipments_pdf, name='shipment_export_pdf'),
]

# ============================================================================
# BOX MANAGEMENT URLS
# ============================================================================

box_patterns = [
    # Box Operations
    path('<int:shipment_pk>/boxes/create/', views.ShipmentBoxCreateView.as_view(), name='box_create'),
    path('<int:shipment_pk>/boxes/manage/', views.manage_shipment_boxes, name='manage_boxes'),
    path('<int:shipment_pk>/boxes/bulk-create/', views.bulk_create_boxes, name='box_bulk_create'),

    # Individual Box Operations
    path('boxes/<int:pk>/', views.ShipmentBoxDetailView.as_view(), name='box_detail'),
    path('boxes/<int:pk>/edit/', views.ShipmentBoxUpdateView.as_view(), name='box_edit'),
    path('boxes/<int:pk>/delete/', views.ShipmentBoxDeleteView.as_view(), name='box_delete'),

    # Label Generation
    path('boxes/<int:box_id>/generate-label/', views.generate_box_label, name='generate_box_label'),
    path('<int:shipment_id>/boxes/generate-all-labels/', views.generate_all_box_labels, name='generate_all_labels'),

    # Box Items
    path('boxes/<int:box_pk>/items/create/', views.BoxItemCreateView.as_view(), name='box_item_create'),
    path('box-items/<int:pk>/', views.BoxItemDetailView.as_view(), name='box_item_detail'),
    path('box-items/<int:pk>/edit/', views.BoxItemUpdateView.as_view(), name='box_item_edit'),
    path('box-items/<int:pk>/delete/', views.BoxItemDeleteView.as_view(), name='box_item_delete'),
]

# ============================================================================
# DRIVER MANAGEMENT URLS
# ============================================================================
driver_portal_patterns = [
    # Driver Portal
    path('dashboard/', views.driver_dashboard, name='driver_dashboard'),
    path('profile/', views.driver_profile, name='driver_profile'),
    path('profile/edit/', views.driver_profile_edit, name='driver_profile_edit'),

    # Shipment Operations (Driver View)
    path('shipment/<int:shipment_id>/', views.shipment_detail_map, name='shipment_detail_map'),
    path('shipment/<int:shipment_id>/start/', views.start_delivery, name='start_delivery'),
    path('shipment/<int:shipment_id>/delivered/', views.mark_delivered, name='mark_delivered'),
    path('shipment/<int:shipment_id>/location/', views.get_shipment_location, name='get_shipment_location'),
    path('shipment/<int:shipment_id>/update-location/', views.update_driver_location, name='update_driver_location'),

]
driver_patterns = [
    # List and Detail Views
    path('', views.DriverListView.as_view(), name='driver_list'),
    path('<int:pk>/', views.DriverDetailView.as_view(), name='driver_detail'),

    # CRUD Operations
    path('create/', views.DriverCreateView.as_view(), name='driver_create'),
    path('<int:pk>/edit/', views.DriverUpdateView.as_view(), name='driver_edit'),
    path('<int:pk>/delete/', views.DriverDeleteView.as_view(), name='driver_delete'),
    path('<int:pk>/deactivate/', views.deactivate_driver, name='driver_deactivate'),
    path('<int:pk>/activate/', views.activate_driver, name='driver_activate'),


    # Performance & Stats
    path('<int:pk>/statistics/', views.driver_statistics, name='driver_statistics'),
    path('<int:pk>/performance/', views.driver_performance, name='driver_performance'),

    path('driver/shipment/<int:shipment_id>/location/update/', views.update_driver_location, name='update_driver_location'),
    path('driver/shipment/<int:shipment_id>/location/latest/', views.get_latest_driver_location, name='get_latest_driver_location'),

]

# ============================================================================
# VEHICLE MANAGEMENT URLS
# ============================================================================

vehicle_patterns = [
    # List and Detail Views
    path('', views.VehicleListView.as_view(), name='vehicle_list'),
    path('<int:pk>/', views.VehicleDetailView.as_view(), name='vehicle_detail'),

    # CRUD Operations
    path('create/', views.VehicleCreateView.as_view(), name='vehicle_create'),
    path('<int:pk>/edit/', views.VehicleUpdateView.as_view(), name='vehicle_edit'),
    path('<int:pk>/delete/', views.VehicleDeleteView.as_view(), name='vehicle_delete'),
    path('<int:pk>/deactivate/', views.deactivate_vehicle, name='vehicle_deactivate'),
    path('<int:pk>/activate/', views.activate_vehicle, name='vehicle_activate'),

    # Maintenance
    path('<int:pk>/maintenance/', views.vehicle_maintenance_log, name='vehicle_maintenance'),
    path('<int:pk>/maintenance/add/', views.add_maintenance_record, name='add_maintenance'),
    path('<int:pk>/maintenance/schedule/', views.schedule_maintenance, name='schedule_maintenance'),
]

# ============================================================================
# WAREHOUSE MANAGEMENT URLS
# ============================================================================

warehouse_patterns = [
    # List and Detail Views
    path('', views.WarehouseListView.as_view(), name='warehouse_list'),
    path('<int:pk>/', views.WarehouseDetailView.as_view(), name='warehouse_detail'),

    # CRUD Operations
    path('create/', views.WarehouseCreateView.as_view(), name='warehouse_create'),
    path('<int:pk>/edit/', views.WarehouseUpdateView.as_view(), name='warehouse_edit'),
    path('<int:pk>/delete/', views.WarehouseDeleteView.as_view(), name='warehouse_delete'),
    path('<int:pk>/deactivate/', views.deactivate_warehouse, name='warehouse_deactivate'),
    path('<int:pk>/activate/', views.activate_warehouse, name='warehouse_activate'),

    # Warehouse Queue & Inventory
    path('<int:pk>/queue/', views.warehouse_queue, name='warehouse_queue'),
    path('queue/item/<int:pk>/', views.WarehouseQueueItemDetailView.as_view(), name='warehouse_item_detail'),
    path('<int:pk>/inventory/', views.warehouse_inventory, name='warehouse_inventory'),
    path('<int:pk>/utilization/', views.warehouse_utilization, name='warehouse_utilization'),
    path("warehouse/orders/<int:order_id>/", views.warehouse_order_detail, name="warehouse_order_detail"),
]

# ============================================================================
# LOGISTIC OFFICE URLS
# ============================================================================

office_patterns = [
    # List and Detail Views
    path('', views.LogisticOfficeListView.as_view(), name='logistic_office_list'),
    path('<int:pk>/', views.LogisticOfficeDetailView.as_view(), name='logistic_office_detail'),

    # CRUD Operations
    path('create/', views.LogisticOfficeCreateView.as_view(), name='logistic_office_create'),
    path('<int:pk>/edit/', views.LogisticOfficeUpdateView.as_view(), name='logistic_office_edit'),
    path('<int:pk>/delete/', views.LogisticOfficeDeleteView.as_view(), name='logistic_office_delete'),
]

# ============================================================================
# ASSIGNMENT MANAGEMENT URLS
# ============================================================================

assignment_patterns = [
    # Dashboard & Reports
    path('', views.AssignmentDashboardView.as_view(), name='assignment_dashboard'),
    path('vehicles/', views.VehicleAssignmentListView.as_view(), name='vehicle_assignment_list'),
    path('drivers/', views.DriverAssignmentListView.as_view(), name='driver_assignment_list'),
    path('report/', views.assignment_report, name='assignment_report'),

    # Assignment Actions
    path('assign/', views.assign_vehicle_to_driver, name='assign_vehicle_to_driver'),
    path('quick-assign/', views.quick_assign_vehicle, name='quick_assign_vehicle'),
    path('bulk-assign/', views.bulk_assign_vehicles, name='bulk_assign_vehicles'),
    path('api/vehicles/unassigned/', views.api_unassigned_vehicles, name='api_unassigned_vehicles'),
    path('api/vehicles/assign/', views.assign_vehicle_to_driver, name='assign_vehicle_to_driver'),
    path('api/vehicles/<int:vehicle_id>/unassign/', views.unassign_vehicle, name='unassign_vehicle'),
    path("api/unassigned-vehicles/", views.api_unassigned_vehicles, name="api_unassigned_vehicles"),
    path('reassign/<int:shipment_id>/', views.reassign_shipment, name='reassign_shipment'),

    # Export Operations
    path('report/export/', views.assignment_report_export, name='assignment_report_export'),
    path('report/json/', views.assignment_report_json, name='assignment_report_json'),
]

# ============================================================================
# AJAX & API ENDPOINTS
# ============================================================================

ajax_patterns = [
    # Order & Address Related
    path('addresses/', views.ajax_addresses_for_order, name='ajax_addresses_for_order'),
    path('addresses/by-order/', views.ajax_addresses_by_order, name='ajax_addresses_by_order'),
    path('orders/', views.ajax_orders_for_address, name='ajax_orders_for_address'),

    # Vehicle & Driver Related
    path('vehicles/', views.ajax_vehicles_by_driver, name='ajax_vehicles_by_driver'),
    path('vehicles/unassigned/', views.get_unassigned_vehicles_ajax, name='api_unassigned_vehicles'),
    path('drivers/', views.ajax_drivers_by_vehicle, name='ajax_drivers_by_vehicle'),
    path('driver/<int:driver_id>/vehicles/', views.get_driver_vehicles_ajax, name='api_driver_vehicles'),

    # Status & Tracking
    path('shipment/<int:shipment_id>/status/', views.get_shipment_status_ajax, name='ajax_shipment_status'),
    path('shipment/<int:shipment_id>/tracking/', views.get_tracking_info_ajax, name='ajax_tracking_info'),

    # Search & Filter
    path('search/shipments/', views.ajax_search_shipments, name='ajax_search_shipments'),
    path('filter/warehouses/', views.ajax_filter_warehouses, name='ajax_filter_warehouses'),
]

# ============================================================================
# REPORTING & ANALYTICS URLS
# ============================================================================

report_patterns = [
    # Standard Reports
    path('dashboard/', views.reports_dashboard, name='reports_dashboard'),
    path('delivery-performance/', views.delivery_performance_report, name='delivery_performance'),
    path('driver-performance/', views.driver_performance_report, name='driver_performance_report'),
    path('warehouse-utilization/', views.warehouse_utilization_report, name='warehouse_utilization_report'),

    # Custom Reports
    path('custom/', views.custom_report_builder, name='custom_report'),
    path('generate/', views.generate_custom_report, name='generate_custom_report'),

    # Export Formats
    path('export/pdf/', views.export_report_pdf, name='export_report_pdf'),
    path('export/csv/', views.export_report_csv, name='export_report_csv'),
    path('export/excel/', views.export_report_excel, name='export_report_excel'),
]

# ============================================================================
# NOTIFICATION URLS
# ============================================================================

notification_patterns = [
    path('list/', views.notification_list, name='notification_list'),
    path('<int:pk>/mark-read/', views.mark_notification_read, name='mark_notification_read'),
    path('mark-all-read/', views.mark_all_notifications_read, name='mark_all_read'),
    path('settings/', views.notification_settings, name='notification_settings'),
    # Notifications
    path('notifications/', views.notifications_list, name='notifications_list'),
    path('notifications/dropdown/', views.notification_dropdown, name='notification_dropdown'),
    path('notifications/<int:notification_id>/mark-read/', views.notification_mark_as_read,
         name='notification_mark_as_read'),
    path('notifications/mark-all-read/', views.notification_mark_all_as_read, name='notification_mark_all_as_read'),
    path('notifications/<int:notification_id>/', views.notification_detail, name='notification_detail'),
]

# ============================================================================
# MAIN URL PATTERNS
# ============================================================================

urlpatterns = [
    # Dashboard
    path('', include(dashboard_patterns)),

    # Core Modules
    path('shipments/', include(shipment_patterns)),
    path('shipments/', include(box_patterns)),  # Box patterns also under shipments
    path('drivers/', include(driver_patterns)),
    path('driver/', include(driver_portal_patterns)),
    path('vehicles/', include(vehicle_patterns)),
    path('warehouses/', include(warehouse_patterns)),
    path('offices/', include(office_patterns)),

    # Assignments
    path('assignments/', include(assignment_patterns)),

    # AJAX API
    path('ajax/', include(ajax_patterns)),

    # Reports
    path('reports/', include(report_patterns)),

    # Notifications
    path('notifications/', include(notification_patterns)),

    path('orders/<int:order_id>/items-preview/', views.order_items_preview, name='order_items_preview'),

    # B2B Shipments
    path("b2b/shipments/", views.b2b_shipment_list, name="b2b_shipment_list"),
    path("b2b/shipments/<uuid:order_id>/", views.b2b_shipment_detail, name="b2b_shipment_detail"),

    # Box Management
    path("b2b/shipments/<uuid:order_id>/boxes/bulk-create/",
         views.b2b_bulk_create_boxes,
         name="b2b_bulk_create_boxes"),

    # Label Generation (regular QR image labels)
    path("b2b/box/<int:box_id>/label/",
         views.b2b_generate_box_label,
         name="b2b_generate_box_label"),

    path("b2b/shipments/<uuid:order_id>/labels/all/",
         views.b2b_generate_all_box_labels,
         name="b2b_generate_all_box_labels"),

    # Printable PDF Labels
    path("b2b/box/<int:box_id>/print-label/",
         views.b2b_print_box_label,
         name="b2b_print_box_label"),

    path("b2b/shipments/<uuid:order_id>/print-all-labels/",
         views.b2b_print_all_labels,
         name="b2b_print_all_labels"),

    # Box Item Management
    path("b2b/box/<int:box_id>/items/add/",
         views.b2b_box_item_add,
         name="b2b_box_item_add"),

    path("b2b/box-item/<int:item_id>/delete/",
         views.b2b_box_item_delete,
         name="b2b_box_item_delete"),

    # Shipment Lock/Unlock
    path("b2b/shipments/<uuid:order_id>/unlock/",
         views.b2b_unlock_shipment,
         name="b2b_unlock_shipment"),

    path("b2b/shipments/<uuid:order_id>/lock/",
         views.b2b_lock_shipment,
         name="b2b_lock_shipment"),

    # NEW: Delivery Management
    path("b2b/shipments/<uuid:order_id>/mark-in-transit/",
         views.b2b_mark_in_transit,
         name="b2b_mark_in_transit"),

    path("b2b/shipments/<uuid:order_id>/mark-delivered/",
         views.b2b_mark_delivered,
         name="b2b_mark_delivered"),

    path("b2b/shipments/<uuid:order_id>/revert-to-in-transit/",
         views.b2b_revert_to_in_transit,
         name="b2b_revert_to_in_transit"),
    # Logistics Agent Management URLs
    path(
        'manage/<uuid:store_id>/orders/<int:order_id>/assign-agent/',
        views.assign_logistics_agent,
        name='assign_logistics_agent'
    ),
    path(
        'manage/<uuid:store_id>/orders/<int:order_id>/agent-status/',
        views.update_agent_status,
        name='update_agent_status'
    ),
    path(
        'manage/<uuid:store_id>/orders/<int:order_id>/get-agent-status/',
        views.get_agent_status,
        name='get_agent_status'
    ),
# Get available agents list
    path(
        'api/logistics-agents/available/',
        views.list_available_agents,
        name='list_available_agents'
    ),
]