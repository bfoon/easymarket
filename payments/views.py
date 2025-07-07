from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db import transaction
from datetime import timedelta
import json
import logging

from orders.models import Order
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
                return JsonResponse({
                    'success': False,
                    'error': 'Order is not in pending status'
                })

            # Check if payment already exists
            if hasattr(order, 'payment_record') and order.payment_record:
                if order.payment_record.is_successful():
                    return JsonResponse({
                        'success': False,
                        'error': 'Order is already paid'
                    })

            # Get payment details from request
            if request.content_type == 'application/json':
                data = json.loads(request.body)
            else:
                data = request.POST

            payment_method = data.get('payment_method')

            # Basic validation
            if not payment_method:
                return JsonResponse({
                    'success': False,
                    'error': 'Payment method is required'
                })

            if payment_method not in dict(Payment.PAYMENT_METHOD_CHOICES):
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid payment method'
                })

            # Handle different payment methods
            if payment_method == 'verve_card':
                card_validation = validate_card_details(data)
                if not card_validation['valid']:
                    return JsonResponse({
                        'success': False,
                        'error': card_validation['error']
                    })

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
                # Update existing payment
                payment.method = payment_method
                payment.amount = order.get_total
                payment.status = 'processing'
                payment.save()

            # Process payment based on method
            payment_result = process_payment_by_method(payment, data)

            if payment_result['success']:
                # Mark payment as completed
                payment.mark_as_completed(
                    transaction_id=payment_result.get('transaction_id')
                )

                # Update order status
                order.status = 'processing'
                order.payment_method = payment_method
                order.payment_date = timezone.now()
                order.expected_delivery_date = timezone.now() + timedelta(days=7)
                order.save()

                logger.info(f"Payment successful for order {order.id}")

                return JsonResponse({
                    'success': True,
                    'message': 'Payment processed successfully',
                    'payment_id': str(payment.id),
                    'transaction_id': payment.transaction_id
                })
            else:
                # Mark payment as failed
                payment.mark_as_failed(notes=payment_result.get('error'))

                logger.warning(f"Payment failed for order {order.id}: {payment_result.get('error')}")

                return JsonResponse({
                    'success': False,
                    'error': payment_result.get('error', 'Payment processing failed')
                })

    except Exception as e:
        logger.error(f"Payment processing error for order {order_id}: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'An unexpected error occurred. Please try again.'
        })


def validate_card_details(data):
    """Validate card payment details"""
    required_fields = ['card_number', 'expiry_date', 'cvv', 'cardholder_name']

    for field in required_fields:
        if not data.get(field):
            return {
                'valid': False,
                'error': f'{field.replace("_", " ").title()} is required'
            }

    card_number = data.get('card_number', '').replace(' ', '')
    cvv = data.get('cvv', '')

    # Basic card number validation
    if not card_number.isdigit() or len(card_number) < 13 or len(card_number) > 19:
        return {'valid': False, 'error': 'Invalid card number'}

    # CVV validation
    if not cvv.isdigit() or len(cvv) not in [3, 4]:
        return {'valid': False, 'error': 'Invalid CVV'}

    return {'valid': True}


def process_payment_by_method(payment, data):
    """Process payment based on payment method"""
    method = payment.method

    if method == 'cash':
        return process_cash_payment(payment, data)
    elif method in ['wave', 'qmoney', 'afrimoney']:
        return process_mobile_money_payment(payment, data)
    elif method == 'verve_card':
        return process_card_payment(payment, data)
    else:
        return {'success': False, 'error': 'Unsupported payment method'}


def process_cash_payment(payment, data):
    """Process cash payment"""
    # Cash payments are typically confirmed manually
    return {
        'success': True,
        'transaction_id': f'CASH_{payment.order.id}_{timezone.now().strftime("%Y%m%d%H%M%S")}'
    }


def process_mobile_money_payment(payment, data):
    """Process mobile money payment"""
    phone_number = data.get('phone_number')

    if not phone_number:
        return {'success': False, 'error': 'Phone number is required for mobile money'}

    # Here you would integrate with mobile money APIs
    # For now, simulate successful payment
    transaction_id = f'{payment.method.upper()}_{payment.order.id}_{timezone.now().strftime("%Y%m%d%H%M%S")}'

    return {
        'success': True,
        'transaction_id': transaction_id
    }


