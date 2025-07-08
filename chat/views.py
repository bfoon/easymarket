from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import ChatThread, ChatMessage
from marketplace.models import Product
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()

@login_required
def start_chat(request):
    if request.method == 'POST':
        recipient_id = request.POST.get('recipient_id')
        product_id = request.POST.get('product_id')  # so we can redirect back

        if not recipient_id or not product_id:
            return redirect('marketplace:product_list')

        recipient = get_object_or_404(User, id=recipient_id)

        # Prevent chatting with self
        if recipient == request.user:
            return redirect('marketplace:product_detail', product_id=product_id)

        # Get or create chat thread
        thread, _ = ChatThread.objects.get_or_create_between(request.user, recipient)

        # Save message
        message_text = request.POST.get('message', '').strip()
        if message_text:
            ChatMessage.objects.create(
                thread=thread,
                sender=request.user,
                message=message_text
            )

        # Redirect back to the same product page
        return redirect('marketplace:product_detail', product_id=product_id)


    return redirect('marketplace:product_list')
