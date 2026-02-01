# crossroad_deals/views.py

from django.shortcuts import render, redirect, get_object_or_404, reverse
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseBadRequest
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db.models import Q, Avg, Count
from django.utils import timezone
from django.core.paginator import Paginator
from decimal import Decimal
from django.views.decorators.csrf import csrf_exempt
from .tasks import send_crossroad_email, send_crossroad_whatsapp


from .models import (
    CrossroadListing,
    CrossroadOrder,
    CrossroadReview,
    CrossroadDealConfig,
    ListingInterest,
    DeviceActivityLog,
    SellerSuspension,
)
from accounts.models import Device


def get_or_create_device(request):
    """Get or create device from request"""
    device_id = request.COOKIES.get('device_id', 'unknown')
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    ip_address = get_client_ip(request)

    if request.user.is_authenticated:
        device, created = Device.objects.get_or_create(
            user=request.user,
            device_id=device_id,
            defaults={
                'user_agent': user_agent,
                'ip': ip_address,
            }
        )
        return device
    return None


def get_client_ip(request):
    """Get client IP address"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def log_activity(request, action_type, listing=None, order=None, metadata=None):
    """Log device activity"""
    device = get_or_create_device(request)
    if device and request.user.is_authenticated:
        DeviceActivityLog.objects.create(
            device=device,
            user=request.user,
            action_type=action_type,
            listing=listing,
            order=order,
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            metadata=metadata or {}
        )


def listing_list(request):
    """Browse all active listings"""
    # Get active listings
    listings = CrossroadListing.objects.filter(
        status='active'
    ).select_related('seller').order_by('-created_at')

    # Filters
    condition = request.GET.get('condition')
    if condition:
        listings = listings.filter(condition=condition)

    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    if min_price:
        listings = listings.filter(price__gte=Decimal(min_price))
    if max_price:
        listings = listings.filter(price__lte=Decimal(max_price))

    search = request.GET.get('search')
    if search:
        listings = listings.filter(
            Q(title__icontains=search) |
            Q(description__icontains=search)
        )

    # Pagination
    paginator = Paginator(listings, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Get disclosed data for each listing
    listings_data = []
    for listing in page_obj:
        data = listing.get_disclosed_data('immediately')
        data['id'] = listing.id
        data['can_show_price'] = listing.can_disclose_field('price', 'immediately')
        listings_data.append(data)

    context = {
        'page_obj': page_obj,
        'listings_data': listings_data,
        'conditions': CrossroadListing.CONDITION_CHOICES,
        'search': search or '',
        'condition': condition or '',
        'min_price': min_price or '',
        'max_price': max_price or '',
    }

    return render(request, 'crossroad_deals/listing_list.html', context)


def listing_detail(request, listing_id):
    """View listing details with privacy-aware disclosure"""
    listing = get_object_or_404(
        CrossroadListing.objects.select_related('seller'),
        listing_id=listing_id,
        status='active'
    )

    # Log activity
    log_activity(request, 'listing_view', listing=listing)

    # -------------------------
    # Determine disclosure stage
    # -------------------------
    disclosure_stage = 'immediately'
    user_has_interest = False
    in_cart = False
    has_ordered = False

    if request.user.is_authenticated:
        # Interest
        user_has_interest = ListingInterest.objects.filter(
            listing=listing,
            user=request.user
        ).exists()

        if user_has_interest:
            disclosure_stage = 'after_interest'

        # ✅ Crossroad session cart (your CROSSROAD_CART_KEY cart)
        cart = request.session.get(CROSSROAD_CART_KEY, {})
        in_cart = str(listing.listing_id) in cart
        if in_cart:
            disclosure_stage = 'after_add_to_cart'

        # ✅ Any order should unlock at least "after_add_to_cart"
        # because your create_listing defaults contact_disclosure to after_add_to_cart
        has_ordered = CrossroadOrder.objects.filter(
            listing=listing,
            buyer=request.user
        ).exists()

        if has_ordered:
            disclosure_stage = 'after_add_to_cart'

        # ✅ Delivered order = after_order_complete
        has_delivered = CrossroadOrder.objects.filter(
            listing=listing,
            buyer=request.user,
            status='delivered'
        ).exists()

        if has_delivered:
            disclosure_stage = 'after_order_complete'

    # -------------------------
    # Get disclosed data
    # -------------------------
    data = listing.get_disclosed_data(disclosure_stage)

    # -------------------------
    # Check what can be disclosed (use REAL field names)
    # -------------------------
    can_show_price = listing.can_disclose_field('price', disclosure_stage)

    can_show_contact = (
        listing.can_disclose_field('contact_phone', disclosure_stage) or
        listing.can_disclose_field('contact_email', disclosure_stage)
    )

    can_show_location = (
        listing.can_disclose_field('geocode', disclosure_stage) or
        listing.can_disclose_field('location_description', disclosure_stage) or
        listing.can_disclose_field('exact_location', disclosure_stage)
    )

    # Seller reviews / ratings
    seller_reviews = CrossroadReview.objects.filter(
        seller=listing.seller
    ).select_related('reviewer')[:5]

    seller_avg_rating = CrossroadReview.objects.filter(
        seller=listing.seller
    ).aggregate(avg=Avg('rating'))['avg'] or 0

    is_suspended = SellerSuspension.objects.filter(
        seller=listing.seller,
        is_lifted=False
    ).exists()

    STAGE_LABELS = {
        "immediately": "Immediately",
        "after_interest": "After Interest",
        "after_add_to_cart": "After Add To Cart",
        "after_order_complete": "After Order Complete",
    }
    disclosure_stage_label = STAGE_LABELS.get(disclosure_stage, disclosure_stage.replace("_", " ").title())

    context = {
        'listing': listing,
        'data': data,
        'disclosure_stage': disclosure_stage,
        'disclosure_stage_label': disclosure_stage_label,

        'can_show_price': can_show_price,
        'can_show_contact': can_show_contact,
        'can_show_location': can_show_location,

        'user_has_interest': user_has_interest,
        'in_cart': in_cart,
        'has_ordered': has_ordered,

        'seller_reviews': seller_reviews,
        'seller_avg_rating': round(seller_avg_rating, 1),
        'is_suspended': is_suspended,
    }

    return render(request, 'crossroad_deals/listing_detail.html', context)


@login_required
@require_POST
def express_interest(request, listing_id):
    """Express interest in a listing (unlocks more info)"""
    listing = get_object_or_404(CrossroadListing, listing_id=listing_id)

    # Create interest
    interest, created = ListingInterest.objects.get_or_create(
        listing=listing,
        user=request.user
    )

    if created:
        # ✅ background notify seller
        seller_email = getattr(listing.seller, "email", "")
        seller_phone = getattr(listing.seller, "telephone", "") or getattr(listing.seller, "phone", "")

        msg = (
            f"New interest on your listing: {listing.title}\n"
            f"Buyer: {request.user.username}\n"
            f"Listing ID: {listing.listing_id}\n"
        )

        if seller_email:
            send_crossroad_email.delay("Crossroad Deals: New Interest", msg, seller_email)
        if seller_phone:
            send_crossroad_whatsapp.delay(seller_phone, msg)

    # Log activity
    log_activity(request, 'listing_view', listing=listing, metadata={'interest': True})

    if created:
        messages.success(request, 'Interest recorded! More information is now visible.')
    else:
        messages.info(request, 'You have already expressed interest in this item.')

    return redirect('crossroad_deals:listing_detail', listing_id=listing_id)


@login_required
def create_listing(request):
    """Create a new listing"""
    config = CrossroadDealConfig.get_config()

    # Check if seller is suspended
    if SellerSuspension.objects.filter(seller=request.user, is_lifted=False).exists():
        messages.error(request, 'Your account is suspended. You cannot create listings.')
        return redirect('crossroad_deals:my_listings')

    if request.method == 'POST':
        # Get form data
        title = request.POST.get('title')
        description = request.POST.get('description')
        condition = request.POST.get('condition')
        quantity = request.POST.get('quantity')
        price = request.POST.get('price')
        geocode = request.POST.get('geocode')
        location_description = request.POST.get('location_description', '')

        # Privacy settings
        show_seller_name = request.POST.get('show_seller_name') == 'on'
        show_exact_location = request.POST.get('show_exact_location') == 'on'
        price_disclosure = request.POST.get('price_disclosure', 'immediately')
        contact_disclosure = request.POST.get('contact_disclosure', 'after_add_to_cart')
        location_disclosure = request.POST.get('location_disclosure', 'after_order_complete')

        # Contact info
        contact_phone = request.POST.get('contact_phone', '')
        contact_email = request.POST.get('contact_email', '')

        # Images
        image_1 = request.FILES.get('image_1')
        image_2 = request.FILES.get('image_2')

        # Vetting
        request_vetting = request.POST.get('request_vetting') == 'on'

        # Validate
        errors = []
        if not title:
            errors.append('Title is required')
        if not description:
            errors.append('Description is required')
        if not quantity or int(quantity) < 1:
            errors.append('Quantity must be at least 1')
        if not price or Decimal(price) < 0:
            errors.append('Price must be a positive number')
        if not geocode and config.require_geocode:
            errors.append('Geocode is required')
        if not image_1:
            errors.append('At least one image is required')

        if errors:
            for error in errors:
                messages.error(request, error)
            return render(request, 'crossroad_deals/create_listing.html', {
                'config': config,
                'conditions': CrossroadListing.CONDITION_CHOICES,
                'disclosure_choices': CrossroadListing._meta.get_field('price_disclosure').choices,
            })

        # Calculate fees
        listing_fee = Decimal('0.00')
        if not request.user.is_seller:
            listing_fee = config.listing_fee

        vetting_fee = Decimal('0.00')
        if request_vetting:
            vetting_fee = config.vetting_fee

        # Create listing
        listing = CrossroadListing.objects.create(
            seller=request.user,
            title=title,
            description=description,
            condition=condition,
            quantity=int(quantity),
            price=Decimal(price),
            geocode=geocode,
            location_description=location_description,
            show_seller_name=show_seller_name,
            show_exact_location=show_exact_location,
            price_disclosure=price_disclosure,
            contact_disclosure=contact_disclosure,
            location_disclosure=location_disclosure,
            contact_phone=contact_phone,
            contact_email=contact_email,
            image_1=image_1,
            image_2=image_2,
            listing_fee_paid=listing_fee,
            vetting_fee_paid=vetting_fee,
            status='draft',  # Start as draft
        )

        # Log activity
        log_activity(request, 'listing_create', listing=listing)

        # TODO: Process payment for fees
        # For now, just activate the listing
        listing.status = 'active'
        listing.save()

        messages.success(request,
                         f'Listing created successfully! {f"Listing fee: ${listing_fee}" if listing_fee > 0 else ""}')
        return redirect('crossroad_deals:listing_detail', listing_id=listing.listing_id)

    context = {
        'config': config,
        'conditions': CrossroadListing.CONDITION_CHOICES,
        'disclosure_choices': CrossroadListing._meta.get_field('price_disclosure').choices,
    }

    return render(request, 'crossroad_deals/create_listing.html', context)


@login_required
def my_listings(request):
    """View user's listings"""
    listings = CrossroadListing.objects.filter(
        seller=request.user
    ).order_by('-created_at')

    # Stats
    active_count = listings.filter(status='active').count()
    sold_out_count = listings.filter(status='sold_out').count()
    suspended_count = listings.filter(status='suspended').count()

    context = {
        'listings': listings,
        'active_count': active_count,
        'sold_out_count': sold_out_count,
        'suspended_count': suspended_count,
    }

    return render(request, 'crossroad_deals/my_listings.html', context)


