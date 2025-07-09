from .models import Review
from django.db.models import Avg, Count

def global_review_stats(request):
    stats = Review.objects.aggregate(
        total_reviews=Count('id'),
        average_rating=Avg('rating')
    )
    return {
        'review_count': stats['total_reviews'] or 0,
        'average_rating': round(stats['average_rating'], 1) if stats['average_rating'] else None
    }
