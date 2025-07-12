from django.shortcuts import render, get_object_or_404, redirect
from unicodedata import category

from .models import (Category, Product, ProductView,
                     CartItem, Cart, CelebrityFeature, Wishlist,
                     SearchHistory, PopularSearch, ProductFeature,
                     ProductFeatureOption, ProductVariant)
from chat.models import ChatThread, ChatMessage
from accounts.models import Address
from stores.models import Store
from reviews.models import Review
from orders.models import PromoCode
from reviews.forms import ReviewForm
from django.contrib.auth import get_user_model
import re
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from decimal import Decimal
from django.core.cache import cache
from .utils import log_search, get_search_suggestions_with_history
from django.urls import reverse
import json
from datetime import timedelta
from django.utils import timezone
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q, Count, F, Sum, Avg
from decimal import Decimal
from django.contrib import messages
from collections import Counter

# Get the custom User model
User = get_user_model()

# Create your views here!

def all_products(request):
    parent_categories = Category.objects.filter(parent__isnull=True, is_active=True)
    category_products = []

    for category in parent_categories:
        # Get all subcategories recursively
        all_subcategories = category.get_all_subcategories()
        related_category_ids = [category.id] + [sub.id for sub in all_subcategories]

        # Fetch products from parent and subcategories
        products = Product.objects.filter(
            category_id__in=related_category_ids,
            category__is_active=True
        ).order_by('?')[:8]

        if products.exists():
            category_products.append({
                'category': category,
                'products': products,
                'subcategories': all_subcategories  # Optional for template use
            })

    return render(request, 'marketplace/all_products.html', {
        'category_products': category_products
    })


def product_list(request):
    categories = Category.objects.filter(parent__isnull=True)[:6]  # Only parent categories
    products = Product.objects.all()
    featured_products = Product.objects.filter(is_featured=True)[:6]
    trending_products = Product.objects.filter(is_trending=True)

    recently_viewed = []
    similar_items = []
    recommended_products = []

    # Handle logged-in user
    if request.user.is_authenticated:
        recently_viewed = Product.objects.filter(productview__user=request.user).distinct().order_by(
            '-productview__viewed_at')[:8]
    else:
        session_recently_viewed = request.session.get('recently_viewed', [])
        recently_viewed = Product.objects.filter(id__in=session_recently_viewed)

    # Similar items logic - consider main category and its subcategories
    if recently_viewed:
        last_viewed_product = recently_viewed.first()

        # Determine main category
        if last_viewed_product.category:
            main_category = last_viewed_product.category.parent or last_viewed_product.category

            # Get IDs of main category and its subcategories
            related_category_ids = [main_category.id] + list(main_category.children.values_list('id', flat=True))

            similar_items = Product.objects.filter(
                category_id__in=related_category_ids
            ).exclude(id=last_viewed_product.id)[:8]

    # Generate personalized recommendations
    recommended_products = generate_recommendations(request, recently_viewed)

    return render(request, 'marketplace/product_list.html', {
        'categories': categories,
        'featured_products': featured_products,
        'trending_products': trending_products,
        'products': products,
        'recently_viewed': recently_viewed,
        'similar_items': similar_items,
        'recommended_products': recommended_products,
    })


def generate_recommendations(request, recently_viewed):
    """
    Generate personalized product recommendations based on user behavior
    """
    recommended_products = []

    if request.user.is_authenticated:
        # For authenticated users, use comprehensive recommendation logic
        recommended_products = get_authenticated_user_recommendations(request.user, recently_viewed)
    else:
        # For anonymous users, use session-based recommendations
        recommended_products = get_anonymous_user_recommendations(request, recently_viewed)

    return recommended_products[:12]  # Limit to 12 recommendations


def get_authenticated_user_recommendations(user, recently_viewed):
    """
    Generate recommendations for authenticated users based on multiple factors
    """
    recommendations = []

    # 1. Category-based recommendations (40% weight)
    category_recommendations = get_category_based_recommendations(user, recently_viewed)
    recommendations.extend(category_recommendations[:5])

    # 2. Collaborative filtering - users who viewed similar products (30% weight)
    collaborative_recommendations = get_collaborative_recommendations(user, recently_viewed)
    recommendations.extend(collaborative_recommendations[:4])

    # 3. Price range preferences (15% weight)
    price_recommendations = get_price_based_recommendations(user, recently_viewed)
    recommendations.extend(price_recommendations[:2])

    # 4. Trending products in user's preferred categories (10% weight)
    trending_recommendations = get_trending_category_recommendations(user, recently_viewed)
    recommendations.extend(trending_recommendations[:1])

    # 5. Wishlist-based recommendations (5% weight)
    wishlist_recommendations = get_wishlist_based_recommendations(user)
    recommendations.extend(wishlist_recommendations[:1])

    # Remove duplicates while preserving order
    seen = set()
    unique_recommendations = []
    for product in recommendations:
        if product.id not in seen:
            seen.add(product.id)
            unique_recommendations.append(product)

    return unique_recommendations


def get_anonymous_user_recommendations(request, recently_viewed):
    """
    Generate recommendations for anonymous users based on session data
    """
    recommendations = []

    if recently_viewed:
        # 1. Category-based recommendations
        category_ids = [p.category.id for p in recently_viewed if p.category]
        if category_ids:
            category_recommendations = Product.objects.filter(
                category_id__in=category_ids
            ).exclude(
                id__in=[p.id for p in recently_viewed]
            ).annotate(
                avg_rating=Avg('reviews__rating')
            ).order_by('-avg_rating', '-created_at')[:8]
            recommendations.extend(category_recommendations)

        # 2. Price range recommendations
        price_range = calculate_price_range(recently_viewed)
        if price_range:
            price_recommendations = Product.objects.filter(
                price__range=price_range
            ).exclude(
                id__in=[p.id for p in recently_viewed]
            ).order_by('-is_trending', '-created_at')[:4]
            recommendations.extend(price_recommendations)

    # 3. Fallback to popular products
    if len(recommendations) < 8:
        popular_products = Product.objects.annotate(
            view_count=Count('productview'),
            avg_rating=Avg('reviews__rating')
        ).order_by('-view_count', '-avg_rating')[:12]
        recommendations.extend(popular_products)

    # Remove duplicates
    seen = set()
    unique_recommendations = []
    for product in recommendations:
        if product.id not in seen:
            seen.add(product.id)
            unique_recommendations.append(product)

    return unique_recommendations


def get_category_based_recommendations(user, recently_viewed):
    """
    Recommend products based on user's category preferences
    """
    # Get user's most viewed categories
    user_categories = ProductView.objects.filter(
        user=user
    ).values('product__category').annotate(
        view_count=Count('id')
    ).order_by('-view_count')[:5]

    category_ids = [cat['product__category'] for cat in user_categories if cat['product__category']]

    if not category_ids:
        return []

    # Get highly rated products from preferred categories
    recommendations = Product.objects.filter(
        category_id__in=category_ids
    ).exclude(
        id__in=[p.id for p in recently_viewed] if recently_viewed else []
    ).annotate(
        avg_rating=Avg('reviews__rating'),
        review_count=Count('reviews')
    ).filter(
        avg_rating__gte=4.0,
        review_count__gte=5
    ).order_by('-avg_rating', '-review_count')

    return list(recommendations)


