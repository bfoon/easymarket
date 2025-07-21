from django.core.management.base import BaseCommand
from orders.models import ShippingAddress
import csv
import os


class Command(BaseCommand):
    help = 'Export addresses with Plus Codes to CSV'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output',
            type=str,
            default='plus_codes_export.csv',
            help='Output CSV file name (default: plus_codes_export.csv)',
        )

    def handle(self, *args, **options):
        output_file = options['output']

        self.stdout.write(f"Exporting Plus Codes to {output_file}...")

        addresses = ShippingAddress.objects.exclude(
            geo_code__isnull=True
        ).exclude(geo_code='')

        with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'full_name', 'street', 'city', 'region', 'geo_code',
                'phone_number', 'latitude', 'longitude', 'geocoding_source'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()

            for address in addresses:
                writer.writerow({
                    'full_name': address.full_name,
                    'street': address.street,
                    'city': address.city,
                    'region': address.region,
                    'geo_code': address.geo_code,
                    'phone_number': address.phone_number,
                    'latitude': address.latitude,
                    'longitude': address.longitude,
                    'geocoding_source': address.geocoding_source or '',
                })

        self.stdout.write(
            self.style.SUCCESS(
                f"Exported {addresses.count()} addresses to {output_file}"
            )
        )