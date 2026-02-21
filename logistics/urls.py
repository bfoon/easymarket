"""
Easy Market Logistics — URL Configuration
==========================================
All URL patterns for the logistics application.
Corrected to match views that actually exist in views.py.

Version: 3.0.0
"""

from django.urls import path, include
from . import views
from .fleet_map_views import (
    fleet_map_view,
    fleet_map_data,
    route_detail_api,
    update_vehicle_location,
)
from .dispatch_views import (
    # Dashboard
    DispatchDashboardView,
    # Driver management
    DriverRosterView,
    DriverRegistrationView,
    DriverProfileView,
    DriverEditView,
    VettingQueueView,
    approve_driver,
    reject_driver,
    suspend_driver,
    # Pickup tasks
    PickupTaskListView,
    PickupTaskDetailView,
    CreatePickupTaskView,
    AssignPickupTaskView,
    PickupTaskStatusUpdateView,
    # Last mile tasks
    LastMileTaskListView,
    LastMileTaskDetailView,
    CreateLastMileTaskView,
    AssignLastMileTaskView,
    # Drones
    DroneListView,
    # Batch
    DispatchBatchCreateView,
    # AJAX / API
    available_drivers_api,
    available_drones_api,
    driver_tasks_api,
    dispatch_stats_api,
)

app_name = "logistics"


# ============================================================================
# DISPATCH OPERATIONS CENTRE  (new in v3.0)
# ============================================================================

dispatch_patterns = [
    path("", DispatchDashboardView.as_view(), name="dispatch_dashboard"),

    # Driver management
    path("drivers/", DriverRosterView.as_view(), name="dispatch_driver_roster"),
    path("drivers/register/", DriverRegistrationView.as_view(), name="dispatch_driver_register"),
    path("drivers/<uuid:pk>/", DriverProfileView.as_view(), name="dispatch_driver_detail"),
    path("drivers/<uuid:pk>/edit/", DriverEditView.as_view(), name="dispatch_driver_edit"),
    path("drivers/<uuid:pk>/approve/", approve_driver, name="dispatch_driver_approve"),
    path("drivers/<uuid:pk>/reject/", reject_driver, name="dispatch_driver_reject"),
    path("drivers/<uuid:pk>/suspend/", suspend_driver, name="dispatch_driver_suspend"),

    # Vetting queue
    path("vetting/", VettingQueueView.as_view(), name="dispatch_vetting_queue"),

    # Drone fleet
    path("drones/", DroneListView.as_view(), name="dispatch_drone_list"),

    # Pickup tasks
    path("pickup/", PickupTaskListView.as_view(), name="dispatch_pickup_task_list"),
    path("pickup/create/", CreatePickupTaskView.as_view(), name="dispatch_pickup_task_create"),
    path("pickup/<uuid:pk>/", PickupTaskDetailView.as_view(), name="dispatch_pickup_task_detail"),
    path("pickup/<uuid:pk>/assign/", AssignPickupTaskView.as_view(), name="dispatch_pickup_task_assign"),
    path("pickup/<uuid:pk>/status/<str:action>/", PickupTaskStatusUpdateView.as_view(), name="dispatch_pickup_task_status"),

    # Last mile delivery tasks
    path("delivery/", LastMileTaskListView.as_view(), name="dispatch_last_mile_list"),
    path("delivery/create/", CreateLastMileTaskView.as_view(), name="dispatch_last_mile_create"),
    path("delivery/<uuid:pk>/", LastMileTaskDetailView.as_view(), name="dispatch_last_mile_detail"),
    path("delivery/<uuid:pk>/assign/", AssignLastMileTaskView.as_view(), name="dispatch_last_mile_assign"),

    # Batch dispatch
    path("batch/create/", DispatchBatchCreateView.as_view(), name="dispatch_batch_create"),

    # JSON APIs
    path("api/drivers/available/", available_drivers_api, name="dispatch_api_available_drivers"),
    path("api/drones/available/", available_drones_api, name="dispatch_api_available_drones"),
    path("api/drivers/<uuid:pk>/tasks/", driver_tasks_api, name="dispatch_api_driver_tasks"),
    path("api/stats/", dispatch_stats_api, name="dispatch_api_stats"),
]


