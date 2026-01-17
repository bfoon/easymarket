from django.conf import settings
from django.db.models import Q, Sum, F
from django.urls import reverse
from decimal import Decimal
from io import BytesIO
from django.db.models import Prefetch
import uuid

from .models import Cart, CartItem, Product, SearchHistory, PopularSearch, ProductImage

from .models import SocialCart, CartMember, PaymentShare

import webcolors
from PIL import Image, ImageStat
import requests

# --- Utils ---------------------------------------------------------

def get_client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    return xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR')

def log_search(request, query, results_count):
    q = (query or '').strip()
    if not q:
        return

    SearchHistory.objects.create(
        user=request.user if request.user.is_authenticated else None,
        query=q,
        results_count=results_count,
        ip_address=get_client_ip(request)
    )

    popular, created = PopularSearch.objects.get_or_create(
        query=q,
        defaults={'search_count': 1}
    )
    if not created:
        popular.search_count = F('search_count') + 1
        popular.save(update_fields=['search_count'])

def get_search_suggestions_with_history(request, query):
    suggestions = []
    q = (query or '').strip()
    if not q:
        return suggestions

    # Product suggestions
    products = (
        Product.objects.filter(
            Q(name__icontains=q) |
            Q(description__icontains=q) |
            Q(category__name__icontains=q)
        )
        .select_related('category')[:5]
    )

    for p in products:
        suggestions.append({
            'type': 'product',
            'id': p.id,
            'name': p.name,
            'price': str(p.price),
            'category': p.category.name if p.category else '',
            'image': (getattr(p.image, 'url', None) if getattr(p, 'image', None) else None),
            # your URL pattern is product/<int:product_id>/
            'url': reverse('marketplace:product_detail', kwargs={'product_id': p.pk})
        })

    # Recent searches (user)
    if request.user.is_authenticated:
        recent = (SearchHistory.objects
                  .filter(user=request.user, query__icontains=q)
                  .values_list('query', flat=True)
                  .distinct()[:3])
        for s in recent:
            suggestions.append({
                'type': 'recent',
                'query': s,
                'url': reverse('marketplace:search_products') + f'?q={s}'
            })

    # Popular searches
    popular = (PopularSearch.objects
               .filter(query__icontains=q)
               .values_list('query', flat=True)[:3])
    for s in popular:
        suggestions.append({
            'type': 'popular',
            'query': s,
            'url': reverse('marketplace:search_products') + f'?q={s}'
        })

    return suggestions[:10]

def migrate_session_cart_to_user(request, user):
    session_cart = request.session.get('cart', {})
    if not session_cart:
        return

    cart, _ = Cart.objects.get_or_create(user=user)

    for key, item in session_cart.items():
        try:
            product_id = int(key.split('::', 1)[0])
            product = Product.objects.get(id=product_id, is_active=True)
        except (ValueError, Product.DoesNotExist):
            continue

        quantity = int(item.get('quantity', 1)) or 1
        # SESSION uses 'features' (your add_to_cart stores 'features': selected_features)
        selected_features = item.get('features') or item.get('selected_features') or {}

        existing = CartItem.objects.filter(
            cart=cart, product=product, selected_features=selected_features
        ).first()
        if existing:
            existing.quantity = min(existing.quantity + quantity, 99)
            existing.save(update_fields=['quantity'])
        else:
            CartItem.objects.create(
                cart=cart, product=product, quantity=min(quantity, 99),
                selected_features=selected_features
            )

    request.session['cart'] = {}
    request.session.modified = True

# --- Color utils ---------------------------------------------------

class ColorUtils:
    @staticmethod
    def extract_dominant_color_from_image(image_url):
        try:
            resp = requests.get(image_url, timeout=5)
            resp.raise_for_status()
            img = Image.open(BytesIO(resp.content))
            img = img.resize((50, 50))
            if img.mode != 'RGB':
                img = img.convert('RGB')
            stat = ImageStat.Stat(img)
            dominant = tuple(map(int, stat.mean))
            return ColorUtils.rgb_to_hex(dominant)
        except Exception:
            return None

    @staticmethod
    def rgb_to_hex(rgb_tuple):
        return '#{:02x}{:02x}{:02x}'.format(*rgb_tuple)

    @staticmethod
    def hex_to_rgb(hex_color):
        h = (hex_color or '').lstrip('#')
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

    @staticmethod
    def get_color_name(hex_color):
        try:
            return webcolors.hex_to_name(hex_color)
        except Exception:
            rgb = ColorUtils.hex_to_rgb(hex_color)
            min_colors = {}
            for key, name in webcolors.CSS3_HEX_TO_NAMES.items():
                r_c, g_c, b_c = ColorUtils.hex_to_rgb(key)
                rd = (r_c - rgb[0]) ** 2
                gd = (g_c - rgb[1]) ** 2
                bd = (b_c - rgb[2]) ** 2
                min_colors[rd + gd + bd] = name
            return min(min_colors, key=min_colors.get) and min_colors[min(min_colors.keys())]

    @staticmethod
    def suggest_color_from_image(product_image):
        if not getattr(product_image, 'image', None):
            return None
        dominant_hex = ColorUtils.extract_dominant_color_from_image(product_image.image.url)
        return ColorUtils.get_color_name(dominant_hex) if dominant_hex else None

