from django.urls import path
from . import views
from .views import login_view
from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy

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
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="accounts/password_reset_form.html",
            email_template_name="accounts/password_reset_email.txt",
            subject_template_name="accounts/password_reset_subject.txt",
            success_url=reverse_lazy("accounts:password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="accounts/password_reset_done.html",
        ),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
            success_url=reverse_lazy("accounts:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html",
        ),
        name="password_reset_complete",
    ),

]