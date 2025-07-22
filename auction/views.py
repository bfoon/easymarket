from django.shortcuts import render, get_object_or_404, redirect, reverse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Count, Case, When, F
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.generic import ListView, DetailView
from datetime import timedelta
from decimal import Decimal

from .models import Auction, Bid, AuctionCategory, Watchlist, AuctionQuestion
from .forms import AuctionForm, BidForm, SearchForm, QuestionForm
from stores.models import Store


class AuctionListView(ListView):
    """Enhanced list view with filtering and search"""
    model = Auction
    template_name = 'auction/index.html'
    context_object_name = 'auctions'
    paginate_by = 12

    def get_queryset(self):
        queryset = Auction.objects.filter(
            status='active',
            end_date__gt=timezone.now()
        ).select_related('category', 'seller', 'store').prefetch_related('bids')

        # Apply search filters
        search_form = SearchForm(self.request.GET)
        if search_form.is_valid():
            query = search_form.cleaned_data.get('query')
            category = search_form.cleaned_data.get('category')
            auction_type = search_form.cleaned_data.get('auction_type')
            min_price = search_form.cleaned_data.get('min_price')
            max_price = search_form.cleaned_data.get('max_price')
            ending_soon = search_form.cleaned_data.get('ending_soon')
            reserve_met = search_form.cleaned_data.get('reserve_met')
            store = search_form.cleaned_data.get('store')

            if query:
                queryset = queryset.filter(
                    Q(title__icontains=query) |
                    Q(description__icontains=query) |
                    Q(store__name__icontains=query)
                )
            if category:
                queryset = queryset.filter(category=category)
            if auction_type:
                queryset = queryset.filter(auction_type=auction_type)
            if store:
                queryset = queryset.filter(store=store)
            if min_price:
                queryset = queryset.filter(
                    Q(current_bid__gte=min_price) |
                    Q(current_bid__isnull=True, starting_bid__gte=min_price)
                )
            if max_price:
                queryset = queryset.filter(
                    Q(current_bid__lte=max_price) |
                    Q(current_bid__isnull=True, starting_bid__lte=max_price)
                )
            if ending_soon:
                soon_threshold = timezone.now() + timedelta(hours=24)
                queryset = queryset.filter(end_date__lte=soon_threshold)
            if reserve_met:
                queryset = queryset.filter(
                    Q(reserve_price__isnull=True) |
                    Q(current_bid__gte=F('reserve_price'))
                )

        return queryset.order_by('-featured', '-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_form'] = SearchForm(self.request.GET)
        context['categories'] = AuctionCategory.objects.filter(is_active=True).annotate(
            auction_count=Count('auctions', filter=Q(auctions__status='active'))
        )
        context['stores'] = Store.objects.filter(status='active').annotate(
            auction_count=Count('auctions', filter=Q(auctions__status='active'))
        )[:10]
        context['total_results'] = self.get_queryset().count()
        context['featured_auctions'] = Auction.objects.filter(
            featured=True,
            status='active',
            end_date__gt=timezone.now()
        )[:6]
        return context