@login_required
def create_order(request):
    """Create an order"""
    if request.method == 'POST':
        listing_id = request.POST.get('listing_id')
        quantity = int(request.POST.get('quantity', 1))
        delivery_method = request.POST.get('delivery_method', 'easy_move')
        request_vetting = request.POST.get('request_vetting') == 'on'
        buyer_geocode = request.POST.get('buyer_geocode', '')
        buyer_phone = request.POST.get('buyer_phone', '')
        buyer_email = request.POST.get('buyer_email', '')

        listing = get_object_or_404(CrossroadListing, listing_id=listing_id)
        config = CrossroadDealConfig.get_config()

        # Validate quantity
        if quantity > listing.quantity_available:
            messages.error(request, 'Not enough quantity available.')
            return redirect('crossroad_deals:listing_detail', listing_id=listing_id)

        # Calculate fees
        delivery_fee = config.pickup_base_fee
        vetting_fee = config.vetting_fee if request_vetting else Decimal('0.00')

        # Create order
        order = CrossroadOrder.objects.create(
            listing=listing,
            buyer=request.user,
            quantity=quantity,
            unit_price=listing.price,
            delivery_method=delivery_method,
            delivery_fee=delivery_fee,
            requested_vetting=request_vetting,
            vetting_fee=vetting_fee,
            buyer_geocode=buyer_geocode,
            buyer_phone=buyer_phone,
            buyer_email=buyer_email,
            buyer_device=get_or_create_device(request),
        )

        # Log activity
        log_activity(request, 'order_create', order=order)

        # TODO: Process payment
        # For now, just confirm the order
        order.status = 'confirmed'
        order.save()

        # Generate receipt
        order.generate_receipt()

        buyer_email = getattr(request.user, "email", "") or buyer_email
        buyer_phone = buyer_phone
        seller_email = getattr(listing.seller, "email", "")
        seller_phone = getattr(listing.seller, "telephone", "") or getattr(listing.seller, "phone", "")

        buyer_msg = (
            f"Order confirmed!\n"
            f"Order ID: {order.order_id}\n"
            f"Item: {listing.title}\n"
            f"Qty: {quantity}\n"
        )

        seller_msg = (
            f"You have a new order!\n"
            f"Order ID: {order.order_id}\n"
            f"Item: {listing.title}\n"
            f"Qty: {quantity}\n"
            f"Buyer: {request.user.username}\n"
        )

        if buyer_email:
            send_crossroad_email.delay("Crossroad Deals: Order Confirmed", buyer_msg, buyer_email)
        if buyer_phone:
            send_crossroad_whatsapp.delay(buyer_phone, buyer_msg)

        if seller_email:
            send_crossroad_email.delay("Crossroad Deals: New Order", seller_msg, seller_email)
        if seller_phone:
            send_crossroad_whatsapp.delay(seller_phone, seller_msg)

        messages.success(request, f'Order placed successfully! Order ID: {order.order_id}')
        return redirect('crossroad_deals:order_detail', order_id=order.order_id)

    return redirect('crossroad_deals:listing_list')


