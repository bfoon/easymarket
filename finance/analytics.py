from django.db.models import Sum, Avg, Count, Q, F, Value
from django.db.models.functions import TruncDate, TruncMonth, Coalesce
from django.utils import timezone
from datetime import timedelta, date
from decimal import Decimal
import pandas as pd
from .models import FinancialRecord, LogisticsIntegration
from stores.models import Store, StoreMetrics
from orders.models import Order, OrderItem, Return
from payments.models import Payment
from logistics.models import Shipment


class AdvancedFinancialAnalytics:
    """Advanced analytics for financial performance"""

    @staticmethod
    def get_cohort_analysis(store, months=6):
        """Analyze customer cohorts and retention"""
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=30 * months)

        # Get customers by month they first ordered
        customer_cohorts = Order.objects.filter(
            items__product__store=store,
            created_at__date__gte=start_date
        ).values('buyer').annotate(
            first_order_month=TruncMonth('created_at'),
            total_orders=Count('id'),
            total_spent=Sum('items__price_at_time'),
            last_order_date=F('created_at')
        ).order_by('first_order_month')

        return customer_cohorts

    @staticmethod
    def get_seasonal_trends(store, years=2):
        """Analyze seasonal sales trends"""
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=365 * years)

        seasonal_data = FinancialRecord.objects.filter(
            store=store,
            record_type='revenue',
            transaction_date__gte=start_date
        ).extra(
            select={'month': "EXTRACT(month FROM transaction_date)"}
        ).values('month').annotate(
            total_revenue=Sum('amount'),
            transaction_count=Count('id'),
            avg_transaction=Avg('amount')
        ).order_by('month')

        return seasonal_data

    @staticmethod
    def get_profit_margin_analysis(store, period_days=90):
        """Analyze profit margins by category and time"""
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=period_days)

        # Revenue by category
        revenue_by_category = FinancialRecord.objects.filter(
            store=store,
            record_type='revenue',
            transaction_date__range=[start_date, end_date]
        ).values('category').annotate(
            total_revenue=Sum('amount'),
            transaction_count=Count('id')
        )

        # Expenses by category
        expenses_by_category = FinancialRecord.objects.filter(
            store=store,
            record_type='expense',
            transaction_date__range=[start_date, end_date]
        ).values('category').annotate(
            total_expenses=Sum('amount')
        )

        # Combine revenue and expenses
        margin_analysis = {}
        for revenue in revenue_by_category:
            category = revenue['category']
            margin_analysis[category] = {
                'revenue': revenue['total_revenue'],
                'expenses': 0,
                'transactions': revenue['transaction_count']
            }

        for expense in expenses_by_category:
            category = expense['category']
            if category in margin_analysis:
                margin_analysis[category]['expenses'] = expense['total_expenses']

        # Calculate margins
        for category, data in margin_analysis.items():
            data['profit'] = data['revenue'] - data['expenses']
            data['margin_percentage'] = (
                (data['profit'] / data['revenue']) * 100
                if data['revenue'] > 0 else 0
            )

        return margin_analysis

    @staticmethod
    def get_payment_method_performance(store, period_days=30):
        """Analyze performance by payment method"""
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=period_days)

        payment_analysis = Payment.objects.filter(
            order__items__product__store=store,
            status='completed',
            payment_date__date__range=[start_date, end_date]
        ).values('method').annotate(
            transaction_count=Count('id'),
            total_amount=Sum('amount'),
            avg_amount=Avg('amount'),
            success_rate=Avg(
                Case(
                    When(status='completed', then=Value(1)),
                    default=Value(0),
                    output_field=FloatField()
                )
            ) * 100
        ).order_by('-total_amount')

        return payment_analysis

    @staticmethod
    def get_return_analysis(store, period_days=90):
        """Comprehensive return analysis"""
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=period_days)

        # Return reasons analysis
        return_reasons = Return.objects.filter(
            items__product__store=store,
            created_at__date__range=[start_date, end_date]
        ).values('reason').annotate(
            count=Count('id'),
            total_amount=Sum('refund_amount'),
            avg_processing_time=Avg(
                F('completed_at') - F('created_at'),
                output_field=DurationField()
            )
        ).order_by('-count')

        # Return trend over time
        return_trend = Return.objects.filter(
            items__product__store=store,
            created_at__date__range=[start_date, end_date]
        ).extra(
            select={'date': 'DATE(created_at)'}
        ).values('date').annotate(
            daily_returns=Count('id'),
            daily_refund_amount=Sum('refund_amount')
        ).order_by('date')

        return {
            'reasons': return_reasons,
            'trend': return_trend
        }

    @staticmethod
    def get_logistics_efficiency_metrics(store, period_days=30):
        """Analyze logistics efficiency"""
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=period_days)

        # Shipment analysis
        shipment_metrics = Shipment.objects.filter(
            order__items__product__store=store,
            created_at__date__range=[start_date, end_date]
        ).aggregate(
            total_shipments=Count('id'),
            avg_weight=Avg('weight_kg'),
            avg_size=Avg('size_cubic_meters'),
            total_shipping_cost=Sum('order__shipping_cost'),
            on_time_rate=Avg(
                Case(
                    When(
                        order__delivered_date__lte=F('estimated_dropoff_time'),
                        then=Value(1)
                    ),
                    default=Value(0),
                    output_field=FloatField()
                )
            ) * 100
        )

        # Delivery time analysis
        delivery_times = Shipment.objects.filter(
            order__items__product__store=store,
            created_at__date__range=[start_date, end_date],
            order__delivered_date__isnull=False
        ).annotate(
            delivery_time=F('order__delivered_date') - F('collect_time')
        ).values('delivery_time')

        return {
            'metrics': shipment_metrics,
            'delivery_times': delivery_times
        }

    @staticmethod
    def get_competitive_analysis(store):
        """Compare store performance with similar stores"""
        # Get stores in same category
        similar_stores = Store.objects.filter(
            category=store.category,
            status='active'
        ).exclude(id=store.id)

        # Calculate metrics for comparison
        store_metrics = []
        for comparison_store in similar_stores:
            metrics = FinancialRecord.objects.filter(
                store=comparison_store,
                transaction_date__gte=timezone.now().date() - timedelta(days=30)
            ).aggregate(
                revenue=Sum('amount', filter=Q(record_type='revenue')),
                expenses=Sum('amount', filter=Q(record_type='expense')),
                orders=Count('order_reference', distinct=True, filter=Q(record_type='revenue'))
            )

            metrics['store'] = comparison_store
            metrics['profit'] = (metrics['revenue'] or 0) - (metrics['expenses'] or 0)
            metrics['avg_order_value'] = (
                metrics['revenue'] / metrics['orders']
                if metrics['orders'] and metrics['revenue'] else 0
            )
            store_metrics.append(metrics)

        # Add current store for comparison
        current_metrics = FinancialRecord.objects.filter(
            store=store,
            transaction_date__gte=timezone.now().date() - timedelta(days=30)
        ).aggregate(
            revenue=Sum('amount', filter=Q(record_type='revenue')),
            expenses=Sum('amount', filter=Q(record_type='expense')),
            orders=Count('order_reference', distinct=True, filter=Q(record_type='revenue'))
        )
        current_metrics['store'] = store
        current_metrics['profit'] = (current_metrics['revenue'] or 0) - (current_metrics['expenses'] or 0)
        current_metrics['avg_order_value'] = (
            current_metrics['revenue'] / current_metrics['orders']
            if current_metrics['orders'] and current_metrics['revenue'] else 0
        )

        return {
            'current_store': current_metrics,
            'competitors': sorted(store_metrics, key=lambda x: x['revenue'] or 0, reverse=True)
        }