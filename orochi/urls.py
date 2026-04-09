"""Orochi URL configuration."""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve as _serve_media

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("", include("hub.urls")),
]

# Serve media files unconditionally (not just in DEBUG). Django's static()
# helper short-circuits to [] when DEBUG=False, which is why /media/ paths
# returned 404 in production despite the file existing on disk.
# We use django.views.static.serve directly so it works in production too.
# (Internal hub — Cloudflare provides edge TLS; no external untrusted access.)
_media_url = settings.MEDIA_URL.strip("/")
urlpatterns += [
    re_path(
        rf"^{_media_url}/(?P<path>.*)$",
        _serve_media,
        {"document_root": settings.MEDIA_ROOT},
    ),
]
