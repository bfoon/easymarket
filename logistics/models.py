from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from orders.models import Order, ShippingAddress, OrderItem

import qrcode
from io import BytesIO
from django.core.files.base import ContentFile

User = get_user_model()

# Logistic Office
class LogisticOffice(models.Model):
    name = models.CharField(max_length=100)
    location = models.CharField(max_length=255)

    def __str__(self):
        return self.name

# Warehouse
class Warehouse(models.Model):
    name = models.CharField(max_length=100)
    address = models.TextField()

    def __str__(self):
        return self.name

# Driver
class Driver(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    phone = models.CharField(max_length=20)
    license_number = models.CharField(max_length=50)

    def __str__(self):
        return self.user.get_full_name()

# Vehicle
class Vehicle(models.Model):
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE)
    plate_number = models.CharField(max_length=20)
    model = models.CharField(max_length=50)
    capacity_kg = models.FloatField()

    def __str__(self):
        return f"{self.plate_number} - {self.model}"

# Shipment
class Shipment(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_transit', 'In Transit'),
        ('shipped', 'Shipped'),
    ]

    MATERIAL_TYPE_CHOICES = [
        ('fragile', 'Fragile'),
        ('flammable', 'Flammable'),
        ('chemical', 'Dangerous Chemical'),
        ('standard', 'Standard'),
    ]

    SHIPMENT_TYPE_CHOICES = [
        ('express', 'Express'),
        ('normal', 'Normal'),
        ('economic', 'Economic'),
        ('free', 'Free'),
    ]

    PACKING_TYPE_CHOICES = [
        ('paper_box', 'Paper Box'),
        ('metal_box', 'Metal Box'),
        ('plastic_box', 'Plastic Box'),
    ]

    CONTAINER_TYPE_CHOICES = [
        ('plastic', 'Plastic'),
        ('paper', 'Paper'),
        ('metal', 'Metal'),
    ]

    shipping_address = models.ForeignKey(ShippingAddress, on_delete=models.CASCADE)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.SET_NULL, null=True, blank=True)
    driver = models.ForeignKey(Driver, on_delete=models.SET_NULL, null=True, blank=True)
    vehicle = models.ForeignKey(Vehicle, on_delete=models.SET_NULL, null=True, blank=True)
    logistic_office = models.ForeignKey(LogisticOffice, on_delete=models.SET_NULL, null=True, blank=True)

    collect_time = models.DateTimeField()
    estimated_dropoff_time = models.DateTimeField()

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='shipments', null=True, blank=True)
    weight_kg = models.FloatField()
    size_cubic_meters = models.FloatField()

    material_type = models.CharField(max_length=20, choices=MATERIAL_TYPE_CHOICES)
    shipment_type = models.CharField(max_length=10, choices=SHIPMENT_TYPE_CHOICES)
    packing_type = models.CharField(max_length=20, choices=PACKING_TYPE_CHOICES)
    container_type = models.CharField(max_length=20, choices=CONTAINER_TYPE_CHOICES)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def mark_as_shipped(self):
        self.status = 'shipped'
        self.save()

    def __str__(self):
        return f"Shipment #{self.id} to {self.shipping_address}"

class ShipmentBox(models.Model):
    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name='boxes')
    box_number = models.PositiveIntegerField()
    weight_kg = models.FloatField(null=True, blank=True)
    label = models.ImageField(upload_to='box_labels/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('shipment', 'box_number')
        ordering = ['box_number']

    def __str__(self):
        return f"Box #{self.box_number} of Shipment #{self.shipment.id}"

    def generate_qr_label(self):
        data = f"Shipment: {self.shipment.id} | Box: {self.box_number}"
        qr = qrcode.make(data)
        buffer = BytesIO()
        qr.save(buffer, format='PNG')
        filename = f"shipment_{self.shipment.id}_box_{self.box_number}.png"
        self.label.save(filename, ContentFile(buffer.getvalue()), save=False)
        buffer.close()

class BoxItem(models.Model):
    box = models.ForeignKey(ShipmentBox, on_delete=models.CASCADE, related_name='items')
    order_item = models.ForeignKey(OrderItem, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()

    def __str__(self):
        return f"{self.quantity} x {self.order_item.product.name} in Box #{self.box.box_number}"
