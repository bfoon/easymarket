from django.core.management.base import BaseCommand
from django.db.models import Sum, Avg, Count, Q
from stores.models import Store  # Import from stores app
from finance.models import LogisticsIntegration, FinancialRecord, FinancialMetricsIntegration
from datetime import timedelta
from django.utils import timezone


class Command(BaseCommand):
    help = 'Update logistics data from your existing systems and Store model'

    def add_arguments(self, parser):
        parser.add_argument(
            '--store-id',
            type=str,
            help='Update specific store by UUID',
        )
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Number of days to analyze for metrics calculation',
        )

    def handle(self, *args, **options):
        # Filter stores
        if options['store_id']:
            try:
                stores = [Store.objects.get(id=options['store_id'])]
            except Store.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Store with ID {options["store_id"]} not found'))
                return
        else:
            stores = Store.objects.filter(status='active')

        days_back = options['days']
        cutoff_date = timezone.now().date() - timedelta(days=days_back)

        for store in stores:
            self.stdout.write(f'Updating logistics data for: {store.name} (ID: {store.id})')

            try:
                # Get or create logistics integration record
                logistics_data, created = LogisticsIntegration.objects.get_or_create(
                    store=store,
                    defaults={}
                )

                # === INTEGRATE WITH YOUR EXISTING LOGISTICS APP ===
                # Update this section based on your actual logistics models
                # Here are examples for different integration patterns:

                try:
                    # Option 1: If you have direct logistics models
                    # from logistics.models import Shipment, Order
                    #
                    # shipments = Shipment.objects.filter(store=store)
                    # orders = Order.objects.filter(store=store)
                    #
                    # logistics_data.total_shipments = shipments.count()
                    # logistics_data.pending_shipments = shipments.filter(status='pending').count()
                    # logistics_data.completed_shipments = shipments.filter(status='delivered').count()
                    # logistics_data.failed_shipments = shipments.filter(status='failed').count()

                    # Option 2: If logistics data is in order items
                    from orders.models import OrderItem

                    # Get order items for this store
                    order_items = OrderItem.objects.filter(product__store=store)
                    recent_orders = order_items.filter(order__created_at__date__gte=cutoff_date)

                    # Calculate logistics metrics from order data
                    logistics_data.total_shipments = recent_orders.values('order').distinct().count()
                    logistics_data.pending_shipments = recent_orders.filter(
                        order__status__in=['pending', 'processing']
                    ).values('order').distinct().count()

                    logistics_data.completed_shipments = recent_orders.filter(
                        order__status__in=['shipped', 'delivered']
                    ).values('order').distinct().count()

                    logistics_data.failed_shipments = recent_orders.filter(
                        order__status='cancelled'
                    ).values('order').distinct().count()

                    # Calculate shipping costs from financial records
                    shipping_costs = FinancialRecord.objects.filter(
                        store=store,
                        record_type='shipping_cost',
                        transaction_date__gte=cutoff_date
                    ).aggregate(total=Sum('amount'))['total'] or 0

                    logistics_data.total_shipping_cost = shipping_costs

                except ImportError:
                    self.stdout.write(
                        self.style.WARNING(
                            f'Could not import logistics models. Using Store model data only for {store.name}'
                        )
                    )

                # === LEVERAGE EXISTING STORE MODEL METHODS ===
                # The Store model already has these methods, so we don't need to duplicate the logic

                # Use existing Store.get_total_orders() - this is available as a property
                # Use existing Store.get_total_sales() - this is available as a property
                # Use existing Store.get_average_rating() - this is available as a property

                # === INTEGRATE WITH EXISTING STOREMETRICS ===
                try:
                    from stores.models import StoreMetrics

                    # Get recent store metrics
                    recent_metrics = StoreMetrics.objects.filter(
                        store=store,
                        date__gte=cutoff_date
                    ).aggregate(
                        avg_return_rate=Avg('return_rate_percentage'),
                        total_returns=Sum('total_returns'),
                        avg_rating=Avg('average_rating')
                    )

                    if recent_metrics['avg_return_rate']:
                        logistics_data.return_rate_percentage = recent_metrics['avg_return_rate']
                    if recent_metrics['total_returns']:
                        logistics_data.total_return_shipments = recent_metrics['total_returns']
                    if recent_metrics['avg_rating']:
                        logistics_data.customer_satisfaction_score = recent_metrics['avg_rating']

                except Exception as e:
                    self.stdout.write(
                        self.style.WARNING(f'Could not sync with StoreMetrics: {e}')
                    )

                # === INTEGRATE WITH EXISTING RETURN SYSTEM ===
                try:
                    from orders.models import Return

                    # Get return data
                    returns = Return.objects.filter(
                        items__product__store=store,
                        created_at__date__gte=cutoff_date
                    ).distinct()

                    logistics_data.total_return_shipments = returns.count()
                    logistics_data.pending_return_pickups = returns.filter(
                        status__in=['pending', 'approved']
                    ).count()
                    logistics_data.completed_return_pickups = returns.filter(
                        status='completed'
                    ).count()

                except ImportError:
                    self.stdout.write(
                        self.style.WARNING('Return models not found, skipping return logistics')
                    )

                # === CALCULATE PERFORMANCE METRICS ===

                # Calculate processing time based on store's configuration
                logistics_data.average_processing_time = store.processing_time

                # Calculate on-time delivery rate (you may need to customize this)
                if logistics_data.total_shipments > 0:
                    logistics_data.on_time_delivery_rate = (
                                                                   logistics_data.completed_shipments / logistics_data.total_shipments
                                                           ) * 100

                # Save the updated logistics data
                logistics_data.save()

                # === SYNC FINANCIAL METRICS ===
                # Use the enhanced integration model
                FinancialMetricsIntegration.sync_with_store_metrics(store)

                self.stdout.write(
                    self.style.SUCCESS(f'✓ Updated logistics data for {store.name}')
                )

                # Print summary
                self.stdout.write(f'  - Total Orders (lifetime): {store.get_total_orders()}')
                self.stdout.write(f'  - Total Sales (lifetime): ${store.get_total_sales()}')
                self.stdout.write(f'  - Average Rating: {store.get_average_rating():.1f}')
                self.stdout.write(f'  - Recent Shipments: {logistics_data.total_shipments}')
                self.stdout.write(f'  - Completed: {logistics_data.completed_shipments}')
                self.stdout.write(f'  - Failed: {logistics_data.failed_shipments}')
                self.stdout.write(f'  - Return Rate: {logistics_data.return_rate_percentage:.1f}%')

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'Error updating {store.name}: {str(e)}')
                )

        self.stdout.write(
            self.style.SUCCESS(f'Logistics data update completed for {len(stores)} stores')
        )