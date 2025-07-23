from django.contrib import admin
from django.utils.html import format_html
from .models import (
    AuctionCategory, Auction, Bid, Watchlist,
    AuctionImage, AuctionQuestion, AuctionReview
)


@admin.register(AuctionCategory)
class AuctionCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'marketplace_category', 'is_active', 'auction_count', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'description']

    def auction_count(self, obj):
        return obj.auctions.count()

    auction_count.short_description = 'Total Auctions'


class AuctionImageInline(admin.TabularInline):
    model = AuctionImage
    extra = 1


class BidInline(admin.TabularInline):
    model = Bid
    extra = 0
    readonly_fields = ['timestamp', 'is_winning']


@admin.register(Auction)
class AuctionAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'seller', 'store', 'category', 'auction_type', 'current_price_display',
        'status', 'end_date', 'bid_count', 'view_count'
    ]
    list_filter = [
        'status', 'auction_type', 'category', 'featured',
        'shipping_required', 'international_shipping', 'created_at', 'store'
    ]
    search_fields = ['title', 'description', 'seller__username', 'store__name']
    date_hierarchy = 'created_at'
    inlines = [AuctionImageInline, BidInline]
    readonly_fields = ['view_count', 'platform_fee', 'seller_earnings', 'created_at', 'updated_at']

    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'description', 'category', 'auction_type', 'seller', 'store')
        }),
        ('Product Integration', {
            'fields': ('marketplace_product',)
        }),
        ('Pricing', {
            'fields': ('starting_bid', 'current_bid', 'reserve_price', 'buy_now_price', 'increment_amount')
        }),
        ('Financial', {
            'fields': ('commission_rate', 'platform_fee', 'seller_earnings'),
            'classes': ('collapse',)
        }),
        ('Timing', {
            'fields': ('start_date', 'end_date', 'auto_extend')
        }),
        ('Media', {
            'fields': ('image',)
        }),
        ('Shipping & Logistics', {
            'fields': ('shipping_required', 'shipping_cost', 'international_shipping')
        }),
        ('Status & Integration', {
            'fields': ('status', 'featured', 'order', 'payment', 'shipment', 'winner')
        }),
        ('Statistics', {
            'fields': ('view_count', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )

    def current_price_display(self, obj):
        price = obj.current_price
        color = 'green' if obj.reserve_met else 'red'
        return format_html(
            '<span style="color: {};">D{}</span>',
            color, price
        )

    current_price_display.short_description = 'Current Price'

    def bid_count(self, obj):
        return obj.bids.count()

    bid_count.short_description = 'Bids'


@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    list_display = ['auction', 'bidder', 'amount', 'timestamp', 'is_winning', 'is_auto_bid']
    list_filter = ['is_winning', 'is_auto_bid', 'timestamp']
    search_fields = ['auction__title', 'bidder__username']
    date_hierarchy = 'timestamp'


@admin.register(Watchlist)
class WatchlistAdmin(admin.ModelAdmin):
    list_display = ['user', 'auction', 'notify_outbid', 'notify_ending', 'created_at']
    list_filter = ['notify_outbid', 'notify_ending', 'created_at']
    search_fields = ['user__username', 'auction__title']


@admin.register(AuctionQuestion)
class AuctionQuestionAdmin(admin.ModelAdmin):
    list_display = ['auction', 'questioner', 'question_preview', 'is_public', 'answered_at']
    list_filter = ['is_public', 'created_at', 'answered_at']
    search_fields = ['auction__title', 'questioner__username', 'question']

    def question_preview(self, obj):
        return obj.question[:50] + '...' if len(obj.question) > 50 else obj.question

    question_preview.short_description = 'Question'


@admin.register(AuctionReview)
class AuctionReviewAdmin(admin.ModelAdmin):
    list_display = ['auction', 'seller_communication', 'item_accuracy', 'shipping_speed', 'would_buy_again']
    list_filter = ['seller_communication', 'item_accuracy', 'shipping_speed', 'would_buy_again']
    search_fields = ['auction__title']