# analytics/services.py
from django.db.models import Count, Q
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from .models import (
    PageView,
    VisitSession,
    CartEvent,
    AnalyticsEvent,
    AnalyticsDailySummary
)


def get_analytics_metrics(days=30):
    """
    Get analytics metrics for the last N days.
    This uses legacy models for backward compatibility.
    Consider migrating to use AnalyticsDailySummary for better performance.
    """
    since = timezone.now() - timedelta(days=days)

    # Page views
    page_views = PageView.objects.filter(created_at__gte=since).count()

    # Unique visitors
    unique_visitors = (
        PageView.objects.filter(created_at__gte=since)
        .values("session_key")
        .distinct()
        .count()
    )

    # Sessions and bounce rate
    sessions = VisitSession.objects.filter(started_at__gte=since)
    total_sessions = sessions.count()
    bounced_sessions = sessions.filter(page_views=1).count()

    bounce_rate = (
        (bounced_sessions / total_sessions) * 100
        if total_sessions > 0 else 0
    )

    # Conversion rate (using AnalyticsEvent)
    paid_orders = AnalyticsEvent.objects.filter(
        event="paid",
        created_at__gte=since
    ).count()

    conversion_rate = (
        (paid_orders / unique_visitors) * 100
        if unique_visitors > 0 else 0
    )

    # Return customers
    return_customers_count = (
        VisitSession.objects.filter(
            user__isnull=False,
            started_at__gte=since
        )
        .values("user")
        .annotate(visit_count=Count("id"))
        .filter(visit_count__gt=1)
        .count()
    )

    return_customers_pct = (
        (return_customers_count / unique_visitors) * 100
        if unique_visitors > 0 else 0
    )

    # Cart abandonment
    cart_adds = CartEvent.objects.filter(
        event="add",
        created_at__gte=since
    ).count()

    cart_completed = CartEvent.objects.filter(
        event="completed",
        created_at__gte=since
    ).count()

    cart_abandonment = (
        ((cart_adds - cart_completed) / cart_adds) * 100
        if cart_adds > 0 else 0
    )

    return {
        "conversion_rate": round(conversion_rate, 2),
        "bounce_rate": round(bounce_rate, 2),
        "page_views": page_views,
        "unique_visitors": unique_visitors,
        "return_customers": round(return_customers_pct, 2),
        "cart_abandonment": round(cart_abandonment, 2),
    }


def get_analytics_metrics_from_summaries(days=30):
    """
    Get analytics metrics from daily summaries (more efficient).
    Use this instead of get_analytics_metrics() when summaries are up to date.
    """
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)

    summaries = AnalyticsDailySummary.objects.filter(
        date__range=(start, today)
    )

    from django.db.models import Sum, Avg

    agg = summaries.aggregate(
        page_views=Sum("page_views"),
        unique_visitors=Sum("unique_visitors"),
        returning_visitors=Sum("returning_visitors"),
        conversion_rate=Avg("conversion_rate"),
        bounce_rate=Avg("bounce_rate"),
        cart_abandonment=Avg("cart_abandonment"),
    )

    page_views = agg["page_views"] or 0
    unique_visitors = agg["unique_visitors"] or 0
    returning = agg["returning_visitors"] or 0

    return_customers = (
        (Decimal(returning) / Decimal(unique_visitors) * 100)
        if unique_visitors > 0 else Decimal("0.00")
    )

    return {
        "conversion_rate": float(agg["conversion_rate"] or 0),
        "bounce_rate": float(agg["bounce_rate"] or 0),
        "page_views": page_views,
        "unique_visitors": unique_visitors,
        "return_customers": float(return_customers),
        "cart_abandonment": float(agg["cart_abandonment"] or 0),
    }


def track_event(session_key, event_type, user=None, store=None, product=None, order=None, **kwargs):
    """
    Helper function to track analytics events.

    Usage:
        from analytics.services import track_event

        # Track product view
        track_event(
            session_key=request.session.session_key,
            event_type="product_view",
            user=request.user if request.user.is_authenticated else None,
            store=product.store,
            product=product
        )

        # Track add to cart
        track_event(
            session_key=request.session.session_key,
            event_type="add_to_cart",
            user=request.user if request.user.is_authenticated else None,
            store=cart_item.product.store,
            product=cart_item.product
        )
    """
    event_data = {
        "session_key": session_key,
        "event": event_type,
        "user": user,
        "store": store,
        "product": product,
        "order": order,
    }

    # Add any additional fields from kwargs
    event_data.update(kwargs)

    return AnalyticsEvent.objects.create(**event_data)


def get_top_products(store=None, days=30, limit=10):
    """
    Get top products by views or add to cart events.
    """
    since = timezone.now() - timedelta(days=days)

    query = AnalyticsEvent.objects.filter(
        event__in=["product_view", "add_to_cart"],
        created_at__gte=since
    ).exclude(product__isnull=True)

    if store:
        query = query.filter(store=store)

    top_products = (
        query
        .values("product__id", "product__name")
        .annotate(
            views=Count("id", filter=Q(event="product_view")),
            adds=Count("id", filter=Q(event="add_to_cart"))
        )
        .order_by("-views")[:limit]
    )

    return list(top_products)


def get_funnel_metrics(store=None, days=30):
    """
    Get conversion funnel metrics.
    """
    since = timezone.now() - timedelta(days=days)

    query = AnalyticsEvent.objects.filter(created_at__gte=since)

    if store:
        query = query.filter(store=store)

    metrics = {
        "product_views": query.filter(event="product_view").count(),
        "add_to_cart": query.filter(event="add_to_cart").count(),
        "checkout": query.filter(event="checkout").count(),
        "paid": query.filter(event="paid").count(),
    }

    # Calculate conversion rates
    if metrics["product_views"] > 0:
        metrics["view_to_cart_rate"] = (
                metrics["add_to_cart"] / metrics["product_views"] * 100
        )
    else:
        metrics["view_to_cart_rate"] = 0

    if metrics["add_to_cart"] > 0:
        metrics["cart_to_checkout_rate"] = (
                metrics["checkout"] / metrics["add_to_cart"] * 100
        )
    else:
        metrics["cart_to_checkout_rate"] = 0

    if metrics["checkout"] > 0:
        metrics["checkout_to_paid_rate"] = (
                metrics["paid"] / metrics["checkout"] * 100
        )
    else:
        metrics["checkout_to_paid_rate"] = 0

    if metrics["product_views"] > 0:
        metrics["overall_conversion"] = (
                metrics["paid"] / metrics["product_views"] * 100
        )
    else:
        metrics["overall_conversion"] = 0

    return metrics