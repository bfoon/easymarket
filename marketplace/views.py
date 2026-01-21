from __future__ import annotations
from django.shortcuts import render, get_object_or_404, redirect
from unicodedata import category

from .models import (Category, Product, ProductView,
                     CartItem, Cart, CelebrityFeature, Wishlist,
                     SearchHistory, PopularSearch, ProductFeature, ProductImage,
                     ProductFeatureOption, ProductVariant, SharedCart, SocialCart, CartMember, PaymentShare,
                     Career, CareerApplication, PressRelease, InvestorDocument, InvestorEvent,
                     Campaign, CampaignProduct, WheelSpin)
from chat.models import ChatThread, ChatMessage
from analytics.models import CartEvent
from analytics.services import track_event
from accounts.models import Address
from stores.models import Store
from reviews.models import Review
from orders.models import PromoCode
from reviews.forms import ReviewForm
from django.db.models import Prefetch
from django.db import models
from django.contrib.auth import get_user_model
import re
import secrets
import qrcode
from io import BytesIO
import base64
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required, user_passes_test
from decimal import Decimal
from django.core.cache import cache
from .utils import (log_search, get_search_suggestions_with_history,
                    build_cart_context, _coerce_int, _ensure_owner_membership,
                    _resolve_active_social_for, _resolve_active_cart_for_user,
                    with_display_images, format_price_for_user)
from .utils import sync_social_items_totals
from django.urls import reverse
import json, uuid
import random
import logging
from datetime import timedelta
from datetime import datetime
from django.utils import timezone
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q, Count, F, Sum, Avg
from django.contrib import messages
from collections import Counter
from accounts.utils import log_admin_action
from django.views.decorators.http import require_GET
from .notifications import send_email, send_whatsapp
from django.http import JsonResponse, HttpRequest
from django.template.loader import render_to_string
from django.conf import settings
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from django.core.mail import EmailMessage
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.db import transaction
import os

# Get the custom User model
User = get_user_model()
logger = logging.getLogger(__name__)


def _ensure_session(request):
    """Make sure guests also have a session_key for tracking."""
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def _track_cart_event(request, event: str):
    """
    Record cart analytics event (add/remove/checkout/completed/abandoned).
    Safe: never breaks cart flow if analytics fails.
    """
    try:
        session_key = _ensure_session(request)
        CartEvent.objects.create(
            user=request.user if request.user.is_authenticated else None,
            session_key=session_key,
            event=event,
        )
    except Exception:
        pass


def all_products(request):
    """
        Alternative approach: Show categories at multiple levels intelligently.
        This version shows root categories if they have products, OR shows their
        child categories if those have products but the root doesn't.
        """
    parent_categories = Category.objects.filter(parent__isnull=True, is_active=True)
    category_products = []

    for root_category in parent_categories:
        # Get all descendants
        all_descendants = root_category.get_all_subcategories()
        all_related_ids = [root_category.id] + [sub.id for sub in all_descendants]

        # Check if root category itself has products
        root_products = Product.objects.filter(
            category_id=root_category.id,
            is_active=True
        )

        if root_products.exists():
            # Root has products, show it
            products_to_show = root_products.order_by('?')[:4]
            category_products.append({
                'category': root_category,
                'products': products_to_show,
                'subcategories': root_category.get_subcategories()
            })
        else:
            # Root has no products, check immediate children (level 2)
            immediate_children = root_category.get_subcategories()

            for child_category in immediate_children:
                # Get all descendants of this child
                child_descendants = child_category.get_all_subcategories()
                child_related_ids = [child_category.id] + [sub.id for sub in child_descendants]

                # Get products from child and its descendants
                child_products = Product.objects.filter(
                    category_id__in=child_related_ids,
                    is_active=True
                ).order_by('?')[:4]

                if child_products.exists():
                    category_products.append({
                        'category': child_category,
                        'products': child_products,
                        'subcategories': child_category.get_subcategories()
                    })

    return render(request, 'marketplace/all_products.html', {
        'category_products': category_products
    })


def product_list(request):
    """Updated product list view with campaign support"""
    categories = Category.objects.filter(parent__isnull=True)[:6]

    # Base queryset for general lists
    base_qs = with_display_images(Product.objects.filter(is_active=True))

    # Get active campaigns
    now = timezone.now()
    active_campaigns = Campaign.objects.filter(
        is_active=True,
        status=Campaign.Status.ACTIVE,
        start_date__lte=now,
        end_date__gte=now
    ).prefetch_related('campaign_products__product')

    # Flash promotion campaign (show wheel)
    flash_campaign = active_campaigns.filter(
        campaign_type=Campaign.CampaignType.FLASH_SALE,
        enable_wheel=True
    ).first()

    # Trending campaign products
    trending_campaign = active_campaigns.filter(
        campaign_type=Campaign.CampaignType.TRENDING
    ).first()

    # Product lists
    products = with_display_images(Product.objects.all())
    featured_products = with_display_images(Product.objects.filter(is_active=True, is_featured=True))[:6]

    # Trending products - only show if there's an active trending campaign
    trending_products = Product.objects.none()
    if trending_campaign:
        trending_product_ids = trending_campaign.campaign_products.values_list('product_id', flat=True)
        trending_products = with_display_images(
            Product.objects.filter(
                id__in=trending_product_ids,
                is_active=True,
                show_in_trending=True
            )
        )

    # Explore section (paginated)
    qs = base_qs.order_by("-sold_count", "-created_at")
    paginator = Paginator(qs, 12)
    explore_page = paginator.get_page(1)

    recently_viewed = Product.objects.none()
    similar_items = Product.objects.none()

    # Logged-in recently viewed
    if request.user.is_authenticated:
        recently_viewed = with_display_images(
            Product.objects.filter(is_active=True, productview__user=request.user)
            .distinct()
            .order_by("-productview__viewed_at")
        )[:8]
    else:
        session_recently_viewed = request.session.get("recently_viewed", [])
        recently_viewed = with_display_images(
            Product.objects.filter(is_active=True, id__in=session_recently_viewed)
        )

    # Similar items logic
    if recently_viewed:
        last_viewed_product = recently_viewed.first()
        if last_viewed_product.category:
            main_category = last_viewed_product.category.parent or last_viewed_product.category
            related_category_ids = [main_category.id] + list(main_category.children.values_list("id", flat=True))

            similar_items = with_display_images(
                Product.objects.filter(is_active=True, category_id__in=related_category_ids)
                .exclude(id=last_viewed_product.id)
            )[:8]

    # Recommendations
    recommended_products = generate_recommendations(request, recently_viewed)
    if hasattr(recommended_products, "prefetch_related"):
        recommended_products = with_display_images(recommended_products)[:12]
    else:
        rec_ids = [p.id for p in recommended_products if getattr(p, "id", None)]
        recommended_products = with_display_images(Product.objects.filter(id__in=rec_ids, is_active=True))

    # Check if user can spin wheel
    user_can_spin = False
    wheel_prizes = []
    user_spins_left = 0
    if flash_campaign:
        wheel_prizes = flash_campaign.wheel_prizes or []
        if flash_campaign.require_login and not request.user.is_authenticated:
            user_can_spin = False
        else:
            # Count user's spins
            if request.user.is_authenticated:
                user_spins = WheelSpin.objects.filter(
                    campaign=flash_campaign,
                    user=request.user
                ).count()
            else:
                session_key = request.session.session_key or _ensure_session(request)
                user_spins = WheelSpin.objects.filter(
                    campaign=flash_campaign,
                    session_key=session_key
                ).count()

            user_spins_left = max(flash_campaign.max_spins_per_user - user_spins, 0)
            user_can_spin = user_spins_left > 0

        # Increment campaign views
        flash_campaign.increment_views()

    return render(request, "marketplace/product_list.html", {
        "categories": categories,
        "featured_products": featured_products,
        "trending_products": trending_products,
        "products": products,
        "explore_page": explore_page,
        "recently_viewed": recently_viewed,
        "similar_items": similar_items,
        "recommended_products": recommended_products,
        # Campaign data
        "flash_campaign": flash_campaign,
        "trending_campaign": trending_campaign,
        "user_can_spin": user_can_spin,
        "user_spins_left": user_spins_left,
        "wheel_prizes": wheel_prizes,
    })


