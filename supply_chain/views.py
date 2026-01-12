# supply_chain/views.py - Supply Chain Management Views

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse, HttpResponseForbidden
from django.db.models import Sum, Count, Q, Avg, F
from django.utils import timezone
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Prefetch
from django.db import transaction
from datetime import timedelta
from decimal import Decimal
from django.views.decorators.http import require_GET

from .models import (
    WarehouseLinkage, StoreToLogisticsTransfer, TransferItem,
    FulfillmentQueue, CountryShippingConfig, ShippingCompany,
    ShippingCompanyCountry, ShipmentTracking
)
from stores.models import B2BOrder, B2BOrderItem, Store
from stock.models import Warehouse, Stock
from logistics.models import Warehouse as LogisticsWarehouse, Vehicle, Driver, B2BShipment


# ==================== PERMISSION CHECKS ====================

def is_logistics_staff(user):
    """Check if user is logistics staff"""
    return user.is_staff or hasattr(user, 'logistics_profile')


def is_warehouse_staff(user):
    """Check if user is warehouse staff"""
    return user.is_staff or hasattr(user, 'warehouse_profile')


# ==================== DASHBOARD ====================


@login_required
@user_passes_test(is_warehouse_staff)
def supply_chain_dashboard(request):
    user_warehouse = None
    if hasattr(request.user, "logistics_profile"):
        user_warehouse = request.user.logistics_profile.warehouse

    base_transfers = (
        StoreToLogisticsTransfer.objects
        .select_related(
            "store_warehouse",
            "logistics_warehouse",
            "order",
            "b2b_order",
            "requested_by",
            # add these only if they exist on the model:
            # "picked_up_by",
            # "received_by",
        )
        .prefetch_related("items")  # if related_name="items" exists
    )

    if user_warehouse:
        base_transfers = base_transfers.filter(logistics_warehouse=user_warehouse)

    pending_transfers = base_transfers.filter(status="PENDING").order_by("-requested_at")[:10]
    in_transit_transfers = base_transfers.filter(status="PICKED_UP").order_by("-requested_at")[:10]

    pending_count = base_transfers.filter(status="PENDING").count()
    in_transit_count = base_transfers.filter(status="PICKED_UP").count()

    # Fulfillment stats
    fulfillment_qs = FulfillmentQueue.objects.select_related("logistics_warehouse").all()
    if user_warehouse:
        fulfillment_qs = fulfillment_qs.filter(logistics_warehouse=user_warehouse)

    fulfillment_by_status = {
        x["status"]: x["c"]
        for x in fulfillment_qs.values("status").annotate(c=Count("id"))
    }

    # Weekly metrics (safe)
    week_ago = timezone.now() - timedelta(days=7)

    avg_transfer_time = (
        base_transfers.filter(requested_at__gte=week_ago, actual_duration_minutes__isnull=False)
        .aggregate(v=Avg("actual_duration_minutes"))["v"]
        or 0
    )
    transfers_completed_count = base_transfers.filter(requested_at__gte=week_ago).count()

    avg_fulfillment_time = (
        fulfillment_qs.filter(shipped_at__gte=week_ago, actual_pick_time_minutes__isnull=False)
        .aggregate(v=Avg("actual_pick_time_minutes"))["v"]
        or 0
    )
    orders_fulfilled_count = fulfillment_qs.filter(shipped_at__gte=week_ago).count()

    urgent_orders = (
        fulfillment_qs.filter(priority__in=["URGENT", "HIGH"])
        .select_related("order")  # only if FulfillmentQueue has FK `order`
        .order_by("queued_at")[:10]
    )

    active_shipments = (
        B2BShipment.objects
        .select_related(
            "order",
            "shipping_address",
            "company_config",
            "company_config__shipping_company",
            "company_config__country",
        )
        .filter(status__in=["locked", "in_transit"])  # use your logistics statuses
        .order_by("-created_at")[:10]
    )

    context = {
        "user_warehouse": user_warehouse,

        "pending_transfers": pending_transfers,
        "in_transit_transfers": in_transit_transfers,
        "pending_count": pending_count,
        "in_transit_count": in_transit_count,

        "fulfillment_by_status": fulfillment_by_status,
        "urgent_orders": urgent_orders,

        "active_shipments": active_shipments,

        "avg_transfer_time": int(avg_transfer_time),
        "transfers_completed_count": transfers_completed_count,
        "avg_fulfillment_time": int(avg_fulfillment_time),
        "orders_fulfilled_count": orders_fulfilled_count,

        # keep what you already compute: warehouse_stats, bottlenecks, etc.
    }
    return render(request, "supply_chain/dashboard.html", context)

# ==================== WAREHOUSE LINKAGES ====================

@login_required
@user_passes_test(is_logistics_staff)
def warehouse_linkages(request):
    """Manage warehouse linkages between stores and logistics centers"""

    # Base queryset
    linkages = WarehouseLinkage.objects.select_related(
        'store_warehouse', 'logistics_warehouse'
    ).order_by('store_warehouse', 'priority')

    # Apply filters
    status_filter = request.GET.get('status')
    transfer_type_filter = request.GET.get('transfer_type')
    priority_filter = request.GET.get('priority')

    if status_filter == 'active':
        linkages = linkages.filter(is_active=True)
    elif status_filter == 'inactive':
        linkages = linkages.filter(is_active=False)

    if transfer_type_filter:
        # Add transfer_type filter if your model has this field
        # linkages = linkages.filter(transfer_type=transfer_type_filter)
        pass

    if priority_filter:
        linkages = linkages.filter(priority=priority_filter)

    # Statistics
    total_linkages = WarehouseLinkage.objects.count()
    active_linkages = WarehouseLinkage.objects.filter(is_active=True).count()

    # Get unique warehouses from linkages
    store_warehouses = Warehouse.objects.filter(
        logistics_linkages__isnull=False
    ).distinct().count()

    logistics_warehouses = LogisticsWarehouse.objects.filter(
        store_linkages__isnull=False
    ).distinct().count()

    # Warehouse lists for dropdowns (modal forms)
    store_warehouses_list = Warehouse.objects.filter(is_active=True).order_by('name')
    logistics_warehouses_list = LogisticsWarehouse.objects.filter(is_active=True).order_by('name')

    context = {
        'linkages': linkages,
        'total_linkages': total_linkages,
        'active_linkages': active_linkages,
        'store_warehouses': store_warehouses,
        'logistics_warehouses': logistics_warehouses,
        'store_warehouses_list': store_warehouses_list,
        'logistics_warehouses_list': logistics_warehouses_list,
    }

    return render(request, 'supply_chain/warehouse_linkages.html', context)


