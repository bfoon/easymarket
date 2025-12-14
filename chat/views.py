# chat/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.urls import reverse
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from .models import ChatThread, ChatMessage
from marketplace.models import Product
from stores.models import Store
from orders.models import Order


def _is_store_owner(user, store: Store) -> bool:
    return getattr(store, "owner_id", None) == getattr(user, "id", None)


@login_required
def start_chat(request):
    """
    Start chat from product page (pre-order chat).
    Requires product_id. Creates/gets a thread for (buyer, store owner, product).
    """
    if request.method != "POST":
        return redirect("marketplace:product_list")

    product_id = request.POST.get("product_id")
    if not product_id:
        return redirect("marketplace:product_list")

    product = get_object_or_404(Product, id=product_id)

    # resolve store from product
    if not hasattr(product, "store") or not product.store_id:
        return redirect("marketplace:product_detail", product_id=product.id)

    store = product.store
    recipient = getattr(store, "owner", None)
    if recipient is None:
        return redirect("marketplace:product_detail", product_id=product.id)

    # Create/get contextual product thread (thread_id stays ChatThread.id)
    thread, _ = ChatThread.objects.get_or_create_between(
        request.user, recipient,
        store=store,
        product=product,
        order=None
    )

    message_text = (request.POST.get("message") or "").strip()
    if message_text:
        ChatMessage.objects.create(thread=thread, sender=request.user, message=message_text)
        # bump ordering
        thread.updated_at = timezone.now()
        thread.save(update_fields=["updated_at"])

    return redirect(reverse("chat:thread_detail", kwargs={"store_id": store.id, "thread_id": thread.id}))


@login_required
def start_chat_with_store(request, store_id):
    """
    Start chat in an order/shipment context (post-order chat).
    Pass ?order_id=123 (and optional shipment_id).
    """
    store = get_object_or_404(Store, id=store_id)
    order_id = request.GET.get("order_id")
    shipment_id = request.GET.get("shipment_id")

    if not order_id:
        return redirect("stores:store_detail", slug=store.slug) if hasattr(store, "slug") else redirect("stores:store_list")

    order = get_object_or_404(Order, id=order_id)

    recipient = getattr(store, "owner", None)
    if recipient is None:
        raise PermissionDenied("Store owner not found.")

    # buyer must own order OR store owner/superuser can open
    if not (request.user.is_superuser or _is_store_owner(request.user, store) or order.buyer_id == request.user.id):
        raise PermissionDenied

    # create/get order-context thread between buyer and store owner
    thread, _ = ChatThread.objects.get_or_create_between(
        order.buyer, recipient,
        store=store,
        order=order,
        product=None
    )

    url = reverse("chat:thread_detail", kwargs={"store_id": store.id, "thread_id": thread.id})
    if shipment_id:
        url += f"?shipment_id={shipment_id}"
    return redirect(url)


@login_required
def chat_thread_detail(request, store_id, thread_id):
    store = get_object_or_404(Store, id=store_id)

    thread = get_object_or_404(
        ChatThread.objects.select_related("store", "product", "order").prefetch_related("participants"),
        id=thread_id,
        store=store
    )

    is_store_owner = _is_store_owner(request.user, store)

    # permission: must be store owner/superuser OR a participant
    if not (request.user.is_superuser or is_store_owner or thread.participants.filter(id=request.user.id).exists()):
        raise PermissionDenied

    # mark unread incoming as read
    (thread.messages
        .filter(is_read=False)
        .exclude(sender=request.user)
        .update(is_read=True, read_at=timezone.now())
    )

    messages = thread.messages.select_related("sender").order_by("timestamp")

    shipment_id = request.GET.get("shipment_id")
    shipment = None
    if shipment_id:
        from logistics.models import Shipment
        shipment = Shipment.objects.filter(id=shipment_id).first()

    # Sidebar threads for this store:
    # - store owner sees all store threads
    # - buyer sees only their threads for this store
    if is_store_owner or request.user.is_superuser:
        all_threads = (
            ChatThread.objects
            .filter(store=store)
            .select_related("product", "order")
            .prefetch_related("participants")
            .order_by("-updated_at")
        )
    else:
        all_threads = (
            ChatThread.objects
            .filter(store=store, participants=request.user)
            .select_related("product", "order")
            .prefetch_related("participants")
            .order_by("-updated_at")
        )

    threads_data = []
    for t in all_threads:
        last = t.messages.order_by("-timestamp").first()
        unread = t.messages.filter(is_read=False).exclude(sender=request.user).count()

        # For store owner, show buyer as participant; for buyer, show store owner
        participant = t.get_other_participant(request.user)

        threads_data.append({
            "thread": t,
            "participant": participant,
            "last_message": (last.message if last else ""),
            "timestamp": (last.timestamp if last else None),
            "unread_count": unread,
            "label": t.context_label,
        })

    other_user = thread.get_other_participant(request.user)

    return render(request, "chat/thread_detail.html", {
        "store": store,
        "thread": thread,
        "messages": messages,
        "threads": threads_data,
        "current_thread_id": thread.id,
        "shipment": shipment,
        "other_user": other_user,
    })


