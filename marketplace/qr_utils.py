"""
QR Code Generation Utilities for Cart Sharing
Provides functions to generate QR codes for cart sharing URLs
"""

import qrcode
from qrcode.image.svg import SvgPathImage
from io import BytesIO
import base64
from django.conf import settings


def generate_qr_code(url, format='png', size=10, border=2):
    """
    Generate QR code for a given URL.
    
    Args:
        url (str): URL to encode in QR code
        format (str): Output format - 'png', 'svg', or 'base64'
        size (int): Size of QR code (1-40, default 10)
        border (int): Border size in boxes (default 2)
    
    Returns:
        bytes or str: QR code image data or base64 string
    
    Example:
        >>> qr_base64 = generate_qr_code('https://example.com/cart/share/abc123', 'base64')
        >>> # Use in template: <img src="data:image/png;base64,{{ qr_base64 }}">
    """
    # Create QR code instance
    qr = qrcode.QRCode(
        version=1,  # Auto-adjust version
        error_correction=qrcode.constants.ERROR_CORRECT_H,  # High error correction
        box_size=size,
        border=border,
    )
    
    # Add data
    qr.add_data(url)
    qr.make(fit=True)
    
    if format == 'svg':
        # Generate SVG
        img = qr.make_image(image_factory=SvgPathImage)
        buffer = BytesIO()
        img.save(buffer)
        return buffer.getvalue().decode('utf-8')
    
    elif format == 'base64':
        # Generate PNG and encode as base64
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        img_str = base64.b64encode(buffer.getvalue()).decode()
        return img_str
    
    else:  # format == 'png'
        # Generate PNG
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        return buffer.getvalue()


def generate_styled_qr_code(url, logo_path=None, fill_color="black", back_color="white"):
    """
    Generate a styled QR code with optional logo.
    
    Args:
        url (str): URL to encode
        logo_path (str): Path to logo image to embed (optional)
        fill_color (str): QR code color (default: black)
        back_color (str): Background color (default: white)
    
    Returns:
        str: Base64 encoded PNG image
    
    Example:
        >>> logo = os.path.join(settings.STATIC_ROOT, 'images/logo.png')
        >>> qr = generate_styled_qr_code('https://example.com', logo_path=logo)
    """
    from PIL import Image
    
    # Create QR code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=2,
    )
    
    qr.add_data(url)
    qr.make(fit=True)
    
    # Create image
    img = qr.make_image(fill_color=fill_color, back_color=back_color).convert('RGB')
    
    # Add logo if provided
    if logo_path:
        try:
            logo = Image.open(logo_path)
            
            # Calculate logo size (should be about 1/5 of QR code)
            qr_width, qr_height = img.size
            logo_size = qr_width // 5
            
            # Resize logo
            logo = logo.resize((logo_size, logo_size), Image.Resampling.LANCZOS)
            
            # Calculate position (center)
            logo_pos = ((qr_width - logo_size) // 2, (qr_height - logo_size) // 2)
            
            # Paste logo
            img.paste(logo, logo_pos)
        except Exception as e:
            # If logo fails, continue without it
            print(f"Could not add logo: {e}")
    
    # Convert to base64
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    img_str = base64.b64encode(buffer.getvalue()).decode()
    
    return img_str


def generate_branded_qr_code(url, brand_color="#FF6B35"):
    """
    Generate a branded QR code with custom colors.
    
    Args:
        url (str): URL to encode
        brand_color (str): Hex color for QR code (default: EasyMarket orange)
    
    Returns:
        str: Base64 encoded PNG image
    """
    return generate_styled_qr_code(url, fill_color=brand_color, back_color="white")


def generate_qr_with_text(url, text, format='base64'):
    """
    Generate QR code with text below it.
    
    Args:
        url (str): URL to encode
        text (str): Text to display below QR code
        format (str): Output format ('base64' or 'png')
    
    Returns:
        str or bytes: QR code image with text
    """
    from PIL import Image, ImageDraw, ImageFont
    
    # Generate QR code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=2,
    )
    
    qr.add_data(url)
    qr.make(fit=True)
    
    qr_img = qr.make_image(fill_color="black", back_color="white").convert('RGB')
    
    # Create new image with extra space for text
    qr_width, qr_height = qr_img.size
    text_height = 50
    new_height = qr_height + text_height
    
    # Create new image
    img = Image.new('RGB', (qr_width, new_height), 'white')
    
    # Paste QR code
    img.paste(qr_img, (0, 0))
    
    # Add text
    draw = ImageDraw.Draw(img)
    
    try:
        # Try to use a nice font
        font = ImageFont.truetype("arial.ttf", 20)
    except:
        # Fallback to default font
        font = ImageFont.load_default()
    
    # Calculate text position (centered)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_x = (qr_width - text_width) // 2
    text_y = qr_height + 10
    
    # Draw text
    draw.text((text_x, text_y), text, fill="black", font=font)
    
    # Convert to output format
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    
    if format == 'base64':
        return base64.b64encode(buffer.getvalue()).decode()
    else:
        return buffer.getvalue()


# Convenience functions for cart sharing

def generate_cart_share_qr(share_url, format='base64'):
    """
    Generate QR code specifically for cart sharing.
    
    Args:
        share_url (str): Full cart share URL
        format (str): Output format
    
    Returns:
        str: Base64 encoded QR code
    """
    return generate_qr_code(share_url, format=format, size=10, border=2)


def generate_social_cart_qr(invite_url, format='base64'):
    """
    Generate QR code for social cart invitations.
    
    Args:
        invite_url (str): Social cart invite URL
        format (str): Output format
    
    Returns:
        str: Base64 encoded QR code
    """
    return generate_branded_qr_code(invite_url)
