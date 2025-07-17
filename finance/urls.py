from django.urls import path
from . import views

app_name = 'finance'

urlpatterns = [
    path('', views.store_dashboard, name='dashboard'),
    path('store/<uuid:store_id>/', views.store_detail, name='store_detail'),
    path('reports/', views.financial_reports, name='reports'),
]