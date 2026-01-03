from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db import transaction
from django.db.models import Q
import json

from .models import (
    Shipment, ShipmentBox, BoxItem, Driver, Vehicle,
    Warehouse, LogisticOffice
)
from orders.models import Order, ShippingAddress, OrderItem

User = get_user_model()


class DateTimeLocalWidget(forms.DateTimeInput):
    input_type = "datetime-local"


class ShipmentForm(forms.ModelForm):
    class Meta:
        model = Shipment
        fields = [
            "shipping_address", "warehouse", "driver", "vehicle", "logistic_office",
            "collect_time", "estimated_dropoff_time", "order", "weight_kg",
            "size_cubic_meters", "material_type", "shipment_type", "packing_type",
            "container_type", "verification_photo", "status"
        ]
        widgets = {
            "collect_time": DateTimeLocalWidget(attrs={"class": "form-control"}),
            "estimated_dropoff_time": DateTimeLocalWidget(attrs={"class": "form-control"}),
            "shipping_address": forms.Select(attrs={"class": "form-select"}),
            "warehouse": forms.Select(attrs={"class": "form-select"}),
            "driver": forms.Select(attrs={"class": "form-select"}),
            "vehicle": forms.Select(attrs={"class": "form-select"}),
            "logistic_office": forms.Select(attrs={"class": "form-select"}),
            "order": forms.Select(attrs={"class": "form-select"}),
            "weight_kg": forms.NumberInput(attrs={"class": "form-control", "step": "0.1", "min": "0"}),
            "size_cubic_meters": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "material_type": forms.Select(attrs={"class": "form-select"}),
            "shipment_type": forms.Select(attrs={"class": "form-select"}),
            "packing_type": forms.Select(attrs={"class": "form-select"}),
            "container_type": forms.Select(attrs={"class": "form-select"}),
            "verification_photo": forms.FileInput(attrs={"class": "form-control"}),
            "status": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["warehouse"].queryset = Warehouse.objects.filter(is_active=True).order_by("name")
        self.fields["driver"].queryset = Driver.objects.select_related("user").filter(
            is_active=True, user__is_active=True
        ).order_by("user__first_name", "user__last_name")
        self.fields["vehicle"].queryset = Vehicle.objects.select_related("driver").filter(
            is_active=True
        ).order_by("plate_number")
        self.fields["logistic_office"].queryset = LogisticOffice.objects.order_by("name")

        is_new = not self.instance or not self.instance.pk

        if is_new:
            # ✅ Only processing orders that DO NOT have any shipment yet
            eligible_orders = (
                Order.objects
                .filter(status="processing")
                .filter(shipments__isnull=True)
                .distinct()
                .order_by("-created_at")
            )
            self.fields["order"].queryset = eligible_orders
            self.fields["order"].help_text = "Only 'Processing' orders without any shipment are available."

            # ✅ Shipping addresses only for eligible orders
            self.fields["shipping_address"].queryset = (
                ShippingAddress.objects
                .filter(order__in=eligible_orders)
                .distinct()
                .order_by("-id")
            )

            self.fields["status"].initial = "pending"
        else:
            # editing an existing shipment
            self.fields["order"].queryset = Order.objects.order_by("-created_at")
            self.fields["order"].disabled = True

            self.fields["shipping_address"].queryset = ShippingAddress.objects.order_by("-id")
            self.fields["shipping_address"].disabled = True

        # Optional fields
        for f in ["warehouse", "driver", "vehicle", "logistic_office", "verification_photo"]:
            self.fields[f].required = False

        # Help texts
        self.fields["weight_kg"].help_text = "Weight in kilograms"
        self.fields["size_cubic_meters"].help_text = "Size in cubic meters"
        self.fields["collect_time"].help_text = "When the shipment will be collected"
        self.fields["estimated_dropoff_time"].help_text = "Estimated delivery time"

    def clean_order(self):
        order = self.cleaned_data.get("order")
        if not order:
            return order

        # ✅ Safety check: prevent creating another shipment for same order
        qs = order.shipments.all()
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise ValidationError("This order already has a shipment.")
        return order

    def clean(self):
        cleaned_data = super().clean()
        collect_time = cleaned_data.get("collect_time")
        estimated_dropoff_time = cleaned_data.get("estimated_dropoff_time")
        driver = cleaned_data.get("driver")
        vehicle = cleaned_data.get("vehicle")
        weight_kg = cleaned_data.get("weight_kg")

        if collect_time and estimated_dropoff_time:
            if collect_time >= estimated_dropoff_time:
                self.add_error("estimated_dropoff_time", "Estimated dropoff time must be after collection time.")
            if not self.instance.pk and collect_time < timezone.now():
                self.add_error("collect_time", "Collection time cannot be in the past.")

        if driver and vehicle:
            if vehicle.driver and vehicle.driver != driver:
                self.add_error(
                    "vehicle",
                    f"Vehicle {vehicle.plate_number} is assigned to {vehicle.driver.user.get_full_name()}."
                )

        if vehicle and weight_kg and getattr(vehicle, "capacity_kg", None):
            if vehicle.capacity_kg and weight_kg > vehicle.capacity_kg:
                self.add_error(
                    "weight_kg",
                    f"Weight ({weight_kg} kg) exceeds vehicle capacity ({vehicle.capacity_kg} kg)."
                )

        return cleaned_data

class DriverForm(forms.ModelForm):
    """
    Create/Update Driver + linked User in one form.

    CREATE:
      - Option A: Select an existing eligible user (is_driver=True and not already used)
      - Option B: Create a new user using email as username

    UPDATE:
      - User is locked (cannot be changed)
      - Updates first/last name only
    """

    user = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    first_name = forms.CharField(
        max_length=30,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter first name'})
    )
    last_name = forms.CharField(
        max_length=30,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter last name'})
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'driver@example.com'})
    )

    class Meta:
        model = Driver
        fields = [
            'user',
            'first_name', 'last_name', 'email',
            'phone', 'license_number', 'employee_id', 'license_expiry',
            'date_hired', 'emergency_contact_name', 'emergency_contact_phone'
        ]
        widgets = {
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+1234567890', 'type': 'tel'}),
            'license_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'DL123456'}),
            'employee_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'DR001'}),
            'license_expiry': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'date_hired': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'emergency_contact_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Emergency contact name'}),
            'emergency_contact_phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+1234567890', 'type': 'tel'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Optional fields
        for f in ['employee_id', 'license_expiry', 'date_hired', 'emergency_contact_name', 'emergency_contact_phone']:
            if f in self.fields:
                self.fields[f].required = False

        # Eligible users = is_driver=True AND not already assigned as Driver
        taken_user_ids = Driver.objects.values_list('user_id', flat=True)
        self.fields['user'].queryset = (
            User.objects.filter(is_driver=True)
            .exclude(id__in=taken_user_ids)
            .order_by('first_name', 'last_name', 'username')
        )
        self.fields['user'].empty_label = "Select an existing driver user (recommended)"

        # If editing existing driver: lock user and populate fields
        if self.instance.pk and getattr(self.instance, 'user', None):
            u = self.instance.user
            self.fields['user'].queryset = User.objects.filter(pk=u.pk)
            self.fields['user'].initial = u.pk
            self.fields['user'].disabled = True
            self.fields['user'].required = False

            self.fields['first_name'].initial = u.first_name
            self.fields['last_name'].initial = u.last_name
            self.fields['email'].initial = u.email

            # Lock email on edit (avoid conflicts)
            self.fields['email'].disabled = True
            self.fields['email'].help_text = "Email cannot be changed for existing drivers."

    def clean(self):
        cleaned = super().clean()
        selected_user = cleaned.get('user')
        email = (cleaned.get('email') or '').strip().lower()

        # If creating and user selected, we don't need email fields
        if not self.instance.pk:
            if selected_user:
                # validate selected user is not already a driver (extra safety)
                if Driver.objects.filter(user=selected_user).exists():
                    raise ValidationError("This user is already assigned as a driver.")
                return cleaned

            # else: no selected user -> must create new user from email fields
            if not email:
                self.add_error('email', "Email is required if you are not selecting an existing user.")
            if not cleaned.get('first_name'):
                self.add_error('first_name', "First name is required if you are creating a new driver user.")
            if not cleaned.get('last_name'):
                self.add_error('last_name', "Last name is required if you are creating a new driver user.")

        return cleaned

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        selected_user = self.cleaned_data.get('user')

        # If selecting an existing user, skip email validation entirely
        if selected_user:
            return email

        # If creating new driver user, email must be unique
        if not self.instance.pk:
            if not email:
                return email
            if User.objects.filter(email__iexact=email).exists():
                raise ValidationError("A user with this email already exists.")
            if User.objects.filter(username__iexact=email).exists():
                raise ValidationError("A user with this email/username already exists.")

        return email

    def clean_license_number(self):
        license_number = self.cleaned_data.get('license_number')

        if not license_number:
            return license_number

        license_number = str(license_number).strip().upper()
        qs = Driver.objects.filter(license_number__iexact=license_number)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("A driver with this license number already exists.")

        return license_number

    @transaction.atomic
    def save(self, commit=True):
        driver = super().save(commit=False)

        # UPDATE existing driver user info
        if driver.pk and driver.user_id:
            u = driver.user
            u.first_name = self.cleaned_data.get('first_name', u.first_name)
            u.last_name = self.cleaned_data.get('last_name', u.last_name)

            # keep flag true
            if hasattr(u, 'is_driver'):
                u.is_driver = True

            if commit:
                u.save()
                driver.save()
            return driver

        # CREATE: attach selected user OR create new user
        selected_user = self.cleaned_data.get('user')
        if selected_user:
            if Driver.objects.filter(user=selected_user).exists():
                raise ValidationError("This user is already assigned as a driver.")
            driver.user = selected_user

            if hasattr(selected_user, 'is_driver'):
                selected_user.is_driver = True
                if commit:
                    selected_user.save()

        else:
            email = (self.cleaned_data.get('email') or '').strip().lower()
            user = User.objects.create_user(
                username=email,
                email=email,
                first_name=self.cleaned_data.get('first_name', ''),
                last_name=self.cleaned_data.get('last_name', ''),
            )
            if hasattr(user, 'is_driver'):
                user.is_driver = True
                if commit:
                    user.save()

            driver.user = user

        if commit:
            driver.save()

        return driver

