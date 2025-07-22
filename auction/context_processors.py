from django.utils import timezone
from .models import Auction, Watchlist, Bid


def auction_counts(request):
    """Add auction-related counts to template context"""
    context = {}

    # Public counts
    context['active_auctions_count'] = Auction.objects.filter(
        status='active',
        end_date__gt=timezone.now()
    ).count()

    if request.user.is_authenticated:
        # User-specific counts for buyers
        if hasattr(request.user, 'is_buyer') and request.user.is_buyer:
            context['user_active_bids_count'] = Bid.objects.filter(
                bidder=request.user,
                auction__status='active'
            ).count()

            context['user_won_auctions_count'] = Auction.objects.filter(
                winner=request.user,
                status__in=['ended', 'sold', 'payment_pending']
            ).count()

            context['user_watchlist_count'] = Watchlist.objects.filter(
                user=request.user
            ).count()

        # User-specific counts for sellers
        if hasattr(request.user, 'is_seller') and request.user.is_seller:
            context['user_auction_count'] = Auction.objects.filter(
                seller=request.user,
                status='active'
            ).count()

    return context