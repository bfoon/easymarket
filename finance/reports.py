class FinancialReportGenerator:
    """Generate comprehensive financial reports"""

    @staticmethod
    def generate_monthly_report(store, year, month):
        """Generate comprehensive monthly report"""
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)

        # Financial summary
        financial_summary = FinancialRecord.objects.filter(
            store=store,
            transaction_date__range=[start_date, end_date]
        ).aggregate(
            total_revenue=Sum('amount', filter=Q(record_type='revenue')),
            total_expenses=Sum('amount', filter=Q(record_type='expense')),
            total_refunds=Sum('amount', filter=Q(record_type='refund')),
            total_commissions=Sum('amount', filter=Q(record_type='commission')),
            return_costs=Sum('amount', filter=Q(record_type='return_cost')),
            shipping_costs=Sum('amount', filter=Q(record_type='shipping_cost'))
        )

        # Order metrics
        order_metrics = Order.objects.filter(
            items__product__store=store,
            created_at__date__range=[start_date, end_date]
        ).distinct().aggregate(
            total_orders=Count('id'),
            delivered_orders=Count('id', filter=Q(status='delivered')),
            cancelled_orders=Count('id', filter=Q(status='cancelled')),
            avg_order_value=Avg('items__price_at_time')
        )

        # Payment method breakdown
        payment_breakdown = Payment.objects.filter(
            order__items__product__store=store,
            status='completed',
            payment_date__date__range=[start_date, end_date]
        ).values('method').annotate(
            count=Count('id'),
            amount=Sum('amount')
        )

        # Return analysis
        return_analysis = Return.objects.filter(
            items__product__store=store,
            created_at__date__range=[start_date, end_date]
        ).aggregate(
            total_returns=Count('id'),
            completed_returns=Count('id', filter=Q(status='completed')),
            total_refunded=Sum('refund_amount', filter=Q(status='completed'))
        )

        # Top products
        top_products = OrderItem.objects.filter(
            product__store=store,
            order__created_at__date__range=[start_date, end_date],
            order__status='delivered'
        ).values('product__name').annotate(
            quantity_sold=Sum('quantity'),
            revenue=Sum(F('quantity') * F('price_at_time'))
        ).order_by('-revenue')[:10]

        return {
            'period': {'start': start_date, 'end': end_date},
            'financial_summary': financial_summary,
            'order_metrics': order_metrics,
            'payment_breakdown': payment_breakdown,
            'return_analysis': return_analysis,
            'top_products': top_products,
        }

    @staticmethod
    def export_to_excel(report_data, filename):
        """Export report data to Excel"""
        with pd.ExcelWriter(filename, engine='xlsxwriter') as writer:
            # Financial summary
            financial_df = pd.DataFrame([report_data['financial_summary']])
            financial_df.to_excel(writer, sheet_name='Financial Summary', index=False)

            # Order metrics
            order_df = pd.DataFrame([report_data['order_metrics']])
            order_df.to_excel(writer, sheet_name='Order Metrics', index=False)

            # Payment breakdown
            if report_data['payment_breakdown']:
                payment_df = pd.DataFrame(report_data['payment_breakdown'])
                payment_df.to_excel(writer, sheet_name='Payment Methods', index=False)

            # Top products
            if report_data['top_products']:
                products_df = pd.DataFrame(report_data['top_products'])
                products_df.to_excel(writer, sheet_name='Top Products', index=False)