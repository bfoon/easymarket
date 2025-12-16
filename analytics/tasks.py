# analytics/tasks.py
from celery import shared_task
from django.utils import timezone
from django.db.models import Count, Sum, Q
from decimal import Decimal
from .models import AnalyticsEvent, AnalyticsDailySummary, StoreDailySummary


@shared_task
def build_daily_summaries(for_date=None):
    """
    Build daily analytics summaries for platform and stores.
    Run this task daily via celery beat.
    """
    d = for_date or (timezone.localdate() - timezone.timedelta(days=1))

    # Get all events for this date
    day_events = AnalyticsEvent.objects.filter(created_at__date=d)

    # Platform-wide metrics
    page_views = day_events.filter(event="page_view").count()
    unique_visitors = day_events.values("session_key").distinct().count()

    # Returning visitors: sessions that appeared before this date
    if unique_visitors > 0:
        sessions_today = set(day_events.values_list("session_key", flat=True).distinct())
        sessions_before = set(
            AnalyticsEvent.objects
            .filter(created_at__date__lt=d, session_key__in=sessions_today)
            .values_list("session_key", flat=True)
            .distinct()
        )
        returning_visitors = len(sessions_before)
    else:
        returning_visitors = 0

    # Bounce rate: sessions with only 1 event (page view) that day
    sessions_with_counts = (
        day_events
        .values("session_key")
        .annotate(event_count=Count("id"))
    )
    bounced_sessions = sessions_with_counts.filter(event_count=1).count()
    bounce_rate = (
        (Decimal(bounced_sessions) / Decimal(unique_visitors) * 100)
        if unique_visitors else Decimal("0.00")
    )

    # Funnel metrics
    add_to_cart = day_events.filter(event="add_to_cart").count()
    checkout = day_events.filter(event="checkout").count()
    paid = day_events.filter(event="paid").count()

    # Conversion rate: paid orders / unique visitors
    conversion_rate = (
        (Decimal(paid) / Decimal(unique_visitors) * 100)
        if unique_visitors else Decimal("0.00")
    )

    # Cart abandonment: sessions that added to cart but didn't pay
    cart_sessions = set(
        day_events.filter(event="add_to_cart")
        .values_list("session_key", flat=True)
        .distinct()
    )
    paid_sessions = set(
        day_events.filter(event="paid")
        .values_list("session_key", flat=True)
        .distinct()
    )
    abandoned_count = len(cart_sessions - paid_sessions)
    cart_abandonment = (
        (Decimal(abandoned_count) / Decimal(len(cart_sessions)) * 100)
        if cart_sessions else Decimal("0.00")
    )

    # Save platform summary
    AnalyticsDailySummary.objects.update_or_create(
        date=d,
        defaults={
            "page_views": page_views,
            "unique_visitors": unique_visitors,
            "returning_visitors": returning_visitors,
            "add_to_cart": add_to_cart,
            "checkout": checkout,
            "paid": paid,
            "conversion_rate": conversion_rate.quantize(Decimal("0.01")),
            "bounce_rate": bounce_rate.quantize(Decimal("0.01")),
            "cart_abandonment": cart_abandonment.quantize(Decimal("0.01")),
        }
    )

    # Per-store summaries
    store_ids = day_events.exclude(store_id__isnull=True).values_list("store_id", flat=True).distinct()

    for store_id in store_ids:
        store_events = day_events.filter(store_id=store_id)

        # Store traffic
        store_page_views = store_events.filter(event="page_view").count()
        store_unique_visitors = store_events.values("session_key").distinct().count()

        # Store returning visitors
        if store_unique_visitors > 0:
            store_sessions_today = set(
                store_events.values_list("session_key", flat=True).distinct()
            )
            store_sessions_before = set(
                AnalyticsEvent.objects
                .filter(created_at__date__lt=d, store_id=store_id, session_key__in=store_sessions_today)
                .values_list("session_key", flat=True)
                .distinct()
            )
            store_returning = len(store_sessions_before)
        else:
            store_returning = 0

        # Store funnel
        store_product_views = store_events.filter(event="product_view").count()
        store_add_to_cart = store_events.filter(event="add_to_cart").count()
        store_checkout = store_events.filter(event="checkout").count()
        store_paid = store_events.filter(event="paid").count()

        # Store conversion rate: paid / unique visitors (or product views)
        store_conversion = (
            (Decimal(store_paid) / Decimal(store_unique_visitors) * 100)
            if store_unique_visitors else Decimal("0.00")
        )

        # Store bounce rate
        store_sessions_counts = (
            store_events
            .values("session_key")
            .annotate(event_count=Count("id"))
        )
        store_bounced = store_sessions_counts.filter(event_count=1).count()
        store_bounce_rate = (
            (Decimal(store_bounced) / Decimal(store_unique_visitors) * 100)
            if store_unique_visitors else Decimal("0.00")
        )

        # Store cart abandonment
        store_cart_sessions = set(
            store_events.filter(event="add_to_cart")
            .values_list("session_key", flat=True)
            .distinct()
        )
        store_paid_sessions = set(
            store_events.filter(event="paid")
            .values_list("session_key", flat=True)
            .distinct()
        )
        store_abandoned = len(store_cart_sessions - store_paid_sessions)
        store_cart_abandonment = (
            (Decimal(store_abandoned) / Decimal(len(store_cart_sessions)) * 100)
            if store_cart_sessions else Decimal("0.00")
        )

        # Calculate revenue from orders
        from orders.models import Order
        store_revenue = (
                Order.objects
                .filter(
                    store_id=store_id,
                    created_at__date=d,
                    status__in=["paid", "completed", "shipped", "delivered"]
                )
                .aggregate(total=Sum("total"))["total"] or Decimal("0.00")
        )

        # Save store summary
        StoreDailySummary.objects.update_or_create(
            date=d,
            store_id=store_id,
            defaults={
                "page_views": store_page_views,
                "unique_visitors": store_unique_visitors,
                "returning_visitors": store_returning,
                "view_product": store_product_views,
                "add_to_cart": store_add_to_cart,
                "checkout": store_checkout,
                "paid": store_paid,
                "conversion_rate": store_conversion.quantize(Decimal("0.01")),
                "bounce_rate": store_bounce_rate.quantize(Decimal("0.01")),
                "cart_abandonment": store_cart_abandonment.quantize(Decimal("0.01")),
                "revenue": store_revenue,
            }
        )

    return f"Built summaries for {d} - {len(store_ids)} stores"


@shared_task
def backfill_summaries(start_date, end_date=None):
    """
    Backfill daily summaries for a date range.
    Usage: backfill_summaries('2024-01-01', '2024-01-31')
    """
    from datetime import datetime, timedelta

    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, "%Y-%m-%d").date()

    if end_date is None:
        end_date = timezone.localdate()
    elif isinstance(end_date, str):
        end_date = datetime.strptime(end_date, "%Y-%m-%d").date()

    current_date = start_date
    processed = 0

    while current_date <= end_date:
        build_daily_summaries(for_date=current_date)
        processed += 1
        current_date += timedelta(days=1)

    return f"Backfilled {processed} days from {start_date} to {end_date}"