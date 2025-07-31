from django.urls import path
from . import views_returns as v

app_name = "returns"

urlpatterns = [
    path('returns/', v.returns_hub, name='hub'),
    path("policy/", v.return_policy, name="policy"),
    path('orders/<int:order_id>/store/<uuid:store_id>/returns/start/', v.start_return, name='start'),
    path('returns/<str:rma>/', v.return_detail_buyer, name='buyer_detail'),
    path('store/<uuid:store_id>/returns/<str:rma>/', v.return_detail_store, name='store_detail'),
    path("store/<uuid:store_id>/", v.store_returns, name="store_returns"),

    path('store/<uuid:store_id>/returns/<str:rma>/approve/', v.store_approve_return, name='approve'),
    path('store/<uuid:store_id>/returns/<str:rma>/reject/', v.store_reject_return, name='reject'),
    path('store/<uuid:store_id>/returns/<str:rma>/mark-received/', v.store_mark_received, name='mark_received'),
    path('store/<uuid:store_id>/returns/<str:rma>/finalize-refund/', v.store_finalize_refund, name='finalize_refund'),
    path('store/<uuid:store_id>/returns/<str:rma>/fulfill-exchange/', v.store_fulfill_exchange, name='fulfill_exchange'),


    path(
        "store/<uuid:store_id>/returns/<str:rma>/add-note/",
        v.add_return_note,
        name="add_note",
    ),
]