def get_collaborative_recommendations(user, recently_viewed):
    """
    Collaborative filtering - recommend products viewed by similar users
    """
    if not recently_viewed:
        return []

    # Find users who viewed similar products
    similar_users = User.objects.filter(
        productview__product__in=recently_viewed
    ).exclude(
        id=user.id
    ).annotate(
        common_views=Count('productview')
    ).filter(
        common_views__gte=2
    ).order_by('-common_views')[:10]

    # Get products viewed by similar users
    collaborative_products = Product.objects.filter(
        productview__user__in=similar_users
    ).exclude(
        id__in=[p.id for p in recently_viewed]
    ).annotate(
        similarity_score=Count('productview__user', distinct=True)
    ).order_by('-similarity_score')

    return list(collaborative_products)


def get_price_based_recommendations(user, recently_viewed):
    """
    Recommend products based on user's price preferences
    """
    if not recently_viewed:
        return []

    # Calculate user's average price preference
    user_price_range = calculate_price_range(recently_viewed)

    if not user_price_range:
        return []

    # Find products in similar price range
    price_recommendations = Product.objects.filter(
        price__range=user_price_range
    ).exclude(
        id__in=[p.id for p in recently_viewed]
    ).annotate(
        avg_rating=Avg('reviews__rating')
    ).order_by('-avg_rating', '-created_at')

    return list(price_recommendations)


def get_trending_category_recommendations(user, recently_viewed):
    """
    Get trending products from user's preferred categories
    """
    if not recently_viewed:
        return []

    # Get categories from recently viewed products
    category_ids = [p.category.id for p in recently_viewed if p.category]

    if not category_ids:
        return []

    # Get trending products from these categories
    trending_recommendations = Product.objects.filter(
        category_id__in=category_ids,
        is_trending=True
    ).exclude(
        id__in=[p.id for p in recently_viewed]
    ).order_by('-created_at')

    return list(trending_recommendations)


def get_wishlist_based_recommendations(user):
    """
    Recommend products similar to items in user's wishlist
    """
    try:
        # Assuming you have a Wishlist model
        wishlist_items = Wishlist.objects.filter(user=user).values_list('product', flat=True)

        if not wishlist_items:
            return []

        # Get categories from wishlist items
        wishlist_categories = Product.objects.filter(
            id__in=wishlist_items
        ).values_list('category', flat=True)

        # Recommend similar products
        wishlist_recommendations = Product.objects.filter(
            category__in=wishlist_categories
        ).exclude(
            id__in=wishlist_items
        ).annotate(
            avg_rating=Avg('reviews__rating')
        ).order_by('-avg_rating')

        return list(wishlist_recommendations)
    except:
        # If Wishlist model doesn't exist, return empty list
        return []


def calculate_price_range(products):
    """
    Calculate price range based on user's viewing history
    """
    if not products:
        return None

    prices = [p.price for p in products if p.price]

    if not prices:
        return None

    # Convert to Decimal for consistent decimal arithmetic
    min_price = min(prices)
    max_price = max(prices)
    avg_price = sum(prices) / len(prices)

    # Create a range around the average price (±30%)
    # Use Decimal for arithmetic operations
    range_min = max(min_price, avg_price * Decimal('0.7'))
    range_max = min(max_price, avg_price * Decimal('1.3'))

    return (range_min, range_max)


# Additional helper view for AJAX recommendations
def get_more_recommendations(request):
    """
    API endpoint to fetch more recommendations via AJAX
    """
    from django.http import JsonResponse

    if request.method == 'GET':
        page = int(request.GET.get('page', 1))
        per_page = int(request.GET.get('per_page', 8))

        # Get recently viewed for context
        recently_viewed = []
        if request.user.is_authenticated:
            recently_viewed = Product.objects.filter(
                productview__user=request.user
            ).distinct().order_by('-productview__viewed_at')[:5]

        # Generate recommendations
        all_recommendations = generate_recommendations(request, recently_viewed)

        # Paginate
        start = (page - 1) * per_page
        end = start + per_page
        recommendations = all_recommendations[start:end]

        # Serialize data
        data = []
        for product in recommendations:
            data.append({
                'id': product.id,
                'name': product.name,
                'price': str(product.price),
                'image_url': product.image.url if product.image else '',
                'url': f'/products/{product.id}/',
                'rating': product.average_rating if hasattr(product, 'average_rating') else 0,
                'is_trending': product.is_trending,
                'discount_percentage': product.discount_percentage if hasattr(product, 'discount_percentage') else 0,
            })

        return JsonResponse({
            'recommendations': data,
            'has_more': len(all_recommendations) > end
        })

    return JsonResponse({'error': 'Invalid request'}, status=400)


def recommended_products_view(request):
    """
    Dedicated view for the "Recommended for You" page
    """
    # Get recently viewed products for context
    recently_viewed = []
    if request.user.is_authenticated:
        recently_viewed = Product.objects.filter(
            productview__user=request.user
        ).distinct().order_by('-productview__viewed_at')[:10]
    else:
        session_recently_viewed = request.session.get('recently_viewed', [])
        recently_viewed = Product.objects.filter(id__in=session_recently_viewed)

    # Generate comprehensive recommendations
    all_recommendations = generate_comprehensive_recommendations(request, recently_viewed)

    # Pagination
    page = request.GET.get('page', 1)
    paginator = Paginator(all_recommendations, 24)  # 24 products per page
    recommended_products = paginator.get_page(page)

    # Get recommendation insights for the user
    recommendation_insights = get_recommendation_insights(request, recently_viewed)

    context = {
        'recommended_products': recommended_products,
        'recently_viewed': recently_viewed,
        'recommendation_insights': recommendation_insights,
        'total_recommendations': len(all_recommendations),
        'page_title': 'Recommended for You',
    }

    # Return JSON for AJAX requests
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'products': serialize_products(recommended_products),
            'has_next': recommended_products.has_next(),
            'has_previous': recommended_products.has_previous(),
            'current_page': recommended_products.number,
            'total_pages': paginator.num_pages,
        })

    return render(request, 'marketplace/recommended_products.html', context)


def generate_comprehensive_recommendations(request, recently_viewed):
    """
    Generate a comprehensive list of recommendations for the dedicated page
    """
    all_recommendations = []

    if request.user.is_authenticated:
        # For authenticated users - more sophisticated recommendations
        recommendations = get_authenticated_comprehensive_recommendations(request.user, recently_viewed)
    else:
        # For anonymous users - session-based recommendations
        recommendations = get_anonymous_comprehensive_recommendations(request, recently_viewed)

    return recommendations


def get_authenticated_comprehensive_recommendations(user, recently_viewed):
    """
    Comprehensive recommendations for authenticated users
    """
    recommendations = []

    # 1. Personal category preferences (30%)
    category_recs = get_enhanced_category_recommendations(user, recently_viewed)
    recommendations.extend(category_recs[:12])

    # 2. Collaborative filtering - similar users (25%)
    collaborative_recs = get_enhanced_collaborative_recommendations(user, recently_viewed)
    recommendations.extend(collaborative_recs[:10])

    # 3. Price preference matching (20%)
    price_recs = get_enhanced_price_recommendations(user, recently_viewed)
    recommendations.extend(price_recs[:8])

    # 4. Trending in preferred categories (15%)
    trending_recs = get_trending_category_recommendations(user, recently_viewed)
    recommendations.extend(trending_recs[:6])

    # 5. High-rated products in browsed categories (10%)
    quality_recs = get_quality_recommendations(user, recently_viewed)
    recommendations.extend(quality_recs[:4])

    # Remove duplicates and recently viewed
    viewed_ids = [p.id for p in recently_viewed] if recently_viewed else []
    unique_recommendations = remove_duplicates(recommendations, viewed_ids)

    # If we don't have enough recommendations, add fallback products
    if len(unique_recommendations) < 30:
        fallback_recs = get_fallback_recommendations(user, viewed_ids, 30 - len(unique_recommendations))
        unique_recommendations.extend(fallback_recs)

    return unique_recommendations[:48]  # Limit to 48 products for performance


