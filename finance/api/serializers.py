from rest_framework import serializers
from stores.models import Store, StoreCategory  # Import from stores app
from ..models import FinancialRecord, LogisticsIntegration, StoreFinancialSummary, FinancialMetricsIntegration


class StoreCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = StoreCategory
        fields = ['id', 'name', 'slug', 'description']


class StoreSerializer(serializers.ModelSerializer):
    category = StoreCategorySerializer(read_only=True)
    total_products = serializers.SerializerMethodField()
    total_orders = serializers.SerializerMethodField()
    total_sales = serializers.SerializerMethodField()
    average_rating = serializers.SerializerMethodField()
    store_type_display = serializers.CharField(source='get_store_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Store
        fields = [
            'id', 'name', 'slug', 'description', 'short_description',
            'store_type', 'store_type_display', 'status', 'status_display',
            'category', 'email', 'phone', 'website',
            'city', 'region', 'country', 'commission_rate',
            'processing_time', 'return_policy_days', 'is_featured',
            'total_products', 'total_orders', 'total_sales', 'average_rating',
            'created_at', 'updated_at'
        ]

    def get_total_products(self, obj):
        return obj.get_total_products()

    def get_total_orders(self, obj):
        return obj.get_total_orders()

    def get_total_sales(self, obj):
        return float(obj.get_total_sales())

    def get_average_rating(self, obj):
        return float(obj.get_average_rating())


class FinancialRecordSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    record_type_display = serializers.CharField(source='get_record_type_display', read_only=True)
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    processed_by_username = serializers.CharField(source='processed_by.username', read_only=True)

    class Meta:
        model = FinancialRecord
        fields = [
            'id', 'store', 'store_name', 'record_type', 'record_type_display',
            'amount', 'description', 'transaction_date', 'category', 'category_display',
            'reference_number', 'order_reference', 'processed_by', 'processed_by_username',
            'is_confirmed', 'notes', 'created_at', 'updated_at'
        ]


class LogisticsIntegrationSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    total_orders = serializers.ReadOnlyField()  # This uses the property
    total_sales_amount = serializers.ReadOnlyField()  # This uses the property
    delivery_success_rate = serializers.ReadOnlyField()  # This uses the property
    average_rating = serializers.ReadOnlyField()  # This uses the property

    class Meta:
        model = LogisticsIntegration
        fields = [
            'id', 'store', 'store_name', 'total_orders', 'total_sales_amount',
            'total_shipments', 'pending_shipments', 'completed_shipments', 'failed_shipments',
            'average_processing_time', 'average_delivery_time', 'total_shipping_cost',
            'total_return_shipments', 'pending_return_pickups', 'completed_return_pickups',
            'on_time_delivery_rate', 'return_rate_percentage', 'customer_satisfaction_score',
            'delivery_success_rate', 'average_rating', 'last_updated'
        ]


class StoreFinancialSummarySerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)

    class Meta:
        model = StoreFinancialSummary
        fields = [
            'id', 'store', 'store_name', 'period_start', 'period_end',
            'total_revenue', 'commission_revenue', 'shipping_revenue',
            'total_expenses', 'commission_expenses', 'shipping_expenses',
            'return_costs', 'marketing_expenses', 'operational_expenses',
            'total_refunds', 'total_returns_processed',
            'gross_profit', 'net_profit', 'profit_margin_percentage',
            'created_at', 'updated_at'
        ]


class FinancialMetricsIntegrationSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    store_metrics = serializers.SerializerMethodField()

    class Meta:
        model = FinancialMetricsIntegration
        fields = [
            'id', 'store', 'store_name', 'date',
            'daily_revenue', 'daily_expenses', 'daily_profit',
            'daily_commission_paid', 'daily_return_cost', 'daily_refund_amount',
            'store_metrics', 'created_at', 'updated_at'
        ]

    def get_store_metrics(self, obj):
        if obj.store_metrics:
            return {
                'total_orders': obj.store_metrics.total_orders,
                'total_sales': float(obj.store_metrics.total_sales),
                'total_items_sold': obj.store_metrics.total_items_sold,
                'total_returns': obj.store_metrics.total_returns,
                'return_rate_percentage': float(obj.store_metrics.return_rate_percentage),
                'new_customers': obj.store_metrics.new_customers,
                'repeat_customers': obj.store_metrics.repeat_customers,
                'average_rating': float(obj.store_metrics.average_rating),
            }
        return None


class ComprehensiveStoreSerializer(serializers.ModelSerializer):
    """Comprehensive serializer that includes financial and logistics data"""
    category = StoreCategorySerializer(read_only=True)
    financial_summary = serializers.SerializerMethodField()
    logistics_data = LogisticsIntegrationSerializer(source='logistics_summary', read_only=True)
    recent_financial_records = serializers.SerializerMethodField()
    store_metrics = serializers.SerializerMethodField()

    class Meta:
        model = Store
        fields = [
            'id', 'name', 'slug', 'description', 'store_type', 'status',
            'category', 'commission_rate', 'processing_time', 'return_policy_days',
            'financial_summary', 'logistics_data', 'recent_financial_records',
            'store_metrics', 'created_at'
        ]

    def get_financial_summary(self, obj):
        from django.db.models import Sum, Q
        from django.utils import timezone

        # Get current month data
        current_month = timezone.now().replace(day=1).date()

        summary = obj.financial_records.filter(
            transaction_date__gte=current_month
        ).aggregate(
            total_revenue=Sum('amount', filter=Q(record_type='revenue')) or 0,
            total_expenses=Sum('amount', filter=Q(record_type='expense')) or 0,
            total_refunds=Sum('amount', filter=Q(record_type='refund')) or 0,
            return_costs=Sum('amount', filter=Q(record_type='return_cost')) or 0,
        )

        # Calculate net profit
        net_profit = (
                (summary['total_revenue'] or 0) -
                (summary['total_expenses'] or 0) -
                (summary['total_refunds'] or 0) -
                (summary['return_costs'] or 0)
        )

        summary['net_profit'] = net_profit
        return summary

    def get_recent_financial_records(self, obj):
        recent_records = obj.financial_records.order_by('-transaction_date')[:5]
        return FinancialRecordSerializer(recent_records, many=True).data

    def get_store_metrics(self, obj):
        return {
            'total_products': obj.get_total_products(),
            'total_orders': obj.get_total_orders(),
            'lifetime_sales': float(obj.get_total_sales()),
            'average_rating': float(obj.get_average_rating()),
        }
