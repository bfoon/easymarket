# analytics/context_processors.py
from django.db.models import Q
from stores.models import Store
from .services import get_analytics_metrics_from_summaries
from .store_kpis import get_store_kpis


def analytics_metrics(request):
    """
    Add platform-wide analytics metrics to template context.
    Available in all templates as {{ analytics }}

    Usage in templates:
        {{ analytics.page_views }}
        {{ analytics.conversion_rate }}%
    """
    try:
        metrics = get_analytics_metrics_from_summaries(days=30)
    except Exception as e:
        # Fallback to empty metrics if summaries don't exist yet
        metrics = {
            "conversion_rate": 0,
            "bounce_rate": 0,
            "page_views": 0,
            "unique_visitors": 0,
            "return_customers": 0,
            "cart_abandonment": 0,
        }

    return {
        "analytics": metrics
    }


def store_analytics_kpis(request):
    """
    Add store-specific analytics to template context.
    Only processes for authenticated users with stores.

    Available in templates as:
        {{ store_kpis_map }} - dict of all stores' KPIs
        {{ active_store_kpis }} - KPIs for first/active store

    Usage in templates:
        <!-- Display KPIs for current store -->
        <div>Conversion: {{ active_store_kpis.conversion_rate }}%</div>
        <div>Revenue: ${{ active_store_kpis.revenue }}</div>

        <!-- Loop through all stores -->
        {% for store_id, kpis in store_kpis_map.items %}
            <h3>{{ kpis.store_name }}</h3>
            <p>Orders: {{ kpis.total_orders }}</p>
        {% endfor %}
    """
    # Only process for authenticated users
    if not request.user.is_authenticated:
        return {}

    # Get user's stores
    try:
        stores = Store.objects.filter(
            Q(owner=request.user) | Q(managers=request.user),
            status="active"
        ).distinct()
    except Exception:
        return {}

    if not stores.exists():
        return {}

    # Build KPI map for all stores
    store_kpis_map = {}

    for store in stores:
        try:
            kpis = get_store_kpis(store=store, days=7)

            store_kpis_map[str(store.id)] = {
                "store_id": str(store.id),
                "store_name": store.name,
                "conversion_rate": float(kpis.conversion_rate),
                "bounce_rate": float(kpis.bounce_rate),
                "page_views": int(kpis.page_views),
                "unique_visitors": int(kpis.unique_visitors),
                "return_customers": float(kpis.return_customers),
                "cart_abandonment": float(kpis.cart_abandonment),
                "revenue": float(kpis.revenue),
                "total_orders": int(kpis.total_orders),
                "avg_order_value": float(kpis.avg_order_value),
            }
        except Exception as e:
            # Skip stores with errors
            continue

    if not store_kpis_map:
        return {}

    # Set first store as active (or use session-based active store if implemented)
    first_store_id = next(iter(store_kpis_map.keys()))

    # Check if there's an active store in session
    active_store_id = request.session.get('active_store_id')
    if active_store_id and str(active_store_id) in store_kpis_map:
        active_kpis = store_kpis_map[str(active_store_id)]
    else:
        active_kpis = store_kpis_map[first_store_id]

    return {
        "store_kpis_map": store_kpis_map,
        "active_store_kpis": active_kpis,
        "has_stores": True,
    }


def store_selector(request):
    """
    Optional: Add store selection helpers to context.
    Useful for multi-store dashboards.
    """
    if not request.user.is_authenticated:
        return {}

    try:
        stores = Store.objects.filter(
            Q(owner=request.user) | Q(managers=request.user),
            status="active"
        ).distinct().values('id', 'name', 'slug')

        stores_list = list(stores)

        return {
            "user_stores": stores_list,
            "user_stores_count": len(stores_list),
        }
    except Exception:
        return {}