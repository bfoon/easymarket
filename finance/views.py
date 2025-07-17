from django.shortcuts import render, get_object_or_404
from django.db.models import Sum, Count, Avg, Q
from django.utils import timezone
from datetime import datetime, timedelta
from stores.models import Store  # Import from stores app
from .models import FinancialRecord, StoreFinancialSummary, LogisticsIntegration, FinancialMetricsIntegration
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from .analytics import AdvancedFinancialAnalytics
from .reports import FinancialReportGenerator

def store_dashboard(request):
    """Main dashboard showing all stores with financial and logistics data"""
    # Filter only active stores
    stores = Store.objects.filter(status='active')

    # Calculate financial summaries for each store
    store_data = []
    current_month = timezone.now().replace(day=1)

    for store in stores:
        # Get financial data for current month
        financial_summary = FinancialRecord.objects.filter(
            store=store,
            transaction_date__gte=current_month
        ).aggregate(
            total_revenue=Sum('amount', filter=Q(record_type='revenue')) or 0,
            total_expenses=Sum('amount', filter=Q(record_type='expense')) or 0,
            total_refunds=Sum('amount', filter=Q(record_type='refund')) or 0,
            total_commissions=Sum('amount', filter=Q(record_type='commission')) or 0,
            return_costs=Sum('amount', filter=Q(record_type='return_cost')) or 0,
        )

        # Calculate net profit
        net_profit = (
                (financial_summary['total_revenue'] or 0) -
                (financial_summary['total_expenses'] or 0) -
                (financial_summary['total_refunds'] or 0) -
                (financial_summary['total_commissions'] or 0) -
                (financial_summary['return_costs'] or 0)
        )

        # Get or create logistics data
        logistics_data, created = LogisticsIntegration.objects.get_or_create(
            store=store,
            defaults={
                'total_shipments': 0,
                'pending_shipments': 0,
                'completed_shipments': 0,
                'failed_shipments': 0,
            }
        )

        # Leverage existing Store model methods
        total_products = store.get_total_products()
        total_orders = store.get_total_orders()  # Use existing method
        total_sales = store.get_total_sales()  # Use existing method
        average_rating = store.get_average_rating()  # Use existing method

        store_data.append({
            'store': store,
            'financial_summary': financial_summary,
            'net_profit': net_profit,
            'logistics_data': logistics_data,
            'total_products': total_products,
            'total_orders': total_orders,
            'total_sales': total_sales,
            'average_rating': average_rating,
            'commission_rate': store.commission_rate,
            'processing_time': store.processing_time,
        })

    # Overall statistics
    total_stores = stores.count()
    active_stores = stores.filter(status='active').count()
    total_revenue_all = sum([data['financial_summary']['total_revenue'] or 0 for data in store_data])

    context = {
        'store_data': store_data,
        'current_month': current_month,
        'total_stores': total_stores,
        'active_stores': active_stores,
        'total_revenue_all': total_revenue_all,
    }

    return render(request, 'finance/store_dashboard.html', context)


def store_detail(request, store_id):
    """Detailed view for a specific store using UUID"""
    store = get_object_or_404(Store, id=store_id, status='active')

    # Get date range from request or default to current month
    date_from = request.GET.get('from', timezone.now().replace(day=1).date())
    date_to = request.GET.get('to', timezone.now().date())

    if isinstance(date_from, str):
        date_from = datetime.strptime(date_from, '%Y-%m-%d').date()
    if isinstance(date_to, str):
        date_to = datetime.strptime(date_to, '%Y-%m-%d').date()

    # Get comprehensive dashboard data using the enhanced service
    from .services import FinancialService
    days_diff = (date_to - date_from).days
    comprehensive_data = FinancialService.get_comprehensive_dashboard_data(store, days_diff)

    # Financial records for the period
    financial_records = FinancialRecord.objects.filter(
        store=store,
        transaction_date__range=[date_from, date_to]
    )

    # Enhanced financial summary with new categories
    financial_summary = comprehensive_data['financial_summary']

    # Calculate comprehensive profit
    gross_profit = financial_summary['gross_profit']
    net_profit = financial_summary['net_profit']

    # Category breakdown
    category_breakdown = financial_records.values('category', 'record_type').annotate(
        total=Sum('amount')
    ).order_by('category')

    # Get logistics data
    logistics_data, created = LogisticsIntegration.objects.get_or_create(store=store)

    # Recent transactions
    recent_transactions = financial_records.order_by('-transaction_date', '-created_at')[:20]

    # Store performance metrics using existing methods + enhanced data
    store_metrics = {
        'total_products': store.get_total_products(),
        'total_orders': store.get_total_orders(),
        'lifetime_sales': store.get_total_sales(),
        'average_rating': store.get_average_rating(),
        'commission_rate': store.commission_rate,
        'processing_time': store.processing_time,
        'return_policy_days': store.return_policy_days,
        'is_featured': store.is_featured,
        'store_type': store.get_store_type_display(),
        'status': store.get_status_display(),
        'health_score': comprehensive_data['health_score'],
    }

    # Get return settings if they exist
    return_settings = getattr(store, 'return_settings', None)

    # Enhanced metrics from comprehensive data
    order_metrics = comprehensive_data['order_metrics']
    return_metrics = comprehensive_data['return_metrics']
    logistics_metrics = comprehensive_data['logistics_metrics']
    payment_methods = comprehensive_data['payment_methods']

    context = {
        'store': store,
        'financial_summary': financial_summary,
        'gross_profit': gross_profit,
        'net_profit': net_profit,
        'category_breakdown': category_breakdown,
        'logistics_data': logistics_data,
        'recent_transactions': recent_transactions,
        'store_metrics': store_metrics,
        'return_settings': return_settings,
        'date_from': date_from,
        'date_to': date_to,
        # Enhanced data
        'order_metrics': order_metrics,
        'return_metrics': return_metrics,
        'logistics_metrics': logistics_metrics,
        'payment_methods': payment_methods,
        'comprehensive_data': comprehensive_data,
    }

    return render(request, 'finance/store_detail.html', context)


