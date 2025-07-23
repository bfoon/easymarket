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
from django.core.cache import cache
from decimal import Decimal
from django.template.loader import render_to_string

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
    """Enhanced auction detail view with full EasyMarket integration."""

    # Fetch auction with all related data
    auction = get_object_or_404(
        Auction.objects.select_related(
            'category', 'seller', 'store', 'winner', 'marketplace_product'
        ).prefetch_related(
            'bids__bidder', 'additional_images', 'questions__questioner'
        ),
        pk=pk
    )

    # Increment view count (atomic)
    Auction.objects.filter(pk=pk).update(view_count=F('view_count') + 1)

    # Latest 10 bids (most recent first)
    bids = auction.bids.select_related('bidder').order_by('-timestamp')[:10]

    # Initialize context variables
    bid_form = None
    question_form = None
    is_watching = False
    user_highest_bid = None
    user_questions = []
    can_bid = False

    # If the user is logged in
    if request.user.is_authenticated:
        is_buyer = getattr(request.user, 'is_buyer', False)
        is_not_seller = request.user != auction.seller
        is_active = auction.is_active
        user_highest_bid = auction.bids.filter(bidder=request.user).order_by('-amount').first()

        can_bid = is_buyer and is_not_seller and is_active

        if can_bid:
            bid_form = BidForm(auction=auction, user=request.user)

        question_form = QuestionForm()
        is_watching = Watchlist.objects.filter(user=request.user, auction=auction).exists()
        user_questions = auction.questions.filter(questioner=request.user)

    # Auto-extend condition
    can_extend = (
            auction.auto_extend and
            auction.is_active and
            (auction.end_date - timezone.now() <= timedelta(minutes=5))
    )

    # Related auctions from same store
    related_auctions = Auction.objects.filter(
        store=auction.store,
        status='active'
    ).exclude(pk=auction.pk).select_related('store', 'category')[:4]

    # Approved reviews for store
    store_reviews = auction.store.reviews.filter(is_approved=True)[:5]

    # Public questions (exclude user’s own if logged in)
    if request.user.is_authenticated:
        public_questions = auction.questions.filter(
            is_public=True
        ).exclude(questioner=request.user)
    else:
        public_questions = auction.questions.filter(is_public=True)

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
        'public_questions': public_questions,
    }

    return render(request, 'auction/detail.html', context)


@login_required
def place_bid(request, pk):
    """Place a bid on an active auction with validations and optional rate limiting."""
    auction = get_object_or_404(Auction, pk=pk)

    # Validate bidding permissions
    if not request.user.is_buyer:
        messages.error(request, "You need to be a registered buyer to place bids.")
        return redirect('auction:detail', pk=pk)

    if not auction.is_active:
        messages.error(request, "This auction is no longer active.")
        return redirect('auction:detail', pk=pk)

    if auction.seller == request.user:
        messages.error(request, "You cannot bid on your own auction.")
        return redirect('auction:detail', pk=pk)

    # Optional: Rate-limiting (e.g., 1 bid per 3 seconds)
    cache_key = f"bid-rate-limit-{request.user.id}"
    if cache.get(cache_key):
        messages.warning(request, "You're bidding too frequently. Please wait a few seconds.")
        return redirect('auction:detail', pk=pk)
    cache.set(cache_key, True, timeout=3)

    if request.method == 'POST':
        form = BidForm(auction=auction, user=request.user, data=request.POST)
        if form.is_valid():
            bid = form.save(commit=False)
            bid.auction = auction
            bid.bidder = request.user
            bid.ip_address = request.META.get('REMOTE_ADDR')

            # Handle optional max auto-bid
            max_auto_bid = form.cleaned_data.get('max_auto_bid')
            if max_auto_bid:
                bid.max_auto_bid = max_auto_bid
                bid.is_auto_bid = True

            bid.save()

            # Auto-extend auction if it's within the last 5 minutes
            if auction.auto_extend and auction.end_date - timezone.now() <= timedelta(minutes=5):
                auction.end_date = timezone.now() + timedelta(minutes=5)
                auction.save(update_fields=['end_date'])
                messages.info(request, "Auction extended by 5 minutes due to last-minute bidding.")

            messages.success(request, f"Your bid of ${bid.amount} has been placed.")

            # If bid meets/exceeds buy-now price, trigger buy-now
            if auction.buy_now_price and bid.amount >= auction.buy_now_price:
                return redirect('auction:buy_now', pk=pk)

            return redirect('auction:detail', pk=pk)
        else:
            messages.error(request, "Invalid bid amount submitted.")

    return redirect('auction:detail', pk=pk)


