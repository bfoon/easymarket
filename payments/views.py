from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, QueryDict
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db import transaction
from django.core.exceptions import ValidationError
from datetime import timedelta
import json
import logging

from orders.models import Order, ShippingAddress
from .models import Payment

logger = logging.getLogger(__name__)


@login_required
@require_POST
def process_payment(request, order_id):
    """Process payment for an order"""
    try:
        with transaction.atomic():
            # Get the order
            order = get_object_or_404(Order, id=order_id, buyer=request.user)

            # Check if order can be paid
            if order.status != 'pending':
                return JsonResponse({'success': False, 'error': 'Order is not in pending status'})

            # Check if already paid
            if hasattr(order, 'payment_record') and order.payment_record and order.payment_record.is_successful():
                return JsonResponse({'success': False, 'error': 'Order is already paid'})

            # Get data (JSON or POST)
            if request.content_type == 'application/json':
                data = json.loads(request.body)
                post_data = QueryDict('', mutable=True)
                post_data.update(data)
            else:
                data = request.POST
                post_data = request.POST

            # Validate and retrieve shipping address
            try:
                shipping_address = handle_shipping_address(post_data, request.user)
                order.shipping_address = shipping_address
                order.save()
            except ValidationError as e:
                return JsonResponse({'success': False, 'error': str(e)})

            # Payment method
            payment_method = data.get('payment_method')
            if not payment_method:
                return JsonResponse({'success': False, 'error': 'Payment method is required'})

            if payment_method not in dict(Payment.PAYMENT_METHOD_CHOICES):
                return JsonResponse({'success': False, 'error': 'Invalid payment method'})

            # Extra card validation if needed
            if payment_method == 'verve_card':
                card_validation = validate_card_details(data)
                if not card_validation['valid']:
                    return JsonResponse({'success': False, 'error': card_validation['error']})

            # Create or update payment record
            payment, created = Payment.objects.get_or_create(
                order=order,
                defaults={
                    'method': payment_method,
                    'amount': order.get_total,
                    'status': 'processing'
                }
            )

            if not created:
                payment.method = payment_method
                payment.amount = order.get_total
                payment.status = 'processing'
                payment.save()

            # Simulate processing
            payment_result = process_payment_by_method(payment, data)

            if payment_result['success']:
                payment.mark_as_completed(transaction_id=payment_result.get('transaction_id'))
                order.status = 'processing'
                order.payment_method = payment_method
                order.payment_date = timezone.now()
                order.expected_delivery_date = timezone.now() + timedelta(days=7)
                order.save()

                # Update product sold count
                for item in order.items.select_related('product'):
                    product = item.product
                    product.sold_count = (product.sold_count or 0) + item.quantity
                    product.save()

                logger.info(f"Payment successful for order {order.id}")

                return JsonResponse({
                    'success': True,
                    'message': 'Payment processed successfully',
                    'payment_id': str(payment.id),
                    'transaction_id': payment.transaction_id
                })
            else:
                payment.mark_as_failed(notes=payment_result.get('error'))
                logger.warning(f"Payment failed for order {order.id}: {payment_result.get('error')}")

                return JsonResponse({
                    'success': False,
                    'error': payment_result.get('error', 'Payment processing failed')
                })

    except Exception as e:
        logger.error(f"Payment processing error for order {order_id}: {str(e)}")
        return JsonResponse({'success': False, 'error': 'An unexpected error occurred. Please try again.'})


def validate_card_details(data):
    """Validate card payment details"""
    required_fields = ['card_number', 'expiry_date', 'cvv', 'cardholder_name']
    for field in required_fields:
        if not data.get(field):
            return {'valid': False, 'error': f'{field.replace("_", " ").title()} is required'}

    card_number = data.get('card_number', '').replace(' ', '')
    cvv = data.get('cvv', '')

    if not card_number.isdigit() or len(card_number) < 13 or len(card_number) > 19:
        return {'valid': False, 'error': 'Invalid card number'}
    if not cvv.isdigit() or len(cvv) not in [3, 4]:
        return {'valid': False, 'error': 'Invalid CVV'}

    return {'valid': True}


def process_payment_by_method(payment, data):
    """Route to payment method handler"""
    method = payment.method
    if method == 'cash':
        return process_cash_payment(payment, data)
    elif method in ['wave', 'qmoney', 'afrimoney']:
        return process_mobile_money_payment(payment, data)
    elif method == 'verve_card':
        return process_card_payment(payment, data)
    return {'success': False, 'error': 'Unsupported payment method'}


def process_cash_payment(payment, data):
    return {
        'success': True,
        'transaction_id': f'CASH_{payment.order.id}_{timezone.now().strftime("%Y%m%d%H%M%S")}'
    }


def process_mobile_money_payment(payment, data):
    phone_number = data.get('phone_number')
    if not phone_number:
        return {'success': False, 'error': 'Phone number is required for mobile money'}

    transaction_id = f'{payment.method.upper()}_{payment.order.id}_{timezone.now().strftime("%Y%m%d%H%M%S")}'
    return {'success': True, 'transaction_id': transaction_id}


def process_card_payment(payment, data):
    transaction_id = f'CARD_{payment.order.id}_{timezone.now().strftime("%Y%m%d%H%M%S")}'
    return {'success': True, 'transaction_id': transaction_id}


def handle_shipping_address(post_data, user):
    """Handle selecting or creating a shipping address"""
    shipping_id = post_data.get('shipping_address')

    if shipping_id == 'new':
        required_fields = ['new_full_name', 'new_phone_number', 'new_street', 'new_city', 'new_region', 'new_geo_code', 'new_country']
        missing = [f for f in required_fields if not post_data.get(f)]
        if missing:
            raise ValidationError("All shipping address fields are required.")

        return ShippingAddress.objects.create(
            user=user,
            full_name=post_data.get('new_full_name'),
            street=post_data.get('new_street'),
            city=post_data.get('new_city'),
            region=post_data.get('new_region'),
            geo_code=post_data.get('new_geo_code'),
            country=post_data.get('new_country'),
            phone_number=post_data.get('new_phone_number'),
            is_default=True  # Optional: mark new one as default
        )

    return get_object_or_404(ShippingAddress, id=shipping_id, user=user)
