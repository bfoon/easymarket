from django.db import models
from django.utils import timezone
from decimal import Decimal
from django.contrib.auth.models import User
from stores.models import Store  # Import your existing Store model
from django.conf import settings


class FinancialRecord(models.Model):
    RECORD_TYPES = [
        ('revenue', 'Revenue'),
        ('expense', 'Expense'),
        ('refund', 'Refund'),
        ('commission', 'Commission'),
        ('return_cost', 'Return Processing Cost'),
        ('shipping_cost', 'Shipping Cost'),
        ('platform_fee', 'Platform Fee'),
        ('marketing', 'Marketing Expense'),
        ('operational', 'Operational Cost'),
    ]

    CATEGORY_CHOICES = [
        ('sales', 'Sales Revenue'),
        ('commission', 'Commission Fees'),
        ('shipping', 'Shipping & Logistics'),
        ('returns', 'Returns & Refunds'),
        ('marketing', 'Marketing & Advertising'),
        ('operations', 'Operations'),
        ('platform', 'Platform Fees'),
        ('tax', 'Taxes'),
        ('other', 'Other'),
    ]

    # Use regular auto-incrementing primary key
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='financial_records')
    record_type = models.CharField(max_length=20, choices=RECORD_TYPES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.TextField()
    transaction_date = models.DateField()
    category = models.CharField(max_length=100, choices=CATEGORY_CHOICES, default='other')
    reference_number = models.CharField(max_length=100, blank=True)

    # Link to existing models
    order_reference = models.CharField(max_length=100, blank=True, null=True)
    return_reference = models.ForeignKey(
        'orders.Return',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='financial_records'
    )

    # Additional fields for better tracking
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    is_confirmed = models.BooleanField(default=True)
    notes = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-transaction_date', '-created_at']
        indexes = [
            models.Index(fields=['store', 'transaction_date']),
            models.Index(fields=['record_type', 'transaction_date']),
            models.Index(fields=['store', 'category']),
        ]

    def __str__(self):
        return f"{self.store.name} - {self.get_record_type_display()} - ${self.amount}"


class StoreFinancialSummary(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='financial_summaries')
    period_start = models.DateField()
    period_end = models.DateField()

    # Revenue breakdown
    total_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    commission_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Expense breakdown
    total_expenses = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    commission_expenses = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_expenses = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    return_costs = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    marketing_expenses = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    operational_expenses = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Returns and refunds
    total_refunds = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_returns_processed = models.IntegerField(default=0)

    # Calculated fields
    gross_profit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_profit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    profit_margin_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['store', 'period_start', 'period_end']
        ordering = ['-period_start']
        verbose_name = 'Store Financial Summary'
        verbose_name_plural = 'Store Financial Summaries'

    def save(self, *args, **kwargs):
        # Auto-calculate profit fields
        self.gross_profit = self.total_revenue - self.total_expenses
        self.net_profit = self.gross_profit - self.total_refunds
        if self.total_revenue > 0:
            self.profit_margin_percentage = (self.net_profit / self.total_revenue) * 100
        super().save(*args, **kwargs)


# Enhanced logistics integration that leverages existing Store methods
class LogisticsIntegration(models.Model):
    """Integration with logistics data - enhanced for your Store model"""

    store = models.OneToOneField(Store, on_delete=models.CASCADE, related_name='logistics_summary')

    # Leverage existing Store methods for real-time data
    @property
    def total_orders(self):
        return self.store.get_total_orders()

    @property
    def total_sales_amount(self):
        return self.store.get_total_sales()

    # Additional logistics metrics not covered by Store model
    total_shipments = models.IntegerField(default=0)
    pending_shipments = models.IntegerField(default=0)
    completed_shipments = models.IntegerField(default=0)
    failed_shipments = models.IntegerField(default=0)

    # Enhanced metrics
    average_processing_time = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    average_delivery_time = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    total_shipping_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # Return logistics (integration with existing return system)
    total_return_shipments = models.IntegerField(default=0)
    pending_return_pickups = models.IntegerField(default=0)
    completed_return_pickups = models.IntegerField(default=0)

    # Performance metrics
    on_time_delivery_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    return_rate_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    customer_satisfaction_score = models.DecimalField(max_digits=3, decimal_places=2, default=0)

    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Logistics Integration'
        verbose_name_plural = 'Logistics Integrations'

    def __str__(self):
        return f"Logistics Summary - {self.store.name}"

    @property
    def delivery_success_rate(self):
        """Calculate delivery success rate"""
        if self.total_shipments > 0:
            return (self.completed_shipments / self.total_shipments) * 100
        return 0

    @property
    def average_rating(self):
        """Get average rating from Store model"""
        return self.store.get_average_rating()


# Enhanced model to integrate with existing StoreMetrics
class FinancialMetricsIntegration(models.Model):
    """Integration layer between finance app and existing StoreMetrics"""

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='financial_metrics_integration')
    date = models.DateField()

    # Financial KPIs derived from FinancialRecord
    daily_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    daily_expenses = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    daily_profit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    daily_commission_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Return financial impact
    daily_return_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    daily_refund_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Integration with existing StoreMetrics
    store_metrics = models.OneToOneField(
        'stores.StoreMetrics',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='financial_integration'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['store', 'date']
        ordering = ['-date']
        verbose_name = 'Financial Metrics Integration'
        verbose_name_plural = 'Financial Metrics Integrations'

    def __str__(self):
        return f"{self.store.name} - Financial Metrics - {self.date}"

    @classmethod
    def sync_with_store_metrics(cls, store, date=None):
        """Sync financial data with existing StoreMetrics"""
        if date is None:
            date = timezone.now().date()

        from stores.models import StoreMetrics

        # Get or create StoreMetrics (using existing model)
        store_metrics = StoreMetrics.calculate_daily_metrics(store, date)

        # Get or create financial integration
        financial_metrics, created = cls.objects.get_or_create(
            store=store,
            date=date,
            defaults={'store_metrics': store_metrics}
        )

        # Calculate financial metrics from FinancialRecord
        daily_records = FinancialRecord.objects.filter(
            store=store,
            transaction_date=date
        )

        financial_metrics.daily_revenue = daily_records.filter(
            record_type='revenue'
        ).aggregate(total=models.Sum('amount'))['total'] or 0

        financial_metrics.daily_expenses = daily_records.filter(
            record_type='expense'
        ).aggregate(total=models.Sum('amount'))['total'] or 0

        financial_metrics.daily_refund_amount = daily_records.filter(
            record_type='refund'
        ).aggregate(total=models.Sum('amount'))['total'] or 0

        financial_metrics.daily_commission_paid = daily_records.filter(
            record_type='commission'
        ).aggregate(total=models.Sum('amount'))['total'] or 0

        financial_metrics.daily_return_cost = daily_records.filter(
            record_type='return_cost'
        ).aggregate(total=models.Sum('amount'))['total'] or 0

        financial_metrics.daily_profit = (
                financial_metrics.daily_revenue -
                financial_metrics.daily_expenses -
                financial_metrics.daily_refund_amount
        )

        financial_metrics.store_metrics = store_metrics
        financial_metrics.save()

        return financial_metrics
