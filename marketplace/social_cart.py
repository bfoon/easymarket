from decimal import Decimal, InvalidOperation
import uuid
import json
from django.http import HttpResponse

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
from django.views.decorators.http import require_http_methods

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


def log_cart_activity(social, actor, event, message="", payload=None):
    """
    Helper to create CartActivity entries
    """
    try:
        CartActivity.objects.create(
            social_cart=social,
            actor=actor,
            event=event,
            message=message,
            payload=payload or {}
        )
    except Exception:
        pass  # fail silently


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
    from .models import SocialCart
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

def _wants_json(request) -> bool:
    # JS calls send X-Requested-With, browsers usually don't.
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True
    accept = (request.headers.get("Accept") or "").lower()
    return "application/json" in accept

def _respond(request, ok: bool, message: str, status_code: int = 200, **extra):
    """
    Return JSON for AJAX, redirect+flash for normal browser.
    """
    if _wants_json(request):
        payload = {"success": ok, "message": message}
        payload.update(extra)
        return JsonResponse(payload, status=status_code)

    # Browser experience
    if ok:
        messages.success(request, message)
    else:
        # use warning for "already a member" type
        if status_code in (400, 409):
            messages.warning(request, message)
        else:
            messages.error(request, message)
    return redirect("marketplace:cart")

# ---------- Core endpoints ----------
@login_required
@require_POST
def create_social_cart(request):
    """
    Create or reactivate a social cart for the user.

    BEHAVIOR:
    - If active social cart exists → Return it
    - If inactive/archived social cart exists → Archive it, create fresh one
    - If no social cart exists → Create new one

    This prevents the duplicate key error while ensuring fresh carts.
    """
    from marketplace.models import Cart
    from django.db import transaction

    cart, _ = Cart.objects.get_or_create(user=request.user)

    # Read access_type from POST
    access_type = (request.POST.get("access_type") or "public").strip()
    if access_type not in ("public", "invite_only"):
        access_type = "public"

    with transaction.atomic():
        # Lock the cart row to avoid race conditions
        cart = Cart.objects.select_for_update().get(pk=cart.pk)

        # Get existing social cart if any
        existing_social = getattr(cart, "social", None)

        # CASE 1: Active social cart already exists
        if existing_social and existing_social.is_active and existing_social.status in ('open', 'checkout'):
            # Just update access type if needed
            if existing_social.access_type != access_type:
                existing_social.access_type = access_type
                existing_social.save(update_fields=["access_type", "updated_at"])

            # Ensure owner membership
            owner_member, created = CartMember.objects.get_or_create(
                social_cart=existing_social,
                user=request.user,
                defaults={"role": "owner", "status": "joined", "is_original_owner": True}
            )

            if not created and owner_member.status != "joined":
                owner_member.status = "joined"
                owner_member.role = "owner"
                owner_member.save(update_fields=["status", "role", "updated_at"])

            return JsonResponse({
                'success': True,
                'message': 'Social cart already active',
                'invite_code': existing_social.invite_code,
                'social_id': str(existing_social.id),
            })

        # CASE 2: Inactive/archived social cart exists
        if existing_social:
            # Archive the old one completely
            existing_social.is_active = False
            existing_social.status = 'archived'
            existing_social.save(update_fields=['is_active', 'status', 'updated_at'])

            # Archive all old members
            existing_social.members.all().update(status='archived')

            # Log archival
            log_cart_activity(
                social=existing_social,
                actor=request.user,
                event="cart_archived",
                message="Old social cart archived when creating new one"
            )

            # ✅ CRITICAL: Delete the old social cart to free up the cart foreign key
            # This allows us to create a fresh one
            old_invite_code = existing_social.invite_code
            existing_social.delete()

            print(f"✅ Archived and deleted old social cart with invite code: {old_invite_code}")

        # CASE 3: Create fresh social cart
        social = SocialCart.objects.create(
            cart=cart,
            owner=request.user,
            is_active=True,
            status="open",
            split_mode="by_items",
            access_type=access_type,
            # original_owner will be set automatically if field exists
        )

        # Set original owner if field exists
        if hasattr(social, 'original_owner'):
            social.original_owner = request.user
            social.save(update_fields=['original_owner'])

        # Create owner membership
        owner_member = CartMember.objects.create(
            social_cart=social,
            user=request.user,
            role="owner",
            status="joined",
            is_original_owner=True  # Mark as original owner
        )

        # Create payment share for owner
        PaymentShare.objects.create(
            social_cart=social,
            member=owner_member,
            percentage=Decimal("100"),
            is_active=True
        )

        # Move normal cart items to NEW social cart
        normal_items = cart.items.filter(cart_type="normal")
        if normal_items.exists():
            normal_items.update(cart_type="social", added_by=request.user)

        social.recalc_members_due()

        # Log activity for NEW cart
        log_cart_activity(
            social=social,
            actor=request.user,
            event="cart_created",
            message="Fresh social cart created",
            payload={"access_type": access_type}
        )

        return JsonResponse({
            'success': True,
            'message': 'Social cart created successfully!',
            'invite_code': social.invite_code,
            'social_id': str(social.id),
        })

