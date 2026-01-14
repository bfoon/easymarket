# accounts/management/commands/populate_countries_currencies.py
"""
Django management command to populate the database with countries and currencies.

Usage:
    python manage.py populate_countries_currencies
    python manage.py populate_countries_currencies --update-rates
"""

from django.core.management.base import BaseCommand
from decimal import Decimal
from accounts.models import Country, Currency, CurrencyExchangeRate


class Command(BaseCommand):
    help = 'Populate database with countries and currencies'

    def add_arguments(self, parser):
        parser.add_argument(
            '--update-rates',
            action='store_true',
            help='Also update exchange rates from API',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting to populate countries and currencies...'))

        # Create currencies first
        currencies_created = self.create_currencies()
        self.stdout.write(self.style.SUCCESS(f'Created/Updated {currencies_created} currencies'))

        # Create countries
        countries_created = self.create_countries()
        self.stdout.write(self.style.SUCCESS(f'Created/Updated {countries_created} countries'))

        # Update exchange rates if requested
        if options['update_rates']:
            self.stdout.write(self.style.WARNING('Updating exchange rates...'))
            from accounts.currency_utils import update_exchange_rates
            success, errors, message = update_exchange_rates()
            self.stdout.write(self.style.SUCCESS(message))

        self.stdout.write(self.style.SUCCESS('Population complete!'))

    def create_currencies(self):
        """Create common world currencies"""
        currencies_data = [
            # Code, Name, Symbol, Decimal Places, Is Base
            ('GMD', 'Gambian Dalasi', 'D', 2, True),  # Set GMD as base for Gambia
            ('USD', 'US Dollar', '$', 2, False),
            ('EUR', 'Euro', '€', 2, False),
            ('GBP', 'British Pound', '£', 2, False),
            ('CNY', 'Chinese Yuan', '¥', 2, False),
            ('JPY', 'Japanese Yen', '¥', 0, False),
            ('AUD', 'Australian Dollar', 'A$', 2, False),
            ('CAD', 'Canadian Dollar', 'C$', 2, False),
            ('CHF', 'Swiss Franc', 'Fr', 2, False),
            ('INR', 'Indian Rupee', '₹', 2, False),
            ('NGN', 'Nigerian Naira', '₦', 2, False),
            ('ZAR', 'South African Rand', 'R', 2, False),
            ('KES', 'Kenyan Shilling', 'KSh', 2, False),
            ('GHS', 'Ghanaian Cedi', 'GH₵', 2, False),
            ('XOF', 'West African CFA Franc', 'CFA', 0, False),
            ('EGP', 'Egyptian Pound', 'E£', 2, False),
            ('MAD', 'Moroccan Dirham', 'DH', 2, False),
            ('AED', 'UAE Dirham', 'د.إ', 2, False),
            ('SAR', 'Saudi Riyal', 'SR', 2, False),
            ('BRL', 'Brazilian Real', 'R$', 2, False),
            ('MXN', 'Mexican Peso', 'Mex$', 2, False),
            ('RUB', 'Russian Ruble', '₽', 2, False),
            ('KRW', 'South Korean Won', '₩', 0, False),
            ('SGD', 'Singapore Dollar', 'S$', 2, False),
            ('HKD', 'Hong Kong Dollar', 'HK$', 2, False),
            ('NZD', 'New Zealand Dollar', 'NZ$', 2, False),
            ('SEK', 'Swedish Krona', 'kr', 2, False),
            ('NOK', 'Norwegian Krone', 'kr', 2, False),
            ('DKK', 'Danish Krone', 'kr', 2, False),
            ('PLN', 'Polish Zloty', 'zł', 2, False),
            ('TRY', 'Turkish Lira', '₺', 2, False),
            ('THB', 'Thai Baht', '฿', 2, False),
            ('MYR', 'Malaysian Ringgit', 'RM', 2, False),
            ('IDR', 'Indonesian Rupiah', 'Rp', 0, False),
            ('PHP', 'Philippine Peso', '₱', 2, False),
            ('VND', 'Vietnamese Dong', '₫', 0, False),
            ('ILS', 'Israeli Shekel', '₪', 2, False),
            ('CZK', 'Czech Koruna', 'Kč', 2, False),
            ('HUF', 'Hungarian Forint', 'Ft', 0, False),
            ('RON', 'Romanian Leu', 'lei', 2, False),
        ]

        count = 0
        for code, name, symbol, decimals, is_base in currencies_data:
            currency, created = Currency.objects.update_or_create(
                code=code,
                defaults={
                    'name': name,
                    'symbol': symbol,
                    'decimal_places': decimals,
                    'is_base_currency': is_base,
                    'is_active': True,
                }
            )
            count += 1
            action = "Created" if created else "Updated"
            self.stdout.write(f"  {action}: {code} - {name}")

        return count

    def create_countries(self):
        """Create countries with their currencies and flag emojis"""
        countries_data = [
            # Name, Code, Code3, Numeric, Phone, Currency Code, Flag Emoji
            ('Afghanistan', 'AF', 'AFG', '004', '+93', 'USD', '🇦🇫'),
            ('Albania', 'AL', 'ALB', '008', '+355', 'EUR', '🇦🇱'),
            ('Algeria', 'DZ', 'DZA', '012', '+213', 'EUR', '🇩🇿'),
            ('Andorra', 'AD', 'AND', '020', '+376', 'EUR', '🇦🇩'),
            ('Angola', 'AO', 'AGO', '024', '+244', 'USD', '🇦🇴'),
            ('Argentina', 'AR', 'ARG', '032', '+54', 'USD', '🇦🇷'),
            ('Australia', 'AU', 'AUS', '036', '+61', 'AUD', '🇦🇺'),
            ('Austria', 'AT', 'AUT', '040', '+43', 'EUR', '🇦🇹'),
            ('Bahrain', 'BH', 'BHR', '048', '+973', 'USD', '🇧🇭'),
            ('Bangladesh', 'BD', 'BGD', '050', '+880', 'USD', '🇧🇩'),
            ('Belgium', 'BE', 'BEL', '056', '+32', 'EUR', '🇧🇪'),
            ('Benin', 'BJ', 'BEN', '204', '+229', 'XOF', '🇧🇯'),
            ('Bolivia', 'BO', 'BOL', '068', '+591', 'USD', '🇧🇴'),
            ('Botswana', 'BW', 'BWA', '072', '+267', 'ZAR', '🇧🇼'),
            ('Brazil', 'BR', 'BRA', '076', '+55', 'BRL', '🇧🇷'),
            ('Bulgaria', 'BG', 'BGR', '100', '+359', 'EUR', '🇧🇬'),
            ('Burkina Faso', 'BF', 'BFA', '854', '+226', 'XOF', '🇧🇫'),
            ('Burundi', 'BI', 'BDI', '108', '+257', 'USD', '🇧🇮'),
            ('Cambodia', 'KH', 'KHM', '116', '+855', 'USD', '🇰🇭'),
            ('Cameroon', 'CM', 'CMR', '120', '+237', 'XOF', '🇨🇲'),
            ('Canada', 'CA', 'CAN', '124', '+1', 'CAD', '🇨🇦'),
            ('Chad', 'TD', 'TCD', '148', '+235', 'XOF', '🇹🇩'),
            ('Chile', 'CL', 'CHL', '152', '+56', 'USD', '🇨🇱'),
            ('China', 'CN', 'CHN', '156', '+86', 'CNY', '🇨🇳'),
            ('Colombia', 'CO', 'COL', '170', '+57', 'USD', '🇨🇴'),
            ('Costa Rica', 'CR', 'CRI', '188', '+506', 'USD', '🇨🇷'),
            ('Croatia', 'HR', 'HRV', '191', '+385', 'EUR', '🇭🇷'),
            ('Cuba', 'CU', 'CUB', '192', '+53', 'USD', '🇨🇺'),
            ('Czech Republic', 'CZ', 'CZE', '203', '+420', 'CZK', '🇨🇿'),
            ('Denmark', 'DK', 'DNK', '208', '+45', 'DKK', '🇩🇰'),
            ('Dominican Republic', 'DO', 'DOM', '214', '+1809', 'USD', '🇩🇴'),
            ('Ecuador', 'EC', 'ECU', '218', '+593', 'USD', '🇪🇨'),
            ('Egypt', 'EG', 'EGY', '818', '+20', 'EGP', '🇪🇬'),
            ('Estonia', 'EE', 'EST', '233', '+372', 'EUR', '🇪🇪'),
            ('Ethiopia', 'ET', 'ETH', '231', '+251', 'USD', '🇪🇹'),
            ('Finland', 'FI', 'FIN', '246', '+358', 'EUR', '🇫🇮'),
            ('France', 'FR', 'FRA', '250', '+33', 'EUR', '🇫🇷'),
            ('Gambia', 'GM', 'GMB', '270', '+220', 'GMD', '🇬🇲'),
            ('Germany', 'DE', 'DEU', '276', '+49', 'EUR', '🇩🇪'),
            ('Ghana', 'GH', 'GHA', '288', '+233', 'GHS', '🇬🇭'),
            ('Greece', 'GR', 'GRC', '300', '+30', 'EUR', '🇬🇷'),
            ('Guinea', 'GN', 'GIN', '324', '+224', 'XOF', '🇬🇳'),
            ('Guinea-Bissau', 'GW', 'GNB', '624', '+245', 'XOF', '🇬🇼'),
            ('Hong Kong', 'HK', 'HKG', '344', '+852', 'HKD', '🇭🇰'),
            ('Hungary', 'HU', 'HUN', '348', '+36', 'HUF', '🇭🇺'),
            ('Iceland', 'IS', 'ISL', '352', '+354', 'EUR', '🇮🇸'),
            ('India', 'IN', 'IND', '356', '+91', 'INR', '🇮🇳'),
            ('Indonesia', 'ID', 'IDN', '360', '+62', 'IDR', '🇮🇩'),
            ('Ireland', 'IE', 'IRL', '372', '+353', 'EUR', '🇮🇪'),
            ('Israel', 'IL', 'ISR', '376', '+972', 'ILS', '🇮🇱'),
            ('Italy', 'IT', 'ITA', '380', '+39', 'EUR', '🇮🇹'),
            ('Ivory Coast', 'CI', 'CIV', '384', '+225', 'XOF', '🇨🇮'),
            ('Jamaica', 'JM', 'JAM', '388', '+1876', 'USD', '🇯🇲'),
            ('Japan', 'JP', 'JPN', '392', '+81', 'JPY', '🇯🇵'),
            ('Jordan', 'JO', 'JOR', '400', '+962', 'USD', '🇯🇴'),
            ('Kenya', 'KE', 'KEN', '404', '+254', 'KES', '🇰🇪'),
            ('South Korea', 'KR', 'KOR', '410', '+82', 'KRW', '🇰🇷'),
            ('Kuwait', 'KW', 'KWT', '414', '+965', 'USD', '🇰🇼'),
            ('Lebanon', 'LB', 'LBN', '422', '+961', 'USD', '🇱🇧'),
            ('Latvia', 'LV', 'LVA', '428', '+371', 'EUR', '🇱🇻'),
            ('Liberia', 'LR', 'LBR', '430', '+231', 'USD', '🇱🇷'),
            ('Libya', 'LY', 'LBY', '434', '+218', 'EUR', '🇱🇾'),
            ('Lithuania', 'LT', 'LTU', '440', '+370', 'EUR', '🇱🇹'),
            ('Luxembourg', 'LU', 'LUX', '442', '+352', 'EUR', '🇱🇺'),
            ('Madagascar', 'MG', 'MDG', '450', '+261', 'EUR', '🇲🇬'),
            ('Malawi', 'MW', 'MWI', '454', '+265', 'USD', '🇲🇼'),
            ('Malaysia', 'MY', 'MYS', '458', '+60', 'MYR', '🇲🇾'),
            ('Mali', 'ML', 'MLI', '466', '+223', 'XOF', '🇲🇱'),
            ('Mauritania', 'MR', 'MRT', '478', '+222', 'EUR', '🇲🇷'),
            ('Mexico', 'MX', 'MEX', '484', '+52', 'MXN', '🇲🇽'),
            ('Morocco', 'MA', 'MAR', '504', '+212', 'MAD', '🇲🇦'),
            ('Mozambique', 'MZ', 'MOZ', '508', '+258', 'USD', '🇲🇿'),
            ('Myanmar', 'MM', 'MMR', '104', '+95', 'USD', '🇲🇲'),
            ('Namibia', 'NA', 'NAM', '516', '+264', 'ZAR', '🇳🇦'),
            ('Nepal', 'NP', 'NPL', '524', '+977', 'INR', '🇳🇵'),
            ('Netherlands', 'NL', 'NLD', '528', '+31', 'EUR', '🇳🇱'),
            ('New Zealand', 'NZ', 'NZL', '554', '+64', 'NZD', '🇳🇿'),
            ('Niger', 'NE', 'NER', '562', '+227', 'XOF', '🇳🇪'),
            ('Nigeria', 'NG', 'NGA', '566', '+234', 'NGN', '🇳🇬'),
            ('Norway', 'NO', 'NOR', '578', '+47', 'NOK', '🇳🇴'),
            ('Oman', 'OM', 'OMN', '512', '+968', 'USD', '🇴🇲'),
            ('Pakistan', 'PK', 'PAK', '586', '+92', 'USD', '🇵🇰'),
            ('Panama', 'PA', 'PAN', '591', '+507', 'USD', '🇵🇦'),
            ('Paraguay', 'PY', 'PRY', '600', '+595', 'USD', '🇵🇾'),
            ('Peru', 'PE', 'PER', '604', '+51', 'USD', '🇵🇪'),
            ('Philippines', 'PH', 'PHL', '608', '+63', 'PHP', '🇵🇭'),
            ('Poland', 'PL', 'POL', '616', '+48', 'PLN', '🇵🇱'),
            ('Portugal', 'PT', 'PRT', '620', '+351', 'EUR', '🇵🇹'),
            ('Qatar', 'QA', 'QAT', '634', '+974', 'SAR', '🇶🇦'),
            ('Romania', 'RO', 'ROU', '642', '+40', 'RON', '🇷🇴'),
            ('Russia', 'RU', 'RUS', '643', '+7', 'RUB', '🇷🇺'),
            ('Rwanda', 'RW', 'RWA', '646', '+250', 'USD', '🇷🇼'),
            ('Saudi Arabia', 'SA', 'SAU', '682', '+966', 'SAR', '🇸🇦'),
            ('Senegal', 'SN', 'SEN', '686', '+221', 'XOF', '🇸🇳'),
            ('Sierra Leone', 'SL', 'SLE', '694', '+232', 'USD', '🇸🇱'),
            ('Singapore', 'SG', 'SGP', '702', '+65', 'SGD', '🇸🇬'),
            ('Slovakia', 'SK', 'SVK', '703', '+421', 'EUR', '🇸🇰'),
            ('Slovenia', 'SI', 'SVN', '705', '+386', 'EUR', '🇸🇮'),
            ('Somalia', 'SO', 'SOM', '706', '+252', 'USD', '🇸🇴'),
            ('South Africa', 'ZA', 'ZAF', '710', '+27', 'ZAR', '🇿🇦'),
            ('Spain', 'ES', 'ESP', '724', '+34', 'EUR', '🇪🇸'),
            ('Sri Lanka', 'LK', 'LKA', '144', '+94', 'USD', '🇱🇰'),
            ('Sweden', 'SE', 'SWE', '752', '+46', 'SEK', '🇸🇪'),
            ('Switzerland', 'CH', 'CHE', '756', '+41', 'CHF', '🇨🇭'),
            ('Taiwan', 'TW', 'TWN', '158', '+886', 'USD', '🇹🇼'),
            ('Tanzania', 'TZ', 'TZA', '834', '+255', 'USD', '🇹🇿'),
            ('Thailand', 'TH', 'THA', '764', '+66', 'THB', '🇹🇭'),
            ('Togo', 'TG', 'TGO', '768', '+228', 'XOF', '🇹🇬'),
            ('Tunisia', 'TN', 'TUN', '788', '+216', 'EUR', '🇹🇳'),
            ('Turkey', 'TR', 'TUR', '792', '+90', 'TRY', '🇹🇷'),
            ('Uganda', 'UG', 'UGA', '800', '+256', 'USD', '🇺🇬'),
            ('Ukraine', 'UA', 'UKR', '804', '+380', 'EUR', '🇺🇦'),
            ('United Arab Emirates', 'AE', 'ARE', '784', '+971', 'AED', '🇦🇪'),
            ('United Kingdom', 'GB', 'GBR', '826', '+44', 'GBP', '🇬🇧'),
            ('United States', 'US', 'USA', '840', '+1', 'USD', '🇺🇸'),
            ('Uruguay', 'UY', 'URY', '858', '+598', 'USD', '🇺🇾'),
            ('Venezuela', 'VE', 'VEN', '862', '+58', 'USD', '🇻🇪'),
            ('Vietnam', 'VN', 'VNM', '704', '+84', 'VND', '🇻🇳'),
            ('Zambia', 'ZM', 'ZMB', '894', '+260', 'USD', '🇿🇲'),
            ('Zimbabwe', 'ZW', 'ZWE', '716', '+263', 'USD', '🇿🇼'),
        ]

        count = 0
        for name, code, code3, numeric, phone, currency_code, flag in countries_data:
            try:
                currency = Currency.objects.get(code=currency_code)
            except Currency.DoesNotExist:
                self.stdout.write(
                    self.style.WARNING(f"  Currency {currency_code} not found for {name}, skipping")
                )
                continue

            country, created = Country.objects.update_or_create(
                code=code,
                defaults={
                    'name': name,
                    'code3': code3,
                    'numeric_code': numeric,
                    'phone_code': phone,
                    'currency': currency,
                    'flag_emoji': flag,  # Add flag emoji
                    'is_active': True,
                }
            )
            count += 1
            action = "Created" if created else "Updated"
            self.stdout.write(f"  {action}: {flag} {name} ({code}) - {currency_code}")

        return count