# --- Cart context (social-aware) -----------------------------------
CART_TAX_RATE = getattr(settings, "CART_TAX_RATE", Decimal("0.00"))
def _coerce_int(v, default=1):
    try:
        return int(v)
    except Exception:
        return default

def _ensure_owner_membership(social: SocialCart):
    """
    Make sure the SocialCart owner is represented in CartMember with role='owner' and status='joined'.
    This lets templates reliably show the owner even if members were created later.
    """
    if not social or not social.owner_id:
        return

    owner_member, created = CartMember.objects.get_or_create(
        social_cart=social,
        user_id=social.owner_id,
        defaults={"role": "owner", "status": "joined"},
    )
    # normalize any drift
    updates = {}
    if owner_member.role != "owner":
        updates["role"] = "owner"
    if owner_member.status != "joined":
        updates["status"] = "joined"
    if updates:
        for k, v in updates.items():
            setattr(owner_member, k, v)
        owner_member.save(update_fields=list(updates.keys()))

def _resolve_active_social_for(user):
    """
    Return the active SocialCart for a given user, if any.
    """
    social = (
        SocialCart.objects.filter(
            is_active=True,
            status__in=["open", "checkout"],
            members__user=user,
            members__status="joined",
        )
        .select_related("cart")
        .order_by("-created_at")
        .first()
    )
    if social:
        _ensure_owner_membership(social)
    return social

def _resolve_active_cart_for_user(user):
    """
    Return (cart, social) for an authenticated user.
    Prefer the active SocialCart's cart if present; else personal cart.
    """
    social = _resolve_active_social_for(user)
    if social and social.cart_id:
        return social.cart, social
    # fallback: personal cart
    cart, _ = Cart.objects.get_or_create(user=user)
    return cart, None

# -----------------------------
# Cart context builder (used by templates)
# -----------------------------
def build_cart_context(request, limit=None):
    cart_items = []
    total_price = Decimal("0.00")
    tax_rate = CART_TAX_RATE

    total_items_count = 0
    cart_count = 0

    social = None
    is_owner = False
    social_members = []
    social_shares = []
    my_share = None

    if request.user.is_authenticated:
        # Prefer social cart if present
        social = _resolve_active_social_for(request.user)
        cart = social.cart if social else Cart.objects.filter(user=request.user).first()

        if social:
            me_member = (
                CartMember.objects.filter(
                    social_cart=social, user=request.user, status="joined"
                )
                .select_related("user")
                .first()
            )
            # authoritative owner: social.owner_id
            is_owner = bool(me_member and social.owner_id == request.user.id)

            social_members = list(
                social.members.select_related("user")
                .filter(status="joined")
                .order_by("joined_at")
            )
            social_shares = list(
                PaymentShare.objects.filter(social_cart=social, is_active=True)
                .select_related("member", "member__user")
            )
            if me_member:
                my_share = next(
                    (ps for ps in social_shares if ps.member_id == me_member.id), None
                )

        if cart:
            base_qs = (
                CartItem.objects.filter(cart=cart)
                .select_related("product", "added_by")
                .order_by("-id")
            )
            total_items_count = base_qs.count()
            cart_count = base_qs.aggregate(s=Sum("quantity"))["s"] or 0

            items_qs = base_qs[:limit] if limit else base_qs
            for it in items_qs:
                if not it.product:
                    continue
                line_total = it.product.price * it.quantity

                # permission: owner can remove any; member only if they added it
                can_remove = bool(
                    (social and (is_owner or it.added_by_id == request.user.id))
                    or (not social and it.cart and it.cart.user_id == request.user.id)
                )

                cart_items.append(
                    {
                        "id": it.id,
                        "product": it.product,
                        "quantity": it.quantity,
                        "subtotal": line_total,
                        "selected_features": getattr(it, "selected_features", {}) or {},
                        "item_type": "db",
                        "remove_id": str(it.id),
                        "added_by_id": it.added_by_id,
                        "can_remove": can_remove,
                    }
                )
                total_price += line_total

    else:
        # guests (session cart)
        session_cart = request.session.get("cart", {})
        tmp = []
        keymap = {}
        full_qty = 0

        for key, val in session_cart.items():
            try:
                pid = int(key.split("::", 1)[0])
                keymap.setdefault(pid, []).append(key)
                full_qty += int(val.get("quantity", 1)) or 1
            except Exception:
                continue

        products = {
            p.id: p
            for p in Product.objects.filter(id__in=keymap.keys(), is_active=True)
        }

        for pid, keys in keymap.items():
            p = products.get(pid)
            if not p:
                continue
            for key in keys:
                data = session_cart.get(key, {})
                q = int(data.get("quantity", 1)) or 1
                feats = data.get("selected_features") or data.get("features") or {}
                line = p.price * q
                tmp.append(
                    {
                        "id": pid,
                        "product": p,
                        "quantity": q,
                        "subtotal": line,
                        "selected_features": feats,
                        "item_type": "session",
                        "remove_id": key,
                        "added_by_id": None,
                        "can_remove": True,
                    }
                )

        total_items_count = len(tmp)
        cart_count = full_qty
        items_iter = tmp[:limit] if limit else tmp
        for row in items_iter:
            cart_items.append(row)
            total_price += row["subtotal"]

    tax_amount = total_price * tax_rate
    final_total = total_price + tax_amount
    has_more = total_items_count > len(cart_items)
    remaining = max(total_items_count - len(cart_items), 0)

    return {
        "cart_items": cart_items,
        "total_price": total_price,
        "tax_amount": tax_amount,
        "final_total": final_total,
        "cart_count": cart_count,
        "has_more": has_more,
        "remaining": remaining,
        "total_items_count": total_items_count,
        "social": social if request.user.is_authenticated else None,
        "is_owner": is_owner,
        "social_members": social_members,
        "social_shares": social_shares,
        "my_share": my_share,
    }

