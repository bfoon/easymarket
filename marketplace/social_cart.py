from decimal import Decimal, InvalidOperation
import uuid
import json

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum, Q
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.contrib import messages
from .social_cart_email import send_email_async
from django.views.decorators.http import require_POST, require_GET

from .models import (
    Cart, CartItem,
    SocialCart, CartMember, CartInvite, PaymentShare, Contribution, CartActivity,
    SocialCartChatThread, SocialCartChatMessage
)
from marketplace.models import Product

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

def get_active_social_cart_for_user(user):
    """
    Replace this with YOUR existing logic.
    Must return:
      - social_cart (object) or None
      - membership/permission info as needed
    """
    # Example (adjust):
    # social_cart = SocialCart.objects.filter(is_active=True, members=user).select_related("owner").first()
    # return social_cart

    # If you already store it in session:
    # cart_id = request.session.get("social_cart_id")
    # ...

    from .models import SocialCart  # only if you have it
    return SocialCart.objects.filter(is_active=True, members=user).first()

def _get_or_create_group_thread(social):
    t, _ = SocialCartChatThread.objects.get_or_create(
        social_cart=social,
        scope=SocialCartChatThread.SCOPE_GROUP,
        product=None,
        defaults={}
    )
    return t

def _get_or_create_item_thread(social, product):
    t, _ = SocialCartChatThread.objects.get_or_create(
        social_cart=social,
        scope=SocialCartChatThread.SCOPE_ITEM,
        product=product,
        defaults={}
    )
    return t

def _get_or_create_seller_item_thread(social, product):
    seller = _get_product_seller_user(product)
    t, _ = SocialCartChatThread.objects.get_or_create(
        social_cart=social,
        scope=SocialCartChatThread.SCOPE_SELLER_ITEM,
        product=product,
        defaults={"seller": seller}
    )
    if seller and not t.participants.filter(id=seller.id).exists():
        t.participants.add(seller)
    return t

def _ensure_member_participant(thread, user):
    if not thread.participants.filter(id=user.id).exists():
        thread.participants.add(user)

def _product_snapshot(product, request=None):
    # pick best image (adapt to your product model)
    img = ""
    try:
        if getattr(product, "image", None):
            img = product.image.url
    except Exception:
        img = ""
    return {
        "id": product.id,
        "name": product.name,
        "price": str(product.price),
        "image": img,
    }

def _get_product_seller_user(product):
    if getattr(product, "store", None) and getattr(product.store, "owner", None):
        return product.store.owner
    if getattr(product, "seller", None):
        return product.seller
    return None

