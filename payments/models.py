from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal
from orders.models import Order


class Payment(models.Model):
    """Track payment information for orders"""
    PAYMENT_METHOD_CHOICES = [
        ('wave', 'Wave'),
        ('qmoney', 'Qmoney'),
        ('afrimoney', 'Afrimoney'),
        ('cash', 'Cash Payment'),
        ('verve_card', 'Verve Card'),
    ]

    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
    ]

    # Core fields
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='payment_record')
    method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    transaction_id = models.CharField(max_length=100, blank=True, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    # Payment tracking
    payment_date = models.DateTimeField(blank=True, null=True)
    refund_date = models.DateTimeField(blank=True, null=True)
    refund_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Payment'
        verbose_name_plural = 'Payments'

    def __str__(self):
        return f"Payment for Order #{self.order.id} - {self.get_status_display()}"

    def clean(self):
        """Validate the payment instance"""
        if self.amount <= 0:
            raise ValidationError("Amount must be greater than zero")

        if self.refund_amount > self.amount:
            raise ValidationError("Refund amount cannot exceed payment amount")

    def save(self, *args, **kwargs):
        """Override save to handle automatic timestamps"""
        # Set payment_date when status changes to completed
        if self.status == 'completed' and not self.payment_date:
            self.payment_date = timezone.now()

        # Set refund_date when status changes to refunded
        if self.status == 'refunded' and not self.refund_date:
            self.refund_date = timezone.now()

        self.full_clean()
        super().save(*args, **kwargs)

    # Status check methods
    def is_successful(self):
        """Check if payment was successful"""
        return self.status == 'completed'

    def is_pending(self):
        """Check if payment is pending"""
        return self.status == 'pending'

    def is_failed(self):
        """Check if payment failed"""
        return self.status == 'failed'

    def is_refunded(self):
        """Check if payment was refunded"""
        return self.status == 'refunded'

    def can_be_refunded(self):
        """Check if payment can be refunded"""
        return self.status == 'completed' and self.refund_amount < self.amount

    def can_be_cancelled(self):
        """Check if payment can be cancelled"""
        return self.status in ['pending', 'processing']

    # Action methods
    def mark_as_completed(self, transaction_id=None):
        """Mark payment as completed"""
        self.status = 'completed'
        self.payment_date = timezone.now()
        if transaction_id:
            self.transaction_id = transaction_id
        self.save()

    def mark_as_failed(self, notes=None):
        """Mark payment as failed"""
        self.status = 'failed'
        if notes:
            self.notes = notes
        self.save()

    def mark_as_cancelled(self):
        """Mark payment as cancelled"""
        if self.can_be_cancelled():
            self.status = 'failed'  # or add 'cancelled' to choices
            self.save()
        else:
            raise ValidationError("Payment cannot be cancelled in current status")

    def process_refund(self, refund_amount=None, notes=None):
        """Process a refund for this payment"""
        if not self.can_be_refunded():
            raise ValidationError("Payment cannot be refunded")

        if refund_amount is None:
            refund_amount = self.amount - self.refund_amount

        if self.refund_amount + refund_amount > self.amount:
            raise ValidationError("Total refund amount cannot exceed payment amount")

        self.refund_amount += refund_amount
        self.refund_date = timezone.now()

        # Mark as refunded if fully refunded
        if self.refund_amount >= self.amount:
            self.status = 'refunded'

        if notes:
            self.notes = f"{self.notes or ''}\nRefund: {notes}".strip()

        self.save()
        return refund_amount

    # Property methods
    @property
    def is_mobile_money(self):
        """Check if payment method is mobile money"""
        return self.method in ['wave', 'qmoney', 'afrimoney']

    @property
    def is_card_payment(self):
        """Check if payment method is card"""
        return self.method == 'verve_card'

    @property
    def is_cash_payment(self):
        """Check if payment method is cash"""
        return self.method == 'cash'

    @property
    def remaining_refundable_amount(self):
        """Get the amount that can still be refunded"""
        return self.amount - self.refund_amount

    @property
    def is_partial_refund(self):
        """Check if this is a partial refund"""
        return self.refund_amount > 0 and self.refund_amount < self.amount

    # Class methods for analytics
    @classmethod
    def get_successful_payments(cls):
        """Get all successful payments"""
        return cls.objects.filter(status='completed')

    @classmethod
    def get_failed_payments(cls):
        """Get all failed payments"""
        return cls.objects.filter(status='failed')

    @classmethod
    def get_pending_payments(cls):
        """Get all pending payments"""
        return cls.objects.filter(status='pending')

    @classmethod
    def get_refunded_payments(cls):
        """Get all refunded payments"""
        return cls.objects.filter(status='refunded')

    @classmethod
    def get_total_revenue(cls):
        """Get total revenue from successful payments"""
        from django.db.models import Sum
        return cls.get_successful_payments().aggregate(
            total=Sum('amount')
        )['total'] or 0

    @classmethod
    def get_total_refunds(cls):
        """Get total amount refunded"""
        from django.db.models import Sum
        return cls.objects.aggregate(
            total=Sum('refund_amount')
        )['total'] or 0


# Alias for backward compatibility if needed
OrderPayment = Payment