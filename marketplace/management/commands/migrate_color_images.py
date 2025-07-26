from django.core.management.base import BaseCommand
from django.db import transaction
from marketplace.models import Product, ProductImage, ProductFeature
import re


class Command(BaseCommand):
    help = 'Migrate existing product images to color-based system'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be migrated without making changes',
        )
        parser.add_argument(
            '--product-id',
            type=int,
            help='Migrate specific product by ID',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        product_id = options['product_id']

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))

        # Get products to process
        if product_id:
            products = Product.objects.filter(id=product_id)
        else:
            products = Product.objects.all()

        self.stdout.write(f'Processing {products.count()} products...')

        for product in products:
            self.migrate_product_images(product, dry_run)

        self.stdout.write(self.style.SUCCESS('Migration completed!'))

    def migrate_product_images(self, product, dry_run):
        """Migrate images for a single product"""
        self.stdout.write(f'\nProcessing product: {product.name}')

        # Get existing images
        images = product.images.all()
        if not images.exists():
            self.stdout.write('  No images found, skipping...')
            return

        # Get available colors from product features
        available_colors = []
        try:
            color_features = ProductFeature.objects.filter(
                product=product,
                feature__name__icontains='color'
            )
            available_colors = [f.value for f in color_features]
        except:
            # Fallback if ProductFeature model doesn't exist
            pass

        # Try to extract colors from image names/paths
        color_patterns = {
            r'red|crimson|scarlet|cherry': 'Red',
            r'blue|navy|azure|sky': 'Blue',
            r'green|forest|emerald|lime': 'Green',
            r'yellow|golden|amber|lemon': 'Yellow',
            r'black|dark|noir': 'Black',
            r'white|pearl|ivory': 'White',
            r'brown|tan|chocolate': 'Brown',
            r'pink|rose|magenta': 'Pink',
            r'purple|violet|lavender': 'Purple',
            r'orange|coral|peach': 'Orange',
            r'gray|grey|silver': 'Gray',
        }

        for image in images:
            color_detected = None
            image_name = image.image.name.lower()

            # Try to detect color from filename
            for pattern, color in color_patterns.items():
                if re.search(pattern, image_name):
                    color_detected = color
                    break

            # Check if detected color matches available colors
            if color_detected and available_colors:
                matching_color = None
                for available_color in available_colors:
                    if color_detected.lower() in available_color.lower() or \
                            available_color.lower() in color_detected.lower():
                        matching_color = available_color
                        break

                if matching_color:
                    color_detected = matching_color

            if color_detected:
                if not dry_run:
                    image.color = color_detected
                    image.save()
                self.stdout.write(f'  Image {image.id}: {color_detected}')
            else:
                self.stdout.write(f'  Image {image.id}: No color detected')

        # Set primary images for each color
        if not dry_run:
            self.set_primary_images(product)

    def set_primary_images(self, product):
        """Set primary images for each color variant"""
        colors = product.images.exclude(color__isnull=True).values_list('color', flat=True).distinct()

        for color in colors:
            color_images = product.images.filter(color=color)
            if color_images.exists() and not color_images.filter(is_primary=True).exists():
                # Set first image as primary
                first_image = color_images.first()
                first_image.is_primary = True
                first_image.save()
                self.stdout.write(f'  Set primary image for {color}')