# ---------- Core endpoints ----------
@login_required
@require_POST
def create_social_cart(request):
    """
    Create (or revive) a social cart for the user.
    Because SocialCart.cart is UNIQUE, we must never try to create
    a second SocialCart for the same cart.
    """
    cart, _ = Cart.objects.get_or_create(user=request.user)

    with transaction.atomic():
        # Lock the cart row to avoid double-create races from fast clicks
        cart = Cart.objects.select_for_update().get(pk=cart.pk)

        existing_social = getattr(cart, "social", None)

        if existing_social:
            # If already active/open, return it (idempotent)
            if existing_social.is_active and existing_social.status == "open":
                social = existing_social
            else:
                # Revive / reset the existing record (no new create!)
                social = existing_social
                social.is_active = True
                social.status = "open"
                social.split_mode = social.split_mode or "by_items"
                social.save(update_fields=["is_active", "status", "split_mode"])
        else:
            # Create only when none exists
            social = SocialCart.objects.create(
                cart=cart,
                owner=request.user,
                is_active=True,
                status="open",
                split_mode="by_items",
            )

        # Ensure owner membership exists (avoid duplicates)
        member, created = CartMember.objects.get_or_create(
            social_cart=social,
            user=request.user,
            defaults={"role": "owner", "status": "joined"},
        )
        if not created:
            # If it existed but was left/invited, normalize it
            updates = {}
            if member.role != "owner":
                updates["role"] = "owner"
            if member.status != "joined":
                updates["status"] = "joined"
            if updates:
                for k, v in updates.items():
                    setattr(member, k, v)
                member.save(update_fields=list(updates.keys()))

        # Ensure payment share exists (avoid duplicates)
        PaymentShare.objects.get_or_create(
            social_cart=social,
            member=member,
            defaults={"percentage": 100, "is_active": True},
        )

    invite_link = request.build_absolute_uri(
        reverse("marketplace:join_open_social_cart", kwargs={"invite_code": social.invite_code})
    )

    return JsonResponse({
        "success": True,
        "message": "Social cart ready!",
        "social_id": social.id,
        "invite_code": social.invite_code,
        "invite_link": invite_link,
        "revived": bool(getattr(cart, "social", None) and getattr(cart.social, "id", None) == social.id),
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

    # Enforce join rules
    if social.access_type == SocialCart.ACCESS_INVITE_ONLY:
        # Must be invited OR already a member
        if not existing_member:
            # If you require email-based invite acceptance:
            # allow only if there's a valid invite for this user email
            user_email = (request.user.email or "").strip().lower()
            has_invite = False
            if user_email:
                has_invite = social.invites.filter(invited_email__iexact=user_email, status="pending").exists()

            if not has_invite:
                if request.method == "POST":
                    return JsonResponse({"success": False, "message": "Invite-only cart. You must be invited."},
                                        status=403)
                messages.error(request, "This is an invite-only social cart. You must be invited.")
                return redirect("marketplace:cart")

        # Optional: scheduled gate
        if social.scheduled_for and timezone.now() < social.scheduled_for:
            if request.method == "POST":
                return JsonResponse({"success": False, "message": "This social cart is scheduled. Please join later."},
                                    status=403)
            messages.warning(request,
                             f"This social cart is scheduled for {social.scheduled_for.strftime('%Y-%m-%d %H:%M')}.")
            return redirect("marketplace:cart")

    # GET request - show invite page
    if request.method == 'GET':
        # Get social cart details
        cart_items = social.cart.items.filter(cart_type='social').select_related('product', 'added_by')

        # Calculate totals
        from decimal import Decimal
        CART_TAX_RATE = Decimal("0.00")
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

def log_cart_activity(social, actor, event, message="", payload=None):
    CartActivity.objects.create(
        social_cart=social,
        actor=actor if actor and actor.is_authenticated else None,
        event=event,
        message=message or "",
        payload=payload or {},
    )


@login_required
@require_POST
def leave_cart(request):
    """
    Member leaves social cart
    - If owner leaves: deactivate cart and create orders for all members
    - If member leaves: just update their status
    """
    try:
        # Use the helper function to find active social cart for this user
        # This works for both owners and members
        social = _resolve_active_social_for(request.user)

        if not social:
            return JsonResponse({
                'success': False,
                'message': 'No active social cart found'
            }, status=404)

        # Check if user is owner
        is_owner = social.owner == request.user

        # Get user's cart for item operations
        cart = get_object_or_404(Cart, user=request.user)

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

    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error in leave_cart: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': f'An error occurred: {str(e)}'
        }, status=500)

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
def social_cart_events(request):
    cart = get_object_or_404(Cart, user=request.user)
    social = getattr(cart, "social", None)

    if not social or not social.is_active:
        return JsonResponse({"success": True, "events": [], "last_id": 0})

    since_id = request.GET.get("since_id")
    try:
        since_id = int(since_id or 0)
    except Exception:
        since_id = 0

    qs = social.activities.filter(id__gt=since_id).select_related("actor").order_by("id")[:50]

    events = []
    last_id = since_id
    for a in qs:
        last_id = a.id
        events.append({
            "id": a.id,
            "event": a.event,
            "message": a.message,
            "actor": getattr(a.actor, "username", None),
            "payload": a.payload,
            "created_at": a.created_at.isoformat(),
        })

    return JsonResponse({"success": True, "events": events, "last_id": last_id})

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
    social_id = request.POST.get("social_id")
    split_mode = (request.POST.get("split_mode") or "").strip()

    if not social_id or not split_mode:
        return JsonResponse({"success": False, "message": "Missing required parameters"}, status=400)

    social = get_object_or_404(SocialCart, id=social_id, is_active=True)

    if social.owner_id != request.user.id:
        return JsonResponse({"success": False, "message": "Only the owner can change split mode"}, status=403)

    if split_mode not in ("by_items", "by_percent", "single_payer"):
        return JsonResponse({"success": False, "message": "Invalid split mode"}, status=400)

    try:
        if split_mode == "by_items":
            social.set_split_mode("by_items")

        elif split_mode == "by_percent":
            allocations_json = request.POST.get("allocations") or "{}"
            allocations = json.loads(allocations_json) or {}
            if not isinstance(allocations, dict):
                allocations = {}

            # convert safely
            clean_allocations = {}
            for k, v in allocations.items():
                if str(k).isdigit():
                    dv = _parse_decimal(v)
                    if dv is not None:
                        clean_allocations[int(k)] = dv

            social.set_split_mode("by_percent", allocations=clean_allocations)

        elif split_mode == "single_payer":
            payer_member_id = request.POST.get("payer_member_id")
            if not payer_member_id or not str(payer_member_id).isdigit():
                return JsonResponse({"success": False, "message": "Valid payer_member_id is required"}, status=400)

            social.set_split_mode("single_payer", payer_member_id=int(payer_member_id))

        return JsonResponse({"success": True, "message": "Split mode updated successfully", "split_mode": social.split_mode})

    except ValueError as e:
        return JsonResponse({"success": False, "message": str(e)}, status=400)

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

