# ==============================================================================
# CUSTOM TEMPLATE TAG FOR PRODUCT IMAGES
# ==============================================================================
# File: stores/templatetags/product_image_tags.py
#
# This creates a reusable template tag that handles all product image formats
# ==============================================================================

from django import template
from django.conf import settings
import os

register = template.Library()


@register.simple_tag
def get_product_image_url(product, default='images/placeholder.jpg'):
    """
    Universal product image getter that handles multiple image field formats.

    Tries in order:
    1. product.images.first().image.url (related ProductImage model)
    2. product.image.url (direct ImageField)
    3. product.primary_image.url (alternate field name)
    4. product.thumbnail.url (thumbnail field)
    5. Returns default placeholder

    Usage in template:
        {% load product_image_tags %}
        <img src="{% get_product_image_url product %}" alt="{{ product.name }}">

    Args:
        product: Product model instance
        default: Path to default image (relative to STATIC_URL)

    Returns:
        str: URL to product image or placeholder
    """

    # Try related images collection (most common)
    try:
        if hasattr(product, 'images') and product.images.exists():
            first_image = product.images.first()
            if first_image and hasattr(first_image, 'image') and first_image.image:
                return first_image.image.url
    except Exception as e:
        pass

    # Try direct image field
    try:
        if hasattr(product, 'image') and product.image:
            return product.image.url
    except Exception:
        pass

    # Try primary_image field
    try:
        if hasattr(product, 'primary_image') and product.primary_image:
            return product.primary_image.url
    except Exception:
        pass

    # Try thumbnail field
    try:
        if hasattr(product, 'thumbnail') and product.thumbnail:
            return product.thumbnail.url
    except Exception:
        pass

    # Try photo field (some models use this)
    try:
        if hasattr(product, 'photo') and product.photo:
            return product.photo.url
    except Exception:
        pass

    # Return placeholder
    if default.startswith('http'):
        return default
    else:
        return f"{settings.STATIC_URL}{default}"


@register.simple_tag
def get_product_images(product, limit=None):
    """
    Get all images for a product.

    Usage:
        {% get_product_images product as images %}
        {% for img in images %}
            <img src="{{ img.url }}" alt="{{ product.name }}">
        {% endfor %}

    Args:
        product: Product model instance
        limit: Maximum number of images to return

    Returns:
        list: List of image objects with .url attribute
    """
    images = []

    # Try related images collection
    try:
        if hasattr(product, 'images'):
            queryset = product.images.all()
            if limit:
                queryset = queryset[:limit]
            for img in queryset:
                if hasattr(img, 'image') and img.image:
                    images.append(img.image)
    except Exception:
        pass

    # If no images found, try single image fields
    if not images:
        for field_name in ['image', 'primary_image', 'thumbnail', 'photo']:
            try:
                if hasattr(product, field_name):
                    img = getattr(product, field_name)
                    if img:
                        images.append(img)
                        break
            except Exception:
                continue

    return images


@register.filter
def has_image(product):
    """
    Check if product has any image.

    Usage:
        {% if product|has_image %}
            <img src="{% get_product_image_url product %}">
        {% else %}
            <div class="no-image">No image available</div>
        {% endif %}

    Returns:
        bool: True if product has at least one image
    """
    # Check related images
    try:
        if hasattr(product, 'images') and product.images.exists():
            return True
    except Exception:
        pass

    # Check direct image fields
    for field_name in ['image', 'primary_image', 'thumbnail', 'photo']:
        try:
            if hasattr(product, field_name):
                img = getattr(product, field_name)
                if img:
                    return True
        except Exception:
            continue

    return False