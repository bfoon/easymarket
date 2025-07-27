from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from stores.models import StoreNotification
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Send pending store notifications to users'

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help='Number of notifications to process at once'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be sent without actually sending'
        )

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        dry_run = options['dry_run']

        # Get unsent notifications
        notifications = StoreNotification.objects.filter(
            is_sent=False
        ).select_related('user', 'store', 'product')[:batch_size]

        if not notifications:
            self.stdout.write(
                self.style.SUCCESS('No pending notifications to send.')
            )
            return

        sent_count = 0
        error_count = 0

        for notification in notifications:
            try:
                if dry_run:
                    self.stdout.write(f"Would send: {notification.title} to {notification.user.email}")
                else:
                    self.send_notification_email(notification)
                    notification.is_sent = True
                    notification.save()
                    sent_count += 1

            except Exception as e:
                logger.error(f"Failed to send notification {notification.id}: {str(e)}")
                error_count += 1

        if dry_run:
            self.stdout.write(
                self.style.WARNING(f'Dry run completed. Would send {len(notifications)} notifications.')
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully sent {sent_count} notifications. {error_count} errors.'
                )
            )

    def send_notification_email(self, notification):
        """Send email notification to user"""
        subject = f"[{notification.store.name}] {notification.title}"

        context = {
            'notification': notification,
            'store': notification.store,
            'user': notification.user,
            'product': notification.product,
        }

        # Render email templates
        html_message = render_to_string('emails/store_notification.html', context)
        text_message = render_to_string('emails/store_notification.txt', context)

        send_mail(
            subject=subject,
            message=text_message,
            html_message=html_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[notification.user.email],
            fail_silently=False
        )