@login_required
@require_GET
def social_cart_fragment(request):
    """
    Returns ONLY the Social Cart HTML block.
    Safe to poll without reloading the main page.
    """
    social = _resolve_active_social_for(request.user)
    if not social:
        return render(request, "marketplace/partials/_social_cart_block.html", {
            "is_social_active": False
        })

    # Determine my member + blocked
    me = social.members.filter(user=request.user).first()
    is_blocked = bool(me and me.status == "blocked")
    is_owner = (social.owner_id == request.user.id) or bool(me and me.role == "owner")

    # Social items live from the underlying cart
    cart = social.cart
    social_items = (
        cart.items
        .filter(cart_type="social")
        .select_related("product", "added_by")
        .order_by("-id")
    )

    members = (
        social.members
        .filter(status__in=["joined", "blocked"])
        .select_related("user")
        .order_by("id")
    )

    context = {
        "is_social_active": True,
        "social": social,
        "social_items": social_items,
        "social_item_count": social_items.count(),
        "members": members,
        "member_count": members.count(),
        "is_owner": is_owner,
        "is_blocked": is_blocked,
        "can_modify": (not is_blocked) and social.can_user_modify(request.user),

        # Totals (you already have social.total())
        "social_total": social.total(),
    }
    return render(request, "marketplace/partials/_social_cart_block.html", context)