def with_display_images(qs):
    return qs.select_related("category", "store").prefetch_related(
        Prefetch(
            "images",
            queryset=ProductImage.objects.only("id", "product_id", "image", "is_primary", "created_at")
                                .order_by("-is_primary", "created_at")
        )
    )


def format_price_for_user(amount, user=None):
    """
    Reusable function that mimics display_money template tag
    Use this anywhere you need to format prices in views

    Args:
        amount: Price amount (Decimal or float)
        user: User object (optional, for guest users)

    Returns:
        Formatted price string (e.g., "D99.99" or "$1.50")
    """
    from accounts.models import Currency
    from accounts.currency_utils import convert_currency, format_price, get_user_currency_preference
    from decimal import Decimal

    if amount is None:
        return ""

    # Ensure Decimal
    try:
        amount = Decimal(str(amount))
    except:
        return str(amount)

    # Get base currency
    base_currency = Currency.objects.filter(is_base_currency=True, is_active=True).first()
    if not base_currency:
        base_currency = Currency.objects.filter(code='GMD').first()
    base_code = base_currency.code if base_currency else 'GMD'

    # Guest user or no preference
    if not user or not user.is_authenticated:
        return format_price(amount, currency_code=base_code)

    # Get user's preference
    preferred = get_user_currency_preference(user)
    if not preferred:
        return format_price(amount, currency_code=base_code)

    # Same currency - no conversion needed
    if preferred.code == base_code:
        return format_price(amount, currency_code=base_code)

    # Convert to user's currency
    result = convert_currency(amount, base_code, preferred.code)
    if result.get("success"):
        return format_price(result["converted_amount"], currency_code=preferred.code)

    # Fallback to base currency
    return format_price(amount, currency_code=base_code)

def sync_social_items_totals(social):
    """
    Recompute each active member's items_total_amount as the sum of cart
    items they personally added (price * qty). Then recalc amount_due.
    """
    if not social or not social.is_active:
        return

    cart = social.cart
    if not cart:
        return

    # Map user_id -> total they added
    per_user_totals = (
        CartItem.objects
        .filter(cart=cart, added_by__isnull=False)
        .values('added_by_id')
        .annotate(total=Sum(models.F('product__price') * models.F('quantity')))
    )
    totals_map = {row['added_by_id']: row['total'] or Decimal('0') for row in per_user_totals}

    # Update shares for active members
    shares = PaymentShare.objects.filter(social_cart=social, is_active=True).select_related('member__user')
    for share in shares:
        user_id = share.member.user_id
        share.items_total_amount = totals_map.get(user_id, Decimal('0')) or Decimal('0')
        share.save(update_fields=['items_total_amount'])

    # Final due math
    social.recalc_members_due()

