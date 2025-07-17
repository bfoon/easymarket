from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import FinancialRecord, StoreFinancialSummary
from decimal import Decimal


@receiver(post_save, sender=FinancialRecord)
@receiver(post_delete, sender=FinancialRecord)
def update_financial_summary(sender, instance, **kwargs):
    """Update financial summary when financial records change"""
    # This would trigger recalculation of financial summaries
    # You can implement this based on your specific needs
    pass


# Signal handlers for automatic financial record creation
@receiver(post_save, sender='orders.OrderItem')
def create_revenue_record(sender, instance, created, **kwargs):
    """Automatically create revenue record when order is completed"""
    if instance.order.status == 'delivered':
        # Calculate revenue amount
        revenue_amount = instance.quantity * instance.price_at_time

        # Create financial record
        FinancialRecord.objects.get_or_create(
            store=instance.product.store,
            order_reference=str(instance.order.id),
            record_type='revenue',
            defaults={
                'amount': revenue_amount,
                'description': f'Sales revenue from order {instance.order.id}',
                'transaction_date': instance.order.updated_at.date(),
                'category': 'sales',
                'reference_number': f'ORD-{instance.order.id}',
                'is_confirmed': True,
            }
        )

        # Create commission record
        commission_amount = revenue_amount * (instance.product.store.commission_rate / 100)
        FinancialRecord.objects.get_or_create(
            store=instance.product.store,
            order_reference=str(instance.order.id),
            record_type='commission',
            defaults={
                'amount': commission_amount,
                'description': f'Platform commission ({instance.product.store.commission_rate}%) for order {instance.order.id}',
                'transaction_date': instance.order.updated_at.date(),
                'category': 'commission',
                'reference_number': f'COM-{instance.order.id}',
                'is_confirmed': True,
            }
        )


@receiver(post_save, sender='orders.Return')
def create_return_financial_records(sender, instance, created, **kwargs):
    """Create financial records for returns"""
    if instance.status == 'completed':
        for return_item in instance.items.all():
            # Create refund record
            refund_amount = return_item.quantity * return_item.return_price

            FinancialRecord.objects.get_or_create(
                store=return_item.product.store,
                return_reference=instance,
                record_type='refund',
                defaults={
                    'amount': refund_amount,
                    'description': f'Refund for return {instance.return_number}',
                    'transaction_date': instance.updated_at.date(),
                    'category': 'returns',
                    'reference_number': instance.return_number,
                    'is_confirmed': True,
                }
            )

            # Create return processing cost
            processing_cost = refund_amount * Decimal('0.05')  # 5% processing cost
            FinancialRecord.objects.get_or_create(
                store=return_item.product.store,
                return_reference=instance,
                record_type='return_cost',
                defaults={
                    'amount': processing_cost,
                    'description': f'Return processing cost for {instance.return_number}',
                    'transaction_date': instance.updated_at.date(),
                    'category': 'returns',
                    'reference_number': f'RPC-{instance.return_number}',
                    'is_confirmed': True,
                }
            )
