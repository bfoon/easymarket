from django.db import models
from django.conf import settings
from django.utils import timezone
from django.urls import reverse
from decimal import Decimal
import uuid


class AuctionCategory(models.Model):
    """Auction-specific categories that link to marketplace categories"""
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    marketplace_category = models.ForeignKey(
        'marketplace.Category',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Link to marketplace category",
        related_name='auction_categories'
    )
    icon = models.CharField(max_length=50, blank=True, help_text="FontAwesome icon class")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Auction Categories"
        ordering = ['name']

    def __str__(self):
        return self.name


class Auction(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('ended', 'Ended'),
        ('cancelled', 'Cancelled'),
        ('sold', 'Sold'),
        ('payment_pending', 'Payment Pending'),
    ]

    AUCTION_TYPE_CHOICES = [
        ('standard', 'Standard Auction'),
        ('reserve', 'Reserve Auction'),
        ('buy_now', 'Auction with Buy Now'),
        ('dutch', 'Dutch Auction'),
    ]

    # Basic auction information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    description = models.TextField()
    auction_type = models.CharField(max_length=20, choices=AUCTION_TYPE_CHOICES, default='standard')

    # Pricing
    starting_bid = models.DecimalField(max_digits=10, decimal_places=2)
    current_bid = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    reserve_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    buy_now_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    increment_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('1.00'))

    # Relationships with existing EasyMarket models
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='auctions')
    store = models.ForeignKey('stores.Store', on_delete=models.CASCADE, related_name='auctions')
    category = models.ForeignKey(AuctionCategory, on_delete=models.CASCADE, related_name='auctions')
    winner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='won_auctions'
    )

    # Link to marketplace product (if auction is for existing product)
    marketplace_product = models.ForeignKey(
        'marketplace.Product',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Link to existing marketplace product",
        related_name='auctions'
    )

    # Timing
    start_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField()
    auto_extend = models.BooleanField(default=False, help_text="Extend auction if bid placed in last 5 minutes")

    # Media
    image = models.ImageField(upload_to='auction_images/', blank=True, null=True)

    # Status and metadata
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    featured = models.BooleanField(default=False)
    view_count = models.PositiveIntegerField(default=0)

    # Shipping and logistics - integrate with existing Address model
    shipping_required = models.BooleanField(default=True)
    shipping_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    international_shipping = models.BooleanField(default=False)

    # Integration with existing order system
    order = models.OneToOneField(
        'orders.Order',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Order created when auction is won",
        related_name='auction'
    )

    # Payment integration
    payment = models.OneToOneField(
        'payments.Payment',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='auction'
    )

    # Logistics integration
    shipment = models.OneToOneField(
        'logistics.Shipment',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='auction'
    )

    # Financial tracking
    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('5.00'),
        help_text="Commission percentage for this auction"
    )
    platform_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    seller_earnings = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'end_date']),
            models.Index(fields=['category', 'status']),
            models.Index(fields=['seller', 'status']),
            models.Index(fields=['store', 'status']),
        ]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('auction:detail', kwargs={'pk': self.pk})

    @property
    def is_active(self):
        return self.status == 'active' and timezone.now() < self.end_date

    @property
    def time_remaining(self):
        if timezone.now() >= self.end_date:
            return "Auction ended"
        remaining = self.end_date - timezone.now()
        days = remaining.days
        hours, remainder = divmod(remaining.seconds, 3600)
        minutes, _ = divmod(remainder, 60)

        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"

    @property
    def current_price(self):
        return self.current_bid or self.starting_bid

    @property
    def minimum_bid(self):
        return self.current_price + self.increment_amount

    @property
    def winning_bid(self):
        return self.bids.filter(is_winning=True).first()

    @property
    def reserve_met(self):
        if not self.reserve_price:
            return True
        return self.current_price >= self.reserve_price

    def save(self, *args, **kwargs):
        # Set store from seller if not provided
        if not self.store_id and self.seller_id:
            user_store = self.seller.owned_stores.filter(status='active').first()
            if user_store:
                self.store = user_store

        # Calculate platform fees and seller earnings
        if self.current_bid:
            self.platform_fee = (self.current_bid * self.commission_rate) / 100
            self.seller_earnings = self.current_bid - self.platform_fee

        super().save(*args, **kwargs)

    def create_order_for_winner(self):
        """Create an order when auction ends with a winner - integrated with existing order system"""
        if not self.winner or self.order:
            return None

        from orders.models import Order, OrderItem, ShippingAddress
        from payments.models import Payment

        # Get winner's default shipping address or create a basic one
        shipping_address = self.winner.shipping_addresses.filter(is_default=True).first()
        if not shipping_address:
            # Create temporary shipping address from user's address
            user_address = self.winner.address_set.first()
            if user_address:
                shipping_address = ShippingAddress.objects.create(
                    user=self.winner,
                    full_name=self.winner.get_full_name(),
                    street=user_address.address1 or '',
                    city=user_address.address2 or '',
                    region='',
                    geo_code=user_address.geo_code or '',
                    country=user_address.country or 'Gambia',
                    phone_number=self.winner.telephone or '',
                    is_default=False
                )

        # Create order
        order = Order.objects.create(
            buyer=self.winner,
            status='pending',
            shipping_cost=self.shipping_cost,
            shipping_address=shipping_address,
            order_notes=f"Order created from auction: {self.title}"
        )

        # Create order item
        OrderItem.objects.create(
            order=order,
            product=self.marketplace_product if self.marketplace_product else None,
            quantity=1,
            price_at_time=self.current_price
        )

        # Create payment record
        payment = Payment.objects.create(
            order=order,
            method='pending',  # Will be set when user chooses payment method
            amount=order.get_total,
            status='pending'
        )

        # Link to auction
        self.order = order
        self.payment = payment
        self.status = 'payment_pending'
        self.save()

        # Create financial record for the store
        self._create_financial_records()

        return order

    def _create_financial_records(self):
        """Create financial records for auction completion"""
        from finance.models import FinancialRecord

        if not self.current_bid:
            return

        # Revenue record for the store
        FinancialRecord.objects.create(
            store=self.store,
            record_type='revenue',
            amount=self.seller_earnings,
            description=f"Auction sale - {self.title}",
            transaction_date=timezone.now().date(),
            category='sales',
            reference_number=f"AUCTION-{self.id}",
            order_reference=str(self.order.id) if self.order else None,
            processed_by=self.winner,
            is_confirmed=True,
            notes=f"Auction completed. Winner: {self.winner.username}"
        )

        # Commission record (expense for store)
        FinancialRecord.objects.create(
            store=self.store,
            record_type='commission',
            amount=self.platform_fee,
            description=f"Platform commission - {self.title}",
            transaction_date=timezone.now().date(),
            category='commission',
            reference_number=f"AUCTION-COMM-{self.id}",
            order_reference=str(self.order.id) if self.order else None,
            processed_by=self.winner,
            is_confirmed=True,
            notes=f"Commission fee for auction: {self.commission_rate}%"
        )

    def create_shipment_for_winner(self):
        """Create shipment when auction is won and paid"""
        if not self.winner or not self.order or self.shipment:
            return None

        from logistics.models import Shipment

        shipment = Shipment.objects.create(
            shipping_address=self.order.shipping_address,
            order=self.order,
            weight_kg=1.0,  # Default weight, can be updated
            size_cubic_meters=0.1,  # Default size
            material_type='standard',
            shipment_type='normal',
            packing_type='paper_box',
            container_type='paper',
            collect_time=timezone.now() + timezone.timedelta(days=self.store.processing_time),
            estimated_dropoff_time=timezone.now() + timezone.timedelta(days=self.store.processing_time + 3)
        )

        self.shipment = shipment
        self.save()

        return shipment


