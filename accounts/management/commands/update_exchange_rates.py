# accounts/management/commands/update_exchange_rates.py
"""
Django management command to update currency exchange rates from online sources.

Usage:
    python manage.py update_exchange_rates
    python manage.py update_exchange_rates --provider=fixer --api-key=YOUR_KEY
    python manage.py update_exchange_rates --base=EUR
"""

from django.core.management.base import BaseCommand
from accounts.currency_utils import update_exchange_rates


class Command(BaseCommand):
    help = 'Update currency exchange rates from online API'

    def add_arguments(self, parser):
        parser.add_argument(
            '--provider',
            type=str,
            default='exchangerate-api',
            help='Exchange rate provider (exchangerate-api, fixer, openexchangerates)',
        )
        parser.add_argument(
            '--api-key',
            type=str,
            default=None,
            help='API key for the exchange rate provider',
        )
        parser.add_argument(
            '--base',
            type=str,
            default=None,
            help='Base currency code (default: from database settings)',
        )

    def handle(self, *args, **options):
        provider = options['provider']
        api_key = options['api_key']
        base_currency = options['base']

        self.stdout.write(self.style.WARNING(f'Updating exchange rates from {provider}...'))

        if base_currency:
            self.stdout.write(f'Using base currency: {base_currency}')

        success_count, error_count, message = update_exchange_rates(
            base_currency_code=base_currency,
            provider=provider,
            api_key=api_key
        )

        if error_count > 0:
            self.stdout.write(self.style.WARNING(message))
        else:
            self.stdout.write(self.style.SUCCESS(message))

        if success_count > 0:
            self.stdout.write(self.style.SUCCESS(f'✓ Successfully updated {success_count} exchange rates'))
        if error_count > 0:
            self.stdout.write(self.style.ERROR(f'✗ {error_count} errors occurred'))