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
    path('my-auctions/', views.my_auctions, name='my_auctions'),
    path('my-bids/', views.my_bids, name='my_bids'),
    path('watchlist/', views.watchlist, name='watchlist'),
    path('won/', views.won_auctions, name='won_auctions'),

    # Categories and stores
    path('category/<int:category_id>/', views.category_view, name='category'),
    path('store/<slug:store_slug>/', views.store_auctions, name='store_auctions'),
    path('manage/<slug:store_slug>/', views.manage_store_auctions, name='manage_store_auctions'),

    # API endpoints
    path('api/<uuid:pk>/status/', views.auction_status_api, name='auction_status_api'),
    path('api/search-suggestions/', views.search_suggestions, name='search_suggestions'),
]