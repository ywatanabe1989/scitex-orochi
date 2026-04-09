"""Orochi URL configuration."""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve as _serve_media

# Serve media files unconditionally (not just in DEBUG). Django's static()
# helper short-circuits to [] when DEBUG=False, which is why /media/ paths
# returned 404 in production despite the file existing on disk.
# We use django.views.static.serve directly so it works in production too.
# (Internal hub — Cloudflare provides edge TLS; no external untrusted access.)
# CRITICAL: this pattern MUST be registered BEFORE the hub.urls include so the
# catchall in hub.urls does not swallow /media/ requests.
_media_url = settings.MEDIA_URL.strip("/")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    re_path(
        rf"^{_media_url}/(?P<path>.*)$",
        _serve_media,
        {"document_root": settings.MEDIA_ROOT},
    ),
    path("", include("hub.urls")),
]