class VehicleForm(forms.ModelForm):
    """Form for creating and updating vehicles"""

    class Meta:
        model = Vehicle
        fields = [
            'driver', 'plate_number', 'model', 'year',
            'capacity_kg', 'capacity_cubic_meters', 'fuel_type'
        ]
        widgets = {
            'driver': forms.Select(attrs={'class': 'form-select'}),
            'plate_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'ABC-1234'
            }),
            'model': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Toyota Hiace'
            }),
            'year': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1990',
                'max': '2030',
                'placeholder': '2023'
            }),
            'capacity_kg': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': '1000'
            }),
            'capacity_cubic_meters': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': '10.5'
            }),
            'fuel_type': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Only active drivers (and active users)
        if 'driver' in self.fields:
            self.fields['driver'].queryset = (
                Driver.objects.select_related('user')
                .filter(is_active=True, user__is_active=True)
                .order_by('user__first_name', 'user__last_name', 'user__username')
            )
            self.fields['driver'].required = False
            self.fields['driver'].empty_label = "Unassigned"

        # Optional fields (only if they exist on model)
        for f in ['year', 'capacity_cubic_meters']:
            if f in self.fields:
                self.fields[f].required = False

        # Helpful hints
        if 'capacity_kg' in self.fields:
            self.fields['capacity_kg'].help_text = "Maximum weight capacity in kilograms"
        if 'capacity_cubic_meters' in self.fields:
            self.fields['capacity_cubic_meters'].help_text = "Maximum volume capacity in cubic meters"

    def clean_plate_number(self):
        """Validate plate number uniqueness + normalize."""
        plate_number = self.cleaned_data.get('plate_number')

        if not plate_number:
            raise ValidationError("Plate number is required.")

        plate_number = str(plate_number).strip().upper()

        # Check duplicates case-insensitively
        qs = Vehicle.objects.filter(plate_number__iexact=plate_number)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise ValidationError("A vehicle with this plate number already exists.")

        return plate_number

    def clean_driver(self):
        """
        Prevent driver reassignment when vehicle has active shipments.
        Only blocks if changing driver AND active shipments exist.
        """
        driver = self.cleaned_data.get('driver')

        # If editing and driver is changing
        if self.instance.pk:
            current_driver_id = getattr(self.instance, "driver_id", None)
            new_driver_id = getattr(driver, "id", None)

            if current_driver_id != new_driver_id:
                # Related name assumed to be `shipments`
                shipments_rel = getattr(self.instance, "shipments", None)

                if shipments_rel is not None:
                    active_shipments = shipments_rel.filter(
                        status__in=['pending', 'shipped', 'in_transit']
                    ).count()

                    if active_shipments > 0:
                        raise ValidationError(
                            f"This vehicle has {active_shipments} active shipment(s) and cannot be reassigned."
                        )

        return driver


