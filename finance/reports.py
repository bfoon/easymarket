# finance/reports.py

from django.db.models import Sum, Count, Avg, Q
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from .models import FinancialRecord, StoreFinancialSummary
from orders.models import Order, Return
from logistics.models import Shipment


class FinancialReportGenerator:
    """Generate financial reports in various formats"""

    @staticmethod
    def generate_monthly_report(store, year, month):
        """Generate comprehensive monthly financial report"""

        # Calculate period
        period_start = datetime(year, month, 1).date()
        if month == 12:
            period_end = datetime(year + 1, 1, 1).date() - timedelta(days=1)
        else:
            period_end = datetime(year, month + 1, 1).date() - timedelta(days=1)

        # Get all financial records for the period
        records = FinancialRecord.objects.filter(
            store=store,
            transaction_date__range=[period_start, period_end]
        )

        # Revenue Summary
        revenue_summary = records.filter(
            record_type='revenue'
        ).values('category').annotate(
            total=Sum('amount'),
            count=Count('id')
        ).order_by('-total')

        # Expense Summary
        expense_summary = records.filter(
            record_type='expense'
        ).values('category').annotate(
            total=Sum('amount'),
            count=Count('id')
        ).order_by('-total')

        # Daily breakdown
        daily_breakdown = records.annotate(
            date=TruncDate('transaction_date')
        ).values('date').annotate(
            revenue=Coalesce(Sum('amount', filter=Q(record_type='revenue')), Decimal('0')),
            expenses=Coalesce(Sum('amount', filter=Q(record_type='expense')), Decimal('0')),
            refunds=Coalesce(Sum('amount', filter=Q(record_type='refund')), Decimal('0'))
        ).order_by('date')

        # Order metrics
        orders = Order.objects.filter(
            items__product__store=store,
            created_at__date__range=[period_start, period_end]
        ).distinct()

        # Calculate order totals from items (Order model doesn't have total_amount field)
        order_totals = orders.annotate(
            order_total=Sum(F('items__price') * F('items__quantity'))
        ).aggregate(
            total_value=Coalesce(Sum('order_total'), Decimal('0')),
            avg_value=Avg('order_total')
        )

        order_summary = {
            'total_orders': orders.count(),
            'completed_orders': orders.filter(status='delivered').count(),
            'cancelled_orders': orders.filter(status='cancelled').count(),
            'total_order_value': order_totals['total_value'],
            'average_order_value': order_totals['avg_value'] or Decimal('0'),
        }

        # Return metrics
        returns = Return.objects.filter(
            items__product__store=store,
            created_at__date__range=[period_start, period_end]
        )

        return_summary = {
            'total_returns': returns.count(),
            'return_rate': (
                (returns.count() / order_summary['total_orders'] * 100)
                if order_summary['total_orders'] > 0 else 0
            ),
            'total_refund_amount': returns.aggregate(
                total=Coalesce(Sum('refund_amount'), Decimal('0'))
            )['total'],
            'return_reasons': returns.values('reason').annotate(
                count=Count('id')
            ).order_by('-count'),
        }

        # Logistics metrics
        shipments = Shipment.objects.filter(
            order__items__product__store=store,
            created_at__date__range=[period_start, period_end]
        )

        logistics_summary = {
            'total_shipments': shipments.count(),
            'delivered_shipments': shipments.filter(status='delivered').count(),
            'failed_shipments': shipments.filter(status='failed').count(),
        }

        # Overall totals
        totals = records.aggregate(
            total_revenue=Coalesce(Sum('amount', filter=Q(record_type='revenue')), Decimal('0')),
            total_expenses=Coalesce(Sum('amount', filter=Q(record_type='expense')), Decimal('0')),
            total_refunds=Coalesce(Sum('amount', filter=Q(record_type='refund')), Decimal('0')),
            total_commissions=Coalesce(Sum('amount', filter=Q(record_type='commission')), Decimal('0')),
        )

        gross_profit = totals['total_revenue'] - totals['total_expenses']
        net_profit = gross_profit - totals['total_refunds']

        return {
            'store': store,
            'period_start': period_start,
            'period_end': period_end,
            'revenue_summary': revenue_summary,
            'expense_summary': expense_summary,
            'daily_breakdown': daily_breakdown,
            'order_summary': order_summary,
            'return_summary': return_summary,
            'logistics_summary': logistics_summary,
            'totals': totals,
            'gross_profit': gross_profit,
            'net_profit': net_profit,
            'profit_margin': (
                (net_profit / totals['total_revenue'] * 100)
                if totals['total_revenue'] > 0 else Decimal('0')
            ),
        }

    @staticmethod
    def export_to_excel(report_data, filename):
        """Export report to Excel file"""
        from django.conf import settings
        import os

        # Create workbook
        wb = openpyxl.Workbook()

        # Summary Sheet
        ws_summary = wb.active
        ws_summary.title = "Summary"

        # Header styling
        header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True)
        border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )

        # Title
        ws_summary['A1'] = f"Financial Report - {report_data['store'].name}"
        ws_summary['A1'].font = Font(size=16, bold=True)
        ws_summary['A2'] = f"Period: {report_data['period_start']} to {report_data['period_end']}"

        # Summary metrics
        row = 4
        ws_summary[f'A{row}'] = "Metric"
        ws_summary[f'B{row}'] = "Amount"
        ws_summary[f'A{row}'].fill = header_fill
        ws_summary[f'B{row}'].fill = header_fill
        ws_summary[f'A{row}'].font = header_font
        ws_summary[f'B{row}'].font = header_font

        metrics = [
            ("Total Revenue", report_data['totals']['total_revenue']),
            ("Total Expenses", report_data['totals']['total_expenses']),
            ("Gross Profit", report_data['gross_profit']),
            ("Total Refunds", report_data['totals']['total_refunds']),
            ("Net Profit", report_data['net_profit']),
            ("Profit Margin %", f"{report_data['profit_margin']:.2f}%"),
            ("", ""),
            ("Total Orders", report_data['order_summary']['total_orders']),
            ("Completed Orders", report_data['order_summary']['completed_orders']),
            ("Cancelled Orders", report_data['order_summary']['cancelled_orders']),
            ("Average Order Value", report_data['order_summary']['average_order_value']),
            ("", ""),
            ("Total Returns", report_data['return_summary']['total_returns']),
            ("Return Rate %", f"{report_data['return_summary']['return_rate']:.2f}%"),
            ("Total Refund Amount", report_data['return_summary']['total_refund_amount']),
        ]

        row += 1
        for metric, value in metrics:
            ws_summary[f'A{row}'] = metric
            ws_summary[f'B{row}'] = value
            ws_summary[f'A{row}'].border = border
            ws_summary[f'B{row}'].border = border
            row += 1

        # Auto-size columns
        ws_summary.column_dimensions['A'].width = 30
        ws_summary.column_dimensions['B'].width = 20

        # Daily Breakdown Sheet
        ws_daily = wb.create_sheet("Daily Breakdown")
        ws_daily['A1'] = "Date"
        ws_daily['B1'] = "Revenue"
        ws_daily['C1'] = "Expenses"
        ws_daily['D1'] = "Refunds"
        ws_daily['E1'] = "Net Profit"

        for col in ['A', 'B', 'C', 'D', 'E']:
            ws_daily[f'{col}1'].fill = header_fill
            ws_daily[f'{col}1'].font = header_font

        row = 2
        for day in report_data['daily_breakdown']:
            ws_daily[f'A{row}'] = day['date']
            ws_daily[f'B{row}'] = float(day['revenue'])
            ws_daily[f'C{row}'] = float(day['expenses'])
            ws_daily[f'D{row}'] = float(day['refunds'])
            ws_daily[f'E{row}'] = float(day['revenue'] - day['expenses'] - day['refunds'])
            row += 1

        # Auto-size columns
        for col in ['A', 'B', 'C', 'D', 'E']:
            ws_daily.column_dimensions[col].width = 15

        # Save file
        reports_dir = os.path.join(settings.MEDIA_ROOT, 'reports')
        os.makedirs(reports_dir, exist_ok=True)
        filepath = os.path.join(reports_dir, filename)
        wb.save(filepath)

        return filepath

    @staticmethod
    def generate_csv_export(store, start_date, end_date):
        """Generate CSV export of financial records"""
        import csv
        from io import StringIO

        output = StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow([
            'Date', 'Type', 'Category', 'Amount', 'Description',
            'Reference', 'Order Reference', 'Confirmed'
        ])

        # Records
        records = FinancialRecord.objects.filter(
            store=store,
            transaction_date__range=[start_date, end_date]
        ).order_by('-transaction_date')

        for record in records:
            writer.writerow([
                record.transaction_date,
                record.get_record_type_display(),
                record.get_category_display(),
                float(record.amount),
                record.description,
                record.reference_number,
                record.order_reference or '',
                'Yes' if record.is_confirmed else 'No',
            ])

        return output.getvalue()

    @staticmethod
    def generate_pdf_report(report_data):
        """Generate PDF report (requires reportlab)"""
        # This would require reportlab to be installed
        # Placeholder for future implementation
        raise NotImplementedError("PDF report generation coming soon")