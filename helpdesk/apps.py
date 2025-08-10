from django.apps import AppConfig


class HelpdeskConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'helpdesk'
    verbose_name = "EasyMarket Helpdesk"

    def ready(self):
        from . import signals  # noqa
