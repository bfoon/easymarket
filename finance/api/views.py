from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Q, Avg, Count
from django.utils import timezone
from datetime import timedelta
from stores.models import Store, StoreCategory  # Import from stores app
from ..models import FinancialRecord, LogisticsIntegration, StoreFinancialSummary, FinancialMetricsIntegration
from .serializers import (
    StoreSerializer, FinancialRecordSerializer, LogisticsIntegrationSerializer,
    StoreFinancialSummarySerializer, ComprehensiveStoreSerializer,
    FinancialMetricsIntegrationSerializer
)
import django_filters


class StoreFilter(django_filters.FilterSet):
    category = django_filters.CharFilter(field_name='category__slug')
    store_type = django_filters.ChoiceFilter(choices=Store.STORE_TYPE_CHOICES)
    status = django_filters.ChoiceFilter(choices=Store.STORE_STATUS_CHOICES)
    is_featured = django_filters.BooleanFilter()
    min_commission = django_filters.NumberFilter(field_name='commission_rate', lookup_expr='gte')
    max_commission = django_filters.NumberFilter(field_name='commission_rate', lookup_expr='lte')

    class Meta:
        model = Store
        fields = ['category', 'store_type', 'status', 'is_featured']


class StoreViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for Store model - read-only since stores are managed in stores app
    """
    queryset = Store.objects.filter(status='active')
    serializer_class = StoreSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [django_filters.DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = StoreFilter
    search_fields = ['name', 'description', 'city', 'region']
    ordering_fields = ['name', 'created_at', 'commission_rate']
    ordering = ['-created_at']
    lookup_field = 'id'  # Use UUID

    def get_serializer_class(self):
        if self.action == 'comprehensive':
            return ComprehensiveStoreSerializer
        return StoreSerializer

    @action(detail=True, methods=['get'])
    def financial_summary(self, request, id=None):
        """Get comprehensive financial summary for a store"""
        store = self.get_object()

        # Get date range from query params
        days = int(request.query_params.get('days', 30))
        start_date = timezone.now().date() - timedelta(days=days)

        # Financial summary
        financial_data = FinancialRecord.objects.filter(
            store=store,
            transaction_date__gte=start_date
        ).aggregate(
            total_revenue=Sum('amount', filter=Q(record_type='revenue')) or 0,
            total_expenses=Sum('amount', filter=Q(record_type='expense')) or 0,
            total_refunds=Sum('amount', filter=Q(record_type='refund')) or 0,
            total_commissions=Sum('amount', filter=Q(record_type='commission')) or 0,
            return_costs=Sum('amount', filter=Q(record_type='return_cost')) or 0,
            shipping_costs=Sum('amount', filter=Q(record_type='shipping_cost')) or 0,
        )

        # Calculate metrics
        gross_profit = (financial_data['total_revenue'] or 0) - (financial_data['total_expenses'] or 0)
        net_profit = gross_profit - (financial_data['total_refunds'] or 0) - (financial_data['return_costs'] or 0)

        # Category breakdown
        category_breakdown = FinancialRecord.objects.filter(
            store=store,
            transaction_date__gte=start_date
        ).values('category').annotate(
            total_amount=Sum('amount'),
            record_count=Count('id')
        ).order_by('-total_amount')

        # Get logistics data
        logistics_data = LogisticsIntegration.objects.filter(store=store).first()

        return Response({
            'store': StoreSerializer(store).data,
            'period': {
                'start_date': start_date,
                'end_date': timezone.now().date(),
                'days': days
            },
            'financial_summary': {
                **financial_data,
                'gross_profit': gross_profit,
                'net_profit': net_profit,
                'profit_margin': (net_profit / financial_data['total_revenue'] * 100) if financial_data[
                    'total_revenue'] else 0
            },
            'category_breakdown': category_breakdown,
            'logistics_data': LogisticsIntegrationSerializer(logistics_data).data if logistics_data else None,
            'store_metrics': {
                'total_products': store.get_total_products(),
                'total_orders': store.get_total_orders(),
                'lifetime_sales': float(store.get_total_sales()),
                'average_rating': float(store.get_average_rating()),
            }
        })

    @action(detail=True, methods=['get'])
    def comprehensive(self, request, id=None):
        """Get comprehensive store data including financial and logistics"""
        store = self.get_object()
        serializer = self.get_serializer(store)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def performance_comparison(self, request):
        """Compare performance across all stores"""
        stores_with_metrics = Store.objects.filter(
            status='active'
        ).annotate(
            total_revenue=Sum('financial_records__amount',
                              filter=Q(financial_records__record_type='revenue')),
            total_expenses=Sum('financial_records__amount',
                               filter=Q(financial_records__record_type='expense')),
            total_orders=Count('products__orderitem__order', distinct=True),
        ).order_by('-total_revenue')

        performance_data = []
        for store in stores_with_metrics:
            net_profit = (store.total_revenue or 0) - (store.total_expenses or 0)
            performance_data.append({
                'store_id': store.id,
                'store_name': store.name,
                'total_revenue': store.total_revenue or 0,
                'total_expenses': store.total_expenses or 0,
                'net_profit': net_profit,
                'total_orders': store.total_orders or 0,
                'commission_rate': float(store.commission_rate),
                'average_rating': float(store.get_average_rating()),
                'store_type': store.store_type,
            })

        return Response({
            'performance_data': performance_data,
            'summary': {
                'total_stores': len(performance_data),
                'total_revenue_all': sum(item['total_revenue'] for item in performance_data),
                'total_orders_all': sum(item['total_orders'] for item in performance_data),
                'avg_commission_rate': sum(item['commission_rate'] for item in performance_data) / len(
                    performance_data) if performance_data else 0,
            }
        })


class FinancialRecordViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing financial records
    """
    queryset = FinancialRecord.objects.all()
    serializer_class = FinancialRecordSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [django_filters.DjangoFilterBackend, filters.OrderingFilter]
    ordering_fields = ['transaction_date', 'amount', 'created_at']
    ordering = ['-transaction_date', '-created_at']

    def get_queryset(self):
        queryset = FinancialRecord.objects.all()

        # Filter by store (UUID)
        store_id = self.request.query_params.get('store_id')
        if store_id:
            queryset = queryset.filter(store_id=store_id)

        # Filter by record type
        record_type = self.request.query_params.get('record_type')
        if record_type:
            queryset = queryset.filter(record_type=record_type)

        # Filter by category
        category = self.request.query_params.get('category')
        if category:
            queryset = queryset.filter(category=category)

        # Filter by date range
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            queryset = queryset.filter(transaction_date__gte=date_from)
        if date_to:
            queryset = queryset.filter(transaction_date__lte=date_to)

        return queryset

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Get financial summary across all or filtered records"""
        queryset = self.filter_queryset(self.get_queryset())

        summary = queryset.aggregate(
            total_revenue=Sum('amount', filter=Q(record_type='revenue')) or 0,
            total_expenses=Sum('amount', filter=Q(record_type='expense')) or 0,
            total_refunds=Sum('amount', filter=Q(record_type='refund')) or 0,
            total_commissions=Sum('amount', filter=Q(record_type='commission')) or 0,
            return_costs=Sum('amount', filter=Q(record_type='return_cost')) or 0,
            record_count=Count('id')
        )

        net_profit = (summary['total_revenue'] or 0) - (summary['total_expenses'] or 0) - (
                    summary['total_refunds'] or 0)
        summary['net_profit'] = net_profit

        return Response(summary)


class LogisticsIntegrationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for logistics integration data - read-only
    """
    queryset = LogisticsIntegration.objects.all()
    serializer_class = LogisticsIntegrationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = LogisticsIntegration.objects.all()
        store_id = self.request.query_params.get('store_id')
        if store_id:
            queryset = queryset.filter(store_id=store_id)
        return queryset


class FinancialMetricsViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for financial metrics integration
    """
    queryset = FinancialMetricsIntegration.objects.all()
    serializer_class = FinancialMetricsIntegrationSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [django_filters.DjangoFilterBackend, filters.OrderingFilter]
    ordering = ['-date']

    def get_queryset(self):
        queryset = FinancialMetricsIntegration.objects.all()

        store_id = self.request.query_params.get('store_id')
        if store_id:
            queryset = queryset.filter(store_id=store_id)

        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            queryset = queryset.filter(date__gte=date_from)
        if date_to:
            queryset = queryset.filter(date__lte=date_to)

        return queryset

    @action(detail=False, methods=['get'])
    def trends(self, request):
        """Get trending data for financial metrics"""
        days = int(request.query_params.get('days', 30))
        store_id = request.query_params.get('store_id')

        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=days)

        queryset = self.get_queryset().filter(
            date__range=[start_date, end_date]
        )

        if store_id:
            queryset = queryset.filter(store_id=store_id)

        trends = queryset.values('date').annotate(
            total_revenue=Sum('daily_revenue'),
            total_expenses=Sum('daily_expenses'),
            total_profit=Sum('daily_profit'),
            total_returns=Sum('daily_return_cost')
        ).order_by('date')

        return Response({
            'period': {
                'start_date': start_date,
                'end_date': end_date,
                'days': days
            },
            'trends': list(trends)
        })