@login_required
@require_POST
def leave_and_checkout_all(request):
    """
    Owner leaves and creates orders for ALL members (including themselves)
    This closes the social cart and creates individual orders

    UPDATED: Uses email template for better formatting
    """
    try:
        social = _resolve_active_social_for(request.user)

        if not social:
            return JsonResponse({
                'success': False,
                'message': 'No active social cart found'
            }, status=404)

        # Only owner can do this
        if social.owner != request.user:
            return JsonResponse({
                'success': False,
                'message': 'Only the cart owner can checkout all members'
            }, status=403)

        with transaction.atomic():
            # Create orders for all members
            created_orders = social.deactivate_and_create_orders()

            # Log activity
            try:
                log_cart_activity(
                    social=social,
                    actor=request.user,
                    event="checkout_all",
                    message="Cart owner created orders for all members",
                    payload={"order_count": len(created_orders)}
                )
            except Exception:
                pass

            # Send email notifications to all members using template
            try:
                owner_name = social.owner.get_full_name() or social.owner.username
                members = social.members.filter(status__in=['joined', 'left']).select_related('user')

                for member in members:
                    if not member.user.email:
                        continue

                    # Check if this member has an order
                    order = created_orders.get(member.user)
                    if not order:
                        continue

                    # Try to get order detail URL
                    try:
                        order_url = request.build_absolute_uri(
                            reverse("orders:order_detail", kwargs={"order_id": order.id})
                        )
                    except Exception:
                        # Fallback if URL doesn't exist
                        order_url = request.build_absolute_uri(reverse("marketplace:cart"))

                    # Send email with template
                    send_email_async(
                        subject="Your Social Cart Order is Ready",
                        to_email=member.user.email,
                        html_template="emails/social_cart/order_created.html",
                        context={
                            "recipient_name": member.user.get_full_name() or member.user.username,
                            "owner_name": owner_name,
                            "order": order,
                            "order_url": order_url
                        }
                    )

            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Email notification failed: {str(e)}")

            # Determine redirect URL
            redirect_url = None
            if created_orders:
                try:
                    # Try different possible URL names for orders list
                    for url_name in ['orders:order_history', 'orders:my_orders', 'orders:list']:
                        try:
                            redirect_url = reverse(url_name)
                            break
                        except Exception:
                            continue

                    # If no list view found, try detail view of first order
                    if not redirect_url:
                        first_order = list(created_orders.values())[0]
                        try:
                            redirect_url = reverse('orders:order_detail', kwargs={'order_id': first_order.id})
                        except Exception:
                            pass

                    # Final fallback: redirect to cart
                    if not redirect_url:
                        redirect_url = reverse('marketplace:cart')

                except Exception:
                    # Absolute fallback
                    redirect_url = reverse('marketplace:cart')

            return JsonResponse({
                'success': True,
                'message': f'Orders created for {len(created_orders)} member(s). Redirecting...',
                'order_count': len(created_orders),
                'redirect_url': redirect_url
            })

    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error in leave_and_checkout_all: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': f'An error occurred: {str(e)}'
        }, status=500)