@login_required
@require_GET
def social_cart_chat_fragment(request):
    social = _resolve_active_social_for(request.user)
    if not social:
        return render(request, "marketplace/partials/_social_cart_chat_messages.html", {"has_social_cart": False})

    me_member = social.members.filter(user=request.user).first()
    if not me_member:
        return render(request, "marketplace/partials/_social_cart_chat_messages.html", {"has_social_cart": False})

    scope = (request.GET.get("scope") or "group").strip().lower()
    product_id = (request.GET.get("product_id") or "").strip()

    thread_product = None
    thread_selected_features = {}   # ✅ ensure always dict

    qs = SocialCartChatMessage.objects.filter(social_cart=social).select_related("sender")

    if scope == "group":
        qs = qs.filter(scope="group")

    elif scope == "item":
        if not product_id:
            scope = "group"
            qs = qs.filter(scope="group")
        else:
            thread_product = get_object_or_404(Product, id=product_id)
            qs = qs.filter(scope="item", product_id=str(thread_product.id))

    elif scope == "seller_item":
        if not product_id:
            scope = "group"
            qs = qs.filter(scope="group")
        else:
            thread_product = get_object_or_404(Product, id=product_id)
            seller_user = _get_product_seller_user(thread_product)

            if not seller_user:
                scope = "group"
                qs = qs.filter(scope="group")
            else:
                qs = (
                    qs.filter(scope="seller_item", product_id=str(thread_product.id))
                      .filter(Q(sender=request.user) | Q(recipient=request.user))
                )
    else:
        scope = "group"
        qs = qs.filter(scope="group")

    qs = qs.order_by("-created_at")[:60]
    messages_list = list(reversed(qs))

    # ✅ Determine thread_selected_features from the latest message in this thread that has them
    if thread_product:
        for msg in reversed(messages_list):
            snap = getattr(msg, "product_snapshot", {}) or {}
            feats = snap.get("selected_features")
            if isinstance(feats, dict) and feats:
                thread_selected_features = feats
                break

    # collect product ids from message.product_id OR snapshot.id
    pids = set()
    for msg in messages_list:
        if getattr(msg, "product_id", None):
            pids.add(str(msg.product_id))
        else:
            snap = getattr(msg, "product_snapshot", {}) or {}
            if snap.get("id"):
                pids.add(str(snap["id"]))

    products = {}
    if pids:
        for p in Product.objects.filter(id__in=list(pids)).select_related("store"):
            products[str(p.id)] = p

    for msg in messages_list:
        snap = getattr(msg, "product_snapshot", {}) or {}
        pid = str(getattr(msg, "product_id", "") or snap.get("id") or "")
        msg.product_obj = products.get(pid)

        # ✅ always dict (critical for template + get_color_image_url)
        feats = snap.get("selected_features") or {}
        msg.selected_features = feats if isinstance(feats, dict) else {}

        # store info
        msg.store_logo = snap.get("store_logo") or None
        msg.store_name = snap.get("store_name") or ""

        if (not msg.store_logo) and msg.product_obj and getattr(msg.product_obj, "store", None):
            msg.store_name = msg.store_name or (getattr(msg.product_obj.store, "name", "") or "")
            logo = getattr(msg.product_obj.store, "logo", None) or getattr(msg.product_obj.store, "store_logo", None)
            try:
                msg.store_logo = logo.url if logo else None
            except Exception:
                msg.store_logo = None

    thread_store_logo = None
    thread_store_name = ""
    if thread_product and getattr(thread_product, "store", None):
        thread_store_name = getattr(thread_product.store, "name", "") or ""
        logo = getattr(thread_product.store, "logo", None) or getattr(thread_product.store, "store_logo", None)
        try:
            thread_store_logo = logo.url if logo else None
        except Exception:
            thread_store_logo = None

    return render(request, "marketplace/partials/_social_cart_chat_messages.html", {
        "has_social_cart": True,
        "social": social,
        "chat_messages": messages_list,
        "me": request.user,
        "current_scope": scope,
        "thread_product": thread_product,
        "thread_selected_features": thread_selected_features,  # ✅ FIX
        "thread_store_logo": thread_store_logo,
        "thread_store_name": thread_store_name,
    })



def _to_bool(v) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "y", "on")


