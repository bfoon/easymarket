# Generated migration file for fixing NULL warehouses
# Save this as: stock/migrations/0003_fix_null_warehouses.py

from django.db import migrations


def fix_null_warehouses_forward(apps, schema_editor):
    """
    Assign default warehouse to stock records with NULL warehouse.
    This ensures data integrity before enforcing the NOT NULL constraint.
    """
    Stock = apps.get_model('stock', 'Stock')
    Warehouse = apps.get_model('stock', 'Warehouse')

    # Count records needing fix
    null_count = Stock.objects.filter(warehouse__isnull=True).count()

    if null_count == 0:
        print("✅ No NULL warehouse records found. Skipping...")
        return

    print(f"📊 Found {null_count} stock records with NULL warehouse")

    # Get or create default warehouse
    default_warehouse, created = Warehouse.objects.get_or_create(
        code='DEFAULT-WH',
        defaults={
            'name': 'Default Warehouse',
            'address': 'Default Address - Please Update',
            'city': 'Default City',
            'country': 'Gambia',
            'is_active': True
        }
    )

    if created:
        print(f"✅ Created default warehouse: {default_warehouse.code}")
    else:
        print(f"✅ Using existing warehouse: {default_warehouse.code}")

    # Update all NULL warehouse stock records
    updated = Stock.objects.filter(warehouse__isnull=True).update(
        warehouse=default_warehouse
    )

    print(f"✅ Fixed {updated} stock records with NULL warehouse")

    # Verify
    remaining = Stock.objects.filter(warehouse__isnull=True).count()
    if remaining == 0:
        print("✅ All stock records now have valid warehouses!")
    else:
        print(f"⚠️  Warning: {remaining} records still have NULL warehouse")


def reverse_fix(apps, schema_editor):
    """
    Reverse is not possible - we can't know which records originally had NULL.
    This is a data cleanup operation that shouldn't be reversed.
    """
    print("⚠️  This migration cannot be reversed (data cleanup)")
    pass


class Migration(migrations.Migration):
    dependencies = [
        # ⚠️  IMPORTANT: Update this to your last migration!
        # Find it by running: python manage.py showmigrations stock
        # Then put the name of the last migration here
        ('stock', '0003_supplier_alter_stock_options_stock_last_counted_and_more'),  # ← CHANGE THIS
    ]

    operations = [
        migrations.RunPython(
            fix_null_warehouses_forward,
            reverse_fix,
            elidable=True,
        ),
    ]

# ============================================================================
# INSTALLATION INSTRUCTIONS
# ============================================================================
#
# 1. Find your last migration:
#    python manage.py showmigrations stock
#
# 2. Update the dependencies above with the name of your last migration
#
# 3. Save this file as:
#    stock/migrations/0003_fix_null_warehouses.py
#    (Or use the next available number if 0003 already exists)
#
# 4. Run the migration:
#    python manage.py migrate stock
#
# 5. Verify it worked:
#    python manage.py shell
#    >>> from stock.models import Stock
#    >>> Stock.objects.filter(warehouse__isnull=True).count()
#    0  # Should be 0
#
# ============================================================================