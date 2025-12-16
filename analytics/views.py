# analytics/views.py
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.utils import timezone
from django.db.models import Sum, Avg, Count, Q, F, Case, When, FloatField
from django.db.models.functions import TruncDate
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from .models import AnalyticsDailySummary, AnalyticsEvent, StoreDailySummary


@staff_member_required
def analytics_dashboard(request):
    # Get and validate days parameter
    try:
        days = int(request.GET.get("days", 30))
    except (ValueError, TypeError):
        days = 30
    days = max(7, min(days, 180))

    today = timezone.localdate()
    start = today - timedelta(days=days - 1)

    # Fetch summaries
    summaries = AnalyticsDailySummary.objects.filter(
        date__range=(start, today)
    ).order_by("date")

    # Safe aggregation with fallback values
    agg = summaries.aggregate(
        page_views=Sum("page_views"),
        unique_visitors=Sum("unique_visitors"),
        returning_visitors=Sum("returning_visitors"),
        add_to_cart=Sum("add_to_cart"),
        checkout=Sum("checkout"),
        paid=Sum("paid"),
        conversion_rate=Avg("conversion_rate"),
        bounce_rate=Avg("bounce_rate"),
        cart_abandonment=Avg("cart_abandonment"),
    )

    # Extract values with safe defaults
    page_views = agg["page_views"] or 0
    unique_visitors = agg["unique_visitors"] or 0
    returning_visitors = agg["returning_visitors"] or 0
    add_to_cart = agg["add_to_cart"] or 0
    checkout = agg["checkout"] or 0
    paid = agg["paid"] or 0

    # Calculate return customer rate safely
    try:
        return_customers = (
            (Decimal(returning_visitors) / Decimal(unique_visitors)) * 100
            if unique_visitors > 0 else Decimal("0.00")
        )
    except (InvalidOperation, ZeroDivisionError):
        return_customers = Decimal("0.00")

    # Calculate average order value
    store_summaries = StoreDailySummary.objects.filter(
        date__range=(start, today)
    ).aggregate(
        total_revenue=Sum("revenue"),
        total_orders=Sum("paid")
    )

    total_revenue = store_summaries["total_revenue"] or Decimal("0.00")
    total_orders = store_summaries["total_orders"] or 0

    try:
        avg_order_value = (
            total_revenue / Decimal(total_orders)
            if total_orders > 0 else Decimal("0.00")
        )
    except (InvalidOperation, ZeroDivisionError):
        avg_order_value = Decimal("0.00")

    # ---------------------------
    # KPI CARDS (ENHANCED)
    # ---------------------------
    kpis = [
        {
            "label": "Page Views",
            "value": page_views,
            "is_percent": False,
            "icon": "👁️"
        },
        {
            "label": "Unique Visitors",
            "value": unique_visitors,
            "is_percent": False,
            "icon": "👥"
        },
        {
            "label": "Total Revenue",
            "value": float(total_revenue),
            "is_percent": False,
            "is_currency": True,
            "icon": "💰"
        },
        {
            "label": "Total Orders",
            "value": total_orders,
            "is_percent": False,
            "icon": "✅"
        },
        {
            "label": "Conversion Rate",
            "value": float(agg["conversion_rate"] or 0),
            "is_percent": True,
            "icon": "📈"
        },
        {
            "label": "Avg Order Value",
            "value": float(avg_order_value),
            "is_percent": False,
            "is_currency": True,
            "icon": "🎯"
        },
    ]

    # ---------------------------
    # CHART DATA (ENHANCED)
    # ---------------------------
    # Ensure we have data for all days in the range
    chart_data = {}
    for d in summaries:
        chart_data[d.date] = {
            "page_views": d.page_views,
            "unique_visitors": d.unique_visitors,
            "conversion_rate": float(d.conversion_rate),
        }

    # Fill missing dates with zeros
    labels = []
    page_views_list = []
    unique_visitors_list = []
    conversion_rate_list = []

    current_date = start
    while current_date <= today:
        labels.append(current_date.strftime("%b %d"))

        if current_date in chart_data:
            page_views_list.append(chart_data[current_date]["page_views"])
            unique_visitors_list.append(chart_data[current_date]["unique_visitors"])
            conversion_rate_list.append(chart_data[current_date]["conversion_rate"])
        else:
            page_views_list.append(0)
            unique_visitors_list.append(0)
            conversion_rate_list.append(0)

        current_date += timedelta(days=1)

    chart = {
        "labels": labels,
        "page_views": page_views_list,
        "unique_visitors": unique_visitors_list,
        "conversion_rate": conversion_rate_list,
    }

    # ---------------------------
    # FUNNEL (ENHANCED)
    # ---------------------------
    funnel = {
        "add_to_cart": add_to_cart,
        "checkout": checkout,
        "paid": paid,
    }

    # Calculate funnel conversion rates
    funnel_rates = {
        "cart_to_checkout": (
            (Decimal(checkout) / Decimal(add_to_cart)) * 100
            if add_to_cart > 0 else Decimal("0.00")
        ),
        "checkout_to_paid": (
            (Decimal(paid) / Decimal(checkout)) * 100
            if checkout > 0 else Decimal("0.00")
        ),
        "overall_conversion": (
            (Decimal(paid) / Decimal(add_to_cart)) * 100
            if add_to_cart > 0 else Decimal("0.00")
        ),
    }

    # ---------------------------
    # TOP STORES (ENHANCED)
    # ---------------------------
    top_stores = (
        StoreDailySummary.objects.filter(date__range=(start, today))
        .values("store__name", "store__id")
        .annotate(
            revenue=Sum("revenue"),
            paid=Sum("paid"),
            visitors=Sum("unique_visitors"),
            page_views=Sum("page_views"),
            conversion=Avg("conversion_rate"),
        )
        .filter(revenue__gt=0)  # Only stores with revenue
        .order_by("-revenue")[:8]
    )

    # ---------------------------
    # TOP PAGES (ENHANCED)
    # ---------------------------
    top_pages = (
        AnalyticsEvent.objects.filter(
            event="page_view",
            created_at__date__range=(start, today)
        )
        .exclude(Q(path="") | Q(path__isnull=True))
        .values("path")
        .annotate(
            views=Count("id"),
            unique_sessions=Count("session_key", distinct=True)
        )
        .order_by("-views")[:10]
    )

    # ---------------------------
    # TRAFFIC SOURCES (NEW)
    # ---------------------------
    traffic_sources = (
        AnalyticsEvent.objects.filter(
            event="page_view",
            created_at__date__range=(start, today)
        )
        .exclude(Q(referrer="") | Q(referrer__isnull=True))
        .values("referrer")
        .annotate(visits=Count("session_key", distinct=True))
        .order_by("-visits")[:5]
    )

    # ---------------------------
    # RECENT ACTIVITY (NEW)
    # ---------------------------
    recent_events = (
        AnalyticsEvent.objects
        .filter(created_at__date__range=(start, today))
        .exclude(event="page_view")  # Exclude page views for cleaner data
        .select_related("user", "store", "product", "order")
        .order_by("-created_at")[:20]
    )

    # ---------------------------
    # PERFORMANCE METRICS (NEW)
    # ---------------------------
    performance = {
        "bounce_rate": float(agg["bounce_rate"] or 0),
        "cart_abandonment": float(agg["cart_abandonment"] or 0),
        "return_rate": float(return_customers),
        "avg_session_pages": (
            float(page_views) / float(unique_visitors)
            if unique_visitors > 0 else 0.0
        ),
    }

    # ---------------------------
    # COMPARISON DATA (NEW)
    # ---------------------------
    # Compare with previous period
    prev_start = start - timedelta(days=days)
    prev_end = start - timedelta(days=1)

    prev_agg = AnalyticsDailySummary.objects.filter(
        date__range=(prev_start, prev_end)
    ).aggregate(
        page_views=Sum("page_views"),
        unique_visitors=Sum("unique_visitors"),
        paid=Sum("paid"),
    )

    prev_page_views = prev_agg["page_views"] or 0
    prev_unique_visitors = prev_agg["unique_visitors"] or 0
    prev_paid = prev_agg["paid"] or 0

    # Calculate percentage changes
    def calc_change(current, previous):
        if previous == 0:
            return 0 if current == 0 else 100
        return ((current - previous) / previous) * 100

    comparison = {
        "page_views_change": calc_change(page_views, prev_page_views),
        "visitors_change": calc_change(unique_visitors, prev_unique_visitors),
        "orders_change": calc_change(paid, prev_paid),
    }

    return render(
        request,
        "analytics/dashboard.html",
        {
            "days": days,
            "kpis": kpis,
            "chart": chart,
            "funnel": funnel,
            "funnel_rates": funnel_rates,
            "top_stores": top_stores,
            "top_pages": top_pages,
            "traffic_sources": traffic_sources,
            "recent_events": recent_events,
            "performance": performance,
            "comparison": comparison,
            "date_range": {
                "start": start,
                "end": today,
            },
        },
    )