def auction_detail(request, pk):
    """Enhanced auction detail view with full EasyMarket integration"""
    auction = get_object_or_404(Auction.objects.select_related(
        'category', 'seller', 'store', 'winner', 'marketplace_product'
    ).prefetch_related(
        'bids__bidder', 'additional_images', 'questions__questioner'
    ), pk=pk)

    # Increment view count
    Auction.objects.filter(pk=pk).update(view_count=F('view_count') + 1)

    bids = auction.bids.select_related('bidder').order_by('-timestamp')[:10]

    bid_form = None
    question_form = None
    is_watching = False
    user_highest_bid = None
    user_questions = []
    can_bid = False

    if request.user.is_authenticated:
        # Check if user can bid (not seller, auction is active)
        can_bid = (
                request.user != auction.seller and
                auction.is_active and
                request.user.is_buyer
        )

        if can_bid:
            bid_form = BidForm(auction=auction, user=request.user)

        question_form = QuestionForm()
        is_watching = Watchlist.objects.filter(user=request.user, auction=auction).exists()
        user_highest_bid = bids.filter(bidder=request.user).first()
        user_questions = auction.questions.filter(questioner=request.user)

    # Check if auction can be extended
    can_extend = (
            auction.auto_extend and
            auction.is_active and
            auction.end_date - timezone.now() <= timedelta(minutes=5)
    )

    # Get related auctions from same store
    related_auctions = Auction.objects.filter(
        store=auction.store,
        status='active'
    ).exclude(pk=auction.pk)[:4]

    # Get store reviews for trust indicators
    store_reviews = auction.store.reviews.filter(is_approved=True)[:5]

    context = {
        'auction': auction,
        'bids': bids,
        'bid_form': bid_form,
        'question_form': question_form,
        'is_watching': is_watching,
        'user_highest_bid': user_highest_bid,
        'user_questions': user_questions,
        'can_extend': can_extend,
        'can_bid': can_bid,
        'related_auctions': related_auctions,
        'store_reviews': store_reviews,
        'public_questions': auction.questions.filter(
            is_public=True
        ).exclude(questioner=request.user) if request.user.is_authenticated else auction.questions.filter(
            is_public=True)
    }
    return render(request, 'auction/detail.html', context)


@login_required
def place_bid(request, pk):
    """Enhanced bidding with integration to existing payment/order system"""
    auction = get_object_or_404(Auction, pk=pk)

    # Validate user can bid
    if not request.user.is_buyer:
        messages.error(request, "You need to be a registered buyer to place bids.")
        return redirect('auction:detail', pk=pk)

    if not auction.is_active:
        messages.error(request, "This auction is no longer active.")
        return redirect('auction:detail', pk=pk)

    if auction.seller == request.user:
        messages.error(request, "You cannot bid on your own auction.")
        return redirect('auction:detail', pk=pk)

    if request.method == 'POST':
        form = BidForm(auction=auction, user=request.user, data=request.POST)
        if form.is_valid():
            bid = form.save(commit=False)
            bid.auction = auction
            bid.bidder = request.user
            bid.ip_address = request.META.get('REMOTE_ADDR')

            # Handle auto-bidding
            max_auto_bid = form.cleaned_data.get('max_auto_bid')
            if max_auto_bid:
                bid.max_auto_bid = max_auto_bid
                bid.is_auto_bid = True

            bid.save()

            # Auto-extend auction if needed
            if auction.auto_extend and auction.end_date - timezone.now() <= timedelta(minutes=5):
                auction.end_date = timezone.now() + timedelta(minutes=5)
                auction.save(update_fields=['end_date'])
                messages.info(request, "Auction extended by 5 minutes due to last-minute bidding.")

            messages.success(request, f"Your bid of ${bid.amount} has been placed!")

            # Check for buy-now price
            if auction.buy_now_price and bid.amount >= auction.buy_now_price:
                return redirect('auction:buy_now', pk=pk)

            return redirect('auction:detail', pk=pk)
        else:
            messages.error(request, "Invalid bid amount.")

    return redirect('auction:detail', pk=pk)


@login_required
def buy_now(request, pk):
    """Buy now functionality integrated with existing order system"""
    auction = get_object_or_404(Auction, pk=pk)

    if not auction.is_active or not auction.buy_now_price:
        messages.error(request, "Buy now is not available for this auction.")
        return redirect('auction:detail', pk=pk)

    if auction.seller == request.user:
        messages.error(request, "You cannot buy your own auction.")
        return redirect('auction:detail', pk=pk)

    if not request.user.is_buyer:
        messages.error(request, "You need to be a registered buyer to purchase items.")
        return redirect('auction:detail', pk=pk)

    # Create winning bid at buy-now price
    bid = Bid.objects.create(
        auction=auction,
        bidder=request.user,
        amount=auction.buy_now_price,
        ip_address=request.META.get('REMOTE_ADDR')
    )

    auction.status = 'ended'
    auction.winner = request.user
    auction.save()

    # Create order through existing system
    order = auction.create_order_for_winner()

    messages.success(request, f"Congratulations! You bought this item for ${auction.buy_now_price}")

    if order:
        return redirect('orders:detail', pk=order.pk)

    return redirect('auction:detail', pk=pk)


