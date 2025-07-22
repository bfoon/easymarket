from django.urls import path
from . import views
from .views import login_view
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('register/', views.register_view, name='register'),
    path('sign_in/', login_view, name='sign_in'),
    path('signoff/', views.custom_logout, name='signoff'),
    path('edit-address-modal/', views.edit_address_modal, name='edit_address_modal'),
    path('profile/',  views.user_profile, name='user_profile'),
    path('admin/logs/', views.admin_logs, name='admin_logs'),
    path('admin/logs/<int:pk>/', views.admin_log_detail, name='admin_log_detail'),
    path('admin/logs/<int:pk>/mark-reviewed/', views.mark_log_reviewed, name='mark_log_reviewed'),
    path('admin/logs/<int:pk>/flag/', views.flag_log_entry, name='flag_log_entry'),
    path('admin/logs/<int:pk>/save-note/', views.save_log_note, name='save_log_note'),


]