from django.urls import path
from . import views

urlpatterns = [
    path('register-buyer/', views.register_buyer, name='register_buyer'),
]