from django.core.management.base import BaseCommand
from django.utils import timezone
from auction.models import Auction


class Command(BaseCommand):
    help = 'End auctions that have passed their end date'

    def handle(self, *args, **options):
        ended_auctions = Auction.objects.filter(
            status='active',
            end_date__lte=timezone.now()
        )

        count = 0
        for auction in ended_auctions:
            auction.status = 'ended'
            auction.save()

            # Create order for winner if exists
            if auction.winner:
                auction.create_order_for_winner()

            count += 1

        self.stdout.write(
            self.style.SUCCESS(f'Successfully ended {count} auctions')
        )