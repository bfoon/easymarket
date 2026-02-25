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
    """
    Enhanced shipment form that integrates with warehouse shipping system.

    Features:
    - Shows only orders with items marked as "shipped to warehouse"
    - Supports multiple shipments per order
    - Automatically includes only warehouse-shipped items
    - Sequential shipment numbering
    """

    class Meta:
        model = Shipment
        fields = [
            "order", "shipping_address", "warehouse", "driver", "vehicle",
            "logistic_office", "collect_time", "estimated_dropoff_time",
            "weight_kg", "size_cubic_meters", "material_type", "shipment_type",
            "packing_type", "container_type", "verification_photo", "status"
        ]
        widgets = {
            "collect_time": DateTimeLocalWidget(attrs={"class": "form-control"}),
            "estimated_dropoff_time": DateTimeLocalWidget(attrs={"class": "form-control"}),
            "order": forms.Select(attrs={"class": "form-select"}),
            "shipping_address": forms.Select(attrs={"class": "form-select"}),
            "warehouse": forms.Select(attrs={"class": "form-select"}),
            "driver": forms.Select(attrs={"class": "form-select"}),
            "vehicle": forms.Select(attrs={"class": "form-select"}),
            "logistic_office": forms.Select(attrs={"class": "form-select"}),
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

        # Set up querysets for related fields
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
            # NEW LOGIC: Show orders that have items marked as "shipped to warehouse"
            # that are not yet in a shipment

            # Get order IDs that have items ready for shipment
            ready_order_ids = OrderItem.objects.filter(
                shipped_to_warehouse=True,
                current_shipment__isnull=True
            ).values_list('order_id', flat=True).distinct()

            # Filter orders to only those with ready items and in processing or shipped status
            eligible_orders = (
                Order.objects
                .filter(id__in=ready_order_ids)
                .filter(status__in=['processing', 'shipped'])
                .distinct()
                .order_by("-created_at")
            )

            self.fields["order"].queryset = eligible_orders
            self.fields["order"].help_text = (
                "Only orders with items marked 'shipped to warehouse' are available. "
                "Multiple shipments can be created for the same order."
            )

            # Shipping addresses for eligible orders
            self.fields["shipping_address"].queryset = (
                ShippingAddress.objects
                .filter(order__in=eligible_orders)
                .distinct()
                .order_by("-id")
            )

            self.fields["status"].initial = "pending"

        else:
            # Editing existing shipment
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
        self.fields["order"].help_text += " Items marked 'shipped to warehouse' will be automatically included."

    def clean_order(self):
        """
        Validate that order has items available for shipment.
        Allow multiple shipments for same order (NEW BEHAVIOR).
        """
        order = self.cleaned_data.get("order")
        if not order:
            return order

        # Check if order has items ready for shipment
        available_items = OrderItem.objects.filter(
            order=order,
            shipped_to_warehouse=True,
            current_shipment__isnull=True
        )

        if not available_items.exists():
            raise ValidationError(
                "This order has no items available for shipment. "
                "Items must be marked as 'shipped to warehouse' first."
            )

        return order

    def clean(self):
        cleaned_data = super().clean()
        collect_time = cleaned_data.get("collect_time")
        estimated_dropoff_time = cleaned_data.get("estimated_dropoff_time")
        driver = cleaned_data.get("driver")
        vehicle = cleaned_data.get("vehicle")
        weight_kg = cleaned_data.get("weight_kg")

        # Time validations
        if collect_time and estimated_dropoff_time:
            if collect_time >= estimated_dropoff_time:
                self.add_error("estimated_dropoff_time", "Estimated dropoff time must be after collection time.")
            if not self.instance.pk and collect_time < timezone.now():
                self.add_error("collect_time", "Collection time cannot be in the past.")

        # Driver/Vehicle validations
        if driver and vehicle:
            if vehicle.driver and vehicle.driver != driver:
                self.add_error(
                    "vehicle",
                    f"Vehicle {vehicle.plate_number} is assigned to {vehicle.driver.user.get_full_name()}."
                )

        # Weight capacity validation
        if vehicle and weight_kg and getattr(vehicle, "capacity_kg", None):
            if vehicle.capacity_kg and weight_kg > vehicle.capacity_kg:
                self.add_error(
                    "weight_kg",
                    f"Weight ({weight_kg} kg) exceeds vehicle capacity ({vehicle.capacity_kg} kg)."
                )

        return cleaned_data

    def save(self, commit=True):
        """
        Override save to:
        1. Set shipment_number automatically
        2. Create ShipmentItem entries
        3. Update order status if needed
        """
        shipment = super().save(commit=False)
        order = shipment.order

        # Set shipment number if new
        if not shipment.pk:
            shipment.shipment_number = order.get_next_shipment_number()

        if commit:
            shipment.save()

            # Create ShipmentItem entries for items marked as shipped
            if not shipment.pk:  # Only on creation
                available_items = OrderItem.objects.filter(
                    order=order,
                    shipped_to_warehouse=True,
                    current_shipment__isnull=True
                )

                for order_item in available_items:
                    ShipmentItem.objects.create(
                        shipment=shipment,
                        order_item=order_item,
                        quantity=order_item.quantity
                    )

                    # Link item to this shipment
                    order_item.current_shipment = shipment
                    order_item.save(update_fields=['current_shipment'])

                # Update order status to 'shipped' if first shipment
                if shipment.shipment_number == 1 and order.status == 'processing':
                    order.status = 'shipped'
                    order.save(update_fields=['status'])

        return shipment


# Additional form for creating shipment directly from order page
class QuickShipmentForm(forms.ModelForm):
    """
    Simplified form for creating shipment from store order page.
    Pre-fills order and only asks for essential details.
    """

    class Meta:
        model = Shipment
        fields = ["warehouse", "driver", "vehicle", "collect_time", "estimated_dropoff_time"]
        widgets = {
            "collect_time": DateTimeLocalWidget(attrs={"class": "form-control"}),
            "estimated_dropoff_time": DateTimeLocalWidget(attrs={"class": "form-control"}),
            "warehouse": forms.Select(attrs={"class": "form-select"}),
            "driver": forms.Select(attrs={"class": "form-select"}),
            "vehicle": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, order=None, *args, **kwargs):
        self.order = order
        super().__init__(*args, **kwargs)

        self.fields["warehouse"].queryset = Warehouse.objects.filter(is_active=True)
        self.fields["driver"].queryset = Driver.objects.filter(is_active=True)
        self.fields["vehicle"].queryset = Vehicle.objects.filter(is_active=True)

        # Make all fields optional for quick creation
        for field in self.fields.values():
            field.required = False

    def save(self, commit=True):
        shipment = super().save(commit=False)
        shipment.order = self.order
        shipment.shipping_address = getattr(self.order, 'shipping_address', None)
        shipment.shipment_number = self.order.get_next_shipment_number()
        shipment.status = 'pending'

        if commit:
            shipment.save()

            # Create ShipmentItem entries
            available_items = self.order.get_shipped_items_without_shipment()
            for order_item in available_items:
                ShipmentItem.objects.create(
                    shipment=shipment,
                    order_item=order_item,
                    quantity=order_item.quantity
                )
                order_item.current_shipment = shipment
                order_item.save(update_fields=['current_shipment'])

            # Update order status if first shipment
            if shipment.shipment_number == 1 and self.order.status == 'processing':
                self.order.status = 'shipped'
                self.order.save(update_fields=['status'])

        return shipment


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

# =============================================================================
# DISPATCH CENTRE FORMS
# Fields named to match templates; save()/clean() methods map to model fields.
# =============================================================================

class DispatchDriverRegistrationForm(forms.Form):
    """
    Register a new dispatch driver profile.

    Two creation modes (same form):
      A) Select an existing system user via the `user` field.
      B) Leave `user` blank → new User is created from first_name/email.

    On save() a DriverProfile is created and (for staff creators) auto-submitted
    for vetting review.

    Template: dispatch/driver_register.html
    View:     DriverRegistrationView
    """

    # ── Select existing user OR create new ───────────────────────────────────
    user = forms.ModelChoiceField(
        queryset=None,            # set in __init__
        required=False,
        empty_label="— Create a new user account —",
        label="Existing User Account",
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text="Select a user who already has a system account, or leave blank to create one below.",
    )

    DRIVER_TYPE_CHOICES = [('', '— Select driver type —')] + list([
        ("easy_move", "Easy Move (Easy Market Staff)"),
        ("external", "External / Partner Driver"),
        ("drone_operator", "Drone Operator"),
    ])
    driver_type = forms.ChoiceField(
        choices=DRIVER_TYPE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    # ── Personal info (used to create User if no existing user selected) ─────
    full_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Full legal name',
        }),
        help_text="Required only when creating a new user account.",
    )
    phone_number = forms.CharField(
        max_length=20,
        label="Mobile Phone",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '+220 000 0000',
            'type': 'tel',
        }),
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'driver@example.com',
        }),
        help_text="Required when creating a new user account.",
    )
    national_id = forms.CharField(
        max_length=50,
        required=False,
        label="National ID / Passport",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'ID or passport number',
        }),
    )
    date_of_birth = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    photo = forms.ImageField(
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control'}),
    )

    # ── Licence ──────────────────────────────────────────────────────────────
    license_number = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'DL-123456',
        }),
    )
    LICENSE_CATEGORY_CHOICES = [
        ('', '— Select —'),
        ('B', 'B — Car'),
        ('C1', 'C1 — Light Truck'),
        ('C', 'C — Heavy Truck'),
        ('D', 'D — Bus'),
        ('A', 'A — Motorcycle'),
        ('drone', 'Drone Operator'),
    ]
    license_category = forms.ChoiceField(
        choices=LICENSE_CATEGORY_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    license_expiry = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    license_document = forms.FileField(
        required=False,
        label="License Document (scan/photo)",
        widget=forms.FileInput(attrs={'class': 'form-control'}),
    )

    # ── Emergency contact ────────────────────────────────────────────────────
    emergency_contact_name = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Contact person full name',
        }),
    )
    emergency_contact_phone = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '+220 000 0000',
            'type': 'tel',
        }),
    )

    # ── Notes ────────────────────────────────────────────────────────────────
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Any additional notes about this driver…',
        }),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from django.contrib.auth import get_user_model
        UserModel = get_user_model()
        # Only users that don't yet have a DriverProfile
        from .dispatch_models import DriverProfile
        taken_ids = DriverProfile.objects.values_list('user_id', flat=True)
        self.fields['user'].queryset = (
            UserModel.objects.exclude(id__in=taken_ids)
            .order_by('first_name', 'last_name', 'username')
        )
        self.fields['user'].label_from_instance = lambda u: (
            f"{u.get_full_name() or u.username} <{u.email}>"
        )

    # ─────────────────────────── validation ──────────────────────────────────

    def clean(self):
        cleaned = super().clean()
        selected_user = cleaned.get('user')
        email = (cleaned.get('email') or '').strip().lower()
        full_name = (cleaned.get('full_name') or '').strip()

        if not selected_user:
            # Creating a new user — need at least full_name and email
            if not full_name:
                self.add_error('full_name', "Full name is required when creating a new user account.")
            if not email:
                self.add_error('email', "Email is required when creating a new user account.")

        return cleaned

    def clean_email(self):
        from django.contrib.auth import get_user_model
        UserModel = get_user_model()
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if email and self.cleaned_data.get('user') is None:
            if UserModel.objects.filter(email__iexact=email).exists():
                raise ValidationError("A user with this email already exists.")
        return email

    def clean_phone_number(self):
        from .dispatch_models import DriverProfile
        phone = (self.cleaned_data.get('phone_number') or '').strip()
        if phone and DriverProfile.objects.filter(phone=phone).exists():
            raise ValidationError("A driver profile with this phone number already exists.")
        return phone

    def clean_license_number(self):
        from .dispatch_models import DriverProfile
        license_number = (self.cleaned_data.get('license_number') or '').strip().upper()
        if license_number and DriverProfile.objects.filter(license_number__iexact=license_number).exists():
            raise ValidationError("A driver with this license number already exists.")
        return license_number

    def get_name_parts(self):
        """Split `full_name` into (first_name, last_name)."""
        full = (self.cleaned_data.get('full_name') or '').strip()
        parts = full.split(' ', 1)
        return parts[0], (parts[1] if len(parts) > 1 else '')

    def save(self, created_by=None, commit=True):
        """
        Create the User (if needed) and DriverProfile.
        Returns the DriverProfile instance.
        """
        from django.contrib.auth import get_user_model
        from .dispatch_models import DriverProfile
        UserModel = get_user_model()

        data = self.cleaned_data
        selected_user = data.get('user')

        if selected_user:
            user = selected_user
        else:
            # Create a new user from full_name + email
            first_name, last_name = self.get_name_parts()
            email = data['email'].lower()
            user = UserModel.objects.create_user(
                username=email,
                email=email,
                first_name=first_name,
                last_name=last_name,
            )
            if hasattr(user, 'is_driver'):
                user.is_driver = True
                user.save(update_fields=['is_driver'])

        profile = DriverProfile(
            user=user,
            driver_type=data.get('driver_type', DriverProfile.DriverType.EXTERNAL),
            phone=data.get('phone_number', ''),
            national_id_number=data.get('national_id', ''),
            date_of_birth=data.get('date_of_birth') or None,
            license_number=data.get('license_number', ''),
            license_category=data.get('license_category', ''),
            license_expiry=data.get('license_expiry') or None,
            emergency_contact_name=data.get('emergency_contact_name', ''),
            emergency_contact_phone=data.get('emergency_contact_phone', ''),
            notes=data.get('notes', ''),
            vetting_status=DriverProfile.VettingStatus.PENDING,
        )
        if data.get('photo'):
            profile.photo = data['photo']

        if commit:
            profile.save()

        return profile


