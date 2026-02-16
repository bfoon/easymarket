from django.shortcuts import render, get_object_or_404
from django.db.models import Sum, Count, Avg, Q
from django.utils import timezone
from decimal import Decimal
from datetime import datetime

from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from stores.models import Store, StoreCategory
from .models import FinancialRecord, LogisticsIntegration
from .analytics import AdvancedFinancialAnalytics
from .reports import FinancialReportGenerator
from .services import FinancialService


# -----------------------------
# Helpers
# -----------------------------

def staff_required(user):
    return user.is_staff or user.is_superuser


# =============================
# MAIN FINANCE DASHBOARD
# =============================

@login_required
@user_passes_test(staff_required)
def store_dashboard(request):
    stores = Store.objects.filter(status="active")

    current_month = timezone.now().replace(day=1).date()

    store_data = []

    total_revenue_all = Decimal("0.00")
    total_expenses_all = Decimal("0.00")
    total_shipments_all = 0

    for store in stores:
        agg = FinancialRecord.objects.filter(
            store=store,
            transaction_date__gte=current_month
        ).aggregate(
            total_revenue=Sum("amount", filter=Q(record_type="revenue")),
            total_expenses=Sum("amount", filter=Q(record_type="expense")),
            total_refunds=Sum("amount", filter=Q(record_type="refund")),
            total_commissions=Sum("amount", filter=Q(record_type="commission")),
            return_costs=Sum("amount", filter=Q(record_type="return_cost")),
            shipping_costs=Sum("amount", filter=Q(record_type="shipping_cost")),
        )

        total_revenue = agg["total_revenue"] or Decimal("0.00")
        total_expenses = agg["total_expenses"] or Decimal("0.00")
        total_refunds = agg["total_refunds"] or Decimal("0.00")
        total_commissions = agg["total_commissions"] or Decimal("0.00")
        return_costs = agg["return_costs"] or Decimal("0.00")
        shipping_costs = agg["shipping_costs"] or Decimal("0.00")

        # Net profit: revenue - all costs out
        net_profit = total_revenue - (
            total_expenses + total_refunds + total_commissions + return_costs + shipping_costs
        )

        logistics, _ = LogisticsIntegration.objects.get_or_create(store=store)

        total_revenue_all += total_revenue
        total_expenses_all += total_expenses
        total_shipments_all += int(logistics.total_shipments or 0)

        store_data.append({
            "store": store,
            "financial_summary": {
                "total_revenue": total_revenue,
                "total_expenses": total_expenses,
                "total_refunds": total_refunds,
                "total_commissions": total_commissions,
                "return_costs": return_costs,
                "shipping_costs": shipping_costs,
            },
            "net_profit": net_profit,
            "logistics_data": logistics,  # template expects logistics_data.*
            "total_products": store.get_total_products(),
            "total_orders": store.get_total_orders(),
            "total_sales": store.get_total_sales(),
            "average_rating": store.get_average_rating(),
            "commission_rate": store.commission_rate,
            "processing_time": store.processing_time,
        })

    context = {
        "store_data": store_data,
        "current_month": current_month,
        "total_stores": stores.count(),
        "total_revenue_all": total_revenue_all,
        "total_expenses_all": total_expenses_all,
        "total_shipments_all": total_shipments_all,
    }
    return render(request, "finance/store_dashboard.html", context)

# =============================
# STORE FINANCIAL DETAIL
# =============================

