from celery import shared_task
from django.apps import apps
from stores.models import Store  # Import from stores app
from .models import LogisticsIntegration, FinancialMetricsIntegration
from decimal import Decimal

@shared_task
def update_logistics_data():
    from logistics.models import Shipment

    for store in Store.objects.filter(status="active"):
        logistics, _ = LogisticsIntegration.objects.get_or_create(store=store)

        qs = Shipment.objects.filter(order__items__product__store=store).distinct()

        logistics.total_shipments = qs.count()
        logistics.pending_shipments = qs.filter(status__in=["pending", "in_transit"]).count()
        logistics.completed_shipments = qs.filter(status__in=["delivered", "completed"]).count()
        logistics.failed_shipments = qs.filter(status="failed").count()

        logistics.save(update_fields=[
            "total_shipments", "pending_shipments", "completed_shipments", "failed_shipments", "last_updated"
        ])


@shared_task
def calculate_daily_financial_metrics():
    """Calculate daily financial metrics for all stores"""
    from django.utils import timezone

    for store in Store.objects.filter(status='active'):
        FinancialMetricsIntegration.sync_with_store_metrics(store)


@shared_task
def generate_financial_summaries(period='monthly'):
    """Generate financial summaries for all stores"""
    from .services import FinancialService

    for store in Store.objects.filter(status='active'):
        if period == 'monthly':
            FinancialService.generate_monthly_summary(store)
        elif period == 'weekly':
            FinancialService.generate_weekly_summary(store)