@require_POST
@login_required
def send_message(request, thread_id):
    thread = get_object_or_404(
        ChatThread.objects.select_related("store").prefetch_related("participants"),
        id=thread_id
    )

    store = thread.store
    is_store_owner = _is_store_owner(request.user, store)

    # permission: must be store owner/superuser OR a participant
    if not (request.user.is_superuser or is_store_owner or thread.participants.filter(id=request.user.id).exists()):
        raise PermissionDenied

    message_text = (request.POST.get("message") or "").strip()
    if not message_text:
        return redirect(request.META.get("HTTP_REFERER", "/"))

    ChatMessage.objects.create(thread=thread, sender=request.user, message=message_text)

    thread.updated_at = timezone.now()
    thread.save(update_fields=["updated_at"])

    shipment_id = request.GET.get("shipment_id")
    url = reverse("chat:thread_detail", kwargs={"store_id": store.id, "thread_id": thread.id})
    if shipment_id:
        url += f"?shipment_id={shipment_id}"
    return redirect(url)


@require_POST
@login_required
def send_chat_message(request):
    """
    AJAX send.
    """
    if request.headers.get("x-requested-with") != "XMLHttpRequest":
        return JsonResponse({"success": False, "message": "Invalid request."}, status=400)

    thread_id = request.POST.get("thread_id")
    message_text = (request.POST.get("message") or "").strip()

    if not thread_id:
        return JsonResponse({"success": False, "message": "Missing thread_id."}, status=400)
    if not message_text:
        return JsonResponse({"success": False, "message": "Message cannot be empty."}, status=400)

    thread = get_object_or_404(
        ChatThread.objects.select_related("store").prefetch_related("participants"),
        id=thread_id
    )

    store = thread.store
    is_store_owner = _is_store_owner(request.user, store)

    if not (request.user.is_superuser or is_store_owner or thread.participants.filter(id=request.user.id).exists()):
        return JsonResponse({"success": False, "message": "Forbidden."}, status=403)

    msg = ChatMessage.objects.create(thread=thread, sender=request.user, message=message_text)

    thread.updated_at = timezone.now()
    thread.save(update_fields=["updated_at"])

    return JsonResponse({
        "success": True,
        "id": msg.id,
        "message": msg.message,
        "timestamp": msg.timestamp.isoformat(),
        "sender_id": msg.sender_id,
    })

@login_required
def my_store_threads(request, store_id):
    store = get_object_or_404(Store, id=store_id)

    # Only threads where I am a participant
    qs = (
        ChatThread.objects
        .filter(store=store, participants=request.user)
        .select_related("product", "order", "store")
        .prefetch_related("participants")
        .order_by("-updated_at")
    )

    threads_data = []
    for t in qs:
        other = t.get_other_participant(request.user)
        last = t.messages.order_by("-timestamp").first()

        threads_data.append({
            "thread": t,
            "participant": other,
            "order": t.order,
            "product": t.product,
            "last_message": last.message if last else "",
            "last_message_time": last.timestamp if last else None,
        })

    return render(request, "stores/chat_panel.html", {
        "store": store,
        "threads": threads_data,
    })