@login_required
@user_passes_test(is_logistics_staff)
def add_linkage(request):
    """Create a new warehouse linkage"""
    if request.method == 'POST':
        try:
            # Get form data
            store_warehouse_id = request.POST.get('store_warehouse')
            logistics_warehouse_id = request.POST.get('logistics_warehouse')
            transfer_type = request.POST.get('transfer_type', 'MANUAL')
            priority = request.POST.get('priority', 'MEDIUM')

            # Optional fields
            lead_time = request.POST.get('lead_time_hours')
            cost = request.POST.get('cost_per_transfer')

            # Create linkage
            linkage = WarehouseLinkage.objects.create(
                store_warehouse_id=store_warehouse_id,
                logistics_warehouse_id=logistics_warehouse_id,
                is_active=request.POST.get('is_active') == 'on',
                priority=1 if priority == 'HIGH' else 2 if priority == 'MEDIUM' else 3,
                notes=request.POST.get('notes', '')
            )

            # Set optional fields if they exist on your model
            if lead_time:
                linkage.estimated_transfer_time_minutes = int(float(lead_time) * 60)

            # If you have these fields, uncomment:
            # if cost:
            #     linkage.cost_per_transfer = Decimal(cost)
            # linkage.transfer_type = transfer_type

            linkage.save()

            messages.success(request, 'Warehouse linkage created successfully!')
            return redirect('supply_chain:warehouse_linkages')

        except Exception as e:
            messages.error(request, f'Error creating linkage: {str(e)}')
            return redirect('supply_chain:warehouse_linkages')

    return redirect('supply_chain:warehouse_linkages')


@login_required
@user_passes_test(is_logistics_staff)
def edit_linkage(request, pk):
    """Edit an existing warehouse linkage"""
    linkage = get_object_or_404(WarehouseLinkage, pk=pk)

    if request.method == 'POST':
        try:
            linkage.priority = 1 if request.POST.get('priority') == 'HIGH' else 2 if request.POST.get(
                'priority') == 'MEDIUM' else 3
            linkage.is_active = request.POST.get('is_active') == 'on'
            linkage.notes = request.POST.get('notes', '')

            # Optional fields
            lead_time = request.POST.get('lead_time_hours')
            if lead_time:
                linkage.estimated_transfer_time_minutes = int(float(lead_time) * 60)

            cost = request.POST.get('cost_per_transfer')
            # If you have cost_per_transfer field:
            # if cost:
            #     linkage.cost_per_transfer = Decimal(cost)

            linkage.save()

            messages.success(request, 'Linkage updated successfully!')
            return redirect('supply_chain:warehouse_linkages')

        except Exception as e:
            messages.error(request, f'Error updating linkage: {str(e)}')
            return redirect('supply_chain:warehouse_linkages')

    return redirect('supply_chain:warehouse_linkages')


@login_required
@user_passes_test(is_logistics_staff)
def toggle_linkage_status(request, pk):
    """Toggle linkage active status"""
    linkage = get_object_or_404(WarehouseLinkage, pk=pk)

    if request.method == 'POST':
        activate = request.POST.get('activate') == 'true'
        linkage.is_active = activate
        linkage.save()

        status = 'activated' if activate else 'deactivated'
        messages.success(request, f'Linkage {status} successfully!')

    return redirect('supply_chain:warehouse_linkages')

@login_required
@user_passes_test(is_logistics_staff)
def create_linkage(request):
    """Create a new warehouse linkage"""
    if request.method == 'POST':
        try:
            linkage = WarehouseLinkage.objects.create(
                store_warehouse_id=request.POST.get('store_warehouse'),
                logistics_warehouse_id=request.POST.get('logistics_warehouse'),
                is_primary=request.POST.get('is_primary') == 'on',
                priority=int(request.POST.get('priority', 1)),
                distance_km=request.POST.get('distance_km') or None,
                estimated_transfer_time_minutes=int(request.POST.get('estimated_time', 60)),
                max_daily_transfers=int(request.POST.get('max_daily_transfers', 10)),
                notes=request.POST.get('notes', '')
            )
            messages.success(request, 'Warehouse linkage created successfully.')
            return redirect('supply_chain:warehouse_linkages')
        except Exception as e:
            messages.error(request, f'Error creating linkage: {str(e)}')

    store_warehouses = Warehouse.objects.filter(is_active=True).order_by('code')
    logistics_warehouses = LogisticsWarehouse.objects.filter(is_active=True).order_by('name')

    context = {
        'store_warehouses': store_warehouses,
        'logistics_warehouses': logistics_warehouses,
    }

    return render(request, 'supply_chain/create_linkage.html', context)


# ==================== TRANSFERS ====================

