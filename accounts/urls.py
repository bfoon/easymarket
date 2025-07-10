from django.urls import path
from . import views
from .views import login_view
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('register-buyer/', views.register_buyer, name='register_buyer'),
    path('sign_in/', login_view, name='sign_in'),
    path('signoff/', views.custom_logout, name='signoff'),
    path('edit-address-modal/', views.edit_address_modal, name='edit_address_modal'),

]