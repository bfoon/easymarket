from django.urls import path
from . import views

app_name = 'stores'

urlpatterns = [
    # Store management URLs
    path('create/', views.create_store, name='create_store'),
    path('manage/', views.manage_stores, name='manage_stores'),
    path('update/<uuid:store_id>/', views.update_store, name='update_store'),
    path('delete/<uuid:store_id>/', views.delete_store, name='delete_store'),

    # Store status management
    path('toggle-status/<uuid:store_id>/', views.toggle_store_status, name='toggle_store_status'),

    # Store analytics/dashboard
    path('dashboard/<uuid:store_id>/', views.store_dashboard, name='store_dashboard'),

    # Product management URLs (using UUID for management) - MUST come before slug patterns
    path('manage/<uuid:store_id>/add-product/', views.add_product, name='add_product'),
    path('manage/<uuid:store_id>/products/', views.manage_store_products, name='manage_store_products'),
    path('product/<int:product_id>/', views.product_detail, name='product_detail'),

    # Public store display URLs (using slug for SEO-friendly URLs) - MUST come after UUID patterns
    path('<slug:slug>/', views.store_detail, name='store_detail'),
    path('<slug:slug>/products/', views.store_products, name='store_products'),
]