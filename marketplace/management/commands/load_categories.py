from django.core.management.base import BaseCommand
from django.db import transaction
from django.apps import apps


DEFAULT_CATEGORIES = [
    {
        "name": "Electronics",
        "icon": "fa-solid fa-bolt",
        "children": [
            {"name": "Phones & Tablets", "children": [
                {"name": "Smartphones"},
                {"name": "Feature Phones"},
                {"name": "Tablets"},
                {"name": "Smartwatches"},
                {"name": "Accessories", "children": [
                    {"name": "Cases & Covers"},
                    {"name": "Chargers & Cables"},
                    {"name": "Power Banks"},
                    {"name": "Screen Protectors"},
                    {"name": "Earphones & Headsets"},
                ]},
            ]},
            {"name": "Computers", "children": [
                {"name": "Laptops"},
                {"name": "Desktops"},
                {"name": "Monitors"},
                {"name": "Computer Accessories", "children": [
                    {"name": "Keyboards & Mice"},
                    {"name": "Storage (HDD/SSD)"},
                    {"name": "Printers & Scanners"},
                    {"name": "Networking", "children": [
                        {"name": "Routers"},
                        {"name": "Modems"},
                        {"name": "Switches"},
                        {"name": "Cables"},
                    ]},
                ]},
            ]},
            {"name": "TV & Audio", "children": [
                {"name": "Televisions"},
                {"name": "Speakers"},
                {"name": "Home Theatre"},
                {"name": "Soundbars"},
            ]},
            {"name": "Cameras", "children": [
                {"name": "DSLR & Mirrorless"},
                {"name": "Action Cameras"},
                {"name": "Security Cameras"},
            ]},
            {"name": "Gaming", "children": [
                {"name": "Consoles"},
                {"name": "Controllers"},
                {"name": "Games"},
                {"name": "VR"},
            ]},
        ],
    },
    {
        "name": "Fashion",
        "icon": "fa-solid fa-shirt",
        "children": [
            {"name": "Men", "children": [
                {"name": "Clothing", "children": [
                    {"name": "T-Shirts"},
                    {"name": "Shirts"},
                    {"name": "Jeans"},
                    {"name": "Trousers"},
                    {"name": "Traditional Wear"},
                    {"name": "Jackets & Coats"},
                ]},
                {"name": "Shoes", "children": [
                    {"name": "Sneakers"},
                    {"name": "Loafers"},
                    {"name": "Sandals"},
                    {"name": "Boots"},
                ]},
                {"name": "Watches"},
                {"name": "Bags & Belts"},
            ]},
            {"name": "Women", "children": [
                {"name": "Clothing", "children": [
                    {"name": "Dresses"},
                    {"name": "Tops"},
                    {"name": "Skirts"},
                    {"name": "Jeans"},
                    {"name": "Traditional Wear"},
                    {"name": "Jackets & Coats"},
                ]},
                {"name": "Shoes", "children": [
                    {"name": "Heels"},
                    {"name": "Flats"},
                    {"name": "Sneakers"},
                    {"name": "Sandals"},
                ]},
                {"name": "Handbags"},
                {"name": "Jewelry"},
            ]},
            {"name": "Kids & Baby", "children": [
                {"name": "Boys"},
                {"name": "Girls"},
                {"name": "Baby Clothing"},
                {"name": "Baby Shoes"},
            ]},
        ],
    },
    {
        "name": "Home & Kitchen",
        "icon": "fa-solid fa-house",
        "children": [
            {"name": "Furniture", "children": [
                {"name": "Living Room"},
                {"name": "Bedroom"},
                {"name": "Office Furniture"},
            ]},
            {"name": "Home Decor", "children": [
                {"name": "Wall Art"},
                {"name": "Rugs & Carpets"},
                {"name": "Curtains"},
                {"name": "Lighting"},
            ]},
            {"name": "Kitchen & Dining", "children": [
                {"name": "Cookware"},
                {"name": "Dinnerware"},
                {"name": "Kitchen Tools"},
            ]},
            {"name": "Home Appliances", "children": [
                {"name": "Refrigerators"},
                {"name": "Microwaves"},
                {"name": "Washers & Dryers"},
                {"name": "Fans & AC"},
            ]},
        ],
    },
    {
        "name": "Beauty & Personal Care",
        "icon": "fa-solid fa-spray-can-sparkles",
        "children": [
            {"name": "Makeup"},
            {"name": "Skincare"},
            {"name": "Hair Care"},
            {"name": "Fragrances"},
            {"name": "Men's Grooming"},
        ],
    },
    {
        "name": "Groceries",
        "icon": "fa-solid fa-basket-shopping",
        "children": [
            {"name": "Beverages"},
            {"name": "Snacks"},
            {"name": "Rice, Pasta & Grains"},
            {"name": "Cooking Essentials"},
            {"name": "Canned & Packaged Foods"},
        ],
    },
    {
        "name": "Sports & Outdoors",
        "icon": "fa-solid fa-dumbbell",
        "children": [
            {"name": "Fitness"},
            {"name": "Outdoor Recreation"},
            {"name": "Sportswear"},
            {"name": "Sports Equipment"},
        ],
    },
    {
        "name": "Automotive",
        "icon": "fa-solid fa-car",
        "children": [
            {"name": "Car Accessories"},
            {"name": "Motorbike Accessories"},
            {"name": "Oils & Fluids"},
            {"name": "Car Electronics"},
        ],
    },
    {
        "name": "Health",
        "icon": "fa-solid fa-heart-pulse",
        "children": [
            {"name": "Medical Supplies"},
            {"name": "Vitamins & Supplements"},
            {"name": "Wellness"},
        ],
    },
    {
        "name": "Books & Stationery",
        "icon": "fa-solid fa-book",
        "children": [
            {"name": "Books"},
            {"name": "Office Supplies"},
            {"name": "School Supplies"},
        ],
    },
]