def get_anonymous_comprehensive_recommendations(request, recently_viewed):
    """
    Comprehensive recommendations for anonymous users
    """
    recommendations = []
    viewed_ids = [p.id for p in recently_viewed] if recently_viewed else []

    if recently_viewed:
        # 1. Category-based recommendations (40%)
        category_ids = list(set([p.category.id for p in recently_viewed if p.category]))
        if category_ids:
            category_recs = Product.objects.filter(
                category_id__in=category_ids
            ).exclude(id__in=viewed_ids).order_by('-created_at')[:16]
            recommendations.extend(category_recs)

        # 2. Price range recommendations (30%)
        price_range = calculate_price_range(recently_viewed)
        if price_range:
            price_recs = Product.objects.filter(
                price__range=price_range
            ).exclude(id__in=viewed_ids).order_by('-is_trending')[:12]
            recommendations.extend(price_recs)

        # 3. Similar products (30%)
        similar_recs = get_similar_products_anonymous(recently_viewed, viewed_ids)
        recommendations.extend(similar_recs[:12])

    # Fallback to popular and trending products
    popular_recs = Product.objects.annotate(
        view_count=Count('productview')
    ).exclude(id__in=viewed_ids).order_by('-view_count', '-created_at')[:20]
    recommendations.extend(popular_recs)

    return remove_duplicates(recommendations, viewed_ids)[:48]


def get_enhanced_category_recommendations(user, recently_viewed):
    """
    Enhanced category-based recommendations
    """
    # Get user's category preferences with weights
    category_stats = ProductView.objects.filter(
        user=user,
        viewed_at__gte=timezone.now() - timedelta(days=90)
    ).values('product__category__name', 'product__category').annotate(
        view_count=Count('id'),
        recent_views=Count('id', filter=Q(viewed_at__gte=timezone.now() - timedelta(days=30)))
    ).order_by('-view_count')[:10]

    recommendations = []
    for stat in category_stats:
        if stat['product__category']:
            try:
                category_products = Product.objects.filter(
                    category_id=stat['product__category']
                ).annotate(
                    avg_rating=Avg('reviews__rating'),
                    review_count=Count('reviews')
                ).filter(
                    avg_rating__gte=3.5
                ).order_by('-avg_rating', '-review_count')[:5]
                recommendations.extend(category_products)
            except:
                # Fallback without reviews
                category_products = Product.objects.filter(
                    category_id=stat['product__category']
                ).order_by('-created_at')[:5]
                recommendations.extend(category_products)

    return recommendations


def get_enhanced_collaborative_recommendations(user, recently_viewed):
    """
    Enhanced collaborative filtering
    """
    if not recently_viewed:
        return []

    # Find users with similar viewing patterns
    similar_users = User.objects.filter(
        productview__product__in=recently_viewed
    ).exclude(id=user.id).annotate(
        common_products=Count('productview__product', distinct=True),
        total_views=Count('productview')
    ).filter(common_products__gte=2).order_by('-common_products')[:20]

    # Get their recently viewed products
    collaborative_products = Product.objects.filter(
        productview__user__in=similar_users,
        productview__viewed_at__gte=timezone.now() - timedelta(days=60)
    ).exclude(
        id__in=[p.id for p in recently_viewed]
    ).annotate(
        similarity_score=Count('productview__user', distinct=True)
    ).order_by('-similarity_score', '-created_at')

    return list(collaborative_products)


def get_enhanced_price_recommendations(user, recently_viewed):
    """
    Enhanced price-based recommendations
    """
    # Get user's purchase history if available
    try:
        # Try to get actual purchase data
        from orders.models import OrderItem
        purchase_prices = OrderItem.objects.filter(
            order__user=user,
            order__created_at__gte=timezone.now() - timedelta(days=180)
        ).values_list('price', flat=True)

        if purchase_prices:
            avg_purchase_price = sum(purchase_prices) / len(purchase_prices)
            price_range = (
                avg_purchase_price * Decimal('0.6'),
                avg_purchase_price * Decimal('1.4')
            )
        else:
            price_range = calculate_price_range(recently_viewed)
    except:
        # Fallback to viewing history
        price_range = calculate_price_range(recently_viewed)

    if not price_range:
        return []

    return list(Product.objects.filter(
        price__range=price_range
    ).order_by('-is_trending', '-created_at'))


def get_quality_recommendations(user, recently_viewed):
    """
    Get high-quality products from user's preferred categories
    """
    if not recently_viewed:
        return []

    category_ids = [p.category.id for p in recently_viewed if p.category]

    try:
        quality_products = Product.objects.filter(
            category_id__in=category_ids
        ).annotate(
            avg_rating=Avg('reviews__rating'),
            review_count=Count('reviews')
        ).filter(
            avg_rating__gte=4.5,
            review_count__gte=10
        ).order_by('-avg_rating', '-review_count')

        return list(quality_products)
    except:
        return []


def get_similar_products_anonymous(recently_viewed, viewed_ids):
    """
    Get similar products for anonymous users
    """
    if not recently_viewed:
        return []

    # Get products from same categories
    category_ids = [p.category.id for p in recently_viewed if p.category]

    similar_products = Product.objects.filter(
        category_id__in=category_ids
    ).exclude(id__in=viewed_ids).order_by('?')  # Random order for variety

    return list(similar_products)


def get_fallback_recommendations(user, excluded_ids, count):
    """
    Fallback recommendations when we don't have enough personalized ones
    """
    return list(Product.objects.exclude(
        id__in=excluded_ids
    ).annotate(
        popularity_score=Count('productview') + Count('reviews') * 2
    ).order_by('-popularity_score', '-created_at')[:count])


def remove_duplicates(recommendations, excluded_ids):
    """
    Remove duplicate products and excluded IDs
    """
    seen = set(excluded_ids)
    unique_recommendations = []

    for product in recommendations:
        if product.id not in seen:
            seen.add(product.id)
            unique_recommendations.append(product)

    return unique_recommendations


def get_recommendation_insights(request, recently_viewed):
    """
    Get insights about why products are recommended
    """
    insights = {
        'total_categories_viewed': 0,
        'primary_category': None,
        'avg_price_range': None,
        'recommendation_reasons': []
    }

    if recently_viewed:
        # Category insights
        categories = [p.category for p in recently_viewed if p.category]
        if categories:
            category_counts = Counter([cat.name for cat in categories])
            insights['total_categories_viewed'] = len(set(categories))
            insights['primary_category'] = category_counts.most_common(1)[0][0] if category_counts else None

        # Price insights
        price_range = calculate_price_range(recently_viewed)
        if price_range:
            insights['avg_price_range'] = f"D{price_range[0]:.2f} - D{price_range[1]:.2f}"

        # Recommendation reasons
        if insights['primary_category']:
            insights['recommendation_reasons'].append(f"Based on your interest in {insights['primary_category']}")

        if len(recently_viewed) >= 3:
            insights['recommendation_reasons'].append("Curated from your browsing history")

        insights['recommendation_reasons'].append("Popular products in your price range")

    return insights

def serialize_products(products):
    serialized = []
    for product in products:
        serialized.append({
            'id': product.id,
            'name': product.name,
            'price': str(product.price),
            'image_url': product.image.url if product.image else '',
            'url': f'/products/{product.id}/',
            'category': product.category.name if product.category else '',
            'is_trending': getattr(product, 'is_trending', False),
            'discount_percentage': getattr(product, 'discount_percentage', 0),
            'view_count': getattr(product, 'view_count', 0),  # <- new line
        })
    return serialized


