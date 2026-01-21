# ============================================================
# QR CODE UTILITIES
# marketplace/qr_utils.py - Create this file
# ============================================================

import base64
from io import BytesIO


def generate_qr_code(data):
    """
    Generate QR code and return as base64 string.
    Handles missing qrcode library gracefully.
    """
    try:
        import qrcode
        
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(data)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        
        img_str = base64.b64encode(buffer.read()).decode()
        return f"data:image/png;base64,{img_str}"
    except ImportError:
        # qrcode library not installed
        return None
    except Exception as e:
        # Any other error
        print(f"Error generating QR code: {e}")
        return None