from decimal import Decimal, InvalidOperation
import uuid
import json

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.contrib import messages
from .social_cart_email import send_email_async
from django.views.decorators.http import require_POST, require_GET

from .models import (
    Cart, CartItem,
    SocialCart, CartMember, CartInvite, PaymentShare, Contribution
)

from orders.models import Order, OrderItem


# ---------- Helpers ----------

def _abs_uri(request, name, *args, **kwargs) -> str:
    return request.build_absolute_uri(reverse(f"marketplace:{name}", args=args, kwargs=kwargs))


def _parse_decimal(val: str | None) -> Decimal | None:
    if val in (None, ""):
        return None
    try:
        return Decimal(str(val))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _json_error(message: str, status: int = 400, **extra):
    payload = {"success": False, "message": message}
    payload.update(extra)
    return JsonResponse(payload, status=status)


# Helper function to ensure backward compatibility
@transaction.atomic
def ensure_social_cart(cart, user) -> SocialCart:
    """
    Idempotently ensure a SocialCart exists for this Cart
    """
    social = getattr(cart, "social", None)
    if social and social.is_active and social.status in ("open", "checkout"):
        return social

    if social and not social.is_active:
        # Revive inactive social cart
        social.is_active = True
        social.status = "open"
        social.save(update_fields=["is_active", "status", "updated_at"])
        return social

    # Create new social cart
    social = SocialCart.objects.create(cart=cart, owner=user)

    owner_member, _ = CartMember.objects.get_or_create(
        social_cart=social,
        user=user,
        defaults={"role": "owner", "status": "joined"}
    )

    PaymentShare.objects.get_or_create(
        social_cart=social,
        member=owner_member,
        defaults={"percentage": Decimal("100"), "is_active": True}
    )

    social.recalc_members_due()
    return social


def _resolve_active_social_for(user):
    return (
        SocialCart.objects
        .filter(
            is_active=True,
            status__in=["open", "checkout"],
            members__user=user,
            members__status="joined"
        )
        .select_related("cart", "owner")
        .order_by("-created_at")
        .first()
    )


def _not_mutable(social: SocialCart) -> bool:
    return social.status in ("locked", "closed", "cancelled")


# ---------- Core endpoints ----------

@login_required
@require_POST
def create_social_cart(request):
    """
    Create a new social cart for the user.
    """
    from marketplace.models import Cart

    cart, _ = Cart.objects.get_or_create(user=request.user)

    # Check if already has active social cart
    existing_social = getattr(cart, 'social', None)
    if existing_social and existing_social.is_active:
        return JsonResponse({
            'success': False,
            'message': 'You already have an active social cart'
        }, status=400)

    # Create social cart
    with transaction.atomic():
        social = SocialCart.objects.create(
            cart=cart,
            owner=request.user,
            is_active=True,
            status='open',
            split_mode='by_items'
        )

        # Create owner membership
        member = CartMember.objects.create(
            social_cart=social,
            user=request.user,
            role='owner',
            status='joined'
        )

        # Create owner's payment share
        PaymentShare.objects.create(
            social_cart=social,
            member=member,
            percentage=100,
            is_active=True
        )

    # Generate invite link
    from django.urls import reverse
    invite_link = request.build_absolute_uri(
        reverse('marketplace:join_open_social_cart', kwargs={'invite_code': social.invite_code})
    )

    return JsonResponse({
        'success': True,
        'message': 'Social cart created successfully!',
        'social_id': social.id,
        'invite_code': social.invite_code,
        'invite_link': invite_link
    })

@login_required
@require_GET
def social_cart_status(request):
    """
    Authoritative status endpoint for JS.
    """
    social = _resolve_active_social_for(request.user)
    if not social:
        return JsonResponse({"success": True, "social_id": None})

    me = social.members.filter(user=request.user, status="joined").first()
    is_owner = bool(me and me.role == "owner") or (social.owner_id == request.user.id)

    invite_link = _abs_uri(request, "join_open_social_cart", invite_code=social.invite_code)

    return JsonResponse({
        "success": True,
        "social_id": social.id,
        "status": social.status,
        "split_mode": getattr(social, "split_mode", "by_items"),
        "single_payer_id": getattr(social, "single_payer_id", None),
        "invite_link": invite_link,
        "is_owner": is_owner,
    })