@login_required
@user_passes_test(is_warehouse_staff)
def transfer_list(request):
    """List all transfers with filtering"""
    # ✅ FIXED: Removed 'picked_up_by' and 'received_by' - they don't exist in the model
    transfers = StoreToLogisticsTransfer.objects.select_related(
        'store_warehouse',
        'logistics_warehouse',
        'order',
        'b2b_order',  # Added b2b_order
        'requested_by'
    ).prefetch_related('items__product')

    # Filters
    status = request.GET.get('status')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    store_warehouse_id = request.GET.get('store_warehouse')
    logistics_warehouse_id = request.GET.get('logistics_warehouse')
    linkage_id = request.GET.get('linkage')  # Added linkage filter

    if status:
        transfers = transfers.filter(status=status)
    if date_from:
        transfers = transfers.filter(requested_at__date__gte=date_from)
    if date_to:
        transfers = transfers.filter(requested_at__date__lte=date_to)
    if store_warehouse_id:
        transfers = transfers.filter(store_warehouse_id=store_warehouse_id)
    if logistics_warehouse_id:
        transfers = transfers.filter(logistics_warehouse_id=logistics_warehouse_id)
    if linkage_id:
        # Filter by linkage (store + logistics warehouse combination)
        from .models import WarehouseLinkage
        try:
            linkage = WarehouseLinkage.objects.get(id=linkage_id)
            transfers = transfers.filter(
                store_warehouse=linkage.store_warehouse,
                logistics_warehouse=linkage.logistics_warehouse
            )
        except WarehouseLinkage.DoesNotExist:
            pass

    # Order by most recent
    transfers = transfers.order_by('-requested_at')

    # Statistics
    total_transfers = transfers.count()
    pending_count = transfers.filter(status='PENDING').count()
    in_transit_count = transfers.filter(status='PICKED_UP').count()
    completed_count = transfers.filter(status='RECEIVED').count()

    # Pagination
    paginator = Paginator(transfers, 25)
    page = request.GET.get('page')
    transfers_page = paginator.get_page(page)

    # Get warehouses for filter dropdowns
    from stock.models import Warehouse
    from logistics.models import Warehouse as LogisticsWarehouse

    store_warehouses = Warehouse.objects.filter(is_active=True).order_by('name')
    logistics_warehouses = LogisticsWarehouse.objects.filter(is_active=True).order_by('name')

    context = {
        'transfers': transfers_page,
        'total_transfers': total_transfers,
        'pending_count': pending_count,
        'in_transit_count': in_transit_count,
        'completed_count': completed_count,
        'status_choices': StoreToLogisticsTransfer.STATUS_CHOICES,
        'store_warehouses': store_warehouses,
        'logistics_warehouses': logistics_warehouses,
        'current_filters': {
            'status': status,
            'date_from': date_from,
            'date_to': date_to,
            'store_warehouse': store_warehouse_id,
            'logistics_warehouse': logistics_warehouse_id,
            'linkage': linkage_id,
        }
    }

    return render(request, 'supply_chain/transfer_list.html', context)


@login_required
@user_passes_test(is_warehouse_staff)
def transfer_detail(request, transfer_id):
    """View transfer details"""
    # ✅ FIXED: Removed non-existent fields
    transfer = get_object_or_404(
        StoreToLogisticsTransfer.objects.select_related(
            'store_warehouse',
            'logistics_warehouse',
            'order',
            'b2b_order',
            'requested_by'
            # 'picked_up_by', 'received_by', 'driver', 'vehicle' - DON'T EXIST
        ).prefetch_related('items__product'),
        id=transfer_id
    )

    context = {
        'transfer': transfer,
    }

    return render(request, 'supply_chain/transfer_detail.html', context)


@login_required
@user_passes_test(is_warehouse_staff)
@transaction.atomic
def mark_transfer_picked_up(request, transfer_id):
    """Mark transfer as picked up"""
    if request.method == 'POST':
        transfer = get_object_or_404(StoreToLogisticsTransfer, id=transfer_id)

        if transfer.status != 'PENDING':
            messages.error(request, 'Transfer is not in pending status.')
            return redirect('supply_chain:transfer_detail', transfer_id=transfer_id)

        # Update transfer status
        transfer.status = 'PICKED_UP'

        # Calculate start time for duration tracking
        # Store pickup time if you want to track it
        # You can add custom attributes or use created_at

        transfer.save()

        messages.success(request, f'Transfer {transfer.transfer_number} marked as picked up.')
        return redirect('supply_chain:transfer_detail', transfer_id=transfer_id)

    return HttpResponseForbidden()


@login_required
@user_passes_test(is_warehouse_staff)
@transaction.atomic
def mark_transfer_received(request, transfer_id):
    """Mark transfer as received"""
    if request.method == 'POST':
        transfer = get_object_or_404(StoreToLogisticsTransfer, id=transfer_id)

        if transfer.status != 'PICKED_UP':
            messages.error(request, 'Transfer must be picked up first.')
            return redirect('supply_chain:transfer_detail', transfer_id=transfer_id)

        # Update status
        transfer.status = 'RECEIVED'

        # Calculate actual duration if needed
        # You could calculate from requested_at to now
        if transfer.requested_at:
            duration = (timezone.now() - transfer.requested_at).total_seconds() / 60
            transfer.actual_duration_minutes = int(duration)

        # Get condition notes if provided
        condition_notes = request.POST.get('condition_notes', '')
        if condition_notes:
            transfer.notes = (transfer.notes or '') + f"\n\nReceiving Notes: {condition_notes}"

        transfer.save()

        # TODO: Update stock levels in logistics warehouse
        # for item in transfer.items.all():
        #     # Add stock to logistics warehouse
        #     pass

        messages.success(request, f'Transfer {transfer.transfer_number} marked as received.')
        return redirect('supply_chain:transfer_detail', transfer_id=transfer_id)

    return HttpResponseForbidden()


# ==================== FULFILLMENT QUEUE ====================

def _stage_from_b2b(order, fq):
    """
    Determine stage for a B2B order based on logistics_shipment and fulfillment queue.
    Returns (stage_key, stage_label)
    """
    shipment = getattr(order, "logistics_shipment", None)

    # If there's a fulfillment queue, use its status
    if fq:
        status_map = {
            'QUEUED': ('queued', 'Queued for Picking'),
            'PICKING': ('picking', 'Being Picked'),
            'PACKING': ('packing', 'Being Packed'),
            'READY': ('ready', 'Ready to Ship'),
            'SHIPPED': ('shipped', 'Shipped'),
        }
        return status_map.get(fq.status, ('unknown', 'Unknown'))

    # Otherwise, check shipment status
    if not shipment:
        return ('no_shipment', 'No Logistics Shipment')

    if shipment.status == 'draft':
        return ('waiting_lock', 'Waiting for Lock')
    elif shipment.status == 'locked':
        return ('locked', 'Locked (Ready for Fulfillment)')
    elif shipment.status == 'in_transit':
        return ('in_transit', 'In Transit')
    elif shipment.status == 'delivered':
        return ('delivered', 'Delivered')
    else:
        return ('unknown', shipment.get_status_display() if hasattr(shipment, 'get_status_display') else 'Unknown')


