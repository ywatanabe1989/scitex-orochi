"""Orochi URL configuration."""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve as _serve_media

# Media routing MUST come BEFORE path("", include("hub.urls")) — that
# include() catches all unmatched paths and 404s, so any route declared
# after it never runs. django.conf.urls.static.static() is also a no-op
# when DEBUG=False, so we use django.views.static.serve directly.
# (Internal hub — Cloudflare provides edge TLS.)
_media_url = settings.MEDIA_URL.strip("/")

urlpatterns = [
    re_path(
        rf"^{_media_url}/(?P<path>.*)$",
        _serve_media,
        {"document_root": settings.MEDIA_ROOT},
    ),
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("", include("hub.urls")),
]