@login_required
@require_POST
def send_cart_invite(request):
    """
    Send an invite to join social cart via email/phone.
    """
    from marketplace.models import Cart
    from django.utils import timezone

    cart = get_object_or_404(Cart, user=request.user)
    social = getattr(cart, 'social', None)

    if not social or not social.is_active:
        return JsonResponse({
            'success': False,
            'message': 'No active social cart found'
        }, status=404)

    # Verify owner
    if social.owner != request.user:
        return JsonResponse({
            'success': False,
            'message': 'Only the owner can send invites'
        }, status=403)

    email = request.POST.get('email', '').strip()
    phone = request.POST.get('phone', '').strip()

    if not email and not phone:
        return JsonResponse({
            'success': False,
            'message': 'Please provide an email or phone number'
        }, status=400)

    # Create invite
    invite = CartInvite.objects.create(
        social_cart=social,
        inviter=request.user,
        invited_email=email or None,
        invited_phone=phone or None,
        expires_at=timezone.now() + timezone.timedelta(days=7)
    )

    # Generate invite link
    from django.urls import reverse
    invite_link = request.build_absolute_uri(
        reverse('marketplace:accept_cart_invite', kwargs={'code': invite.code})
    )

    # Send email if provided
    if email:
        try:
            from marketplace.notifications import send_email

            subject = f"Join {request.user.username}'s Social Cart"
            message = f"""
            Hi!

            {request.user.username} has invited you to join their social cart on EasyMarket.

            Click here to join: {invite_link}

            Happy shopping!
            """

            send_email(
                to_email=email,
                subject=subject,
                message=message
            )
        except Exception as e:
            # Log error but don't fail
            import logging
            logging.error(f"Error sending invite email: {e}")

    return JsonResponse({
        'success': True,
        'message': 'Invite sent successfully!',
        'invite_link': invite_link
    })

@login_required
def join_open_social_cart(request, invite_code):
    """
    Join a social cart using invite code.

    GET: Show invite page with social cart details
    POST: Actually join the social cart
    """
    social = get_object_or_404(SocialCart, invite_code=invite_code, is_active=True)

    # Check if cart is accepting members
    if social.status not in ['open', 'checkout']:
        if request.method == 'POST':
            return JsonResponse({
                'success': False,
                'message': 'This social cart is no longer accepting new members'
            }, status=400)
        else:
            messages.error(request, 'This social cart is no longer accepting new members.')
            return redirect('marketplace:cart')

    # Check if already a member
    existing_member = None
    if request.user.is_authenticated:
        existing_member = social.members.filter(user=request.user).first()

    # GET request - show invite page
    if request.method == 'GET':
        # Get social cart details
        cart_items = social.cart.items.filter(cart_type='social').select_related('product', 'added_by')

        # Calculate totals
        from decimal import Decimal
        CART_TAX_RATE = Decimal("0.085")
        subtotal = sum(item.product.price * item.quantity for item in cart_items)
        tax = subtotal * CART_TAX_RATE
        total = subtotal + tax

        # Get members
        members = social.members.filter(status__in=['joined', 'blocked']).select_related('user')

        context = {
            'social': social,
            'cart_items': cart_items,
            'members': members,
            'member_count': members.count(),
            'subtotal': subtotal,
            'tax': tax,
            'total': total,
            'existing_member': existing_member,
            'is_already_joined': existing_member and existing_member.status == 'joined',
            'is_blocked': existing_member and existing_member.status == 'blocked',
            'can_rejoin': existing_member and existing_member.status == 'left',
        }

        return render(request, 'marketplace/social_cart_invite.html', context)

    # POST request - join the cart
    elif request.method == 'POST':
        if existing_member:
            if existing_member.status == 'joined':
                return JsonResponse({
                    'success': False,
                    'message': 'You are already a member of this social cart'
                }, status=400)
            elif existing_member.status == 'blocked':
                return JsonResponse({
                    'success': False,
                    'message': 'You have been blocked from this social cart'
                }, status=403)
            elif existing_member.status == 'left':
                # Rejoin
                existing_member.status = 'joined'
                existing_member.save(update_fields=['status'])

                messages.success(request, 'You have rejoined the social cart!')
                return redirect('marketplace:cart')
        else:
            # Create new membership
            with transaction.atomic():
                member = CartMember.objects.create(
                    social_cart=social,
                    user=request.user,
                    role='editor',
                    status='joined'
                )

                # Create default payment share (for by_items mode)
                PaymentShare.objects.create(
                    social_cart=social,
                    member=member,
                    is_active=True
                )

        messages.success(request, f'You have joined {social.owner.username}\'s social cart!')
        return redirect('marketplace:cart')