def product_detail(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    product_images = product.images.all()
    variants = product.variants.select_related('feature_option__feature')

    # Organize by feature name
    feature_map = {}
    for variant in variants:
        feature_name = variant.feature_option.feature.name
        feature_map.setdefault(feature_name, set()).add(variant.feature_option)

    # convert to list for template rendering
    feature_data = {
        k: sorted(list(v), key=lambda x: x.value) for k, v in feature_map.items()
    }
    try:
        seller_store = Store.objects.get(owner=product.seller, status='active')
    except Store.DoesNotExist:
        seller_store = None

    # Record view
    if request.user.is_authenticated:
        ProductView.objects.get_or_create(user=request.user, product=product)
    else:
        recently_viewed = request.session.get('recently_viewed', [])
        if product.id not in recently_viewed:
            recently_viewed.insert(0, product.id)
            if len(recently_viewed) > 10:
                recently_viewed = recently_viewed[:10]
            request.session['recently_viewed'] = recently_viewed

        # Organize by feature name
        feature_map = {}
        for variant in variants:
            feature_name = variant.feature_option.feature.name
            feature_map.setdefault(feature_name, set()).add(variant.feature_option)

        # convert to list for template rendering
        feature_data = {
            k: sorted(list(v), key=lambda x: x.value) for k, v in feature_map.items()
        }    # Recommended items with annotated review stats
    recommended_items = (
        Product.objects
        .filter(category=product.category)
        .exclude(id=product.id)
        [:4]
    )

    featured_celebrities = CelebrityFeature.objects.filter(products=product)[:8]

    # Clean specifications
    cleaned_specs = []
    if product.specifications:
        for line in product.specifications.splitlines():
            if ':' in line:
                raw_key, value = line.split(':', 1)
                clean_key = re.sub(r'^[^a-zA-Z0-9]*(.*?)[^a-zA-Z0-9]*$', r'\1', raw_key).strip()
                cleaned_specs.append((clean_key, value.strip()))

    # Truncate description
    description_text = product.description or ""
    short_description = description_text[:800]
    description_truncated = len(description_text) > 800
    if description_truncated:
        last_space = short_description.rfind(' ')
        if last_space != -1:
            short_description = short_description[:last_space]




    # Review data
    reviews = Review.objects.filter(product=product)
    user_review = Review.objects.filter(product=product, user=request.user).first() if request.user.is_authenticated else None
    form = ReviewForm(instance=user_review)

    avg_rating = reviews.aggregate(avg=Avg('rating'))['avg'] or 0
    review_count = reviews.count()

    user_rating = user_review.rating if user_review else 0

    # Address display
    address_display = ""
    address = None
    if request.user.is_authenticated:
        address = Address.objects.filter(user=request.user).first()
        if address:
            parts = [address.address1, address.address2, address.country]
            address_display = ', '.join(part for part in parts if part)

    # Chat messages
    messages = []
    if request.user.is_authenticated and request.user != product.seller:
        thread = ChatThread.objects.filter(participants=request.user).filter(participants=product.seller).first()
        if thread:
            messages = ChatMessage.objects.filter(thread=thread).select_related('sender').order_by('timestamp')

    return render(request, 'marketplace/product_detail.html', {
        'product': product,
        'product_images': product_images,
        'recommended_items': recommended_items,
        'specifications': cleaned_specs,
        'short_description': short_description,
        'description_truncated': description_truncated,
        'featured_celebrities': featured_celebrities,
        'messages': messages,
        'address': address,
        'address_display': address_display,
        'reviews': reviews,
        'user_review': user_review,
        'review_form': form,
        'avg_rating': round(avg_rating, 1),
        'review_count': review_count,
        'user_rating': user_rating,
        'rating_range': range(1, 6),
        'seller_store': seller_store,
        'feature_data': feature_data,
    })

def hot_picks(request):
    """
    Display hot picks for each parent category including products from all subcategories
    """
    parent_categories = Category.get_root_categories()  # Only active top-level categories
    hot_products_by_category = []

    for category in parent_categories:
        # Get all subcategories recursively using the model method
        all_subcategories = category.get_all_subcategories()

        # Create list of category IDs (parent + all descendants)
        related_category_ids = [category.id] + [sub.id for sub in all_subcategories]

        # Fetch featured products from parent category and all subcategories
        products = Product.objects.filter(
            category_id__in=related_category_ids,
            is_featured=True,
            category__is_active=True  # Assuming you have an is_active field on Product
        ).select_related('category').order_by('-created_at')[:8]

        if products.exists():
            hot_products_by_category.append({
                'category': category,
                'products': products,
                'subcategories': all_subcategories,  # Include subcategories for template use
                'total_categories': len(related_category_ids)  # Total categories included
            })

    return render(request, 'marketplace/hot_picks.html', {
        'hot_products_by_category': hot_products_by_category
    })

def category_products(request, slug):
    category = get_object_or_404(Category, id=slug)

    # Get IDs of the category and its subcategories
    subcategories = category.children.all()
    related_category_ids = [category.id] + list(subcategories.values_list('id', flat=True))

    # Fetch products belonging to the category and its subcategories
    products = Product.objects.filter(category_id__in=related_category_ids)

    return render(request, 'marketplace/category_products.html', {
        'category': category,
        'subcategories': subcategories,
        'products': products,
    })


def category_detail(request, pk):
    category = get_object_or_404(Category, pk=pk)

    # Get search query
    search_query = request.GET.get('q', '').strip()

    # Get sort parameter
    sort_by = request.GET.get('sort', '')

    # Get all subcategories at any depth (children, grandchildren, etc.)
    all_descendants = category.get_all_subcategories()

    # Collect category IDs: main + all descendant IDs
    related_category_ids = [category.id] + [subcat.id for subcat in all_descendants]

    # Base queryset with products in this category and all subcategories
    products_queryset = Product.objects.filter(
        category_id__in=related_category_ids,
        is_active=True  # Only show active products
    ).select_related('category', 'brand').prefetch_related('stock')

    # Apply search filter if query exists
    if search_query:
        products_queryset = products_queryset.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(brand__name__icontains=search_query) |
            Q(tags__icontains=search_query)
        ).distinct()

    # Apply sorting
    if sort_by == 'name':
        products_queryset = products_queryset.order_by('name')
    elif sort_by == '-name':
        products_queryset = products_queryset.order_by('-name')
    elif sort_by == 'price':
        products_queryset = products_queryset.order_by('price')
    elif sort_by == '-price':
        products_queryset = products_queryset.order_by('-price')
    elif sort_by == '-created_at':
        products_queryset = products_queryset.order_by('-created_at')
    elif sort_by == 'popularity':
        # Sort by review count and average rating
        products_queryset = products_queryset.annotate(
            review_count=Count('reviews'),
            avg_rating=Avg('reviews__rating')
        ).order_by('-review_count', '-avg_rating')
    else:
        # Default sorting: featured first, then by creation date
        products_queryset = products_queryset.order_by('-is_featured', '-created_at')

    # Pagination
    paginator = Paginator(products_queryset, 24)  # 24 products per page
    page = request.GET.get('page', 1)

    try:
        products = paginator.page(page)
    except PageNotAnInteger:
        products = paginator.page(1)
    except EmptyPage:
        products = paginator.page(paginator.num_pages)

    # Only direct subcategories for navigation
    subcategories = category.get_subcategories().annotate(
        product_count=Count('products', filter=Q(products__is_active=True))
    )

    # Get sibling categories if this category has a parent
    sibling_categories = None
    if category.parent:
        sibling_categories = Category.objects.filter(
            parent=category.parent,
            is_active=True
        ).annotate(
            product_count=Count('products', filter=Q(products__is_active=True))
        ).exclude(id=category.id)

    # Get related categories (categories with similar products or tags)
    related_categories = Category.objects.filter(
        is_active=True
    ).exclude(
        id__in=related_category_ids
    ).annotate(
        product_count=Count('products', filter=Q(products__is_in_stock=True))
    ).filter(
        product_count__gt=0
    )[:8]  # Limit to 8 related categories

    # Get recently viewed products from session
    recently_viewed_ids = request.session.get('recently_viewed', [])
    recently_viewed = Product.objects.filter(
        id__in=recently_viewed_ids
    )[:6] if recently_viewed_ids else None

    # Prepare context
    context = {
        'category': category,
        'products': products,
        'subcategories': subcategories,
        'sibling_categories': sibling_categories,
        'related_categories': related_categories,
        'recently_viewed': recently_viewed,
        'search_query': search_query,
        'current_sort': sort_by,
        'is_paginated': products.has_other_pages(),
        'page_obj': products,
    }

    # Add some category statistics
    total_products_in_category = Product.objects.filter(
        category_id__in=related_category_ids
    ).count()

    context['total_products'] = total_products_in_category

    # AJAX request handling for infinite scroll or dynamic loading
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # Return JSON response for AJAX requests
        products_data = []
        for product in products:
            products_data.append({
                'id': product.id,
                'name': product.name,
                'price': str(product.price),
                'image_url': product.image.url if product.image else None,
                'detail_url': product.get_absolute_url(),
                'is_in_stock': product.is_in_stock(),
                'discount_percentage': product.discount_percentage if hasattr(product, 'discount_percentage') else None,
                'is_featured': product.is_featured if hasattr(product, 'is_featured') else False,
                'is_new': product.is_new() if hasattr(product, 'is_new') else False,
                'average_rating': product.get_average_rating() if hasattr(product, 'get_average_rating') else None,
                'review_count': product.get_review_count() if hasattr(product, 'get_review_count') else 0,
            })

        return JsonResponse({
            'products': products_data,
            'has_next': products.has_next(),
            'has_previous': products.has_previous(),
            'current_page': products.number,
            'total_pages': products.paginator.num_pages,
            'total_products': products.paginator.count,
        })

    return render(request, 'marketplace/category_detail.html', context)