class DispatchDriverEditForm(forms.Form):
    """
    Edit an existing DriverProfile.
    Field names mirror the driver_edit.html template;
    view maps cleaned_data back to model fields.

    Template: dispatch/driver_edit.html
    View:     DriverEditView
    """

    # ── Personal ─────────────────────────────────────────────────────────────
    full_name = forms.CharField(
        max_length=150,
        required=False,
        label="Full Name",
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        help_text="Updates the linked User account's first/last name.",
    )
    phone_number = forms.CharField(
        max_length=20,
        label="Mobile Phone",
        widget=forms.TextInput(attrs={'class': 'form-control', 'type': 'tel'}),
    )
    email = forms.EmailField(
        required=False,
        disabled=True,                    # email cannot be changed after creation
        widget=forms.EmailInput(attrs={'class': 'form-control'}),
        help_text="Email cannot be changed after account creation.",
    )
    national_id = forms.CharField(
        max_length=50,
        required=False,
        label="National ID / Passport",
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    date_of_birth = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    photo = forms.ImageField(
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control'}),
        help_text="Leave blank to keep the current photo.",
    )

    # ── Licence ──────────────────────────────────────────────────────────────
    license_number = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    LICENSE_CATEGORY_CHOICES = [
        ('', '— Select —'),
        ('B', 'B — Car'), ('C1', 'C1 — Light Truck'), ('C', 'C — Heavy Truck'),
        ('D', 'D — Bus'), ('A', 'A — Motorcycle'), ('drone', 'Drone Operator'),
    ]
    license_category = forms.ChoiceField(
        choices=LICENSE_CATEGORY_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    license_expiry = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )

    # ── Availability (staff only) ────────────────────────────────────────────
    AVAILABILITY_CHOICES = [
        ('available', 'Available'),
        ('on_trip', 'On Trip'),
        ('offline', 'Offline'),
        ('on_leave', 'On Leave'),
    ]
    availability = forms.ChoiceField(
        choices=AVAILABILITY_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    # ── Emergency contact ────────────────────────────────────────────────────
    emergency_contact_name = forms.CharField(
        max_length=100, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    emergency_contact_phone = forms.CharField(
        max_length=20, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'type': 'tel'}),
    )

    # ── Notes ────────────────────────────────────────────────────────────────
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )

    def __init__(self, *args, driver=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._driver = driver
        # Pre-populate from driver object on GET (no POST data)
        if driver and not self.is_bound:
            user = getattr(driver, 'user', None)
            self.fields['full_name'].initial = (
                user.get_full_name() if user else ''
            )
            self.fields['phone_number'].initial = getattr(driver, 'phone', '')
            self.fields['email'].initial = user.email if user else ''
            self.fields['national_id'].initial = getattr(driver, 'national_id_number', '')
            self.fields['date_of_birth'].initial = getattr(driver, 'date_of_birth', None)
            self.fields['license_number'].initial = getattr(driver, 'license_number', '')
            self.fields['license_category'].initial = getattr(driver, 'license_category', '')
            self.fields['license_expiry'].initial = getattr(driver, 'license_expiry', None)
            self.fields['availability'].initial = getattr(driver, 'availability', 'available')
            self.fields['emergency_contact_name'].initial = getattr(driver, 'emergency_contact_name', '')
            self.fields['emergency_contact_phone'].initial = getattr(driver, 'emergency_contact_phone', '')
            self.fields['notes'].initial = getattr(driver, 'notes', '')

    def clean_phone_number(self):
        from .dispatch_models import DriverProfile
        phone = (self.cleaned_data.get('phone_number') or '').strip()
        qs = DriverProfile.objects.filter(phone=phone)
        if self._driver and getattr(self._driver, 'pk', None):
            qs = qs.exclude(pk=self._driver.pk)
        if qs.exists():
            raise ValidationError("Another driver with this phone number already exists.")
        return phone

    def clean_license_number(self):
        from .dispatch_models import DriverProfile
        license_number = (self.cleaned_data.get('license_number') or '').strip().upper()
        if not license_number:
            return license_number
        qs = DriverProfile.objects.filter(license_number__iexact=license_number)
        if self._driver and getattr(self._driver, 'pk', None):
            qs = qs.exclude(pk=self._driver.pk)
        if qs.exists():
            raise ValidationError("A driver with this license number already exists.")
        return license_number

    def get_name_parts(self):
        full = (self.cleaned_data.get('full_name') or '').strip()
        parts = full.split(' ', 1)
        return parts[0], (parts[1] if len(parts) > 1 else '')

    def apply_to_driver(self, driver, files=None, is_staff=False):
        """
        Apply validated form data to an existing DriverProfile and its linked User.
        The caller is responsible for driver.save().
        """
        data = self.cleaned_data

        # Update User name
        user = driver.user
        first_name, last_name = self.get_name_parts()
        if first_name:
            user.first_name = first_name
            user.last_name = last_name
            user.save(update_fields=['first_name', 'last_name'])

        # Map form fields → model fields
        field_map = {
            'phone_number':         'phone',
            'national_id':          'national_id_number',
            'license_number':       'license_number',
            'license_category':     'license_category',
            'license_expiry':       'license_expiry',
            'date_of_birth':        'date_of_birth',
            'emergency_contact_name':  'emergency_contact_name',
            'emergency_contact_phone': 'emergency_contact_phone',
            'notes':                'notes',
        }
        fields_saved = []
        for form_key, model_field in field_map.items():
            value = data.get(form_key)
            if value is not None and value != '':
                setattr(driver, model_field, value)
                fields_saved.append(model_field)

        if is_staff and data.get('availability'):
            driver.availability = data['availability']
            fields_saved.append('availability')

        if files and files.get('photo'):
            driver.photo = files['photo']
            fields_saved.append('photo')

        if fields_saved:
            fields_saved.append('updated_at')
            driver.save(update_fields=fields_saved)

        return driver


class PickupTaskForm(forms.Form):
    """
    Create a new Pickup Task.

    Field names match BOTH the pickup_task_create.html template AND the names
    that CreatePickupTaskView reads from POST, so the view can use
    form.cleaned_data directly.

    Template: dispatch/pickup_task_create.html
    View:     CreatePickupTaskView
    """

    ORDER_TYPE_CHOICES = [
        ('', '— Select order type —'),
        ('regular', 'Regular Marketplace Order'),
        ('b2b',     'B2B Order'),
        ('crossroad', 'Black Market / Crossroad Order'),
    ]
    order_type = forms.ChoiceField(
        choices=ORDER_TYPE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text="The type of order this pickup is for.",
    )
    order_id = forms.CharField(
        max_length=100,
        label="Order ID",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. 1042 or UUID for B2B / Crossroad',
        }),
        help_text="The ID of the order to create a pickup task for.",
    )
    warehouse_id = forms.ModelChoiceField(
        queryset=None,           # set in __init__
        label="Destination Warehouse",
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text="Easy Market warehouse where the package will be delivered.",
    )
    pickup_address = forms.CharField(
        max_length=500,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '123 Kairaba Avenue, Banjul',
        }),
    )
    packages_count = forms.IntegerField(
        min_value=1,
        initial=1,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
    )
    PRIORITY_CHOICES = [
        (1, 'Low'),
        (2, 'Normal'),
        (3, 'High'),
        (4, 'Urgent'),
        (5, 'Critical'),
    ]
    priority = forms.ChoiceField(
        choices=PRIORITY_CHOICES,
        initial=2,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    scheduled_pickup_time = forms.DateTimeField(
        required=False,
        label="Scheduled Pickup Time",
        widget=forms.DateTimeInput(attrs={
            'class': 'form-control',
            'type': 'datetime-local',
        }),
    )
    pickup_contact_name = forms.CharField(
        max_length=150,
        required=False,
        label="Contact Name at Pickup",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Seller / contact person name',
        }),
    )
    pickup_contact_phone = forms.CharField(
        max_length=20,
        required=False,
        label="Contact Phone at Pickup",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '+220 000 0000',
            'type': 'tel',
        }),
    )
    special_instructions = forms.CharField(
        required=False,
        label="Special Instructions",
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Fragile items, call before arrival, gate code, etc.',
        }),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import Warehouse
        self.fields['warehouse_id'].queryset = (
            Warehouse.objects.filter(is_active=True).order_by('name')
        )
        self.fields['warehouse_id'].label_from_instance = lambda w: w.name

    def clean_scheduled_pickup_time(self):
        t = self.cleaned_data.get('scheduled_pickup_time')
        if t and t < timezone.now():
            raise ValidationError("Scheduled pickup time cannot be in the past.")
        return t

    def get_post_data(self):
        """
        Return a dict that matches what CreatePickupTaskView expects from request.POST.
        Views can call this directly to feed into DispatchService.
        """
        data = self.cleaned_data
        warehouse = data.get('warehouse_id')
        return {
            'order_type':          data.get('order_type', ''),
            'order_id':            data.get('order_id', ''),
            'warehouse_id':        str(warehouse.pk) if warehouse else '',
            'pickup_address':      data.get('pickup_address', ''),
            'packages_count':      str(data.get('packages_count', 1)),
            'priority':            str(data.get('priority', 2)),
            'pickup_contact_name': data.get('pickup_contact_name', ''),
            'pickup_contact_phone': data.get('pickup_contact_phone', ''),
            'special_instructions': data.get('special_instructions', ''),
            'scheduled_pickup_time': (
                data['scheduled_pickup_time'].strftime('%Y-%m-%dT%H:%M')
                if data.get('scheduled_pickup_time') else ''
            ),
        }