class Bid(models.Model):
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name='bids')
    bidder = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='auction_bids')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    timestamp = models.DateTimeField(auto_now_add=True)
    is_winning = models.BooleanField(default=False)
    is_auto_bid = models.BooleanField(default=False)
    max_auto_bid = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ['-timestamp']
        unique_together = ['auction', 'bidder', 'amount']
        indexes = [
            models.Index(fields=['auction', '-amount']),
            models.Index(fields=['bidder', '-timestamp']),
        ]

    def __str__(self):
        return f"{self.bidder.username} - ${self.amount} on {self.auction.title}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        # Update auction's current bid and winner
        auction = self.auction
        highest_bid = auction.bids.order_by('-amount').first()

        if highest_bid and highest_bid.pk == self.pk:
            # Mark all other bids as not winning
            auction.bids.exclude(pk=self.pk).update(is_winning=False)

            # Mark this bid as winning
            self.is_winning = True
            auction.current_bid = self.amount
            auction.winner = self.bidder
            auction.save(update_fields=['current_bid', 'winner'])
            super().save(update_fields=['is_winning'])


class Watchlist(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='auction_watchlist')
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name='watchers')
    created_at = models.DateTimeField(auto_now_add=True)
    notify_outbid = models.BooleanField(default=True)
    notify_ending = models.BooleanField(default=True)

    class Meta:
        unique_together = ['user', 'auction']

    def __str__(self):
        return f"{self.user.username} watching {self.auction.title}"


class AuctionImage(models.Model):
    """Additional images for auctions"""
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name='additional_images')
    image = models.ImageField(upload_to='auction_images/')
    alt_text = models.CharField(max_length=200, blank=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'created_at']


class AuctionQuestion(models.Model):
    """Questions from potential bidders - integrated with existing chat system"""
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name='questions')
    questioner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='auction_questions')
    question = models.TextField()
    answer = models.TextField(blank=True)
    is_public = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    answered_at = models.DateTimeField(null=True, blank=True)

    # Link to chat thread for private communication
    chat_thread = models.ForeignKey(
        'chat.ChatThread',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='auction_questions'
    )

    class Meta:
        ordering = ['-created_at']

    def create_chat_thread(self):
        """Create a chat thread between questioner and seller"""
        from chat.models import ChatThread
        thread, created = ChatThread.objects.get_or_create_between(
            self.questioner,
            self.auction.seller
        )
        self.chat_thread = thread
        self.save()
        return thread


class AuctionReview(models.Model):
    """Reviews for auction transactions - extends existing review system"""
    auction = models.OneToOneField(Auction, on_delete=models.CASCADE, related_name='auction_review')
    review = models.OneToOneField(
        'reviews.Review',
        on_delete=models.CASCADE,
        related_name='auction_review'
    )

    # Auction-specific review fields
    seller_communication = models.IntegerField(
        choices=[(i, i) for i in range(1, 6)],
        default=5,
        help_text="Rate seller communication (1-5)"
    )
    item_accuracy = models.IntegerField(
        choices=[(i, i) for i in range(1, 6)],
        default=5,
        help_text="How accurately was the item described (1-5)"
    )
    shipping_speed = models.IntegerField(
        choices=[(i, i) for i in range(1, 6)],
        default=5,
        help_text="Rate shipping speed (1-5)"
    )
    would_buy_again = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Auction review for {self.auction.title}"