@login_required
def order_detail(request, order_id):
    """View order details"""
    order = get_object_or_404(
        CrossroadOrder.objects.select_related('listing', 'buyer', 'listing__seller'),
        order_id=order_id
    )

    # Check permission
    if order.buyer != request.user and order.listing.seller != request.user:
        messages.error(request, 'You do not have permission to view this order.')
        return redirect('crossroad_deals:listing_list')

    # Get all disclosed info for buyer
    if order.buyer == request.user:
        disclosure_stage = 'after_order_complete' if order.status == 'delivered' else 'after_payment'
        listing_data = order.listing.get_disclosed_data(disclosure_stage)
    else:
        listing_data = {}

    # Check if can review
    can_review = (
            order.buyer == request.user and
            order.status == 'delivered' and
            not hasattr(order, 'review')
    )

    context = {
        'order': order,
        'listing_data': listing_data,
        'can_review': can_review,
    }

    return render(request, 'crossroad_deals/order_detail.html', context)


@login_required
def my_orders(request):
    """View user's orders"""
    orders = CrossroadOrder.objects.filter(
        buyer=request.user
    ).select_related('listing', 'listing__seller').order_by('-created_at')

    context = {
        'orders': orders,
    }

    return render(request, 'crossroad_deals/my_orders.html', context)


