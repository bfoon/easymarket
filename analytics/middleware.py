# analytics/middleware.py
from django.utils.deprecation import MiddlewareMixin
from .models import PageView, VisitSession, AnalyticsEvent


class AnalyticsMiddleware(MiddlewareMixin):
    """
    Tracks page views and session activity.
    Uses both legacy models (PageView, VisitSession) and new AnalyticsEvent.
    """

    EXCLUDED_PATHS = [
        '/admin/',
        '/static/',
        '/media/',
        '/__debug__/',
        '/favicon.ico',
        '/robots.txt',
    ]

    def should_track(self, request):
        """Determine if this request should be tracked"""
        # Skip tracking for excluded paths
        for excluded in self.EXCLUDED_PATHS:
            if request.path.startswith(excluded):
                return False

        # Skip tracking for bots (basic check)
        user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
        bot_indicators = ['bot', 'crawler', 'spider', 'scraper']
        if any(indicator in user_agent for indicator in bot_indicators):
            return False

        return True

    def process_request(self, request):
        """Track page views and update session"""
        if not self.should_track(request):
            return None

        # Ensure session exists
        if not request.session.session_key:
            request.session.create()

        session_key = request.session.session_key

        # Update or create visit session
        visit, created = VisitSession.objects.get_or_create(
            session_key=session_key,
            defaults={
                "user": request.user if request.user.is_authenticated else None
            }
        )

        # Update session activity
        visit.page_views += 1
        visit.save(update_fields=["page_views", "last_activity"])

        # Create legacy PageView record
        PageView.objects.create(
            user=request.user if request.user.is_authenticated else None,
            session_key=session_key,
            path=request.path,
            ip_address=self.get_client_ip(request)
        )

        # Create AnalyticsEvent record
        referrer = request.META.get('HTTP_REFERER', '')

        AnalyticsEvent.objects.create(
            user=request.user if request.user.is_authenticated else None,
            session_key=session_key,
            event="page_view",
            path=request.path,
            referrer=referrer,
        )

        return None

    def get_client_ip(self, request):
        """Extract client IP address from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


class StoreAnalyticsMiddleware(MiddlewareMixin):
    """
    Optional: Attach store context to requests for store-specific tracking.
    Add this middleware AFTER AnalyticsMiddleware if you want automatic store detection.
    """

    def process_request(self, request):
        """Detect current store from URL and attach to request"""
        # This is a placeholder - implement based on your URL structure
        # Example: /store/abc123/products/ -> store_id = abc123

        # Option 1: Store slug in URL
        if '/store/' in request.path:
            parts = request.path.split('/')
            try:
                store_index = parts.index('store')
                if len(parts) > store_index + 1:
                    store_slug = parts[store_index + 1]
                    from stores.models import Store
                    try:
                        store = Store.objects.get(slug=store_slug)
                        request.current_store = store
                    except Store.DoesNotExist:
                        pass
            except (ValueError, IndexError):
                pass

        # Option 2: Subdomain-based stores (e.g., mystore.marketplace.com)
        # host = request.get_host().split(':')[0]
        # subdomain = host.split('.')[0]
        # if subdomain != 'www' and subdomain != request.get_host():
        #     try:
        #         from stores.models import Store
        #         store = Store.objects.get(subdomain=subdomain)
        #         request.current_store = store
        #     except Store.DoesNotExist:
        #         pass

        return None