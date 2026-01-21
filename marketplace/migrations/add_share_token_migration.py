# Generated migration for adding share_token to Cart model
# File: marketplace/migrations/XXXX_add_share_token_to_cart.py

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0002_initial'),  # Replace with your last migration number
    ]

    operations = [
        migrations.AddField(
            model_name='cart',
            name='share_token',
            field=models.CharField(blank=True, max_length=32, null=True, unique=True),
        ),
    ]