def process_card_payment(payment, data):
    """Process card payment"""
    # Here you would integrate with your card payment processor
    # For now, simulate successful payment

    # In production, you would:
    # 1. Call payment gateway API
    # 2. Handle response
    # 3. Return appropriate result

    transaction_id = f'CARD_{payment.order.id}_{timezone.now().strftime("%Y%m%d%H%M%S")}'

    return {
        'success': True,
        'transaction_id': transaction_id
    }


@login_required
def payment_status(request, payment_id):
    """Get payment status"""
    payment = get_object_or_404(Payment, id=payment_id, order__buyer=request.user)

    return JsonResponse({
        'payment_id': str(payment.id),
        'order_id': payment.order.id,
        'status': payment.status,
        'method': payment.method,
        'amount': str(payment.amount),
        'transaction_id': payment.transaction_id,
        'created_at': payment.created_at.isoformat(),
        'payment_date': payment.payment_date.isoformat() if payment.payment_date else None,
    })


@login_required
def refund_payment(request, payment_id):
    """Process refund for a payment"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'})

    try:
        with transaction.atomic():
            payment = get_object_or_404(Payment, id=payment_id, order__buyer=request.user)

            if not payment.can_be_refunded():
                return JsonResponse({
                    'success': False,
                    'error': 'Payment cannot be refunded'
                })

            # Get refund details
            if request.content_type == 'application/json':
                data = json.loads(request.body)
            else:
                data = request.POST

            refund_amount = data.get('refund_amount')
            refund_reason = data.get('refund_reason', '')

            # If no amount specified, refund full amount
            if not refund_amount:
                refund_amount = payment.remaining_refundable_amount
            else:
                refund_amount = float(refund_amount)

            # Process refund
            actual_refund = payment.process_refund(
                refund_amount=refund_amount,
                notes=refund_reason
            )

            logger.info(f"Refund processed for payment {payment.id}: {actual_refund}")

            return JsonResponse({
                'success': True,
                'message': 'Refund processed successfully',
                'refund_amount': str(actual_refund),
                'remaining_refundable': str(payment.remaining_refundable_amount)
            })

    except Exception as e:
        logger.error(f"Refund processing error for payment {payment_id}: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
def payment_history(request, order_id):
    """Get payment history for an order"""
    order = get_object_or_404(Order, id=order_id, buyer=request.user)

    if not hasattr(order, 'payment_record') or not order.payment_record:
        return JsonResponse({
            'success': False,
            'error': 'No payment record found for this order'
        })

    payment = order.payment_record

    return JsonResponse({
        'success': True,
        'payment': {
            'id': str(payment.id),
            'status': payment.status,
            'method': payment.method,
            'amount': str(payment.amount),
            'transaction_id': payment.transaction_id,
            'created_at': payment.created_at.isoformat(),
            'payment_date': payment.payment_date.isoformat() if payment.payment_date else None,
            'refund_amount': str(payment.refund_amount),
            'refund_date': payment.refund_date.isoformat() if payment.refund_date else None,
            'notes': payment.notes,
            'can_be_refunded': payment.can_be_refunded(),
            'is_successful': payment.is_successful(),
        }
    })


# Webhook handlers for payment gateways
@csrf_exempt
def payment_webhook(request):
    """Handle payment gateway webhooks"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        # Parse webhook data
        if request.content_type == 'application/json':
            data = json.loads(request.body)
        else:
            data = request.POST.dict()

        # Verify webhook signature (implement based on your gateway)
        # if not verify_webhook_signature(request, data):
        #     return JsonResponse({'error': 'Invalid signature'}, status=400)

        transaction_id = data.get('transaction_id')
        status = data.get('status')

        if not transaction_id:
            return JsonResponse({'error': 'Missing transaction_id'}, status=400)

        # Find payment by transaction_id
        try:
            payment = Payment.objects.get(transaction_id=transaction_id)
        except Payment.DoesNotExist:
            logger.warning(f"Payment not found for transaction_id: {transaction_id}")
            return JsonResponse({'error': 'Payment not found'}, status=404)

        # Update payment status based on webhook
        if status == 'success':
            payment.mark_as_completed()
            # Update order status
            payment.order.status = 'processing'
            payment.order.save()
        elif status == 'failed':
            payment.mark_as_failed(notes=data.get('failure_reason'))

        logger.info(f"Webhook processed for payment {payment.id}: {status}")

        return JsonResponse({'success': True})

    except Exception as e:
        logger.error(f"Webhook processing error: {str(e)}")
        return JsonResponse({'error': 'Internal server error'}, status=500)