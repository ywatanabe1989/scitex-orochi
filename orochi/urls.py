"""Orochi URL configuration."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("", include("hub.urls")),
]

# Serve media files (always — no external web server in Docker)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