@login_required
def accept_cart_invite(request, code):
    """
    Accept a cart invite sent via email.

    GET: Show invite details page
    POST: Accept the invite
    """
    inv = CartInvite.objects.filter(code=code).select_related("social_cart").first()

    if not inv:
        messages.error(request, "Invite not found.")
        return redirect('marketplace:cart')

    if not inv.is_valid():
        messages.error(request, "This invite has expired.")
        return redirect('marketplace:cart')

    social = inv.social_cart

    # GET request - show invite page
    if request.method == 'GET':
        # Get social cart details
        cart_items = social.cart.items.filter(cart_type='social').select_related('product', 'added_by')

        # Calculate totals
        from decimal import Decimal
        CART_TAX_RATE = Decimal("0.085")
        subtotal = sum(item.product.price * item.quantity for item in cart_items)
        tax = subtotal * CART_TAX_RATE
        total = subtotal + tax

        # Get members
        members = social.members.filter(status__in=['joined', 'blocked']).select_related('user')

        # Check if already a member
        existing_member = social.members.filter(user=request.user).first()

        context = {
            'social': social,
            'invite': inv,
            'cart_items': cart_items,
            'members': members,
            'member_count': members.count(),
            'subtotal': subtotal,
            'tax': tax,
            'total': total,
            'existing_member': existing_member,
            'is_already_joined': existing_member and existing_member.status == 'joined',
            'is_blocked': existing_member and existing_member.status == 'blocked',
        }

        return render(request, 'marketplace/social_cart_invite.html', context)

    # POST request - accept invite
    elif request.method == 'POST':
        # Check if already a member
        existing_member = social.members.filter(user=request.user).first()

        if existing_member:
            if existing_member.status == 'joined':
                messages.warning(request, 'You are already a member of this social cart.')
                return redirect('marketplace:cart')
            elif existing_member.status == 'blocked':
                messages.error(request, 'You have been blocked from this social cart.')
                return redirect('marketplace:cart')
            elif existing_member.status == 'left':
                # Rejoin
                existing_member.status = 'joined'
                existing_member.save(update_fields=['status'])

                # Mark invite as accepted
                inv.status = 'accepted'
                inv.accepted_by = request.user
                inv.save(update_fields=['status', 'accepted_by'])

                messages.success(request, 'You have rejoined the social cart!')
                return redirect('marketplace:cart')
        else:
            # Create new membership
            with transaction.atomic():
                member = CartMember.objects.create(
                    social_cart=social,
                    user=request.user,
                    role='editor',
                    status='joined'
                )

                # Create default payment share
                PaymentShare.objects.create(
                    social_cart=social,
                    member=member,
                    is_active=True
                )

                # Mark invite as accepted
                inv.status = 'accepted'
                inv.accepted_by = request.user
                inv.save(update_fields=['status', 'accepted_by'])

        messages.success(request, f'You have joined {social.owner.username}\'s social cart!')
        return redirect('marketplace:cart')


