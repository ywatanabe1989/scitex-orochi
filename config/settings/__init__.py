"""Environment-dispatching settings loader (ADR 0002 §1).

``DJANGO_SETTINGS_MODULE`` points at ``config.settings`` (this package).
On import we dispatch on ``SCITEX_OROCHI_ENV`` and pull the matching
per-environment module's names into this namespace:

* ``development`` / ``dev``  → ``settings_dev``   (default)
* ``production``  / ``prod`` → ``settings_prod``
* ``staging``               → ``settings_staging`` (falls back to prod)

Every per-env module does ``from .settings_shared import *`` so the
shared base is always present; this loader just selects which one wins.
"""

import os

_env = os.environ.get("SCITEX_OROCHI_ENV", "development").strip().lower()

if _env in ("prod", "production"):
    from .settings_prod import *  # noqa: F401,F403
elif _env in ("staging", "stage"):
    try:
        from .settings_staging import *  # noqa: F401,F403
    except ImportError:
        from .settings_prod import *  # noqa: F401,F403
else:
    from .settings_dev import *  # noqa: F401,F403