@require_POST
def spin_wheel(request, slug):
    """
    Handle wheel spin requests.

    FIXED ISSUES:
    - Promo code now auto-generates correctly
    - Prize value is included in response
    - Better error handling
    """
    try:
        # Import models
        from marketplace.models import Campaign, WheelSpin
        from orders.models import PromoCode

        logger.info(f"=== Spin wheel request for campaign: {slug} ===")

        # Get campaign
        campaign = get_object_or_404(
            Campaign,
            slug=slug,
            is_active=True,
            status=Campaign.Status.ACTIVE
        )

        logger.info(f"Campaign found: {campaign.name}")

        # Check if campaign is running
        if not campaign.is_running():
            logger.warning(f"Campaign {campaign.slug} is not running")
            return JsonResponse({
                'success': False,
                'error': 'This campaign is not currently active'
            }, status=400)

        # Check login requirement
        if campaign.require_login and not request.user.is_authenticated:
            logger.info(f"Login required for campaign {campaign.slug}")
            return JsonResponse({
                'success': False,
                'error': 'Please login to spin the wheel',
                'require_login': True
            }, status=403)

        # Get or create session key
        session_key = request.session.session_key
        if not session_key:
            session_key = _ensure_session(request)

        # Check spin limit
        if request.user.is_authenticated:
            existing_spins = WheelSpin.objects.filter(
                campaign=campaign,
                user=request.user
            ).count()
            user_identifier = f"User {request.user.id}"
        else:
            existing_spins = WheelSpin.objects.filter(
                campaign=campaign,
                session_key=session_key
            ).count()
            user_identifier = f"Session {session_key[:8]}"

        logger.info(f"{user_identifier} has {existing_spins}/{campaign.max_spins_per_user} spins")

        if existing_spins >= campaign.max_spins_per_user:
            return JsonResponse({
                'success': False,
                'error': f'You have used all your spins ({campaign.max_spins_per_user} maximum)'
            }, status=400)

        # Get prizes from campaign
        prizes = campaign.wheel_prizes

        # Use default prizes if none configured
        if not prizes or not isinstance(prizes, list) or len(prizes) == 0:
            logger.warning(f"No prizes configured, using defaults")
            prizes = [
                {"label": "10% OFF", "probability": 0.25, "type": "discount", "value": 10},
                {"label": "15% OFF", "probability": 0.15, "type": "discount", "value": 15},
                {"label": "20% OFF", "probability": 0.10, "type": "discount", "value": 20},
                {"label": "Free Shipping", "probability": 0.20, "type": "free_shipping", "value": 0},
                {"label": "5% OFF", "probability": 0.20, "type": "discount", "value": 5},
                {"label": "Try Again", "probability": 0.10, "type": "nothing", "value": 0},
            ]

        # Validate and normalize prizes
        valid_prizes = []
        for prize in prizes:
            if isinstance(prize, dict) and 'label' in prize and 'probability' in prize:
                # Ensure all required fields exist
                normalized_prize = {
                    'label': prize.get('label', 'Prize'),
                    'probability': float(prize.get('probability', 0)),
                    'type': prize.get('type', 'discount'),
                    'value': float(prize.get('value', 0)),
                }
                valid_prizes.append(normalized_prize)

        if not valid_prizes:
            logger.error("No valid prizes available")
            return JsonResponse({
                'success': False,
                'error': 'Campaign configuration error'
            }, status=500)

        prizes = valid_prizes

        # Weighted random selection
        total_probability = sum(p['probability'] for p in prizes)

        if total_probability <= 0:
            logger.error(f"Invalid total probability: {total_probability}")
            return JsonResponse({
                'success': False,
                'error': 'Campaign configuration error'
            }, status=500)

        rand = random.uniform(0, total_probability)
        cumulative = 0
        selected_prize = prizes[-1]  # Default to last prize

        for prize in prizes:
            cumulative += prize['probability']
            if rand <= cumulative:
                selected_prize = prize
                break

        logger.info(f"Selected prize: {selected_prize['label']} (value: {selected_prize['value']})")

        # Create WheelSpin record
        try:
            spin = WheelSpin.objects.create(
                campaign=campaign,
                user=request.user if request.user.is_authenticated else None,
                session_key=session_key if not request.user.is_authenticated else '',
                prize_won=selected_prize['label'],
                prize_type=selected_prize['type'],
                prize_value=Decimal(str(selected_prize['value'])),
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:1000]
            )
            logger.info(f"✅ Created WheelSpin #{spin.id}")
        except Exception as e:
            logger.error(f"❌ Error creating WheelSpin: {e}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': 'Failed to record your spin. Please try again.'
            }, status=500)

        # ===================================================================
        # FIX: Generate promo code IMMEDIATELY after creating spin
        # ===================================================================
        promo_code = None

        if selected_prize['type'] != 'nothing':
            try:
                logger.info(f"Generating promo code for prize: {selected_prize['label']}")

                # Call the generate_promo_code method
                promo_code = spin.generate_promo_code()

                if promo_code:
                    logger.info(f"✅ Generated promo code: {promo_code}")
                else:
                    logger.warning(f"⚠️  generate_promo_code returned None")

            except Exception as e:
                logger.error(f"❌ Error generating promo code: {e}", exc_info=True)
                # Don't fail the entire spin if promo generation fails
                # Admin can manually create the code later
                logger.warning("Spin recorded but promo code generation failed")
        else:
            logger.info(f"Prize type is 'nothing', no promo code needed")

        # Increment campaign stats
        try:
            campaign.increment_spins()
        except Exception as e:
            logger.error(f"Error incrementing campaign spins: {e}")

        # Calculate remaining spins
        spins_left = max(campaign.max_spins_per_user - (existing_spins + 1), 0)

        # ===================================================================
        # FIX: Include prize value in response
        # ===================================================================
        response_data = {
            'success': True,
            'prize': {
                'label': selected_prize['label'],
                'type': selected_prize['type'],
                'value': selected_prize['value'],  # ✅ FIX: Include value
                'promo_code': promo_code,  # ✅ FIX: This now contains the code
            },
            'spins_left': spins_left,
            'message': f"🎉 Congratulations! You won {selected_prize['label']}!"
        }

        logger.info(f"✅ Spin successful - Response: {response_data}")

        return JsonResponse(response_data)

    except Campaign.DoesNotExist:
        logger.error(f"Campaign not found: {slug}")
        return JsonResponse({
            'success': False,
            'error': 'Campaign not found'
        }, status=404)

    except Exception as e:
        logger.error(f"❌ Unexpected error in spin_wheel: {type(e).__name__}: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'An error occurred. Please try again.',
            'debug': str(e) if request.user.is_staff else None
        }, status=500)


@require_GET
def campaign_detail(request, slug):
    """View campaign details and products"""
    campaign = get_object_or_404(
        Campaign.objects.prefetch_related('campaign_products__product'),
        slug=slug,
        is_active=True
    )

    # Get campaign products
    campaign_products = campaign.campaign_products.filter(
        product__is_active=True
    ).select_related('product').order_by('position')

    # Add campaign prices to products
    products_with_prices = []
    for cp in campaign_products:
        product = cp.product
        product.campaign_price = cp.get_campaign_price()
        product.campaign_discount_percentage = cp.get_discount_percentage()
        product.campaign_discount_amount = cp.get_discount_amount()
        product.campaign_stock_remaining = cp.remaining_stock()
        products_with_prices.append(product)

    # Paginate products
    paginator = Paginator(products_with_prices, 24)
    page_obj = paginator.get_page(request.GET.get('page'))

    # Check user spin eligibility
    user_can_spin = False
    user_spins_left = 0

    if campaign.enable_wheel and campaign.is_running():
        if campaign.require_login and not request.user.is_authenticated:
            user_can_spin = False
        else:
            if request.user.is_authenticated:
                user_spins = WheelSpin.objects.filter(
                    campaign=campaign,
                    user=request.user
                ).count()
            else:
                session_key = request.session.session_key or _ensure_session(request)
                user_spins = WheelSpin.objects.filter(
                    campaign=campaign,
                    session_key=session_key
                ).count()

            user_spins_left = max(campaign.max_spins_per_user - user_spins, 0)
            user_can_spin = user_spins_left > 0

    # Increment views
    campaign.increment_views()

    return render(request, 'marketplace/campaign_detail.html', {
        'campaign': campaign,
        'page_obj': page_obj,
        'products': page_obj.object_list,
        'user_can_spin': user_can_spin,
        'user_spins_left': user_spins_left,
    })


@require_GET
@require_GET
def explore_more(request):
    """
    AJAX endpoint for infinite scroll pagination of explore products.

    Returns paginated products sorted by popularity (sold_count) and recency.
    Includes display images for hover/slide functionality.

    Query Parameters:
        page (int): Page number (default: 1)
        per_page (int): Items per page (default: 12)

    Returns:
        JsonResponse: {
            'success': bool,
            'html': str (rendered product cards),
            'has_next': bool,
            'next_page': int | None
        }

    Security:
        - GET only (enforced by @require_GET)
        - No authentication required (public product browsing)
        - Integer coercion prevents injection attacks
    """
    page = int(request.GET.get("page", "1"))
    per_page = int(request.GET.get("per_page", "12"))

    qs = with_display_images(Product.objects.filter(is_active=True)).order_by("-sold_count", "-created_at")
    paginator = Paginator(qs, per_page)
    page_obj = paginator.get_page(page)

    html = render_to_string(
        "marketplace/partials/_explore_cards.html",
        {"products": page_obj.object_list},
        request=request
    )

    return JsonResponse({
        "success": True,
        "html": html,
        "has_next": page_obj.has_next(),
        "next_page": page_obj.next_page_number() if page_obj.has_next() else None,
    })


