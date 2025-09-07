from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from django.urls import reverse
from django.utils import timezone
from marketplace.notifications import send_whatsapp, send_email

# --- Utilities ---------------------------------------------------------------

def _get_site_base_url() -> str:
    """
    Resolve a base URL for notifications (no request object available).
    Prefers settings.SITE_BASE_URL, then Sites framework, then a final fallback.
    """
    # 1) Explicit setting
    base = getattr(settings, "SITE_BASE_URL", "").strip()
    if base:
        return base.rstrip("/")

    # 2) Sites framework
    try:
        current_site ='easymarket.vip'#Site.objects.get_current()
        scheme = "https" if not settings.DEBUG else "http"
        return f"{scheme}://{current_site}".rstrip("/")
    except Exception:
        pass

    # 3) Final hardcoded fallback
    return "https://www.easymarket.vip"

def _get_order_seller_users(order):
    """
    Return a queryset of Users who are sellers with items in this order.
    Assumes order.items has product->seller relation.
    """
    User = get_user_model()
    seller_ids = (
        order.items
        .select_related('product__seller')
        .values_list('product__seller', flat=True)
        .distinct()
    )
    return User.objects.filter(id__in=seller_ids)

def _build_order_chat_url(order_id: int) -> str:
    """
    Make an absolute URL to the order chat screen.
    Adjust 'orders:order_chat' to your actual URL name.
    """
    base = _get_site_base_url()
    path = reverse('orders:order_detail', args=[order_id])  # e.g. /orders/123/chat/
    return f"{base}{path}"

def _preview(text: str, limit: int = 120) -> str:
    text = (text or "").strip()
    return (text[:limit] + "…") if len(text) > limit else text

# --- Notification ------------------------------------------------------------

def notify_new_order_message(chat_msg):
    """
    Notify the opposite party/parties when a new ChatMessage is created.

    ChatMessage model:
        order (FK to Order)
        sender (User)
        content (Text)
        created_at (auto_now_add)
        is_read (bool)
    """
    order = chat_msg.order
    sender = chat_msg.sender

    # Determine recipients:
    if sender == order.buyer:
        # Buyer messaged -> notify all sellers on this order
        recipients_qs = _get_order_seller_users(order)
        subject = f"💬 New message from Buyer • Order #{order.id}"
        role_label = "Buyer"
    else:
        # A seller messaged -> notify the buyer
        recipients_qs = get_user_model().objects.filter(id=order.buyer_id)
        subject = f"💬 New message from Seller • Order #{order.id}"
        role_label = "Seller"

    # Compose message
    chat_url = _build_order_chat_url(order.id)
    sender_name = sender.get_full_name() or getattr(sender, "username", "User")
    created_local = timezone.localtime(chat_msg.created_at).strftime("%Y-%m-%d %H:%M")

    body_text = (
        f"Order #{order.id}\n"
        f"From ({role_label}): {sender_name}\n"
        f"At: {created_local}\n\n"
        f"Message preview:\n{_preview(chat_msg.content, 200)}\n\n"
        f"Open chat: {chat_url}"
    )

    # Send notifications
    emails = [u.email for u in recipients_qs if getattr(u, "email", None)]
    tels = [getattr(u, "telephone", None) for u in recipients_qs if getattr(u, "telephone", None)]

    if emails:
        send_email(subject, body_text, emails)
    for tel in tels:
        send_whatsapp(tel, body_text)