@login_required
@user_passes_test(is_warehouse_staff)
def fulfillment_queue(request):
    """
    Fulfillment board (B2B-driven):
    - Lists ALL B2B orders (customer/items always show)
    - Shows stage from logistics_shipment + fulfillment queue if exists
    - Warehouse restriction is applied via fulfillment queue / transfer warehouse when available
    """

    user_warehouse = None
    if hasattr(request.user, "logistics_profile"):
        user_warehouse = getattr(request.user.logistics_profile, "warehouse", None)

    stage_filter = (request.GET.get("stage") or "ALL").upper()
    status_filter = request.GET.get("status")
    priority_filter = request.GET.get("priority")

    # ✅ FIX: Only select_related on fields that actually exist
    # Removed: destination_country (doesn't exist)
    b2b_qs = (
        B2BOrder.objects
        .select_related(
            "buyer",
            "store",
            "shipping",
            "logistics_shipment"
            # "destination_country"  # ❌ This field doesn't exist
        )
        .prefetch_related("items__product")
        .order_by("-id")
    )

    # Build maps for fast lookup
    order_ids = list(b2b_qs.values_list("id", flat=True))

    # ✅ FIX: Use b2b_order_id instead of order_id
    transfers = StoreToLogisticsTransfer.objects.filter(
        b2b_order_id__in=order_ids
    ).select_related(
        "logistics_warehouse",
        "store_warehouse"
    )
    transfer_map = {t.b2b_order_id: t for t in transfers}

    # ✅ FIX: Use b2b_order_id instead of order_id
    # ✅ FIX: Remove 'shipped_by' from select_related (field doesn't exist yet)
    fqs = FulfillmentQueue.objects.filter(
        b2b_order_id__in=order_ids
    ).select_related(
        "logistics_warehouse",
        "picked_by",
        "packed_by",
        "transfer"
        # "shipped_by"  # ❌ Add this after running migration
    )
    fq_map = {q.b2b_order_id: q for q in fqs}

    rows = []
    for order in b2b_qs:
        fq = fq_map.get(order.id)
        transfer = transfer_map.get(order.id)
        shipment = getattr(order, "logistics_shipment", None)

        # Optional warehouse restriction:
        if user_warehouse:
            # If queue exists, use it
            if fq and fq.logistics_warehouse_id != user_warehouse.id:
                continue
            # Else if transfer exists, use it
            if (not fq) and transfer and transfer.logistics_warehouse_id != user_warehouse.id:
                continue

        # Apply status filter
        if status_filter and fq:
            if fq.status != status_filter:
                continue
        elif status_filter and not fq:
            continue  # No FQ means no status to match

        # Apply priority filter
        if priority_filter and fq:
            if fq.priority != priority_filter:
                continue
        elif priority_filter and not fq:
            continue  # No FQ means no priority to match

        stage_key, stage_label = _stage_from_b2b(order, fq)

        # Filter by stage
        if stage_filter != "ALL":
            # allow filtering by queue statuses too
            if stage_filter == "WAITING_LOCK" and stage_key != "waiting_lock":
                continue
            elif stage_filter == "LOCKED" and stage_key != "locked":
                continue
            elif stage_filter in {"QUEUED", "PICKING", "PACKING", "READY", "SHIPPED"}:
                if not fq or fq.status != stage_filter:
                    continue
            elif stage_filter == "IN_TRANSIT" and stage_key != "in_transit":
                continue
            elif stage_filter == "DELIVERED" and stage_key != "delivered":
                continue

        rows.append({
            "order": order,
            "shipment": shipment,
            "transfer": transfer,
            "fq": fq,
            "stage_key": stage_key,
            "stage_label": stage_label,
        })

    paginator = Paginator(rows, 30)
    page_number = request.GET.get("page")
    rows_page = paginator.get_page(page_number)

    context = {
        "rows": rows_page,
        "user_warehouse": user_warehouse,
        "current_stage": stage_filter,
        "current_status": status_filter,
        "current_priority": priority_filter,
        "stage_choices": [
            ("ALL", "All Stages"),
            ("WAITING_LOCK", "Waiting Lock"),
            ("LOCKED", "Locked"),
            ("QUEUED", "Queued"),
            ("PICKING", "Picking"),
            ("PACKING", "Packing"),
            ("READY", "Ready"),
            ("SHIPPED", "Shipped"),
            ("IN_TRANSIT", "In Transit"),
            ("DELIVERED", "Delivered"),
        ],
        "status_choices": FulfillmentQueue.STATUS_CHOICES,
        "priority_choices": FulfillmentQueue.PRIORITY_CHOICES,
    }

    return render(request, "supply_chain/fulfillment_queue.html", context)