@login_required
@require_POST
def social_cart_chat_send(request):
    """
    Send a message or share a product card into chat.

    Supports:
      - scope=group|item|seller_item
      - product_id for item/seller_item threads OR for attach_product
      - attach_product=1 to post a product card (message can be empty)
      - selected_features (JSON string) stored in product_snapshot for variant image rendering
    """
    social = _resolve_active_social_for(request.user)
    if not social:
        return _json_error("No active social cart found.", 404)

    member = social.members.filter(user=request.user).first()
    if not member:
        return _json_error("You are not a member of this social cart.", 403)

    if member.status == "blocked":
        return _json_error("You are blocked and cannot send messages.", 403)

    scope = (request.POST.get("scope") or "group").strip().lower()
    if scope not in ("group", "item", "seller_item"):
        scope = "group"

    product_id = (request.POST.get("product_id") or "").strip()
    attach_product = _to_bool(request.POST.get("attach_product"))
    msg = (request.POST.get("message") or "").strip()

    # selected_features is expected to be JSON (string) coming from your share button
    selected_features_raw = request.POST.get("selected_features") or ""
    try:
        selected_features = json.loads(selected_features_raw) if selected_features_raw else {}
        if not isinstance(selected_features, dict):
            selected_features = {}
    except Exception:
        selected_features = {}

    # Message rules
    if not attach_product and not msg:
        return _json_error("Message cannot be empty.", 400)

    if msg and len(msg) > 2000:
        return _json_error("Message too long (max 2000 chars).", 400)

    # Resolve product if needed
    product = None
    if product_id:
        product = Product.objects.filter(id=product_id).select_related("store").first()

    # item/seller_item requires product
    if scope in ("item", "seller_item") and not product:
        return _json_error("Product is required for this chat thread.", 400)

    # attach_product generally needs product too (otherwise you can't build the card)
    if attach_product and not product:
        return _json_error("Product is required to share an item card.", 400)

    # Resolve seller user for seller_item scope
    recipient = None
    seller_user = None
    if product:
        if getattr(product, "store", None) and getattr(product.store, "owner", None):
            seller_user = product.store.owner
        elif getattr(product, "seller", None):
            seller_user = product.seller

        if scope == "seller_item":
            if not seller_user:
                return _json_error("This product has no shop owner to chat with.", 400)
            recipient = seller_user

    # Build snapshot (used for display + variant image logic)
    product_snapshot = {}
    if product:
        # product image (fallback only; variant image is computed in template via get_color_image_url)
        img_url = ""
        try:
            if getattr(product, "image", None):
                img_url = product.image.url
        except Exception:
            img_url = ""

        # store logo (for seller thread / card)
        store_logo = ""
        store_name = ""
        if getattr(product, "store", None):
            store_name = getattr(product.store, "name", "") or ""
            logo_field = getattr(product.store, "logo", None) or getattr(product.store, "store_logo", None)
            try:
                store_logo = logo_field.url if logo_field else ""
            except Exception:
                store_logo = ""

        product_snapshot = {
            "id": str(product.id),
            "name": getattr(product, "name", "") or "",
            "price": str(getattr(product, "price", "") or ""),
            "image": img_url,  # fallback image only
            "selected_features": selected_features,  # ✅ critical for get_color_image_url
            "store_name": store_name,
            "store_logo": store_logo,
        }

    SocialCartChatMessage.objects.create(
        social_cart=social,
        sender=request.user,
        recipient=recipient,                       # seller private thread target (nullable)
        scope=scope,                               # "group"|"item"|"seller_item"
        product_id=str(product.id) if product else None,
        message=msg,
        attach_product=attach_product,
        product_snapshot=product_snapshot,
    )

    # Optional event log
    try:
        log_cart_activity(
            social=social,
            actor=request.user,
            event="chat_message",
            message="New chat message",
            payload={"scope": scope, "product_id": str(product.id) if product else None},
        )
    except Exception:
        pass

    return JsonResponse({"success": True})