@login_required
def create_auction(request):
    """Create auction with store validation"""
    # Check if user has an active store
    user_store = request.user.owned_stores.filter(status='active').first()
    if not user_store:
        messages.error(request, "You need to have an active store to create auctions.")
        return redirect('stores:create')

    if not request.user.is_seller:
        messages.error(request, "You need to be a registered seller to create auctions.")
        return redirect('auction:index')

    if request.method == 'POST':
        form = AuctionForm(user=request.user, data=request.POST, files=request.FILES)
        if form.is_valid():
            auction = form.save(commit=False)
            auction.seller = request.user
            auction.store = user_store

            # Set commission rate from store or default
            auction.commission_rate = user_store.commission_rate

            # Determine status based on store settings
            if user_store.auto_approve_products:
                auction.status = 'active'
            else:
                auction.status = 'draft'
                messages.info(request, "Your auction has been created and is pending approval.")

            auction.save()

            if auction.status == 'active':
                messages.success(request, "Your auction has been created and is now live!")

            return redirect('auction:detail', pk=auction.pk)
    else:
        form = AuctionForm(user=request.user)

    return render(request, 'auction/create.html', {
        'form': form,
        'user_store': user_store
    })


@login_required
def my_auctions(request):
    """User's own auctions with store context"""
    user_stores = request.user.owned_stores.filter(status='active')
    auctions = Auction.objects.filter(
        seller=request.user
    ).select_related('store', 'category').order_by('-created_at')

    # Filter by store if specified
    store_filter = request.GET.get('store')
    if store_filter:
        auctions = auctions.filter(store__id=store_filter)

    paginator = Paginator(auctions, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'auction/my_auctions.html', {
        'page_obj': page_obj,
        'user_stores': user_stores,
        'current_store': store_filter
    })


@login_required
def my_bids(request):
    """User's bid history with order integration"""
    bids = request.user.auction_bids.select_related(
        'auction__store', 'auction__order'
    ).order_by('-timestamp')

    paginator = Paginator(bids, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'auction/my_bids.html', {'page_obj': page_obj})


@login_required
def won_auctions(request):
    """User's won auctions with order status"""
    won_auctions = Auction.objects.filter(
        winner=request.user,
        status__in=['ended', 'sold', 'payment_pending']
    ).select_related('store', 'order', 'payment').order_by('-end_date')

    paginator = Paginator(won_auctions, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'auction/won_auctions.html', {'page_obj': page_obj})


@login_required
def watchlist(request):
    """User's watchlist"""
    watched_auctions = Watchlist.objects.filter(
        user=request.user
    ).select_related('auction__store').order_by('-created_at')

    paginator = Paginator(watched_auctions, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'auction/watchlist.html', {'page_obj': page_obj})


@login_required
@require_POST
def toggle_watchlist(request, pk):
    """Add/remove auction from watchlist"""
    auction = get_object_or_404(Auction, pk=pk)
    watchlist_item, created = Watchlist.objects.get_or_create(
        user=request.user,
        auction=auction
    )

    if not created:
        watchlist_item.delete()
        is_watching = False
        message = "Removed from watchlist"
    else:
        is_watching = True
        message = "Added to watchlist"

    if request.headers.get('HX-Request'):
        return JsonResponse({
            'is_watching': is_watching,
            'message': message,
            'watchlist_count': request.user.auction_watchlist.count()
        })

    messages.success(request, message)
    return redirect('auction:detail', pk=pk)