@login_required
@require_GET
def social_cart_status(request):
    """
    Authoritative status endpoint for JS.
    Returns core state + (for owners) pending member requests, sent invites, and joined members.

    FIXED: Now returns pending_invites and members lists
    """
    social = _resolve_active_social_for(request.user)
    if not social:
        return JsonResponse({"success": True, "social_id": None})

    me = social.members.filter(user=request.user, status="joined").first()
    is_owner = bool(me and me.role == "owner") or (social.owner_id == request.user.id)

    invite_link = _abs_uri(request, "join_open_social_cart", invite_code=social.invite_code)

    # Pending member requests (people who clicked link and are waiting approval)
    pending_members = []

    # Pending invites (invitations sent but not yet accepted)
    pending_invites = []

    # Joined members (active members in the cart)
    members = []

    if is_owner:
        # Get pending member requests
        pending_qs = (
            social.members
            .filter(status__in=["pending", "blocked"])
            .select_related("user")
            .order_by("-updated_at")[:50]
        )

        pending_members = [
            {
                "id": m.id,
                "username": getattr(m.user, "username", ""),
                "name": (m.user.get_full_name() or getattr(m.user, "username", "")),
                "email": (getattr(m.user, "email", "") or ""),
                "status": m.status,
            }
            for m in pending_qs
        ]

        # Get pending invites (not yet accepted)
        invites_qs = (
            social.invites
            .filter(status="pending", expires_at__gt=timezone.now())
            .order_by("-created_at")[:50]
        )

        pending_invites = [
            {
                "id": inv.id,
                "invited_email": inv.invited_email or "",
                "invited_phone": inv.invited_phone or "",
                "code": inv.code,
                "created_at": inv.created_at.isoformat(),
                "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
                "status": inv.status,
            }
            for inv in invites_qs
        ]

        # Get joined members
        members_qs = (
            social.members
            .filter(status="joined")
            .select_related("user")
            .order_by("-joined_at")[:100]
        )

        members = [
            {
                "id": m.id,
                "username": getattr(m.user, "username", ""),
                "name": (m.user.get_full_name() or getattr(m.user, "username", "")),
                "email": (getattr(m.user, "email", "") or ""),
                "role": m.role,
                "status": m.status,
            }
            for m in members_qs
        ]

    return JsonResponse({
        "success": True,
        "social_id": str(social.id),
        "status": social.status,
        "split_mode": getattr(social, "split_mode", "by_items"),
        "single_payer_id": getattr(social, "single_payer_id", None),
        "invite_link": invite_link,
        "is_owner": is_owner,
        "access_type": getattr(social, "access_type", "public"),
        "scheduled_for": social.scheduled_for.isoformat() if getattr(social, "scheduled_for", None) else None,

        # ✅ FIXED: Now includes all three lists
        "pending_members": pending_members,  # People waiting for approval
        "pending_invites": pending_invites,  # Invitations sent but not accepted
        "members": members,  # Active members
    })


@login_required
@require_POST
def send_cart_invite(request):
    """
    Send an invite to join social cart via email/phone.

    FIXED: Now properly sends emails and creates invite records
    """
    from marketplace.models import Cart
    from django.utils import timezone
    from django.core.validators import validate_email
    from django.core.exceptions import ValidationError

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

    # Validate email if provided
    if email:
        try:
            validate_email(email)
        except ValidationError:
            return JsonResponse({
                'success': False,
                'message': 'Please provide a valid email address'
            }, status=400)

    # Check if invite already exists for this email/phone
    existing_invite = CartInvite.objects.filter(
        social_cart=social,
        status='pending'
    )

    if email:
        existing_invite = existing_invite.filter(invited_email=email)
    elif phone:
        existing_invite = existing_invite.filter(invited_phone=phone)

    if existing_invite.exists():
        return JsonResponse({
            'success': False,
            'message': 'An invitation has already been sent to this email/phone'
        }, status=400)

    # Create invite
    try:
        invite = CartInvite.objects.create(
            social_cart=social,
            inviter=request.user,
            invited_email=email or None,
            invited_phone=phone or None,
            expires_at=timezone.now() + timezone.timedelta(days=7)
        )

        # Log activity
        log_cart_activity(
            social=social,
            actor=request.user,
            event="invite_sent",
            message=f"Invitation sent to {email or phone}",
            payload={"invite_id": str(invite.id)}
        )
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error creating invite: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': 'Failed to create invitation'
        }, status=500)

    # Generate invite link
    invite_link = request.build_absolute_uri(
        reverse('marketplace:accept_cart_invite', kwargs={'code': invite.code})
    )

    # Send email if provided
    if email:
        try:
            owner_name = request.user.get_full_name() or request.user.username

            # Try using the email template system
            send_email_async(
                subject=f"Join {owner_name}'s Social Cart on EasyMarket",
                to_email=email,
                html_template="emails/social_cart/invite.html",
                context={
                    "inviter_name": owner_name,
                    "invite_link": invite_link,
                    "cart_access_type": social.access_type,
                    "expires_at": invite.expires_at,
                }
            )

            email_sent = True

        except Exception as e:
            # Fallback to simple email if template doesn't exist
            try:
                from django.core.mail import send_mail
                from django.conf import settings

                message = f"""
Hi!

{owner_name} has invited you to join their social cart on EasyMarket.

Click here to join: {invite_link}

This invitation will expire in 7 days.

Happy shopping!
EasyMarket Team
                """

                send_mail(
                    subject=f"Join {owner_name}'s Social Cart",
                    message=message.strip(),
                    from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@easymarket.com'),
                    recipient_list=[email],
                    fail_silently=False
                )

                email_sent = True

            except Exception as e2:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Error sending invite email: {str(e2)}")
                email_sent = False

    # Send SMS if phone provided (placeholder)
    if phone:
        # TODO: Implement SMS sending
        # For now, just log it
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"SMS invite to {phone}: {invite_link}")

    response_message = 'Invite sent successfully!'
    if email and not email_sent:
        response_message = 'Invite created but email failed to send. Share the link manually.'

    return JsonResponse({
        'success': True,
        'message': response_message,
        'invite_link': invite_link,
        'invite': {
            'id': invite.id,
            'invited_email': invite.invited_email or '',
            'invited_phone': invite.invited_phone or '',
            'expires_at': invite.expires_at.isoformat(),
        }
    })