# ============================================================================
# DASHBOARD & ANALYTICS
# ============================================================================

dashboard_patterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("analytics/", views.AssignmentAnalyticsView.as_view(), name="analytics"),
]


# ============================================================================
# SHIPMENT MANAGEMENT
# ============================================================================

shipment_patterns = [
    path("", views.ShipmentListView.as_view(), name="shipment_list"),
    path("<int:pk>/", views.ShipmentDetailView.as_view(), name="shipment_detail"),
    path("create/", views.ShipmentCreateView.as_view(), name="shipment_create"),
    path("<int:pk>/edit/", views.ShipmentUpdateView.as_view(), name="shipment_edit"),
    path("<int:pk>/delete/", views.ShipmentDeleteView.as_view(), name="shipment_delete"),
    path("<int:pk>/update-status/", views.update_shipment_status, name="update_shipment_status"),
    path("<int:shipment_pk>/mark-delivered/", views.mark_order_as_delivered, name="mark_order_delivered"),
    path("<int:shipment_pk>/cancel/", views.cancel_shipment, name="cancel_shipment"),
    path("<int:shipment_pk>/order-status/", views.get_shipment_order_status, name="get_order_status"),
    path("export/csv/", views.export_shipments_csv, name="shipment_export_csv"),
    path("export/excel/", views.export_shipments_excel, name="shipment_export_excel"),
    path("export/pdf/", views.export_shipments_pdf, name="shipment_export_pdf"),
]


# ============================================================================
# BOX MANAGEMENT
# ============================================================================

box_patterns = [
    path("<int:shipment_pk>/boxes/create/", views.ShipmentBoxCreateView.as_view(), name="box_create"),
    path("<int:shipment_pk>/boxes/manage/", views.manage_shipment_boxes, name="manage_boxes"),
    path("<int:shipment_pk>/boxes/bulk-create/", views.bulk_create_boxes, name="box_bulk_create"),
    path("boxes/<int:pk>/", views.ShipmentBoxDetailView.as_view(), name="box_detail"),
    path("boxes/<int:pk>/edit/", views.ShipmentBoxUpdateView.as_view(), name="box_edit"),
    path("boxes/<int:pk>/delete/", views.ShipmentBoxDeleteView.as_view(), name="box_delete"),
    path("boxes/<int:box_id>/generate-label/", views.generate_box_label, name="generate_box_label"),
    path("<int:shipment_id>/boxes/generate-all-labels/", views.generate_all_box_labels, name="generate_all_labels"),
    path("boxes/<int:box_pk>/items/create/", views.BoxItemCreateView.as_view(), name="box_item_create"),
    path("box-items/<int:pk>/", views.BoxItemDetailView.as_view(), name="box_item_detail"),
    path("box-items/<int:pk>/edit/", views.BoxItemUpdateView.as_view(), name="box_item_edit"),
    path("box-items/<int:pk>/delete/", views.BoxItemDeleteView.as_view(), name="box_item_delete"),
]


# ============================================================================
# DRIVER PORTAL  (self-service for drivers)
# ============================================================================

driver_portal_patterns = [
    path("dashboard/", views.driver_dashboard, name="driver_dashboard"),
    path("profile/", views.driver_profile, name="driver_profile"),
    path("profile/edit/", views.driver_profile_edit, name="driver_profile_edit"),
    path("shipment/<int:shipment_id>/", views.shipment_detail_map, name="shipment_detail_map"),
    path("shipment/<int:shipment_id>/start/", views.start_delivery, name="start_delivery"),
    path("shipment/<int:shipment_id>/delivered/", views.mark_delivered, name="mark_delivered"),
    path("shipment/<int:shipment_id>/location/", views.get_shipment_location, name="get_shipment_location"),
    path("shipment/<int:shipment_id>/update-location/", views.update_driver_location, name="update_driver_location"),
]


