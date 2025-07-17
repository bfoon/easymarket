from django.contrib import admin
from stores.models import Store  # Import from stores app
from .models import FinancialRecord, StoreFinancialSummary, LogisticsIntegration

# Note: Store admin should be in stores/admin.py, not here
# Only register finance-specific models

@admin.register(FinancialRecord)
class FinancialRecordAdmin(admin.ModelAdmin):
    list_display = ['store', 'record_type', 'amount', 'category', 'transaction_date']
    list_filter = ['record_type', 'category', 'transaction_date', 'store']
    search_fields = ['store__name', 'description', 'reference_number']
    date_hierarchy = 'transaction_date'

@admin.register(StoreFinancialSummary)
class StoreFinancialSummaryAdmin(admin.ModelAdmin):
    list_display = ['store', 'period_start', 'period_end', 'total_revenue', 'net_profit']
    list_filter = ['period_start', 'store']
    readonly_fields = ['created_at', 'updated_at']

@admin.register(LogisticsIntegration)
class LogisticsIntegrationAdmin(admin.ModelAdmin):
    list_display = ['store', 'total_shipments', 'total_orders', 'pending_shipments', 'last_updated']
    list_filter = ['last_updated']
    readonly_fields = ['last_updated']