def generate_recommendations(request, recently_viewed):
    recommended_products = []

    if request.user.is_authenticated:
        recommended_products = get_authenticated_user_recommendations(request.user, recently_viewed)
    else:
        recommended_products = get_anonymous_user_recommendations(request, recently_viewed)

    # If it's a queryset, prefetch directly
    if hasattr(recommended_products, "prefetch_related"):
        recommended_products = with_display_images(recommended_products)[:12]
        return list(recommended_products)

    # If it's a list, re-query by IDs (fast + prefetched)
    rec_ids = [p.id for p in recommended_products if getattr(p, "id", None)]
    qs = with_display_images(Product.objects.filter(is_active=True, id__in=rec_ids))
    # preserve original order
    ordered = sorted(qs, key=lambda p: rec_ids.index(p.id)) if rec_ids else []
    return ordered[:12]


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
    recommendations = []
    viewed_ids = [p.id for p in recently_viewed] if recently_viewed else []

    if recently_viewed:
        category_ids = [p.category.id for p in recently_viewed if p.category]
        if category_ids:
            category_recommendations = with_display_images(
                Product.objects.filter(is_active=True, category_id__in=category_ids)
                .exclude(id__in=viewed_ids)
                .annotate(avg_rating=Avg('reviews__rating'))
                .order_by('-avg_rating', '-created_at')
            )[:8]
            recommendations.extend(list(category_recommendations))

        price_range = calculate_price_range(recently_viewed)
        if price_range:
            price_recommendations = with_display_images(
                Product.objects.filter(is_active=True, price__range=price_range)
                .exclude(id__in=viewed_ids)
                .order_by('-is_trending', '-created_at')
            )[:4]
            recommendations.extend(list(price_recommendations))

    if len(recommendations) < 8:
        popular_products = with_display_images(
            Product.objects.filter(is_active=True)
            .annotate(view_count=Count('productview'), avg_rating=Avg('reviews__rating'))
            .order_by('-view_count', '-avg_rating')
        )[:12]
        recommendations.extend(list(popular_products))

    return remove_duplicates(recommendations, viewed_ids)


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
        category_id__in=category_ids, is_active=True
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
    if request.method == 'GET':
        page = int(request.GET.get('page', 1))
        per_page = int(request.GET.get('per_page', 8))

        recently_viewed = []
        if request.user.is_authenticated:
            recently_viewed = with_display_images(
                Product.objects.filter(productview__user=request.user, is_active=True)
                .distinct()
                .order_by('-productview__viewed_at')
            )[:5]

        all_recommendations = generate_recommendations(request, recently_viewed)

        start = (page - 1) * per_page
        end = start + per_page
        recommendations = all_recommendations[start:end]

        data = []
        for product in recommendations:
            data.append({
                'id': product.id,
                'name': product.name,
                'price': str(product.price),
                'image_url': product.display_image_url,  # ✅ primary -> first -> product.image
                'url': product.get_absolute_url if hasattr(product, "get_absolute_url") else f'/products/{product.id}/',
                'rating': getattr(product, 'average_rating', 0),
                'is_trending': product.is_trending,
                'discount_percentage': getattr(product, 'discount_percentage', 0) or 0,
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
            productview__user=request.user, is_active=True
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
    collaborative_products = Product.objects.filter(is_active=True,
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
            category_id__in=category_ids, is_active=True
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
        category_id__in=category_ids, is_active=True
    ).exclude(id__in=viewed_ids).order_by('?')  # Random order for variety

    return list(similar_products)


def get_fallback_recommendations(user, excluded_ids, count):
    """
    Fallback recommendations when we don't have enough personalized ones
    """
    return list(Product.objects.filter(is_active=True).exclude(
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
    product = get_object_or_404(Product, id=product_id, is_active=True)
    product_images = product.images.all().prefetch_related('variants__feature')
    variants = product.variants.select_related('feature_option__feature')

    # Build feature_data with enhanced structure for image sync
    feature_map = {}
    for variant in variants:
        feature_name = variant.feature_option.feature.name
        feature_option = variant.feature_option

        if feature_name not in feature_map:
            feature_map[feature_name] = {}

        feature_map[feature_name][feature_option.value] = {
            'id': feature_option.id,
            'value': feature_option.value,
            'feature_name': feature_name,
            'color_code': feature_option.color_code if hasattr(feature_option, 'color_code') else None
        }

    # Convert to sorted lists for template
    feature_data = {}
    for feature_name, options in feature_map.items():
        feature_data[feature_name] = sorted(list(options.values()), key=lambda x: x['value'])

    # Build image-feature mapping for JavaScript
    image_data = []

    # Add main product image with default features if any
    main_image_features = {}

    image_data.append({
        'url': product.image.url,
        'features': main_image_features,
        'is_main': True,
        'alt_text': f"{product.name}"
    })

    # Add variant images with their features
    for img in product_images:
        if img.variants.exists():
            image_features = {}
            feature_display = []

            for variant in img.variants.all():
                feature_name = variant.feature.name
                feature_value = variant.value
                image_features[feature_name] = feature_value
                feature_display.append(f"{feature_name}: {feature_value}")

            image_data.append({
                'url': img.image.url,
                'features': image_features,
                'is_main': False,
                'alt_text': img.alt_text or f"{product.name} - {', '.join(feature_display)}",
                'feature_display': ', '.join(feature_display)
            })

    # Store
    seller_store = Store.objects.filter(owner=product.seller, status='active').first()

    # Record view
    if request.user.is_authenticated:
        ProductView.objects.get_or_create(user=request.user, product=product)
        log_admin_action(
            request.user,
            action_type='product_view',
            message=f"Viewed product: {product.name}",
            model='Product',
            object_id=product.id
        )
    else:
        recently_viewed = request.session.get('recently_viewed', [])
        if product.id not in recently_viewed:
            recently_viewed.insert(0, product.id)
            if len(recently_viewed) > 10:
                recently_viewed = recently_viewed[:10]
            request.session['recently_viewed'] = recently_viewed

    # Recommended products
    # ----------------------------------------------------
    # Recommended products (Also-bought first, then top-selling in root tree)
    # ----------------------------------------------------
    RECOMMENDATION_LIMIT = 12

    # Build category scope: root category of this product, and ALL descendants
    category_ids = []
    if product.category:
        root = product.category.get_root()
        category_ids = [root.id] + [c.id for c in root.get_all_subcategories()]

    selected_ids = []
    recommended_items = []

    # 1) PRIORITY: "Bought together" (co-purchased in same orders)
    try:
        from orders.models import OrderItem  # import here to avoid circular imports

        order_ids = (
            OrderItem.objects
            .filter(product=product)
            .values_list("order_id", flat=True)
            .distinct()
        )

        also_bought_rows = (
            OrderItem.objects
            .filter(order_id__in=order_ids)
            .exclude(product=product)
            .values("product_id")
            .annotate(freq=Count("id"))
            .order_by("-freq")
        )

        also_bought_ids = [r["product_id"] for r in also_bought_rows]

        if also_bought_ids:
            also_bought_qs = Product.objects.filter(
                is_active=True,
                id__in=also_bought_ids,
            ).exclude(id=product.id)

            # Keep them relevant: if product has a category tree, constrain to it
            if category_ids:
                also_bought_qs = also_bought_qs.filter(category_id__in=category_ids)

            also_bought_qs = with_display_images(also_bought_qs.select_related("category"))

            # Preserve frequency order (because id__in doesn't preserve order)
            also_bought_map = {p.id: p for p in also_bought_qs}
            for pid in also_bought_ids:
                if pid in also_bought_map and pid not in selected_ids:
                    recommended_items.append(also_bought_map[pid])
                    selected_ids.append(pid)
                    if len(recommended_items) >= RECOMMENDATION_LIMIT:
                        break

    except Exception:
        # If orders app isn't ready / any issue, just skip also-bought
        pass

    # 2) FILL: Top-selling in the SAME ROOT TREE (root + descendants)
    if len(recommended_items) < RECOMMENDATION_LIMIT:
        fallback_qs = Product.objects.filter(is_active=True).exclude(
            id__in=[product.id] + selected_ids
        )

        if category_ids:
            fallback_qs = fallback_qs.filter(category_id__in=category_ids)
        elif product.category_id:
            # If for some reason no tree was built, at least stay in same category
            fallback_qs = fallback_qs.filter(category_id=product.category_id)

        fallback_qs = with_display_images(
            fallback_qs.select_related("category").order_by("-sold_count", "-created_at")
        )[: (RECOMMENDATION_LIMIT - len(recommended_items))]

        recommended_items.extend(list(fallback_qs))

    # Featured celebrities
    featured_celebrities = CelebrityFeature.objects.filter(products=product)[:8]

    # Clean specifications
    cleaned_specs = []
    if product.specifications:
        for line in product.specifications.splitlines():
            if ':' in line:
                raw_key, value = line.split(':', 1)
                clean_key = re.sub(r'^[^a-zA-Z0-9]*(.*?)[^a-zA-Z0-9]*$', r'\1', raw_key).strip()
                cleaned_specs.append((clean_key, value.strip()))

    # Description handling
    description_text = product.description or ""
    short_description = description_text[:800]
    description_truncated = len(description_text) > 800
    if description_truncated:
        last_space = short_description.rfind(' ')
        if last_space != -1:
            short_description = short_description[:last_space]

    # ✅ ANALYTICS: Track product view
    session_key = request.session.session_key
    if not session_key:
        request.session.create()
        session_key = request.session.session_key

    track_event(
        session_key=session_key,
        event_type="product_view",
        user=request.user if request.user.is_authenticated else None,
        store=product.store,
        product=product,
        path=request.path,
        referrer=request.META.get('HTTP_REFERER', ''),
    )

    # Reviews
    reviews = Review.objects.filter(product=product)
    user_review = Review.objects.filter(product=product,
                                        user=request.user).first() if request.user.is_authenticated else None
    form = ReviewForm(instance=user_review)
    avg_rating = reviews.aggregate(avg=Avg('rating'))['avg'] or 0
    review_count = reviews.count()
    user_rating = user_review.rating if user_review else 0

    # Address handling
    address_display = ""
    address = None
    if request.user.is_authenticated:
        address = Address.objects.filter(user=request.user).first()
        if address:
            parts = [
                address.address1,
                address.address2,
                str(address.country) if address.country else None
            ]
            address_display = ', '.join(part for part in parts if part)

    # Chat messages
    messages = []
    if request.user.is_authenticated and request.user != product.seller:
        thread = ChatThread.objects.filter(
            participants=request.user
        ).filter(
            participants=product.seller
        ).first()
        if thread:
            messages = ChatMessage.objects.filter(thread=thread).select_related('sender').order_by('timestamp')

    # Get user's wishlist product IDs
    user_wishlist_product_ids = []
    if request.user.is_authenticated:
        user_wishlist_product_ids = list(
            Wishlist.objects.filter(user=request.user).values_list('product_id', flat=True)
        )

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
        'image_data': image_data,  # New: structured image data with features
        'user_wishlist_product_ids': user_wishlist_product_ids,
        'store': seller_store,  # Add this for the template references
    })


def product_quick_view(request, product_id):
    product = get_object_or_404(Product, id=product_id, is_active=True)
    return render(request, 'marketplace/partials/product_quick_view.html', {'product': product})


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
            is_active=True  # Assuming you have an is_active field on Product
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


def used_products_view(request):
    """
    View to display all used products with filtering and pagination.
    """
    # Get all used products that are active
    products = Product.objects.filter(
        used=True,
        is_active=True
    ).select_related('category', 'store', 'seller').order_by('-created_at')

    # Get all categories for filtering
    categories = Category.objects.all()

    # Apply filters based on GET parameters
    category_filter = request.GET.get('category')
    if category_filter:
        products = products.filter(category__id=category_filter)

    # Price range filtering
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')

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

    # Search functionality
    search_query = request.GET.get('search')
    if search_query:
        products = products.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(specifications__icontains=search_query)
        )

    # Sorting options
    sort_by = request.GET.get('sort', '-created_at')
    if sort_by in ['price', '-price', 'name', '-name', 'created_at', '-created_at']:
        products = products.order_by(sort_by)

    # Pagination
    paginator = Paginator(products, 12)  # Show 12 products per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'products': page_obj,
        'categories': categories,
        'current_category': category_filter,
        'search_query': search_query,
        'min_price': min_price,
        'max_price': max_price,
        'sort_by': sort_by,
        'total_products': products.count(),
    }

    return render(request, 'marketplace/used_products.html', context)


