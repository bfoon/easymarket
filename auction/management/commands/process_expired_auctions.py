from django.core.management.base import BaseCommand
from django.utils import timezone
from auction.models import Auction


class Command(BaseCommand):
    help = 'Process expired auctions and assign winners'

    def handle(self, *args, **options):
        # Find active auctions that have ended but no winner assigned
        expired_auctions = Auction.objects.filter(
            status='active',
            end_date__lte=timezone.now(),
            winner__isnull=True
        )

        processed_count = 0
        for auction in expired_auctions:
            auction.assign_winner_if_expired()
            processed_count += 1
            self.stdout.write(
                self.style.SUCCESS(f'Processed auction: {auction.title}')
            )

        self.stdout.write(
            self.style.SUCCESS(f'Successfully processed {processed_count} expired auctions')
        )