class WarehouseForm(forms.ModelForm):
    """Form for creating and updating warehouses"""

    class Meta:
        model = Warehouse
        fields = ['name', 'code', 'address', 'latitude', 'longitude',
                  'capacity_cubic_meters', 'manager', 'logistic_office']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Main Warehouse'
            }),
            'code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'WH001'
            }),
            'address': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Complete warehouse address'
            }),
            'latitude': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': 'any',
                'placeholder': '13.4443'
            }),
            'longitude': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': 'any',
                'placeholder': '-16.6738'
            }),
            'capacity_cubic_meters': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': '1000'
            }),
            'manager': forms.Select(attrs={'class': 'form-select'}),
            'logistic_office': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Make optional fields
        self.fields['code'].required = False
        self.fields['latitude'].required = False
        self.fields['longitude'].required = False
        self.fields['capacity_cubic_meters'].required = False
        self.fields['manager'].required = False
        self.fields['manager'].empty_label = "No manager assigned"
        self.fields['logistic_office'].required = False
        self.fields['logistic_office'].empty_label = "No office assigned"

        # Help texts
        self.fields['code'].help_text = "Unique warehouse code (auto-generated if empty)"
        self.fields['latitude'].help_text = "GPS latitude coordinate"
        self.fields['longitude'].help_text = "GPS longitude coordinate"
        self.fields['capacity_cubic_meters'].help_text = "Total storage capacity in cubic meters"

    def clean(self):
        """Validate coordinate pairs"""
        cleaned_data = super().clean()
        latitude = cleaned_data.get('latitude')
        longitude = cleaned_data.get('longitude')

        # If one coordinate is provided, both must be provided
        if (latitude is not None and longitude is None) or (longitude is not None and latitude is None):
            raise ValidationError("Both latitude and longitude must be provided together.")

        return cleaned_data


