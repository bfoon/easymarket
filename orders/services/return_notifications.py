from threading import Thread
from django.conf import settings
from django.urls import reverse

# Replace these with your actual utilities:
# from core.mailers import send_email
# from core.whatsapp import send_whatsapp
from marketplace.notifications import send_email, send_whatsapp  # <-- adjust import
# orders/services/return_notifications.py (optional)
from accounts.models import AdminLog, User

def _log(kind, message, user: "User|None" = None, related_model="Return", related_id=""):
    try:
        AdminLog.objects.create(
            action_type=kind,            # use an existing type like 'complaint' or extend ACTION_TYPES
            related_object_id=str(related_id),
            related_model=related_model,
            message=message,
            created_by=user if isinstance(user, User) else None,
        )
    except Exception:
        pass

def _spawn(target, *args, **kwargs):
    Thread(target=target, args=args, kwargs=kwargs, daemon=True).start()

def _abs_url(path: str) -> str:
    base = getattr(settings, "SITE_URL", "").rstrip("/")
    return f"{base}{path}"

def _reverse_or_empty(name, **kwargs) -> str:
    try:
        return reverse(name, kwargs=kwargs)
    except Exception:
        return ""

def _get_phone(user):
    # You store phone on accounts.User.telephone
    return (getattr(user, "telephone", "") or "").strip()

# ---------------- Public API ---------------- #

def notify_store_return_created(ret, store, owner_user):
    """
    Notify the store owner when a new Return is created that includes this store's items.
    """
    rma = ret.return_number
    subject = f"New Return Request: {rma}"
    body = (
        f"A new return was created for Order #{ret.order_id} by "
        f"{ret.buyer.get_full_name()}.\n"
        f"Reason: {ret.get_reason_display()}.\n"
        f"Estimated refund: D{ret.refund_amount:.2f}."
    )
    path = _reverse_or_empty('returns:store_detail', store_id=str(store.id), rma=rma)
    url  = _abs_url(path)
    body_full = f"{body}\n\nOpen: {url}" if url else body

    if getattr(owner_user, "email", ""):
        _spawn(send_email, subject, body_full, [owner_user.email])

    phone = _get_phone(owner_user)
    if phone:
        _spawn(send_whatsapp, phone, f"{subject}\n{body}\n{url}")

def notify_buyer_status_change(ret, history):
    """
    Notify buyer when return status changes.
    Your choices: pending, approved, rejected, in_transit, received, completed, cancelled
    """
    status = history.status
    rma = ret.return_number

    if status == 'approved':
        subject = f"Return Approved: {rma}"
        msg     = "Your return was approved. Please follow pickup/collection instructions."
    elif status == 'rejected':
        subject = f"Return Rejected: {rma}"
        reason  = (history.notes or "").strip()
        msg     = f"Your return was rejected.{(' Reason: ' + reason) if reason else ''}"
    elif status == 'in_transit':
        subject = f"Items In Transit: {rma}"
        msg     = "Your return parcel is on the way to the store."
    elif status == 'received':
        subject = f"Items Received: {rma}"
        msg     = "The store has received your returned items and will process them."
    elif status == 'completed':
        subject = f"Refund Completed: {rma}"
        msg     = f"Your refund has been processed. Amount: D{ret.refund_amount:.2f}."
    elif status == 'cancelled':
        subject = f"Return Cancelled: {rma}"
        msg     = "Your return request has been cancelled."
    else:  # pending / fallback
        subject = f"Return Update: {rma}"
        msg     = f"Status updated to {ret.get_status_display()}."

    path = _reverse_or_empty('returns:buyer_detail', rma=rma)
    url  = _abs_url(path)
    body = f"{msg}\n\nView details: {url}" if url else msg

    if getattr(ret.buyer, "email", ""):
        _spawn(send_email, subject, body, [ret.buyer.email])

    phone = _get_phone(ret.buyer)
    if phone:
        _spawn(send_whatsapp, phone, f"{subject}\n{msg}\n{url}")