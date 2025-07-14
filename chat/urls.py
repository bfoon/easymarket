from django.urls import path
from . import views

app_name = 'chat'

urlpatterns = [
    path('start/', views.start_chat, name='start_chat'),
    path('send/', views.send_chat_message, name='send_chat_message'),
]
