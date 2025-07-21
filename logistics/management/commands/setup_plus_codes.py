from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from orders.models import ShippingAddress
from logistics.models import Shipment, Driver, Vehicle, Warehouse
from django.utils import timezone
from datetime import timedelta

User = get_user_model()


class Command(BaseCommand):
    help = 'Set up sample data with Plus Codes for testing the driver interface'

    def add_arguments(self, parser):
        parser.add_argument(
            '--create-driver',
            action='store_true',
            help='Create a test driver user',
        )
        parser.add_argument(
            '--create-addresses',
            action='store_true',
            help='Create test addresses with Plus Codes',
        )
        parser.add_argument(
            '--create-shipments',
            action='store_true',
            help='Create test shipments',
        )
        parser.add_argument(
            '--validate-codes',
            action='store_true',
            help='Validate existing Plus Codes in database',
        )

    def handle(self, *args, **options):
        if options['create_driver']:
            self.create_test_driver()

        if options['create_addresses']:
            self.create_test_addresses()

        if options['create_shipments']:
            self.create_test_shipments()

        if options['validate_codes']:
            self.validate_existing_codes()

    def create_test_driver(self):
        """Create a test driver user with profile"""
        self.stdout.write("Creating test driver...")

        # Create or get driver user
        driver_user, created = User.objects.get_or_create(
            username='test_driver',
            defaults={
                'email': 'driver@example.com',
                'first_name': 'John',
                'last_name': 'Doe',
                'is_driver': True,
                'is_verified': True,
            }
        )

        if created:
            driver_user.set_password('password123')
            driver_user.save()
            self.stdout.write(f"Created user: {driver_user.username}")
        else:
            self.stdout.write(f"User already exists: {driver_user.username}")

        # Create or get driver profile
        driver, created = Driver.objects.get_or_create(
            user=driver_user,
            defaults={
                'phone': '+220 123 4567',
                'license_number': 'GM-DL-001234'
            }
        )

        if created:
            self.stdout.write(f"Created driver profile for: {driver.user.get_full_name()}")

        # Create vehicle
        vehicle, created = Vehicle.objects.get_or_create(
            driver=driver,
            plate_number='GM-001-ABC',
            defaults={
                'model': 'Toyota Hiace',
                'capacity_kg': 1000.0
            }
        )

        if created:
            self.stdout.write(f"Created vehicle: {vehicle.plate_number}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Test driver setup complete!\n"
                f"Username: {driver_user.username}\n"
                f"Password: password123\n"
                f"Login URL: /admin/ or your login page"
            )
        )

    def create_test_addresses(self):
        """Create test addresses with real Gambia Plus Codes"""
        self.stdout.write("Creating test addresses with Plus Codes...")

        # Get or create a test user for addresses
        user, created = User.objects.get_or_create(
            username='test_customer',
            defaults={
                'email': 'customer@example.com',
                'first_name': 'Jane',
                'last_name': 'Smith',
                'is_buyer': True,
            }
        )

        # Real Gambia locations with Plus Codes
        test_addresses = [
            {
                'full_name': 'Aminata Jallow',
                'street': 'Kairaba Avenue, Near Traffic Light',
                'city': 'Serrekunda',
                'region': 'Kanifing',
                'geo_code': 'C7QR+2QC',  # Westfield Junction
                'phone_number': '+220 987 6543'
            },
            {
                'full_name': 'Omar Ceesay',
                'street': 'Banjul-Serrekunda Highway',
                'city': 'Banjul',
                'region': 'Banjul',
                'geo_code': 'C7QM+6RX',  # Near Arch 22
                'phone_number': '+220 555 1234'
            },
            {
                'full_name': 'Fatou Drammeh',
                'street': 'Turntable Junction',
                'city': 'Serrekunda',
                'region': 'Kanifing',
                'geo_code': 'C7QR+4PC',  # Turntable
                'phone_number': '+220 777 8899'
            },
            {
                'full_name': 'Lamin Touray',
                'street': 'Market Street',
                'city': 'Brikama',
                'region': 'West Coast Region',
                'geo_code': 'C7MQ+8QH',  # Brikama Market
                'phone_number': '+220 333 4455'
            },
            {
                'full_name': 'Isatou Sanyang',
                'street': 'Independence Drive',
                'city': 'Banjul',
                'region': 'Banjul',
                'geo_code': 'C7QM+5QR',  # Banjul Market area
                'phone_number': '+220 666 7788'
            },
            {
                'full_name': 'Modou Jobe',
                'street': 'Coastal Road',
                'city': 'Bakau',
                'region': 'Kanifing',
                'geo_code': 'C7PP+8QM',  # Bakau area
                'phone_number': '+220 999 1122'
            }
        ]

        created_count = 0
        for addr_data in test_addresses:
            address, created = ShippingAddress.objects.get_or_create(
                user=user,
                geo_code=addr_data['geo_code'],
                defaults=addr_data
            )

            if created:
                created_count += 1
                self.stdout.write(f"Created address: {address.full_name} - {address.geo_code}")

        self.stdout.write(
            self.style.SUCCESS(f"Created {created_count} test addresses with Plus Codes")
        )

    def create_test_shipments(self):
        """Create test shipments using the test addresses"""
        self.stdout.write("Creating test shipments...")

        try:
            driver = Driver.objects.get(user__username='test_driver')
            vehicle = Vehicle.objects.get(driver=driver)
        except (Driver.DoesNotExist, Vehicle.DoesNotExist):
            self.stdout.write(
                self.style.ERROR("Test driver or vehicle not found. Run with --create-driver first.")
            )
            return

        # Get test addresses
        addresses = ShippingAddress.objects.filter(
            user__username='test_customer'
        )[:4]  # Take first 4 addresses

        if not addresses:
            self.stdout.write(
                self.style.ERROR("No test addresses found. Run with --create-addresses first.")
            )
            return

        # Create shipments with different statuses
        shipment_data = [
            {'status': 'pending', 'hours_offset': 1},
            {'status': 'pending', 'hours_offset': 2},
            {'status': 'in_transit', 'hours_offset': -1},
            {'status': 'shipped', 'hours_offset': -24},
        ]

        created_count = 0
        for i, data in enumerate(shipment_data):
            if i < len(addresses):
                collect_time = timezone.now() + timedelta(hours=data['hours_offset'])
                estimated_delivery = collect_time + timedelta(hours=1)

                shipment, created = Shipment.objects.get_or_create(
                    shipping_address=addresses[i],
                    driver=driver,
                    defaults={
                        'vehicle': vehicle,
                        'collect_time': collect_time,
                        'estimated_dropoff_time': estimated_delivery,
                        'weight_kg': 15.5 + (i * 5),  # Varying weights
                        'size_cubic_meters': 0.3 + (i * 0.1),
                        'material_type': 'standard',
                        'shipment_type': 'normal',
                        'packing_type': 'paper_box',
                        'container_type': 'paper',
                        'status': data['status']
                    }
                )

                if created:
                    created_count += 1
                    self.stdout.write(
                        f"Created shipment #{shipment.id} - {shipment.status} - "
                        f"{shipment.shipping_address.geo_code}"
                    )

        self.stdout.write(
            self.style.SUCCESS(f"Created {created_count} test shipments")
        )

    def validate_existing_codes(self):
        """Validate all Plus Codes in the database"""
        self.stdout.write("Validating existing Plus Codes...")

        from logistics.utils import validate_plus_code, decode_plus_code

        addresses = ShippingAddress.objects.exclude(geo_code__isnull=True).exclude(geo_code='')

        valid_count = 0
        invalid_count = 0
        decoded_count = 0

        for address in addresses:
            is_valid = validate_plus_code(address.geo_code)

            if is_valid:
                valid_count += 1
                self.stdout.write(f"✓ Valid: {address.geo_code} - {address.full_name}")

                # Try to decode
                lat, lng = decode_plus_code(address.geo_code)
                if lat and lng:
                    decoded_count += 1

                    # Update coordinates if not already set
                    if not address.latitude:
                        address.latitude = lat
                        address.longitude = lng
                        address.geocoding_source = 'plus_code'
                        address.save()
                        self.stdout.write(f"  Updated coordinates: {lat}, {lng}")

            else:
                invalid_count += 1
                self.stdout.write(
                    self.style.WARNING(f"✗ Invalid: {address.geo_code} - {address.full_name}")
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Validation complete:\n"
                f"Valid Plus Codes: {valid_count}\n"
                f"Invalid Plus Codes: {invalid_count}\n"
                f"Successfully decoded: {decoded_count}"
            )
        )
