from django.urls import path
from . import views

app_name = 'stores'

urlpatterns = [
    # Store management URLs - All management under /admin/ prefix to avoid conflicts
    path('create/', views.create_store, name='create_store'),
    path('manage/', views.manage_stores, name='manage_stores'),

    # Store admin/management URLs (completely separate from public URLs)
    path('admin/<uuid:store_id>/dashboard/', views.store_dashboard, name='store_dashboard'),
    path('admin/<uuid:store_id>/update/', views.update_store, name='update_store'),
    path('admin/<uuid:store_id>/delete/', views.delete_store, name='delete_store'),
    path('admin/<uuid:store_id>/toggle-status/', views.toggle_store_status, name='toggle_store_status'),

    # Product management URLs - All under /admin/ prefix
    path('admin/<uuid:store_id>/add-product/', views.add_product, name='add_product'),
    path('admin/<uuid:store_id>/products/', views.manage_store_products, name='manage_store_products'),
    path('admin/<uuid:store_id>/products/<int:product_id>/edit/', views.edit_product, name='edit_product'),
    path('admin/<uuid:store_id>/products/<int:product_id>/images/<int:image_id>/delete/',
         views.delete_product_image, name='delete_product_image'),
    path('<uuid:store_id>/orders/', views.store_orders, name='store_orders'),

    # Public store display URLs (using slug for SEO-friendly URLs) - MUST come last
    path('<slug:slug>/', views.store_detail, name='store_detail'),
    path('<slug:slug>/products/', views.store_products, name='store_products'),

    path('product/<int:product_id>/', views.product_detail, name='product_detail'),
    path('<int:store_id>/products/<int:product_id>/delete/', views.delete_product, name='delete_product'),

    # Product image management
    path('<int:store_id>/products/<int:product_id>/images/<int:image_id>/delete/', views.delete_product_image,
         name='delete_product_image'),
    path('store/<uuid:store_id>/order/<int:order_id>/', views.store_order_detail, name='store_order_detail'),
    path('order/<int:order_id>/update-status/', views.update_order_status, name='update_order_status'),
    path('<int:store_id>/chat/<int:buyer_id>/', views.start_store_chat, name='start_store_chat'),
    path('chat/send/', views.send_chat_message, name='send_chat_message'),
    path('chat/fetch/<int:order_id>/', views.fetch_chat_messages, name='fetch_chat_messages'),
    path('order/item/<int:item_id>/update-quantity/', views.update_order_item_quantity, name='update_order_item_quantity'),
    path('order/<int:order_id>/update-status/', views.update_order_status, name='update_order_status'),


]