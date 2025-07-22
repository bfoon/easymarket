from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.utils import timezone
from datetime import timedelta
from auction.models import Auction, Watchlist


class Command(BaseCommand):
    help = 'Send auction ending notifications'

    def handle(self, *args, **options):
        # Auctions ending in 1 hour
        ending_soon = timezone.now() + timedelta(hours=1)
        auctions_ending = Auction.objects.filter(
            status='active',
            end_date__lte=ending_soon,
            end_date__gt=timezone.now()
        )

        for auction in auctions_ending:
            # Notify watchers
            watchers = Watchlist.objects.filter(
                auction=auction,
                notify_ending=True
            ).select_related('user')

            for watcher in watchers:
                self.send_ending_notification(watcher.user, auction)

        self.stdout.write(
            self.style.SUCCESS(f'Sent notifications for {auctions_ending.count()} auctions')
        )

    def send_ending_notification(self, user, auction):
        """Send auction ending notification"""
        if not user.email:
            return

        subject = f'Auction ending soon: {auction.title}'
        message = f'''
        The auction "{auction.title}" is ending in less than 1 hour.

        Current bid: ${auction.current_price}
        Time remaining: {auction.time_remaining}
        Store: {auction.store.name}

        Place your bid now: http://yourdomain.com{auction.get_absolute_url()}
        '''

        try:
            send_mail(
                subject,
                message,
                'noreply@easymarket.com',
                [user.email],
                fail_silently=True,
            )
        except Exception:
            pass  # Fail silently for email errors