@login_required
@require_POST
def approve_member(request, member_id):
    """
    Owner approves a pending member to join the social cart.
    """
    member = CartMember.objects.select_related("social_cart").filter(id=member_id).first()
    if not member:
        return _json_error("Member not found.", 404)

    social = member.social_cart

    if social.owner_id != request.user.id:
        return _json_error("Only the owner can approve members.", 403)

    if _not_mutable(social):
        return _json_error("Cart membership cannot be changed now.", 409)

    if member.status == "joined":
        return JsonResponse({"success": True, "message": "Member already approved."})

    member.status = "joined"
    member.save(update_fields=["status"])

    # Send approval email
    member_email = getattr(member.user, "email", "") or ""
    if member_email:
        cart_link = request.build_absolute_uri(reverse("marketplace:cart_view"))
        ctx = {
            "subject": "You're approved",
            "owner_name": social.owner.get_full_name() or social.owner.username,
            "cart_link": cart_link,
            "now": timezone.now(),
        }
        send_email_async(
            subject="You've been approved to join the Social Cart",
            to_email=member_email,
            html_template="emails/social_cart/approved.html",
            context=ctx,
        )

    social.recalc_members_due()
    return JsonResponse({"success": True, "message": "Member approved."})


@login_required
@require_POST
def reject_member(request, member_id):
    """
    Owner rejects a pending member's request to join the social cart.
    """
    member = CartMember.objects.select_related("social_cart", "user").filter(id=member_id).first()
    if not member:
        return _json_error("Member not found.", 404)

    social = member.social_cart

    if social.owner_id != request.user.id:
        return _json_error("Only the owner can reject members.", 403)

    if _not_mutable(social):
        return _json_error("Cart membership cannot be changed now.", 409)

    if member.status != "pending":
        return _json_error("Only pending members can be rejected.", 400)

    # Send rejection email
    member_email = getattr(member.user, "email", "") or ""
    if member_email:
        ctx = {
            "subject": "Social Cart Request Declined",
            "owner_name": social.owner.get_full_name() or social.owner.username,
            "now": timezone.now(),
        }
        send_email_async(
            subject="Your Social Cart request was declined",
            to_email=member_email,
            html_template="emails/social_cart/rejected.html",
            context=ctx,
        )

    # Remove their payment share
    PaymentShare.objects.filter(social_cart=social, member=member).delete()

    # Delete the member
    member.delete()

    return JsonResponse({"success": True, "message": "Member rejected and removed."})


@login_required
@require_POST
def block_member(request, member_id):
    """
    Owner blocks a member from modifying social cart
    Blocked members can still view but cannot add/modify items
    """
    cart = get_object_or_404(Cart, user=request.user)
    social = getattr(cart, 'social', None)

    if not social or not social.is_active:
        return JsonResponse({
            'success': False,
            'message': 'No active social cart found'
        }, status=404)

    # Verify owner
    if social.owner != request.user:
        return JsonResponse({
            'success': False,
            'message': 'Only the owner can block members'
        }, status=403)

    # Get member
    member = get_object_or_404(CartMember, id=member_id, social_cart=social)

    # Cannot block yourself
    if member.user == request.user:
        return JsonResponse({
            'success': False,
            'message': 'You cannot block yourself'
        }, status=400)

    # Block the member
    member.status = 'blocked'
    member.save(update_fields=['status', 'updated_at'])

    return JsonResponse({
        'success': True,
        'message': f'{member.user.username} has been blocked from modifying the social cart',
        'member_id': member.id,
        'member_username': member.user.username
    })


@login_required
@require_POST
def leave_cart(request):
    """
    Member leaves social cart
    - If owner leaves: deactivate cart and create orders for all members
    - If member leaves: just update their status
    """
    cart = get_object_or_404(Cart, user=request.user)
    social = getattr(cart, 'social', None)

    if not social or not social.is_active:
        return JsonResponse({
            'success': False,
            'message': 'No active social cart found'
        }, status=404)

    # Check if user is owner
    is_owner = social.owner == request.user

    with transaction.atomic():
        if is_owner:
            # Owner leaving = close the cart and create orders
            created_orders = social.deactivate_and_create_orders()

            return JsonResponse({
                'success': True,
                'message': f'You left the social cart. Orders created for all members.',
                'is_owner': True,
                'order_count': len(created_orders),
                'orders_created': True
            })
        else:
            # Regular member leaving
            member = social.members.filter(user=request.user).first()
            if member:
                member.status = 'left'
                member.save(update_fields=['status', 'updated_at'])

                # Move their social cart items to their normal cart
                social_items = cart.items.filter(cart_type='social', added_by=request.user)
                social_items.update(cart_type='normal')

            return JsonResponse({
                'success': True,
                'message': 'You left the social cart. Your items were moved to your normal cart.',
                'is_owner': False
            })


