from django.core.management.base import BaseCommand
from django.db.models import Count, Avg
from stores.models import Store, StoreFollow, StoreNotification


class Command(BaseCommand):
    help = 'Display store following statistics'

    def handle(self, *args, **options):
        # Overall statistics
        total_stores = Store.objects.count()
        stores_with_followers = Store.objects.annotate(
            follower_count=Count('followers', filter=models.Q(followers__is_active=True))
        ).filter(follower_count__gt=0).count()

        total_follows = StoreFollow.objects.filter(is_active=True).count()
        total_notifications = StoreNotification.objects.count()

        # Top followed stores
        top_stores = Store.objects.annotate(
            follower_count=Count('followers', filter=models.Q(followers__is_active=True))
        ).order_by('-follower_count')[:10]

        # Average followers per store
        avg_followers = StoreFollow.objects.filter(is_active=True).values('store').annotate(
            count=Count('id')
        ).aggregate(avg=Avg('count'))['avg'] or 0

        self.stdout.write(self.style.SUCCESS('=== Store Following Statistics ==='))
        self.stdout.write(f'Total Stores: {total_stores}')
        self.stdout.write(f'Stores with Followers: {stores_with_followers}')
        self.stdout.write(f'Total Active Follows: {total_follows}')
        self.stdout.write(f'Total Notifications: {total_notifications}')
        self.stdout.write(f'Average Followers per Store: {avg_followers:.2f}')

        self.stdout.write('\n=== Top 10 Most Followed Stores ===')
        for i, store in enumerate(top_stores, 1):
            self.stdout.write(f'{i}. {store.name}: {store.follower_count} followers')