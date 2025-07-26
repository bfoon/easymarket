import colorsys
import webcolors
from PIL import Image, ImageStat
import requests
from io import BytesIO


class ColorUtils:

    @staticmethod
    def extract_dominant_color_from_image(image_url):
        """Extract dominant color from an image URL"""
        try:
            response = requests.get(image_url)
            img = Image.open(BytesIO(response.content))

            # Resize image for faster processing
            img = img.resize((50, 50))

            # Convert to RGB if necessary
            if img.mode != 'RGB':
                img = img.convert('RGB')

            # Get dominant color
            stat = ImageStat.Stat(img)
            dominant_color = tuple(map(int, stat.mean))

            return ColorUtils.rgb_to_hex(dominant_color)
        except Exception as e:
            print(f"Error extracting color from image: {e}")
            return None

    @staticmethod
    def rgb_to_hex(rgb_tuple):
        """Convert RGB tuple to hex color"""
        return '#{:02x}{:02x}{:02x}'.format(*rgb_tuple)

    @staticmethod
    def hex_to_rgb(hex_color):
        """Convert hex color to RGB tuple"""
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))

    @staticmethod
    def get_color_name(hex_color):
        """Get closest color name for a hex color"""
        try:
            return webcolors.hex_to_name(hex_color)
        except ValueError:
            # Find closest named color
            rgb = ColorUtils.hex_to_rgb(hex_color)
            min_colors = {}

            for key, name in webcolors.CSS3_HEX_TO_NAMES.items():
                r_c, g_c, b_c = ColorUtils.hex_to_rgb(key)
                rd = (r_c - rgb[0]) ** 2
                gd = (g_c - rgb[1]) ** 2
                bd = (b_c - rgb[2]) ** 2
                min_colors[(rd + gd + bd)] = name

            return min_colors[min(min_colors.keys())]

    @staticmethod
    def suggest_color_from_image(product_image):
        """Suggest a color name based on the product image"""
        if not product_image.image:
            return None

        try:
            dominant_hex = ColorUtils.extract_dominant_color_from_image(product_image.image.url)
            if dominant_hex:
                return ColorUtils.get_color_name(dominant_hex)
        except Exception as e:
            print(f"Error suggesting color: {e}")

        return None