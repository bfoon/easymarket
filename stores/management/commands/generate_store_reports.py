# stores/management/commands/calculate_store_metrics.py
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


# stores/management/commands/cleanup_inventory_tracking.py
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


# stores/management/commands/update_store_commission_rates.py
from django.core.management.base import BaseCommand
from decimal import Decimal
from stores.models import Store


class Command(BaseCommand):
    help = 'Update commission rates for stores based on performance'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tier1-rate',
            type=float,
            default=3.0,
            help='Commission rate for top-performing stores (default: 3.0%)',
        )
        parser.add_argument(
            '--tier2-rate',
            type=float,
            default=5.0,
            help='Commission rate for medium-performing stores (default: 5.0%)',
        )
        parser.add_argument(
            '--tier3-rate',
            type=float,
            default=7.0,
            help='Commission rate for new/low-performing stores (default: 7.0%)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what changes would be made without applying them',
        )

    def handle(self, *args, **options):
        from orders.models import OrderItem
        from django.db.models import Sum, Count

        stores = Store.objects.filter(status='active')

        for store in stores:
            # Calculate store performance metrics
            thirty_days_ago = timezone.now() - timedelta(days=30)

            recent_orders = OrderItem.objects.filter(
                product__seller=store.owner,
                order__created_at__gte=thirty_days_ago,
                order__status='delivered'
            )

            total_revenue = recent_orders.aggregate(
                total=Sum('quantity') * Sum('price_at_time')
            )['total'] or 0

            order_count = recent_orders.values('order').distinct().count()

            # Determine tier based on performance
            if total_revenue >= 50000 and order_count >= 100:
                new_rate = Decimal(str(options['tier1_rate']))
                tier = 'Tier 1 (Top Performer)'
            elif total_revenue >= 10000 and order_count >= 20:
                new_rate = Decimal(str(options['tier2_rate']))
                tier = 'Tier 2 (Good Performer)'
            else:
                new_rate = Decimal(str(options['tier3_rate']))
                tier = 'Tier 3 (Standard)'

            if options['dry_run']:
                self.stdout.write(
                    f'{store.name}: {store.commission_rate}% → {new_rate}% ({tier})'
                )
            else:
                old_rate = store.commission_rate
                store.commission_rate = new_rate
                store.save(update_fields=['commission_rate'])

                if old_rate != new_rate:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'✓ Updated {store.name}: {old_rate}% → {new_rate}% ({tier})'
                        )
                    )
                else:
                    self.stdout.write(
                        f'= {store.name}: Rate unchanged at {new_rate}% ({tier})'
                    )


# stores/management/commands/generate_store_reports.py
from django.core.management.base import BaseCommand
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.conf import settings
from stores.models import Store, StoreMetrics
from datetime import datetime, timedelta
import csv
import io


class Command(BaseCommand):
    help = 'Generate and email store performance reports'

    def add_arguments(self, parser):
        parser.add_argument(
            '--period',
            choices=['weekly', 'monthly'],
            default='weekly',
            help='Report period (default: weekly)',
        )
        parser.add_argument(
            '--email-to',
            type=str,
            help='Email address to send reports to (default: admin emails)',
        )
        parser.add_argument(
            '--store-id',
            type=str,
            help='Generate report for specific store only',
        )

    def handle(self, *args, **options):
        if options['period'] == 'weekly':
            days = 7
            period_name = 'Weekly'
        else:
            days = 30
            period_name = 'Monthly'

        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days)

        # Get stores
        if options['store_id']:
            stores = Store.objects.filter(id=options['store_id'], status='active')
        else:
            stores = Store.objects.filter(status='active')

        # Generate CSV report
        csv_buffer = io.StringIO()
        csv_writer = csv.writer(csv_buffer)

        # CSV Headers
        csv_writer.writerow([
            'Store Name', 'Owner', 'Total Orders', 'Total Revenue',
            'Total Returns', 'Return Rate %', 'Avg Rating',
            'Low Stock Items', 'Out of Stock Items'
        ])

        report_data = []

        for store in stores:
            # Get metrics for the period
            metrics = StoreMetrics.objects.filter(
                store=store,
                date__gte=start_date,
                date__lte=end_date
            )

            # Aggregate metrics
            total_orders = sum(m.total_orders for m in metrics)
            total_revenue = sum(m.total_sales for m in metrics)
            total_returns = sum(m.total_returns for m in metrics)
            avg_return_rate = sum(m.return_rate_percentage for m in metrics) / len(metrics) if metrics else 0
            avg_rating = sum(m.average_rating for m in metrics) / len(metrics) if metrics else 0

            # Current stock status
            from marketplace.models import Product
            products = Product.objects.filter(seller=store.owner)
            low_stock = products.filter(stock__quantity__lte=10, stock__quantity__gt=0).count()
            out_of_stock = products.filter(stock__quantity=0).count()

            store_data = {
                'store': store,
                'total_orders': total_orders,
                'total_revenue': total_revenue,
                'total_returns': total_returns,
                'return_rate': avg_return_rate,
                'avg_rating': avg_rating,
                'low_stock': low_stock,
                'out_of_stock': out_of_stock,
            }

            report_data.append(store_data)

            # Add to CSV
            csv_writer.writerow([
                store.name,
                store.owner.get_full_name() or store.owner.username,
                total_orders,
                f'{total_revenue:.2f}',
                total_returns,
                f'{avg_return_rate:.2f}',
                f'{avg_rating:.2f}',
                low_stock,
                out_of_stock,
            ])

        # Generate HTML report
        html_content = render_to_string('stores/admin/store_report_email.html', {
            'period_name': period_name,
            'start_date': start_date,
            'end_date': end_date,
            'stores_data': report_data,
            'total_stores': len(report_data),
        })

        # Send email
        subject = f'{period_name} Store Performance Report - {end_date}'

        email_recipients = []
        if options['email_to']:
            email_recipients.append(options['email_to'])
        else:
            email_recipients = [admin[1] for admin in settings.ADMINS]

        if email_recipients:
            email = EmailMessage(
                subject=subject,
                body=html_content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=email_recipients,
            )
            email.content_subtype = 'html'

            # Attach CSV report
            csv_content = csv_buffer.getvalue()
            email.attach(
                f'store_report_{start_date}_to_{end_date}.csv',
                csv_content,
                'text/csv'
            )

            email.send()

            self.stdout.write(
                self.style.SUCCESS(
                    f'Report sent to {", ".join(email_recipients)}'
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING('No email recipients configured')
            )

        self.stdout.write(
            self.style.SUCCESS(
                f'{period_name} report generated for {len(report_data)} stores'
            )
        )