@login_required
def buy_now(request, pk):
    """Buy Now functionality integrated with the auction and order system."""
    auction = get_object_or_404(Auction, pk=pk)

    # Validations
    if not auction.is_active or not auction.buy_now_price:
        messages.error(request, "Buy Now is not available for this auction.")
        return redirect('auction:detail', pk=pk)

    if auction.seller == request.user:
        messages.error(request, "You cannot buy your own auction.")
        return redirect('auction:detail', pk=pk)

    if not getattr(request.user, 'is_buyer', False):
        messages.error(request, "You must be a registered buyer to purchase items.")
        return redirect('auction:detail', pk=pk)

    if auction.status == 'ended' or auction.winner:
        messages.error(request, "This auction has already ended or has a winner.")
        return redirect('auction:detail', pk=pk)

    # Create a bid at the buy now price
    bid = Bid.objects.create(
        auction=auction,
        bidder=request.user,
        amount=auction.buy_now_price,
        ip_address=request.META.get('REMOTE_ADDR', '')
    )

    # Finalize auction
    auction.status = 'ended'
    auction.winner = request.user
    auction.ended_at = timezone.now()
    auction.save()

    # Create an order (assumes method exists)
    order = auction.create_order_for_winner()

    messages.success(request, f"🎉 You bought this item for ${auction.buy_now_price:.2f}!")

    if order:
        return redirect('orders:order_detail', pk=order.pk)

    return redirect('auction:detail', pk=pk)


