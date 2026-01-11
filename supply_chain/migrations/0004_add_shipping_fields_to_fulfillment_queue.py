# supply_chain/migrations/0004_add_shipping_fields_to_fulfillment_queue.py
# Generated migration file

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('supply_chain', '0006_alter_fulfillmentqueue_options_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='fulfillmentqueue',
            name='shipped_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='fulfillmentqueue',
            name='shipped_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='shipped_orders',
                to=settings.AUTH_USER_MODEL
            ),
        ),
    ]