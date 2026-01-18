from django.urls import path, include
from . import views

app_name = 'stores'

urlpatterns = [
    # Store management URLs - Store creation and general management
    path('', views.store_list, name='store_list'),

    # 🔹 NEW: B2B marketplace URL
    path("b2b/", views.b2b_marketplace, name="b2b_marketplace"),
    path("stores/<uuid:store_id>/api/b2b-counts/", views.b2b_counts, name="b2b_counts"),

    path("<slug:slug>/b2b-settings/", views.b2b_settings, name="b2b_settings"),

    path('favorites/', views.my_favorite_stores, name='my_favorite_stores'),
    path('create/', views.create_store, name='create_store'),
    path('manage/', views.manage_stores, name='manage_stores'),

    # Store dashboard and admin URLs (using manage/ prefix for consistency)
    path('manage/<uuid:store_id>/dashboard/', views.store_dashboard, name='store_dashboard'),
    path('manage/<uuid:store_id>/update/', views.update_store, name='update_store'),
    path('manage/<uuid:store_id>/delete/', views.delete_store, name='delete_store'),
    path('manage/<uuid:store_id>/toggle-status/', views.toggle_store_status, name='toggle_store_status'),

    # Store settings and configuration
    path('manage/<uuid:store_id>/settings/', views.store_settings, name='store_settings'),

    # Product management URLs
    path('manage/<uuid:store_id>/products/', views.manage_store_products, name='manage_store_products'),
    path('manage/<uuid:store_id>/products/add/', views.add_product, name='add_product'),
    path('manage/<uuid:store_id>/products/<int:product_id>/edit/', views.edit_product, name='edit_product'),
    path('manage/<uuid:store_id>/products/<int:product_id>/delete/', views.delete_product, name='delete_product'),
    path('manage/<uuid:store_id>/products/<int:product_id>/images/<int:image_id>/delete/',
         views.delete_product_image, name='delete_product_image'),

    # Stock management
    path('manage/<uuid:store_id>/stock/', views.stock_management, name='stock_management'),
    path('manage/<uuid:store_id>/stock/<int:product_id>/update/',
         views.update_stock_quantity,
         name='update_stock_quantity'),

    path('manage/<uuid:store_id>/warehouse/update/',
         views.update_warehouse,
         name='update_warehouse'),

    path('manage/<uuid:store_id>/stock/export/',
         views.export_stock,
         name='export_stock'),
    path('manage/<uuid:store_id>/stock/<int:product_id>/update/', views.update_stock, name='update_stock'),
    path('manage/<uuid:store_id>/inventory/history/', views.inventory_history, name='inventory_history'),
    path(
        "manage/<uuid:store_id>/stock/history/<int:product_id>/",
        views.stock_history,
        name="stock_history"
    ),

    # Financial management
    path('manage/<uuid:store_id>/financial/', views.financial_dashboard, name='financial_dashboard'),
    path('manage/<uuid:store_id>/analytics/', views.sales_analytics, name='sales_analytics'),
    path('manage/<uuid:store_id>/financial/export/', views.export_financial_report, name='export_financial_report'),

    # Order management
    path('manage/<uuid:store_id>/orders/', views.store_orders, name='store_orders'),
    path('manage/<uuid:store_id>/orders/<int:order_id>/', views.store_order_detail, name='store_order_detail'),
    path('orders/<int:order_id>/update-status/', views.update_order_status, name='update_order_status'),
    path('orders/items/<int:item_id>/update-quantity/', views.update_order_item_quantity,
         name='update_order_item_quantity'),
    path('<uuid:store_id>/order/<int:order_id>/set-shipping-cost/', views.set_shipping_cost, name='set_shipping_cost'),

    # Chat and communication
    path('manage/<uuid:store_id>/chat/', views.store_chat_panel, name='store_chat_panel'),
    path('manage/<uuid:store_id>/chat/<str:thread_id>/', views.chat_thread_detail, name='chat_thread_detail'),
    path('manage/<uuid:store_id>/chat/start/<int:buyer_id>/', views.start_store_chat, name='start_store_chat'),
    path('manage/<uuid:store_id>/chat/start/<int:buyer_id>/<int:order_id>/', views.start_store_chat,
         name='start_store_chat_with_order'),

    # AJAX endpoints
    path('ajax/chat/send/', views.send_store_chat_message, name='send_store_chat_message'),
    path('ajax/chat/<int:recipient_id>/messages/', views.fetch_store_chat_messages, name='fetch_store_chat_messages'),
    path('ajax/chat/order/send/', views.send_chat_message, name='send_chat_message'),
    path('ajax/chat/order/<int:order_id>/messages/', views.fetch_chat_messages, name='fetch_chat_messages'),
    path('api/toggle-favorite/', views.toggle_store_favorite, name='toggle_favorite'),
    path('api/search-suggestions/', views.store_search_suggestions, name='search_suggestions'),
    path('api/user-counts/', views.get_user_store_counts, name='user_counts'),

    # API endpoints
    path('api/stores/<uuid:store_id>/metrics/', views.store_metrics_api, name='store_metrics_api'),
    path('api/stores/<uuid:store_id>/inventory/bulk-update/', views.bulk_inventory_update,
         name='bulk_inventory_update'),
    path('api/b2b-inquiry/', views.create_b2b_inquiry, name='create_b2b_inquiry'),

    # Product detail (public view)
    path('product/<int:product_id>/', views.product_detail, name='product_detail'),

    # ⭐⭐⭐ CRITICAL: SLUG-BASED FOLLOW ENDPOINTS - MUST BE HERE (before generic <slug:slug>/) ⭐⭐⭐
    # These handle the follow functionality from public store pages
    path('<slug:slug>/follow/', views.follow_store_by_slug, name='follow_store_by_slug'),
    path('<slug:slug>/follow-status/', views.get_follow_status_by_slug, name='follow_status_by_slug'),

    # Public store display URLs (using slug for SEO-friendly URLs) - MUST come AFTER specific slug patterns
    path('<slug:slug>/', views.store_detail, name='store_detail'),
    path('<slug:slug>/products/', views.store_products, name='store_products'),

    # Referral (moved after generic slug to avoid conflicts)
    path('refer/store/<uuid:store_id>/', views.create_store_referral, name='refer_store'),

    # Legacy UUID-based follow URLs (kept for backward compatibility with admin/API)
    path('api/follow/<uuid:store_id>/', views.toggle_store_follow, name='toggle_store_follow'),
    path('api/follow-status/<uuid:store_id>/', views.get_store_follow_status, name='get_store_follow_status'),
    path('api/followed-stores/', views.get_followed_stores, name='get_followed_stores'),

    # Notification URLs
    path('api/notifications/', views.get_user_notifications, name='get_user_notifications'),
    path('api/notifications/<int:notification_id>/read/', views.mark_notification_read, name='mark_notification_read'),
    path('api/notifications/mark-all-read/', views.mark_all_notifications_read, name='mark_all_notifications_read'),
    path(
        "api/notifications/preferences/<uuid:store_id>/",
        views.notification_preferences,
        name="store_notification_preferences"
    ),

    path("<slug:slug>/promote/", views.store_promote, name="store_promote"),
    path("<slug:slug>/promote/subscribe/", views.create_subscription, name="promo_subscribe"),
    path("<slug:slug>/promote/campaign/new/", views.create_campaign, name="promo_campaign_create"),
    path("<slug:slug>/promote/campaign/<int:pk>/push/", views.push_campaign, name="promo_campaign_push"),

    # Campaign detail and management URLs
    path('<slug:slug>/campaigns/<int:campaign_id>/', views.campaign_detail, name='campaign_detail'),
    path('<slug:slug>/campaigns/<int:campaign_id>/submit/', views.campaign_submit_review,
         name='campaign_submit_review'),
    path('<slug:slug>/campaigns/<int:campaign_id>/approve/', views.campaign_approve, name='campaign_approve'),
    path('<slug:slug>/campaigns/<int:campaign_id>/reject/', views.campaign_reject, name='campaign_reject'),
    path('<slug:slug>/campaigns/<int:campaign_id>/pause/', views.campaign_pause, name='campaign_pause'),
    path('<slug:slug>/campaigns/<int:campaign_id>/stop/', views.campaign_stop, name='campaign_stop'),
    path('<slug:slug>/campaigns/<int:campaign_id>/duplicate/', views.campaign_duplicate, name='campaign_duplicate'),
    path('<slug:slug>/campaigns/<int:campaign_id>/delete/', views.campaign_delete, name='campaign_delete'),
    path('<slug:slug>/campaigns/<int:campaign_id>/report/download/', views.campaign_download_report,
         name='campaign_download_report'),
    path('<slug:slug>/campaigns/<int:campaign_id>/request-changes/', views.campaign_request_changes,
         name='campaign_request_changes'),

    # Theme customization URLs
    path('manage/<uuid:store_id>/theme/', views.store_theme_settings, name='store_theme_settings'),
    path('manage/<uuid:store_id>/theme/preset/apply/', views.apply_theme_preset, name='apply_theme_preset'),
    path('manage/<uuid:store_id>/theme/preview/', views.preview_theme, name='preview_theme'),
    path('manage/<uuid:store_id>/theme/reset/', views.reset_theme, name='reset_theme'),
    path('manage/<uuid:store_id>/theme/duplicate/<uuid:target_store_id>/', views.duplicate_theme,
         name='duplicate_theme'),

# Warehouse & Stock Management
    path('manage/<uuid:store_id>/stock/', views.stock_management, name='stock_management'),
    path('manage/<uuid:store_id>/warehouse/', views.manage_warehouse, name='manage_warehouse'),
    path('manage/<uuid:store_id>/stock/<int:product_id>/update/', views.update_stock, name='update_stock'),
    path('manage/<uuid:store_id>/stock/history/', views.inventory_history, name='inventory_history'),
    path('manage/<uuid:store_id>/stock/export/', views.export_stock, name='export_stock'),
    # Warehouse shipping toggle
    path('items/<int:item_id>/toggle-warehouse-shipped/',
         views.toggle_item_warehouse_shipped,
         name='toggle_item_warehouse_shipped'),
    path('orders/<int:order_id>/update-status-processing/',
         views.update_order_status_to_processing,
         name='update_order_status_to_processing'),

]