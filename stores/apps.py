from django.apps import AppConfig


class StoresConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'stores'
    verbose_name = 'Store Management'

    def ready(self):
        """
        Import signal handlers when the app is ready.

        This ensures that:
        1. Warehouses are created automatically when stores are created
        2. Stock entries are created automatically when products are added
        3. Price changes are tracked for notifications
        """
        import stores.signals  # noqa

