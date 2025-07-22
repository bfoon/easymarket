from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.core.mail import send_mail
from django.conf import settings
from .models import Auction, Bid


@receiver(post_save, sender=Bid)
def handle_new_bid(sender, instance, created, **kwargs):
    """Handle new bid placement"""
    if created:
        auction = instance.auction

        # Auto-extend auction if needed
        from datetime import timedelta
        if auction.auto_extend and auction.end_date - timezone.now() <= timedelta(minutes=5):
            auction.end_date = timezone.now() + timedelta(minutes=5)
            auction.save(update_fields=['end_date'])

        # Create chat message notification (optional)
        # You could create a notification system here


@receiver(pre_save, sender=Auction)
def handle_auction_status_change(sender, instance, **kwargs):
    """Handle auction status changes"""
    if instance.pk:
        old_instance = Auction.objects.get(pk=instance.pk)

        # If auction just ended
        if old_instance.status != instance.status and instance.status == 'ended':
            # Auto-create order if there's a winner
            if instance.winner:
                instance.create_order_for_winner()