@login_required
@require_POST
def remove_member(request, member_id):
    """
    Owner removes a member completely from social cart
    Their items are moved to their personal normal cart
    """
    cart = get_object_or_404(Cart, user=request.user)
    social = getattr(cart, 'social', None)

    if not social or not social.is_active:
        return JsonResponse({
            'success': False,
            'message': 'No active social cart found'
        }, status=404)

    # Verify owner
    if social.owner != request.user:
        return JsonResponse({
            'success': False,
            'message': 'Only the owner can remove members'
        }, status=403)

    # Get member
    member = get_object_or_404(CartMember, id=member_id, social_cart=social)

    # Cannot remove yourself
    if member.user == request.user:
        return JsonResponse({
            'success': False,
            'message': 'You cannot remove yourself. Use "Leave Cart" instead.'
        }, status=400)

    with transaction.atomic():
        # Move member's social cart items to their normal cart
        member_cart = Cart.objects.get(user=member.user)
        social_items = member_cart.items.filter(cart_type='social', added_by=member.user)
        social_items.update(cart_type='normal')

        # Remove member
        member.delete()

    return JsonResponse({
        'success': True,
        'message': f'{member.user.username} has been removed from the social cart',
        'member_id': member.id
    })


# ---------- Live endpoint (fixes your 404 spam) ----------

@login_required
@require_GET
def social_cart_live(request):
    """
    Live update endpoint for social cart
    Returns current state of social cart including items and members
    """
    cart = get_object_or_404(Cart, user=request.user)
    social = getattr(cart, 'social', None)

    if not social:
        return JsonResponse({
            'success': True,
            'active': False,
            'message': 'No social cart'
        })

    # Get social cart items
    social_items = cart.items.filter(cart_type='social').select_related('product', 'added_by')

    # Get members
    members = social.members.filter(status__in=['joined', 'blocked']).select_related('user')

    # Check user permissions
    is_owner = social.owner == request.user
    my_member = members.filter(user=request.user).first()
    is_blocked = my_member and my_member.status == 'blocked'

    # Build items data
    items_data = []
    for item in social_items:
        items_data.append({
            'id': item.id,
            'product_id': item.product.id,
            'product_name': item.product.name,
            'price': float(item.product.price),
            'quantity': item.quantity,
            'subtotal': float(item.subtotal()),
            'added_by': item.added_by.username if item.added_by else 'Unknown',
            'added_by_id': item.added_by.id if item.added_by else None,
            'can_modify': item.can_user_modify(request.user),
            'selected_features': item.selected_features
        })

    # Build members data
    members_data = []
    for member in members:
        members_data.append({
            'id': member.id,
            'user_id': member.user.id,
            'username': member.user.username,
            'status': member.status,
            'role': member.role,
            'is_owner': member.user == social.owner
        })

    return JsonResponse({
        'success': True,
        'active': social.is_active,
        'social_id': social.id,
        'status': social.status,
        'split_mode': social.split_mode,
        'is_owner': is_owner,
        'is_blocked': is_blocked,
        'can_modify': not is_blocked and social.can_user_modify(request.user),
        'total': float(social.total()),
        'items': items_data,
        'members': members_data,
        'item_count': len(items_data)
    })


# ---------- Split Mode ----------

