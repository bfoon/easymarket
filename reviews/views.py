from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.db.models import Avg, Count
from django.core.paginator import Paginator
from django.template.loader import render_to_string
from django.conf import settings
from django.contrib.auth import get_user_model

from .models import Review, Comment
from marketplace.models import Product

User = get_user_model()


@login_required
@require_POST
def submit_review(request):
    product_id = request.POST.get('product_id')
    rating = request.POST.get('rating')
    comment = request.POST.get('comment', '')

    # Validation
    if not product_id or not rating:
        return JsonResponse({'success': False, 'error': 'Product ID and rating are required'})

    try:
        rating = int(rating)
        if rating < 1 or rating > 5:
            return JsonResponse({'success': False, 'error': 'Rating must be between 1 and 5'})
    except ValueError:
        return JsonResponse({'success': False, 'error': 'Invalid rating value'})

    product = get_object_or_404(Product, id=product_id)

    # Create or update review
    review, created = Review.objects.update_or_create(
        user=request.user,
        product=product,
        defaults={'rating': rating, 'comment': comment}
    )

    # Calculate new statistics
    stats = product.reviews.aggregate(
        avg_rating=Avg('rating'),
        total_reviews=Count('id')
    )

    new_avg = stats['avg_rating'] or 0
    total_reviews = stats['total_reviews'] or 0

    # Generate star HTML
    stars_html = generate_stars_html(new_avg)

    return JsonResponse({
        'success': True,
        'created': created,
        'new_avg': round(new_avg, 1),
        'total_reviews': total_reviews,
        'stars_html': stars_html,
        'review_id': review.id,
        'message': 'Review submitted successfully!' if created else 'Review updated successfully!'
    })


@login_required
@require_POST
def delete_review(request):
    review_id = request.POST.get('review_id')

    if not review_id:
        return JsonResponse({'success': False, 'error': 'Review ID is required'})

    try:
        review = Review.objects.get(id=review_id, user=request.user)
        product = review.product
        review.delete()

        # Recalculate statistics
        stats = product.reviews.aggregate(
            avg_rating=Avg('rating'),
            total_reviews=Count('id')
        )

        new_avg = stats['avg_rating'] or 0
        total_reviews = stats['total_reviews'] or 0
        stars_html = generate_stars_html(new_avg)

        return JsonResponse({
            'success': True,
            'new_avg': round(new_avg, 1),
            'total_reviews': total_reviews,
            'stars_html': stars_html,
            'message': 'Review deleted successfully!'
        })

    except Review.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Review not found or you do not have permission to delete it'})


@login_required
@require_POST
def submit_comment(request):
    review_id = request.POST.get('review_id')
    content = request.POST.get('content', '').strip()

    if not review_id or not content:
        return JsonResponse({'success': False, 'error': 'Review ID and content are required'})

    try:
        review = Review.objects.get(id=review_id)
        comment = Comment.objects.create(
            user=request.user,
            review=review,
            content=content
        )

        # Generate comment HTML
        comment_html = render_to_string('reviews/comment_item.html', {
            'comment': comment,
            'user': request.user
        })

        return JsonResponse({
            'success': True,
            'comment_html': comment_html,
            'comment_id': comment.id,
            'message': 'Comment added successfully!'
        })

    except Review.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Review not found'})


@login_required
@require_POST
def delete_comment(request):
    comment_id = request.POST.get('comment_id')

    if not comment_id:
        return JsonResponse({'success': False, 'error': 'Comment ID is required'})

    try:
        comment = Comment.objects.get(id=comment_id, user=request.user)
        comment.delete()

        return JsonResponse({
            'success': True,
            'message': 'Comment deleted successfully!'
        })

    except Comment.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Comment not found or you do not have permission to delete it'})


def load_reviews(request, product_id):
    """Load reviews via AJAX for pagination"""
    product = get_object_or_404(Product, id=product_id)
    page = request.GET.get('page', 1)

    reviews = Review.objects.filter(product=product).select_related('user').prefetch_related('comments__user')
    paginator = Paginator(reviews, 5)  # 5 reviews per page
    reviews_page = paginator.get_page(page)

    reviews_html = render_to_string('reviews/reviews_list.html', {
        'reviews': reviews_page,
        'user': request.user,
        'rating_range': range(1, 6)
    })

    return JsonResponse({
        'success': True,
        'reviews_html': reviews_html,
        'has_next': reviews_page.has_next(),
        'has_previous': reviews_page.has_previous(),
        'current_page': reviews_page.number,
        'total_pages': paginator.num_pages
    })


def generate_stars_html(rating):
    """Generate HTML for star display"""
    stars = []
    for i in range(1, 6):
        if rating >= i:
            stars.append('<i class="fas fa-star"></i>')
        elif rating >= i - 0.5:
            stars.append('<i class="fas fa-star-half-alt"></i>')
        else:
            stars.append('<i class="far fa-star"></i>')
    return ''.join(stars)



