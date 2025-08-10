from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

User = get_user_model()


@login_required
def dashboard(request):
    from .models import Ticket

    # Staff see all; customers see theirs
    qs = Ticket.objects.all() if request.user.is_staff else Ticket.objects.filter(customer=request.user)

    status = request.GET.get("status")
    if status:
        qs = qs.filter(status=status)

    priority = request.GET.get("priority")
    if priority:
        qs = qs.filter(priority=priority)

    topic = request.GET.get("topic")
    if topic:
        qs = qs.filter(topic__slug=topic)

    qs = qs.order_by("-updated_at")

    page = Paginator(qs, 20).get_page(request.GET.get("page"))

    ctx = {"page": page}
    return render(request, "helpdesk/dashboard.html", ctx)


@login_required
def ticket_list(request):
    from .models import Ticket

    qs = Ticket.objects.filter(customer=request.user).order_by("-updated_at")
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(request, "helpdesk/ticket_list.html", {"page": page})


@login_required
def ticket_detail(request, pk):
    from .models import Ticket
    from .forms import TicketReplyForm, TicketAssignForm

    ticket = get_object_or_404(Ticket, pk=pk)

    # Authorization: customers can view their own; staff can view all
    if not request.user.is_staff and ticket.customer_id != request.user.id:
        return HttpResponseForbidden("Not allowed")

    reply_form = TicketReplyForm()
    assign_form = None

    staff_users = User.objects.none()
    seller_users = User.objects.none()

    if request.user.is_staff:
        assign_form = TicketAssignForm(
            initial={
                "assignee_id": ticket.assignee_id,
                "status": ticket.status,
                "priority": ticket.priority,
            }
        )
        # Fetch staff & sellers for dropdown
        staff_users = (
            User.objects.filter(is_staff=True)
            .only("id", "first_name", "last_name", "username")
            .order_by("first_name", "last_name", "username")
        )
        # Adjust group name if yours is different (e.g., "StoreOwners")
        seller_users = (
            User.objects.filter(is_seller=True)
            .only("id", "first_name", "last_name", "username")
            .order_by("first_name", "last_name", "username")
            .distinct()
        )

    return render(
        request,
        "helpdesk/ticket_detail.html",
        {
            "ticket": ticket,
            "reply_form": reply_form,
            "assign_form": assign_form,
            "staff_users": staff_users,
            "seller_users": seller_users,
        },
    )


@login_required
@transaction.atomic
def ticket_create(request):
    from .models import Ticket
    from .forms import TicketCreateForm
    from .utils import notify_new_ticket

    if request.method == "POST":
        form = TicketCreateForm(request.POST)
        if form.is_valid():
            ticket: Ticket = form.save(commit=False)
            ticket.customer = request.user
            ticket.save()
            form.save_m2m()
            notify_new_ticket(ticket)
            messages.success(request, f"Ticket #{ticket.id} created.")
            return redirect("helpdesk:ticket_detail", pk=ticket.pk)
    else:
        form = TicketCreateForm()

    return render(request, "helpdesk/ticket_create.html", {"form": form})


@login_required
@require_POST
@transaction.atomic
def ticket_reply(request, pk):
    from .models import Ticket, TicketMessage, Attachment, TicketEvent
    from .forms import TicketReplyForm

    ticket = get_object_or_404(Ticket, pk=pk)
    if not request.user.is_staff and ticket.customer_id != request.user.id:
        return HttpResponseForbidden("Not allowed")

    form = TicketReplyForm(request.POST, request.FILES)
    if form.is_valid():
        msg = TicketMessage.objects.create(
            ticket=ticket,
            author=request.user,
            body=form.cleaned_data["body"],
            is_internal=form.cleaned_data.get("is_internal", False) and request.user.is_staff,
        )
        for f in request.FILES.getlist("attachments"):
            Attachment.objects.create(message=msg, file=f)

        # If staff replies, set status appropriately
        if request.user.is_staff and not msg.is_internal and ticket.status == "pending":
            ticket.status = "open"
            ticket.save(update_fields=["status", "updated_at"])
            TicketEvent.objects.create(ticket=ticket, actor=request.user, action="status_changed", meta={"to": "open"})

        messages.success(request, "Message posted.")
    else:
        messages.error(request, "Invalid message.")

    return redirect("helpdesk:ticket_detail", pk=pk)


@login_required
@require_POST
@transaction.atomic
def ticket_assign_update(request, pk):
    from .models import Ticket, TicketEvent
    from .forms import TicketAssignForm

    if not request.user.is_staff:
        raise Http404

    ticket = get_object_or_404(Ticket, pk=pk)
    form = TicketAssignForm(request.POST)
    if form.is_valid():
        assignee_id = form.cleaned_data.get("assignee_id")
        new_status = form.cleaned_data.get("status")
        new_priority = form.cleaned_data.get("priority")

        changes = {}

        if assignee_id != ticket.assignee_id:
            ticket.assignee_id = assignee_id
            changes["assignee_id"] = assignee_id

        if new_status != ticket.status:
            ticket.status = new_status
            changes["status"] = new_status

        if new_priority != ticket.priority:
            ticket.priority = new_priority
            changes["priority"] = new_priority

        if changes:
            ticket.save()
            TicketEvent.objects.create(ticket=ticket, actor=request.user, action="ticket_updated", meta=changes)
            messages.success(request, "Ticket updated.")
    else:
        messages.error(request, "Invalid update.")

    return redirect("helpdesk:ticket_detail", pk=pk)