@login_required
@require_POST
def set_split_mode(request):
    """
    Owner sets how the social cart will be split for payment
    """
    social_id = request.POST.get('social_id')
    split_mode = request.POST.get('split_mode')

    if not social_id or not split_mode:
        return JsonResponse({
            'success': False,
            'message': 'Missing required parameters'
        }, status=400)

    social = get_object_or_404(SocialCart, id=social_id, is_active=True)

    # Verify owner
    if social.owner != request.user:
        return JsonResponse({
            'success': False,
            'message': 'Only the owner can change split mode'
        }, status=403)

    if split_mode not in ['by_items', 'by_percent', 'single_payer']:
        return JsonResponse({
            'success': False,
            'message': 'Invalid split mode'
        }, status=400)

    try:
        if split_mode == 'by_items':
            social.set_split_mode('by_items')
        elif split_mode == 'by_percent':
            # Get allocations from POST data
            allocations_json = request.POST.get('allocations', '{}')
            allocations = json.loads(allocations_json)
            # Convert keys to int
            allocations = {int(k): Decimal(str(v)) for k, v in allocations.items()}
            social.set_split_mode('by_percent', allocations=allocations)
        elif split_mode == 'single_payer':
            payer_member_id = request.POST.get('payer_member_id')
            if not payer_member_id:
                return JsonResponse({
                    'success': False,
                    'message': 'Payer member ID required for single payer mode'
                }, status=400)
            social.set_split_mode('single_payer', payer_member_id=int(payer_member_id))

        return JsonResponse({
            'success': True,
            'message': 'Split mode updated successfully',
            'split_mode': social.split_mode
        })

    except ValueError as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=400)


@require_POST
@login_required
def set_share(request):
    """
    Set or update a member's payment share.
    Owner-only.
    """
    social = _resolve_active_social_for(request.user)
    if not social:
        return _json_error("No active social cart", 404)

    if social.owner_id != request.user.id:
        return _json_error("Only the owner can set shares", 403)

    member_id = request.POST.get("member_id")
    percentage = request.POST.get("percentage")
    fixed_amount = request.POST.get("fixed_amount")

    if not member_id:
        return _json_error("member_id is required", 400)

    member = CartMember.objects.filter(
        id=member_id,
        social_cart=social,
        status="joined"
    ).first()

    if not member:
        return _json_error("Invalid member", 404)

    share, _ = PaymentShare.objects.get_or_create(
        social_cart=social,
        member=member
    )

    pct = _parse_decimal(percentage)
    amt = _parse_decimal(fixed_amount)

    if pct is not None and (pct < 0 or pct > 100):
        return _json_error("Percentage must be between 0 and 100")

    if amt is not None and amt < 0:
        return _json_error("Amount cannot be negative")

    share.percentage = pct
    share.fixed_amount = amt
    share.is_active = True
    share.save()

    social.recalc_members_due()

    return JsonResponse({
        "success": True,
        "message": "Share updated",
        "member_id": member.id,
        "percentage": share.percentage,
        "fixed_amount": share.fixed_amount,
        "amount_due": share.amount_due,
    })


@login_required
@require_POST
def start_my_payment(request):
    """
    Start payment for user's share in social cart
    Only owner can initiate full social cart checkout
    """
    cart = get_object_or_404(Cart, user=request.user)
    social = getattr(cart, 'social', None)

    if not social or not social.is_active:
        return JsonResponse({
            'success': False,
            'message': 'No active social cart found'
        }, status=404)

    # Check if user is owner
    if social.owner != request.user:
        return JsonResponse({
            'success': False,
            'message': 'Only the owner can checkout the social cart'
        }, status=403)

    # Verify there are items
    social_items = cart.items.filter(cart_type='social')
    if not social_items.exists():
        return JsonResponse({
            'success': False,
            'message': 'Social cart is empty'
        }, status=400)

    # Change status to checkout
    social.status = 'checkout'
    social.save(update_fields=['status', 'updated_at'])

    # Calculate total
    total = social.total()

    return JsonResponse({
        'success': True,
        'message': 'Checkout initiated',
        'total': float(total),
        'redirect_url': reverse('orders:checkout_social_cart')
    })

@login_required
@require_POST
def set_checkout_members(request):
    social_id = request.POST.get("social_id")
    social = get_object_or_404(SocialCart, id=social_id)

    if request.user.id != social.owner_id:
        return JsonResponse({"success": False, "message": "Only the owner can change checkout members."}, status=403)

    member_ids = request.POST.getlist("member_ids[]") or request.POST.getlist("member_ids")
    member_ids = [int(x) for x in member_ids if str(x).isdigit()]

    members = CartMember.objects.filter(social_cart=social, status="joined")

    # Set everyone false, then enable selected
    members.update(can_checkout=False)
    if member_ids:
        members.filter(id__in=member_ids).update(can_checkout=True)

    return JsonResponse({"success": True, "message": "Checkout permissions updated."})