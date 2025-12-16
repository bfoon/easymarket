# analytics/management/commands/test_analytics.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from analytics.models import AnalyticsEvent, AnalyticsDailySummary, StoreDailySummary
from analytics.services import get_analytics_metrics_from_summaries
from analytics.store_kpis import get_store_kpis
from stores.models import Store


class Command(BaseCommand):
    help = 'Test analytics system and display sample data'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('=== Analytics System Test ===\n'))

        # Test 1: Check events
        total_events = AnalyticsEvent.objects.count()
        today_events = AnalyticsEvent.objects.filter(
            created_at__date=timezone.localdate()
        ).count()

        self.stdout.write(f"Total Events: {total_events}")
        self.stdout.write(f"Today's Events: {today_events}")

        # Test 2: Check summaries
        summary_count = AnalyticsDailySummary.objects.count()
        latest_summary = AnalyticsDailySummary.objects.first()

        self.stdout.write(f"\nDaily Summaries: {summary_count}")
        if latest_summary:
            self.stdout.write(f"Latest Summary Date: {latest_summary.date}")
            self.stdout.write(f"  - Page Views: {latest_summary.page_views}")
            self.stdout.write(f"  - Unique Visitors: {latest_summary.unique_visitors}")
            self.stdout.write(f"  - Conversion Rate: {latest_summary.conversion_rate}%")

        # Test 3: Platform metrics
        try:
            metrics = get_analytics_metrics_from_summaries(days=7)
            self.stdout.write(self.style.SUCCESS('\n=== Platform Metrics (7 days) ==='))
            for key, value in metrics.items():
                self.stdout.write(f"{key}: {value}")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error getting metrics: {e}"))

        # Test 4: Store metrics
        stores = Store.objects.filter(status='active')[:3]
        if stores:
            self.stdout.write(self.style.SUCCESS('\n=== Store Metrics (7 days) ==='))
            for store in stores:
                try:
                    kpis = get_store_kpis(store, days=7)
                    self.stdout.write(f"\n{store.name}:")
                    self.stdout.write(f"  - Visitors: {kpis.unique_visitors}")
                    self.stdout.write(f"  - Orders: {kpis.total_orders}")
                    self.stdout.write(f"  - Revenue: D{kpis.revenue}")
                    self.stdout.write(f"  - Conversion: {kpis.conversion_rate}%")
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"  Error: {e}"))

        # Test 5: Recent events
        recent = AnalyticsEvent.objects.exclude(event='page_view')[:5]
        if recent:
            self.stdout.write(self.style.SUCCESS('\n=== Recent Events ==='))
            for event in recent:
                self.stdout.write(
                    f"{event.created_at.strftime('%Y-%m-%d %H:%M')} - "
                    f"{event.get_event_display()}"
                )

        self.stdout.write(self.style.SUCCESS('\n=== Test Complete ==='))


