import os
from celery import Celery

# Set default Django settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "easymarket.settings")

app = Celery("easymarket")

# Load config from Django settings, using CELERY_ prefix
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks.py in all INSTALLED_APPS
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
