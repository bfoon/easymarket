from django.core.management.base import BaseCommand
from orders.models import ShippingAddress
from logistics.utils import geocode_address_with_plus_code


class Command(BaseCommand):
    help = 'Geocode addresses that don\'t have coordinates'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Re-geocode all addresses, even those with existing coordinates',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=50,
            help='Limit number of addresses to process (default: 50)',
        )

    def handle(self, *args, **options):
        self.stdout.write("Starting geocoding process...")

        # Get addresses without coordinates
        if options['force']:
            addresses = ShippingAddress.objects.all()
        else:
            addresses = ShippingAddress.objects.filter(
                latitude__isnull=True
            )

        # Limit the number of requests
        addresses = addresses[:options['limit']]

        processed = 0
        successful = 0

        for address in addresses:
            processed += 1

            self.stdout.write(f"Processing {processed}/{len(addresses)}: {address.full_name}")

            # Geocode the address
            full_address = f"{address.street}, {address.city}, {address.region}"
            result = geocode_address_with_plus_code(full_address, address.geo_code)

            if result:
                address.latitude = result['lat']
                address.longitude = result['lng']
                address.geocoding_source = result['accuracy']
                address.save()

                successful += 1
                self.stdout.write(
                    f"  ✓ Geocoded: {result['lat']}, {result['lng']} via {result['source']}"
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f"  ✗ Failed to geocode address")
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Geocoding complete!\n"
                f"Processed: {processed}\n"
                f"Successful: {successful}\n"
                f"Success rate: {(successful / processed * 100):.1f}%"
            )
        )