# ============================================================================
# DRIVER ADMIN  (legacy Driver model)
# ============================================================================

driver_patterns = [
    path("", views.DriverListView.as_view(), name="driver_list"),
    path("<int:pk>/", views.DriverDetailView.as_view(), name="driver_detail"),
    path("create/", views.DriverCreateView.as_view(), name="driver_create"),
    path("<int:pk>/edit/", views.DriverUpdateView.as_view(), name="driver_edit"),
    path("<int:pk>/delete/", views.DriverDeleteView.as_view(), name="driver_delete"),
    path("<int:pk>/deactivate/", views.deactivate_driver, name="driver_deactivate"),
    path("<int:pk>/activate/", views.activate_driver, name="driver_activate"),
    path("<int:pk>/statistics/", views.driver_statistics, name="driver_statistics"),
    path("<int:pk>/performance/", views.driver_performance, name="driver_performance"),
    path("driver/shipment/<int:shipment_id>/location/update/", views.update_driver_location, name="update_driver_location"),
    path("driver/shipment/<int:shipment_id>/location/latest/", views.get_latest_driver_location, name="get_latest_driver_location"),
]


# ============================================================================
# VEHICLE MANAGEMENT
# ============================================================================

vehicle_patterns = [
    path("", views.VehicleListView.as_view(), name="vehicle_list"),
    path("<int:pk>/", views.VehicleDetailView.as_view(), name="vehicle_detail"),
    path("create/", views.VehicleCreateView.as_view(), name="vehicle_create"),
    path("<int:pk>/edit/", views.VehicleUpdateView.as_view(), name="vehicle_edit"),
    path("<int:pk>/delete/", views.VehicleDeleteView.as_view(), name="vehicle_delete"),
    path("<int:pk>/deactivate/", views.deactivate_vehicle, name="vehicle_deactivate"),
    path("<int:pk>/activate/", views.activate_vehicle, name="vehicle_activate"),
    path("<int:pk>/maintenance/", views.vehicle_maintenance_log, name="vehicle_maintenance"),
    path("<int:pk>/maintenance/add/", views.add_maintenance_record, name="add_maintenance"),
    path("<int:pk>/maintenance/schedule/", views.schedule_maintenance, name="schedule_maintenance"),
]


# ============================================================================
# WAREHOUSE MANAGEMENT
# ============================================================================

warehouse_patterns = [
    path("", views.WarehouseListView.as_view(), name="warehouse_list"),
    path("<int:pk>/", views.WarehouseDetailView.as_view(), name="warehouse_detail"),
    path("create/", views.WarehouseCreateView.as_view(), name="warehouse_create"),
    path("<int:pk>/edit/", views.WarehouseUpdateView.as_view(), name="warehouse_edit"),
    path("<int:pk>/delete/", views.WarehouseDeleteView.as_view(), name="warehouse_delete"),
    path("<int:pk>/deactivate/", views.deactivate_warehouse, name="warehouse_deactivate"),
    path("<int:pk>/activate/", views.activate_warehouse, name="warehouse_activate"),
    path("<int:pk>/queue/", views.warehouse_queue, name="warehouse_queue"),
    path("queue/item/<int:pk>/", views.WarehouseQueueItemDetailView.as_view(), name="warehouse_item_detail"),
    path("<int:pk>/inventory/", views.warehouse_inventory, name="warehouse_inventory"),
    path("<int:pk>/utilization/", views.warehouse_utilization, name="warehouse_utilization"),
    path("warehouse/orders/<int:order_id>/", views.warehouse_order_detail, name="warehouse_order_detail"),
]


