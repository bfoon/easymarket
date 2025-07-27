from django import template

register = template.Library()


@register.filter
def material_icon(material_name):
    """
    Get FontAwesome icon for material type
    """
    if not material_name:
        return 'circle'

    icon_mapping = {
        'leather': 'tshirt',
        'metal': 'circle',
        'fabric': 'cut',
        'plastic': 'cube',
        'wood': 'tree',
        'glass': 'wine-glass',
        'cotton': 'leaf',
        'silk': 'feather',
        'wool': 'cloud',
        'polyester': 'industry',
        'denim': 'jeans',
        'canvas': 'paint-brush',
        'rubber': 'circle',
        'ceramic': 'wine-glass',
        'stone': 'mountain'
    }
    return icon_mapping.get(material_name.lower(), 'circle')


@register.filter
def get_color_code(color_name):
    """
    Convert color name to hex code
    """
    if not color_name:
        return '#CCCCCC'

    color_mapping = {
        'black': '#000000',
        'white': '#FFFFFF',
        'brown': '#8B4513',
        'silver': '#C0C0C0',
        'gold': '#FFD700',
        'blue': '#0066CC',
        'red': '#FF0000',
        'green': '#008000',
        'gray': '#808080',
        'grey': '#808080',
        'navy': '#000080',
        'purple': '#800080',
        'pink': '#FFC0CB',
        'orange': '#FFA500',
        'yellow': '#FFFF00',
        'beige': '#F5F5DC',
        'maroon': '#800000',
        'teal': '#008080',
        'cyan': '#00FFFF',
        'magenta': '#FF00FF',
        'lime': '#00FF00',
        'olive': '#808000',
        'aqua': '#00FFFF',
        'fuchsia': '#FF00FF',
        'tan': '#D2B48C',
        'khaki': '#F0E68C'
    }
    return color_mapping.get(color_name.lower(), '#CCCCCC')