@login_required
@user_passes_test(is_warehouse_staff)
@transaction.atomic
def start_picking_b2b(request, b2b_order_id):
    """Start picking for a B2B order"""
    if request.method != "POST":
        return redirect("supply_chain:fulfillment_queue")

    order = get_object_or_404(B2BOrder, id=b2b_order_id)

    # Check if order has a logistics shipment
    shipment = getattr(order, "logistics_shipment", None)

    # Must be locked before warehouse can work
    if not shipment or shipment.status != "locked":
        messages.error(request, "Order must be locked before picking can start.")
        return redirect("supply_chain:fulfillment_queue")

    # Get the transfer for this order
    transfer = StoreToLogisticsTransfer.objects.filter(b2b_order=order).first()

    # ✅ FIX: Determine logistics warehouse
    # Priority: 1) From transfer, 2) From user profile, 3) First active warehouse
    logistics_warehouse = None

    if transfer and transfer.logistics_warehouse:
        logistics_warehouse = transfer.logistics_warehouse
    elif hasattr(request.user, 'logistics_profile') and request.user.logistics_profile.warehouse:
        logistics_warehouse = request.user.logistics_profile.warehouse
    else:
        # Fall back to first active logistics warehouse
        logistics_warehouse = LogisticsWarehouse.objects.filter(is_active=True).first()

    # ✅ FIX: If still no warehouse, we can't proceed
    if not logistics_warehouse:
        messages.error(request, "No logistics warehouse available. Please contact administrator.")
        return redirect("supply_chain:fulfillment_queue")

    # Create or get fulfillment queue entry
    fq, created = FulfillmentQueue.objects.get_or_create(
        b2b_order=order,
        defaults={
            "transfer": transfer,
            "logistics_warehouse": logistics_warehouse,  # ✅ Now guaranteed to have a value
            "status": "QUEUED",
            "priority": "NORMAL",
        }
    )

    # If it already existed and was in a different status, update it
    if not created and fq.status not in ['PICKING', 'PACKING', 'READY', 'SHIPPED']:
        fq.status = "PICKING"
        fq.picked_by = request.user
        fq.picking_started_at = timezone.now()
        fq.save()
    elif created:
        # Just created, now start picking
        fq.status = "PICKING"
        fq.picked_by = request.user
        fq.picking_started_at = timezone.now()
        fq.save()
    else:
        # Already in progress
        messages.info(request, f"Order is already in {fq.get_status_display()} status.")
        return redirect("supply_chain:fulfillment_queue")

    messages.success(request, f"Started picking for B2B Order #{order.id}")
    return redirect("supply_chain:fulfillment_queue")


@login_required
@user_passes_test(is_warehouse_staff)
@transaction.atomic
def complete_picking_b2b(request, b2b_order_id):
    """Complete picking and start packing for B2B order"""
    if request.method != "POST":
        return redirect("supply_chain:fulfillment_queue")

    order = get_object_or_404(B2BOrder, id=b2b_order_id)

    try:
        fq = FulfillmentQueue.objects.get(b2b_order=order)
    except FulfillmentQueue.DoesNotExist:
        messages.error(request, "Fulfillment queue entry not found.")
        return redirect("supply_chain:fulfillment_queue")

    if fq.status != 'PICKING':
        messages.error(request, f"Order must be in PICKING status. Current status: {fq.get_status_display()}")
        return redirect("supply_chain:fulfillment_queue")

    # Complete picking and start packing
    fq.status = "PACKING"
    fq.picking_completed_at = timezone.now()
    fq.packed_by = request.user
    fq.packing_started_at = timezone.now()

    # Calculate pick time
    if fq.picking_started_at:
        duration = (fq.picking_completed_at - fq.picking_started_at).total_seconds() / 60
        fq.actual_pick_time_minutes = int(duration)

    fq.save()

    messages.success(request, f"Picking completed for B2B Order #{order.id}. Started packing.")
    return redirect("supply_chain:fulfillment_queue")


@login_required
@user_passes_test(is_warehouse_staff)
@transaction.atomic
def complete_packing_b2b(request, b2b_order_id):
    """Complete packing for B2B order"""
    if request.method != "POST":
        return redirect("supply_chain:fulfillment_queue")

    order = get_object_or_404(B2BOrder, id=b2b_order_id)

    try:
        fq = FulfillmentQueue.objects.get(b2b_order=order)
    except FulfillmentQueue.DoesNotExist:
        messages.error(request, "Fulfillment queue entry not found.")
        return redirect("supply_chain:fulfillment_queue")

    if fq.status != 'PACKING':
        messages.error(request, f"Order must be in PACKING status. Current status: {fq.get_status_display()}")
        return redirect("supply_chain:fulfillment_queue")

    # Complete packing
    fq.status = "READY"
    fq.packing_completed_at = timezone.now()

    # Calculate pack time
    if fq.packing_started_at:
        duration = (fq.packing_completed_at - fq.packing_started_at).total_seconds() / 60
        fq.actual_pack_time_minutes = int(duration)

    fq.save()

    messages.success(request, f"Packing completed for B2B Order #{order.id}. Ready to ship.")
    return redirect("supply_chain:fulfillment_queue")

# ==================== B2B SHIPPING ====================

@login_required
@user_passes_test(is_logistics_staff)
def shipping_config(request):
    """Manage shipping configuration for countries and companies"""
    countries = CountryShippingConfig.objects.prefetch_related(
        'shipping_companies'
    ).order_by('country_name')

    shipping_companies = ShippingCompany.objects.filter(
        is_active=True
    ).order_by('name')

    context = {
        'countries': countries,
        'shipping_companies': shipping_companies,
    }

    return render(request, 'supply_chain/shipping_config.html', context)


@login_required
@user_passes_test(is_logistics_staff)
def country_detail(request, pk):
    """Display detailed information about a specific country's shipping configuration"""
    country = get_object_or_404(CountryShippingConfig, pk=pk)

    # Get all shipping companies configured for this country
    configured_companies = ShippingCompanyCountry.objects.filter(
        country=country
    ).select_related('shipping_company').order_by('priority', 'service_level')

    # Get all available shipping companies (for the add modal)
    all_companies = ShippingCompany.objects.filter(is_active=True).order_by('name')

    context = {
        'country': country,
        'configured_companies': configured_companies,
        'all_companies': all_companies,
    }

    return render(request, 'supply_chain/country_detail.html', context)


@login_required
@user_passes_test(is_logistics_staff)
def b2b_shipments(request):
    """List and manage B2B shipments"""
    shipments = B2BShipment.objects.select_related(
        'b2b_order', 'shipping_company', 'country', 'company_config'
    ).prefetch_related('tracking_history')

    # Filters
    status = request.GET.get('status')
    country_id = request.GET.get('country')
    company_id = request.GET.get('company')
    date_from = request.GET.get('date_from')

    if status:
        shipments = shipments.filter(status=status)
    if country_id:
        shipments = shipments.filter(country_id=country_id)
    if company_id:
        shipments = shipments.filter(shipping_company_id=company_id)
    if date_from:
        shipments = shipments.filter(created_at__date__gte=date_from)

    shipments = shipments.order_by('-created_at')

    # Pagination
    paginator = Paginator(shipments, 25)
    page = request.GET.get('page')
    shipments_page = paginator.get_page(page)

    # For filters
    countries = CountryShippingConfig.objects.filter(is_active=True)
    companies = ShippingCompany.objects.filter(is_active=True)

    context = {
        'shipments': shipments_page,
        'status_choices': B2BShipment.STATUS_CHOICES,
        'countries': countries,
        'companies': companies,
        'current_filters': {
            'status': status,
            'country': country_id,
            'company': company_id,
            'date_from': date_from,
        }
    }

    return render(request, 'supply_chain/b2b_shipments.html', context)


