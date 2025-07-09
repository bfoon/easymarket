from django.urls import path
from . import views

urlpatterns = [
    path('submit/', views.submit_review, name='submit_review'),
    path('delete/', views.delete_review, name='delete_review'),
    path('comment/submit/', views.submit_comment, name='submit_comment'),
    path('comment/delete/', views.delete_comment, name='delete_comment'),
    path('load/<int:product_id>/', views.load_reviews, name='load_reviews'),
]