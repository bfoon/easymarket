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
    store = get_object_or_404(Store, id=store_id)

    if request.user not in thread.participants.all():
        return redirect('stores:store_dashboard', store_id=store.id)

    thread.messages.filter(is_read=False).exclude(sender=request.user).update(
        is_read=True, read_at=timezone.now()
    )

    messages = thread.messages.select_related('sender').order_by('timestamp')
    other_user = thread.participants.exclude(id=request.user.id).first()

    # ✅ Get shipment from query param
    shipment_id = request.GET.get('shipment_id')
    shipment = None
    if shipment_id:
        from logistics.models import Shipment
        shipment = Shipment.objects.filter(id=shipment_id).first()

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
        'store': store,
        'shipment': shipment,  # ✅ Pass this to template
    })

@login_required
def start_chat_with_store(request, store_id):
    store = get_object_or_404(Store, id=store_id)
    recipient = store.owner

    # Always get or create a new thread between the logistics officer and store owner
    thread, created = ChatThread.objects.get_or_create_between(request.user, recipient)

    # Optional: get shipment_id from query param to keep context
    shipment_id = request.GET.get('shipment_id')

    # Redirect with shipment context if available
    url = reverse('chat:thread_detail', kwargs={'store_id': store.id, 'thread_id': thread.id})
    if shipment_id:
        url += f'?shipment_id={shipment_id}'

    return redirect(url)

@login_required
def send_message(request, thread_id):
    if request.method == 'POST':
        thread = get_object_or_404(ChatThread, id=thread_id)
        message = request.POST.get('message', '').strip()

        if message:
            ChatMessage.objects.create(thread=thread, sender=request.user, message=message)

        # Get other participant
        other_user = thread.participants.exclude(id=request.user.id).first()
        store = other_user.owned_stores.first()  # assuming related_name='stores' on Store model

        # Preserve shipment_id
        shipment_id = request.GET.get('shipment_id')
        url = reverse('chat:thread_detail', kwargs={'store_id': store.id, 'thread_id': thread.id})
        if shipment_id:
            url += f'?shipment_id={shipment_id}'

        return redirect(url)