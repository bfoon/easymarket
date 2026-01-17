# marketplace/templatetags/cart_image_tags.py

from django import template
from marketplace.models import ProductImage

register = template.Library()


@register.simple_tag
def get_color_image_url(product, selected_features):
    """
    Get the image URL for a product based on the selected color.

    Args:
        product: Product instance
        selected_features: dict containing selected features (including color)

    Returns:
        str: Image URL or empty string if no color-specific image found
    """
    if not selected_features:
        return product.display_image_url or ''

    # Check for color in selected features (case-insensitive)
    color_value = None
    for key, value in selected_features.items():
        if key.lower() == 'color':
            color_value = value
            break

    if not color_value:
        return product.display_image_url or ''

    # Try to find an image with the matching color variant
    try:
        # Get images that have color variants matching the selected color
        color_images = ProductImage.objects.filter(
            product=product,
            variants__feature__name__iexact='color',
            variants__value__iexact=color_value
        ).distinct()

        # Prefer primary image, otherwise get first match
        primary_img = color_images.filter(is_primary=True).first()
        if primary_img and primary_img.image:
            return primary_img.image.url

        # Fallback to any color-specific image
        first_img = color_images.first()
        if first_img and first_img.image:
            return first_img.image.url

    except Exception:
        pass

    # Fallback to default product image
    return product.display_image_url or ''


@register.simple_tag
def get_color_hex(color_name):
    """
    Convert color names to hex codes for display.
    Add more color mappings as needed.

    Args:
        color_name: str - name of the color

    Returns:
        str: hex color code
    """
    color_map = {
        'red': '#FF0000',
        'blue': '#0000FF',
        'green': '#008000',
        'yellow': '#FFFF00',
        'black': '#000000',
        'white': '#FFFFFF',
        'gray': '#808080',
        'grey': '#808080',
        'pink': '#FFC0CB',
        'purple': '#800080',
        'orange': '#FFA500',
        'brown': '#A52A2A',
        'navy': '#000080',
        'teal': '#008080',
        'gold': '#FFD700',
        'silver': '#C0C0C0',
        'beige': '#F5F5DC',
        'maroon': '#800000',
        'olive': '#808000',
        'lime': '#00FF00',
        'aqua': '#00FFFF',
        'fuchsia': '#FF00FF',
    }

    # Return hex code if found, otherwise return the color name as-is
    # (in case it's already a hex code)
    return color_map.get(color_name.lower(), color_name)