from django.urls import path
from . import views
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('register-buyer/', views.register_buyer, name='register_buyer'),
    path('login/', auth_views.LoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
]