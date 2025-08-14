"""
URL configuration for easymarket project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('marketplace.urls')),
    path("accounts/", include("allauth.urls")),
    path('accounts/', include(('accounts.urls', 'accounts'), namespace='accounts')),
    path('orders/', include('orders.urls', namespace='orders')),
    path('reviews/', include('reviews.urls')),
    path('payments/', include('payments.urls')),
    path('chat/', include('chat.urls')),
    path('stores/', include('stores.urls')),
    path('logistics/', include('logistics.urls')),
    path('finance/', include('finance.urls')),
    path('auction/', include('auction.urls')),
    path("helpdesk/", include("helpdesk.urls", namespace="helpdesk")),
    path('', include(('orders.urls_returns', 'returns'), namespace='returns')),
    path("legal/terms/", TemplateView.as_view(template_name="legal/terms/terms.html"), name="legal_terms"),
    path("legal/privacy/", TemplateView.as_view(template_name="legal/privacy/privacy.html"), name="legal_privacy"),

]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