def category_products_ajax(request, pk):
    """
    Separate view for AJAX product loading (infinite scroll, filtering, etc.)
    """
    category = get_object_or_404(Category, pk=pk)

    # Get parameters
    page = request.GET.get('page', 1)
    search_query = request.GET.get('q', '').strip()
    sort_by = request.GET.get('sort', '')

    # Get all subcategories
    all_descendants = category.get_all_subcategories()
    related_category_ids = [category.id] + [subcat.id for subcat in all_descendants]

    # Build queryset
    products_queryset = Product.objects.filter(
        category_id__in=related_category_ids,
        is_active=True
    ).select_related('category', 'brand').prefetch_related('stock')

    # Apply search
    if search_query:
        products_queryset = products_queryset.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(brand__name__icontains=search_query)
        ).distinct()

    # Apply sorting
    if sort_by == 'name':
        products_queryset = products_queryset.order_by('name')
    elif sort_by == '-name':
        products_queryset = products_queryset.order_by('-name')
    elif sort_by == 'price':
        products_queryset = products_queryset.order_by('price')
    elif sort_by == '-price':
        products_queryset = products_queryset.order_by('-price')
    elif sort_by == '-created_at':
        products_queryset = products_queryset.order_by('-created_at')
    elif sort_by == 'popularity':
        products_queryset = products_queryset.annotate(
            review_count=Count('reviews'),
            avg_rating=Avg('reviews__rating')
        ).order_by('-review_count', '-avg_rating')
    else:
        products_queryset = products_queryset.order_by('-is_featured', '-created_at')

    # Pagination
    paginator = Paginator(products_queryset, 24)

    try:
        products = paginator.page(page)
    except (PageNotAnInteger, EmptyPage):
        products = paginator.page(1)

    # Prepare product data
    products_data = []
    for product in products:
        products_data.append({
            'id': product.id,
            'name': product.name,
            'price': str(product.price),
            'original_price': str(product.original_price) if hasattr(product,
                                                                     'original_price') and product.original_price else None,
            'image_url': product.image.url if product.image else None,
            'detail_url': product.get_absolute_url(),
            'is_in_stock': product.is_in_stock(),
            'stock_quantity': product.get_stock_quantity() if hasattr(product, 'get_stock_quantity') else 0,
            'discount_percentage': product.discount_percentage if hasattr(product, 'discount_percentage') else None,
            'is_featured': product.is_featured if hasattr(product, 'is_featured') else False,
            'is_new': product.is_new() if hasattr(product, 'is_new') else False,
            'average_rating': product.get_average_rating() if hasattr(product, 'get_average_rating') else None,
            'review_count': product.get_review_count() if hasattr(product, 'get_review_count') else 0,
            'brand': product.brand.name if hasattr(product, 'brand') and product.brand else None,
        })

    return JsonResponse({
        'success': True,
        'products': products_data,
        'pagination': {
            'has_next': products.has_next(),
            'has_previous': products.has_previous(),
            'current_page': products.number,
            'total_pages': products.paginator.num_pages,
            'total_products': products.paginator.count,
            'next_page_number': products.next_page_number() if products.has_next() else None,
            'previous_page_number': products.previous_page_number() if products.has_previous() else None,
        },
        'filters': {
            'search_query': search_query,
            'sort_by': sort_by,
        }
    })

@csrf_exempt
def add_to_cart(request, product_id):
    try:
        product = get_object_or_404(Product, id=product_id)
        quantity = int(request.POST.get('quantity', 1))

        # Get feature selections
        features_json = request.POST.get('features', '{}')
        selected_features = json.loads(features_json)

        if quantity < 1:
            quantity = 1
        elif quantity > 99:
            quantity = 99

        if request.user.is_authenticated:
            cart, created = Cart.objects.get_or_create(user=request.user)

            # Check for same product + same features
            cart_item = CartItem.objects.filter(
                cart=cart,
                product=product,
                selected_features=selected_features
            ).first()

            if cart_item:
                cart_item.quantity += quantity
                item_created = False
            else:
                cart_item = CartItem.objects.create(
                    cart=cart,
                    product=product,
                    quantity=quantity,
                    selected_features=selected_features
                )
                item_created = True

            if cart_item.quantity > 99:
                cart_item.quantity = 99

            cart_item.save()

            cart_items = CartItem.objects.filter(cart=cart)
            cart_count = sum(item.quantity for item in cart_items)
            cart_total = sum(item.product.price * item.quantity for item in cart_items)

            tax_rate = Decimal('0.085')
            tax_amount = cart_total * tax_rate
            final_total = cart_total + tax_amount

            return JsonResponse({
                'success': True,
                'message': f'{product.name} added to cart successfully!',
                'cart_count': cart_count,
                'cart_total': f"{cart_total:.2f}",
                'tax_amount': f"{tax_amount:.2f}",
                'final_total': f"{final_total:.2f}",
                'item_quantity': cart_item.quantity,
                'item_was_updated': not item_created,
                'product_name': product.name
            })

        else:
            # Session cart
            cart = request.session.get('cart', {})

            key = f"{product_id}::{json.dumps(selected_features, sort_keys=True)}"

            if key in cart:
                cart[key]['quantity'] += quantity
                if cart[key]['quantity'] > 99:
                    cart[key]['quantity'] = 99
                item_was_updated = True
            else:
                cart[key] = {
                    'quantity': quantity,
                    'name': product.name,
                    'price': str(product.price),
                    'features': selected_features
                }
                item_was_updated = False

            request.session['cart'] = cart
            request.session.modified = True

            cart_count = sum(item['quantity'] for item in cart.values())
            cart_total = Decimal('0')

            for entry in cart.values():
                try:
                    cart_total += Decimal(entry['price']) * entry['quantity']
                except:
                    continue

            tax_rate = Decimal('0.085')
            tax_amount = cart_total * tax_rate
            final_total = cart_total + tax_amount

            return JsonResponse({
                'success': True,
                'message': f'{product.name} added to cart successfully!',
                'cart_count': cart_count,
                'cart_total': f"{cart_total:.2f}",
                'tax_amount': f"{tax_amount:.2f}",
                'final_total': f"{final_total:.2f}",
                'item_quantity': cart[key]['quantity'],
                'item_was_updated': item_was_updated,
                'product_name': product.name
            })

    except ValueError:
        return JsonResponse({
            'success': False,
            'message': 'Invalid quantity specified'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error adding item to cart: {str(e)}'
        })

