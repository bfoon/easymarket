# analytics/management/commands/generate_test_data.py

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
import random
from analytics.models import AnalyticsEvent
from stores.models import Store
from marketplace.models import Product


class Command(BaseCommand):
    help = 'Generate test analytics data for development'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=7,
            help='Number of days of data to generate',
        )
        parser.add_argument(
            '--events-per-day',
            type=int,
            default=100,
            help='Number of events per day',
        )

    def handle(self, *args, **options):
        days = options['days']
        events_per_day = options['events_per_day']

        self.stdout.write(f"Generating {days} days of test data...")

        # Get some stores and products
        stores = list(Store.objects.filter(status='active')[:5])
        products = list(Product.objects.filter(status='active')[:20])

        if not stores or not products:
            self.stdout.write(self.style.ERROR(
                'Need active stores and products to generate data'
            ))
            return

        events_created = 0
        today = timezone.localdate()

        for day in range(days):
            date = today - timedelta(days=day)

            # Generate sessions for this day
            num_sessions = random.randint(20, 50)

            for session_num in range(num_sessions):
                session_key = f"test_session_{date}_{session_num}"

                # Each session has multiple events
                num_events = random.randint(1, 10)

                for _ in range(num_events):
                    event_type = random.choice([
                        'page_view',
                        'page_view',
                        'page_view',
                        'product_view',
                        'product_view',
                        'add_to_cart',
                        'checkout',
                        'paid',
                    ])

                    store = random.choice(stores)
                    product = random.choice([p for p in products if p.store == store])

                    # Create event at random time during the day
                    hour = random.randint(0, 23)
                    minute = random.randint(0, 59)
                    created_at = timezone.make_aware(
                        timezone.datetime.combine(
                            date,
                            timezone.datetime.min.time().replace(
                                hour=hour,
                                minute=minute
                            )
                        )
                    )

                    AnalyticsEvent.objects.create(
                        session_key=session_key,
                        event=event_type,
                        store=store,
                        product=product if event_type != 'page_view' else None,
                        path=f"/store/{store.slug}/product/{product.slug}/",
                        created_at=created_at,
                    )

                    events_created += 1

            self.stdout.write(f"Generated data for {date}")

        self.stdout.write(self.style.SUCCESS(
            f"\nCreated {events_created} test events across {days} days"
        ))
        self.stdout.write(
            "Run 'python manage.py build_analytics --backfill {days}' "
            "to process summaries"
        )