class Command(BaseCommand):
    help = "Load default ecommerce categories/subcategories into Category model (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--app",
            default="marketplace",
            help="Django app label that contains the Category model (default: marketplace).",
        )
        parser.add_argument(
            "--model",
            default="Category",
            help="Model name for Category (default: Category).",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete all existing categories before loading.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be created/updated without writing to DB.",
        )

    def handle(self, *args, **options):
        app_label = options["app"]
        model_name = options["model"]
        clear = options["clear"]
        dry_run = options["dry_run"]

        Category = apps.get_model(app_label, model_name)

        def upsert_category(data, parent=None):
            """
            Create/update category uniquely by (name, parent).
            This keeps it safe even if same name exists under different parents.
            """
            name = data["name"].strip()
            defaults = {
                "icon": data.get("icon", "") or "",
                "description": data.get("description", "") or "",
                "is_active": data.get("is_active", True),
                "parent": parent,
            }

            if dry_run:
                self.stdout.write(f"[DRY-RUN] upsert: {name} (parent={parent.name if parent else 'ROOT'})")
                category = None
            else:
                category, created = Category.objects.update_or_create(
                    name=name,
                    parent=parent,
                    defaults=defaults,
                )
                self.stdout.write(
                    self.style.SUCCESS(f"{'CREATED' if created else 'UPDATED'}: {category.get_full_name()}")
                    if hasattr(category, "get_full_name")
                    else self.style.SUCCESS(f"{'CREATED' if created else 'UPDATED'}: {category.name}")
                )

            # handle children
            for child in data.get("children", []) or []:
                upsert_category(child, parent=category if not dry_run else None)

        with transaction.atomic():
            if clear:
                if dry_run:
                    self.stdout.write("[DRY-RUN] would delete all categories")
                else:
                    deleted_count, _ = Category.objects.all().delete()
                    self.stdout.write(self.style.WARNING(f"Deleted {deleted_count} categories."))

            for root in DEFAULT_CATEGORIES:
                upsert_category(root, parent=None)

            if dry_run:
                self.stdout.write(self.style.WARNING("Dry-run finished (no DB changes)."))
            else:
                self.stdout.write(self.style.SUCCESS("Categories loaded successfully."))