@login_required
@user_passes_test(staff_required)
def store_detail(request, store_id):
    store = get_object_or_404(Store, id=store_id, status="active")

    date_from = request.GET.get("from")
    date_to = request.GET.get("to")

    date_from = (
        datetime.strptime(date_from, "%Y-%m-%d").date()
        if date_from else timezone.now().replace(day=1).date()
    )
    date_to = (
        datetime.strptime(date_to, "%Y-%m-%d").date()
        if date_to else timezone.now().date()
    )

    days = max((date_to - date_from).days + 1, 1)

    comprehensive = FinancialService.get_comprehensive_dashboard_data(store, days)

    records = FinancialRecord.objects.filter(
        store=store,
        transaction_date__range=(date_from, date_to)
    )

    category_breakdown = records.values(
        "category", "record_type"
    ).annotate(total=Sum("amount"))

    logistics, _ = LogisticsIntegration.objects.get_or_create(store=store)

    context = {
        "store": store,
        "date_from": date_from,
        "date_to": date_to,
        "financial_summary": comprehensive["financial_summary"],
        "gross_profit": comprehensive["financial_summary"]["gross_profit"],
        "net_profit": comprehensive["financial_summary"]["net_profit"],
        "category_breakdown": category_breakdown,
        "recent_transactions": records.order_by("-transaction_date")[:20],
        "logistics_data": logistics,
        "store_metrics": {
            "total_products": store.get_total_products(),
            "total_orders": store.get_total_orders(),
            "lifetime_sales": store.get_total_sales(),
            "average_rating": store.get_average_rating(),
            "commission_rate": store.commission_rate,
            "processing_time": store.processing_time,
            "return_policy_days": store.return_policy_days,
            "store_type": store.get_store_type_display(),
            "status": store.get_status_display(),
            "health_score": comprehensive["health_score"],
        },
        "order_metrics": comprehensive["order_metrics"],
        "return_metrics": comprehensive["return_metrics"],
        "logistics_metrics": comprehensive["logistics_metrics"],
        "payment_methods": comprehensive["payment_methods"],
    }

    return render(request, "finance/store_detail.html", context)


# =============================
# FINANCIAL REPORTS
# =============================

@login_required
@user_passes_test(staff_required)
def financial_reports(request):
    stores = Store.objects.filter(status=request.GET.get("status", "active"))

    if request.GET.get("type"):
        stores = stores.filter(store_type=request.GET["type"])

    if request.GET.get("category"):
        stores = stores.filter(category__slug=request.GET["category"])

    overall = FinancialRecord.objects.filter(store__in=stores).aggregate(
        revenue=Sum("amount", filter=Q(record_type="revenue")),
        expenses=Sum("amount", filter=Q(record_type="expense")),
        refunds=Sum("amount", filter=Q(record_type="refund")),
        commissions=Sum("amount", filter=Q(record_type="commission")),
    )

    store_performance = stores.annotate(
        revenue=Sum("financial_records__amount",
                    filter=Q(financial_records__record_type="revenue")),
        order_count=Count("products__order_items__order", distinct=True),
        product_count=Count("products", filter=Q(products__is_active=True)),
    ).order_by("-revenue")

    context = {
        "overall_summary": overall,
        "store_performance": store_performance,
        "store_categories": StoreCategory.objects.filter(is_active=True),
        "store_types": Store.STORE_TYPE_CHOICES,
    }

    return render(request, "finance/financial_reports.html", context)


# =============================
# ADVANCED ANALYTICS API
# =============================

@require_http_methods(["GET"])
@login_required
def advanced_analytics_api(request, store_id):
    store = get_object_or_404(Store, id=store_id)

    handlers = {
        "cohort": AdvancedFinancialAnalytics.get_cohort_analysis,
        "seasonal": AdvancedFinancialAnalytics.get_seasonal_trends,
        "margins": AdvancedFinancialAnalytics.get_profit_margin_analysis,
        "payments": AdvancedFinancialAnalytics.get_payment_method_performance,
        "returns": AdvancedFinancialAnalytics.get_return_analysis,
        "logistics": AdvancedFinancialAnalytics.get_logistics_efficiency_metrics,
        "competitive": AdvancedFinancialAnalytics.get_competitive_analysis,
    }

    analytics_type = request.GET.get("type", "cohort")
    handler = handlers.get(analytics_type)

    if not handler:
        return JsonResponse({"error": "Invalid analytics type"}, status=400)

    return JsonResponse(handler(store), safe=False)


# =============================
# REPORT GENERATION API
# =============================

@require_http_methods(["POST"])
@login_required
def generate_report_api(request, store_id):
    store = get_object_or_404(Store, id=store_id)

    report_type = request.POST.get("type", "monthly")
    year = int(request.POST.get("year", timezone.now().year))
    month = int(request.POST.get("month", timezone.now().month))

    if report_type != "monthly":
        return JsonResponse({"error": "Invalid report type"}, status=400)

    report = FinancialReportGenerator.generate_monthly_report(store, year, month)
    filename = f"{store.slug}_financial_{year}_{month:02d}.xlsx"

    FinancialReportGenerator.export_to_excel(report, filename)

    return JsonResponse({
        "status": "success",
        "filename": filename,
        "download_url": f"/media/reports/{filename}"
    })
