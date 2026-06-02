"""Development settings (ADR 0002 §1).

Inherits everything from ``settings_shared`` and keeps the
development-friendly defaults (DEBUG on unless overridden via env). The
shared module already derives DEBUG / cookie-security from
``DJANGO_DEBUG``, so this module is intentionally thin — it exists so the
env-loader has a concrete ``development`` target and so dev-only
overrides have an obvious home.
"""

from .settings_shared import *  # noqa: F401,F403
