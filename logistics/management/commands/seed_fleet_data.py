"""
Management command to seed sample fleet management data
Usage: python manage.py seed_fleet_data
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
import random
from logistics.models import (
    LogisticsLocation, DeliveryRoute, DeliveryStop, 
    VehicleTracking, FleetVehicle, Order
)
from stores.models import Store

User = get_user_model()


class Command(BaseCommand):
    help = 'Seeds the database with sample fleet management data'

    def handle(self, *args, **options):
        self.stdout.write('Seeding fleet management data...')

        # Create sample stores
        stores_data = [
            {'name': 'Main Store Banjul', 'lat': 13.4549, 'lng': -16.5790},
            {'name': 'Store Serrekunda', 'lat': 13.4380, 'lng': -16.6772},
            {'name': 'Store Brikama', 'lat': 13.2727, 'lng': -16.6505},
            {'name': 'Store Bakau', 'lat': 13.4789, 'lng': -16.6818},
        ]

        for store_data in stores_data:
            LogisticsLocation.objects.get_or_create(
                name=store_data['name'],
                defaults={
                    'location_type': 'store',
                    'address': f"{store_data['name']} Address",
                    'latitude': store_data['lat'],
                    'longitude': store_data['lng'],
                    'contact_person': 'Store Manager',
                    'contact_phone': '+220 XXX XXXX',
                    'is_active': True,
                }
            )

        # Create warehouses
        warehouses_data = [
            {'name': 'Central Warehouse', 'lat': 13.4500, 'lng': -16.6000},
            {'name': 'Distribution Center West', 'lat': 13.3000, 'lng': -16.7000},
        ]

        for warehouse_data in warehouses_data:
            LogisticsLocation.objects.get_or_create(
                name=warehouse_data['name'],
                defaults={
                    'location_type': 'warehouse',
                    'address': f"{warehouse_data['name']} Address",
                    'latitude': warehouse_data['lat'],
                    'longitude': warehouse_data['lng'],
                    'contact_person': 'Warehouse Manager',
                    'contact_phone': '+220 YYY YYYY',
                    'is_active': True,
                }
            )

        # Create sample vehicles
        vehicle_types = ['van', 'truck', 'motorcycle']
        for i in range(5):
            FleetVehicle.objects.get_or_create(
                vehicle_number=f'VEH-{i+1:03d}',
                defaults={
                    'license_plate': f'GMB-{i+1000}',
                    'vehicle_type': random.choice(vehicle_types),
                    'make_model': f'Toyota {random.choice(["Hiace", "Hilux", "Dyna"])}',
                    'year': random.randint(2018, 2024),
                    'status': 'active',
                    'capacity_kg': Decimal(random.randint(500, 2000)),
                    'mileage_km': random.randint(10000, 50000),
                    'current_latitude': Decimal('13.4549'),
                    'current_longitude': Decimal('-16.5790'),
                    'last_location_update': timezone.now(),
                }
            )

        # Create sample routes with stops
        stores = list(LogisticsLocation.objects.filter(location_type='store'))
        vehicles = list(FleetVehicle.objects.all())

        for i in range(3):
            route = DeliveryRoute.objects.create(
                route_number=f'ROUTE-{timezone.now().strftime("%Y%m%d")}-{i+1:03d}',
                vehicle=vehicles[i].vehicle_number if i < len(vehicles) else 'VEH-001',
                status=random.choice(['in_progress', 'planned', 'completed']),
                start_location=stores[0] if stores else None,
                planned_start_time=timezone.now(),
                actual_start_time=timezone.now() if random.random() > 0.3 else None,
                estimated_end_time=timezone.now() + timedelta(hours=4),
                total_distance_km=Decimal(random.randint(20, 100)),
                total_stops=random.randint(5, 15),
                completed_stops=random.randint(0, 5),
            )

            # Create stops for this route
            num_stops = random.randint(5, 10)
            for j in range(num_stops):
                # Random location around Banjul area
                lat = Decimal(str(13.4549 + (random.random() - 0.5) * 0.2))
                lng = Decimal(str(-16.5790 + (random.random() - 0.5) * 0.2))

                DeliveryStop.objects.create(
                    route=route,
                    stop_type=random.choice(['pickup', 'delivery']),
                    status=random.choice(['pending', 'completed', 'in_progress']),
                    sequence_number=j + 1,
                    address=f'{random.randint(1, 999)} Sample Street, Banjul',
                    latitude=lat,
                    longitude=lng,
                    contact_name=f'Customer {j+1}',
                    contact_phone=f'+220 {random.randint(3000000, 9999999)}',
                    packages_count=random.randint(1, 5),
                    tracking_numbers=[
                        f'TRK{timezone.now().strftime("%Y%m%d")}{random.randint(1000, 9999)}'
                        for _ in range(random.randint(1, 3))
                    ],
                )

            # Create tracking points for in-progress routes
            if route.status == 'in_progress':
                for k in range(10):
                    lat = Decimal(str(13.4549 + (random.random() - 0.5) * 0.1))
                    lng = Decimal(str(-16.5790 + (random.random() - 0.5) * 0.1))

                    VehicleTracking.objects.create(
                        route=route,
                        latitude=lat,
                        longitude=lng,
                        speed_kmh=Decimal(random.randint(0, 60)),
                        heading=random.randint(0, 360),
                        accuracy_meters=random.randint(5, 50),
                        timestamp=timezone.now() - timedelta(minutes=k*5),
                        battery_level=random.randint(20, 100),
                        is_connected=True,
                    )

        self.stdout.write(self.style.SUCCESS('Successfully seeded fleet management data!'))
        self.stdout.write(f'Created:')
        self.stdout.write(f'  - {LogisticsLocation.objects.count()} locations')
        self.stdout.write(f'  - {FleetVehicle.objects.count()} vehicles')
        self.stdout.write(f'  - {DeliveryRoute.objects.count()} routes')
        self.stdout.write(f'  - {DeliveryStop.objects.count()} stops')
        self.stdout.write(f'  - {VehicleTracking.objects.count()} tracking points')
