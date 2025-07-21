from django.urls import path
from . import views

app_name = 'chat'

urlpatterns = [
    path('start/', views.start_chat, name='start_chat'),
    path('send/', views.send_chat_message, name='send_chat_message'),
    path('start-chat/store/<uuid:store_id>/', views.start_chat_with_store, name='start_chat_with_store'),
    path('<uuid:store_id>/thread/<int:thread_id>/', views.chat_thread_detail, name='thread_detail'),
    path('thread/<int:thread_id>/send/', views.send_message, name='send_message'),
]
