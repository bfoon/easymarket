class FinancialDashboard:
    """Create dashboard widgets and data"""

    @staticmethod
    def get_kpi_widgets(store, period_days=30):
        """Get KPI widgets for dashboard"""
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=period_days)

        # Current period metrics
        current_metrics = FinancialRecord.objects.filter(
            store=store,
            transaction_date__range=[start_date, end_date]
        ).aggregate(
            revenue=Sum('amount', filter=Q(record_type='revenue')),
            expenses=Sum('amount', filter=Q(record_type='expense')),
            profit=Sum('amount', filter=Q(record_type='revenue')) - Sum('amount', filter=Q(record_type='expense'))
        )

        # Previous period for comparison
        prev_start = start_date - timedelta(days=period_days)
        prev_end = start_date

        previous_metrics = FinancialRecord.objects.filter(
            store=store,
            transaction_date__range=[prev_start, prev_end]
        ).aggregate(
            revenue=Sum('amount', filter=Q(record_type='revenue')),
            expenses=Sum('amount', filter=Q(record_type='expense')),
            profit=Sum('amount', filter=Q(record_type='revenue')) - Sum('amount', filter=Q(record_type='expense'))
        )

        # Calculate percentage changes
        widgets = []
        for metric in ['revenue', 'expenses', 'profit']:
            current = current_metrics[metric] or 0
            previous = previous_metrics[metric] or 0

            change = ((current - previous) / previous * 100) if previous else 0

            widgets.append({
                'title': metric.title(),
                'value': current,
                'change': change,
                'trend': 'up' if change > 0 else 'down' if change < 0 else 'stable',
                'icon': {
                    'revenue': 'fas fa-dollar-sign',
                    'expenses': 'fas fa-credit-card',
                    'profit': 'fas fa-chart-line'
                }[metric]
            })

        return widgets

    @staticmethod
    def get_alert_notifications(store):
        """Get alert notifications for the store"""
        alerts = []

        # Check for low profit margins
        recent_profit = FinancialRecord.objects.filter(
            store=store,
            transaction_date__gte=timezone.now().date() - timedelta(days=7)
        ).aggregate(
            revenue=Sum('amount', filter=Q(record_type='revenue')),
            expenses=Sum('amount', filter=Q(record_type='expense'))
        )

        if recent_profit['revenue'] and recent_profit['expenses']:
            margin = ((recent_profit['revenue'] - recent_profit['expenses']) / recent_profit['revenue']) * 100
            if margin < 10:
                alerts.append({
                    'type': 'warning',
                    'message': f'Profit margin is low: {margin:.1f}%',
                    'action': 'Review expenses and pricing'
                })

        # Check for high return rates
        recent_orders = Order.objects.filter(
            items__product__store=store,
            created_at__gte=timezone.now() - timedelta(days=30)
        ).distinct().count()

        recent_returns = Return.objects.filter(
            items__product__store=store,
            created_at__gte=timezone.now() - timedelta(days=30)
        ).count()

        if recent_orders > 0:
            return_rate = (recent_returns / recent_orders) * 100
            if return_rate > 15:
                alerts.append({
                    'type': 'danger',
                    'message': f'High return rate: {return_rate:.1f}%',
                    'action': 'Review product quality and descriptions'
                })

        # Check for failed shipments
        failed_shipments = Shipment.objects.filter(
            order__items__product__store=store,
            status='failed',
            created_at__gte=timezone.now() - timedelta(days=7)
        ).count()

        if failed_shipments > 0:
            alerts.append({
                'type': 'warning',
                'message': f'{failed_shipments} failed shipments this week',
                'action': 'Review logistics operations'
            })

        return alerts
