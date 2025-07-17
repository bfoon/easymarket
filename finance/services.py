from django.db.models import Sum, Q, Count, Avg, F, Case, When, Value, FloatField, DurationField
from django.utils import timezone
from datetime import timedelta, date
from .models import FinancialRecord, StoreFinancialSummary, LogisticsIntegration
from stores.models import Store
from decimal import Decimal


class FinancialService:
    """Service class for financial operations"""

    @staticmethod
    def calculate_store_profit(store, start_date=None, end_date=None):
        """Calculate profit for a store in a given period"""
        if not start_date:
            start_date = timezone.now().replace(day=1).date()
        if not end_date:
            end_date = timezone.now().date()

        records = FinancialRecord.objects.filter(
            store=store,
            transaction_date__range=[start_date, end_date]
        )

        summary = records.aggregate(
            revenue=Sum('amount', filter=Q(record_type='revenue')) or 0,
            expenses=Sum('amount', filter=Q(record_type='expense')) or 0,
            refunds=Sum('amount', filter=Q(record_type='refund')) or 0,
            commissions=Sum('amount', filter=Q(record_type='commission')) or 0,
            return_costs=Sum('amount', filter=Q(record_type='return_cost')) or 0,
            shipping_costs=Sum('amount', filter=Q(record_type='shipping_cost')) or 0,
        )

        gross_profit = (summary['revenue'] or 0) - (summary['expenses'] or 0)
        net_profit = gross_profit - (summary['refunds'] or 0) - (summary['return_costs'] or 0)

        return {
            'gross_profit': gross_profit,
            'net_profit': net_profit,
            'profit_margin': (net_profit / summary['revenue'] * 100) if summary['revenue'] else 0,
            'total_revenue': summary['revenue'] or 0,
            'total_expenses': summary['expenses'] or 0,
            'total_refunds': summary['refunds'] or 0,
            'total_commissions': summary['commissions'] or 0,
            'return_costs': summary['return_costs'] or 0,
            'shipping_costs': summary['shipping_costs'] or 0,
        }

    @staticmethod
    def get_order_metrics(store, start_date=None, end_date=None):
        """Get order metrics for a store"""
        if not start_date:
            start_date = timezone.now().replace(day=1).date()
        if not end_date:
            end_date = timezone.now().date()

        try:
            from orders.models import Order

            # Get orders for this store
            store_orders = Order.objects.filter(
                items__product__store=store,
                created_at__date__range=[start_date, end_date]
            ).distinct()

            metrics = {
                'total_orders': store_orders.count(),
                'pending_orders': store_orders.filter(status='pending').count(),
                'processing_orders': store_orders.filter(status='processing').count(),
                'shipped_orders': store_orders.filter(status='shipped').count(),
                'delivered_orders': store_orders.filter(status='delivered').count(),
                'cancelled_orders': store_orders.filter(status='cancelled').count(),
                'average_order_value': store_orders.aggregate(
                    avg=Avg('items__price_at_time')
                )['avg'] or 0,
            }

            return metrics
        except ImportError:
            return {
                'total_orders': 0,
                'pending_orders': 0,
                'processing_orders': 0,
                'shipped_orders': 0,
                'delivered_orders': 0,
                'cancelled_orders': 0,
                'average_order_value': 0,
            }

    @staticmethod
    def get_return_metrics(store, start_date=None, end_date=None):
        """Get return metrics for a store"""
        if not start_date:
            start_date = timezone.now().replace(day=1).date()
        if not end_date:
            end_date = timezone.now().date()

        try:
            from orders.models import Return

            # Get returns for this store
            store_returns = Return.objects.filter(
                items__product__store=store,
                created_at__date__range=[start_date, end_date]
            ).distinct()

            metrics = {
                'total_returns': store_returns.count(),
                'pending_returns': store_returns.filter(status='pending').count(),
                'approved_returns': store_returns.filter(status='approved').count(),
                'completed_returns': store_returns.filter(status='completed').count(),
                'rejected_returns': store_returns.filter(status='rejected').count(),
                'total_refund_amount': store_returns.filter(status='completed').aggregate(
                    total=Sum('refund_amount')
                )['total'] or 0,
                'return_reasons': store_returns.values('reason').annotate(
                    count=Count('id')
                ).order_by('-count'),
            }

            return metrics
        except ImportError:
            return {
                'total_returns': 0,
                'pending_returns': 0,
                'approved_returns': 0,
                'completed_returns': 0,
                'rejected_returns': 0,
                'total_refund_amount': 0,
                'return_reasons': [],
            }

    @staticmethod
    def get_logistics_metrics(store, start_date=None, end_date=None):
        """Get logistics metrics for a store"""
        if not start_date:
            start_date = timezone.now().replace(day=1).date()
        if not end_date:
            end_date = timezone.now().date()

        try:
            from logistics.models import Shipment

            # Get shipments for this store's orders
            store_shipments = Shipment.objects.filter(
                order__items__product__store=store,
                created_at__date__range=[start_date, end_date]
            ).distinct()

            metrics = {
                'total_shipments': store_shipments.count(),
                'pending_shipments': store_shipments.filter(status='pending').count(),
                'in_transit_shipments': store_shipments.filter(status='in_transit').count(),
                'shipped_shipments': store_shipments.filter(status='shipped').count(),
                'average_weight': store_shipments.aggregate(
                    avg=Avg('weight_kg')
                )['avg'] or 0,
                'total_shipping_cost': store_shipments.aggregate(
                    total=Sum('order__shipping_cost')
                )['total'] or 0,
                'average_delivery_time': 0,
            }

            # Calculate average delivery time
            completed_shipments = store_shipments.filter(
                status='shipped',
                order__delivered_date__isnull=False,
                order__shipped_date__isnull=False
            )

            if completed_shipments.exists():
                delivery_times = []
                for shipment in completed_shipments:
                    if shipment.order.delivered_date and shipment.order.shipped_date:
                        delivery_time = (shipment.order.delivered_date.date() - shipment.order.shipped_date.date()).days
                        delivery_times.append(delivery_time)

                metrics['average_delivery_time'] = sum(delivery_times) / len(delivery_times) if delivery_times else 0

            return metrics
        except ImportError:
            return {
                'total_shipments': 0,
                'pending_shipments': 0,
                'in_transit_shipments': 0,
                'shipped_shipments': 0,
                'average_weight': 0,
                'total_shipping_cost': 0,
                'average_delivery_time': 0,
            }

    @staticmethod
    def get_payment_method_breakdown(store, start_date=None, end_date=None):
        """Get payment method breakdown for a store"""
        if not start_date:
            start_date = timezone.now().replace(day=1).date()
        if not end_date:
            end_date = timezone.now().date()

        try:
            from payments.models import Payment

            # Get payments for this store's orders
            payments = Payment.objects.filter(
                order__items__product__store=store,
                status='completed',
                payment_date__date__range=[start_date, end_date]
            ).distinct()

            method_breakdown = payments.values('method').annotate(
                count=Count('id'),
                total_amount=Sum('amount')
            ).order_by('-total_amount')

            return method_breakdown
        except ImportError:
            return []

    @staticmethod
    def get_financial_health_score(store):
        """Calculate a financial health score for a store (0-100)"""
        # Get last 30 days data
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=30)

        try:
            profit_data = FinancialService.calculate_store_profit(store, start_date, end_date)
            order_metrics = FinancialService.get_order_metrics(store, start_date, end_date)
            return_metrics = FinancialService.get_return_metrics(store, start_date, end_date)
            logistics_data = LogisticsIntegration.objects.filter(store=store).first()

            score = 0

            # Profit margin (30 points)
            if profit_data['profit_margin'] > 20:
                score += 30
            elif profit_data['profit_margin'] > 10:
                score += 20
            elif profit_data['profit_margin'] > 0:
                score += 10

            # Revenue consistency (20 points)
            if profit_data['total_revenue'] > 0:
                score += 20

            # Order completion rate (20 points)
            if order_metrics['total_orders'] > 0:
                completion_rate = (order_metrics['delivered_orders'] / order_metrics['total_orders']) * 100
                if completion_rate >= 90:
                    score += 20
                elif completion_rate >= 75:
                    score += 15
                elif completion_rate >= 50:
                    score += 10

            # Low return rate (15 points)
            if order_metrics['total_orders'] > 0:
                return_rate = (return_metrics['total_returns'] / order_metrics['total_orders']) * 100
                if return_rate < 5:
                    score += 15
                elif return_rate < 10:
                    score += 10
                elif return_rate < 15:
                    score += 5

            # Customer satisfaction (15 points)
            avg_rating = store.get_average_rating()
            if avg_rating >= 4.5:
                score += 15
            elif avg_rating >= 4.0:
                score += 10
            elif avg_rating >= 3.5:
                score += 5

            return min(score, 100)
        except Exception:
            # Return default score if calculation fails
            return 75

    @staticmethod
    def get_comprehensive_dashboard_data(store, days=30):
        """Get comprehensive dashboard data for a store"""
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=days)

        return {
            'financial_summary': FinancialService.calculate_store_profit(store, start_date, end_date),
            'order_metrics': FinancialService.get_order_metrics(store, start_date, end_date),
            'return_metrics': FinancialService.get_return_metrics(store, start_date, end_date),
            'logistics_metrics': FinancialService.get_logistics_metrics(store, start_date, end_date),
            'payment_methods': FinancialService.get_payment_method_breakdown(store, start_date, end_date),
            'health_score': FinancialService.get_financial_health_score(store),
            'period': {
                'start_date': start_date,
                'end_date': end_date,
                'days': days
            }
        }

    @staticmethod
    def generate_monthly_summary(store, year=None, month=None):
        """Generate monthly financial summary for a store"""
        if not year:
            year = timezone.now().year
        if not month:
            month = timezone.now().month

        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)

        profit_data = FinancialService.calculate_store_profit(store, start_date, end_date)
        order_metrics = FinancialService.get_order_metrics(store, start_date, end_date)
        return_metrics = FinancialService.get_return_metrics(store, start_date, end_date)
        payment_methods = FinancialService.get_payment_method_breakdown(store, start_date, end_date)

        # Create or update summary
        summary, created = StoreFinancialSummary.objects.update_or_create(
            store=store,
            period_start=start_date,
            period_end=end_date,
            defaults={
                'total_revenue': profit_data['total_revenue'],
                'total_expenses': profit_data['total_expenses'],
                'total_refunds': profit_data['total_refunds'],
                'commission_expenses': profit_data['total_commissions'],
                'return_costs': profit_data['return_costs'],
                'shipping_expenses': profit_data['shipping_costs'],
                'gross_profit': profit_data['gross_profit'],
                'net_profit': profit_data['net_profit'],
                'profit_margin_percentage': profit_data['profit_margin'],
                'total_returns_processed': return_metrics['total_returns'],
            }
        )

        return {
            'summary': summary,
            'order_metrics': order_metrics,
            'return_metrics': return_metrics,
            'payment_methods': payment_methods,
        }

    @staticmethod
    def get_top_performing_stores(limit=10, period_days=30):
        """Get top performing stores by profit"""
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=period_days)

        store_profits = []
        for store in Store.objects.filter(status='active'):
            profit_data = FinancialService.calculate_store_profit(store, start_date, end_date)
            order_metrics = FinancialService.get_order_metrics(store, start_date, end_date)

            store_profits.append({
                'store': store,
                'net_profit': profit_data['net_profit'],
                'revenue': profit_data['total_revenue'],
                'profit_margin': profit_data['profit_margin'],
                'total_orders': order_metrics['total_orders'],
                'delivered_orders': order_metrics['delivered_orders'],
            })

        return sorted(store_profits, key=lambda x: x['net_profit'], reverse=True)[:limit]