from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from .models import ChatThread, ChatMessage
from marketplace.models import Product
from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
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

@require_POST
@login_required
def send_chat_message(request):
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        recipient_id = request.POST.get('recipient_id')
        content = request.POST.get('message', '').strip()

        if not content or not recipient_id:
            return JsonResponse({'success': False, 'message': 'Missing recipient or message.'})

        try:
            recipient = User.objects.get(id=recipient_id)
            thread, _ = ChatThread.objects.get_or_create_between(request.user, recipient)

            ChatMessage.objects.create(
                thread=thread,
                sender=request.user,
                message=content
            )

            return JsonResponse({'success': True})
        except User.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'User not found.'})
    return JsonResponse({'success': False, 'message': 'Invalid request.'})