@login_required
def create_auction(request):
    """Create auction with store validation and marketplace product selection"""

    # Ensure user is a seller with an active store
    user_store = request.user.owned_stores.filter(status='active').first()

    if not user_store:
        messages.error(request, "You need to have an active store to create auctions.")
        return redirect('stores:create')

    if not request.user.is_seller:
        messages.error(request, "You need to be a registered seller to create auctions.")
        return redirect('auction:index')

    # Get store's marketplace products
    from marketplace.models import Product
    marketplace_products = Product.objects.filter(
        store=user_store,
        is_active=True  # assuming products have a status field
    ).select_related('category')

    if request.method == 'POST':
        form = AuctionForm(user=request.user, data=request.POST, files=request.FILES)
        if form.is_valid():
            auction = form.save(commit=False)
            auction.seller = request.user
            auction.store = user_store
            auction.commission_rate = user_store.commission_rate

            # Handle marketplace product selection
            marketplace_product_id = request.POST.get('marketplace_product')
            if marketplace_product_id:
                try:
                    selected_product = marketplace_products.get(id=marketplace_product_id)
                    auction.marketplace_product = selected_product

                    # Auto-populate some fields from marketplace product
                    if not auction.title:
                        auction.title = selected_product.name
                    if not auction.description:
                        auction.description = selected_product.description
                    if not auction.image and selected_product.image:
                        auction.image = selected_product.image

                except Product.DoesNotExist:
                    messages.error(request, "Selected marketplace product not found.")
                    return render(request, 'auction/create.html', {
                        'form': form,
                        'store': user_store,
                        'store_slug': user_store.slug,
                        'marketplace_products': marketplace_products,
                    })

            # Status logic
            if user_store.auto_approve_products:
                auction.status = 'active'
                messages.success(request, "Your auction has been created and is now live!")
            else:
                auction.status = 'draft'
                messages.info(request, "Your auction has been created and is pending approval.")

            auction.save()
            return redirect('auction:detail', pk=auction.pk)
    else:
        form = AuctionForm(user=request.user)

    return render(request, 'auction/create.html', {
        'form': form,
        'store': user_store,
        'store_slug': user_store.slug if user_store else '',
        'marketplace_products': marketplace_products,
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

def ajax_auction_bids(request, pk):
    auction = get_object_or_404(Auction, pk=pk)
    bids = auction.bids.select_related('bidder').order_by('-timestamp')
    html = render_to_string('auction/partials/recent_bids.html', {'bids': bids})
    return JsonResponse({'html': html})

def ajax_current_bid(request, pk):
    auction = get_object_or_404(Auction, pk=pk)
    bids = auction.bids.order_by('-amount')
    html = render_to_string('auction/partials/current_bid.html', {'bids': bids, 'auction': auction})
    return JsonResponse({'html': html})

def ajax_questions(request, pk):
    auction = get_object_or_404(Auction, pk=pk)
    questions = auction.public_questions.select_related('questioner')
    html = render_to_string('auction/partials/questions.html', {'public_questions': questions})
    return JsonResponse({'html': html})


@login_required
def won_auctions(request):
    """Display auctions won by the user, with order and payment info."""

    # Assign winners if auctions expired
    expired_auctions = Auction.objects.filter(
        status='active',
        end_date__lte=timezone.now(),
        winner__isnull=True,
        bids__bidder=request.user
    ).distinct()

    for auction in expired_auctions:
        auction.assign_winner_if_expired()

    # Fetch won auctions
    won_auctions = Auction.objects.filter(
        winner=request.user,
        status__in=['ended', 'sold', 'payment_pending']
    ).select_related('store', 'order', 'payment', 'shipment').order_by('-end_date')

    paginator = Paginator(won_auctions, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Safely sum up winning prices
    total_spent = sum(
        (auction.current_bid or auction.starting_bid or Decimal('0.00')) for auction in won_auctions
    )

    return render(request, 'auction/won_auctions.html', {
        'page_obj': page_obj,
        'total_spent': total_spent
    })

@login_required
@require_POST
def create_order_for_auction(request, pk):
    """Create an order for a won auction"""
    auction = get_object_or_404(Auction, pk=pk, winner=request.user)

    # Validate auction state
    if auction.order:
        messages.info(request, "An order already exists for this auction.")
        return redirect('orders:order_detail', pk=auction.order.pk)

    if auction.status not in ['ended', 'payment_pending']:
        messages.error(request, "Cannot create order for this auction status.")
        return redirect('auction:won_auctions')

    try:
        # Use the existing method from the model
        order = auction.create_order_for_winner()

        if order:
            messages.success(request, f"Order #{order.pk} created successfully!")
            return redirect('orders:order_detail', pk=order.pk)
        else:
            messages.error(request, "Failed to create order. Please contact support.")

    except Exception as e:
        messages.error(request, f"Error creating order: {str(e)}")

    return redirect('auction:won_auctions')


@login_required
def auction_order_detail(request, pk):
    """Quick order detail view for auction context"""
    auction = get_object_or_404(Auction, pk=pk, winner=request.user)

    if not auction.order:
        messages.error(request, "No order exists for this auction yet.")
        return redirect('auction:won_auctions')

    # Redirect to the main order detail view
    return redirect('orders:order_detail', pk=auction.order.pk)

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

@login_required
def edit_auction(request, pk):
    auction = get_object_or_404(Auction, pk=pk)

    # Ensure only the store owner or manager can edit
    if request.user != auction.store.owner and not auction.store.managers.filter(id=request.user.id).exists():
        messages.error(request, "You do not have permission to edit this auction.")
        return redirect('auction:manage_store_auctions', store_slug=auction.store.slug)

    if request.method == 'POST':
        form = AuctionForm(user=request.user, instance=auction, data=request.POST, files=request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "Auction updated successfully.")
            return redirect('auction:manage_store_auctions', store_slug=auction.store.slug)
    else:
        form = AuctionForm(user=request.user, instance=auction)

    return render(request, 'auction/edit.html', {
        'form': form,
        'auction': auction,
        'store_slug': auction.store.slug,
    })