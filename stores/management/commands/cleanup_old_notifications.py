from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from stores.models import StoreNotification, ProductPriceHistory


class Command(BaseCommand):
    help = 'Cleanup old notifications and price history records'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=90,
            help='Delete records older than this many days (default: 90)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting'
        )

    def handle(self, *args, **options):
        days = options['days']
        dry_run = options['dry_run']

        cutoff_date = timezone.now() - timedelta(days=days)

        # Count records to be deleted
        old_notifications = StoreNotification.objects.filter(
            created_at__lt=cutoff_date,
            is_read=True
        )
        old_price_history = ProductPriceHistory.objects.filter(
            changed_at__lt=cutoff_date
        )

        notification_count = old_notifications.count()
        price_history_count = old_price_history.count()

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f'Dry run: Would delete {notification_count} notifications '
                    f'and {price_history_count} price history records older than {days} days.'
                )
            )
        else:
            # Delete old records
            old_notifications.delete()
            old_price_history.delete()

            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully deleted {notification_count} notifications '
                    f'and {price_history_count} price history records.'
                )
            )