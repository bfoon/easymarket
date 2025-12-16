# analytics/store_kpis.py
from dataclasses import dataclass
from decimal import Decimal
from django.db.models import Sum, Avg
from django.utils import timezone

from analytics.models import StoreDailySummary


def _pct(numerator, denominator) -> Decimal:
    """
    Safe percentage calculation with Decimal precision.
    """
    if not denominator or denominator == 0:
        return Decimal("0.00")
    try:
        return (
                Decimal(str(numerator)) / Decimal(str(denominator)) * Decimal("100.00")
        ).quantize(Decimal("0.01"))
    except (ValueError, TypeError, ArithmeticError):
        return Decimal("0.00")


@dataclass
class StoreKPIResult:
    """
    Store KPI data class with all key metrics.
    """
    conversion_rate: Decimal
    bounce_rate: Decimal
    page_views: int
    unique_visitors: int
    return_customers: Decimal
    cart_abandonment: Decimal
    revenue: Decimal = Decimal("0.00")
    total_orders: int = 0
    avg_order_value: Decimal = Decimal("0.00")


def get_store_kpis(store, days=7) -> StoreKPIResult:
    """
    Returns KPI metrics for a store over the last N days.

    Args:
        store: Store model instance
        days: Number of days to analyze (default: 7)

    Returns:
        StoreKPIResult dataclass with all metrics

    Usage:
        from analytics.store_kpis import get_store_kpis

        kpis = get_store_kpis(store=my_store, days=7)
        print(f"Conversion: {kpis.conversion_rate}%")
        print(f"Revenue: ${kpis.revenue}")
    """
    today = timezone.localdate()
    start = today - timezone.timedelta(days=max(1, days) - 1)

    # Query store daily summaries
    qs = StoreDailySummary.objects.filter(
        store=store,
        date__range=(start, today)
    )

    # Aggregate metrics
    agg = qs.aggregate(
        page_views=Sum("page_views"),
        unique_visitors=Sum("unique_visitors"),
        returning_visitors=Sum("returning_visitors"),
        view_product=Sum("view_product"),
        add_to_cart=Sum("add_to_cart"),
        checkout=Sum("checkout"),
        paid=Sum("paid"),
        revenue=Sum("revenue"),
        avg_conversion=Avg("conversion_rate"),
        avg_bounce=Avg("bounce_rate"),
        avg_abandonment=Avg("cart_abandonment"),
    )

    # Extract values with safe defaults
    page_views = int(agg["page_views"] or 0)
    unique_visitors = int(agg["unique_visitors"] or 0)
    returning = int(agg["returning_visitors"] or 0)
    add_to_cart = int(agg["add_to_cart"] or 0)
    paid = int(agg["paid"] or 0)
    revenue = Decimal(str(agg["revenue"] or "0.00"))

    # Calculate KPIs
    # Conversion rate: paid orders / unique visitors
    conversion_rate = _pct(paid, unique_visitors)

    # Return customers: returning visitors / unique visitors
    return_customers = _pct(returning, unique_visitors)

    # Cart abandonment: (cart adds - paid) / cart adds
    cart_abandonment = _pct(max(add_to_cart - paid, 0), add_to_cart)

    # Average order value
    if paid > 0:
        avg_order_value = (revenue / Decimal(str(paid))).quantize(Decimal("0.01"))
    else:
        avg_order_value = Decimal("0.00")

    # Bounce rate: use averaged value from summaries
    # If not tracked in summaries, calculate from events
    bounce_rate = Decimal(str(agg["avg_bounce"] or "0.00")).quantize(Decimal("0.01"))

    return StoreKPIResult(
        conversion_rate=conversion_rate,
        bounce_rate=bounce_rate,
        page_views=page_views,
        unique_visitors=unique_visitors,
        return_customers=return_customers,
        cart_abandonment=cart_abandonment,
        revenue=revenue,
        total_orders=paid,
        avg_order_value=avg_order_value,
    )


def get_store_comparison(store, days=7):
    """
    Compare current period with previous period for trend analysis.

    Returns:
        dict with current metrics and percentage changes
    """
    today = timezone.localdate()
    current_start = today - timezone.timedelta(days=days - 1)
    previous_start = current_start - timezone.timedelta(days=days)
    previous_end = current_start - timezone.timedelta(days=1)

    # Current period
    current = get_store_kpis(store, days=days)

    # Previous period
    prev_qs = StoreDailySummary.objects.filter(
        store=store,
        date__range=(previous_start, previous_end)
    )

    prev_agg = prev_qs.aggregate(
        unique_visitors=Sum("unique_visitors"),
        paid=Sum("paid"),
        revenue=Sum("revenue"),
    )

    prev_visitors = int(prev_agg["unique_visitors"] or 0)
    prev_orders = int(prev_agg["paid"] or 0)
    prev_revenue = Decimal(str(prev_agg["revenue"] or "0.00"))

    # Calculate changes
    def calc_change(current_val, previous_val):
        if previous_val == 0:
            return 100.0 if current_val > 0 else 0.0
        return float(((current_val - previous_val) / previous_val) * 100)

    return {
        "current": current,
        "changes": {
            "visitors": calc_change(current.unique_visitors, prev_visitors),
            "orders": calc_change(current.total_orders, prev_orders),
            "revenue": calc_change(float(current.revenue), float(prev_revenue)),
        }
    }


def get_all_stores_ranking(days=7, limit=10):
    """
    Get top performing stores by revenue.

    Returns:
        List of dicts with store info and metrics
    """
    today = timezone.localdate()
    start = today - timezone.timedelta(days=days - 1)

    from django.db.models import F

    rankings = (
        StoreDailySummary.objects
        .filter(date__range=(start, today))
        .values("store__id", "store__name")
        .annotate(
            total_revenue=Sum("revenue"),
            total_orders=Sum("paid"),
            total_visitors=Sum("unique_visitors"),
            avg_conversion=Avg("conversion_rate"),
        )
        .order_by("-total_revenue")[:limit]
    )

    return list(rankings)