@login_required
@user_passes_test(is_logistics_staff)
def create_b2b_shipment(request, order_id):
    """Create B2B shipment for an order"""
    b2b_order = get_object_or_404(
        B2BOrder.objects.select_related('store', 'shipping'),
        id=order_id
    )

    if request.method == 'POST':
        try:
            company_config_id = request.POST.get('company_config')
            company_config = get_object_or_404(ShippingCompanyCountry, id=company_config_id)

            weight_kg = Decimal(request.POST.get('weight_kg'))
            package_count = int(request.POST.get('package_count', 1))

            # Calculate costs
            shipping_cost = company_config.calculate_cost(weight_kg)
            insurance_cost = Decimal(request.POST.get('insurance_cost', 0))
            customs_fee = Decimal(request.POST.get('customs_fee', 0))

            shipment = B2BShipment.objects.create(
                b2b_order=b2b_order,
                shipping_company=company_config.shipping_company,
                company_config=company_config,
                country=company_config.country,
                total_weight_kg=weight_kg,
                package_count=package_count,
                dimensions_cm=request.POST.get('dimensions', ''),
                shipping_cost=shipping_cost,
                insurance_cost=insurance_cost,
                customs_fee=customs_fee,
                notes=request.POST.get('notes', '')
            )

            messages.success(request, f'Shipment {shipment.shipment_number} created successfully.')
            return redirect('supply_chain:shipment_detail', shipment_id=shipment.id)

        except Exception as e:
            messages.error(request, f'Error creating shipment: {str(e)}')

    # Get shipping address country
    shipping_country = None
    if hasattr(b2b_order, 'shipping'):
        country_name = b2b_order.shipping.country
        shipping_country = CountryShippingConfig.objects.filter(
            country_name__iexact=country_name,
            is_active=True
        ).first()

    # Get available shipping companies for this country
    company_configs = []
    if shipping_country:
        company_configs = ShippingCompanyCountry.objects.filter(
            country=shipping_country,
            is_active=True
        ).select_related('shipping_company').order_by('priority')

    context = {
        'b2b_order': b2b_order,
        'shipping_country': shipping_country,
        'company_configs': company_configs,
    }

    return render(request, 'supply_chain/create_b2b_shipment.html', context)


@login_required
def shipment_detail(request, shipment_id):
    """View shipment details and tracking"""
    shipment = get_object_or_404(
        B2BShipment.objects.select_related(
            'b2b_order', 'shipping_company', 'country', 'company_config'
        ).prefetch_related('tracking_history'),
        id=shipment_id
    )

    # Check permission
    if not (request.user.is_staff or
            shipment.b2b_order.buyer == request.user or
            shipment.b2b_order.store.owner == request.user):
        return HttpResponseForbidden()

    context = {
        'shipment': shipment,
        'tracking_history': shipment.tracking_history.all()[:20],
    }

    return render(request, 'supply_chain/shipment_detail.html', context)


@login_required
@user_passes_test(is_logistics_staff)
def mark_shipment_shipped(request, shipment_id):
    """Mark B2B shipment as shipped"""
    if request.method == 'POST':
        shipment = get_object_or_404(B2BShipment, id=shipment_id)

        tracking_number = request.POST.get('tracking_number')
        tracking_url = request.POST.get('tracking_url', '')

        if not tracking_number:
            messages.error(request, 'Tracking number is required.')
            return redirect('supply_chain:shipment_detail', shipment_id=shipment_id)

        shipment.mark_shipped(tracking_number, request.user)
        shipment.carrier_tracking_url = tracking_url
        shipment.save()

        # Create initial tracking entry
        ShipmentTracking.objects.create(
            shipment=shipment,
            status='SHIPPED',
            location='Warehouse',
            description='Shipment dispatched from warehouse',
            timestamp=timezone.now()
        )

        messages.success(request, f'Shipment {shipment.shipment_number} marked as shipped.')
        return redirect('supply_chain:shipment_detail', shipment_id=shipment_id)

    return HttpResponseForbidden()


@login_required
def add_country(request):
    """Add a new shipping destination country"""
    if request.method == 'POST':
        try:
            country = CountryShippingConfig.objects.create(
                country_code=request.POST.get('country_code', '').upper(),
                country_name=request.POST.get('country_name', ''),
                is_active=request.POST.get('is_active') == 'on',
                requires_customs=request.POST.get('requires_customs') == 'on',
                estimated_delivery_days=int(request.POST.get('estimated_delivery_days', 7)),
                max_package_weight_kg=Decimal(request.POST.get('max_package_weight_kg')) if request.POST.get(
                    'max_package_weight_kg') else None,
                restricted_items=request.POST.get('restricted_items', ''),
                notes=request.POST.get('notes', '')
            )

            messages.success(request, f'Country "{country.country_name}" added successfully!')
            return redirect('supply_chain:shipping_config')

        except Exception as e:
            messages.error(request, f'Error adding country: {str(e)}')
            return redirect('supply_chain:shipping_config')

    return redirect('supply_chain:shipping_config')


