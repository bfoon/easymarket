from django.core.management.base import BaseCommand
from django.db import transaction
from django.apps import apps

DEFAULT_FEATURES = {
    # Extensive Color Options with Hex Codes (format: "ColorName|#HexCode")
    "Color": [
        # Basic Colors
        "Black|#000000",
        "White|#FFFFFF",
        "Grey|#808080",
        "Silver|#C0C0C0",
        "Charcoal|#36454F",

        # Blues
        "Navy|#000080",
        "Blue|#0000FF",
        "Light Blue|#ADD8E6",
        "Sky Blue|#87CEEB",
        "Royal Blue|#4169E1",
        "Midnight Blue|#191970",
        "Teal|#008080",
        "Turquoise|#40E0D0",
        "Aqua|#00FFFF",
        "Cyan|#00FFFF",

        # Reds & Pinks
        "Red|#FF0000",
        "Dark Red|#8B0000",
        "Crimson|#DC143C",
        "Burgundy|#800020",
        "Maroon|#800000",
        "Pink|#FFC0CB",
        "Hot Pink|#FF69B4",
        "Rose|#FF007F",
        "Coral|#FF7F50",
        "Salmon|#FA8072",

        # Greens
        "Green|#008000",
        "Dark Green|#006400",
        "Forest Green|#228B22",
        "Olive|#808000",
        "Lime|#00FF00",
        "Mint|#98FF98",
        "Emerald|#50C878",
        "Sage|#9DC183",
        "Sea Green|#2E8B57",

        # Yellows & Oranges
        "Yellow|#FFFF00",
        "Gold|#FFD700",
        "Mustard|#FFDB58",
        "Beige|#F5F5DC",
        "Cream|#FFFDD0",
        "Ivory|#FFFFF0",
        "Orange|#FFA500",
        "Burnt Orange|#CC5500",
        "Peach|#FFE5B4",
        "Apricot|#FBCEB1",

        # Purples
        "Purple|#800080",
        "Violet|#EE82EE",
        "Lavender|#E6E6FA",
        "Plum|#DDA0DD",
        "Mauve|#E0B0FF",
        "Magenta|#FF00FF",
        "Indigo|#4B0082",

        # Browns
        "Brown|#A52A2A",
        "Tan|#D2B48C",
        "Khaki|#C3B091",
        "Camel|#C19A6B",
        "Chocolate|#D2691E",
        "Coffee|#6F4E37",
        "Espresso|#4E3B31",
        "Mocha|#967969",

        # Neutrals & Pastels
        "Nude|#E3BC9A",
        "Blush|#DE5D83",
        "Taupe|#483C32",
        "Sand|#C2B280",
        "Stone|#8D918D",
        "Ash|#B2BEB5",
        "Slate|#708090",

        # Multi-color (using gradient-like representation)
        "Multi-Color|#FF00FF",
        "Rainbow|#FF0000",
        "Tie-Dye|#9370DB",
        "Camouflage|#78866B",
        "Floral Print|#FF69B4",
        "Animal Print|#D2691E"
    ],

    # Product Class/Grade
    "Class": ["A", "B", "C", "D", "Premium", "Standard", "Economy"],
    "Grade": ["A+", "A", "B+", "B", "C+", "C"],
    "Quality": ["Premium", "High Quality", "Standard", "Budget", "Economy"],
    "Tier": ["Platinum", "Gold", "Silver", "Bronze", "Basic"],

    # Fashion / Clothing Sizes
    "Size": ["XXS", "XS", "S", "M", "L", "XL", "XXL", "3XL", "4XL", "5XL"],
    "Numeric Size": ["0", "2", "4", "6", "8", "10", "12", "14", "16", "18", "20", "22"],
    "Shoe Size": [
        # EU Sizes
        "EU 35", "EU 36", "EU 37", "EU 38", "EU 39", "EU 40", "EU 41", "EU 42",
        "EU 43", "EU 44", "EU 45", "EU 46", "EU 47", "EU 48",
        # US Sizes
        "US 5", "US 6", "US 7", "US 8", "US 9", "US 10", "US 11", "US 12", "US 13", "US 14"
    ],
    "Waist Size": ["28", "30", "32", "34", "36", "38", "40", "42", "44", "46"],
    "Length": ["Short", "Regular", "Long", "Extra Long"],
    "Inseam": ["28", "30", "32", "34", "36"],

    # Fit & Style
    "Fit": ["Slim Fit", "Regular Fit", "Relaxed Fit", "Loose Fit", "Oversized", "Athletic Fit", "Tailored"],
    "Cut": ["Straight", "Tapered", "Bootcut", "Skinny", "Baggy", "Cropped"],
    "Neckline": ["Crew Neck", "V-Neck", "Round Neck", "Scoop Neck", "Turtleneck", "Polo"],
    "Sleeve Length": ["Sleeveless", "Short Sleeve", "3/4 Sleeve", "Long Sleeve"],
    "Style": ["Casual", "Street", "Smart Casual", "Sport", "Formal", "Business", "Athletic", "Vintage", "Modern"],

    # Material & Fabric
    "Material": [
        # Leather
        "Leather", "Genuine Leather", "Full Grain Leather", "Top Grain Leather", "Synthetic Leather", "PU Leather",
        "Suede", "Nubuck",
        # Fabrics
        "Cotton", "Organic Cotton", "Polyester", "Nylon", "Spandex", "Elastane", "Lycra",
        "Denim", "Canvas", "Linen", "Silk", "Wool", "Cashmere", "Fleece", "Velvet",
        # Technical
        "Mesh", "Gore-Tex", "Microfiber", "Rubber", "EVA", "Memory Foam",
        # Blends
        "Cotton Blend", "Poly-Cotton", "Cotton-Spandex"
    ],
    "Fabric Type": ["Knit", "Woven", "Jersey", "French Terry", "Corduroy", "Chambray"],
    "Lining": ["Lined", "Unlined", "Partially Lined", "Fleece Lined", "Thermal Lined"],

    # Product Features
    "Pattern": ["Solid", "Striped", "Checkered", "Plaid", "Floral", "Geometric", "Abstract", "Polka Dot", "Camouflage"],
    "Closure Type": ["Zipper", "Button", "Snap", "Velcro", "Lace-Up", "Pull-On", "Buckle", "Magnetic"],
    "Collar Type": ["Spread Collar", "Point Collar", "Button-Down", "Mandarin", "No Collar", "Hood"],

    # Gender & Age
    "Gender": ["Men", "Women", "Unisex", "Boys", "Girls", "Kids"],
    "Age Group": ["Adults", "Teens", "Kids", "Toddlers", "Infants"],

    # Condition & Authenticity
    "Condition": ["New with Tags", "New without Tags", "Like New", "Very Good", "Good", "Fair", "Used", "Refurbished"],
    "Authenticity": ["Authentic", "Original", "Licensed", "Replica"],

    # Electronics - Storage & Memory
    "Storage": ["16GB", "32GB", "64GB", "128GB", "256GB", "512GB", "1TB", "2TB", "4TB", "8TB"],
    "RAM": ["2GB", "3GB", "4GB", "6GB", "8GB", "12GB", "16GB", "32GB", "64GB", "128GB"],
    "Memory Type": ["DDR3", "DDR4", "DDR5", "LPDDR4", "LPDDR5"],

    # Electronics - Display
    "Screen Size": ['5"', '5.5"', '6"', '6.5"', '6.7"', '7"', '10"', '11"', '12"', '13"', '14"', '15"', '17"', '21"',
                    '24"', '27"', '32"'],
    "Resolution": ["HD", "Full HD", "2K", "4K", "8K", "Retina", "AMOLED", "OLED"],
    "Refresh Rate": ["60Hz", "90Hz", "120Hz", "144Hz", "165Hz", "240Hz"],

    # Electronics - Performance
    "Processor": ["Intel i3", "Intel i5", "Intel i7", "Intel i9", "AMD Ryzen 3", "AMD Ryzen 5", "AMD Ryzen 7",
                  "AMD Ryzen 9", "Apple M1", "Apple M2", "Apple M3"],
    "Graphics": ["Integrated", "NVIDIA GTX", "NVIDIA RTX", "AMD Radeon", "Intel Iris"],
    "Battery": ["3000mAh", "4000mAh", "5000mAh", "6000mAh", "7000mAh"],

    # Electronics - Connectivity
    "Network": ["2G", "3G", "4G", "4G LTE", "5G", "Wi-Fi Only"],
    "Connectivity": ["Wi-Fi", "Bluetooth", "NFC", "GPS", "USB-C", "Lightning", "Micro USB"],
    "Ports": ["HDMI", "USB 3.0", "USB-C", "Thunderbolt", "Ethernet", "Audio Jack"],

    # Electronics - Operating System
    "OS": ["Windows 10", "Windows 11", "macOS", "Linux", "Chrome OS", "Android", "iOS", "iPadOS"],

    # Power & Energy
    "Voltage": ["110V", "220V", "240V", "Dual Voltage", "Universal"],
    "Wattage": ["25W", "50W", "100W", "150W", "200W", "300W", "500W", "1000W"],
    "Energy Rating": ["A+++", "A++", "A+", "A", "B", "C", "D"],

    # Warranty & Support
    "Warranty": ["No Warranty", "1 Month", "3 Months", "6 Months", "1 Year", "2 Years", "3 Years", "Lifetime"],
    "Support": ["24/7 Support", "Business Hours", "Online Only", "No Support"],

    # Packaging & Quantity
    "Pack Size": ["1", "2", "3", "4", "5", "6", "10", "12", "24", "50", "100"],
    "Packaging": ["Retail Box", "Original Box", "Bulk Pack", "Gift Box", "Eco-Friendly"],

    # Weight & Dimensions
    "Weight": ["Light (< 1kg)", "Medium (1-5kg)", "Heavy (5-10kg)", "Extra Heavy (> 10kg)"],
    "Dimensions": ["Compact", "Standard", "Large", "Extra Large"],

    # Features & Specifications
    "Features": ["Waterproof", "Water Resistant", "Dustproof", "Shockproof", "Wireless", "Rechargeable", "Foldable",
                 "Portable"],
    "Season": ["Spring", "Summer", "Fall", "Winter", "All Season"],
    "Usage": ["Indoor", "Outdoor", "Indoor/Outdoor", "Professional", "Home Use"],

    # Brand Type
    "Brand Type": ["Original Brand", "Generic", "OEM", "Private Label"],

    # Certification
    "Certification": ["CE", "FCC", "RoHS", "ISO", "FDA Approved", "UL Listed", "Energy Star"],

    # Special Categories
    "Fragrance": ["Unscented", "Lavender", "Rose", "Vanilla", "Citrus", "Fresh", "Woody", "Floral"],
    "Flavor": ["Original", "Chocolate", "Vanilla", "Strawberry", "Mint", "Coffee", "Caramel"],
    "Ingredients": ["Organic", "Natural", "Vegan", "Gluten-Free", "Sugar-Free", "Dairy-Free"],

    # ==============================
    # 🚗 AUTOMOTIVE FEATURES
    # ==============================

    "Vehicle Brand": [
        "Toyota", "Nissan", "Honda", "Hyundai", "Kia",
        "Mercedes-Benz", "BMW", "Ford", "Chevrolet",
        "Mitsubishi", "Mazda", "Volkswagen", "Peugeot",
        "Suzuki", "Lexus", "Range Rover"
    ],

    "Vehicle Model": [
        "Corolla", "Camry", "Yaris", "Hilux",
        "X-Trail", "Navara", "Elantra", "Sonata",
        "C-Class", "E-Class", "3 Series", "5 Series",
        "RAV4", "CR-V", "Outlander"
    ],

    "Model Year": [
        "2000-2005", "2006-2010", "2011-2015",
        "2016-2020", "2021-2024"
    ],

    "Position": [
        "Front", "Rear", "Left", "Right",
        "Front Left", "Front Right",
        "Rear Left", "Rear Right"
    ],

    "Side": [
        "Driver Side", "Passenger Side", "Both Sides"
    ],

    "Engine Type": [
        "Petrol", "Diesel", "Hybrid", "Electric"
    ],

    "Engine Capacity": [
        "1.0L", "1.3L", "1.5L", "1.6L", "1.8L",
        "2.0L", "2.4L", "3.0L", "3.5L"
    ],

    "Transmission Type": [
        "Manual", "Automatic", "CVT", "Dual Clutch"
    ],

    "Brake Type": [
        "Ceramic", "Semi-Metallic", "Organic"
    ],

    "Shock Type": [
        "Gas Filled", "Oil Filled", "Hydraulic"
    ],

    "Battery Capacity": [
        "45Ah", "60Ah", "70Ah", "75Ah", "100Ah"
    ],

    "Oil Grade": [
        "5W-30", "10W-40", "15W-40", "20W-50", "ATF"
    ],

    "Tire Size": [
        "185/65R14",
        "195/65R15",
        "205/55R16",
        "215/60R16",
        "225/45R17"
    ],

    "Rim Size": [
        "14 inch", "15 inch", "16 inch", "17 inch", "18 inch"
    ],

    "Part Type": [
        "OEM", "Aftermarket", "Genuine", "Replacement"
    ],

    "Installation Type": [
        "Bolt-On", "Plug & Play", "Professional Installation Required"
    ],

    "Compatibility": [
        "Universal Fit", "Vehicle Specific"
    ],

    "Fuel Type": [
        "Petrol", "Diesel", "Electric", "Hybrid"
    ],
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

                # Parse color code if present (format: "ColorName|#HexCode")
                color_name = val
                color_code = None
                if '|' in val:
                    parts = val.split('|')
                    color_name = parts[0].strip()
                    color_code = parts[1].strip() if len(parts) > 1 else None

                if dry_run:
                    self.stdout.write(f"  [DRY-RUN] option: {feature_name} = {color_name}" +
                                      (f" (color: {color_code})" if color_code else ""))
                    continue

                # prevent duplicates per feature
                opt_obj, o_created = Option.objects.get_or_create(
                    feature=feature_obj,
                    value=color_name,
                    defaults={'color_code': color_code} if color_code else {}
                )

                # Update color_code if option already exists but didn't have one
                if not o_created and color_code and not opt_obj.color_code:
                    opt_obj.color_code = color_code
                    opt_obj.save()

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