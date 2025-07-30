# core/utils/urls.py
from django.conf import settings
from django.urls import reverse

def absolute_url(path: str) -> str:
    """
    Build an absolute URL to your site, e.g. https://easymarket.example.com + path
    Ensure you set SITE_BASE_URL in settings (e.g. https://easymarket.com)
    """
    base = getattr(settings, "SITE_BASE_URL", "").rstrip("/")
    return f"{base}{path}"

def product_url(product):
    return absolute_url(reverse("product_detail", kwargs={"pk": product.pk}))

def wishlist_url():
    return absolute_url(reverse("marketplace:my_wishlist"))
