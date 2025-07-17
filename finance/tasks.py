from celery import shared_task
from django.apps import apps
from stores.models import Store  # Import from stores app
from .models import LogisticsIntegration, FinancialMetricsIntegration
from decimal import Decimal


@shared_task
def update_logistics_data():
    """Background task to update logistics data periodically"""
    try:
        from orders.models import OrderItem, Return

        for store in Store.objects.filter(status='active'):
            # Your logistics data update logic here
            # This is similar to the management command above
            pass

    except ImportError:
        print("Order models not found")


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