
from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """Get item from dictionary in template"""
    if dictionary is None:
        return None
    return dictionary.get(key)

@register.filter
def get_color_images_count(color_images_dict, color):
    """Get count of images for a specific color"""
    if color_images_dict is None:
        return 0
    images = color_images_dict.get(color, [])
    return len(images)

@register.filter
def has_color_images(color_images_dict, color):
    """Check if a color has images"""
    if color_images_dict is None:
        return False
    return color in color_images_dict and len(color_images_dict[color]) > 0