# ============================================================================
# LOGISTIC OFFICE
# ============================================================================

office_patterns = [
    path("", views.LogisticOfficeListView.as_view(), name="logistic_office_list"),
    path("<int:pk>/", views.LogisticOfficeDetailView.as_view(), name="logistic_office_detail"),
    path("create/", views.LogisticOfficeCreateView.as_view(), name="logistic_office_create"),
    path("<int:pk>/edit/", views.LogisticOfficeUpdateView.as_view(), name="logistic_office_edit"),
    path("<int:pk>/delete/", views.LogisticOfficeDeleteView.as_view(), name="logistic_office_delete"),
]


# ============================================================================
# ASSIGNMENT MANAGEMENT
# These are the assignment views that actually exist in views.py
# ============================================================================

assignment_patterns = [
    path("", views.AssignmentDashboardView.as_view(), name="assignment_dashboard"),
    path("vehicles/", views.VehicleAssignmentListView.as_view(), name="vehicle_assignment_list"),
    path("drivers/", views.DriverAssignmentListView.as_view(), name="driver_assignment_list"),
    path("assign-vehicle/", views.assign_vehicle_to_driver, name="assign_vehicle"),
    path("quick-assign/", views.quick_assign_vehicle, name="quick_assign_vehicle"),
    path("bulk-assign/", views.bulk_assign_vehicles, name="bulk_assign_vehicles"),
    path("vehicle/<int:vehicle_id>/unassign/", views.unassign_vehicle, name="unassign_vehicle"),
    path("shipment/<int:shipment_id>/reassign/", views.reassign_shipment, name="reassign_shipment"),
    path("report/", views.assignment_report, name="assignment_report"),
    path("report/export/", views.assignment_report_export, name="assignment_report_export"),
    path("report/json/", views.assignment_report_json, name="assignment_report_json"),
]


# ============================================================================
# AJAX / API
# Only references ajax views that actually exist in views.py
# ============================================================================

ajax_patterns = [
    path("addresses-for-order/", views.ajax_addresses_for_order, name="ajax_addresses_for_order"),
    path("addresses-by-order/", views.ajax_addresses_by_order, name="ajax_addresses_by_order"),
    path("orders-for-address/", views.ajax_orders_for_address, name="ajax_orders_for_address"),
    path("vehicles-by-driver/", views.ajax_vehicles_by_driver, name="ajax_vehicles_by_driver"),
    path("unassigned-vehicles/", views.get_unassigned_vehicles_ajax, name="ajax_unassigned_vehicles"),
    path("drivers-by-vehicle/", views.ajax_drivers_by_vehicle, name="ajax_drivers_by_vehicle"),
    path("driver/<int:driver_id>/vehicles/", views.get_driver_vehicles_ajax, name="ajax_driver_vehicles"),
    path("shipment/<int:shipment_id>/status/", views.get_shipment_status_ajax, name="ajax_shipment_status"),
    path("shipment/<int:shipment_id>/tracking/", views.get_tracking_info_ajax, name="ajax_tracking_info"),
    path("search-shipments/", views.ajax_search_shipments, name="ajax_search_shipments"),
    path("filter-warehouses/", views.ajax_filter_warehouses, name="ajax_filter_warehouses"),
    path("api/unassigned-vehicles/", views.api_unassigned_vehicles, name="api_unassigned_vehicles"),
]


# ============================================================================
# REPORTS
# Only references report views that actually exist in views.py
# ============================================================================

report_patterns = [
    path("", views.reports_dashboard, name="reports_dashboard"),
    path("delivery-performance/", views.delivery_performance_report, name="report_delivery_performance"),
    path("driver-performance/", views.driver_performance_report, name="report_driver_performance"),
    path("warehouse-utilization/", views.warehouse_utilization_report, name="report_warehouse_utilization"),
    path("custom/", views.custom_report_builder, name="report_custom_builder"),
    path("custom/generate/", views.generate_custom_report, name="report_custom_generate"),
    path("export/pdf/", views.export_report_pdf, name="report_export_pdf"),
    path("export/csv/", views.export_report_csv, name="report_export_csv"),
    path("export/excel/", views.export_report_excel, name="report_export_excel"),
]


