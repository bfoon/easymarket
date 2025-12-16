# analytics/management/commands/build_analytics.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from analytics.tasks import build_daily_summaries, backfill_summaries


class Command(BaseCommand):
    help = 'Build analytics daily summaries'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            help='Specific date to process (YYYY-MM-DD)',
        )
        parser.add_argument(
            '--backfill',
            type=int,
            help='Backfill N days from today',
        )
        parser.add_argument(
            '--yesterday',
            action='store_true',
            help='Process yesterday only',
        )

    def handle(self, *args, **options):
        if options.get('backfill'):
            days = options['backfill']
            end_date = timezone.localdate()
            start_date = end_date - timedelta(days=days)

            self.stdout.write(f"Backfilling {days} days: {start_date} to {end_date}")
            result = backfill_summaries(start_date, end_date)
            self.stdout.write(self.style.SUCCESS(result))

        elif options.get('yesterday'):
            date = timezone.localdate() - timedelta(days=1)
            self.stdout.write(f"Processing date: {date}")
            result = build_daily_summaries(for_date=date)
            self.stdout.write(self.style.SUCCESS(result))

        elif options.get('date'):
            from datetime import datetime
            date = datetime.strptime(options['date'], '%Y-%m-%d').date()
            self.stdout.write(f"Processing date: {date}")
            result = build_daily_summaries(for_date=date)
            self.stdout.write(self.style.SUCCESS(result))

        else:
            # Default: process yesterday
            date = timezone.localdate() - timedelta(days=1)
            self.stdout.write(f"Processing yesterday: {date}")
            result = build_daily_summaries(for_date=date)
            self.stdout.write(self.style.SUCCESS(result))


