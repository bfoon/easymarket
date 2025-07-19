from django.urls import path
from . import views

app_name = 'stores'

urlpatterns = [
    # Store management URLs - Store creation and general management
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
    path('manage/<uuid:store_id>/stock/<int:product_id>/update/', views.update_stock, name='update_stock'),
    path('manage/<uuid:store_id>/inventory/history/', views.inventory_history, name='inventory_history'),

    # Financial management
    path('manage/<uuid:store_id>/financial/', views.financial_dashboard, name='financial_dashboard'),
    path('manage/<uuid:store_id>/analytics/', views.sales_analytics, name='sales_analytics'),
    path('manage/<uuid:store_id>/financial/export/', views.export_financial_report, name='export_financial_report'),

    # Order management
    path('manage/<uuid:store_id>/orders/', views.store_orders, name='store_orders'),
    path('manage/<uuid:store_id>/orders/<int:order_id>/', views.store_order_detail, name='store_order_detail'),
    path('orders/<int:order_id>/update-status/', views.update_order_status, name='update_order_status'),
    path('orders/items/<int:item_id>/update-quantity/', views.update_order_item_quantity, name='update_order_item_quantity'),

    # Chat and communication
    path('manage/<uuid:store_id>/chat/', views.store_chat_panel, name='store_chat_panel'),
    path('manage/<uuid:store_id>/chat/<int:thread_id>/', views.chat_thread_detail, name='chat_thread_detail'),
    path('manage/<uuid:store_id>/chat/start/<int:buyer_id>/', views.start_store_chat, name='start_store_chat'),
    path('manage/<uuid:store_id>/chat/start/<int:buyer_id>/<int:order_id>/', views.start_store_chat, name='start_store_chat_with_order'),

    # AJAX endpoints
    path('ajax/chat/send/', views.send_store_chat_message, name='send_store_chat_message'),
    path('ajax/chat/<int:recipient_id>/messages/', views.fetch_store_chat_messages, name='fetch_store_chat_messages'),
    path('ajax/chat/order/send/', views.send_chat_message, name='send_chat_message'),
    path('ajax/chat/order/<int:order_id>/messages/', views.fetch_chat_messages, name='fetch_chat_messages'),

    # API endpoints
    path('api/stores/<uuid:store_id>/metrics/', views.store_metrics_api, name='store_metrics_api'),
    path('api/stores/<uuid:store_id>/inventory/bulk-update/', views.bulk_inventory_update, name='bulk_inventory_update'),

    # Product detail (public view)
    path('product/<int:product_id>/', views.product_detail, name='product_detail'),

    # Public store display URLs (using slug for SEO-friendly URLs) - MUST come last to avoid conflicts
    path('<slug:slug>/', views.store_detail, name='store_detail'),
    path('<slug:slug>/products/', views.store_products, name='store_products'),
]