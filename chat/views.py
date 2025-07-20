from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from .models import ChatThread, ChatMessage
from marketplace.models import Product
from stores.models import Store
from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.utils import timezone
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

@login_required
def chat_thread_detail(request, store_id, thread_id):
    thread = get_object_or_404(ChatThread, id=thread_id)

    # Ensure the user is a participant
    if request.user not in thread.participants.all():
        return redirect('stores:store_dashboard', store_id=store_id)

    # Mark all unread messages from other users as read
    unread_messages = thread.messages.filter(is_read=False).exclude(sender=request.user)
    unread_messages.update(is_read=True, read_at=timezone.now())

    # Fetch all messages
    messages = thread.messages.select_related('sender').order_by('timestamp')

    # Get the other user in the thread
    other_user = thread.participants.exclude(id=request.user.id).first()

    # Fetch all threads for the current user (with unread count)
    all_threads = ChatThread.objects.filter(participants=request.user).prefetch_related('participants', 'messages')
    threads_data = []
    for t in all_threads:
        participant = t.participants.exclude(id=request.user.id).first()
        last_msg = t.messages.order_by('-timestamp').first()
        unread_count = t.messages.filter(is_read=False).exclude(sender=request.user).count()

        threads_data.append({
            'thread': t,
            'participant': participant,
            'last_message': last_msg.message if last_msg else '',
            'timestamp': last_msg.timestamp if last_msg else '',
            'unread_count': unread_count,
        })

    return render(request, 'chat/thread_detail.html', {
        'thread': thread,
        'messages': messages,
        'other_user': other_user,
        'threads': threads_data,
        'current_thread': thread,
        'store': get_object_or_404(Store, id=store_id)  # Assuming `Store` model exists
    })