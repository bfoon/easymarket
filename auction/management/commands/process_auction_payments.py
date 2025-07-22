from django.core.management.base import BaseCommand
from django.utils import timezone
from auction.models import Auction


class Command(BaseCommand):
    help = 'Process payments for completed auctions'

    def handle(self, *args, **options):
        # Get auctions that ended with winners but no order created
        completed_auctions = Auction.objects.filter(
            status='ended',
            winner__isnull=False,
            order__isnull=True
        )

        for auction in completed_auctions:
            try:
                order = auction.create_order_for_winner()
                if order:
                    self.stdout.write(
                        self.style.SUCCESS(f'Created order {order.id} for auction {auction.id}')
                    )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'Failed to create order for auction {auction.id}: {e}')
                )
