import secrets
from django.utils import timezone

def _generate_b2b_tracking_number(prefix="EM-B2B"):
    """
    Example: EM-B2B-20251212-A1B2C3D4
    """
    date_part = timezone.now().strftime("%Y%m%d")
    rand_part = secrets.token_hex(4).upper()  # 8 chars
    return f"{prefix}-{date_part}-{rand_part}"