@login_required
def create_review(request):
    """Create a review for an order"""
    if request.method == 'POST':
        order_id = request.POST.get('order_id')
        rating = int(request.POST.get('rating'))
        title = request.POST.get('title', '')
        comment = request.POST.get('comment')
        product_as_described = request.POST.get('product_as_described') == 'on'
        would_buy_again = request.POST.get('would_buy_again') == 'on'

        order = get_object_or_404(CrossroadOrder, order_id=order_id, buyer=request.user)

        # Check if already reviewed
        if hasattr(order, 'review'):
            messages.error(request, 'You have already reviewed this order.')
            return redirect('crossroad_deals:order_detail', order_id=order_id)

        # Create review
        review = CrossroadReview.objects.create(
            order=order,
            reviewer=request.user,
            seller=order.listing.seller,
            rating=rating,
            title=title,
            comment=comment,
            product_as_described=product_as_described,
            would_buy_again=would_buy_again,
        )

        # Log activity
        log_activity(request, 'review_submit', metadata={'rating': rating})

        messages.success(request, 'Review submitted successfully!')
        return redirect('crossroad_deals:order_detail', order_id=order_id)

    return redirect('crossroad_deals:my_orders')

CROSSROAD_CART_KEY = "crossroad_cart"


def _get_cart(request):
    return request.session.get(CROSSROAD_CART_KEY, {})


