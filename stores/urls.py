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

    # Public store display URLs (using slug for SEO-friendly URLs) - MUST come last
    path('<slug:slug>/', views.store_detail, name='store_detail'),
    path('<slug:slug>/products/', views.store_products, name='store_products'),

    path('product/<int:product_id>/', views.product_detail, name='product_detail'),
]