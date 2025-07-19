from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime, timedelta
from stores.models import Store, StoreMetrics
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Calculate daily metrics for all stores'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            help='Calculate metrics for specific date (YYYY-MM-DD format)',
        )
        parser.add_argument(
            '--days',
            type=int,
            default=1,
            help='Number of days to calculate metrics for (default: 1)',
        )
        parser.add_argument(
            '--store-id',
            type=str,
            help='Calculate metrics for specific store UUID',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Recalculate metrics even if they already exist',
        )

    def handle(self, *args, **options):
        if options['date']:
            try:
                target_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
            except ValueError:
                self.stdout.write(
                    self.style.ERROR('Invalid date format. Use YYYY-MM-DD')
                )
                return
        else:
            target_date = timezone.now().date()

        # Get stores to process
        if options['store_id']:
            try:
                stores = [Store.objects.get(id=options['store_id'])]
            except Store.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'Store with ID {options["store_id"]} not found')
                )
                return
        else:
            stores = Store.objects.filter(status='active')

        self.stdout.write(f'Processing {stores.count()} stores...')

        # Calculate metrics for specified number of days
        for day_offset in range(options['days']):
            calc_date = target_date - timedelta(days=day_offset)

            for store in stores:
                try:
                    # Check if metrics already exist
                    existing_metrics = StoreMetrics.objects.filter(
                        store=store,
                        date=calc_date
                    ).first()

                    if existing_metrics and not options['force']:
                        self.stdout.write(
                            f'Metrics for {store.name} on {calc_date} already exist. Skipping...'
                        )
                        continue

                    # Calculate metrics
                    metrics = StoreMetrics.calculate_daily_metrics(store, calc_date)

                    self.stdout.write(
                        self.style.SUCCESS(
                            f'✓ Calculated metrics for {store.name} on {calc_date}'
                        )
                    )

                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f'✗ Error calculating metrics for {store.name}: {str(e)}'
                        )
                    )
                    logger.error(f'Error calculating metrics for store {store.id}: {str(e)}')

        self.stdout.write(
            self.style.SUCCESS('Store metrics calculation completed!')
        )
