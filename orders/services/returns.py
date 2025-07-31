from decimal import Decimal
from django.utils import timezone
from orders.models import Return, ReturnItem, ReturnRefund, ReturnStatusHistory
from django.core.exceptions import ValidationError
from django.db.models import Sum

RETURNS_WINDOW_DAYS = 30

def create_return_from_post(order, store, buyer, data, files=None) -> Return:
    """
    data should include:
      reasons, note_from_buyer
      items: list of dicts {order_item_id, quantity, resolution, condition, exchange_variant_id?}
    """
    ret = Return.objects.create(
        order=order, store=store, buyer=buyer,
        reason=data.get('reason',''), note_from_buyer=data.get('note','')
    )
    _add_status(ret, 'requested', note='Return requested')

    # Attach images
    if files:
        for f in files.getlist('images'):
            ret.images.create(image=f)

    # Build items
    for row in data['items']:
        oi = row['order_item']
        qty = int(row['quantity'])
        resolution = row.get('resolution', 'refund')
        condition = row.get('condition', 'unopened')
        exchange_variant = row.get('exchange_variant')

        # snapshot unit price at purchase (discounted)
        # prefer oi.discounted_unit_price property if present
        unit_price = getattr(oi, 'discounted_unit_price', None) or oi.price_at_time or oi.product.price
        unit_price = Decimal(unit_price)

        per_unit_discount = Decimal('0.00')
        if hasattr(oi, 'get_unit_discount_amount'):
            per_unit_discount = Decimal(oi.get_unit_discount_amount())

        line_subtotal = (unit_price * qty).quantize(Decimal('0.01'))

        ret_item = ReturnItem.objects.create(
            ret=ret, order_item=oi, quantity=qty, condition=condition, resolution=resolution,
            exchange_variant=exchange_variant,
            unit_price_at_purchase=unit_price, per_unit_discount=per_unit_discount,
            line_subtotal=line_subtotal,
        )

    return ret


def validate_return_request(order, store, user, rows):
    """
    rows: list of dicts like:
      {'order_item': <OrderItem>, 'qty': int, 'resolution': 'refund'|'exchange', ...}
    """

    # 1) Basic order ownership & store check (adapt to your schema)
    for r in rows:
        oi = r['order_item']
        if oi.order_id != order.id:
            raise ValidationError("One or more items do not belong to this order.")
        # If Product has .store:
        if getattr(oi.product, 'store_id', None) != getattr(store, 'id', None):
            raise ValidationError(f"{oi.product.name}: this item does not belong to the selected store.")

    # 2) Build a map of previously returned qtys for these order_items
    oi_ids = [r['order_item'].id for r in rows]
    prior = (
        ReturnItem.objects
        .filter(order_item_id__in=oi_ids,
                return_request__status__in=['pending','approved','in_transit','received','completed'])
        .values('order_item_id')
        .annotate(qty=Sum('quantity'))
    )
    prior_map = {p['order_item_id']: (p['qty'] or 0) for p in prior}

    # 3) Validate quantities do not exceed remaining allowed
    for r in rows:
        oi = r['order_item']
        requested = int(r.get('qty') or 0)
        if requested < 0:
            raise ValidationError(f"{oi.product.name}: quantity cannot be negative.")

        already = prior_map.get(oi.id, 0)
        remaining = max(oi.quantity - already, 0)

        if requested > remaining:
            raise ValidationError(
                f"{oi.product.name}: requested {requested} exceeds remaining returnable {remaining}."
            )

    # 4) Ensure at least one non-zero line
    if not any((int(r.get('qty') or 0) > 0) for r in rows):
        raise ValidationError("Please select at least one item quantity to return.")

    # 5) Return True if all good
    return True

def compute_refund(ret: Return) -> Decimal:
    """
    Sum refundable amount across ReturnItems; optionally subtract restocking fee.
    Shipping and tax policies can be added here (e.g., refund proportional tax).
    """
    subtotal = sum((ri.line_subtotal for ri in ret.items.all()), start=Decimal('0.00'))
    restocking = (subtotal * (ret.restocking_fee_percent / Decimal('100'))).quantize(Decimal('0.01'))
    # Shipping refund policy:
    ship_refund = Decimal('0.00')
    if ret.allow_refund_shipping:
        ship_refund = Decimal(getattr(ret.order, 'shipping_cost', 0) or 0)
    amount = (subtotal - restocking + ship_refund).quantize(Decimal('0.01'))

    # write back per line restocking allocation (pro rata)
    _allocate_restocking(ret, restocking)
    return amount


def _allocate_restocking(ret: Return, restocking_total: Decimal):
    total_lines = sum((ri.line_subtotal for ri in ret.items.all()), start=Decimal('0.00')) or Decimal('1.00')
    for ri in ret.items.all():
        share = (ri.line_subtotal / total_lines) * restocking_total
        ri.restocking_fee_amount = share.quantize(Decimal('0.01'))
        # default refund line = line_subtotal - line_share
        ri.refund_amount = (ri.line_subtotal - ri.restocking_fee_amount).quantize(Decimal('0.01'))
        ri.save(update_fields=['restocking_fee_amount', 'refund_amount'])


def mark_status(ret: Return, new_status: str, note: str = ''):
    ret.status = new_status
    if new_status == 'received':
        ret.received_at = timezone.now()
    if new_status in ('refunded', 'exchanged', 'closed'):
        ret.closed_at = timezone.now()
    ret.save(update_fields=['status','received_at','closed_at'])
    _add_status(ret, new_status, note)


def process_refund(ret: Return, method: str, reference: str, user) -> ReturnRefund:
    """
    Record refund (actual payment is done via your payment gateway UI/app).
    """
    amount = compute_refund(ret)
    refund, _ = ReturnRefund.objects.update_or_create(
        ret=ret,
        defaults={
            'amount': amount, 'method': method, 'reference': reference, 'processed_by': user
        }
    )
    mark_status(ret, 'refunded', note=f"Refunded {amount} via {method}. Ref: {reference}")
    return refund


def adjust_stock_after_receive(ret: Return):
    """
    Increase stock if condition allows restock; for exchanges, reserve the exchange variant.
    """
    for ri in ret.items.all():
        # restock policy: unopened or opened restockable
        if ri.condition in ('unopened', 'opened'):
            # Increase stock of the original product/variant
            if hasattr(ri.order_item, 'variant') and ri.order_item.variant:
                v = ri.order_item.variant
                v.stock = (v.stock or 0) + ri.quantity
                v.save(update_fields=['stock'])
            else:
                p = ri.order_item.product
                p.stock = (p.stock or 0) + ri.quantity
                p.save(update_fields=['stock'])

        if ri.resolution == 'exchange' and ri.exchange_variant:
            # reserve stock for exchange variant
            ex = ri.exchange_variant
            if (ex.stock or 0) < ri.quantity:
                raise ValueError(f"Insufficient stock for exchange variant {ex}")
            ex.stock = ex.stock - ri.quantity
            ex.save(update_fields=['stock'])


def _add_status(ret: Return, status: str, note: str = ''):
    ReturnStatusHistory.objects.create(ret=ret, status=status, note=note)