def cart_view(request):
    """
    Display cart with all items and totals
    """
    cart_items = []
    total_price = Decimal('0')

    if request.user.is_authenticated:
        cart = Cart.objects.filter(user=request.user).first()
        if cart:
            cart_item_qs = CartItem.objects.filter(cart=cart).select_related('product')
            for item in cart_item_qs:
                subtotal = item.product.price * item.quantity
                cart_items.append({
                    'id': item.id,  # Add item ID for frontend reference
                    'product': item.product,
                    'quantity': item.quantity,
                    'subtotal': subtotal,
                    # Optional: include features if stored for auth users
                    'selected_features': item.selected_features if hasattr(item, 'selected_features') else {},
                })
                total_price += subtotal
    else:
        session_cart = request.session.get('cart', {})
        cart_items = []
        total_price = Decimal('0.00')

        # Step 1: Map product_id to actual cart keys
        product_key_map = {}
        for key in session_cart.keys():
            try:
                pid = int(key.split("::")[0])
                product_key_map.setdefault(pid, []).append(key)
            except ValueError:
                continue

        # Step 2: Load Products
        product_ids = list(product_key_map.keys())
        products = Product.objects.filter(id__in=product_ids)

        # Step 3: Build cart item entries
        for product in products:
            product_keys = product_key_map.get(product.id, [])
            for key in product_keys:
                cart_data = session_cart.get(key, {})
                quantity = cart_data.get('quantity', 1)
                selected_features = cart_data.get('selected_features', {})
                subtotal = product.price * quantity

                cart_items.append({
                    'id': product.id,
                    'product': product,
                    'quantity': quantity,
                    'subtotal': subtotal,
                    'selected_features': selected_features,
                })
                total_price += subtotal

    # Calculate tax and final total
    tax_rate = Decimal('0.15')
    tax_amount = total_price * tax_rate
    final_total = total_price + tax_amount

    # Get cart count for badge
    cart_count = sum(item['quantity'] for item in cart_items)

    return render(request, 'marketplace/cart_detail.html', {
        'cart_items': cart_items,
        'total_price': total_price,
        'tax_amount': tax_amount,
        'final_total': final_total,
        'cart_count': cart_count,
    })

# Optional: Add this view to get current cart count for consistency
@csrf_exempt
def get_cart_count(request):
    """
    Get current cart count and total - useful for page load synchronization
    """
    try:
        if request.user.is_authenticated:
            cart = Cart.objects.filter(user=request.user).first()
            if cart:
                cart_items = CartItem.objects.filter(cart=cart)
                cart_count = sum(item.quantity for item in cart_items)
                cart_total = sum(item.product.price * item.quantity for item in cart_items)
            else:
                cart_count = 0
                cart_total = Decimal('0')
        else:
            cart = request.session.get('cart', {})
            cart_count = sum(item['quantity'] for item in cart.values())
            cart_total = Decimal('0')

            for pid, item in cart.items():
                try:
                    prod = Product.objects.get(id=pid)
                    cart_total += prod.price * item['quantity']
                except Product.DoesNotExist:
                    continue

        # Calculate tax
        tax_rate = Decimal('0.085')
        tax_amount = cart_total * tax_rate
        final_total = cart_total + tax_amount

        return JsonResponse({
            'success': True,
            'cart_count': cart_count,
            'cart_total': f"{cart_total:.2f}",
            'tax_amount': f"{tax_amount:.2f}",
            'final_total': f"{final_total:.2f}"
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error getting cart count: {str(e)}'
        })


# Helper function to get cart context for templates
def get_cart_context(request):
    """
    Helper function to get cart data for template context
    Use this in other views that need cart information
    """
    if request.user.is_authenticated:
        cart = Cart.objects.filter(user=request.user).first()
        if cart:
            cart_items = CartItem.objects.filter(cart=cart)
            cart_count = sum(item.quantity for item in cart_items)
            cart_total = sum(item.product.price * item.quantity for item in cart_items)
        else:
            cart_count = 0
            cart_total = Decimal('0')
    else:
        cart = request.session.get('cart', {})
        cart_count = sum(item['quantity'] for item in cart.values())
        cart_total = Decimal('0')

        for pid, item in cart.items():
            try:
                prod = Product.objects.get(id=pid)
                cart_total += prod.price * item['quantity']
            except Product.DoesNotExist:
                continue

    return {
        'cart_count': cart_count,
        'cart_total': cart_total
    }

