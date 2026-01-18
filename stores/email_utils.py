"""
Email Utilities for Image URLs

Add this file as: stores/email_utils.py

Then import it in your Store model or wherever you send emails.
"""

from django.conf import settings


def get_absolute_image_url(image_field_or_url):
    """
    Convert a Django ImageField or relative URL to an absolute URL for emails.

    Args:
        image_field_or_url: Can be:
            - Django ImageField (product.image)
            - String URL ('/media/products/image.jpg')
            - None/empty

    Returns:
        Absolute URL string or empty string if no image

    Usage:
        product_image = get_absolute_image_url(product.image)
        # Returns: 'https://yourdomain.com/media/products/image.jpg'
    """
    # Handle None or empty
    if not image_field_or_url:
        return ''

    # Get URL from ImageField or use string directly
    if hasattr(image_field_or_url, 'url'):
        relative_url = image_field_or_url.url
    else:
        relative_url = str(image_field_or_url)

    # If already absolute, return as is
    if relative_url.startswith('http://') or relative_url.startswith('https://'):
        return relative_url

    # Get site URL from settings
    site_url = getattr(settings, 'SITE_URL', 'http://localhost:8000')
    site_url = site_url.rstrip('/')

    # Ensure relative URL starts with /
    if not relative_url.startswith('/'):
        relative_url = '/' + relative_url

    return f"{site_url}{relative_url}"


def prepare_product_context_for_email(product):
    """
    Prepare product data with absolute URLs for email templates.

    Args:
        product: Product instance

    Returns:
        dict with product data ready for email templates
    """
    context = {
        'product_name': product.name,
        'product_description': product.description or '',
        'product_url': get_absolute_image_url(product.get_absolute_url()),
        'product_image': get_absolute_image_url(product.image),
        'product_price': f"{float(product.price):.2f}",
    }

    # Add discount info if applicable
    if product.original_price and product.original_price > product.price:
        discount = ((product.original_price - product.price) / product.original_price) * 100
        context.update({
            'original_price': f"{float(product.original_price):.2f}",
            'discount_percentage': f"{discount:.0f}",
        })

    # Add product features if available
    if hasattr(product, 'specifications') and product.specifications:
        # Split specifications into list (assuming they're line-separated)
        features = [f.strip() for f in product.specifications.split('\n') if f.strip()]
        context['product_features'] = features[:5]  # Max 5 features

    return context


def get_similar_products_for_email(product, limit=3):
    """
    Get similar products with absolute URLs for email.

    Args:
        product: Product instance
        limit: Number of similar products to return

    Returns:
        List of dicts with similar product data
    """
    similar_products = []

    # Get products from same category and store
    if product.category and product.store:
        similar = product.category.product_set.filter(
            is_active=True,
            store=product.store
        ).exclude(id=product.id)[:limit]

        similar_products = [
            {
                'name': p.name,
                'price': f"{float(p.price):.2f}",
                'url': get_absolute_image_url(p.get_absolute_url()),
                'image': get_absolute_image_url(p.image),
            }
            for p in similar
        ]

    return similar_products