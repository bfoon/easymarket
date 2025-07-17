from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import StoreViewSet, FinancialRecordViewSet

router = DefaultRouter()
router.register(r'stores', StoreViewSet)
router.register(r'financial-records', FinancialRecordViewSet)

urlpatterns = [
    path('api/', include(router.urls)),
]