# ============================================================================
# NOTIFICATIONS
# Only references notification views that actually exist in views.py
# ============================================================================

notification_patterns = [
    # "notifications_list" is what base.html uses at the footer link
    path("", views.notification_list, name="notifications_list"),
    # "notification_mark_as_read" is what base.html uses per-item (passes pk=0 as placeholder)
    path("<int:pk>/mark-read/", views.mark_notification_read, name="notification_mark_as_read"),
    # "notification_mark_all_as_read" is what base.html uses for the "mark all" button
    path("mark-all-read/", views.mark_all_notifications_read, name="notification_mark_all_as_read"),
    path("settings/", views.notification_settings, name="notification_settings"),
    path("dropdown/", views.notification_dropdown, name="notification_dropdown"),
    path("<int:notification_id>/detail/", views.notification_detail, name="notification_detail"),
]


# ============================================================================
# ROOT URL PATTERNS
# ============================================================================

urlpatterns = [
    # ── Dashboard ─────────────────────────────────────────────────────────────
    path("", include(dashboard_patterns)),

    # ── NEW: Dispatch Operations Centre ───────────────────────────────────────
    path("dispatch/", include(dispatch_patterns)),

    # ── Core modules ──────────────────────────────────────────────────────────
    path("shipments/", include(shipment_patterns)),
    path("shipments/", include(box_patterns)),
    path("drivers/", include(driver_patterns)),
    path("driver/", include(driver_portal_patterns)),
    path("vehicles/", include(vehicle_patterns)),
    path("warehouses/", include(warehouse_patterns)),
    path("offices/", include(office_patterns)),

    # ── Assignments / AJAX / Reports / Notifications ───────────────────────────
    path("assignments/", include(assignment_patterns)),
    path("ajax/", include(ajax_patterns)),
    path("reports/", include(report_patterns)),
    path("notifications/", include(notification_patterns)),

    # ── Orders utility ─────────────────────────────────────────────────────────
    path("orders/<int:order_id>/items-preview/", views.order_items_preview, name="order_items_preview"),

    # ── B2B Shipments ──────────────────────────────────────────────────────────
    path("b2b/shipments/", views.b2b_shipment_list, name="b2b_shipment_list"),
    path("b2b/shipments/<uuid:order_id>/", views.b2b_shipment_detail, name="b2b_shipment_detail"),
    path("b2b/shipments/<uuid:order_id>/boxes/bulk-create/", views.b2b_bulk_create_boxes, name="b2b_bulk_create_boxes"),
    path("b2b/box/<int:box_id>/label/", views.b2b_generate_box_label, name="b2b_generate_box_label"),
    path("b2b/shipments/<uuid:order_id>/labels/all/", views.b2b_generate_all_box_labels, name="b2b_generate_all_box_labels"),
    path("b2b/box/<int:box_id>/print-label/", views.b2b_print_box_label, name="b2b_print_box_label"),
    path("b2b/shipments/<uuid:order_id>/print-all-labels/", views.b2b_print_all_labels, name="b2b_print_all_labels"),
    path("b2b/box/<int:box_id>/items/add/", views.b2b_box_item_add, name="b2b_box_item_add"),
    path("b2b/box-item/<int:item_id>/delete/", views.b2b_box_item_delete, name="b2b_box_item_delete"),
    path("b2b/shipments/<uuid:order_id>/unlock/", views.b2b_unlock_shipment, name="b2b_unlock_shipment"),
    path("b2b/shipments/<uuid:order_id>/lock/", views.b2b_lock_shipment, name="b2b_lock_shipment"),
    path("b2b/shipments/<uuid:order_id>/mark-in-transit/", views.b2b_mark_in_transit, name="b2b_mark_in_transit"),
    path("b2b/shipments/<uuid:order_id>/mark-delivered/", views.b2b_mark_delivered, name="b2b_mark_delivered"),
    path("b2b/shipments/<uuid:order_id>/revert-to-in-transit/", views.b2b_revert_to_in_transit, name="b2b_revert_to_in_transit"),

    # ── Logistics Agent Management ─────────────────────────────────────────────
    # NOTE: view signature is assign_logistics_agent(request, order_id) — no store_id
    path("orders/<int:order_id>/assign-agent/", views.assign_logistics_agent, name="assign_logistics_agent"),
    path("orders/<int:order_id>/agent-status/", views.update_agent_status, name="update_agent_status"),
    path("orders/<int:order_id>/get-agent-status/", views.get_agent_status, name="get_agent_status"),
    path("api/logistics-agents/available/", views.list_available_agents, name="list_available_agents"),

    # ── Shipment Chat ──────────────────────────────────────────────────────────
    path("shipments/<int:shipment_id>/chat/send/", views.send_shipment_chat_message, name="send_shipment_chat"),
    path("shipments/<int:shipment_id>/chat/messages/", views.get_shipment_chat_messages, name="get_shipment_chat_messages"),
    path("shipments/<int:shipment_id>/chat/unread-count/", views.get_shipment_unread_count, name="get_shipment_unread_count"),

    # ── Warehouse Receiving ────────────────────────────────────────────────────
    path("warehouse/", views.warehouse_receiving_dashboard, name="warehouse_receiving_dashboard"),
    path("warehouse/scan/", views.warehouse_scan_verify, name="warehouse_scan_verify"),
    path("warehouse/verify-code/", views.verify_code_ajax, name="verify_code_ajax"),
    path("shipment/<int:shipment_id>/start-receiving/", views.start_receiving_shipment, name="start_receiving_shipment"),
    path("shipment/<str:tracking_code>/tracking/", views.shipment_tracking_detail, name="shipment_tracking_detail"),
    path("warehouse/receipt/<int:receipt_id>/", views.warehouse_receipt_detail, name="warehouse_receipt_detail"),
    path("warehouse/receipt/<int:receipt_id>/verify/", views.warehouse_verify_receipt, name="warehouse_verify_receipt"),
    path("shipment/<int:shipment_id>/qr/", views.generate_shipment_qr_code, name="generate_shipment_qr_code"),
    path("warehouse/receipt/<int:receipt_id>/qr/", views.generate_receipt_qr_code, name="generate_receipt_qr_code"),

    # ── Crossroad / Black Market ───────────────────────────────────────────────
    path("crossroad/dashboard/", views.crossroad_dashboard, name="crossroad_dashboard"),
    path("crossroad/export/", views.crossroad_export_orders, name="crossroad_export_orders"),
    path("crossroad/order/<uuid:order_id>/", views.crossroad_order_detail, name="crossroad_order_detail"),
    path("crossroad/order/<uuid:order_id>/update-status/", views.update_order_status, name="update_order_status"),
    path("crossroad/order/<uuid:order_id>/complete-vetting/", views.mark_vetting_complete, name="mark_vetting_complete"),
    path("crossroad/vetting/queue/", views.crossroad_vetting_queue, name="crossroad_vetting_queue"),
    path("order/<uuid:order_id>/update-vetting-fee/", views.update_vetting_fee, name="update_vetting_fee"),

    # ── Fleet Map ──────────────────────────────────────────────────────────────
    path("fleet-map/", fleet_map_view, name="fleet_map"),
    path("api/fleet-map-data/", fleet_map_data, name="fleet_map_data"),
    path("api/route/<int:route_id>/", route_detail_api, name="route_detail_api"),
    path("api/update-vehicle-location/", update_vehicle_location, name="update_vehicle_location"),
]