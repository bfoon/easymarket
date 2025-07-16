from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.urls import reverse_lazy, reverse
from django.db.models import Q
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.forms import modelformset_factory
from django.utils import timezone
from logistics.models import Shipment
from logistics.forms import ShipmentForm

from .models import (
    Shipment, ShipmentBox, BoxItem, Driver, Vehicle,
    Warehouse, LogisticOffice
)
from orders.models import Order, OrderItem
from .forms import ShipmentBoxForm, BoxItemForm


class ShipmentListView(LoginRequiredMixin, ListView):
    model = Shipment
    template_name = 'logistics/shipment_list.html'
    context_object_name = 'shipments'
    paginate_by = 20

    def get_queryset(self):
        queryset = Shipment.objects.select_related(
            'shipping_address', 'warehouse', 'driver', 'vehicle', 'order'
        ).order_by('-created_at')

        # Search functionality
        search_query = self.request.GET.get('search')
        if search_query:
            queryset = queryset.filter(
                Q(id__icontains=search_query) |
                Q(shipping_address__address__icontains=search_query) |
                Q(driver__user__first_name__icontains=search_query) |
                Q(driver__user__last_name__icontains=search_query) |
                Q(order__id__icontains=search_query)  # Added order ID search
            )

        # Status filter
        status_filter = self.request.GET.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        # Order status filter
        order_status_filter = self.request.GET.get('order_status')
        if order_status_filter:
            queryset = queryset.filter(order__status=order_status_filter)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['status_choices'] = Shipment.STATUS_CHOICES
        context['order_status_choices'] = [
            ('pending', 'Pending'),
            ('processing', 'Processing'),
            ('shipped', 'Shipped'),
            ('delivered', 'Delivered'),
            ('cancelled', 'Cancelled'),
        ]
        context['current_status'] = self.request.GET.get('status', '')
        context['current_order_status'] = self.request.GET.get('order_status', '')
        context['search_query'] = self.request.GET.get('search', '')
        return context


class ShipmentDetailView(LoginRequiredMixin, DetailView):
    model = Shipment
    template_name = 'logistics/shipment_detail.html'
    context_object_name = 'shipment'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        shipment = self.get_object()
        context['boxes'] = shipment.boxes.prefetch_related('items__order_item__product')
        context['total_boxes'] = shipment.boxes.count()

        # Add order status information
        if shipment.order:
            order = shipment.order
            context['order'] = order
            context['order_status'] = order.status
            context['order_status_display'] = order.get_status_display()
            context['is_order_delivered'] = order.status == 'delivered'
            context['can_mark_delivered'] = (
                    order.status in ['shipped'] and
                    shipment.status == 'shipped'
            )
            context['delivered_date'] = order.delivered_date
            # Make boxes read-only if order is delivered
            context['boxes_readonly'] = order.status == 'delivered'
        else:
            context['order'] = None
            context['boxes_readonly'] = False

        return context