@login_required
def edit_country(request, pk):
    """Edit an existing country configuration"""
    country = get_object_or_404(CountryShippingConfig, pk=pk)

    if request.method == 'POST':
        try:
            country.country_name = request.POST.get('country_name', country.country_name)
            country.country_code = request.POST.get('country_code', country.country_code).upper()
            country.is_active = request.POST.get('is_active') == 'on'
            country.requires_customs = request.POST.get('requires_customs') == 'on'
            country.estimated_delivery_days = int(request.POST.get('estimated_delivery_days', 7))

            max_weight = request.POST.get('max_package_weight_kg')
            country.max_package_weight_kg = Decimal(max_weight) if max_weight else None

            country.restricted_items = request.POST.get('restricted_items', '')
            country.notes = request.POST.get('notes', '')
            country.save()

            messages.success(request, f'Country "{country.country_name}" updated successfully!')
            return redirect('supply_chain:country_detail', pk=pk)

        except Exception as e:
            messages.error(request, f'Error updating country: {str(e)}')
            return redirect('supply_chain:country_detail', pk=pk)

    return redirect('supply_chain:country_detail', pk=pk)


@login_required
def delete_country(request, pk):
    """Delete a country configuration"""
    country = get_object_or_404(CountryShippingConfig, pk=pk)

    if request.method == 'POST':
        country_name = country.country_name
        country.delete()
        messages.success(request, f'Country "{country_name}" deleted successfully!')
        return redirect('supply_chain:shipping_config')

    return redirect('supply_chain:country_detail', pk=pk)


@login_required
def add_shipping_company(request):
    """Add a new shipping company"""
    if request.method == 'POST':
        try:
            # Create the shipping company
            company = ShippingCompany.objects.create(
                name=request.POST.get('name', ''),
                code=request.POST.get('code', '').upper(),
                contact_email=request.POST.get('contact_email', ''),
                contact_phone=request.POST.get('contact_phone', ''),
                website=request.POST.get('website', ''),
                has_api_integration=request.POST.get('has_api_integration') == 'on',
                api_endpoint=request.POST.get('api_endpoint', ''),
                api_key=request.POST.get('api_key', ''),
                supports_tracking=request.POST.get('supports_tracking') == 'on',
                supports_insurance=request.POST.get('supports_insurance') == 'on',
                supports_cod=request.POST.get('supports_cod') == 'on',
                is_active=request.POST.get('is_active') == 'on',
                notes=request.POST.get('notes', '')
            )

            # Handle logo upload
            if 'logo' in request.FILES:
                company.logo = request.FILES['logo']
                company.save()

            messages.success(request, f'Shipping company "{company.name}" added successfully!')
            return redirect('supply_chain:shipping_config')

        except Exception as e:
            messages.error(request, f'Error adding shipping company: {str(e)}')
            return redirect('supply_chain:shipping_config')

    return redirect('supply_chain:shipping_config')

@login_required
def edit_shipping_company(request, pk):
    """Edit an existing shipping company"""
    company = get_object_or_404(ShippingCompany, pk=pk)

    if request.method == 'POST':
        try:
            company.name = request.POST.get('name', company.name)
            company.code = request.POST.get('code', company.code).upper()
            company.contact_email = request.POST.get('contact_email', company.contact_email)
            company.contact_phone = request.POST.get('contact_phone', company.contact_phone)
            company.website = request.POST.get('website', '')
            company.has_api_integration = request.POST.get('has_api_integration') == 'on'
            company.api_endpoint = request.POST.get('api_endpoint', '')
            company.api_key = request.POST.get('api_key', '')
            company.supports_tracking = request.POST.get('supports_tracking') == 'on'
            company.supports_insurance = request.POST.get('supports_insurance') == 'on'
            company.supports_cod = request.POST.get('supports_cod') == 'on'
            company.is_active = request.POST.get('is_active') == 'on'
            company.notes = request.POST.get('notes', '')

            # Handle logo upload
            if 'logo' in request.FILES:
                company.logo = request.FILES['logo']

            company.save()

            messages.success(request, f'Shipping company "{company.name}" updated successfully!')
            return redirect('supply_chain:shipping_config')

        except Exception as e:
            messages.error(request, f'Error updating shipping company: {str(e)}')
            return redirect('supply_chain:shipping_config')

    return redirect('supply_chain:shipping_config')


@login_required
def delete_shipping_company(request, pk):
    """Delete a shipping company"""
    company = get_object_or_404(ShippingCompany, pk=pk)

    if request.method == 'POST':
        company_name = company.name
        company.delete()
        messages.success(request, f'Shipping company "{company_name}" deleted successfully!')
        return redirect('supply_chain:shipping_config')

    return redirect('supply_chain:shipping_config')


@login_required
def add_company_to_country(request, country_id):
    """Add a shipping company to a country with rate configuration"""
    country = get_object_or_404(CountryShippingConfig, pk=country_id)

    if request.method == 'POST':
        try:
            shipping_company_id = request.POST.get('shipping_company')
            shipping_company = get_object_or_404(ShippingCompany, pk=shipping_company_id)

            config = ShippingCompanyCountry.objects.create(
                shipping_company=shipping_company,
                country=country,
                base_rate=Decimal(request.POST.get('base_rate', '0')),
                per_kg_rate=Decimal(request.POST.get('per_kg_rate', '0')),
                service_level=request.POST.get('service_level', 'STANDARD'),
                estimated_days=int(request.POST.get('estimated_days', 7)),
                priority=int(request.POST.get('priority', 1)),
                min_weight_kg=Decimal(request.POST.get('min_weight_kg', '0')),
                max_weight_kg=Decimal(request.POST.get('max_weight_kg')) if request.POST.get('max_weight_kg') else None,
                is_active=request.POST.get('is_active') == 'on'
            )

            messages.success(request, f'"{shipping_company.name}" added to "{country.country_name}" successfully!')
            return redirect('supply_chain:country_detail', pk=country_id)

        except Exception as e:
            messages.error(request, f'Error adding company to country: {str(e)}')
            return redirect('supply_chain:country_detail', pk=country_id)

    return redirect('supply_chain:country_detail', pk=country_id)