class LastMileTaskForm(forms.Form):
    """
    Create a new Last-Mile Delivery Task.

    Field names match BOTH the last_mile_create.html template AND the names
    CreateLastMileTaskView reads from POST.

    Template: dispatch/last_mile_create.html
    View:     CreateLastMileTaskView
    """

    shipment_id = forms.ModelChoiceField(
        queryset=None,           # set in __init__
        label="Shipment",
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text="Select the shipment that needs last-mile delivery.",
    )
    warehouse_id = forms.ModelChoiceField(
        queryset=None,           # set in __init__
        label="Origin Warehouse",
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text="Warehouse from which the package will be dispatched.",
    )
    delivery_address = forms.CharField(
        max_length=500,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '45 Independence Drive, Banjul',
        }),
        help_text="Leave blank to auto-fill from shipment address.",
        required=False,
    )
    recipient_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Recipient full name',
        }),
    )
    recipient_phone = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '+220 000 0000',
            'type': 'tel',
        }),
    )
    scheduled_delivery_time = forms.DateTimeField(
        required=False,
        label="Scheduled Delivery Time",
        widget=forms.DateTimeInput(attrs={
            'class': 'form-control',
            'type': 'datetime-local',
        }),
    )
    PRIORITY_CHOICES = [
        (1, 'Low'),
        (2, 'Normal'),
        (3, 'High'),
        (4, 'Urgent'),
        (5, 'Critical'),
    ]
    priority = forms.ChoiceField(
        choices=PRIORITY_CHOICES,
        initial=2,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    special_instructions = forms.CharField(
        required=False,
        label="Special Instructions / Notes",
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Gate codes, floor numbers, call before delivery, etc.',
        }),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import Warehouse, Shipment
        # Only shipments that are in-transit/shipped and don't yet have a last-mile task
        self.fields['shipment_id'].queryset = (
            Shipment.objects
            .filter(status__in=['in_transit', 'shipped'])
            .exclude(last_mile_task__isnull=False)
            .order_by('-created_at')
            .select_related('order')[:200]
        )
        self.fields['shipment_id'].label_from_instance = lambda s: (
            f"#{s.tracking_number}" if hasattr(s, 'tracking_number') else str(s)
        )
        self.fields['warehouse_id'].queryset = (
            Warehouse.objects.filter(is_active=True).order_by('name')
        )
        self.fields['warehouse_id'].label_from_instance = lambda w: w.name

    def clean_scheduled_delivery_time(self):
        t = self.cleaned_data.get('scheduled_delivery_time')
        if t and t < timezone.now():
            raise ValidationError("Scheduled delivery time cannot be in the past.")
        return t


