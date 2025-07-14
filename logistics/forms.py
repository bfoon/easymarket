from django import forms
from orders.models import Order
from .models import Shipment
from decimal import Decimal

class ShipmentForm(forms.ModelForm):
    # Manually define the shipping cost input (not part of Shipment model)
    shipping_cost = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        initial=Decimal('0.00'),
        required=True,
        label="Shipping Cost",
        widget=forms.NumberInput(attrs={'class': 'form-control'})
    )

    class Meta:
        model = Shipment
        fields = [
            'order',
            'shipping_address',
            'warehouse',
            'driver',
            'vehicle',
            'logistic_office',
            'collect_time',
            'estimated_dropoff_time',
            'weight_kg',
            'size_cubic_meters',
            'material_type',
            'shipment_type',
            'packing_type',
            'container_type',
        ]
        widgets = {
            'collect_time': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'estimated_dropoff_time': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'weight_kg': forms.NumberInput(attrs={'class': 'form-control'}),
            'size_cubic_meters': forms.NumberInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field_name, field in self.fields.items():
            field.widget.attrs.setdefault('class', 'form-control')

        self.fields['shipping_address'].widget = forms.HiddenInput()

    def save(self, commit=True):
        shipment = super().save(commit=False)

        # Update linked order with values from the shipment
        shipping_cost = self.cleaned_data.get('shipping_cost')
        if shipment.order:
            if shipping_cost is not None:
                shipment.order.shipping_cost = shipping_cost

            if shipment.collect_time:
                shipment.order.shipped_date = shipment.collect_time

            if shipment.estimated_dropoff_time:
                shipment.order.expected_delivery_date = shipment.estimated_dropoff_time.date()

            shipment.order.save(update_fields=['shipping_cost', 'shipped_date', 'expected_delivery_date'])

        if commit:
            shipment.save()
            self.save_m2m()

        return shipment

