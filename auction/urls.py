from django.urls import path
from . import views

app_name = 'auction'

urlpatterns = [
    # Main auction URLs
    path('', views.AuctionListView.as_view(), name='index'),
    path('<uuid:pk>/', views.auction_detail, name='detail'),
    path('<uuid:pk>/bid/', views.place_bid, name='place_bid'),
    path('<uuid:pk>/buy-now/', views.buy_now, name='buy_now'),
    path('<uuid:pk>/question/', views.ask_question, name='ask_question'),
    path('<uuid:pk>/watchlist/', views.toggle_watchlist, name='toggle_watchlist'),
    path('<uuid:pk>/payment/', views.auction_payment, name='payment'),

    # User management
    path('create/', views.create_auction, name='create'),
    path('<uuid:pk>/edit/', views.edit_auction, name='edit'),
    path('my-auctions/', views.my_auctions, name='my_auctions'),
    path('my-bids/', views.my_bids, name='my_bids'),
    path('watchlist/', views.watchlist, name='watchlist'),
    path('won/', views.won_auctions, name='won_auctions'),

    # Categories and stores
    path('category/<int:category_id>/', views.category_view, name='category'),
    path('store/<slug:store_slug>/', views.store_auctions, name='store_auctions'),
    path('manage/<slug:store_slug>/', views.manage_store_auctions, name='manage_store_auctions'),

    # Order creation for won auctions
    path('won/<uuid:pk>/create-order/', views.create_order_for_auction, name='create_order_for_auction'),
    path('won/<uuid:pk>/order/', views.auction_order_detail, name='auction_order'),

    # API endpoints
    path('api/<uuid:pk>/status/', views.auction_status_api, name='auction_status_api'),
    path('api/search-suggestions/', views.search_suggestions, name='search_suggestions'),

    path('<uuid:pk>/ajax/recent-bids/', views.ajax_auction_bids, name='ajax_recent_bids'),
    path('<uuid:pk>/ajax/current-bid/', views.ajax_current_bid, name='ajax_current_bid'),
    path('<uuid:pk>/ajax/questions/', views.ajax_questions, name='ajax_questions'),

]