def _save_cart(request, cart):
    request.session[CROSSROAD_CART_KEY] = cart
    request.session.modified = True


def _is_listing_orderable(listing: CrossroadListing) -> bool:
    return listing.status == "active" and (listing.quantity_available or 0) > 0


@login_required
@require_POST
def cart_add(request):
    listing_id = request.POST.get("listing_id")
    qty = request.POST.get("quantity", "1")

    listing = get_object_or_404(CrossroadListing, listing_id=listing_id)

    if listing.seller_id == request.user.id:
        messages.error(request, "You cannot buy your own listing.")
        return redirect("crossroad_deals:listing_detail", listing_id=listing.listing_id)

    if not _is_listing_orderable(listing):
        messages.error(request, "This item is not available right now.")
        return redirect("crossroad_deals:listing_detail", listing_id=listing.listing_id)

    try:
        qty = int(qty)
    except ValueError:
        qty = 1

    qty = max(1, qty)
    qty = min(qty, listing.quantity_available)

    cart = _get_cart(request)
    key = str(listing.listing_id)

    existing_qty = int(cart.get(key, {}).get("quantity", 0))
    new_qty = min(existing_qty + qty, listing.quantity_available)

    cart[key] = {
        "quantity": new_qty,
        # we store optional offer info here too
        "offer_price": cart.get(key, {}).get("offer_price"),
        "offer_note": cart.get(key, {}).get("offer_note"),
    }
    _save_cart(request, cart)

    messages.success(request, "Added to Crossroad cart.")
    return redirect("crossroad_deals:cart_view")


@login_required
def cart_view(request):
    cart = _get_cart(request)
    ids = list(cart.keys())

    listings = CrossroadListing.objects.filter(listing_id__in=ids).select_related("seller")
    listing_map = {str(l.listing_id): l for l in listings}

    items = []
    for key, data in cart.items():
        listing = listing_map.get(key)
        if not listing:
            continue
        items.append({
            "listing": listing,
            "quantity": int(data.get("quantity", 1)),
            "offer_price": data.get("offer_price"),
            "offer_note": data.get("offer_note"),
            "available": _is_listing_orderable(listing),
        })
        cart_has_unavailable = any(not it.get("available", True) for it in items)

    return render(request, "crossroad_deals/cart.html", {
        "items": items,
        "cart_has_unavailable": cart_has_unavailable,
    })


