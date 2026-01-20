from decimal import Decimal, InvalidOperation
import uuid
import json

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
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


@transaction.atomic
def ensure_social_cart(cart, user) -> SocialCart:
    """
    Idempotently ensure a SocialCart exists for this Cart,
    plus owner membership and default share.
    """
    social = getattr(cart, "social", None)
    if social and social.is_active and social.status in ("open", "checkout"):
        return social

    if social and not social.is_active:
        # revive (optional) — or create a new one
        social.is_active = True
        social.status = "open"
        social.save(update_fields=["is_active", "status"])
        return social

    social = SocialCart.objects.create(cart=cart, owner=user)

    owner_member, _ = CartMember.objects.get_or_create(
        social_cart=social,
        user=user,
        defaults={"role": "owner", "status": "joined"}
    )

    PaymentShare.objects.get_or_create(
        social_cart=social,
        member=owner_member,
        defaults={"percentage": Decimal("100")}
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
    cart, _ = Cart.objects.get_or_create(user=request.user)
    social = ensure_social_cart(cart, request.user)
    return JsonResponse({
        "success": True,
        "social_id": social.id,
        "invite_link": _abs_uri(request, "join_open_social_cart", invite_code=social.invite_code),
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
    Hardened:
    - validates social_id
    - ensures requester is owner
    - never relies on localStorage/social_id only
    """
    social_id = request.POST.get("social_id")

    if not social_id:
        # allow fallback: use user's active social
        social = _resolve_active_social_for(request.user)
        if not social:
            return _json_error("No active social cart. Please create one first.", 400)
    else:
        social = SocialCart.objects.filter(
            id=social_id,
            is_active=True,
            status__in=["open", "checkout"]
        ).select_related("owner").first()
        if not social:
            return _json_error("Invalid or expired social cart. Please recreate.", 400)

    # owner check
    if social.owner_id != request.user.id:
        return _json_error("Only the owner can invite members.", 403)

    if _not_mutable(social):
        return _json_error("Cart is not accepting new members right now.", 409)

    email = (request.POST.get("email") or "").strip() or None
    phone = (request.POST.get("phone") or "").strip() or None

    if not email and not phone:
        return _json_error("Please enter an email or phone number.", 400)

    inv = CartInvite.objects.create(
        social_cart=social,
        inviter=request.user,
        invited_email=email,
        invited_phone=phone,
        expires_at=timezone.now() + timezone.timedelta(days=7),
    )

    invite_link = _abs_uri(request, "accept_cart_invite", code=inv.code)

    # send email if email provided
    if email:
        ctx = {
            "subject": "EasyMarket Social Cart Invite",
            "inviter_name": request.user.get_full_name() or request.user.username,
            "owner_name": social.owner.get_full_name() or social.owner.username,
            "social_status": social.status,
            "invite_link": invite_link,
            "now": timezone.now(),
        }
        send_email_async(
            subject="You're invited to a Social Cart (EasyMarket)",
            to_email=email,
            html_template="emails/social_cart/invite.html",
            context=ctx,
        )

    return JsonResponse({
        "success": True,
        "invite_link": _abs_uri(request, "accept_cart_invite", code=inv.code),
    })


@login_required
def join_open_social_cart(request, invite_code):
    """
    Public share link join (open).
    If you want invitation-only groups, change defaults status to 'pending'
    and require owner approval.
    """
    social = SocialCart.objects.filter(
        invite_code=invite_code, is_active=True, status__in=["open", "checkout"]
    ).first()
    if not social:
        return redirect("marketplace:cart_view")

    member, _ = CartMember.objects.get_or_create(
        social_cart=social, user=request.user,
        defaults={"role": "editor", "status": "joined"}
    )

    PaymentShare.objects.get_or_create(social_cart=social, member=member)
    social.recalc_members_due()
    return redirect("marketplace:cart_view")


@login_required
def accept_cart_invite(request, code):
    inv = CartInvite.objects.filter(code=code).select_related("social_cart").first()
    if not inv:
        return _json_error("Invite not found.", 404)

    if not inv.is_valid():
        return _json_error("Invite expired.", 400)

    social = inv.social_cart
    if _not_mutable(social):
        return _json_error("Cart not accepting new members.", 409)

    member, _ = CartMember.objects.get_or_create(
        social_cart=social, user=request.user,
        defaults={"role": "editor", "status": "pending"}  # ✅ pending so owner can approve
    )
    owner_email = getattr(social.owner, "email", "") or ""
    if owner_email:
        manage_link = request.build_absolute_uri(reverse("marketplace:cart_view"))
        ctx = {
            "subject": "Invite Accepted - Approval Needed",
            "member_name": request.user.get_full_name() or request.user.username,
            "manage_link": manage_link,
            "now": timezone.now(),
        }
        send_email_async(
            subject="Social Cart: Invite accepted (approval required)",
            to_email=owner_email,
            html_template="emails/social_cart/accepted_pending.html",
            context=ctx,
        )

    inv.accepted_by = request.user
    inv.status = "accepted"
    inv.save(update_fields=["accepted_by", "status"])

    PaymentShare.objects.get_or_create(social_cart=social, member=member)
    social.recalc_members_due()
    return redirect("marketplace:cart_view")


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
    Owner blocks an existing joined member from the social cart.
    Blocked members cannot rejoin unless unblocked.
    """
    member = CartMember.objects.select_related("social_cart", "user").filter(id=member_id).first()
    if not member:
        return _json_error("Member not found.", 404)

    social = member.social_cart

    if social.owner_id != request.user.id:
        return _json_error("Only the owner can block members.", 403)

    if member.user_id == social.owner_id:
        return _json_error("Owner cannot be blocked.", 400)

    if _not_mutable(social):
        return _json_error("Cart membership cannot be changed now.", 409)

    if member.status == "blocked":
        return JsonResponse({"success": True, "message": "Member is already blocked."})

    # Remove member's items from cart
    CartItem.objects.filter(cart=social.cart, added_by=member.user).delete()

    # Deactivate payment share
    PaymentShare.objects.filter(social_cart=social, member=member).update(is_active=False)

    # Set status to blocked
    member.status = "blocked"
    member.save(update_fields=["status"])

    # Send notification email
    member_email = getattr(member.user, "email", "") or ""
    if member_email:
        ctx = {
            "subject": "Removed from Social Cart",
            "owner_name": social.owner.get_full_name() or social.owner.username,
            "now": timezone.now(),
        }
        send_email_async(
            subject="You were removed from a Social Cart",
            to_email=member_email,
            html_template="emails/social_cart/blocked.html",
            context=ctx,
        )

    social.recalc_members_due()
    return JsonResponse({"success": True, "message": "Member blocked successfully."})


@login_required
@require_POST
def leave_cart(request):
    social_id = request.POST.get("social_id")
    if not social_id:
        return _json_error("social_id is required.", 400)

    social = SocialCart.objects.filter(id=social_id, is_active=True).first()
    if not social:
        return _json_error("Invalid social cart.", 400)

    if _not_mutable(social):
        return _json_error("Cart membership cannot be changed now.", 409)

    member = CartMember.objects.filter(social_cart=social, user=request.user).first()
    if not member:
        return _json_error("You are not a member of this social cart.", 403)

    PaymentShare.objects.filter(social_cart=social, member=member).update(is_active=False)

    member.status = "left"
    member.save(update_fields=["status"])

    # owner leaving: assign replacement
    if member.role == "owner":
        replacement = social.members.filter(status="joined").exclude(id=member.id).order_by("joined_at").first()
        if replacement:
            replacement.role = "owner"
            replacement.save(update_fields=["role"])
            social.owner_id = replacement.user_id
            social.save(update_fields=["owner"])
        else:
            social.status = "cancelled"
            social.is_active = False
            social.save(update_fields=["status", "is_active"])

    social.recalc_members_due()
    return JsonResponse({"success": True, "message": "You left the cart.", "social_status": social.status})


@login_required
@require_POST
def remove_member(request, member_id):
    member = CartMember.objects.select_related("social_cart", "user").filter(id=member_id).first()
    if not member:
        return _json_error("Member not found.", 404)

    social = member.social_cart

    if social.owner_id != request.user.id:
        return _json_error("Only the owner can remove members.", 403)

    if member.user_id == social.owner_id:
        return _json_error("Owner cannot be removed.", 400)

    if _not_mutable(social):
        return _json_error("Cart membership cannot be changed now.", 409)

    # ✅ Remove member's items too (requires CartItem.added_by)
    CartItem.objects.filter(cart=social.cart, added_by=member.user).delete()

    PaymentShare.objects.filter(social_cart=social, member=member).update(is_active=False)
    member.delete()

    # Send removal email
    member_email = getattr(member.user, "email", "") or ""
    if member_email:
        ctx = {
            "subject": "Removed from Social Cart",
            "now": timezone.now(),
        }
        send_email_async(
            subject="You were removed from a Social Cart",
            to_email=member_email,
            html_template="emails/social_cart/removed.html",
            context=ctx,
        )

    social.recalc_members_due()
    return JsonResponse({"success": True, "message": "Member removed."})


# ---------- Live endpoint (fixes your 404 spam) ----------

@login_required
@require_GET
def social_cart_live(request):
    """
    GET /cart/social/live/?social_id=1&since=0
    - Never raises 404 (returns JSON errors)
    - Validates membership
    - Returns activities list (basic events)
    """
    social_id = request.GET.get("social_id")
    since = request.GET.get("since") or "0"

    try:
        since_id = int(since)
    except Exception:
        since_id = 0

    if not social_id:
        return _json_error("social_id is required.", 400)

    social = SocialCart.objects.filter(
        id=social_id, is_active=True, status__in=["open", "checkout"]
    ).select_related("cart", "owner").first()

    if not social:
        return _json_error("Invalid social cart.", 400)

    # membership check
    if not CartMember.objects.filter(social_cart=social, user=request.user, status__in=["joined", "pending"]).exists():
        return _json_error("You are not a member of this social cart.", 403)

    # ✅ Basic activity feed (no custom activity model needed):
    # We'll show:
    # - latest members joined
    # - latest contributions
    activities = []

    # Members joined (using id > since_id as a cheap cursor)
    members = (CartMember.objects
               .filter(social_cart=social, id__gt=since_id)
               .select_related("user")
               .order_by("id")[:20])

    for m in members:
        activities.append({
            "id": m.id,
            "type": "member",
            "message": f"{m.user.get_full_name() or m.user.username} joined (status: {m.status}).",
            "ts": getattr(m, "joined_at", None).isoformat() if getattr(m, "joined_at", None) else "",
        })

    # Contributions (also cursor by id)
    contribs = (Contribution.objects
                .filter(social_cart=social, id__gt=since_id)
                .select_related("member__user")
                .order_by("id")[:20])

    for c in contribs:
        uname = c.member.user.get_full_name() or c.member.user.username
        activities.append({
            "id": c.id,
            "type": "payment",
            "message": f"{uname} paid {c.amount} ({c.provider}) — {c.status}.",
            "ts": c.created_at.isoformat() if getattr(c, "created_at", None) else "",
        })

    # sort by id ascending, compute latest_id
    activities.sort(key=lambda x: x["id"])
    latest_id = activities[-1]["id"] if activities else since_id

    # totals snapshot (optional)
    item_count = CartItem.objects.filter(cart=social.cart).aggregate(s=Sum("quantity"))["s"] or 0

    return JsonResponse({
        "success": True,
        "activities": activities,
        "latest_id": latest_id,
        "item_count": int(item_count),
        "social_status": social.status,
    })


# ---------- Split Mode ----------

@require_POST
@login_required
def set_split_mode(request):
    social = _resolve_active_social_for(request.user)
    if not social:
        return _json_error("No active social cart", 404)

    if social.owner_id != request.user.id:
        return _json_error("Only the owner can change split mode", 403)

    mode = (request.POST.get("mode") or "").strip()
    allocations_raw = request.POST.get("allocations")
    payer_member_id = request.POST.get("payer_member_id")

    try:
        if mode == SocialCart.SPLIT_BY_ITEMS:
            social.set_split_mode(SocialCart.SPLIT_BY_ITEMS)

        elif mode == SocialCart.SPLIT_BY_PERCENT:
            try:
                allocations = json.loads(allocations_raw or "{}")
            except Exception:
                allocations = {}

            norm = {}
            for k, v in allocations.items():
                try:
                    mid = int(k)
                    pct = Decimal(str(v))
                except Exception:
                    continue
                norm[mid] = pct

            social.set_split_mode(SocialCart.SPLIT_BY_PERCENT, allocations=norm)

        elif mode == SocialCart.SPLIT_SINGLE_PAYER:
            if not payer_member_id:
                return _json_error("payer_member_id is required", 400)
            social.set_split_mode(SocialCart.SPLIT_SINGLE_PAYER, payer_member_id=int(payer_member_id))

        else:
            return _json_error("Invalid mode", 400)

        shares = list(
            social.payment_shares.filter(is_active=True)
            .select_related("member", "member__user")
            .values("member_id", "member__user__username", "fixed_amount", "percentage", "items_total_amount",
                    "amount_due")
        )

        return JsonResponse({
            "success": True,
            "mode": social.split_mode,
            "single_payer_id": social.single_payer_id,
            "shares": shares,
            "message": "Split mode updated"
        })

    except ValueError as e:
        return _json_error(str(e), 400)
    except Exception as e:
        return _json_error(f"Error: {e}", 500)


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


@require_POST
@login_required
@transaction.atomic
def start_my_payment(request):
    """
    Create an order ONLY for what the current user must pay.
    Prevents duplicate OrderItem errors.
    """
    social = _resolve_active_social_for(request.user)
    if not social:
        return _json_error("No active social cart", 404)

    member = CartMember.objects.filter(
        social_cart=social,
        user=request.user,
        status="joined"
    ).first()

    if not member:
        return _json_error("You are not part of this social cart", 403)

    cart = social.cart
    split_mode = social.split_mode

    # -----------------------------
    # Determine payable items
    # -----------------------------
    cart_items = CartItem.objects.filter(cart=cart)

    if split_mode == SocialCart.SPLIT_BY_ITEMS:
        payable_items = cart_items.filter(added_by=request.user)

    elif split_mode == SocialCart.SPLIT_SINGLE_PAYER:
        if social.single_payer_id != member.id:
            return _json_error("You are not the selected payer", 403)
        payable_items = cart_items

    elif split_mode == SocialCart.SPLIT_BY_PERCENT:
        share = PaymentShare.objects.filter(
            social_cart=social,
            member=member,
            is_active=True
        ).first()

        if not share or not share.amount_due or share.amount_due <= 0:
            return _json_error("Your share is not set", 400)

        payable_items = cart_items  # order contains summary only
    else:
        return _json_error("Invalid split mode", 400)

    if not payable_items.exists():
        return _json_error("You have nothing to pay for", 400)

    # -----------------------------
    # Create Order
    # -----------------------------
    order = Order.objects.create(
        buyer=request.user,
        is_social=True,
        social_cart=social,
    )

    subtotal = Decimal("0")

    for item in payable_items:
        # IMPORTANT: avoid duplicate OrderItem
        OrderItem.objects.create(
            order=order,
            product=item.product,
            quantity=item.quantity,
            price=item.product.price,
            selected_features=item.selected_features,
        )

        subtotal += item.product.price * item.quantity

    # -----------------------------
    # Adjust total for percentage
    # -----------------------------
    if split_mode == SocialCart.SPLIT_BY_PERCENT:
        subtotal = share.amount_due

    order.subtotal = subtotal
    order.total = subtotal
    order.save(update_fields=["subtotal", "total"])

    # -----------------------------
    # Mark contribution
    # -----------------------------
    Contribution.objects.create(
        social_cart=social,
        member=member,
        amount=subtotal,
        status="initiated",
        provider="checkout"
    )

    return JsonResponse({
        "success": True,
        "order_id": order.id,
        "redirect": reverse("orders:order_detail", args=[order.id]),
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