@csrf_exempt
@require_POST
def update_cart_quantity(request):
    """
    Update cart item quantity - handles both direct quantity updates and increase/decrease actions
    Expects: product_id, and either 'quantity' or 'action' parameter
    """
    try:
        product_id = request.POST.get('product_id')
        quantity = request.POST.get('quantity')
        action = request.POST.get('action')  # 'increase' or 'decrease'

        if not product_id:
            return JsonResponse({
                'success': False,
                'message': 'Product ID is required'
            })

        product = get_object_or_404(Product, id=product_id)

        # Handle authenticated users
        if request.user.is_authenticated:
            cart = Cart.objects.filter(user=request.user).first()
            if not cart:
                return JsonResponse({
                    'success': False,
                    'message': 'Cart not found'
                })

            cart_item = CartItem.objects.filter(cart=cart, product=product).first()
            if not cart_item:
                return JsonResponse({
                    'success': False,
                    'message': 'Item not found in cart'
                })

            # Determine new quantity
            if quantity:
                # Direct quantity update
                new_quantity = int(quantity)
                if new_quantity < 1:
                    new_quantity = 1
                elif new_quantity > 99:
                    new_quantity = 99
                cart_item.quantity = new_quantity
            elif action:
                # Action-based update
                if action == 'increase':
                    cart_item.quantity = min(cart_item.quantity + 1, 99)
                elif action == 'decrease':
                    cart_item.quantity = max(cart_item.quantity - 1, 1)
                else:
                    return JsonResponse({
                        'success': False,
                        'message': 'Invalid action'
                    })
            else:
                return JsonResponse({
                    'success': False,
                    'message': 'Either quantity or action is required'
                })

            cart_item.save()

            # Calculate totals
            subtotal = cart_item.product.price * cart_item.quantity
            cart_items = CartItem.objects.filter(cart=cart)
            total_price = sum(item.product.price * item.quantity for item in cart_items)
            item_count = sum(item.quantity for item in cart_items)

            # Calculate tax (assuming 8.5% tax rate, adjust as needed)
            tax_rate = Decimal('0.085')
            tax_amount = total_price * tax_rate
            final_total = total_price + tax_amount

            return JsonResponse({
                'success': True,
                'quantity': cart_item.quantity,
                'subtotal': f"{subtotal:.2f}",
                'total_price': f"{total_price:.2f}",
                'tax_amount': f"{tax_amount:.2f}",
                'final_total': f"{final_total:.2f}",
                'item_count': item_count,
                'message': 'Cart updated successfully'
            })

        # Handle session-based cart for anonymous users
        else:
            cart = request.session.get('cart', {})
            product_key = str(product_id)

            if product_key not in cart:
                return JsonResponse({
                    'success': False,
                    'message': 'Item not found in cart'
                })

            # Determine new quantity
            if quantity:
                # Direct quantity update
                new_quantity = int(quantity)
                if new_quantity < 1:
                    new_quantity = 1
                elif new_quantity > 99:
                    new_quantity = 99
                cart[product_key]['quantity'] = new_quantity
            elif action:
                # Action-based update
                current_qty = cart[product_key]['quantity']
                if action == 'increase':
                    cart[product_key]['quantity'] = min(current_qty + 1, 99)
                elif action == 'decrease':
                    cart[product_key]['quantity'] = max(current_qty - 1, 1)
                else:
                    return JsonResponse({
                        'success': False,
                        'message': 'Invalid action'
                    })
            else:
                return JsonResponse({
                    'success': False,
                    'message': 'Either quantity or action is required'
                })

            request.session['cart'] = cart
            request.session.modified = True

            # Calculate totals
            quantity = cart[product_key]['quantity']
            subtotal = product.price * quantity

            total_price = Decimal('0')
            item_count = 0
            for pid, item in cart.items():
                try:
                    prod = Product.objects.get(id=pid)
                    item_total = prod.price * item['quantity']
                    total_price += item_total
                    item_count += item['quantity']
                except Product.DoesNotExist:
                    continue

            # Calculate tax
            tax_rate = Decimal('0.085')
            tax_amount = total_price * tax_rate
            final_total = total_price + tax_amount

            return JsonResponse({
                'success': True,
                'quantity': quantity,
                'subtotal': f"{subtotal:.2f}",
                'total_price': f"{total_price:.2f}",
                'tax_amount': f"{tax_amount:.2f}",
                'final_total': f"{final_total:.2f}",
                'item_count': item_count,
                'message': 'Cart updated successfully'
            })

    except ValueError as e:
        return JsonResponse({
            'success': False,
            'message': 'Invalid quantity value'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'An error occurred: {str(e)}'
        })


@csrf_exempt
@require_POST
def remove_cart_item(request):
    """
    Remove an item from the cart.
    Expects POST data: product_id
    """
    try:
        product_id = request.POST.get('product_id')

        if not product_id or not product_id.isdigit():
            return JsonResponse({'success': False, 'message': 'Invalid product ID'})

        product_id = int(product_id)
        product = get_object_or_404(Product, id=product_id)

        # --- Authenticated Users ---
        if request.user.is_authenticated:
            cart = Cart.objects.filter(user=request.user).first()
            if not cart:
                return JsonResponse({'success': False, 'message': 'Cart not found'})

            cart_item = CartItem.objects.filter(cart=cart, product=product).first()
            if not cart_item:
                return JsonResponse({'success': False, 'message': 'Item not found in cart'})

            cart_item.delete()

            # Recalculate totals
            cart_items = CartItem.objects.filter(cart=cart)
            total_price = sum(item.product.price * item.quantity for item in cart_items)
            item_count = sum(item.quantity for item in cart_items)

        # --- Anonymous Users ---
        else:
            cart = request.session.get('cart', {})

            # Handle malformed keys like "1::{}"
            normalized_keys = {key.split("::")[0]: key for key in cart.keys()}
            matched_key = normalized_keys.get(str(product_id))

            if not matched_key or matched_key not in cart:
                return JsonResponse({'success': False, 'message': 'Item not found in cart'})

            del cart[matched_key]
            request.session['cart'] = cart
            request.session.modified = True

            # Recalculate totals
            total_price = Decimal('0.00')
            item_count = 0
            for pid, item in cart.items():
                try:
                    prod = Product.objects.get(id=int(pid.split("::")[0]))
                    qty = item.get('quantity', 1)
                    total_price += prod.price * qty
                    item_count += qty
                except (Product.DoesNotExist, ValueError):
                    continue

        # Shared tax calculation
        tax_rate = Decimal('0.085')
        tax_amount = total_price * tax_rate
        final_total = total_price + tax_amount

        return JsonResponse({
            'success': True,
            'message': 'Item removed from cart',
            'total_price': f"{total_price:.2f}",
            'tax_amount': f"{tax_amount:.2f}",
            'final_total': f"{final_total:.2f}",
            'item_count': item_count
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'An error occurred: {str(e)}'
        })

