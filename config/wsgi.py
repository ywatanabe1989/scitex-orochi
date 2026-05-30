"""WSGI config for Orochi."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    os.environ.get("SCITEX_OROCHI_DJANGO_SETTINGS_MODULE", "config.settings"),
)

application = get_wsgi_application()
