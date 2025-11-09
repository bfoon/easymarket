from decimal import Decimal, InvalidOperation
import uuid

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Cart, SocialCart, CartMember, CartInvite, PaymentShare, Contribution


# ---------- Helpers ----------

def _abs_uri(request, name, *args, **kwargs) -> str:
    """Build absolute URL from a named route."""
    return request.build_absolute_uri(reverse(f"marketplace:{name}", args=args, kwargs=kwargs))


@transaction.atomic
def ensure_social_cart(cart, user) -> SocialCart:
    """
    Create a SocialCart wrapper + owner membership + 100% owner share, idempotently.
    Transaction keeps owner member & share consistent under race.
    """
    social = getattr(cart, 'social', None)
    if social:
        return social

    social = SocialCart.objects.create(cart=cart, owner=user)
    owner_member, _ = CartMember.objects.get_or_create(
        social_cart=social, user=user,
        defaults={'role': 'owner', 'status': 'joined'}
    )
    PaymentShare.objects.get_or_create(
        social_cart=social, member=owner_member,
        defaults={'percentage': Decimal('100')}
    )
    social.recalc_members_due()
    return social


def _redistribute_equal(social: SocialCart):
    """
    Optional: split 100% equally among joined members.
    Use with care if you plan to preserve custom splits elsewhere.
    """
    members = social.members.filter(status='joined')
    if not members.exists():
        return
    eq = (Decimal('100') / members.count()).quantize(Decimal('0.01'))
    for m in members:
        share, _ = PaymentShare.objects.get_or_create(social_cart=social, member=m)
        share.percentage = eq
        share.fixed_amount = None
        share.items_total_amount = None
        share.save(update_fields=['percentage', 'fixed_amount', 'items_total_amount'])
    social.recalc_members_due()


def _parse_decimal(val: str | None) -> Decimal | None:
    if val in (None, ''):
        return None
    try:
        return Decimal(val)
    except (InvalidOperation, TypeError, ValueError):
        return None


# ---------- Views ----------

@login_required
@require_POST
def create_social_cart(request):
    cart, _ = Cart.objects.get_or_create(user=request.user)
    social = ensure_social_cart(cart, request.user)
    return JsonResponse({
        'success': True,
        'invite_link': _abs_uri(request, 'join_open_social_cart', invite_code=social.invite_code),
    })


@login_required
@require_POST
def send_cart_invite(request):
    cart = Cart.objects.filter(user=request.user).select_related('social').first()
    if not cart or not hasattr(cart, 'social'):
        return JsonResponse({'success': False, 'message': 'No social cart'}, status=400)

    social = cart.social
    if social.owner_id != request.user.id:
        return JsonResponse({'success': False, 'message': 'Only owner can invite'}, status=403)
    if social.status in ('locked', 'closed', 'cancelled'):
        return JsonResponse({'success': False, 'message': 'Cart is not accepting new members'}, status=409)

    email = request.POST.get('email') or None
    phone = request.POST.get('phone') or None

    inv = CartInvite.objects.create(
        social_cart=social,
        inviter=request.user,
        invited_email=email,
        invited_phone=phone,
        expires_at=timezone.now() + timezone.timedelta(days=7),
    )
    return JsonResponse({
        'success': True,
        'invite_link': _abs_uri(request, 'accept_cart_invite', code=inv.code),
    })


@login_required
def join_open_social_cart(request, invite_code):
    social = get_object_or_404(
        SocialCart,
        invite_code=invite_code, is_active=True, status__in=['open', 'checkout']
    )
    member, _ = CartMember.objects.get_or_create(
        social_cart=social, user=request.user,
        defaults={'role': 'editor', 'status': 'joined'}
    )
    PaymentShare.objects.get_or_create(social_cart=social, member=member)
    _redistribute_equal(social)  # remove if you don’t want auto-redistribute
    social.recalc_members_due()
    return redirect('marketplace:cart_view')


@login_required
def accept_cart_invite(request, code):
    inv = get_object_or_404(CartInvite, code=code)
    if not inv.is_valid():
        return JsonResponse({'success': False, 'message': 'Invite expired'}, status=400)

    social = inv.social_cart
    if social.status in ('locked', 'closed', 'cancelled'):
        return JsonResponse({'success': False, 'message': 'Cart not accepting new members'}, status=409)

    member, _ = CartMember.objects.get_or_create(
        social_cart=social, user=request.user,
        defaults={'role': 'editor', 'status': 'joined'}
    )
    inv.accepted_by = request.user
    inv.status = 'accepted'
    inv.save(update_fields=['accepted_by', 'status'])

    PaymentShare.objects.get_or_create(social_cart=social, member=member)
    _redistribute_equal(social)  # remove if you don’t want auto-redistribute
    social.recalc_members_due()
    return redirect('marketplace:cart_view')


