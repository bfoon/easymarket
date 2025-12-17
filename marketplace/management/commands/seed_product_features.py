from django.core.management.base import BaseCommand
from django.db import transaction
from django.apps import apps


DEFAULT_FEATURES = {
    # Fashion / Shoes
    "Color": ["Black", "White", "Grey", "Navy", "Brown", "Red", "Blue", "Green", "Beige"],
    "Size": ["EU 39", "EU 40", "EU 41", "EU 42", "EU 43", "EU 44", "EU 45", "EU 46"],
    "Shoe Size": ["EU 39", "EU 40", "EU 41", "EU 42", "EU 43", "EU 44", "EU 45", "EU 46"],
    "Fit": ["Slim", "Regular", "Loose"],
    "Material": ["Leather", "Synthetic Leather", "Mesh", "Canvas", "Suede", "Rubber"],
    "Style": ["Casual", "Street", "Smart Casual", "Sport", "Formal"],
    "Gender": ["Men", "Women", "Unisex"],
    "Condition": ["New", "Used", "Refurbished"],

    # General ecommerce
    "Capacity": ["16GB", "32GB", "64GB", "128GB", "256GB", "512GB", "1TB"],
    "Storage": ["128GB", "256GB", "512GB", "1TB", "2TB"],
    "RAM": ["2GB", "3GB", "4GB", "6GB", "8GB", "12GB", "16GB", "32GB"],
    "Network": ["2G", "3G", "4G", "5G", "Wi-Fi"],
    "Voltage": ["110V", "220V", "Dual Voltage"],
    "Warranty": ["No Warranty", "3 Months", "6 Months", "1 Year", "2 Years"],

    # For listings control
    "Pack Size": ["1", "2", "3", "5", "10"],
}


class Command(BaseCommand):
    help = "Seed ecommerce product features + options (and optionally variants for products)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--app",
            default="marketplace",
            help="App label where ProductFeature/ProductFeatureOption/ProductVariant live (default: marketplace).",
        )
        parser.add_argument(
            "--features-model",
            default="ProductFeature",
            help="Model name for features (default: ProductFeature).",
        )
        parser.add_argument(
            "--options-model",
            default="ProductFeatureOption",
            help="Model name for feature options (default: ProductFeatureOption).",
        )
        parser.add_argument(
            "--variants-model",
            default="ProductVariant",
            help="Model name for variants (default: ProductVariant).",
        )
        parser.add_argument(
            "--product-model",
            default="Product",
            help="Product model name in the same app (default: Product).",
        )
        parser.add_argument(
            "--create-variants-for-all-products",
            action="store_true",
            help="If set, creates ProductVariant rows for ALL products using a chosen feature (see --variant-feature).",
        )
        parser.add_argument(
            "--variant-feature",
            default="Color",
            help="Feature name used to create variants when --create-variants-for-all-products is set (default: Color).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would happen without writing to the DB.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        app_label = options["app"]
        Feature = apps.get_model(app_label, options["features_model"])
        Option = apps.get_model(app_label, options["options_model"])
        Variant = apps.get_model(app_label, options["variants_model"])
        Product = apps.get_model(app_label, options["product_model"])

        dry_run = options["dry_run"]

        created_features = 0
        created_options = 0
        created_variants = 0

        # 1) Seed features & options
        for feature_name, values in DEFAULT_FEATURES.items():
            if dry_run:
                self.stdout.write(f"[DRY-RUN] feature: {feature_name}")
                feature_obj = None
            else:
                feature_obj, f_created = Feature.objects.get_or_create(name=feature_name)
                created_features += int(f_created)

            for val in values:
                val = str(val).strip()
                if not val:
                    continue

                if dry_run:
                    self.stdout.write(f"  [DRY-RUN] option: {feature_name} = {val}")
                    continue

                # prevent duplicates per feature
                opt_obj, o_created = Option.objects.get_or_create(
                    feature=feature_obj,
                    value=val
                )
                created_options += int(o_created)

        # 2) Optionally create variants for all products
        if options["create_variants_for_all_products"]:
            feature_name = options["variant_feature"].strip()
            if not feature_name:
                feature_name = "Color"

            if dry_run:
                self.stdout.write(f"[DRY-RUN] would create variants for all products using feature: {feature_name}")
            else:
                try:
                    feature_obj = Feature.objects.get(name=feature_name)
                except Feature.DoesNotExist:
                    self.stdout.write(self.style.ERROR(
                        f"Feature '{feature_name}' not found. Run command without variants first."
                    ))
                    return

                feature_options = Option.objects.filter(feature=feature_obj)

                # Create variants: product × feature_option (careful, this can be huge)
                for product in Product.objects.all().iterator():
                    for opt in feature_options.iterator():
                        _, v_created = Variant.objects.get_or_create(
                            product=product,
                            feature_option=opt
                        )
                        created_variants += int(v_created)

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry-run finished (no DB changes)."))
            return

        self.stdout.write(self.style.SUCCESS(
            f"Done. Features created: {created_features}, Options created: {created_options}, Variants created: {created_variants}"
        ))