class ShipmentBoxForm(forms.ModelForm):
    """Form for creating and managing shipment boxes"""

    class Meta:
        model = ShipmentBox
        fields = ['shipment', 'box_number', 'weight_kg', 'dimensions']
        widgets = {
            'shipment': forms.Select(attrs={'class': 'form-select'}),
            'box_number': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1'
            }),
            'weight_kg': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.1',
                'min': '0'
            }),
            'dimensions': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '50x40x30 cm'
            }),
        }


class BoxItemForm(forms.ModelForm):
    """Form for adding items to boxes"""

    class Meta:
        model = BoxItem
        fields = ['box', 'order_item', 'quantity']
        widgets = {
            'box': forms.Select(attrs={'class': 'form-select'}),
            'order_item': forms.Select(attrs={'class': 'form-select'}),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1'
            }),
        }

    def clean(self):
        """Validate quantity doesn't exceed order item quantity"""
        cleaned_data = super().clean()
        order_item = cleaned_data.get('order_item')
        quantity = cleaned_data.get('quantity')

        if order_item and quantity:
            if quantity > order_item.quantity:
                raise ValidationError(
                    f"Quantity ({quantity}) cannot exceed order item quantity ({order_item.quantity})"
                )

        return cleaned_data


class BulkAssignmentForm(forms.Form):
    """Form for bulk vehicle-driver assignments"""

    assignments = forms.CharField(
        widget=forms.HiddenInput(),
        required=True
    )

    def clean_assignments(self):
        """Validate and parse bulk assignment data"""
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
                    vehicle = Vehicle.objects.get(id=vehicle_id, is_active=True)
                except Vehicle.DoesNotExist:
                    raise ValidationError(f"Vehicle with ID {vehicle_id} does not exist")

                # Validate driver exists (if provided)
                driver = None
                if driver_id:
                    try:
                        driver = Driver.objects.get(id=driver_id, is_active=True)
                    except Driver.DoesNotExist:
                        raise ValidationError(f"Driver with ID {driver_id} does not exist")

                # Check for active shipments
                active_shipments = vehicle.shipments.filter(
                    status__in=['pending', 'shipped', 'in_transit']
                ).count()

                if active_shipments > 0 and vehicle.driver != driver:
                    raise ValidationError(
                        f'Vehicle {vehicle.plate_number} has {active_shipments} active shipment(s) '
                        f'and cannot be reassigned'
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
        queryset=Driver.objects.select_related('user').filter(
            is_active=True, user__is_active=True
        ),
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
        queryset=Driver.objects.select_related('user').filter(
            is_active=True, user__is_active=True
        ),
        required=False,
        empty_label="Unassign Vehicle",
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    def __init__(self, vehicle, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.vehicle = vehicle
        self.fields['new_driver'].queryset = Driver.objects.select_related('user').filter(
            is_active=True, user__is_active=True
        ).order_by('user__first_name')

        # Set initial value to current driver
        if vehicle.driver:
            self.fields['new_driver'].initial = vehicle.driver

    def clean_new_driver(self):
        """Validate driver reassignment"""
        new_driver = self.cleaned_data.get('new_driver')

        # Check if vehicle has active shipments and is being reassigned
        if self.vehicle.driver != new_driver:
            active_shipments = self.vehicle.shipments.filter(
                status__in=['pending', 'shipped', 'in_transit']
            ).count()

            if active_shipments > 0:
                raise ValidationError(
                    f'Vehicle {self.vehicle.plate_number} has {active_shipments} active shipment(s) '
                    f'and cannot be reassigned to a different driver.'
                )

        return new_driver