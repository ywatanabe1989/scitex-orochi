"""Django settings for Orochi — standalone agent communication hub."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from importlib.metadata import version as _pkg_version

    OROCHI_VERSION = _pkg_version("scitex-orochi")
except Exception:
    OROCHI_VERSION = "0.6.2"

# Deployment build ID — set at container start or read from env.
# Used by the dashboard to show a "new/updated" badge and verify deploys.
OROCHI_BUILD_ID = os.environ.get("OROCHI_BUILD_ID", "")
OROCHI_DEPLOYED_AT = os.environ.get("OROCHI_DEPLOYED_AT", "")
if not OROCHI_DEPLOYED_AT:
    # Fall back to process start time (ISO-8601 UTC)
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    OROCHI_DEPLOYED_AT = _dt.now(_tz.utc).isoformat()

# If no explicit build ID, derive one from the deploy timestamp so it
# changes every restart. This guarantees the dashboard version string
# visibly updates even when the package version is unchanged.
if not OROCHI_BUILD_ID:
    try:
        from datetime import datetime as _dt2

        OROCHI_BUILD_ID = _dt2.fromisoformat(
            OROCHI_DEPLOYED_AT.replace("Z", "+00:00")
        ).strftime("%Y%m%d.%H%M")
    except Exception:
        OROCHI_BUILD_ID = ""

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-change-me-in-production",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() in ("true", "1", "yes")

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if o.strip()
]

# Subdomain workspace routing (Slack-style)
OROCHI_BASE_DOMAIN = os.environ.get("OROCHI_BASE_DOMAIN", "lvh.me:8000")
OROCHI_RESERVED_SUBDOMAINS = {
    "www",
    "api",
    "admin",
    "mail",
    "smtp",
    "ftp",
    "static",
    "media",
    "app",
    "status",
}

SESSION_COOKIE_DOMAIN = os.environ.get("SESSION_COOKIE_DOMAIN", None) or None
CSRF_COOKIE_DOMAIN = os.environ.get("CSRF_COOKIE_DOMAIN", None) or None
SESSION_COOKIE_SECURE = not DEBUG  # HTTPS via Cloudflare — required for WS auth
CSRF_COOKIE_SECURE = not DEBUG

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "channels",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "allauth.socialaccount.providers.orcid",
    "hub.providers.scitex",
    "hub",
]

SITE_ID = 1

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "hub.middleware.WorkspaceSubdomainMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "hub.backends.SciTexRemoteBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

ROOT_URLCONF = "orochi.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "hub.context_processors.workspace_context",
            ],
        },
    },
]

WSGI_APPLICATION = "orochi.wsgi.application"
ASGI_APPLICATION = "orochi.asgi.application"

# Channel layers — in-memory for dev, Redis for production
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    },
}

# Database — SQLite for simplicity, PostgreSQL for production
_db_path = os.environ.get("SCITEX_OROCHI_DB_PATH", str(BASE_DIR / "db.sqlite3"))
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": _db_path,
    },
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
if not DEBUG:
    STORAGES = {
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }

MEDIA_URL = "media/"
MEDIA_ROOT = os.environ.get("SCITEX_OROCHI_MEDIA_ROOT", str(BASE_DIR / "media"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Proxy settings — Cloudflare terminates SSL, Daphne sees HTTP
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

LOGIN_URL = "/signin/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/signin/"

# Optional SSO — set SCITEX_OROCHI_SSO_URL to enable "Sign in with SciTeX" button
# e.g. SCITEX_OROCHI_SSO_URL=https://scitex.ai
SCITEX_OROCHI_SSO_URL = os.environ.get("SCITEX_OROCHI_SSO_URL", "")

# --- django-allauth (Google, ORCID) ---
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True
ACCOUNT_EMAIL_VERIFICATION = "none"  # No SMTP configured yet
ACCOUNT_LOGIN_METHODS = {"email", "username"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "username*", "password1*", "password2*"]
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
SOCIALACCOUNT_EMAIL_VERIFICATION = "none"

# Use console email backend until SMTP is configured
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Social providers — configure via Django admin or env vars
# Google: set client ID/secret in Django admin > Social applications
# ORCID: set client ID/secret in Django admin > Social applications
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
        "APP": {
            "client_id": os.environ.get("SCITEX_OROCHI_GOOGLE_CLIENT_ID", ""),
            "secret": os.environ.get("SCITEX_OROCHI_GOOGLE_SECRET", ""),
        },
    },
    "orcid": {
        "BASE_DOMAIN": "orcid.org",
        "MEMBER_API": False,
        "APP": {
            "client_id": os.environ.get("SCITEX_OROCHI_ORCID_CLIENT_ID", ""),
            "secret": os.environ.get("SCITEX_OROCHI_ORCID_SECRET", ""),
        },
    },
    "scitex": {
        "APP": {
            "client_id": os.environ.get("SCITEX_OROCHI_SCITEX_CLIENT_ID", ""),
            "secret": os.environ.get("SCITEX_OROCHI_SCITEX_SECRET", ""),
            "settings": {
                "server_url": os.environ.get(
                    "SCITEX_OROCHI_SSO_URL", "https://scitex.ai"
                ),
            },
        },
    },
}
