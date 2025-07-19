from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from stores.models import StoreInventoryTracking


class Command(BaseCommand):
    help = 'Clean up old inventory tracking records'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=365,
            help='Delete records older than this many days (default: 365)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting',
        )

    def handle(self, *args, **options):
        cutoff_date = timezone.now() - timedelta(days=options['days'])

        old_records = StoreInventoryTracking.objects.filter(
            timestamp__lt=cutoff_date
        )

        count = old_records.count()

        if options['dry_run']:
            self.stdout.write(
                f'Would delete {count} inventory tracking records older than {cutoff_date.date()}'
            )
        else:
            deleted_count, _ = old_records.delete()
            self.stdout.write(
                self.style.SUCCESS(
                    f'Deleted {deleted_count} old inventory tracking records'
                )
            )