def category_products(request, slug):
    """
       Full-featured version with search, sorting, and pagination.
       Best for: Large catalogs (100+ products)
       """
    category = get_object_or_404(Category, id=slug)

    # Get all descendants
    all_subcategories = category.get_all_subcategories()
    related_category_ids = [category.id] + [sub.id for sub in all_subcategories]

    # Base queryset
    products = Product.objects.filter(
        category_id__in=related_category_ids,
        is_active=True
    ).select_related('category', 'seller')

    # Search within category
    search_query = request.GET.get('q', '').strip()
    if search_query:
        products = products.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(category__name__icontains=search_query)
        )

    # Sorting
    sort_by = request.GET.get('sort', '-created_at')
    valid_sorts = {
        'newest': '-created_at',
        'oldest': 'created_at',
        'price_low': 'price',
        'price_high': '-price',
        'name_az': 'name',
        'name_za': '-name',
        'popular': '-sold_count',
    }

    sort_order = valid_sorts.get(sort_by, '-created_at')
    products = products.order_by(sort_order)

    # Pagination
    items_per_page = int(request.GET.get('per_page', 24))
    items_per_page = min(items_per_page, 100)  # Max 100 items per page

    paginator = Paginator(products, items_per_page)
    page = request.GET.get('page', 1)

    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    immediate_subcategories = category.get_subcategories()

    return render(request, 'marketplace/category_products.html', {
        'category': category,
        'subcategories': immediate_subcategories,
        'products': page_obj.object_list,
        'page_obj': page_obj,
        'total_products': paginator.count,
        'search_query': search_query,
        'current_sort': sort_by,
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
            Q(tags__name__icontains=search_query)
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


CART_TAX_RATE = getattr(settings, "CART_TAX_RATE", Decimal("0.00"))


def _resolve_active_cart_for_user(user):
    """
    If user is in an active SocialCart (joined + open/checkout), use that cart.
    Otherwise use/get their personal cart.
    Non-owner members are allowed to add items.
    """
    social = (
        SocialCart.objects
        .filter(
            is_active=True,
            status__in=['open', 'checkout'],
            members__user=user,
            members__status='joined',
        )
        .select_related('cart')
        .order_by('-created_at')
        .first()
    )
    if social:
        return social.cart, social
    cart, _ = Cart.objects.get_or_create(user=user)
    return cart, None


def _coerce_int(v, default=1, lo=1, hi=99):
    try:
        n = int(v)
    except Exception:
        n = default
    return max(lo, min(hi, n))


def _collect_selected_features(request):
    """
    Collect dynamic feature selections from request.

    Supports:
      - JSON body: { "selected_features": {...} } or { "features": {...} }
      - FORM body: selected_features='{"color":"Red"}'
      - Fallback: fields named feature_color, feature_size, etc.
    """
    selected_features = {}

    # JSON body
    if request.content_type and "application/json" in request.content_type:
        try:
            payload = json.loads(request.body.decode() or "{}")
        except Exception:
            payload = {}
        selected_features = (
                                    payload.get("selected_features")
                                    or payload.get("features")
                                    or {}
                            ) or {}
        # Ensure dict
        if not isinstance(selected_features, dict):
            selected_features = {}
        return selected_features

    # FORM body (x-www-form-urlencoded / multipart)
    raw_feats = (
            request.POST.get("selected_features")
            or request.POST.get("features")
    )

    if raw_feats:
        try:
            parsed = json.loads(raw_feats)
            if isinstance(parsed, dict):
                selected_features = parsed
        except Exception:
            selected_features = {}

    # Fallback: look for prefixed dynamic names if we didn't get JSON
    if not selected_features:
        # e.g. feature_color = "Red"
        dynamic = {
            k.replace("feature_", ""): v
            for k, v in request.POST.items()
            if k.startswith("feature_")
        }
        if dynamic:
            selected_features = dynamic

    return selected_features or {}


# ============================================================================
# CART VIEWS WITH ANALYTICS
# ============================================================================

@login_required
@require_POST
def add_to_cart(request, product_id):
    """
    FIXED: Add item to cart (normal or social) with permission checks
    """
    from analytics.services import track_event

    product = get_object_or_404(Product, id=product_id, is_active=True)
    user_cart, _ = Cart.objects.get_or_create(user=request.user)

    # Get cart type from request
    cart_type = request.POST.get('cart_type', 'normal')

    if cart_type not in ['normal', 'social']:
        return JsonResponse({
            'success': False,
            'message': 'Invalid cart type'
        }, status=400)

    # If adding to social cart, find and verify access
    if cart_type == 'social':
        social = None

        # Check if user owns a social cart
        try:
            social = user_cart.social
            if not social or not social.is_active or social.status not in ('open', 'checkout'):
                social = None
        except (SocialCart.DoesNotExist, AttributeError):
            pass

        # If not owner, check if member
        if not social:
            try:
                member = CartMember.objects.filter(
                    user=request.user,
                    status='joined'
                ).select_related('social_cart').first()

                if member and member.social_cart.is_active:
                    social = member.social_cart
            except Exception:
                pass

        # No accessible social cart found
        if not social:
            return JsonResponse({
                'success': False,
                'message': 'No active social cart available'
            }, status=403)

        # Check if user can add items
        member = social.members.filter(user=request.user).first()
        if not member or member.status != 'joined':
            return JsonResponse({
                'success': False,
                'message': 'You do not have permission to add items'
            }, status=403)

        # Use the social cart's main cart
        target_cart = social.cart
    else:
        target_cart = user_cart

    # Get quantity and features
    try:
        quantity = int(request.POST.get('quantity', 1))
        if quantity < 1:
            quantity = 1
    except ValueError:
        quantity = 1

    selected_features = {}
    features_json = request.POST.get('selected_features', '{}')
    try:
        import json
        selected_features = json.loads(features_json)
    except:
        pass

    # Add or update cart item
    with transaction.atomic():
        cart_item, created = CartItem.objects.get_or_create(
            cart=target_cart,
            product=product,
            selected_features=selected_features,
            cart_type=cart_type,
            defaults={
                'quantity': quantity,
                'added_by': request.user
            }
        )

        if not created:
            cart_item.quantity += quantity
            cart_item.save(update_fields=['quantity', 'updated_at'])

        # Recalculate shares if social cart
        if cart_type == 'social':
            try:
                if social.split_mode == 'by_items':
                    social.compute_shares_by_items()
            except Exception:
                pass

    # Track analytics
    try:
        track_event(
            session_key=request.session.session_key or request.user.username,
            event_type="add_to_cart",
            user=request.user,
            store=product.store,
            product=product,
            path=request.path,
        )
    except Exception:
        pass

    # Get counts for response
    normal_count = target_cart.items.filter(cart_type='normal').aggregate(
        total=Sum('quantity')
    )['total'] or 0

    social_count = target_cart.items.filter(cart_type='social').aggregate(
        total=Sum('quantity')
    )['total'] or 0

    return JsonResponse({
        'success': True,
        'message': f'Added to {cart_type} cart',
        'cart_type': cart_type,
        'normal_count': normal_count,
        'social_count': social_count,
    })

def cart_preview(request):
    """
    Returns a small HTML snippet (partial) with up to 5 items + subtotal.
    """
    ctx = build_cart_context(request, limit=5)
    return render(request, "marketplace/partials/cart_preview.html", ctx)


@login_required
def cart_view(request):
    """
    FIXED: Complete cart view with proper member visibility for social carts
    """
    # Get or create user's cart
    user_cart, _ = Cart.objects.get_or_create(user=request.user)

    # Get normal cart items from user's own cart
    normal_items = (
        user_cart.items.filter(cart_type='normal')
        .select_related('product', 'product__store', 'product__category')
        .order_by('-created_at')
    )

    # Initialize social cart variables
    social = None
    social_items = []
    is_social_active = False
    is_owner = False
    is_blocked = False
    can_modify_social = False
    my_share = None
    social_members = []
    cart_to_use = user_cart  # Which cart to use for display

    # CRITICAL FIX: Find social cart in TWO ways
    # Method 1: User owns a social cart
    try:
        social = user_cart.social
        if social and social.is_active and social.status in ('open', 'checkout'):
            is_social_active = True
            is_owner = True
            cart_to_use = user_cart
    except (SocialCart.DoesNotExist, AttributeError):
        pass

    # Method 2: User is a MEMBER of a social cart (not owner)
    if not is_social_active:
        try:
            member = CartMember.objects.filter(
                user=request.user,
                status='joined'
            ).select_related('social_cart', 'social_cart__cart').first()

            if member and member.social_cart.is_active and member.social_cart.status in ('open', 'checkout'):
                social = member.social_cart
                is_social_active = True
                is_owner = False
                # Use the owner's cart for social items
                cart_to_use = social.cart
        except Exception as e:
            logger.error(f"Error checking social cart membership: {e}")

    # If we found an active social cart (owned or member)
    if is_social_active and social:
        try:
            # ✅ Build invite link (absolute)
            social_invite_link = request.build_absolute_uri(
                reverse("marketplace:join_open_social_cart", kwargs={"invite_code": social.invite_code})
            )

            # ✅ Generate QR (base64 data URL)
            social_cart_qr = generate_qr_code(social_invite_link)

            # Get social items from the social cart's main cart
            social_items = (
                social.cart.items.filter(cart_type='social')
                .select_related('product', 'product__store', 'product__category', 'added_by')
                .order_by('-created_at')
            )

            # Get current user's membership details
            member = social.members.filter(user=request.user).first()
            if member:
                is_blocked = member.status == 'blocked'

                # Check modification permissions
                if hasattr(member, 'can_modify_items'):
                    can_modify_social = member.can_modify_items()
                else:
                    can_modify_social = member.status == 'joined'

                # Get payment share
                try:
                    my_share = social.payment_shares.filter(
                        member=member,
                        is_active=True
                    ).first()
                except Exception:
                    pass

            # Get all members
            social_members = social.members.filter(
                status__in=['joined', 'blocked']
            ).select_related('user').order_by('-joined_at')

            # Add permission flags to social items
            for item in social_items:
                # Check if item has can_user_modify method
                if hasattr(item, 'can_user_modify'):
                    item.can_modify = item.can_user_modify(request.user)
                    item.can_remove = item.can_user_modify(request.user)
                else:
                    # Fallback logic
                    is_item_owner = item.added_by == request.user
                    item.can_modify = (is_owner or (is_item_owner and not is_blocked))
                    item.can_remove = (is_owner or (is_item_owner and not is_blocked))

        except Exception as e:
            logger.error(f"Error loading social cart items: {e}")
            social_items = []

    # Add permission flags to normal items
    for item in normal_items:
        item.can_modify = True
        item.can_remove = True

    # Calculate totals
    CART_TAX_RATE = Decimal("0.000")

    normal_subtotal = sum(item.product.price * item.quantity for item in normal_items)
    normal_tax = normal_subtotal * CART_TAX_RATE
    normal_total = normal_subtotal + normal_tax
    normal_count = sum(item.quantity for item in normal_items)

    social_subtotal = sum(item.product.price * item.quantity for item in social_items)
    social_tax = social_subtotal * CART_TAX_RATE
    social_total = social_subtotal + social_tax
    social_count = sum(item.quantity for item in social_items)

    cart_count = normal_count + social_count

    # # QR + invite link
    # social_invite_link = None
    # social_cart_qr = None

    context = {
        'cart': user_cart,
        'normal_items': normal_items,
        'social_items': social_items,
        'normal_subtotal': normal_subtotal,
        'normal_tax': normal_tax,
        'normal_total': normal_total,
        'social_subtotal': social_subtotal,
        'social_tax': social_tax,
        'social_total': social_total,
        'normal_count': normal_count,
        'social_count': social_count,
        'cart_count': cart_count,
        'social': social,
        'is_social_active': is_social_active,
        'is_owner': is_owner,
        'is_blocked': is_blocked,
        'can_modify_social': can_modify_social,
        'my_share': my_share,
        'social_members': social_members,
        'social_invite_link': social_invite_link,
        'social_cart_qr': social_cart_qr,

    }

    return render(request, 'marketplace/cart_detail.html', context)

def generate_qr_code(data):
    """
    Generate QR code and return as base64 string.
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    buffer = BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)

    img_str = base64.b64encode(buffer.read()).decode()
    return f"data:image/png;base64,{img_str}"


@login_required
@require_POST
def move_cart_item(request):
    """
    ENHANCED: Move item between normal and social carts with debug logging
    """
    item_id = request.POST.get('item_id')
    target_cart_type = request.POST.get('target_cart_type')

    logger.info(f"move_cart_item called by {request.user.username}: item_id={item_id}, target={target_cart_type}")

    if not item_id or target_cart_type not in ['normal', 'social']:
        logger.warning(f"Invalid parameters: item_id={item_id}, target={target_cart_type}")
        return JsonResponse({
            'success': False,
            'message': 'Invalid parameters'
        }, status=400)

    try:
        # Get user's cart
        user_cart = Cart.objects.get(user=request.user)
        logger.info(f"User cart ID: {user_cart.id}")

        # Get the item
        try:
            cart_item = CartItem.objects.select_related(
                'cart', 'cart__user', 'product', 'added_by'
            ).get(id=item_id)
            logger.info(f"Found item: ID={cart_item.id}, cart_type={cart_item.cart_type}, cart_id={cart_item.cart.id}")
        except CartItem.DoesNotExist:
            logger.error(f"Item not found: {item_id}")
            return JsonResponse({
                'success': False,
                'message': 'Item not found'
            }, status=404)

        # Check if user can modify this item
        can_modify = False

        # Case 1: Item is in user's own normal cart
        if cart_item.cart.user == request.user and cart_item.cart_type == 'normal':
            can_modify = True
            logger.info("✓ User can modify - item in own normal cart")

        # Case 2: Item is in social cart
        elif cart_item.cart_type == 'social':
            try:
                social = cart_item.cart.social
                member = social.members.filter(user=request.user).first()

                if member:
                    if social.owner == request.user:
                        can_modify = True
                        logger.info("✓ User can modify - is social cart owner")
                    elif cart_item.added_by == request.user and member.status == 'joined':
                        can_modify = True
                        logger.info("✓ User can modify - member and added this item")
                    else:
                        logger.warning(
                            f"Cannot modify: added_by={cart_item.added_by}, user={request.user}, status={member.status}")
                else:
                    logger.warning(f"User is not a member of this social cart")
            except (SocialCart.DoesNotExist, AttributeError) as e:
                logger.error(f"Error checking social cart: {e}")

        if not can_modify:
            logger.warning("Permission denied to modify item")
            return JsonResponse({
                'success': False,
                'message': 'You do not have permission to move this item'
            }, status=403)

        # Check if already in target cart type
        if cart_item.cart_type == target_cart_type:
            logger.warning(f"Item already in {target_cart_type} cart")
            return JsonResponse({
                'success': False,
                'message': f'Item is already in {target_cart_type} cart'
            }, status=400)

        # If moving TO social cart, find and verify access
        if target_cart_type == 'social':
            social = None
            target_cart = None

            # Method 1: Check if user owns a social cart
            logger.info("Checking if user owns a social cart...")
            try:
                social = user_cart.social
                if social and social.is_active and social.status in ('open', 'checkout'):
                    target_cart = user_cart
                    logger.info(f"✓ Found owned social cart: ID={social.id}")
                else:
                    logger.info(
                        f"Owned social cart not active or wrong status: active={social.is_active if social else 'N/A'}, status={social.status if social else 'N/A'}")
                    social = None
            except (SocialCart.DoesNotExist, AttributeError) as e:
                logger.info(f"User doesn't own a social cart: {e}")

            # Method 2: Check if user is a MEMBER
            if not social:
                logger.info("Checking if user is a member of a social cart...")
                try:
                    member = CartMember.objects.filter(
                        user=request.user,
                        status='joined'
                    ).select_related('social_cart', 'social_cart__cart').first()

                    logger.info(f"Member lookup result: {member}")

                    if member:
                        logger.info(
                            f"Found membership: social_cart_id={member.social_cart.id}, role={member.role}, status={member.status}")
                        logger.info(
                            f"Social cart: active={member.social_cart.is_active}, status={member.social_cart.status}")

                        if member.social_cart.is_active and member.social_cart.status in ('open', 'checkout'):
                            social = member.social_cart
                            target_cart = social.cart
                            logger.info(f"✓ Found member social cart: ID={social.id}, target_cart={target_cart.id}")
                        else:
                            logger.warning(
                                f"Member's social cart not accessible: active={member.social_cart.is_active}, status={member.social_cart.status}")
                    else:
                        logger.warning("No active 'joined' membership found")

                except Exception as e:
                    logger.error(f"Error finding member social cart: {e}", exc_info=True)

            # Check results
            logger.info(f"Social cart lookup complete: social={social}, target_cart={target_cart}")

            if not social or not target_cart:
                logger.error("No accessible social cart found - returning 403")
                return JsonResponse({
                    'success': False,
                    'message': 'No active social cart available'
                }, status=403)

            # Verify user can add items
            member = social.members.filter(user=request.user).first()
            logger.info(f"Final member check: member={member}, status={member.status if member else 'N/A'}")

            if not member or member.status != 'joined':
                logger.error(f"Member cannot add items: member={member}, status={member.status if member else 'N/A'}")
                return JsonResponse({
                    'success': False,
                    'message': 'You cannot add items to this social cart'
                }, status=403)

            logger.info(f"✓ All checks passed - proceeding with move to social cart {social.id}")

        # If moving TO normal cart
        else:
            target_cart = user_cart
            logger.info(f"Moving to normal cart: {target_cart.id}")

        # Move the item
        logger.info(f"Moving item {cart_item.id} from cart {cart_item.cart.id} to cart {target_cart.id}")

        with transaction.atomic():
            old_cart_type = cart_item.cart_type
            old_cart = cart_item.cart

            cart_item.cart = target_cart
            cart_item.cart_type = target_cart_type
            cart_item.save(update_fields=['cart', 'cart_type', 'updated_at'])

            logger.info(f"✓ Item moved successfully")

            # Recalculate shares
            if target_cart_type == 'social' or old_cart_type == 'social':
                try:
                    if target_cart_type == 'social':
                        social_to_update = target_cart.social
                    else:
                        social_to_update = old_cart.social

                    if social_to_update.split_mode == 'by_items':
                        social_to_update.compute_shares_by_items()
                        logger.info(f"✓ Recalculated shares for social cart {social_to_update.id}")
                except Exception as e:
                    logger.error(f"Error recalculating shares: {e}")

        # Get counts
        normal_count = user_cart.items.filter(cart_type='normal').aggregate(
            total=Sum('quantity')
        )['total'] or 0

        social_count = 0
        try:
            social = user_cart.social
            if social and social.is_active:
                social_count = social.cart.items.filter(cart_type='social').aggregate(
                    total=Sum('quantity')
                )['total'] or 0
        except (SocialCart.DoesNotExist, AttributeError):
            try:
                member = CartMember.objects.filter(
                    user=request.user,
                    status='joined'
                ).select_related('social_cart').first()

                if member and member.social_cart.is_active:
                    social_count = member.social_cart.cart.items.filter(
                        cart_type='social'
                    ).aggregate(total=Sum('quantity'))['total'] or 0
            except Exception:
                pass

        logger.info(f"✓ Move complete. Counts: normal={normal_count}, social={social_count}")

        return JsonResponse({
            'success': True,
            'message': f'Item moved to {target_cart_type} cart',
            'item_id': cart_item.id,
            'normal_count': normal_count,
            'social_count': social_count,
        })

    except Cart.DoesNotExist:
        logger.error("User cart not found")
        return JsonResponse({
            'success': False,
            'message': 'Cart not found'
        }, status=404)
    except Exception as e:
        logger.error(f"Unexpected error in move_cart_item: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': 'An error occurred while moving the item'
        }, status=500)

@require_GET
def get_cart_count(request):
    """
    AJAX endpoint to retrieve cart counts and totals.

    Returns cart summary for authenticated users (including social carts) and guests.
    Calculates subtotal, tax, and final total.

    Returns:
        JsonResponse: {
            'success': bool,
            'cart_count': int (total quantity),
            'cart_total': str (formatted decimal),
            'tax_amount': str (formatted decimal),
            'final_total': str (formatted decimal)
        }

    Security:
        - GET only (safe, idempotent operation)
        - No CSRF needed for GET requests
        - Handles both authenticated and anonymous users
    """
    CART_TAX_RATE = Decimal("0.085")

    try:
        if request.user.is_authenticated:
            social = _resolve_active_social_for(request.user)
            if social and social.cart_id:
                cart = social.cart
            else:
                cart = Cart.objects.filter(user=request.user).first()

            if cart:
                items = CartItem.objects.filter(cart=cart)
                cart_count = sum(i.quantity for i in items)
                cart_total = sum(i.product.price * i.quantity for i in items)
            else:
                cart_count = 0
                cart_total = Decimal("0")
        else:
            sess = request.session.get("cart", {})
            cart_count = sum(int(item.get("quantity", 1) or 1) for item in sess.values())
            cart_total = Decimal("0")
            for key, item in sess.items():
                try:
                    pid = int(key.split("::", 1)[0])
                    prod = Product.objects.get(id=pid, is_active=True)
                    cart_total += prod.price * int(item.get("quantity", 1) or 1)
                except Product.DoesNotExist:
                    continue

        tax_amount = cart_total * CART_TAX_RATE
        final_total = cart_total + tax_amount

        return JsonResponse(
            {
                "success": True,
                "cart_count": cart_count,
                "cart_total": f"{cart_total:.2f}",
                "tax_amount": f"{tax_amount:.2f}",
                "final_total": f"{final_total:.2f}",
            }
        )
    except Exception as e:
        logger.error(f"Error in get_cart_count: {str(e)}", exc_info=True)
        return JsonResponse(
            {"success": False, "message": "Error retrieving cart information"}
        )


def get_cart_context(request):
    """
    Lightweight cart summary you can include in other views.
    Prefers SocialCart when present.
    """
    if request.user.is_authenticated:
        social = _resolve_active_social_for(request.user)
        cart = social.cart if social else Cart.objects.filter(user=request.user).first()
        if cart:
            cart_items = CartItem.objects.filter(cart=cart)
            cart_count = sum(item.quantity for item in cart_items)
            cart_total = sum(item.product.price * item.quantity for item in cart_items)
        else:
            cart_count = 0
            cart_total = Decimal("0")
    else:
        sess = request.session.get("cart", {})
        cart_count = sum(int(item.get("quantity", 1) or 1) for item in sess.values())
        cart_total = Decimal("0")
        for key, item in sess.items():
            try:
                pid = int(key.split("::", 1)[0])
                prod = Product.objects.get(id=pid, is_active=True)
                cart_total += prod.price * int(item.get("quantity", 1) or 1)
            except Product.DoesNotExist:
                continue

    return {"cart_count": cart_count, "cart_total": cart_total}


@login_required
@require_POST
def update_cart_quantity(request):
    """
    FIXED: Update cart item quantity with permission checks
    """
    cart_item_id = request.POST.get('cart_item_id')
    quantity = request.POST.get('quantity')

    if not cart_item_id or not quantity:
        return JsonResponse({
            'success': False,
            'message': 'Missing required parameters'
        }, status=400)

    try:
        quantity = int(quantity)
        if quantity < 1:
            return JsonResponse({
                'success': False,
                'message': 'Quantity must be at least 1'
            }, status=400)
    except ValueError:
        return JsonResponse({
            'success': False,
            'message': 'Invalid quantity'
        }, status=400)

    try:
        item = CartItem.objects.select_related(
            'cart', 'cart__user', 'product', 'added_by'
        ).get(id=cart_item_id)

        can_modify = False

        # Permission check for normal cart
        if item.cart_type == 'normal' and item.cart.user == request.user:
            can_modify = True

        # Permission check for social cart
        elif item.cart_type == 'social':
            try:
                social = item.cart.social
                member = social.members.filter(user=request.user).first()

                if member:
                    # Owner can modify any item
                    if social.owner == request.user:
                        can_modify = True
                    # Non-blocked member can modify their own items
                    elif item.added_by == request.user and member.status == 'joined':
                        can_modify = True
            except (SocialCart.DoesNotExist, AttributeError):
                pass

        if not can_modify:
            return JsonResponse({
                'success': False,
                'message': 'You do not have permission to modify this item'
            }, status=403)

        # Update quantity
        with transaction.atomic():
            item.quantity = quantity
            item.save(update_fields=['quantity', 'updated_at'])

            # Recalculate shares for social cart
            if item.cart_type == 'social':
                try:
                    social = item.cart.social
                    if social.split_mode == 'by_items':
                        social.compute_shares_by_items()
                except Exception as e:
                    logger.error(f"Error recalculating shares: {e}")

        return JsonResponse({
            'success': True,
            'message': 'Quantity updated',
            'new_quantity': quantity,
            'subtotal': float(item.product.price * quantity)
        })

    except CartItem.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Item not found'
        }, status=404)
    except Exception as e:
        logger.error(f"Error updating quantity: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': 'An error occurred'
        }, status=500)


@login_required
@require_POST
def remove_cart_item(request):
    """
    FIXED: Remove cart item with proper permission checks for both normal and social carts
    """
    item_id = request.POST.get('item_id')

    if not item_id:
        return JsonResponse({
            'success': False,
            'message': 'Invalid payload'
        }, status=400)

    try:
        item = CartItem.objects.select_related(
            'cart', 'cart__user', 'product', 'added_by'
        ).get(id=item_id)

        can_remove = False

        # Permission check for normal cart items
        if item.cart_type == 'normal' and item.cart.user == request.user:
            can_remove = True

        # Permission check for social cart items
        elif item.cart_type == 'social':
            try:
                social = item.cart.social
                member = social.members.filter(user=request.user).first()

                if member:
                    # Owner can remove any item
                    if social.owner == request.user:
                        can_remove = True
                    # Non-blocked member can remove their own items
                    elif item.added_by == request.user and member.status == 'joined':
                        can_remove = True
            except (SocialCart.DoesNotExist, AttributeError):
                pass

        if not can_remove:
            return JsonResponse({
                'success': False,
                'message': 'You do not have permission to remove this item'
            }, status=403)

        # Delete the item
        with transaction.atomic():
            cart_type = item.cart_type
            item.delete()

            # Recalculate shares for social cart
            if cart_type == 'social':
                try:
                    social = item.cart.social
                    if social.split_mode == 'by_items':
                        social.compute_shares_by_items()
                except Exception as e:
                    logger.error(f"Error recalculating shares: {e}")

        return JsonResponse({
            'success': True,
            'message': 'Item removed successfully'
        })

    except CartItem.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Item not found'
        }, status=404)
    except Exception as e:
        logger.error(f"Error removing cart item: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': 'An error occurred while removing the item'
        }, status=500)


# ============================================================================
# WISHLIST VIEWS WITH ANALYTICS
# ============================================================================

@require_http_methods(["GET", "POST"])
@login_required
def toggle_wishlist(request, product_id):
    """
    Toggle wishlist item for a product.
    - If ?action=add_to_cart, add to cart and (optionally) remove from wishlist.
    - When adding to wishlist, capture last_known_price/stock for notifications.

     Analytics: Tracks add_to_cart when moving from wishlist to cart
    """

    product = get_object_or_404(Product, id=product_id)
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'

    # If user clicked 'Add to Cart' from wishlist
    if request.GET.get('action') == 'add_to_cart':
        cart, _ = Cart.objects.get_or_create(user=request.user)
        cart_item, created = CartItem.objects.get_or_create(
            cart=cart,
            product=product,
            defaults={'quantity': 1}
        )

        if not created:
            cart_item.quantity += 1
            cart_item.save(update_fields=['quantity'])

        # ANALYTICS: Track add to cart from wishlist
        track_event(
            session_key=request.session.session_key or request.user.username,
            event_type="add_to_cart",
            user=request.user,
            store=product.store,
            product=product,
            path=request.path,
        )

        # Remove from wishlist (optional)
        Wishlist.objects.filter(user=request.user, product=product).delete()

        messages.success(request, f"{product.name} added to cart.")
        return redirect('marketplace:my_wishlist')

    # Try to add (if not exists) or fetch (if exists so we can remove)
    wishlist_item, created = Wishlist.objects.get_or_create(
        user=request.user,
        product=product,
        defaults={
            'last_known_price': product.price,
            'last_known_stock': product.stock_quantity,
        }
    )

    if created:
        log_admin_action(
            request.user,
            action_type='wishlist_add',
            message=f"Added {product.name} to wishlist",
            model='Product',
            object_id=product.id
        )

        if is_ajax:
            return JsonResponse({
                'success': True,
                'status': 'added',
                'message': f"{product.name} added to your wishlist"
            })

        messages.success(request, f"{product.name} added to your wishlist.")
        return redirect('marketplace:my_wishlist')

    # If it already existed, this call is acting as "remove"
    wishlist_item.delete()
    log_admin_action(
        request.user,
        action_type='wishlist_remove',
        message=f"Removed {product.name} from wishlist",
        model='Product',
        object_id=product.id
    )

    if is_ajax:
        return JsonResponse({
            'success': True,
            'status': 'removed',
            'message': f"{product.name} removed from your wishlist"
        })

    messages.info(request, f"{product.name} removed from your wishlist.")
    return redirect('marketplace:my_wishlist')


@login_required
def my_wishlist(request):
    """Display user's wishlist with related product data."""
    items = Wishlist.objects.filter(user=request.user).select_related('product')
    return render(request, 'wishlist/my_wishlist.html', {'items': items})


@require_POST
def apply_promo_code(request):
    """
    AJAX endpoint to apply promotional codes to cart.

    Validates promo code, calculates discount, and stores in session.
    Supports both authenticated users and guest carts.

    POST Parameters:
        promo_code (str): Promotional code to apply (case-insensitive)

    Returns:
        JsonResponse: {
            'success': bool,
            'discount': str (formatted decimal),
            'total_price': str (subtotal after discount),
            'tax_amount': str,
            'final_total': str,
            'item_count': int,
            'message': str
        }

    Security:
        - CSRF protection enabled (removed @csrf_exempt)
        - Requires valid CSRF token from frontend
        - Validates promo code existence and active status
        - Checks usage limits via is_valid() method
        - Input sanitization: strip() and upper()

    Note:
        Frontend must include CSRF token in POST requests:
        headers: {'X-CSRFToken': getCookie('csrftoken')}
    """
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
                    product = Product.objects.get(id=pid, is_active=True)
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
        logger.error(f"Error in apply_promo_code: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': 'Unable to apply promo code. Please try again.'
        })


def trending_products_view(request):
    """
    Display trending products with celebrity features and sorting options
    """
    sort_by = request.GET.get('sort', 'trending')

    # Annotate products with total stock
    trending_products = Product.objects.filter(is_trending=True, is_active=True).annotate(
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
    return CelebrityFeature.objects.filter(is_active=True).prefetch_related('products').order_by('featured_order',
                                                                                                 '-created_at')


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
        products = Product.objects.filter(is_active=True)

        if query:
            products = products.filter(
                Q(name__icontains=query) |
                Q(description__icontains=query) |
                Q(category__name__icontains=query)
            )

        if category_id:
            products = products.filter(category_id=category_id, is_active=True)

        if min_price:
            try:
                products = products.filter(price__gte=float(min_price), is_active=True)
            except ValueError:
                pass

        if max_price:
            try:
                products = products.filter(price__lte=float(max_price), is_active=True)
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
        log_admin_action(
            request.user,
            action_type='search',
            message=f"Search performed for: '{query}'",
            model='SearchHistory'
        )
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
                Q(description__icontains=query), is_active=True
            )

            # If you have categories, also search there
            if hasattr(Product, 'category'):
                products = products.filter(
                    Q(name__icontains=query) |
                    Q(description__icontains=query) |
                    Q(category__name__icontains=query), is_active=True
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
                    'price': str(format_price_for_user(product.price, request.user)),
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


@login_required
def share_cart(request):
    """
    Generate shareable cart link with QR code.

    Returns cart share URL and QR code for easy sharing.
    The QR code can be scanned to directly access the shared cart.

    Returns:
        JsonResponse: {
            'share_url': str (full URL to shared cart),
            'qr_code': str (base64 encoded PNG QR code),
            'qr_svg': str (optional SVG QR code)
        }

    Example Response:
        {
            "share_url": "https://example.com/cart/share/abc123",
            "qr_code": "iVBORw0KGgoAAAANSUhEUgAA..."
        }

    Frontend Usage:
        <img src="data:image/png;base64,{{ qr_code }}" alt="QR Code">
    """

    shared_cart, created = SharedCart.objects.get_or_create(user=request.user)
    share_url = request.build_absolute_uri(shared_cart.get_absolute_url())

    # Generate QR code
    try:
        qr_code_base64 = generate_qr_code(share_url, format='base64')
    except Exception as e:
        logger.error(f"Failed to generate QR code: {e}")
        qr_code_base64 = None

    return JsonResponse({
        'share_url': share_url,
        'qr_code': qr_code_base64
    })


def copy_shared_cart(request, token):
    """
    Copy items from a shared normal cart to user's cart.
    Shows preview page with QR code.
    """
    # Find the cart with this share token
    try:
        from marketplace.models import Cart as MarketplaceCart
        source_cart = MarketplaceCart.objects.get(share_token=token)
    except MarketplaceCart.DoesNotExist:
        messages.error(request, "Invalid or expired share link.")
        return redirect('marketplace:cart')

    # Get items from source cart
    source_items = source_cart.items.filter(cart_type='normal').select_related(
        'product', 'product__store'
    )

    if not source_items.exists():
        messages.error(request, "This shared cart is empty.")
        return redirect('marketplace:cart')

    # GET request - show preview
    if request.method == 'GET':
        # Calculate totals
        CART_TAX_RATE = Decimal("0.085")
        subtotal = sum(item.product.price * item.quantity for item in source_items)
        tax = subtotal * CART_TAX_RATE
        total = subtotal + tax

        # Generate QR code for this share link
        share_url = request.build_absolute_uri()
        qr_code = generate_qr_code(share_url)

        context = {
            'source_cart': source_cart,
            'source_items': source_items,
            'owner': source_cart.user,
            'subtotal': subtotal,
            'tax': tax,
            'total': total,
            'item_count': sum(item.quantity for item in source_items),
            'qr_code': qr_code,
            'share_url': share_url,
        }

        return render(request, 'marketplace/shared_cart_preview.html', context)

    # POST request - copy items
    elif request.method == 'POST':
        if not request.user.is_authenticated:
            messages.error(request, "Please log in to copy this cart.")
            return redirect('accounts:sign_in')

        # Don't copy your own cart to yourself
        if source_cart.user == request.user:
            messages.warning(request, "This is your own cart.")
            return redirect('marketplace:cart')

        # Copy items to user's cart
        user_cart, _ = Cart.objects.get_or_create(user=request.user)

        copied_count = 0
        with transaction.atomic():
            for source_item in source_items:
                # Check if item already exists
                existing_item = user_cart.items.filter(
                    product=source_item.product,
                    selected_features=source_item.selected_features,
                    cart_type='normal'
                ).first()

                if existing_item:
                    # Update quantity
                    existing_item.quantity += source_item.quantity
                    existing_item.save()
                else:
                    # Create new item
                    CartItem.objects.create(
                        cart=user_cart,
                        product=source_item.product,
                        quantity=source_item.quantity,
                        selected_features=source_item.selected_features,
                        cart_type='normal',
                        added_by=request.user
                    )

                copied_count += 1

        messages.success(
            request,
            f'Successfully copied {copied_count} item{"s" if copied_count != 1 else ""} to your cart!'
        )
        return redirect('marketplace:cart')

def about(request):
    return render(request, 'marketplace/about.html')


def careers_list(request):
    q = (request.GET.get("q") or "").strip()
    dept = (request.GET.get("dept") or "").strip()
    jobs = Career.objects.active()

    if q:
        jobs = jobs.filter(
            Q(title__icontains=q) |
            Q(location__icontains=q) |
            Q(department__icontains=q) |
            Q(summary__icontains=q) |
            Q(description__icontains=q)
        )

    if dept:
        jobs = jobs.filter(department=dept)

    # Template expects `jobs`
    return render(request, "careers/careers.html", {"jobs": jobs, "q": q, "dept": dept})


def career_detail(request, slug):
    job = get_object_or_404(Career.objects.active(), slug=slug)
    return render(request, "careers/detail.html", {"job": job})


MAX_RESUME_SIZE_MB = 5
ALLOWED_RESUME_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def careers_apply(request):
    """
    GET  -> show form (optionally prefilled via ?role=<slug>)
    POST -> save application and redirect to success
    """
    role_slug = request.GET.get("role") or request.POST.get("role")
    job = None
    if role_slug:
        job = get_object_or_404(Career.objects.active(), slug=role_slug)

    if request.method == "GET":
        return render(request, "careers/apply.html", {"job": job})

    # POST
    full_name = (request.POST.get("full_name") or "").strip()
    email = (request.POST.get("email") or "").strip()
    phone = (request.POST.get("phone") or "").strip()
    cover_letter = (request.POST.get("cover_letter") or "").strip()
    portfolio_url = (request.POST.get("portfolio_url") or "").strip()
    linkedin_url = (request.POST.get("linkedin_url") or "").strip()
    github_url = (request.POST.get("github_url") or "").strip()
    source = (request.POST.get("source") or "").strip()
    consent_privacy = request.POST.get("consent_privacy") == "on"
    resume = request.FILES.get("resume")

    errors = {}

    if not job:
        errors["role"] = "Please select a role to apply for."
    if not full_name:
        errors["full_name"] = "Your full name is required."
    if not email:
        errors["email"] = "Email is required."
    else:
        try:
            validate_email(email)
        except ValidationError:
            errors["email"] = "Please enter a valid email address."

    if not resume:
        errors["resume"] = "Please attach your resume (PDF, DOC, or DOCX)."
    else:
        # Basic file checks
        if hasattr(resume, "content_type") and resume.content_type not in ALLOWED_RESUME_TYPES:
            errors["resume"] = "Resume must be a PDF, DOC, or DOCX."
        if resume.size > MAX_RESUME_SIZE_MB * 1024 * 1024:
            errors["resume"] = f"Resume must be under {MAX_RESUME_SIZE_MB} MB."

    if not consent_privacy:
        errors["consent_privacy"] = "You must consent to our privacy policy to apply."

    if errors:
        messages.error(request, "Please correct the errors below.")
        context = {
            "job": job,
            "errors": errors,
            "form": {
                "full_name": full_name,
                "email": email,
                "phone": phone,
                "cover_letter": cover_letter,
                "portfolio_url": portfolio_url,
                "linkedin_url": linkedin_url,
                "github_url": github_url,
                "source": source,
                "consent_privacy": consent_privacy,
            },
        }
        return render(request, "careers/apply.html", context, status=400)

    app = CareerApplication.objects.create(
        job=job,
        full_name=full_name,
        email=email,
        phone=phone,
        resume=resume,
        cover_letter=cover_letter,
        portfolio_url=portfolio_url,
        linkedin_url=linkedin_url,
        github_url=github_url,
        source=source,
        consent_privacy=consent_privacy,
        ip_address=request.META.get("REMOTE_ADDR"),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:1000],
    )

    # Optional: Notify HR (configure EMAIL_* settings first)
    try:
        subject = f"[Careers] {app.full_name} applied for {job.title} ({app.application_code})"
        body = (
            f"Role: {job.title}\n"
            f"Applicant: {app.full_name}\n"
            f"Email: {app.email}\nPhone: {app.phone}\n"
            f"Source: {app.source}\n"
            f"Portfolio: {app.portfolio_url}\nLinkedIn: {app.linkedin_url}\nGitHub: {app.github_url}\n"
            f"Application code: {app.application_code}\n\n"
            f"Cover letter:\n{app.cover_letter}\n"
        )
        email_hr = getattr(settings, "HR_INBOX", "info@easymarket.vip")
        msg = EmailMessage(subject, body, to=[email_hr])
        if app.resume:
            app.resume.open("rb")
            msg.attach(os.path.basename(app.resume.name), app.resume.read(), "application/octet-stream")
        msg.send(fail_silently=True)
    except Exception:
        # Silent fail—app is saved; HR can view in admin
        pass

    return redirect("marketplace:career_apply_success", code=app.application_code)


def careers_apply_success(request, code):
    app = get_object_or_404(CareerApplication, application_code=code)
    return render(request, "careers/apply_success.html", {"app": app})


def press_list(request):
    q = (request.GET.get("q") or "").strip()
    cat = (request.GET.get("category") or "").strip()

    qs = PressRelease.objects.published()
    if q:
        qs = qs.filter(
            Q(title__icontains=q) |
            Q(subtitle__icontains=q) |
            Q(summary__icontains=q) |
            Q(body__icontains=q)
        )
    if cat:
        qs = qs.filter(category=cat)

    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "press/index.html", {
        "page_obj": page_obj,
        "releases": page_obj.object_list,
        "q": q,
        "category": cat,
    })


