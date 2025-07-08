from django.contrib import admin
from .models import ChatThread, ChatMessage

admin.site.register(ChatThread)
admin.site.register(ChatMessage)
