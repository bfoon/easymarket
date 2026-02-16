# finance/services.py
# ALTERNATIVE VERSION: Queries OrderItem directly to avoid related name conflicts

from django.db.models import Sum, Count, Avg, Q, F, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from .models import FinancialRecord, StoreFinancialSummary, LogisticsIntegration
from orders.models import Order, Return
from payments.models import Payment
from logistics.models import Shipment

# Import OrderItem model
try:
    from orders.models import OrderItem
except ImportError:
    # Try alternative names
    try:
        from marketplace.models import OrderItem
    except ImportError:
        OrderItem = None


class FinancialService:
    """Service class for financial operations"""

    @staticmethod
    def get_comprehensive_dashboard_data(store, period_days=30):
        """Get comprehensive financial dashboard data for a store"""
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=period_days)

        # Financial Summary
        financial_records = FinancialRecord.objects.filter(
            store=store,
            transaction_date__range=[start_date, end_date]
        )

        financial_summary = financial_records.aggregate(
            total_revenue=Coalesce(Sum('amount', filter=Q(record_type='revenue')), Decimal('0')),
            total_expenses=Coalesce(Sum('amount', filter=Q(record_type='expense')), Decimal('0')),
            total_refunds=Coalesce(Sum('amount', filter=Q(record_type='refund')), Decimal('0')),
            total_commissions=Coalesce(Sum('amount', filter=Q(record_type='commission')), Decimal('0')),
            return_costs=Coalesce(Sum('amount', filter=Q(record_type='return_cost')), Decimal('0')),
            shipping_costs=Coalesce(Sum('amount', filter=Q(record_type='shipping_cost')), Decimal('0')),
            marketing_costs=Coalesce(Sum('amount', filter=Q(record_type='marketing')), Decimal('0')),
            operational_costs=Coalesce(Sum('amount', filter=Q(record_type='operational')), Decimal('0')),
        )

        # Calculate profits
        gross_profit = financial_summary['total_revenue'] - financial_summary['total_expenses']
        net_profit = gross_profit - financial_summary['total_refunds']

        financial_summary['gross_profit'] = gross_profit
        financial_summary['net_profit'] = net_profit
        financial_summary['profit_margin'] = (
            (net_profit / financial_summary['total_revenue'] * 100)
            if financial_summary['total_revenue'] > 0 else Decimal('0')
        )

        # Order Metrics - DIRECT QUERY METHOD (avoids related name issues)
        if OrderItem:
            # Get OrderItems for this store
            order_items = OrderItem.objects.filter(
                product__store=store,
                order__created_at__date__range=[start_date, end_date]
            )

            # Get unique orders
            order_ids = order_items.values_list('order_id', flat=True).distinct()
            orders = Order.objects.filter(id__in=order_ids)

            # Calculate order value directly from OrderItems
            # Try different field name combinations
            try:
                # Try price/quantity
                order_value_data = order_items.values('order_id').annotate(
                    order_total=Sum(F('price') * F('quantity'))
                ).aggregate(
                    avg_value=Avg('order_total'),
                    total_value=Sum('order_total')
                )
            except:
                try:
                    # Try unit_price/quantity
                    order_value_data = order_items.values('order_id').annotate(
                        order_total=Sum(F('unit_price') * F('quantity'))
                    ).aggregate(
                        avg_value=Avg('order_total'),
                        total_value=Sum('order_total')
                    )
                except:
                    # Fallback: no value calculation
                    order_value_data = {'avg_value': Decimal('0'), 'total_value': Decimal('0')}
        else:
            # Fallback if OrderItem model not found
            orders = Order.objects.none()
            order_value_data = {'avg_value': Decimal('0'), 'total_value': Decimal('0')}

        order_metrics = {
            'total_orders': orders.count(),
            'completed_orders': orders.filter(status='delivered').count(),
            'pending_orders': orders.filter(status__in=['pending', 'processing']).count(),
            'cancelled_orders': orders.filter(status='cancelled').count(),
            'average_order_value': order_value_data['avg_value'] or Decimal('0'),
            'total_order_value': order_value_data['total_value'] or Decimal('0'),
        }

        # Return Metrics
        returns = Return.objects.filter(
            items__product__store=store,
            created_at__date__range=[start_date, end_date]
        )

        return_metrics = {
            'total_returns': returns.count(),
            'return_rate': (
                (returns.count() / order_metrics['total_orders'] * 100)
                if order_metrics['total_orders'] > 0 else 0
            ),
            'total_refund_amount': returns.aggregate(
                total=Coalesce(Sum('refund_amount'), Decimal('0'))
            )['total'],
            'pending_returns': returns.filter(status='pending').count(),
            'approved_returns': returns.filter(status='approved').count(),
        }

        # Logistics Metrics
        logistics, _ = LogisticsIntegration.objects.get_or_create(store=store)

        # Query shipments via OrderItem to avoid related name issues
        if OrderItem:
            shipment_order_ids = OrderItem.objects.filter(
                product__store=store
            ).values_list('order_id', flat=True).distinct()

            shipments = Shipment.objects.filter(
                order_id__in=shipment_order_ids,
                created_at__date__range=[start_date, end_date]
            )
        else:
            shipments = Shipment.objects.none()

        logistics_metrics = {
            'total_shipments': shipments.count(),
            'pending_shipments': shipments.filter(status__in=['pending', 'in_transit']).count(),
            'delivered_shipments': shipments.filter(status='delivered').count(),
            'failed_shipments': shipments.filter(status='failed').count(),
            'average_delivery_time': logistics.average_delivery_time,
            'on_time_delivery_rate': logistics.on_time_delivery_rate,
        }

        # Payment Method Analysis
        if OrderItem:
            payment_order_ids = OrderItem.objects.filter(
                product__store=store
            ).values_list('order_id', flat=True).distinct()

            payments = Payment.objects.filter(
                order_id__in=payment_order_ids,
                payment_date__date__range=[start_date, end_date]
            ).values('method').annotate(
                count=Count('id'),
                total_amount=Sum('amount')
            ).order_by('-total_amount')
        else:
            payments = Payment.objects.none()

        payment_methods = list(payments)

        # Health Score Calculation
        health_score = FinancialService._calculate_health_score(
            financial_summary,
            order_metrics,
            return_metrics,
            logistics_metrics
        )

        return {
            'financial_summary': financial_summary,
            'order_metrics': order_metrics,
            'return_metrics': return_metrics,
            'logistics_metrics': logistics_metrics,
            'payment_methods': payment_methods,
            'health_score': health_score,
        }

    @staticmethod
    def _calculate_health_score(financial, orders, returns, logistics):
        """Calculate overall store health score (0-100)"""
        score = 100

        # Deduct for low profit margin
        profit_margin = financial.get('profit_margin', 0)
        if profit_margin < 10:
            score -= 20
        elif profit_margin < 20:
            score -= 10

        # Deduct for high return rate
        return_rate = returns.get('return_rate', 0)
        if return_rate > 15:
            score -= 15
        elif return_rate > 10:
            score -= 10

        # Deduct for failed shipments
        total_shipments = logistics.get('total_shipments', 0)
        failed_shipments = logistics.get('failed_shipments', 0)
        if total_shipments > 0:
            failure_rate = (failed_shipments / total_shipments) * 100
            if failure_rate > 5:
                score -= 15
            elif failure_rate > 2:
                score -= 10

        # Deduct for low on-time delivery
        on_time_rate = logistics.get('on_time_delivery_rate', 100)
        if on_time_rate < 80:
            score -= 10
        elif on_time_rate < 90:
            score -= 5

        # Deduct for cancelled orders
        total_orders = orders.get('total_orders', 0)
        cancelled = orders.get('cancelled_orders', 0)
        if total_orders > 0:
            cancel_rate = (cancelled / total_orders) * 100
            if cancel_rate > 10:
                score -= 10
            elif cancel_rate > 5:
                score -= 5

        return max(0, min(100, score))

    @staticmethod
    def generate_monthly_summary(store, year=None, month=None):
        """Generate monthly financial summary for a store"""
        if year is None:
            year = timezone.now().year
        if month is None:
            month = timezone.now().month

        # Calculate period dates
        period_start = timezone.datetime(year, month, 1).date()
        if month == 12:
            period_end = timezone.datetime(year + 1, 1, 1).date() - timedelta(days=1)
        else:
            period_end = timezone.datetime(year, month + 1, 1).date() - timedelta(days=1)

        # Get or create summary
        summary, created = StoreFinancialSummary.objects.get_or_create(
            store=store,
            period_start=period_start,
            period_end=period_end
        )

        # Calculate metrics using FinancialRecord
        records = FinancialRecord.objects.filter(
            store=store,
            transaction_date__range=[period_start, period_end]
        )

        # Revenue breakdown
        summary.total_revenue = records.filter(
            record_type='revenue'
        ).aggregate(total=Coalesce(Sum('amount'), Decimal('0')))['total']

        summary.commission_revenue = records.filter(
            record_type='revenue',
            category='commission'
        ).aggregate(total=Coalesce(Sum('amount'), Decimal('0')))['total']

        summary.shipping_revenue = records.filter(
            record_type='revenue',
            category='shipping'
        ).aggregate(total=Coalesce(Sum('amount'), Decimal('0')))['total']

        # Expense breakdown
        summary.total_expenses = records.filter(
            record_type='expense'
        ).aggregate(total=Coalesce(Sum('amount'), Decimal('0')))['total']

        summary.commission_expenses = records.filter(
            record_type='commission'
        ).aggregate(total=Coalesce(Sum('amount'), Decimal('0')))['total']

        summary.shipping_expenses = records.filter(
            record_type='shipping_cost'
        ).aggregate(total=Coalesce(Sum('amount'), Decimal('0')))['total']

        summary.return_costs = records.filter(
            record_type='return_cost'
        ).aggregate(total=Coalesce(Sum('amount'), Decimal('0')))['total']

        summary.marketing_expenses = records.filter(
            record_type='marketing'
        ).aggregate(total=Coalesce(Sum('amount'), Decimal('0')))['total']

        summary.operational_expenses = records.filter(
            record_type='operational'
        ).aggregate(total=Coalesce(Sum('amount'), Decimal('0')))['total']

        # Refunds
        summary.total_refunds = records.filter(
            record_type='refund'
        ).aggregate(total=Coalesce(Sum('amount'), Decimal('0')))['total']

        summary.total_returns_processed = Return.objects.filter(
            items__product__store=store,
            created_at__date__range=[period_start, period_end]
        ).count()

        summary.save()
        return summary

    @staticmethod
    def generate_weekly_summary(store):
        """Generate weekly financial summary"""
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=7)

        return FinancialService.get_comprehensive_dashboard_data(store, period_days=7)