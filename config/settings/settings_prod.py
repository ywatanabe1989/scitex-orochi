"""Production settings (ADR 0002 §1).

Inherits from ``settings_shared`` and hardens the runtime for deploys.
The shared base already wires DEBUG / cookie-security off ``DJANGO_DEBUG``
and reads secrets from the environment; here we force the safe posture so
a production process can never accidentally run with DEBUG on, regardless
of how ``DJANGO_DEBUG`` is set.
"""

from .settings_shared import *  # noqa: F403

# Never run production with DEBUG on, irrespective of DJANGO_DEBUG.
DEBUG = False

# DEBUG was forced False after the shared module computed the cookie /
# storage flags, so re-derive the security-sensitive ones here.
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
