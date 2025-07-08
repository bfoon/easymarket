from django.db import models
from django.conf import settings


class ChatThreadManager(models.Manager):
    def get_or_create_between(self, user1, user2):
        thread = self.filter(participants=user1).filter(participants=user2).first()
        if thread:
            return thread, False
        thread = self.create()
        thread.participants.add(user1, user2)
        return thread, True

class ChatThread(models.Model):
    participants = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='chat_threads')
    updated_at = models.DateTimeField(auto_now=True)

    objects = ChatThreadManager()

    def __str__(self):
        return f"ChatThread ({self.id})"


class ChatMessage(models.Model):
    thread = models.ForeignKey('ChatThread', on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='chat_sent_messages')
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.sender.username}: {self.message[:30]}"
