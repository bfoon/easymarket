# management/commands/cleanup_google_apps.py
from django.core.management.base import BaseCommand
from allauth.socialaccount.models import SocialApp
from django.contrib.sites.models import Site


class Command(BaseCommand):
    help = 'Clean up duplicate Google SocialApp entries'

    def handle(self, *args, **options):
        current_site = Site.objects.get_current()

        # Get all Google apps for current site
        google_apps = SocialApp.objects.filter(
            provider="google",
            sites=current_site
        )

        self.stdout.write(f"Found {google_apps.count()} Google SocialApp entries")

        if google_apps.count() > 1:
            self.stdout.write("Multiple Google apps found:")
            for i, app in enumerate(google_apps):
                self.stdout.write(f"  {i + 1}. ID: {app.id}, Name: {app.name}, Client ID: {app.client_id}")

            # Keep the first one, remove others
            keep_app = google_apps.first()
            duplicate_apps = google_apps.exclude(id=keep_app.id)

            if input("Remove duplicates? (y/n): ").lower() == 'y':
                count = duplicate_apps.count()
                duplicate_apps.delete()
                self.stdout.write(
                    self.style.SUCCESS(f"Removed {count} duplicate Google SocialApp entries")
                )
                self.stdout.write(f"Kept: {keep_app.name} (ID: {keep_app.id})")

        elif google_apps.count() == 0:
            self.stdout.write(
                self.style.WARNING("No Google SocialApp found for current site")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("Single Google SocialApp found - configuration is correct")
            )