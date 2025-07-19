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