class ShipmentCreateView(LoginRequiredMixin, CreateView):
    model = Shipment
    template_name = 'logistics/shipment_form.html'
    form_class = ShipmentForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['processing_orders_count'] = Order.objects.filter(status='processing').count()
        return context

    def get_success_url(self):
        return reverse_lazy('logistics:shipment_detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        # You can also assign request.user or other meta info here
        response = super().form_valid(form)
        messages.success(self.request, 'Shipment created successfully!')
        return response

    def form_invalid(self, form):
        # Log all field errors in the console for debugging
        print("\n=== Shipment Form Errors ===")
        for field, errors in form.errors.items():
            print(f"{field}: {errors}")

        # Optional: Set a user-facing message
        messages.error(self.request, "There was an error creating the shipment. Please review the form.")
        return super().form_invalid(form)


class ShipmentUpdateView(LoginRequiredMixin, UpdateView):
    model = Shipment
    template_name = 'logistics/shipment_form.html'
    fields = [
        'warehouse', 'driver', 'vehicle', 'logistic_office',
        'collect_time', 'estimated_dropoff_time', 'weight_kg',
        'size_cubic_meters', 'material_type', 'shipment_type', 'packing_type',
        'container_type', 'status'
    ]

    def get_success_url(self):
        return reverse_lazy('logistics:shipment_detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, 'Shipment updated successfully!')
        return super().form_valid(form)


class DriverListView(LoginRequiredMixin, ListView):
    model = Driver
    template_name = 'logistics/driver_list.html'
    context_object_name = 'drivers'
    paginate_by = 20

    def get_queryset(self):
        queryset = Driver.objects.select_related('user').prefetch_related(
            'vehicle_set', 'shipment_set'
        ).order_by('user__first_name')

        search_query = self.request.GET.get('search')
        if search_query:
            queryset = queryset.filter(
                Q(user__first_name__icontains=search_query) |
                Q(user__last_name__icontains=search_query) |
                Q(license_number__icontains=search_query) |
                Q(phone__icontains=search_query)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Add driver statistics
        for driver in context['drivers']:
            driver.active_shipments_count = driver.shipment_set.exclude(status='shipped').count()
            driver.total_shipments_count = driver.shipment_set.count()
            driver.vehicle_count = driver.vehicle_set.count()

        return context


class DriverDetailView(LoginRequiredMixin, DetailView):
    model = Driver
    template_name = 'logistics/driver_detail.html'
    context_object_name = 'driver'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        driver = self.get_object()

        # Get vehicles with computed status
        vehicles = driver.vehicle_set.all()
        for vehicle in vehicles:
            vehicle.active_shipments_count = vehicle.shipment_set.exclude(status='shipped').count()

        context['vehicles'] = vehicles
        context['recent_shipments'] = Shipment.objects.filter(
            driver=driver
        ).select_related('shipping_address', 'vehicle').order_by('-created_at')[:10]

        # Add computed statistics
        context['total_shipments'] = driver.shipment_set.count()
        context['active_shipments'] = driver.shipment_set.exclude(status='shipped').count()
        context['completed_shipments'] = driver.shipment_set.filter(status='shipped').count()
        context['vehicle_count'] = driver.vehicle_set.count()

        return context


class DriverCreateView(LoginRequiredMixin, CreateView):
    model = Driver
    form_class = None  # We'll set this in get_form_class
    template_name = 'logistics/driver_form.html'

    def get_form_class(self):
        from .forms import DriverForm
        return DriverForm

    def get_success_url(self):
        return reverse_lazy('logistics:driver_detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, f'Driver {form.instance.user.get_full_name()} created successfully!')
        return super().form_valid(form)


class DriverUpdateView(LoginRequiredMixin, UpdateView):
    model = Driver
    form_class = None
    template_name = 'logistics/driver_form.html'

    def get_form_class(self):
        from .forms import DriverForm
        return DriverForm

    def get_success_url(self):
        return reverse_lazy('logistics:driver_detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, f'Driver {form.instance.user.get_full_name()} updated successfully!')
        return super().form_valid(form)


class VehicleCreateView(LoginRequiredMixin, CreateView):
    model = Vehicle
    form_class = None
    template_name = 'logistics/vehicle_form.html'

    def get_form_class(self):
        from .forms import VehicleForm
        return VehicleForm

    def get_success_url(self):
        return reverse_lazy('logistics:vehicle_list')

    def form_valid(self, form):
        messages.success(self.request, f'Vehicle {form.instance.plate_number} created successfully!')
        return super().form_valid(form)


class VehicleUpdateView(LoginRequiredMixin, UpdateView):
    model = Vehicle
    form_class = None
    template_name = 'logistics/vehicle_form.html'

    def get_form_class(self):
        from .forms import VehicleForm
        return VehicleForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.object:
            context['active_shipments_count'] = self.object.shipment_set.exclude(status='shipped').count()
        return context

    def get_success_url(self):
        return reverse_lazy('logistics:vehicle_list')

    def form_valid(self, form):
        messages.success(self.request, f'Vehicle {form.instance.plate_number} updated successfully!')
        return super().form_valid(form)


class VehicleDetailView(LoginRequiredMixin, DetailView):
    model = Vehicle
    template_name = 'logistics/vehicle_detail.html'
    context_object_name = 'vehicle'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        vehicle = self.get_object()

        # Get shipment statistics
        context['total_shipments'] = vehicle.shipment_set.count()
        context['active_shipments'] = vehicle.shipment_set.exclude(status='shipped').count()
        context['completed_shipments'] = vehicle.shipment_set.filter(status='shipped').count()

        # Get recent shipments
        context['recent_shipments'] = vehicle.shipment_set.select_related(
            'shipping_address', 'driver'
        ).order_by('-created_at')[:10]

        return context


class WarehouseCreateView(LoginRequiredMixin, CreateView):
    model = Warehouse
    form_class = None
    template_name = 'logistics/warehouse_form.html'

    def get_form_class(self):
        from .forms import WarehouseForm
        return WarehouseForm

    def get_success_url(self):
        return reverse_lazy('logistics:warehouse_list')

    def form_valid(self, form):
        messages.success(self.request, f'Warehouse {form.instance.name} created successfully!')
        return super().form_valid(form)


class WarehouseUpdateView(LoginRequiredMixin, UpdateView):
    model = Warehouse
    form_class = None
    template_name = 'logistics/warehouse_form.html'

    def get_form_class(self):
        from .forms import WarehouseForm
        return WarehouseForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.object:
            context['active_shipments_count'] = self.object.shipment_set.exclude(status='shipped').count()
            context['completed_shipments_count'] = self.object.shipment_set.filter(status='shipped').count()
        return context

    def get_success_url(self):
        return reverse_lazy('logistics:warehouse_list')

    def form_valid(self, form):
        messages.success(self.request, f'Warehouse {form.instance.name} updated successfully!')
        return super().form_valid(form)


class WarehouseDetailView(LoginRequiredMixin, DetailView):
    model = Warehouse
    template_name = 'logistics/warehouse_detail.html'
    context_object_name = 'warehouse'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        warehouse = self.get_object()

        # Get shipment statistics
        context['total_shipments'] = warehouse.shipment_set.count()
        context['active_shipments'] = warehouse.shipment_set.exclude(status='shipped').count()
        context['completed_shipments'] = warehouse.shipment_set.filter(status='shipped').count()

        # Get recent shipments
        context['recent_shipments'] = warehouse.shipment_set.select_related(
            'shipping_address', 'driver', 'vehicle'
        ).order_by('-created_at')[:10]

        return context


class LogisticOfficeCreateView(LoginRequiredMixin, CreateView):
    model = LogisticOffice
    form_class = None
    template_name = 'logistics/logistic_office_form.html'

    def get_form_class(self):
        from .forms import LogisticOfficeForm
        return LogisticOfficeForm

    def get_success_url(self):
        return reverse_lazy('logistics:logistic_office_list')

    def form_valid(self, form):
        messages.success(self.request, f'Logistic Office {form.instance.name} created successfully!')
        return super().form_valid(form)


class LogisticOfficeUpdateView(LoginRequiredMixin, UpdateView):
    model = LogisticOffice
    form_class = None
    template_name = 'logistics/logistic_office_form.html'

    def get_form_class(self):
        from .forms import LogisticOfficeForm
        return LogisticOfficeForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.object:
            context['active_shipments_count'] = self.object.shipment_set.exclude(status='shipped').count()
            context['completed_shipments_count'] = self.object.shipment_set.filter(status='shipped').count()
        return context

    def get_success_url(self):
        return reverse_lazy('logistics:logistic_office_list')

    def form_valid(self, form):
        messages.success(self.request, f'Logistic Office {form.instance.name} updated successfully!')
        return super().form_valid(form)


class LogisticOfficeListView(LoginRequiredMixin, ListView):
    model = LogisticOffice
    template_name = 'logistics/logistic_office_list.html'
    context_object_name = 'offices'
    paginate_by = 20

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Add office statistics
        total_shipments_sum = 0
        active_shipments_sum = 0
        completed_shipments_sum = 0

        for office in context['offices']:
            office.total_shipments_count = office.shipment_set.count()
            office.active_shipments_count = office.shipment_set.exclude(status='shipped').count()
            office.completed_shipments_count = office.shipment_set.filter(status='shipped').count()

            total_shipments_sum += office.total_shipments_count
            active_shipments_sum += office.active_shipments_count
            completed_shipments_sum += office.completed_shipments_count

        context['total_shipments_sum'] = total_shipments_sum
        context['active_shipments_sum'] = active_shipments_sum
        context['completed_shipments_sum'] = completed_shipments_sum

        return context


class VehicleListView(LoginRequiredMixin, ListView):
    model = Vehicle
    template_name = 'logistics/vehicle_list.html'
    context_object_name = 'vehicles'
    paginate_by = 20

    def get_queryset(self):
        queryset = Vehicle.objects.select_related('driver__user').prefetch_related(
            'shipment_set'
        ).order_by('plate_number')

        search_query = self.request.GET.get('search')
        if search_query:
            queryset = queryset.filter(
                Q(plate_number__icontains=search_query) |
                Q(model__icontains=search_query) |
                Q(driver__user__first_name__icontains=search_query) |
                Q(driver__user__last_name__icontains=search_query)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Add vehicle statistics
        active_count = 0
        available_count = 0

        for vehicle in context['vehicles']:
            vehicle.active_shipments_count = vehicle.shipment_set.exclude(status='shipped').count()
            vehicle.total_shipments_count = vehicle.shipment_set.count()
            # Calculate current load (you might want to implement this based on your business logic)
            vehicle.current_load = 0  # Placeholder - implement based on active shipments
            vehicle.current_usage_percent = 0  # Placeholder

            if vehicle.active_shipments_count > 0:
                active_count += 1
            else:
                available_count += 1

        context['active_vehicles_count'] = active_count
        context['available_vehicles_count'] = available_count

        return context


class WarehouseListView(LoginRequiredMixin, ListView):
    model = Warehouse
    template_name = 'logistics/warehouse_list.html'
    context_object_name = 'warehouses'
    paginate_by = 20

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Add warehouse statistics
        total_shipments_sum = 0
        active_shipments_sum = 0
        completed_shipments_sum = 0

        for warehouse in context['warehouses']:
            warehouse.total_shipments_count = warehouse.shipment_set.count()
            warehouse.active_shipments_count = warehouse.shipment_set.exclude(status='shipped').count()
            warehouse.completed_shipments_count = warehouse.shipment_set.filter(status='shipped').count()

            total_shipments_sum += warehouse.total_shipments_count
            active_shipments_sum += warehouse.active_shipments_count
            completed_shipments_sum += warehouse.completed_shipments_count

        context['total_shipments_sum'] = total_shipments_sum
        context['active_shipments_sum'] = active_shipments_sum
        context['completed_shipments_sum'] = completed_shipments_sum

        return context


def update_shipment_status(request, pk):
    """AJAX view to update shipment status"""
    if request.method == 'POST':
        shipment = get_object_or_404(Shipment, pk=pk)
        new_status = request.POST.get('status')

        if new_status in dict(Shipment.STATUS_CHOICES):
            shipment.status = new_status
            shipment.save()

            if new_status == 'shipped':
                shipment.mark_as_shipped()

            return JsonResponse({
                'success': True,
                'message': f'Shipment status updated to {shipment.get_status_display()}'
            })

    return JsonResponse({'success': False, 'message': 'Invalid request'})


def generate_box_label(request, shipment_id, box_id):
    """Generate QR code label for a box"""
    shipment = get_object_or_404(Shipment, pk=shipment_id)
    box = get_object_or_404(ShipmentBox, pk=box_id, shipment=shipment)

    box.generate_qr_label()
    box.save()

    messages.success(request, f'QR label generated for Box #{box.box_number}')
    return redirect('logistics:shipment_detail', pk=shipment_id)


def mark_order_as_delivered(request, shipment_pk):
    """Mark the associated order as delivered and update shipment status"""
    if request.method == 'POST':
        shipment = get_object_or_404(Shipment, pk=shipment_pk)

        if not shipment.order:
            return JsonResponse({
                'success': False,
                'message': 'No order associated with this shipment'
            })

        # Check if shipment is shipped
        if shipment.status != 'shipped':
            return JsonResponse({
                'success': False,
                'message': 'Shipment must be shipped before marking as delivered'
            })

        # Update order status to delivered
        order = shipment.order
        old_status = order.status
        order.status = 'delivered'

        # Set delivered date if not already set
        if not order.delivered_date:
            order.delivered_date = timezone.now()

        order.save()

        # Update shipment status (you might want to add a 'delivered' status to Shipment model)
        # For now, we'll keep it as 'shipped' since the shipment itself is complete

        # Create order status history
        from orders.models import OrderStatusHistory
        OrderStatusHistory.objects.create(
            order=order,
            status='delivered',
            changed_by=request.user,
            notes=f'Marked as delivered via logistics app - Shipment #{shipment.id}'
        )

        return JsonResponse({
            'success': True,
            'message': f'Order #{order.id} marked as delivered successfully',
            'new_status': order.get_status_display(),
            'delivered_date': order.delivered_date.strftime('%B %d, %Y at %I:%M %p') if order.delivered_date else None
        })

    return JsonResponse({'success': False, 'message': 'Invalid request method'})


def get_shipment_order_status(request, shipment_pk):
    """Get the current order status for a shipment"""
    shipment = get_object_or_404(Shipment, pk=shipment_pk)

    if not shipment.order:
        return JsonResponse({
            'has_order': False,
            'message': 'No order associated with this shipment'
        })

    order = shipment.order
    return JsonResponse({
        'has_order': True,
        'order_id': order.id,
        'order_status': order.status,
        'order_status_display': order.get_status_display(),
        'can_mark_delivered': order.status == 'shipped' and shipment.status == 'shipped',
        'delivered_date': order.delivered_date.strftime('%B %d, %Y at %I:%M %p') if order.delivered_date else None,
        'is_delivered': order.status == 'delivered'
    })


class DashboardView(LoginRequiredMixin, ListView):
    template_name = 'logistics/dashboard.html'

    def get(self, request, *args, **kwargs):
        context = {
            'total_shipments': Shipment.objects.count(),
            'pending_shipments': Shipment.objects.filter(status='pending').count(),
            'in_transit_shipments': Shipment.objects.filter(status='in_transit').count(),
            'shipped_shipments': Shipment.objects.filter(status='shipped').count(),
            'total_drivers': Driver.objects.count(),
            'total_vehicles': Vehicle.objects.count(),
            'total_warehouses': Warehouse.objects.count(),
            'recent_shipments': Shipment.objects.select_related(
                'shipping_address', 'driver', 'vehicle'
            ).order_by('-created_at')[:10],
        }
        return render(request, self.template_name, context)


# Box Management Views
class ShipmentBoxCreateView(LoginRequiredMixin, CreateView):
    model = ShipmentBox
    form_class = ShipmentBoxForm
    template_name = 'logistics/box_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.shipment = get_object_or_404(Shipment, pk=kwargs['shipment_pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['shipment'] = self.shipment
        return kwargs

    def form_valid(self, form):
        form.instance.shipment = self.shipment
        messages.success(self.request, f'Box #{form.instance.box_number} created successfully!')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('logistics:shipment_detail', kwargs={'pk': self.shipment.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['shipment'] = self.shipment
        context['action'] = 'Create'
        return context


class ShipmentBoxUpdateView(LoginRequiredMixin, UpdateView):
    model = ShipmentBox
    form_class = ShipmentBoxForm
    template_name = 'logistics/box_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['shipment'] = self.object.shipment
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, f'Box #{form.instance.box_number} updated successfully!')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('logistics:shipment_detail', kwargs={'pk': self.object.shipment.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['shipment'] = self.object.shipment
        context['action'] = 'Edit'
        return context


class ShipmentBoxDeleteView(LoginRequiredMixin, DeleteView):
    model = ShipmentBox
    template_name = 'logistics/box_confirm_delete.html'

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        shipment_pk = self.object.shipment.pk
        box_number = self.object.box_number

        success_url = reverse('logistics:shipment_detail', kwargs={'pk': shipment_pk})
        result = super().delete(request, *args, **kwargs)

        messages.success(request, f'Box #{box_number} deleted successfully!')
        return result

    def get_success_url(self):
        return reverse('logistics:shipment_detail', kwargs={'pk': self.object.shipment.pk})


class BoxItemCreateView(LoginRequiredMixin, CreateView):
    model = BoxItem
    form_class = BoxItemForm
    template_name = 'logistics/box_item_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.box = get_object_or_404(ShipmentBox, pk=kwargs['box_pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['box'] = self.box
        return kwargs

    def form_valid(self, form):
        form.instance.box = self.box
        messages.success(self.request, 'Item added to box successfully!')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('logistics:shipment_detail', kwargs={'pk': self.box.shipment.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['box'] = self.box
        context['shipment'] = self.box.shipment
        context['action'] = 'Add'
        return context


class BoxItemUpdateView(LoginRequiredMixin, UpdateView):
    model = BoxItem
    form_class = BoxItemForm
    template_name = 'logistics/box_item_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['box'] = self.object.box
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, 'Box item updated successfully!')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('logistics:shipment_detail', kwargs={'pk': self.object.box.shipment.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['box'] = self.object.box
        context['shipment'] = self.object.box.shipment
        context['action'] = 'Edit'
        return context


class BoxItemDeleteView(LoginRequiredMixin, DeleteView):
    model = BoxItem
    template_name = 'logistics/box_item_confirm_delete.html'

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        shipment_pk = self.object.box.shipment.pk

        success_url = reverse('logistics:shipment_detail', kwargs={'pk': shipment_pk})
        result = super().delete(request, *args, **kwargs)

        messages.success(request, 'Item removed from box successfully!')
        return result

    def get_success_url(self):
        return reverse('logistics:shipment_detail', kwargs={'pk': self.object.box.shipment.pk})


def manage_shipment_boxes(request, shipment_pk):
    """Bulk manage boxes for a shipment"""
    shipment = get_object_or_404(Shipment, pk=shipment_pk)

    BoxFormSet = modelformset_factory(
        ShipmentBox,
        form=ShipmentBoxForm,
        extra=3,  # Allow 3 new boxes by default
        can_delete=True
    )

    if request.method == 'POST':
        formset = BoxFormSet(request.POST, queryset=shipment.boxes.all())

        if formset.is_valid():
            instances = formset.save(commit=False)

            for instance in instances:
                instance.shipment = shipment
                instance.save()

            # Delete marked instances
            for instance in formset.deleted_objects:
                instance.delete()

            messages.success(request, 'Boxes updated successfully!')
            return redirect('logistics:shipment_detail', pk=shipment.pk)
    else:
        formset = BoxFormSet(queryset=shipment.boxes.all())

    # Modify each form to include the shipment reference
    for form in formset:
        if hasattr(form, 'instance') and form.instance.pk is None:
            form.instance.shipment = shipment

    context = {
        'shipment': shipment,
        'formset': formset,
    }
    return render(request, 'logistics/manage_boxes.html', context)