@login_required
def cart_remove(request, listing_id):
    cart = _get_cart(request)
    key = str(listing_id)
    if key in cart:
        del cart[key]
        _save_cart(request, cart)
        messages.info(request, "Removed from cart.")
    return redirect("crossroad_deals:cart_view")


@login_required
@require_POST
def cart_checkout(request):
    """
    Converts cart items into CrossroadOrder records.
    This keeps your Crossroad system separate from EasyMarket cart.
    """
    delivery_method = request.POST.get("delivery_method", "delivery")
    buyer_geocode = request.POST.get("buyer_geocode", "").strip()
    buyer_phone = request.POST.get("buyer_phone", "").strip()
    buyer_email = request.POST.get("buyer_email", "").strip()
    request_vetting = bool(request.POST.get("request_vetting"))

    cart = _get_cart(request)
    if not cart:
        messages.error(request, "Your cart is empty.")
        return redirect("crossroad_deals:cart_view")

    created = 0
    for listing_key, data in cart.items():
        listing = CrossroadListing.objects.filter(listing_id=listing_key).first()
        if not listing or not _is_listing_orderable(listing):
            continue

        qty = int(data.get("quantity", 1))
        qty = max(1, min(qty, listing.quantity_available))

        # If you want negotiation to affect unit_price, you can apply it here.
        # Safer: store it as a note; keep unit_price from listing.price.
        unit_price = listing.price or Decimal("0.00")

        CrossroadOrder.objects.create(
            listing=listing,
            buyer=request.user,
            quantity=qty,
            unit_price=unit_price,
            delivery_method=delivery_method,   # make sure values match your choices
            buyer_geocode=buyer_geocode,
            buyer_phone=buyer_phone,
            buyer_email=buyer_email,
            requested_vetting=request_vetting,
        )
        created += 1

    _save_cart(request, {})  # clear
    messages.success(request, f"Checkout completed. Created {created} order(s).")
    return redirect("crossroad_deals:my_orders")


@login_required
@require_POST
def make_offer(request, listing_id):
    listing = get_object_or_404(CrossroadListing, listing_id=listing_id)

    if listing.seller_id == request.user.id:
        messages.error(request, "You cannot negotiate on your own listing.")
        return redirect("crossroad_deals:listing_detail", listing_id=listing.listing_id)

    offer_price = request.POST.get("offer_price", "").strip()
    note = request.POST.get("note", "").strip()

    # Save offer as interest record (simple)
    obj, created = ListingInterest.objects.get_or_create(user=request.user, listing=listing)
    # If your model doesn't have these fields yet, see section 2 below.
    if hasattr(obj, "offer_price"):
        obj.offer_price = offer_price or None
    if hasattr(obj, "offer_note"):
        obj.offer_note = note or ""
    obj.save()

    seller_email = getattr(listing.seller, "email", "")
    seller_phone = getattr(listing.seller, "telephone", "") or getattr(listing.seller, "phone", "")

    msg = (
        f"New offer received on: {listing.title}\n"
        f"Buyer: {request.user.username}\n"
        f"Offer: {offer_price}\n"
        f"Note: {note or '-'}\n"
        f"Listing ID: {listing.listing_id}\n"
    )

    if seller_email:
        send_crossroad_email.delay("Crossroad Deals: New Offer", msg, seller_email)
    if seller_phone:
        send_crossroad_whatsapp.delay(seller_phone, msg)

    messages.success(request, "Offer sent to seller.")
    return redirect("crossroad_deals:listing_detail", listing_id=listing.listing_id)

ALLOWED_PROVIDERS = {"wave", "qmoney", "afrimoney", "verve", "waychit"}

