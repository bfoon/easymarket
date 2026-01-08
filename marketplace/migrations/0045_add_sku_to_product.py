from django.db import migrations, models
import secrets
import string


def generate_sku():
    """Generate a unique SKU in format: EM-XXXXXXXX"""
    random_part = ''.join(
        secrets.choice(string.ascii_uppercase + string.digits)
        for _ in range(8)
    )
    return f"EM-{random_part}"


def populate_existing_skus(apps, schema_editor):
    """Generate SKUs for existing products"""
    Product = apps.get_model('marketplace', 'Product')

    existing_skus = set()

    for product in Product.objects.all():
        # Generate unique SKU
        while True:
            sku = generate_sku()
            if sku not in existing_skus:
                existing_skus.add(sku)
                break

        product.sku = sku
        product.save(update_fields=['sku'])

    print(f"Generated SKUs for {Product.objects.count()} products")


def reverse_populate_skus(apps, schema_editor):
    """Reverse migration - set SKUs to empty string"""
    Product = apps.get_model('marketplace', 'Product')
    Product.objects.all().update(sku='')


class Migration(migrations.Migration):
    dependencies = [
        ('marketplace', '0044_alter_product_options_product_b2b_min_quantity_and_more'),  # Replace with your last migration
    ]

    operations = [
        # Step 1: Add SKU field (nullable, non-unique first)
        migrations.AddField(
            model_name='product',
            name='sku',
            field=models.CharField(
                max_length=50,
                null=True,
                blank=True,
                help_text="Auto-generated SKU in format: EM-XXXXXXXX"
            ),
        ),

        # Step 2: Populate SKUs for existing products
        migrations.RunPython(
            populate_existing_skus,
            reverse_populate_skus
        ),

        # Step 3: Make SKU unique and non-null
        migrations.AlterField(
            model_name='product',
            name='sku',
            field=models.CharField(
                max_length=50,
                unique=True,
                editable=False,
                help_text="Auto-generated SKU in format: EM-XXXXXXXX"
            ),
        ),
    ]