@login_required
def ask_question(request, pk):
    """Ask a question about the auction with chat integration"""
    auction = get_object_or_404(Auction, pk=pk)

    if request.method == 'POST':
        form = QuestionForm(request.POST)
        if form.is_valid():
            question = form.save(commit=False)
            question.auction = auction
            question.questioner = request.user
            question.save()

            # Create chat thread for private communication
            question.create_chat_thread()

            messages.success(request, "Your question has been submitted and a chat thread has been created.")
        else:
            messages.error(request, "Please enter a valid question.")

    return redirect('auction:detail', pk=pk)


def category_view(request, category_id):
    """View auctions in a specific category"""
    category = get_object_or_404(AuctionCategory, pk=category_id)
    auctions = Auction.objects.filter(
        category=category,
        status='active',
        end_date__gt=timezone.now()
    ).select_related('seller', 'store').order_by('-created_at')

    paginator = Paginator(auctions, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'auction/category.html', {
        'category': category,
        'page_obj': page_obj
    })


def store_auctions(request, store_slug):
    """View all auctions from a specific store"""
    store = get_object_or_404(Store, slug=store_slug, status='active')
    auctions = Auction.objects.filter(
        store=store,
        status='active',
        end_date__gt=timezone.now()
    ).select_related('category').order_by('-created_at')

    paginator = Paginator(auctions, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'auction/store_auctions.html', {
        'store': store,
        'page_obj': page_obj
    })


# API endpoints for AJAX/HTMX
def auction_status_api(request, pk):
    """API endpoint for auction status updates"""
    auction = get_object_or_404(Auction, pk=pk)

    return JsonResponse({
        'status': auction.status,
        'current_price': str(auction.current_price),
        'time_remaining': auction.time_remaining,
        'bid_count': auction.bids.count(),
        'is_active': auction.is_active,
        'reserve_met': auction.reserve_met,
        'minimum_bid': str(auction.minimum_bid)
    })


def search_suggestions(request):
    """AJAX search suggestions"""
    query = request.GET.get('q', '')
    if len(query) >= 2:
        auctions = Auction.objects.filter(
            Q(title__icontains=query) |
            Q(description__icontains=query) |
            Q(store__name__icontains=query),
            status='active'
        ).values('title', 'pk', 'store__name')[:10]

        suggestions = [
            {
                'title': auction['title'],
                'store': auction['store__name'],
                'url': reverse('auction:detail', kwargs={'pk': auction['pk']})
            }
            for auction in auctions
        ]

        return JsonResponse({'suggestions': suggestions})

    return JsonResponse({'suggestions': []})


@login_required
def auction_payment(request, pk):
    """Handle auction payment - integrate with existing payment system"""
    auction = get_object_or_404(Auction, pk=pk, winner=request.user)

    if auction.status != 'payment_pending':
        messages.error(request, "Payment is not required for this auction.")
        return redirect('auction:detail', pk=pk)

    if not auction.order:
        messages.error(request, "No order found for this auction.")
        return redirect('auction:detail', pk=pk)

    # Redirect to existing payment system
    return redirect('payments:process', order_id=auction.order.id)


# Admin views for store managers
@login_required
def manage_store_auctions(request, store_slug):
    """Manage auctions for a specific store"""
    store = get_object_or_404(Store, slug=store_slug)

    # Check if user is store owner or manager
    if not (request.user == store.owner or
            store.managers.filter(id=request.user.id).exists()):
        messages.error(request, "You don't have permission to manage this store.")
        return redirect('stores:detail', slug=store_slug)

    auctions = store.auctions.all().order_by('-created_at')

    # Filter by status
    status_filter = request.GET.get('status')
    if status_filter:
        auctions = auctions.filter(status=status_filter)

    paginator = Paginator(auctions, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'auction/manage_store_auctions.html', {
        'store': store,
        'page_obj': page_obj,
        'status_filter': status_filter,
        'status_choices': Auction.STATUS_CHOICES
    })