def order_pay(request, order_id):
    order = get_object_or_404(CrossroadOrder, order_id=order_id, buyer=request.user)

    if order.status in ("paid", "confirmed", "delivered"):
        messages.info(request, "This order is already paid/confirmed.")
        return redirect("crossroad_deals:my_orders")

    if request.method == "POST":
        provider = (request.POST.get("provider") or "").lower()
        if provider not in ALLOWED_PROVIDERS:
            return HttpResponseBadRequest("Invalid provider")

        order.payment_method = provider
        order.save(update_fields=["payment_method"])

        # ✅ Start payment (provider-specific)
        # Return a redirect URL OR a payment token/page
        start = start_payment_for_provider(request, order, provider)

        # start can be {"redirect_url": "..."} or {"error": "..."}
        if start.get("error"):
            messages.error(request, start["error"])
            return redirect("crossroad_deals:order_pay", order_id=order.order_id)

        return redirect(start["redirect_url"])

    return render(request, "crossroad_deals/order_pay.html", {"order": order, "providers": sorted(ALLOWED_PROVIDERS)})


def start_payment_for_provider(request, order, provider):
    """
    This is where you integrate each provider.
    Best practice: server creates a transaction and gets a redirect/checkout url from the provider.
    Do NOT store PIN/card. Collect any sensitive data only on provider side or through secure gateway.
    """
    amount = float(order.total_amount)

    # ✅ Example placeholders:
    if provider in ("wave", "qmoney", "afrimoney", "waychit"):
        # typically mobile money push / checkout page
        # return provider redirect URL that will callback to our payment_callback
        callback_url = request.build_absolute_uri(
            reverse("crossroad_deals:payment_callback", args=[provider])
        )
        # TODO: call provider API, get checkout_url + reference
        # reference = provider_api.create_payment(amount=amount, callback_url=callback_url, ...)
        reference = f"{provider.upper()}-{order.order_id}"
        order.payment_reference = reference
        order.save(update_fields=["payment_reference"])
        return {"redirect_url": callback_url + f"?ref={reference}&status=success"}  # placeholder

    if provider == "verve":
        # card payment gateway checkout
        callback_url = request.build_absolute_uri(
            reverse("crossroad_deals:payment_callback", args=[provider])
        )
        reference = f"VERVE-{order.order_id}"
        order.payment_reference = reference
        order.save(update_fields=["payment_reference"])
        return {"redirect_url": callback_url + f"?ref={reference}&status=success"}  # placeholder

    return {"error": "Payment provider not supported."}


def payment_callback(request, provider):
    provider = (provider or "").lower()
    if provider not in ALLOWED_PROVIDERS:
        return HttpResponseBadRequest("Invalid provider")

    ref = request.GET.get("ref")
    status = request.GET.get("status")  # success/failed/etc

    # find order by reference
    order = get_object_or_404(CrossroadOrder, payment_reference=ref)

    if status == "success":
        # Mark paid
        order.status = "paid"
        order.paid_at = timezone.now()
        order.save(update_fields=["status", "paid_at"])

        # Confirm and generate receipt (your existing flow)
        # You can keep confirmed separate if you want manual seller confirm
        order.status = "confirmed"
        order.confirmed_at = timezone.now()
        order.save(update_fields=["status", "confirmed_at"])

        # generate receipt if you have it
        try:
            order.generate_receipt()
        except Exception:
            pass

        messages.success(request, "Payment successful. Your order is confirmed.")
        return redirect("crossroad_deals:my_orders")

    messages.error(request, "Payment failed or cancelled.")
    return redirect("crossroad_deals:order_pay", order_id=order.order_id)

@csrf_exempt
def payment_webhook(request, provider):
    provider = (provider or "").lower()
    if provider not in ALLOWED_PROVIDERS:
        return HttpResponseBadRequest("Invalid provider")

    # TODO: verify signature header etc.
    # payload = json.loads(request.body)

    # Example parsing:
    # ref = payload.get("reference")
    # paid = payload.get("paid") is True

    return JsonResponse({"ok": True})
