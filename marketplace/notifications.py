from django.core.mail import send_mail
import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from marketplace.models import Product, Wishlist
from django.db import transaction


def send_email(subject, message, recipient_list):
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipient_list)

def send_whatsapp(phone_number, message):
    try:
        requests.post(
            'https://api.twilio.com/2010-04-01/Accounts/ACa0ca58dacb6f9255c9efb3eeaa17026c/Messages.json',
            data={
                'From': f'whatsapp:{settings.TWILIO_WHATSAPP_NUMBER}',
                'To': f'whatsapp:{phone_number}',
                'Body': message,
            },
            auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        )
    except Exception as e:
        print("WhatsApp notification failed:", e)


def _safe_send_mail(to, subject, body):
    if not to:
        return
    try:
        send_mail(subject, body, "no-reply@easymarket.com", [to], fail_silently=True)
    except Exception:
        pass

def notify_wishlist_price_change_threadsafe(product_id, old_price, new_price):
    try:
        product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return

    qs = Wishlist.objects.select_related("user").filter(product_id=product_id)
    to_update = []
    for item in qs:
        # Notify only if user baseline differs from new price (prevents duplicate mails)
        if item.last_known_price != new_price:
            _safe_send_mail(
                item.user.email,
                f"Price change: {product.name}",
                f"The price changed from {old_price} to {new_price}."
            )
            item.last_known_price = new_price
            to_update.append(item)

    if to_update:
        with transaction.atomic():
            for item in to_update:
                item.save(update_fields=["last_known_price"])

def notify_wishlist_back_in_stock_threadsafe(product_id, old_qty, new_qty):
    if not (old_qty is not None and old_qty <= 0 and new_qty > 0):
        return

    try:
        product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return

    qs = Wishlist.objects.select_related("user").filter(product_id=product_id)
    to_update = []
    for item in qs:
        # Only notify if the user’s baseline says it was not available
        if item.last_known_stock <= 0:
            _safe_send_mail(
                item.user.email,
                f"Back in stock: {product.name}",
                f"{product.name} is now available. Hurry before it sells out!"
            )
            item.last_known_stock = new_qty
            to_update.append(item)

    if to_update:
        with transaction.atomic():
            for item in to_update:
                item.save(update_fields=["last_known_stock"])