def press_detail(request, slug):
    obj = get_object_or_404(PressRelease.objects.published(), slug=slug)
    # Optional: next/prev for footer nav
    newer = PressRelease.objects.published().filter(publish_at__gt=obj.publish_at).order_by("publish_at").first()
    older = PressRelease.objects.published().filter(publish_at__lt=obj.publish_at).order_by("-publish_at").first()

    return render(request, "press/detail.html", {
        "pr": obj,
        "newer": newer,
        "older": older,
    })


def _is_staff(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)


@login_required
@user_passes_test(_is_staff)
def press_create(request):
    """Manual create page for PressRelease (staff only, no Django forms)."""
    if request.method == "GET":
        return render(request, "press/create.html", {
            "categories": PressRelease.Category.choices,
            "now_iso": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
        })

    # POST
    data = request.POST
    files = request.FILES

    title = (data.get("title") or "").strip()
    subtitle = (data.get("subtitle") or "").strip()
    summary = (data.get("summary") or "").strip()
    body = (data.get("body") or "").strip()
    category = (data.get("category") or "").strip() or PressRelease.Category.COMPANY
    tags_raw = (data.get("tags") or "").strip()
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

    author = (data.get("author") or "").strip()
    source_url = (data.get("source_url") or "").strip()

    is_published = data.get("is_published") == "on"
    publish_at_str = (data.get("publish_at") or "").strip()

    hero_image = files.get("hero_image")

    errors = {}
    if not title:
        errors["title"] = "Title is required."
    if not summary:
        errors["summary"] = "Summary is required."
    if not body:
        errors["body"] = "Body is required."

    # Parse datetime-local (YYYY-MM-DDTHH:MM)
    publish_at = timezone.now()
    if publish_at_str:
        try:
            dt = datetime.fromisoformat(publish_at_str)
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt, timezone.get_current_timezone())
            publish_at = dt
        except Exception:
            errors["publish_at"] = "Invalid date/time."

    if errors:
        messages.error(request, "Please fix the errors below.")
        return render(request, "press/create.html", {
            "errors": errors,
            "categories": PressRelease.Category.choices,
            "form": {
                "title": title, "subtitle": subtitle, "summary": summary, "body": body,
                "category": category, "tags": tags_raw, "author": author,
                "source_url": source_url, "is_published": is_published,
                "publish_at": publish_at_str,
            },
            "now_iso": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
        }, status=400)

    pr = PressRelease.objects.create(
        title=title,
        subtitle=subtitle,
        summary=summary,
        body=body,
        category=category,
        tags=tags,
        author=author,
        source_url=source_url,
        hero_image=hero_image,
        is_published=is_published,
        publish_at=publish_at,
    )

    messages.success(request, "Press release created.")
    return redirect(pr.get_absolute_url())


def investors_home(request):
    q = (request.GET.get("q") or "").strip()
    cat = (request.GET.get("category") or "").strip()

    docs = InvestorDocument.objects.published()
    if q:
        docs = docs.filter(Q(title__icontains=q) | Q(summary__icontains=q))
    if cat:
        docs = docs.filter(category=cat)

    latest_finance_news = PressRelease.objects.published().filter(category__in=["finance", "company"])[:3]
    upcoming = InvestorEvent.objects.upcoming()[:3]
    past = InvestorEvent.objects.past()[:3]

    return render(request, "investors/index.html", {
        "docs": docs[:12],  # keep the home concise
        "q": q,
        "category": cat,
        "latest_finance_news": latest_finance_news,
        "upcoming": upcoming,
        "past": past,
    })


def shipping_info(request):
    return render(request, "info/shipping.html")