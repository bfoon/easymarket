from django.core.management.base import BaseCommand
from django.db import connection
from marketplace.models import Product, SearchHistory, PopularSearch


class Command(BaseCommand):
    help = 'Update search indexes and clean old search history'

    def handle(self, *args, **options):
        # Clean old search history (older than 30 days)
        from datetime import datetime, timedelta
        cutoff_date = datetime.now() - timedelta(days=30)

        old_searches = SearchHistory.objects.filter(timestamp__lt=cutoff_date)
        deleted_count = old_searches.count()
        old_searches.delete()

        self.stdout.write(
            self.style.SUCCESS(f'Cleaned {deleted_count} old search records')
        )

        # Update popular searches based on recent activity
        recent_searches = SearchHistory.objects.filter(
            timestamp__gte=cutoff_date
        ).values_list('query', flat=True)

        # Count occurrences and update popular searches
        from collections import Counter
        query_counts = Counter(recent_searches)

        for query, count in query_counts.most_common(50):
            popular_search, created = PopularSearch.objects.get_or_create(
                query=query,
                defaults={'search_count': count}
            )
            if not created:
                popular_search.search_count = count
                popular_search.save()

        self.stdout.write(
            self.style.SUCCESS('Updated popular searches')
        )

        # Optimize database
        with connection.cursor() as cursor:
            cursor.execute("ANALYZE;")

        self.stdout.write(
            self.style.SUCCESS('Database optimization completed')
        )