class BatchDispatchForm(forms.Form):
    """
    Top-level settings for a batch dispatch run.
    Individual task rows are submitted as tasks-{i}-* and handled by
    DispatchBatchCreateView.post() / DispatchService.create_dispatch_batch().

    Template: dispatch/batch_create.html
    View:     DispatchBatchCreateView
    """

    BATCH_TYPE_CHOICES = [
        ('pickup',   'Pickup Run'),
        ('delivery', 'Delivery Run'),
        ('mixed',    'Mixed (Pickup + Delivery)'),
    ]
    batch_type = forms.ChoiceField(
        choices=BATCH_TYPE_CHOICES,
        initial='mixed',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    driver_id = forms.ModelChoiceField(
        queryset=None,
        required=False,
        label="Assign Driver",
        empty_label="— No driver (drone-only batch) —",
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    drone_id = forms.ModelChoiceField(
        queryset=None,
        required=False,
        label="Assign Drone",
        empty_label="— No drone —",
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    planned_start_time = forms.DateTimeField(
        required=False,
        label="Planned Start Time",
        widget=forms.DateTimeInput(attrs={
            'class': 'form-control',
            'type': 'datetime-local',
        }),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .dispatch_models import DriverProfile, DroneUnit

        self.fields['driver_id'].queryset = (
            DriverProfile.objects
            .filter(
                is_active=True,
                vetting_status=DriverProfile.VettingStatus.APPROVED,
                availability=DriverProfile.Availability.AVAILABLE,
            )
            .select_related('user')
            .order_by('user__first_name', 'user__last_name')
        )
        self.fields['driver_id'].label_from_instance = lambda d: (
            d.user.get_full_name() or d.user.username
        )

        self.fields['drone_id'].queryset = (
            DroneUnit.objects
            .filter(is_active=True, status=DroneUnit.DroneStatus.AVAILABLE, battery_level__gte=30)
            .order_by('drone_id')
        )
        self.fields['drone_id'].label_from_instance = lambda d: (
            f"{d.drone_id} ({d.battery_level}%)"
        )

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('driver_id') and not cleaned.get('drone_id'):
            raise ValidationError("A batch must be assigned to either a driver or a drone.")
        return cleaned

    def clean_planned_start_time(self):
        t = self.cleaned_data.get('planned_start_time')
        if t and t < timezone.now():
            raise ValidationError("Planned start time cannot be in the past.")
        return t