@login_required
def toggle_wishlist(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    wishlist_item, created = Wishlist.objects.get_or_create(user=request.user, product=product)

    # If user clicked 'Add to Cart' from wishlist
    if request.GET.get('action') == 'add_to_cart':
        # Logic to add to cart
        cart, _ = Cart.objects.get_or_create(user=request.user)
        CartItem.objects.get_or_create(cart=cart, product=product, defaults={'quantity': 1})

        # Remove from wishlist (optional)
        wishlist_item.delete()

        messages.success(request, f"{product.name} added to cart.")
        return redirect('marketplace:my_wishlist')

    # AJAX or normal toggle
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        if not created:
            wishlist_item.delete()
            return JsonResponse({
                'success': True,
                'status': 'removed',
                'message': f"{product.name} removed from your wishlist"
            })
        return JsonResponse({
            'success': True,
            'status': 'added',
            'message': f"{product.name} added to your wishlist"
        })

    else:
        if not created:
            wishlist_item.delete()
            messages.info(request, f"{product.name} removed from your wishlist.")
        else:
            messages.success(request, f"{product.name} added to your wishlist.")
        return redirect('marketplace:my_wishlist')


@login_required
def my_wishlist(request):
    items = Wishlist.objects.filter(user=request.user).select_related('product')
    return render(request, 'wishlist/my_wishlist.html', {'items': items})

@csrf_exempt
@require_POST
def apply_promo_code(request):
    try:
        promo_code_str = request.POST.get('promo_code', '').strip().upper()

        if not promo_code_str:
            return JsonResponse({'success': False, 'message': 'Promo code is required'})

        try:
            promo = PromoCode.objects.get(code__iexact=promo_code_str, is_active=True)
        except PromoCode.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Invalid or expired promo code'})

        if not promo.is_valid():
            return JsonResponse({'success': False, 'message': 'Promo code usage limit reached or inactive'})

        subtotal = Decimal('0')
        discount_amount = Decimal('0')
        item_count = 0
        eligible_total = Decimal('0')

        # Get cart items (auth or guest)
        if request.user.is_authenticated:
            cart = Cart.objects.filter(user=request.user).first()
            if not cart:
                return JsonResponse({'success': False, 'message': 'Cart is empty'})
            cart_items = CartItem.objects.filter(cart=cart).select_related('product')
        else:
            cart_data = request.session.get('cart', {})
            if not cart_data:
                return JsonResponse({'success': False, 'message': 'Cart is empty'})
            cart_items = []
            for pid, item in cart_data.items():
                try:
                    product = Product.objects.get(id=pid)
                    quantity = item.get('quantity', 1)
                    cart_items.append({
                        'product': product,
                        'quantity': quantity
                    })
                except Product.DoesNotExist:
                    continue

        # Calculate eligible total & subtotal
        for item in cart_items:
            product = item.product if hasattr(item, 'product') else item['product']
            quantity = item.quantity if hasattr(item, 'quantity') else item['quantity']
            line_total = product.price * quantity
            subtotal += line_total
            item_count += quantity

            if not promo.products.exists() or promo.products.filter(id=product.id).exists():
                eligible_total += line_total

        # Calculate discount
        if promo.discount_percentage > 0 and eligible_total > 0:
            discount_amount = (eligible_total * Decimal(promo.discount_percentage)) / 100

        # Totals
        discounted_subtotal = subtotal - discount_amount
        tax_rate = Decimal('0.085')
        tax_amount = discounted_subtotal * tax_rate
        final_total = discounted_subtotal + tax_amount

        # Store promo in session for later use
        request.session['applied_promo'] = {
            'code': promo.code,
            'discount_amount': str(discount_amount),
            'discount_percent': promo.discount_percentage
        }

        return JsonResponse({
            'success': True,
            'discount': f"{discount_amount:.2f}",
            'total_price': f"{discounted_subtotal:.2f}",
            'tax_amount': f"{tax_amount:.2f}",
            'final_total': f"{final_total:.2f}",
            'item_count': item_count,
            'message': f'Promo code "{promo.code}" applied successfully!'
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'An error occurred: {str(e)}'
        })
def trending_products_view(request):
    """
    Display trending products with celebrity features and sorting options
    """
    sort_by = request.GET.get('sort', 'trending')

    # Annotate products with total stock
    trending_products = Product.objects.filter(is_trending=True).annotate(
        total_stock=Sum('stock_records__quantity')
    ).filter(total_stock__gt=0)  # Only show products with stock

    # Apply sorting
    if sort_by == 'price_low':
        trending_products = trending_products.order_by('price')
    elif sort_by == 'price_high':
        trending_products = trending_products.order_by('-price')
    elif sort_by == 'newest':
        trending_products = trending_products.order_by('-created_at')
    else:
        trending_products = trending_products.order_by('-sold_count', '-created_at')

    paginator = Paginator(trending_products, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    celebrity_features = get_celebrity_features()
    trending_categories = get_trending_categories()

    context = {
        'trending_products': page_obj,
        'celebrity_features': celebrity_features,
        'trending_categories': trending_categories,
        'current_sort': sort_by,
        'page_obj': page_obj,
    }

    return render(request, 'marketplace/trending_products.html', context)


def get_celebrity_features():
    """
    Fetch active celebrity features from the database, ordered by featured_order and created_at.
    """
    return CelebrityFeature.objects.filter(is_active=True).prefetch_related('products').order_by('featured_order', '-created_at')


def get_trending_categories():
    """
    Get trending categories with mock statistics
    """
    categories = Category.objects.annotate(
        product_count=Count('product')
    ).filter(product_count__gt=0)[:4]

    # Add mock trending stats
    trending_stats = ['230%', '180%', '156%', '145%']
    icons = ['fas fa-tshirt', 'fas fa-spa', 'fas fa-mobile-alt', 'fas fa-home']
    descriptions = [
        'Celeb-inspired outfits',
        'Red carpet ready',
        'Celebrity must-haves',
        'Designer favorites'
    ]

    trending_categories = []
    for i, category in enumerate(categories):
        trending_categories.append({
            'category': category,
            'increase': trending_stats[i] if i < len(trending_stats) else '100%',
            'icon': icons[i] if i < len(icons) else 'fas fa-star',
            'description': descriptions[i] if i < len(descriptions) else 'Trending now'
        })

    return trending_categories


def search_products(request):
    """Enhanced search view with logging and caching"""
    query = request.GET.get('q', '').strip()
    category_id = request.GET.get('category', '')
    min_price = request.GET.get('min_price', '')
    max_price = request.GET.get('max_price', '')
    sort_by = request.GET.get('sort', 'name')

    # Create cache key for search results
    cache_key = f"search:{query}:{category_id}:{min_price}:{max_price}:{sort_by}"

    # Try to get results from cache
    cached_results = cache.get(cache_key)
    if cached_results:
        products = cached_results
    else:
        # Build query
        products = Product.objects.filter(category__is_active=True)

        if query:
            products = products.filter(
                Q(name__icontains=query) |
                Q(description__icontains=query) |
                Q(category__name__icontains=query)
            )

        if category_id:
            products = products.filter(category_id=category_id)

        if min_price:
            try:
                products = products.filter(price__gte=float(min_price))
            except ValueError:
                pass

        if max_price:
            try:
                products = products.filter(price__lte=float(max_price))
            except ValueError:
                pass

        # Apply sorting
        if sort_by == 'price_low':
            products = products.order_by('price')
        elif sort_by == 'price_high':
            products = products.order_by('-price')
        elif sort_by == 'newest':
            products = products.order_by('-created_at')
        else:
            products = products.order_by('name')

        # Cache results for 5 minutes
        cache.set(cache_key, products, 300)

    # Log search if query exists
    if query:
        log_search(request, query, products.count())

    # Pagination
    paginator = Paginator(products, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Get popular searches for suggestions
    popular_searches = PopularSearch.objects.all()[:5]

    context = {
        'products': page_obj,
        'query': query,
        'selected_category': category_id,
        'min_price': min_price,
        'max_price': max_price,
        'sort_by': sort_by,
        'categories': Category.objects.all(),
        'total_results': products.count(),
        'page_obj': page_obj,
        'popular_searches': popular_searches,
    }

    return render(request, 'marketplace/search_results.html', context)


def search_suggestions(request):
    """
    AJAX endpoint for search suggestions
    """
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        query = request.GET.get('q', '').strip()

        if len(query) >= 2:
            # Basic search in product name and description
            products = Product.objects.filter(
                Q(name__icontains=query) |
                Q(description__icontains=query)
            )

            # If you have categories, also search there
            if hasattr(Product, 'category'):
                products = products.filter(
                    Q(name__icontains=query) |
                    Q(description__icontains=query) |
                    Q(category__name__icontains=query)
                )

            # Select related category if it exists
            if hasattr(Product, 'category'):
                products = products.select_related('category')

            # Limit to 8 suggestions
            products = products[:8]

            suggestions = []
            for product in products:
                # Get category name safely
                category_name = 'Uncategorized'
                if hasattr(product, 'category') and product.category:
                    category_name = product.category.name

                # Get product URL safely
                product_url = '#'
                try:
                    product_url = reverse('marketplace:product_detail', kwargs={'pk': product.pk})
                except:
                    product_url = f'/product/{product.pk}/'

                suggestions.append({
                    'id': product.id,
                    'name': product.name,
                    'price': str(product.price),
                    'category': category_name,
                    'image': product.image.url if hasattr(product, 'image') and product.image else None,
                    'url': product_url
                })

            return JsonResponse({
                'suggestions': suggestions,
                'query': query
            })

    return JsonResponse({'suggestions': [], 'query': ''})


def get_popular_searches(request):
    """API endpoint for popular searches"""
    popular_searches = PopularSearch.objects.all()[:10]
    searches = [{'query': search.query, 'count': search.search_count} for search in popular_searches]
    return JsonResponse({'popular_searches': searches})


def clear_search_history(request):
    """Clear user's search history"""
    if request.user.is_authenticated and request.method == 'POST':
        SearchHistory.objects.filter(user=request.user).delete()
        return JsonResponse({'success': True})
    return JsonResponse({'success': False})

def about(request):
    return render(request, 'marketplace/about.html')