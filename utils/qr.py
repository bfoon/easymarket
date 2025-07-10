import qrcode
import io
import base64
from decimal import Decimal


def generate_invoice_qr_code(order):
    """Generate QR code for invoice with proper decimal handling"""

    # Debug: Check what attributes your order has
    print(f"Order attributes: {dir(order)}")

    # Try different ways to get the total
    try:
        # Option 1: Property
        total = order.get_total
        print(f"get_total (property): {total}")
    except AttributeError:
        try:
            # Option 2: Method
            total = order.get_total()
            print(f"get_total (method): {total}")
        except (AttributeError, TypeError):
            try:
                # Option 3: Direct field
                total = order.total
                print(f"total (field): {total}")
            except AttributeError:
                # Option 4: Calculate manually
                total = order.get_subtotal + order.get_tax_amount
                if hasattr(order, 'shipping_cost') and order.shipping_cost:
                    total += order.shipping_cost
                if hasattr(order, 'discount_amount') and order.discount_amount:
                    total -= order.discount_amount
                print(f"calculated total: {total}")

    # Ensure total is a Decimal and format properly
    if isinstance(total, Decimal):
        total_str = f"{total:.2f}"
    else:
        total_str = f"{float(total):.2f}"

    # Create QR code data
    qr_data = f"Invoice: INV-{order.id:05d}\nOrder: {order.id}\nTotal: D{total_str}"

    # Alternative: Just include basic info without total
    # qr_data = f"Invoice: INV-{order.id:05d}\nOrder: #{order.id}"

    print(f"QR Data: {qr_data}")

    # Generate QR code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_data)
    qr.make(fit=True)

    # Create QR code image
    img = qr.make_image(fill_color="black", back_color="white")

    # Convert to base64 for embedding in HTML
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    img_str = base64.b64encode(buffer.getvalue()).decode()

    return f"data:image/png;base64,{img_str}"


# Simple version without total if still having issues:
def generate_simple_invoice_qr_code(order):
    """Generate QR code with just basic invoice info"""

    # Simple QR code data without total
    qr_data = f"Invoice: INV-{order.id:05d}\nOrder: #{order.id}\nDate: {order.created_at.strftime('%Y-%m-%d')}"

    # Generate QR code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_data)
    qr.make(fit=True)

    # Create QR code image
    img = qr.make_image(fill_color="black", back_color="white")

    # Convert to base64
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    img_str = base64.b64encode(buffer.getvalue()).decode()

    return f"data:image/png;base64,{img_str}"