@login_required
@require_POST
def set_share(request):
    social_id = request.POST.get('social_id')
    percentage_raw = request.POST.get('percentage')     # "25" -> 25%
    fixed_raw = request.POST.get('fixed_amount')        # "500.00"
    member_id = request.POST.get('member_id')           # owner can edit others

    social = get_object_or_404(SocialCart, id=social_id, is_active=True)
    me = get_object_or_404(CartMember, social_cart=social, user=request.user, status='joined')

    target = me
    if me.role == 'owner' and member_id:
        target = get_object_or_404(CartMember, id=member_id, social_cart=social)

    share, _ = PaymentShare.objects.get_or_create(social_cart=social, member=target)

    percentage = _parse_decimal(percentage_raw)
    fixed = _parse_decimal(fixed_raw)

    # Validate and assign
    if percentage is not None:
        if percentage < 0 or percentage > 100:
            return JsonResponse({'success': False, 'message': 'percentage must be between 0 and 100'}, status=400)
        share.percentage = percentage.quantize(Decimal('0.01'))
    if fixed is not None:
        if fixed < 0:
            return JsonResponse({'success': False, 'message': 'fixed_amount must be >= 0'}, status=400)
        share.fixed_amount = fixed.quantize(Decimal('0.01'))

    share.save(update_fields=['percentage', 'fixed_amount'])
    social.recalc_members_due()
    return JsonResponse({'success': True})


@login_required
@require_POST
def start_my_payment(request):
    social_id = request.POST.get('social_id')
    provider = (request.POST.get('provider') or '').lower()  # wave/qmoney/afrimoney/gamswitch/cash

    if provider not in {'wave', 'qmoney', 'afrimoney', 'gamswitch', 'cash'}:
        return JsonResponse({'success': False, 'message': 'Unsupported provider'}, status=400)

    social = get_object_or_404(SocialCart, id=social_id, is_active=True)
    if social.status in ('locked', 'closed', 'cancelled'):
        return JsonResponse({'success': False, 'message': 'Cart not payable'}, status=409)

    member = get_object_or_404(CartMember, social_cart=social, user=request.user, status='joined')
    share = get_object_or_404(PaymentShare, social_cart=social, member=member, is_active=True)

    # Enter checkout mode
    if social.status == 'open':
        social.status = 'checkout'
        social.save(update_fields=['status'])

    social.recalc_members_due()

    already = Contribution.objects.filter(
        social_cart=social, member=member, status='success'
    ).aggregate(s=Sum('amount'))['s'] or Decimal('0')
    due = (share.amount_due or Decimal('0'))
    remaining = (due - already).quantize(Decimal('0.01'))
    if remaining <= 0:
        return JsonResponse({'success': False, 'message': 'Nothing left to pay'})

    c = Contribution.objects.create(
        social_cart=social,
        member=member,
        provider=provider,
        amount=remaining,
        status='init'
    )

    # TODO: initiate the provider payment here and set real reference
    c.status = 'pending'
    c.provider_ref = f"{provider.upper()}-{uuid.uuid4()}"
    c.save(update_fields=['status', 'provider_ref'])

    return JsonResponse({'success': True, 'payment_ref': c.provider_ref})


def _not_mutable(social: SocialCart) -> bool:
    """True if cart is not allowed to change membership."""
    return social.status in ('locked', 'closed', 'cancelled')


@login_required
@require_POST
def leave_cart(request):
    """
    Current user leaves a social cart.
    - If owner: transfer ownership to earliest joined member (if any). If none, cancel the cart.
    - Deactivate the member's share and mark status='left'.
    """
    social_id = request.POST.get('social_id')
    social = get_object_or_404(SocialCart, id=social_id, is_active=True)

    if _not_mutable(social):
        return JsonResponse({'success': False, 'message': 'Cart membership cannot be changed now.'}, status=409)

    member = get_object_or_404(CartMember, social_cart=social, user=request.user)

    # Deactivate share (keep history)
    PaymentShare.objects.filter(social_cart=social, member=member).update(is_active=False)

    # Mark member left
    if member.status != 'left':
        member.status = 'left'
        member.save(update_fields=['status'])

    # If owner left, transfer or cancel
    new_owner_id = None
    if member.role == 'owner':
        replacement = social.members.filter(status='joined').exclude(id=member.id).order_by('joined_at').first()
        if replacement:
            replacement.role = 'owner'
            replacement.save(update_fields=['role'])
            new_owner_id = replacement.user_id
            social.owner_id = replacement.user_id
            social.save(update_fields=['owner'])
        else:
            # No members left → cancel collaborative layer
            social.status = 'cancelled'
            social.is_active = False
            social.save(update_fields=['status', 'is_active'])
            return JsonResponse({
                'success': True,
                'message': 'You left the cart. No members remain, so the social cart was cancelled.',
                'new_owner_id': None,
                'social_status': social.status,
            })

    # Optional: redistribute equally among remaining active members
    _redistribute_equal(social)
    social.recalc_members_due()

    return JsonResponse({
        'success': True,
        'message': 'You left the cart.',
        'new_owner_id': new_owner_id,
        'social_status': social.status,
    })


@login_required
@require_POST
def remove_member(request, member_id):
    member = get_object_or_404(
        CartMember.objects.select_related('social_cart', 'user', 'social_cart__owner'),
        pk=member_id
    )

    social = member.social_cart

    # Must be owner
    if social.owner_id != request.user.id:
        return JsonResponse({'success': False, 'message': 'Only the owner can remove members.'}, status=403)

    # Don’t allow removing the owner
    if member.user_id == social.owner_id:
        return JsonResponse({'success': False, 'message': 'Owner cannot be removed.'}, status=400)

    # Optional: ensure the member is currently joined
    if member.status != 'joined':
        return JsonResponse({'success': False, 'message': 'Member is not active.'}, status=400)

    member.delete()
    return JsonResponse({'success': True})