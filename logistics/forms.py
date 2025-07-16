from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db.models import Q
from .models import (
    Shipment, ShipmentBox, BoxItem, Driver, Vehicle,
    Warehouse, LogisticOffice
)
from orders.models import Order, ShippingAddress, OrderItem

User = get_user_model()


class DateTimeLocalWidget(forms.DateTimeInput):
    input_type = 'datetime-local'


class ShipmentForm(forms.ModelForm):
    class Meta:
        model = Shipment
        fields = [
            'shipping_address', 'warehouse', 'driver', 'vehicle', 'logistic_office',
            'collect_time', 'estimated_dropoff_time', 'order', 'weight_kg',
            'size_cubic_meters', 'material_type', 'shipment_type', 'packing_type',
            'container_type', 'status'
        ]
        widgets = {
            'collect_time': DateTimeLocalWidget(attrs={'class': 'form-control'}),
            'estimated_dropoff_time': DateTimeLocalWidget(attrs={'class': 'form-control'}),
            'shipping_address': forms.Select(attrs={'class': 'form-select'}),
            'warehouse': forms.Select(attrs={'class': 'form-select'}),
            'driver': forms.Select(attrs={'class': 'form-select'}),
            'vehicle': forms.Select(attrs={'class': 'form-select'}),
            'logistic_office': forms.Select(attrs={'class': 'form-select'}),
            'order': forms.Select(attrs={'class': 'form-select'}),
            'weight_kg': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1', 'min': '0'}),
            'size_cubic_meters': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'material_type': forms.Select(attrs={'class': 'form-select'}),
            'shipment_type': forms.Select(attrs={'class': 'form-select'}),
            'packing_type': forms.Select(attrs={'class': 'form-select'}),
            'container_type': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['warehouse'].queryset = Warehouse.objects.order_by('name')
        self.fields['driver'].queryset = Driver.objects.select_related('user').filter(user__is_active=True).order_by('user__first_name')
        self.fields['vehicle'].queryset = Vehicle.objects.select_related('driver').order_by('plate_number')
        self.fields['logistic_office'].queryset = LogisticOffice.objects.order_by('name')

        is_new_shipment = not self.instance or not self.instance.pk

        if is_new_shipment:
            # Default status on creation
            self.fields['status'].initial = 'pending'
            # Limit to processing orders only
            self.fields['order'].queryset = Order.objects.filter(status='processing').order_by('-created_at')
            self.fields['order'].help_text = "Only orders with 'Processing' status are available for new shipments"
            self.fields['shipping_address'].queryset = ShippingAddress.objects.filter(
                order__status='processing'
            ).distinct().order_by('-id')
        else:
            self.fields['order'].queryset = Order.objects.order_by('-created_at')
            self.fields['order'].disabled = True
            self.fields['shipping_address'].queryset = ShippingAddress.objects.order_by('-id')
            self.fields['shipping_address'].disabled = True

        # Optional fields
        self.fields['warehouse'].required = False
        self.fields['driver'].required = False
        self.fields['vehicle'].required = False
        self.fields['logistic_office'].required = False

        # Help texts
        self.fields['weight_kg'].help_text = "Weight in kilograms"
        self.fields['size_cubic_meters'].help_text = "Size in cubic meters"
        self.fields['collect_time'].help_text = "When the shipment will be collected"
        self.fields['estimated_dropoff_time'].help_text = "Estimated delivery time"

    def clean(self):
        cleaned_data = super().clean()
        collect_time = cleaned_data.get('collect_time')
        estimated_dropoff_time = cleaned_data.get('estimated_dropoff_time')
        driver = cleaned_data.get('driver')
        vehicle = cleaned_data.get('vehicle')
        weight_kg = cleaned_data.get('weight_kg')

        if collect_time and estimated_dropoff_time:
            if collect_time >= estimated_dropoff_time:
                self.add_error('estimated_dropoff_time', "Estimated dropoff time must be after collection time.")
            if not self.instance.pk and collect_time < timezone.now():
                self.add_error('collect_time', "Collection time cannot be in the past.")

        if driver and vehicle:
            if vehicle.driver != driver:
                self.add_error('vehicle', f"Vehicle {vehicle.plate_number} is not assigned to driver {driver.user.get_full_name()}.")

        if vehicle and weight_kg:
            if weight_kg > vehicle.capacity_kg:
                self.add_error('weight_kg', f"Weight ({weight_kg} kg) exceeds vehicle capacity ({vehicle.capacity_kg} kg).")

        return cleaned_data


class DriverForm(forms.ModelForm):
    first_name = forms.CharField(max_length=30, widget=forms.TextInput(attrs={'class': 'form-control'}))
    last_name = forms.CharField(max_length=30, widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(widget=forms.EmailInput(attrs={'class': 'form-control'}))

    class Meta:
        model = Driver
        fields = ['phone', 'license_number']
        widgets = {
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'license_number': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['first_name'].initial = self.instance.user.first_name
            self.fields['last_name'].initial = self.instance.user.last_name
            self.fields['email'].initial = self.instance.user.email

    def save(self, commit=True):
        driver = super().save(commit=False)

        if not driver.user_id:
            # Create new user
            user = User.objects.create_user(
                username=self.cleaned_data['email'],
                email=self.cleaned_data['email'],
                first_name=self.cleaned_data['first_name'],
                last_name=self.cleaned_data['last_name'],
            )
            driver.user = user
        else:
            # Update existing user
            user = driver.user
            user.first_name = self.cleaned_data['first_name']
            user.last_name = self.cleaned_data['last_name']
            user.email = self.cleaned_data['email']
            user.username = self.cleaned_data['email']
            if commit:
                user.save()

        if commit:
            driver.save()
        return driver


class VehicleForm(forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = ['driver', 'plate_number', 'model', 'capacity_kg']
        widgets = {
            'driver': forms.Select(attrs={'class': 'form-select'}),
            'plate_number': forms.TextInput(attrs={'class': 'form-control'}),
            'model': forms.TextInput(attrs={'class': 'form-control'}),
            'capacity_kg': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1', 'min': '0'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['driver'].queryset = Driver.objects.select_related('user').filter(user__is_active=True).order_by(
            'user__first_name')

    def clean_plate_number(self):
        plate_number = self.cleaned_data['plate_number']
        # Check for duplicate plate numbers
        qs = Vehicle.objects.filter(plate_number=plate_number)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("A vehicle with this plate number already exists.")
        return plate_number.upper()


class WarehouseForm(forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = ['name', 'address']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class LogisticOfficeForm(forms.ModelForm):
    class Meta:
        model = LogisticOffice
        fields = ['name', 'location']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'location': forms.TextInput(attrs={'class': 'form-control'}),
        }


class ShipmentBoxForm(forms.ModelForm):
    class Meta:
        model = ShipmentBox
        fields = ['box_number', 'weight_kg']
        widgets = {
            'box_number': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'weight_kg': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1', 'min': '0'}),
        }

    def __init__(self, *args, **kwargs):
        self.shipment = kwargs.pop('shipment', None)
        super().__init__(*args, **kwargs)

    def clean_box_number(self):
        box_number = self.cleaned_data['box_number']
        if self.shipment:
            # Check for duplicate box numbers within the same shipment
            qs = ShipmentBox.objects.filter(shipment=self.shipment, box_number=box_number)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise ValidationError(f"Box number {box_number} already exists for this shipment.")
        return box_number


class BoxItemForm(forms.ModelForm):
    class Meta:
        model = BoxItem
        fields = ['order_item', 'quantity']
        widgets = {
            'order_item': forms.Select(attrs={'class': 'form-select'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
        }

    def __init__(self, *args, **kwargs):
        self.box = kwargs.pop('box', None)
        super().__init__(*args, **kwargs)

        if self.box and self.box.shipment.order:
            # Limit order items to those from the shipment's order
            self.fields['order_item'].queryset = OrderItem.objects.filter(
                order=self.box.shipment.order
            ).select_related('product')

    def clean_quantity(self):
        quantity = self.cleaned_data['quantity']
        order_item = self.cleaned_data.get('order_item')

        if order_item and quantity:
            # Check if quantity doesn't exceed the order item quantity
            if quantity > order_item.quantity:
                raise ValidationError(
                    f"Quantity ({quantity}) cannot exceed order item quantity ({order_item.quantity})."
                )

        return quantity


class ShipmentSearchForm(forms.Form):
    search = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search by ID, address, or driver name'
        })
    )
    status = forms.ChoiceField(
        choices=[('', 'All Statuses')] + Shipment.STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    shipment_type = forms.ChoiceField(
        choices=[('', 'All Types')] + Shipment.SHIPMENT_TYPE_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    material_type = forms.ChoiceField(
        choices=[('', 'All Materials')] + Shipment.MATERIAL_TYPE_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )


class VehicleAssignmentForm(forms.Form):
    """Form for assigning a vehicle to a driver"""
    vehicle = forms.ModelChoiceField(
        queryset=Vehicle.objects.all(),
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    driver = forms.ModelChoiceField(
        queryset=Driver.objects.select_related('user').filter(user__is_active=True),
        required=False,
        empty_label="Unassigned",
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['vehicle'].queryset = Vehicle.objects.select_related('driver__user').order_by('plate_number')
        self.fields['driver'].queryset = Driver.objects.select_related('user').filter(
            user__is_active=True
        ).order_by('user__first_name')

    def clean(self):
        cleaned_data = super().clean()
        vehicle = cleaned_data.get('vehicle')
        driver = cleaned_data.get('driver')

        if vehicle:
            # Check if vehicle has active shipments and is being reassigned
            active_shipments = vehicle.shipment_set.filter(status__in=['pending', 'in_transit']).count()
            if active_shipments > 0 and vehicle.driver != driver:
                raise ValidationError(
                    f'Vehicle {vehicle.plate_number} has {active_shipments} active shipments '
                    f'and cannot be reassigned to a different driver.'
                )

        return cleaned_data


class QuickAssignmentForm(forms.Form):
    """Quick form for immediate vehicle assignment"""
    driver = forms.ModelChoiceField(
        queryset=Driver.objects.select_related('user').filter(user__is_active=True),
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    vehicle = forms.ModelChoiceField(
        queryset=Vehicle.objects.filter(driver__isnull=True),
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['driver'].queryset = Driver.objects.select_related('user').filter(
            user__is_active=True
        ).order_by('user__first_name')

        # Show only unassigned vehicles or vehicles without active shipments
        available_vehicles = Vehicle.objects.filter(
            Q(driver__isnull=True) |
            ~Q(shipment__status__in=['pending', 'in_transit'])
        ).distinct().order_by('plate_number')

        self.fields['vehicle'].queryset = available_vehicles

        if not available_vehicles.exists():
            self.fields['vehicle'].empty_label = "No vehicles available"
            self.fields['vehicle'].help_text = "All vehicles are currently assigned or in use"


class BulkAssignmentForm(forms.Form):
    """Form for bulk assignment of vehicles to drivers"""
    assignments = forms.CharField(
        widget=forms.HiddenInput(),
        help_text="JSON data containing vehicle-driver assignments"
    )

    def clean_assignments(self):
        import json
        assignments_data = self.cleaned_data.get('assignments')

        try:
            assignments = json.loads(assignments_data)

            # Validate that assignments is a list of dictionaries
            if not isinstance(assignments, list):
                raise ValidationError("Invalid assignment data format")

            validated_assignments = []
            for assignment in assignments:
                if not isinstance(assignment, dict) or 'vehicle_id' not in assignment:
                    raise ValidationError("Invalid assignment format")

                vehicle_id = assignment.get('vehicle_id')
                driver_id = assignment.get('driver_id')

                # Validate vehicle exists
                try:
                    vehicle = Vehicle.objects.get(id=vehicle_id)
                except Vehicle.DoesNotExist:
                    raise ValidationError(f"Vehicle with ID {vehicle_id} does not exist")

                # Validate driver exists (if provided)
                driver = None
                if driver_id:
                    try:
                        driver = Driver.objects.get(id=driver_id)
                    except Driver.DoesNotExist:
                        raise ValidationError(f"Driver with ID {driver_id} does not exist")

                # Check for active shipments
                active_shipments = vehicle.shipment_set.filter(status__in=['pending', 'in_transit']).count()
                if active_shipments > 0 and vehicle.driver != driver:
                    raise ValidationError(
                        f'Vehicle {vehicle.plate_number} has active shipments and cannot be reassigned'
                    )

                validated_assignments.append({
                    'vehicle': vehicle,
                    'driver': driver,
                    'vehicle_id': vehicle_id,
                    'driver_id': driver_id
                })

            return validated_assignments

        except json.JSONDecodeError:
            raise ValidationError("Invalid JSON format in assignments data")


class AssignmentSearchForm(forms.Form):
    """Search form for filtering assignments"""
    search = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search by vehicle plate, model, or driver name'
        })
    )
    assignment_status = forms.ChoiceField(
        choices=[
            ('', 'All Vehicles'),
            ('assigned', 'Assigned'),
            ('unassigned', 'Unassigned'),
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    driver = forms.ModelChoiceField(
        queryset=Driver.objects.select_related('user').filter(user__is_active=True),
        required=False,
        empty_label="All Drivers",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    vehicle_status = forms.ChoiceField(
        choices=[
            ('', 'All Vehicles'),
            ('available', 'Available'),
            ('in_use', 'In Use'),
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )


class DriverVehicleSearchForm(forms.Form):
    """Search form for driver assignments"""
    search = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search by driver name, license, or phone'
        })
    )
    vehicle_status = forms.ChoiceField(
        choices=[
            ('', 'All Drivers'),
            ('with_vehicles', 'With Vehicles'),
            ('without_vehicles', 'Without Vehicles'),
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )


class VehicleReassignmentForm(forms.Form):
    """Form for reassigning a specific vehicle to a different driver"""
    new_driver = forms.ModelChoiceField(
        queryset=Driver.objects.select_related('user').filter(user__is_active=True),
        required=False,
        empty_label="Unassign Vehicle",
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    def __init__(self, vehicle, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.vehicle = vehicle
        self.fields['new_driver'].queryset = Driver.objects.select_related('user').filter(
            user__is_active=True
        ).order_by('user__first_name')

        # Set initial value to current driver
        if vehicle.driver:
            self.fields['new_driver'].initial = vehicle.driver

    def clean_new_driver(self):
        new_driver = self.cleaned_data.get('new_driver')

        # Check if vehicle has active shipments and is being reassigned
        if self.vehicle.driver != new_driver:
            active_shipments = self.vehicle.shipment_set.filter(status__in=['pending', 'in_transit']).count()
            if active_shipments > 0:
                raise ValidationError(
                    f'Vehicle {self.vehicle.plate_number} has {active_shipments} active shipments '
                    f'and cannot be reassigned to a different driver.'
                )

        return new_driver


# Update your existing VehicleForm to include assignment validation
class VehicleForm(forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = ['driver', 'plate_number', 'model', 'capacity_kg']
        widgets = {
            'driver': forms.Select(attrs={'class': 'form-select'}),
            'plate_number': forms.TextInput(attrs={'class': 'form-control'}),
            'model': forms.TextInput(attrs={'class': 'form-control'}),
            'capacity_kg': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1', 'min': '0'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['driver'].queryset = Driver.objects.select_related('user').filter(
            user__is_active=True
        ).order_by('user__first_name')
        self.fields['driver'].required = False
        self.fields['driver'].empty_label = "Unassigned"

    def clean_plate_number(self):
        plate_number = self.cleaned_data['plate_number']
        # Check for duplicate plate numbers
        qs = Vehicle.objects.filter(plate_number=plate_number)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("A vehicle with this plate number already exists.")
        return plate_number.upper()

    def clean_driver(self):
        driver = self.cleaned_data.get('driver')

        # If changing driver and vehicle has active shipments, prevent change
        if self.instance.pk and self.instance.driver != driver:
            active_shipments = self.instance.shipment_set.filter(status__in=['pending', 'in_transit']).count()
            if active_shipments > 0:
                raise ValidationError(
                    f'This vehicle has {active_shipments} active shipments and cannot be reassigned.'
                )

        return driver