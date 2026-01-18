"""
Management Command: Create Warehouses for Existing Stores

This command creates warehouses and stock entries for stores and products
that were created before the automatic warehouse system was implemented.

Usage:
    python manage.py create_missing_warehouses
    python manage.py create_missing_warehouses --dry-run  # Preview only
    python manage.py create_missing_warehouses --store-id <uuid>  # Single store
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from stores.models import Store
from stock.models import Warehouse, Stock
from marketplace.models import Product
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Create warehouses for existing stores and stock entries for existing products'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview changes without saving to database',
        )
        parser.add_argument(
            '--store-id',
            type=str,
            help='Process only a specific store by ID',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        store_id = options.get('store_id')

        if dry_run:
            self.stdout.write(self.style.WARNING('🔍 DRY RUN MODE - No changes will be saved'))

        # Get stores to process
        if store_id:
            stores = Store.objects.filter(id=store_id)
            if not stores.exists():
                self.stdout.write(self.style.ERROR(f'❌ Store with ID {store_id} not found'))
                return
        else:
            stores = Store.objects.all()

        stats = {
            'stores_total': stores.count(),
            'stores_with_warehouse': 0,
            'warehouses_created': 0,
            'stock_entries_created': 0,
            'errors': 0,
        }

        self.stdout.write(self.style.SUCCESS(f'\n📦 Processing {stats["stores_total"]} store(s)...\n'))

        for store in stores:
            try:
                # Check if store has warehouse
                if store.warehouse:
                    stats['stores_with_warehouse'] += 1
                    self.stdout.write(f'  ✅ {store.name}: Already has warehouse {store.warehouse.code}')
                    warehouse = store.warehouse
                else:
                    # Create warehouse
                    warehouse_code = f"STORE-{store.id}"
                    
                    if dry_run:
                        self.stdout.write(
                            self.style.WARNING(
                                f'  🔍 {store.name}: Would create warehouse {warehouse_code}'
                            )
                        )
                        warehouse = None
                    else:
                        with transaction.atomic():
                            warehouse, created = Warehouse.objects.get_or_create(
                                code=warehouse_code,
                                defaults={
                                    "name": f"{store.name} Warehouse",
                                    "address": store.address_line_1 or "Store Location",
                                    "city": store.city or '',
                                    "state": store.region or '',
                                    "country": store.country or 'Gambia',
                                    "postal_code": store.postal_code or '',
                                    "manager": store.owner,
                                    "is_active": True,
                                    "description": f"Warehouse for {store.name} (created by migration)"
                                }
                            )
                            
                            if created:
                                store.warehouse = warehouse
                                store.save(update_fields=['warehouse'])
                                stats['warehouses_created'] += 1
                                self.stdout.write(
                                    self.style.SUCCESS(
                                        f'  ✅ {store.name}: Created warehouse {warehouse_code}'
                                    )
                                )
                            else:
                                # Warehouse existed but wasn't linked
                                store.warehouse = warehouse
                                store.save(update_fields=['warehouse'])
                                self.stdout.write(
                                    self.style.SUCCESS(
                                        f'  🔗 {store.name}: Linked to existing warehouse {warehouse_code}'
                                    )
                                )

                # Process products for this store
                if warehouse or dry_run:
                    products = Product.objects.filter(store=store)
                    
                    for product in products:
                        # Check if stock entry exists
                        stock_exists = Stock.objects.filter(
                            product=product,
                            warehouse=warehouse
                        ).exists() if warehouse else False
                        
                        if stock_exists:
                            continue
                        
                        if dry_run:
                            self.stdout.write(
                                self.style.WARNING(
                                    f'    🔍 Would create stock entry for: {product.name}'
                                )
                            )
                        else:
                            with transaction.atomic():
                                Stock.objects.create(
                                    product=product,
                                    warehouse=warehouse,
                                    quantity=0,
                                    reserved_quantity=0,
                                    reorder_level=10,
                                    reorder_quantity=50,
                                    unit_cost=Decimal('0.00'),
                                )
                                stats['stock_entries_created'] += 1
                                self.stdout.write(
                                    self.style.SUCCESS(
                                        f'    ✅ Created stock entry for: {product.name}'
                                    )
                                )

            except Exception as e:
                stats['errors'] += 1
                self.stdout.write(
                    self.style.ERROR(
                        f'  ❌ Error processing {store.name}: {str(e)}'
                    )
                )
                logger.error(f"Error migrating store {store.id}: {str(e)}", exc_info=True)

        # Print summary
        self.stdout.write('\n' + '='*60)
        self.stdout.write(self.style.SUCCESS('\n📊 MIGRATION SUMMARY\n'))
        self.stdout.write('='*60)
        self.stdout.write(f'Total stores processed:      {stats["stores_total"]}')
        self.stdout.write(f'Stores with warehouse:       {stats["stores_with_warehouse"]}')
        self.stdout.write(f'Warehouses created:          {stats["warehouses_created"]}')
        self.stdout.write(f'Stock entries created:       {stats["stock_entries_created"]}')
        self.stdout.write(f'Errors:                      {stats["errors"]}')
        self.stdout.write('='*60 + '\n')

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    '🔍 This was a DRY RUN - no changes were saved.\n'
                    'Run without --dry-run to apply changes.\n'
                )
            )
        else:
            if stats['errors'] == 0:
                self.stdout.write(
                    self.style.SUCCESS(
                        '✅ Migration completed successfully!\n'
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f'⚠️  Migration completed with {stats["errors"]} error(s).\n'
                        'Check logs for details.\n'
                    )
                )