# =============================================================================
# NEW FUNCTION 1: Delete/Cancel Invitation
# =============================================================================

@login_required
@require_POST
def delete_cart_invite(request, invite_id):
    """
    Delete/cancel a pending invitation
    Only the cart owner can delete invites
    """
    try:
        invite = get_object_or_404(CartInvite, id=invite_id)
        social = invite.social_cart

        # Verify owner
        if social.owner != request.user:
            return JsonResponse({
                'success': False,
                'message': 'Only the cart owner can delete invites'
            }, status=403)

        # Can only delete pending invites
        if invite.status != 'pending':
            return JsonResponse({
                'success': False,
                'message': 'Can only delete pending invitations'
            }, status=400)

        invited_contact = invite.invited_email or invite.invited_phone

        # Delete the invite
        invite.delete()

        # Log activity
        log_cart_activity(
            social=social,
            actor=request.user,
            event="invite_deleted",
            message=f"Invitation to {invited_contact} was deleted",
            payload={"invite_id": str(invite_id)}
        )

        return JsonResponse({
            'success': True,
            'message': 'Invitation deleted successfully'
        })

    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error deleting invite: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': f'Failed to delete invitation: {str(e)}'
        }, status=500)

@login_required
@require_http_methods(["GET", "POST"])
def join_open_social_cart(request, invite_code):
    """
    Join a social cart using invite_code (public/share link).
    - PUBLIC carts: join immediately (joined)
    - INVITE_ONLY carts: create pending request (owner must approve)
    - Browser clicks: redirect to cart with a message (no raw JSON)
    - AJAX: returns JSON (keeps your JS happy)
    """
    social = get_object_or_404(SocialCart, invite_code=invite_code, is_active=True)

    if not social.is_join_allowed_now():
        return _respond(
            request,
            ok=False,
            message="This social cart is not available for joining right now.",
            status_code=403
        )

    # Check if already exists
    existing = social.members.filter(user=request.user).first()
    if existing:
        if existing.status == "joined":
            return _respond(request, ok=False, message="You are already a member of this cart.", status_code=400)

        if existing.status == "pending":
            return _respond(request, ok=False, message="Your request to join is pending approval.", status_code=400)

        if existing.status == "blocked":
            return _respond(request, ok=False, message="You have been blocked from this cart.", status_code=403)

        if existing.status in ("left", "rejected"):
            # Rejoin logic
            with transaction.atomic():
                if social.access_type == SocialCart.ACCESS_INVITE_ONLY:
                    existing.status = "pending"
                    existing.save(update_fields=["status", "updated_at"])

                    # (Optional) mark a pending invite as accepted if it matches this user
                    _mark_matching_invite_accepted(social, request.user)

                    # Notify owner (best-effort)
                    try:
                        send_email_async(
                            subject="New Join Request for Your Social Cart",
                            to_email=social.owner.email,
                            html_template="emails/social_cart/join_request.html",
                            context={
                                "owner_name": social.owner.get_full_name() or social.owner.username,
                                "requester_name": request.user.get_full_name() or request.user.username,
                                "cart_url": request.build_absolute_uri(reverse("marketplace:cart")),
                            }
                        )
                    except Exception:
                        pass

                    try:
                        log_cart_activity(
                            social=social,
                            actor=request.user,
                            event="join_requested",
                            message=f"{request.user.username} requested to rejoin"
                        )
                    except Exception:
                        pass

                    return _respond(
                        request,
                        ok=True,
                        message="Your request to rejoin has been sent to the owner for approval.",
                        status="pending"
                    )
                else:
                    existing.status = "joined"
                    existing.save(update_fields=["status", "updated_at"])

                    PaymentShare.objects.get_or_create(
                        social_cart=social,
                        member=existing,
                        defaults={"percentage": Decimal("0"), "is_active": True}
                    )

                    _mark_matching_invite_accepted(social, request.user)

                    try:
                        log_cart_activity(
                            social=social,
                            actor=request.user,
                            event="member_rejoined",
                            message=f"{request.user.username} rejoined the cart"
                        )
                    except Exception:
                        pass

                    return _respond(request, ok=True, message="You rejoined the social cart!", status="joined")

    # New member
    with transaction.atomic():
        if social.access_type == SocialCart.ACCESS_INVITE_ONLY:
            member, created = CartMember.objects.get_or_create(
                social_cart=social,
                user=request.user,
                defaults={"role": "member", "status": "pending"}
            )
            if not created and member.status != "pending":
                member.status = "pending"
                member.save(update_fields=["status", "updated_at"])

            _mark_matching_invite_accepted(social, request.user)

            # Notify owner (best-effort)
            try:
                send_email_async(
                    subject="New Join Request for Your Social Cart",
                    to_email=social.owner.email,
                    html_template="emails/social_cart/join_request.html",
                    context={
                        "owner_name": social.owner.get_full_name() or social.owner.username,
                        "requester_name": request.user.get_full_name() or request.user.username,
                        "cart_url": request.build_absolute_uri(reverse("marketplace:cart")),
                    }
                )
            except Exception:
                pass

            try:
                log_cart_activity(
                    social=social,
                    actor=request.user,
                    event="join_requested",
                    message=f"{request.user.username} requested to join"
                )
            except Exception:
                pass

            return _respond(
                request,
                ok=True,
                message="Your request to join has been sent to the owner for approval.",
                status="pending"
            )

        # PUBLIC cart - join immediately
        member, created = CartMember.objects.get_or_create(
            social_cart=social,
            user=request.user,
            defaults={"role": "member", "status": "joined"}
        )
        if not created and member.status != "joined":
            member.status = "joined"
            member.save(update_fields=["status", "updated_at"])

        PaymentShare.objects.get_or_create(
            social_cart=social,
            member=member,
            defaults={"percentage": Decimal("0"), "is_active": True}
        )

        _mark_matching_invite_accepted(social, request.user)

        try:
            log_cart_activity(
                social=social,
                actor=request.user,
                event="member_joined",
                message=f"{request.user.username} joined the cart"
            )
        except Exception:
            pass

        return _respond(request, ok=True, message="You joined the social cart!", status="joined")