@login_required
def edit_company_config(request, pk):
    """Edit shipping company-country configuration"""
    config = get_object_or_404(ShippingCompanyCountry, pk=pk)

    if request.method == 'POST':
        try:
            config.base_rate = Decimal(request.POST.get('base_rate', config.base_rate))
            config.per_kg_rate = Decimal(request.POST.get('per_kg_rate', config.per_kg_rate))
            config.service_level = request.POST.get('service_level', config.service_level)
            config.estimated_days = int(request.POST.get('estimated_days', config.estimated_days))
            config.priority = int(request.POST.get('priority', config.priority))
            config.min_weight_kg = Decimal(request.POST.get('min_weight_kg', '0'))

            max_weight = request.POST.get('max_weight_kg')
            config.max_weight_kg = Decimal(max_weight) if max_weight else None

            config.is_active = request.POST.get('is_active') == 'on'
            config.save()

            messages.success(request, 'Company configuration updated successfully!')
            return redirect('supply_chain:country_detail', pk=config.country.pk)

        except Exception as e:
            messages.error(request, f'Error updating configuration: {str(e)}')
            return redirect('supply_chain:country_detail', pk=config.country.pk)

    return redirect('supply_chain:country_detail', pk=config.country.pk)


@login_required
def delete_company_config(request, pk):
    """Delete shipping company-country configuration"""
    config = get_object_or_404(ShippingCompanyCountry, pk=pk)
    country_id = config.country.pk

    if request.method == 'POST':
        config.delete()
        messages.success(request, 'Company configuration removed successfully!')
        return redirect('supply_chain:country_detail', pk=country_id)

    return redirect('supply_chain:country_detail', pk=country_id)


# ==================== ANALYTICS ====================

@login_required
@user_passes_test(is_logistics_staff)
def supply_chain_analytics(request):
    """Analytics and performance metrics"""
    # Date range
    period = request.GET.get('period', '30')
    period_days = int(period)
    start_date = timezone.now().date() - timedelta(days=period_days)

    # Transfer Performance
    transfers = StoreToLogisticsTransfer.objects.filter(
        requested_at__date__gte=start_date
    )

    transfer_stats = {
        'total': transfers.count(),
        'completed': transfers.filter(status='RECEIVED').count(),
        'avg_time': transfers.filter(
            status='RECEIVED',
            actual_duration_minutes__isnull=False
        ).aggregate(avg=Avg('actual_duration_minutes'))['avg'] or 0,
    }

    # Fulfillment Performance
    fulfillments = FulfillmentQueue.objects.filter(
        queued_at__date__gte=start_date
    )

    fulfillment_stats = {
        'total': fulfillments.count(),
        'shipped': fulfillments.filter(status='SHIPPED').count(),
        'avg_pick_time': fulfillments.filter(
            actual_pick_time_minutes__isnull=False
        ).aggregate(avg=Avg('actual_pick_time_minutes'))['avg'] or 0,
        'avg_pack_time': fulfillments.filter(
            actual_pack_time_minutes__isnull=False
        ).aggregate(avg=Avg('actual_pack_time_minutes'))['avg'] or 0,
    }

    # B2B Shipment Stats
    shipments = B2BShipment.objects.filter(
        created_at__date__gte=start_date
    )

    shipment_stats = {
        'total': shipments.count(),
        'delivered': shipments.filter(status='DELIVERED').count(),
        'total_revenue': shipments.aggregate(
            total=Sum('total_cost')
        )['total'] or 0,
    }

    # Performance by warehouse
    warehouse_performance = []
    warehouses = LogisticsWarehouse.objects.filter(is_active=True)

    for wh in warehouses:
        wh_fulfillments = fulfillments.filter(logistics_warehouse=wh)
        shipped = wh_fulfillments.filter(status='SHIPPED').count()
        total = wh_fulfillments.count()

        warehouse_performance.append({
            'warehouse': wh,
            'total_orders': total,
            'shipped_orders': shipped,
            'fulfillment_rate': round((shipped / total * 100) if total > 0 else 0, 1),
            'avg_time': wh_fulfillments.filter(
                status='SHIPPED'
            ).aggregate(
                avg=Avg(F('actual_pick_time_minutes') + F('actual_pack_time_minutes'))
            )['avg'] or 0,
        })

    context = {
        'period_days': period_days,
        'transfer_stats': transfer_stats,
        'fulfillment_stats': fulfillment_stats,
        'shipment_stats': shipment_stats,
        'warehouse_performance': warehouse_performance,
    }

    return render(request, 'supply_chain/analytics.html', context)


# ==================== API ENDPOINTS ====================

@login_required
def api_shipping_cost(request):
    """Calculate shipping cost for B2B order"""
    if request.method == 'GET':
        country_id = request.GET.get('country_id')
        weight_kg = request.GET.get('weight_kg')
        company_config_id = request.GET.get('company_config_id')

        try:
            company_config = ShippingCompanyCountry.objects.get(id=company_config_id)
            cost = company_config.calculate_cost(float(weight_kg))

            return JsonResponse({
                'success': True,
                'shipping_cost': float(cost),
                'company': company_config.shipping_company.name,
                'service_level': company_config.service_level,
                'estimated_days': company_config.estimated_days,
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)

    return JsonResponse({'error': 'Invalid request'}, status=400)

@login_required
def api_origin_shipping_companies(request):
    origin = (request.GET.get("origin") or "").strip()
    mode = (request.GET.get("mode") or "").strip()

    if not origin:
        return JsonResponse({"success": False, "error": "Missing origin"}, status=400)

    qs = CountryShippingConfig.objects.filter(is_active=True)

    # allow "GM" or "Gambia"
    if len(origin) == 2:
        country = qs.filter(country_code__iexact=origin).first()
    else:
        country = qs.filter(country_name__iexact=origin).first() or qs.filter(country_name__icontains=origin).first()

    if not country:
        return JsonResponse({"success": True, "results": []})

    configs = ShippingCompanyCountry.objects.filter(
        country=country,
        is_active=True,
        shipping_company__is_active=True
    ).select_related("shipping_company").order_by("priority", "service_level")

    # filter by mode if provided (supported_modes empty = supports all)
    if mode:
        configs = configs.filter(
            Q(shipping_company__supported_modes=[]) |
            Q(shipping_company__supported_modes__contains=[mode])
        )

    results = [
        {
            "id": c.id,
            "company_name": c.shipping_company.name,
            "service_level": c.service_level,
            "estimated_days": c.estimated_days,
        }
        for c in configs
    ]
    return JsonResponse({"success": True, "results": results})