def financial_reports(request):
    """Generate comprehensive financial reports"""
    # Filter parameters
    store_category = request.GET.get('category')
    store_type = request.GET.get('type')
    status_filter = request.GET.get('status', 'active')

    # Base queryset
    stores_qs = Store.objects.filter(status=status_filter)

    if store_category:
        stores_qs = stores_qs.filter(category__slug=store_category)
    if store_type:
        stores_qs = stores_qs.filter(store_type=store_type)

    # Overall financial summary
    overall_summary = FinancialRecord.objects.filter(store__in=stores_qs).aggregate(
        total_revenue=Sum('amount', filter=Q(record_type='revenue')) or 0,
        total_expenses=Sum('amount', filter=Q(record_type='expense')) or 0,
        total_refunds=Sum('amount', filter=Q(record_type='refund')) or 0,
        total_commissions=Sum('amount', filter=Q(record_type='commission')) or 0,
        return_costs=Sum('amount', filter=Q(record_type='return_cost')) or 0,
        shipping_costs=Sum('amount', filter=Q(record_type='shipping_cost')) or 0,
    )

    # Store performance comparison with enhanced metrics
    store_performance = stores_qs.annotate(
        # Financial metrics from FinancialRecord
        total_revenue=Sum('financial_records__amount',
                          filter=Q(financial_records__record_type='revenue')),
        total_expenses=Sum('financial_records__amount',
                           filter=Q(financial_records__record_type='expense')),

        # Use existing Store model methods via related fields
        total_orders_count=Count('products__order_items__product__price', distinct=True),
        total_products_count=Count('products', filter=Q(products__is_active=True)),

    ).order_by('-total_revenue')

    # Commission analysis
    commission_analysis = stores_qs.aggregate(
        avg_commission_rate=Avg('commission_rate'),
        total_commission_paid=Sum('financial_records__amount',
                                  filter=Q(financial_records__record_type='commission')),
    )

    # Return analysis (leverage existing return system)
    return_analysis = {
        'stores_with_return_settings': stores_qs.filter(return_settings__isnull=False).count(),
        'avg_return_window': stores_qs.aggregate(
            avg=Avg('return_settings__return_window_days')
        )['avg'] or 0,
        'stores_auto_approve_returns': stores_qs.filter(
            return_settings__auto_approve_returns=True
        ).count(),
    }

    # Category performance
    from stores.models import StoreCategory
    category_performance = StoreCategory.objects.filter(
        store__in=stores_qs
    ).annotate(
        store_count=Count('store'),
        total_revenue=Sum('store__financial_records__amount',
                          filter=Q(store__financial_records__record_type='revenue')),
        avg_rating=Avg('store__reviews__rating', filter=Q(store__reviews__is_approved=True))
    ).order_by('-total_revenue')

    context = {
        'overall_summary': overall_summary,
        'store_performance': store_performance,
        'commission_analysis': commission_analysis,
        'return_analysis': return_analysis,
        'category_performance': category_performance,
        'store_categories': StoreCategory.objects.filter(is_active=True),
        'store_types': Store.STORE_TYPE_CHOICES,
        'filters': {
            'category': store_category,
            'type': store_type,
            'status': status_filter,
        }
    }

    return render(request, 'finance/financial_reports.html', context)


@require_http_methods(["GET"])
def advanced_analytics_api(request, store_id):
    """API endpoint for advanced analytics"""
    store = get_object_or_404(Store, id=store_id)

    analytics_type = request.GET.get('type', 'overview')

    if analytics_type == 'cohort':
        data = AdvancedFinancialAnalytics.get_cohort_analysis(store)
    elif analytics_type == 'seasonal':
        data = AdvancedFinancialAnalytics.get_seasonal_trends(store)
    elif analytics_type == 'margins':
        data = AdvancedFinancialAnalytics.get_profit_margin_analysis(store)
    elif analytics_type == 'payments':
        data = AdvancedFinancialAnalytics.get_payment_method_performance(store)
    elif analytics_type == 'returns':
        data = AdvancedFinancialAnalytics.get_return_analysis(store)
    elif analytics_type == 'logistics':
        data = AdvancedFinancialAnalytics.get_logistics_efficiency_metrics(store)
    elif analytics_type == 'competitive':
        data = AdvancedFinancialAnalytics.get_competitive_analysis(store)
    else:
        data = {'error': 'Invalid analytics type'}

    return JsonResponse(data, safe=False)


@require_http_methods(["POST"])
def generate_report_api(request, store_id):
    """API endpoint for report generation"""
    store = get_object_or_404(Store, id=store_id)

    report_type = request.POST.get('type', 'monthly')
    year = int(request.POST.get('year', timezone.now().year))
    month = int(request.POST.get('month', timezone.now().month))

    if report_type == 'monthly':
        report_data = FinancialReportGenerator.generate_monthly_report(store, year, month)

        # Generate filename
        filename = f"{store.name.replace(' ', '_')}_monthly_report_{year}_{month:02d}.xlsx"

        # Export to Excel
        FinancialReportGenerator.export_to_excel(report_data, filename)

        return JsonResponse({
            'status': 'success',
            'filename': filename,
            'download_url': f'/media/reports/{filename}'
        })

    return JsonResponse({'error': 'Invalid report type'})