def _mark_matching_invite_accepted(social, user):
    """
    Best-effort: if owner sent an invite to this user's email/phone, mark it accepted,
    so 'Invites Sent' doesn't stay pending.
    """
    try:
        email = (getattr(user, "email", "") or "").strip()
        phone = (getattr(user, "phone", "") or "").strip()  # adjust if your phone field is elsewhere

        qs = CartInvite.objects.filter(social_cart=social, status="pending")
        if email:
            qs = qs.filter(invited_email__iexact=email)
        elif phone:
            qs = qs.filter(invited_phone__iexact=phone)
        else:
            return

        inv = qs.order_by("-created_at").first()
        if inv:
            inv.status = "accepted"
            inv.accepted_by = user
            inv.save(update_fields=["status", "accepted_by"])
    except Exception:
        pass

@login_required
@require_POST
def rejoin_social_cart(request):
    """
    Rejoin a social cart after leaving.

    FIXED:
    - Works even when user is NOT joined (find cart where user is left/temporarily_left)
    - Browser POST redirects to cart with messages (no raw JSON)
    - AJAX calls still get JSON
    """
    try:
        # ✅ DO NOT use _resolve_active_social_for here (it filters joined members only)
        social = (
            SocialCart.objects
            .filter(
                is_active=True,
                status__in=["open", "checkout"],
                members__user=request.user,
                members__status__in=["left", "temporarily_left"]
            )
            .select_related("cart", "owner")
            .order_by("-created_at")
            .first()
        )

        if not social:
            return _respond(request, False, "No social cart available to rejoin.", 404)

        with transaction.atomic():
            member = social.members.select_for_update().filter(user=request.user).first()
            if not member:
                return _respond(request, False, "You were never a member of this cart.", 404)

            if member.status == "joined":
                return _respond(request, False, "You are already a member of this cart.", 400)

            can_rejoin = (
                member.status in ("temporarily_left", "left") or
                getattr(member, "is_original_owner", False)
            )
            if not can_rejoin:
                return _respond(
                    request,
                    False,
                    "You cannot rejoin this cart. Please request a new invitation.",
                    403
                )

            is_original_owner = bool(getattr(member, "is_original_owner", False))

            # ✅ restore ownership only for invite_only carts
            if is_original_owner and social.access_type == "invite_only":
                current_owner = social.owner
                current_owner_member = social.members.filter(user=current_owner).first()

                social.owner = request.user
                social.save(update_fields=["owner", "updated_at"])

                member.role = "owner"
                member.status = "joined"
                member.save(update_fields=["role", "status", "updated_at"])

                if current_owner_member and current_owner_member.id != member.id:
                    current_owner_member.role = "member"
                    current_owner_member.save(update_fields=["role", "updated_at"])

                # Ensure payment share exists
                PaymentShare.objects.get_or_create(
                    social_cart=social,
                    member=member,
                    defaults={"percentage": Decimal("0"), "is_active": True}
                )

                try:
                    log_cart_activity(
                        social=social,
                        actor=request.user,
                        event="ownership_restored",
                        message=f"Original owner {request.user.username} rejoined - ownership restored",
                        payload={
                            "previous_temp_owner_id": getattr(current_owner, "id", None),
                            "restored_owner_id": request.user.id
                        }
                    )
                except Exception:
                    pass

                try:
                    send_email_async(
                        subject="Cart Ownership Restored to Original Owner",
                        to_email=current_owner.email,
                        html_template="emails/social_cart/ownership_restored.html",
                        context={
                            "recipient_name": current_owner.get_full_name() or current_owner.username,
                            "original_owner": request.user.get_full_name() or request.user.username,
                            "cart_url": request.build_absolute_uri(reverse("marketplace:cart"))
                        }
                    )
                except Exception:
                    pass

                return _respond(
                    request,
                    True,
                    "Welcome back! Your ownership has been restored.",
                    ownership_restored=True,
                    role="owner"
                )

            # ✅ Regular rejoin
            member.status = "joined"
            if not member.role or member.role == "owner":
                member.role = "member"
            member.save(update_fields=["status", "role", "updated_at"])

            PaymentShare.objects.get_or_create(
                social_cart=social,
                member=member,
                defaults={"percentage": Decimal("0"), "is_active": True}
            )

            try:
                log_cart_activity(
                    social=social,
                    actor=request.user,
                    event="member_rejoined",
                    message=f"{request.user.username} rejoined the cart"
                )
            except Exception:
                pass

            return _respond(request, True, "You have rejoined the social cart!", role=member.role)

    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error in rejoin_social_cart: {str(e)}", exc_info=True)
        return _respond(request, False, f"An error occurred: {str(e)}", 500)


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
    Owner approves a pending member request
    """
    social = _resolve_active_social_for(request.user)

    if not social:
        return JsonResponse({
            'success': False,
            'message': 'No active social cart found'
        }, status=404)

    if social.owner != request.user:
        return JsonResponse({
            'success': False,
            'message': 'Only the owner can approve members'
        }, status=403)

    member = get_object_or_404(CartMember, id=member_id, social_cart=social)

    if member.status not in ('pending', 'blocked'):
        return JsonResponse({
            'success': False,
            'message': f'This member cannot be admitted from status: {member.status}'
        }, status=400)

    with transaction.atomic():
        member.status = 'joined'
        member.save(update_fields=['status', 'updated_at'])

        # Create payment share
        PaymentShare.objects.get_or_create(
            social_cart=social,
            member=member,
            defaults={'percentage': Decimal('0'), 'is_active': True}
        )

        # Notify approved member
        try:
            send_email_async(
                subject="You've Been Approved to Join the Social Cart!",
                to_email=member.user.email,
                html_template="emails/social_cart/approved.html",
                context={
                    "recipient_name": member.user.get_full_name() or member.user.username,
                    "owner_name": social.owner.get_full_name() or social.owner.username,
                    "cart_url": request.build_absolute_uri(reverse("marketplace:cart"))
                }
            )
        except Exception:
            pass

        # Log activity
        try:
            log_cart_activity(
                social=social,
                actor=request.user,
                event="member_approved",
                message=f"{member.user.username} was approved by {request.user.username}"
            )
        except Exception:
            pass

    return JsonResponse({
        'success': True,
        'message': f'{member.user.username} has been approved',
        'member_id': member.id
    })


@login_required
@require_POST
def reject_member(request, member_id):
    """
    Owner rejects a pending member request
    """
    social = _resolve_active_social_for(request.user)

    if not social:
        return JsonResponse({
            'success': False,
            'message': 'No active social cart found'
        }, status=404)

    if social.owner != request.user:
        return JsonResponse({
            'success': False,
            'message': 'Only the owner can reject members'
        }, status=403)

    member = get_object_or_404(CartMember, id=member_id, social_cart=social)

    if member.status != 'pending':
        return JsonResponse({
            'success': False,
            'message': 'This member is not pending approval'
        }, status=400)

    member.status = 'rejected'
    member.save(update_fields=['status', 'updated_at'])

    # Log activity
    try:
        log_cart_activity(
            social=social,
            actor=request.user,
            event="member_rejected",
            message=f"{member.user.username} was rejected by {request.user.username}"
        )
    except Exception:
        pass

    return JsonResponse({
        'success': True,
        'message': f'{member.user.username} has been rejected',
        'member_id': member.id
    })

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
    Leave a social cart

    ENHANCED with ownership transfer logic and restoration support:
    - If OWNER leaves PRIVATE cart: Transfer ownership to next member (can restore later)
    - If OWNER leaves PUBLIC cart: Close cart and kick everyone out
    - If MEMBER leaves: Just remove them
    """
    try:
        social = _resolve_active_social_for(request.user)

        if not social:
            return JsonResponse({
                'success': False,
                'message': 'No active social cart found'
            }, status=404)

        with transaction.atomic():
            member = social.members.filter(user=request.user).first()

            if not member:
                return JsonResponse({
                    'success': False,
                    'message': 'You are not a member of this cart'
                }, status=404)

            is_owner = (social.owner == request.user or member.role == 'owner')
            is_original_owner = getattr(member, 'is_original_owner', False)

            # ========================================
            # CASE 1: OWNER LEAVING
            # ========================================
            if is_owner:

                # PRIVATE CART: Transfer ownership to next member (with restoration support)
                if social.access_type == 'invite_only':
                    # Find next member to become owner (oldest joined member)
                    next_owner_member = (
                        social.members
                        .filter(status='joined')
                        .exclude(user=request.user)
                        .order_by('joined_at')
                        .first()
                    )

                    if next_owner_member:
                        # Transfer ownership
                        old_owner_name = request.user.get_full_name() or request.user.username
                        new_owner_name = next_owner_member.user.get_full_name() or next_owner_member.user.username

                        # ✅ Store original owner if not already stored (for restoration)
                        if not hasattr(social, 'original_owner') or not social.original_owner:
                            social.original_owner = request.user

                        # Update social cart owner
                        social.owner = next_owner_member.user
                        social.save(update_fields=['owner', 'original_owner', 'updated_at'])

                        # Update member role
                        next_owner_member.role = 'owner'
                        next_owner_member.save(update_fields=['role', 'updated_at'])

                        # ✅ Mark old owner as temporarily_left (not fully left) so they can rejoin
                        member.role = 'member'
                        member.status = 'temporarily_left'  # ✅ CHANGED from 'left'
                        member.save(update_fields=['role', 'status', 'updated_at'])

                        # Log activity
                        log_cart_activity(
                            social=social,
                            actor=request.user,
                            event="ownership_transferred",
                            message=f"Ownership temporarily transferred from {old_owner_name} to {new_owner_name}",  # ✅ Added "temporarily"
                            payload={
                                "old_owner_id": request.user.id,
                                "new_owner_id": next_owner_member.user.id,
                                "is_original_owner": is_original_owner,  # ✅ Track if original owner
                                "can_restore": True  # ✅ Indicates restoration possible
                            }
                        )

                        # Send email to new owner
                        try:
                            send_email_async(
                                subject="You're now the Social Cart Owner",
                                to_email=next_owner_member.user.email,
                                html_template="emails/social_cart/ownership_transferred.html",
                                context={
                                    "recipient_name": new_owner_name,
                                    "previous_owner": old_owner_name,
                                    "social_cart": social,
                                    "is_temporary": True,  # ✅ NEW: Indicates temporary ownership
                                    "cart_url": request.build_absolute_uri(reverse('marketplace:cart'))
                                }
                            )
                        except Exception:
                            # Fallback to simple email
                            try:
                                from django.core.mail import send_mail
                                from django.conf import settings

                                message = f"""
Hi {new_owner_name},

{old_owner_name} has left the social cart and transferred ownership to you.

As the new owner, you can now:
- Manage members (approve/remove)
- Send invitations
- Change cart settings
- Close the cart when ready

Note: If {old_owner_name} returns, ownership will be restored to them.

View your cart: {request.build_absolute_uri(reverse('marketplace:cart'))}

EasyMarket Team
                                """

                                send_mail(
                                    subject="You're now the Social Cart Owner",
                                    message=message.strip(),
                                    from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@easymarket.com'),
                                    recipient_list=[next_owner_member.user.email],
                                    fail_silently=True
                                )
                            except Exception:
                                pass

                        # Move owner's items to their personal cart
                        social_items = social.cart.items.filter(
                            cart_type='social',
                            added_by=request.user
                        )
                        social_items.update(cart_type='normal')

                        return JsonResponse({
                            'success': True,
                            'message': f'You left the cart. Ownership transferred to {new_owner_name}.',
                            'ownership_transferred': True,
                            'new_owner': new_owner_name,
                            'can_rejoin': True  # ✅ NEW: Frontend can show "Rejoin" button
                        })

                    else:
                        # No other members - close the cart
                        social.is_active = False
                        social.status = 'closed'
                        social.save(update_fields=['is_active', 'status', 'updated_at'])

                        member.status = 'left'
                        member.save(update_fields=['status', 'updated_at'])

                        # Move items to personal cart
                        social.cart.items.filter(cart_type='social').update(cart_type='normal')

                        log_cart_activity(
                            social=social,
                            actor=request.user,
                            event="cart_closed",
                            message="Owner left and cart was closed (no other members)"
                        )

                        return JsonResponse({
                            'success': True,
                            'message': 'Cart closed. You were the only member.',
                            'cart_closed': True
                        })

                # PUBLIC CART: Close cart and kick everyone out
                else:  # access_type == 'public'
                    # Get all members
                    all_members = social.members.filter(status='joined').select_related('user')

                    # Close the cart
                    social.is_active = False
                    social.status = 'closed'
                    social.save(update_fields=['is_active', 'status', 'updated_at'])

                    # Mark all members as kicked
                    social.members.all().update(status='left')

                    # Move all items to respective personal carts
                    social_items = social.cart.items.filter(cart_type='social')
                    for item in social_items:
                        item.cart_type = 'normal'
                        # Ensure item is in the correct user's cart
                        if item.added_by:
                            user_cart, _ = Cart.objects.get_or_create(user=item.added_by)
                            item.cart = user_cart
                        item.save(update_fields=['cart_type', 'cart'])

                    # Log activity
                    log_cart_activity(
                        social=social,
                        actor=request.user,
                        event="cart_closed_by_owner",
                        message="Owner left public cart - all members removed",
                        payload={"members_count": all_members.count()}
                    )

                    # Notify all members
                    owner_name = request.user.get_full_name() or request.user.username

                    for member_obj in all_members:
                        if member_obj.user == request.user:
                            continue  # Skip owner

                        try:
                            member_name = member_obj.user.get_full_name() or member_obj.user.username

                            send_email_async(
                                subject="Social Cart Has Been Closed",
                                to_email=member_obj.user.email,
                                html_template="emails/social_cart/cart_closed.html",
                                context={
                                    "recipient_name": member_name,
                                    "owner_name": owner_name,
                                    "cart_url": request.build_absolute_uri(reverse('marketplace:cart'))
                                }
                            )
                        except Exception:
                            # Fallback
                            try:
                                from django.core.mail import send_mail
                                from django.conf import settings

                                message = f"""
Hi {member_name},

The social cart owned by {owner_name} has been closed.

Your items have been moved back to your personal cart.

View your cart: {request.build_absolute_uri(reverse('marketplace:cart'))}

EasyMarket Team
                                """

                                send_mail(
                                    subject="Social Cart Has Been Closed",
                                    message=message.strip(),
                                    from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@easymarket.com'),
                                    recipient_list=[member_obj.user.email],
                                    fail_silently=True
                                )
                            except Exception:
                                pass

                    return JsonResponse({
                        'success': True,
                        'message': 'Cart closed. All members have been removed.',
                        'cart_closed': True,
                        'members_notified': all_members.count() - 1  # Excluding owner
                    })

            # ========================================
            # CASE 2: REGULAR MEMBER LEAVING
            # ========================================
            else:
                # Mark as left
                member.status = 'left'
                member.save(update_fields=['status', 'updated_at'])

                # Move their items to their personal cart
                social_items = social.cart.items.filter(
                    cart_type='social',
                    added_by=request.user
                )
                social_items.update(cart_type='normal')

                # Log activity
                log_cart_activity(
                    social=social,
                    actor=request.user,
                    event="member_left",
                    message=f"{request.user.username} left the cart"
                )

                # Recalculate shares
                social.recalc_members_due()

                return JsonResponse({
                    'success': True,
                    'message': 'You have left the social cart. Your items were moved to your personal cart.'
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
    Returns partial HTML fragments for the Social Cart.

    Modes:
      - ?partial=members  -> marketplace/partials/_social_members_strip.html
      - default / ?partial=cart -> marketplace/partials/_social_cart_block.html

    Safe to poll without reloading the main page.
    """
    partial = (request.GET.get("partial") or "").strip().lower()

    social = _resolve_active_social_for(request.user)

    # -------------------------
    # PARTIAL: MEMBERS STRIP ONLY
    # -------------------------
    if partial == "members":
        if not social:
            # Return empty content (JS can replace safely)
            return render(request, "marketplace/partials/_social_members_strip.html", {
                "social_members": []
            })

        social_members = (
            social.members
            .filter(status__in=["joined", "blocked"])
            .select_related("user")
            .order_by("id")
        )

        return render(request, "marketplace/partials/_social_members_strip.html", {
            "social_members": social_members
        })

    # -------------------------
    # DEFAULT: FULL SOCIAL CART BLOCK
    # -------------------------
    if not social:
        return render(request, "marketplace/partials/_social_cart_block.html", {
            "is_social_active": False
        })

    me = social.members.filter(user=request.user).first()
    is_blocked = bool(me and me.status == "blocked")
    is_owner = (social.owner_id == request.user.id) or bool(me and me.role == "owner")

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
        "social_total": social.total(),

        # ✅ If your main template uses social_members, include it too:
        "social_members": members,
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

@login_required
@require_GET
def social_cart_items_fragment(request):
    social = _resolve_active_social_for(request.user)
    if not social:
        return HttpResponse("")

    cart = social.cart
    social_items = (
        cart.items
        .filter(cart_type="social")
        .select_related("product", "added_by")
        .order_by("-id")
    )

    return render(
        request,
        "marketplace/partials/_social_cart_items.html",
        {"social_items": social_items, "social": social}
    )

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
                reverse('marketplace:accept_cart_invite', kwargs={'code': social.invite_code})
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
                link = request.build_absolute_uri(reverse("marketplace:cart"))  # adjust if your cart page url name differs
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