# ---------------------------------------
# SCHEDULE SOCIAL CART (Invite-only best)
# ---------------------------------------
@login_required
@require_POST
def schedule_social_cart(request):
    social = _resolve_active_social_for(request.user)
    if not social:
        return _json_error("No active social cart found.", 404)

    if social.owner_id != request.user.id:
        return _json_error("Only the owner can schedule this cart.", 403)

    # Expect ISO string: 2026-01-22T18:30
    scheduled_for = (request.POST.get("scheduled_for") or "").strip()
    access_type = (request.POST.get("access_type") or "").strip()  # public / invite_only

    if access_type not in ("public", "invite_only"):
        return _json_error("Invalid access_type. Use public or invite_only.", 400)

    if not scheduled_for:
        return _json_error("scheduled_for is required.", 400)

    try:
        # naive parse; if you want timezone-aware, use Django forms or dateutil
        dt = timezone.datetime.fromisoformat(scheduled_for)
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
    except Exception:
        return _json_error("Invalid datetime format. Use ISO like 2026-01-22T18:30", 400)

    social.access_type = access_type
    social.scheduled_for = dt
    social.save(update_fields=["access_type", "scheduled_for", "updated_at"])

    # Log activity (so pollers refresh)
    try:
        log_cart_activity(
            social=social,
            actor=request.user,
            event="cart_scheduled",
            message=f"Social cart scheduled for {dt.strftime('%Y-%m-%d %H:%M')}",
            payload={"scheduled_for": dt.isoformat(), "access_type": access_type}
        )
    except Exception:
        pass

    # Notify invitees (invite-only usually)
    # - joined members with email
    # - pending invites with invited_email
    try:
        subject = "EasyMarket Social Cart Scheduled"
        owner_name = social.owner.get_full_name() or social.owner.username
        when_text = dt.strftime("%A, %d %B %Y at %H:%M")

        # joined members
        members = social.members.filter(status="joined").select_related("user")
        to_emails = [m.user.email for m in members if getattr(m.user, "email", None)]

        # pending invites
        pending_invites = social.invites.filter(status="pending")
        to_emails += [i.invited_email for i in pending_invites if i.invited_email]

        to_emails = sorted(set([e for e in to_emails if e]))

        if to_emails:
            invite_link = request.build_absolute_uri(
                reverse("marketplace:join_open_social_cart", kwargs={"invite_code": social.invite_code})
            )

            html = f"""
            <p>Hello,</p>
            <p><b>{owner_name}</b> scheduled a Social Cart session.</p>
            <p><b>When:</b> {when_text}</p>
            <p><b>Join link:</b> {invite_link}</p>
            <p>See you there 🙌</p>
            """

            for email in to_emails:
                send_email_async(
                    subject="EasyMarket Social Cart Scheduled",
                    to_email=email,
                    html_template="emails/social_cart/scheduled.html",
                    context={
                        "recipient_name": "",
                        "owner_name": owner_name,
                        "when_text": when_text,
                        "access_type": access_type,
                        "member_count": social.members.filter(status="joined").count(),
                        "invite_link": invite_link,
                        "now": timezone.now(),
                    }
                )

    except Exception:
        # don't break scheduling on email errors
        pass

    return JsonResponse({
        "success": True,
        "message": "Social cart scheduled successfully.",
        "scheduled_for": social.scheduled_for.isoformat(),
        "access_type": social.access_type
    })


# ---------------------------------------
# OWNER GO LIVE / OFFLINE
# ---------------------------------------
@login_required
@require_POST
def social_cart_set_live(request):
    social = _resolve_active_social_for(request.user)
    if not social:
        return _json_error("No active social cart found.", 404)

    if social.owner_id != request.user.id:
        return _json_error("Only the owner can set live status.", 403)

    is_live = (request.POST.get("is_live") or "true").lower() in ("1", "true", "yes", "on")

    social.is_live = is_live
    if is_live and not social.live_started_at:
        social.live_started_at = timezone.now()
    social.save(update_fields=["is_live", "live_started_at", "updated_at"])

    # Activity ping
    try:
        log_cart_activity(
            social=social,
            actor=request.user,
            event="owner_live",
            message="Cart owner is now live" if is_live else "Cart owner went offline",
            payload={"is_live": is_live}
        )
    except Exception:
        pass

    # Notify members when owner comes live (only when turning ON)
    if is_live:
        try:
            owner_name = social.owner.get_full_name() or social.owner.username
            members = social.members.filter(status="joined").select_related("user")
            to_emails = [m.user.email for m in members if getattr(m.user, "email", None)]
            to_emails = [e for e in sorted(set(to_emails)) if e]

            if to_emails:
                link = request.build_absolute_uri(reverse("marketplace:cart_view"))  # adjust if your cart page url name differs
                html = f"""
                <p>Hey!</p>
                <p><b>{owner_name}</b> is now live on the Social Cart chat.</p>
                <p>Join the chat here: {link}</p>
                <p>🔥</p>
                """
                for email in to_emails:
                    send_email_async(
                        subject="EasyMarket: Social Cart Owner is Live",
                        to_email=email,
                        html_template=None,
                        context={"raw_html": html}
                    )
        except Exception:
            pass

    return JsonResponse({"success": True, "is_live": social.is_live})