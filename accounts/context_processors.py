# accounts/context_processors.py
"""
Context processor to make currencies and countries available in all templates.
This allows you to access them in your header without passing them from every view.

Add this to your settings.py TEMPLATES context_processors:
'accounts.context_processors.currency_context',
"""

from .models import Currency, Country


def currency_context(request):
    """
    Add currency and country data to all template contexts
    """
    return {
        'currencies': Currency.objects.filter(is_active=True).order_by('code'),
        'countries': Country.objects.filter(is_active=True).select_related('currency').order_by('name'),
        'popular_currencies': Currency.objects.filter(
            code__in=['GMD', 'USD', 'EUR', 'GBP', 'CNY', 'NGN'],
            is_active=True
        ).order_by('code'),
    }


# SETTINGS.PY CONFIGURATION:
"""
Add this to your settings.py:

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',

                # Add this line:
                'accounts.context_processors.currency_context',
            ],
        },
    },
]
"""