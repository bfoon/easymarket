from django.db.models import Sum, Q
from django.db.models.functions import Coalesce
from .models import FinancialRecord
from decimal import Decimal


def format_currency(amount):
    """Format amount as currency"""
    if amount is None:
        return "$0.00"
    return f"${amount:,.2f}"


def calculate_commission(amount, rate):
    """Calculate commission amount"""
    return amount * (rate / 100)


def get_financial_summary_for_period(store, start_date, end_date):
    """Get financial summary for a specific period"""
    return FinancialRecord.objects.filter(
        store=store,
        transaction_date__range=[start_date, end_date]
    ).aggregate(
        revenue=Coalesce(Sum('amount', filter=Q(record_type='revenue')), Decimal('0')),
        expenses=Coalesce(Sum('amount', filter=Q(record_type='expense')), Decimal('0')),
        refunds=Coalesce(Sum('amount', filter=Q(record_type='refund')), Decimal('0')),
        commissions=Coalesce(Sum('amount', filter=Q(record_type='commission')), Decimal('0')),
        return_costs=Coalesce(Sum('amount', filter=Q(record_type='return_cost')), Decimal('0')),
        shipping_costs=Coalesce(Sum('amount', filter=Q(record_type='shipping_cost')), Decimal('0')),
    )


def export_financial_data_csv(store, start_date, end_date):
    """Export financial data to CSV format"""
    import csv
    from io import StringIO

    output = StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow([
        'Date', 'Type', 'Category', 'Amount', 'Description', 'Reference'
    ])

    # Write data
    records = FinancialRecord.objects.filter(
        store=store,
        transaction_date__range=[start_date, end_date]
    ).order_by('-transaction_date')

    for record in records:
        writer.writerow([
            record.transaction_date,
            record.get_record_type_display(),
            record.get_category_display(),
            record.amount,
            record.description,
            record.reference_number,
        ])

    return output.getvalue()