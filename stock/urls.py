from django.urls import path
from . import views

urlpatterns = [
    path('update/<int:stock_id>/', views.update_stock_quantity, name='update_stock_quantity'),
]
