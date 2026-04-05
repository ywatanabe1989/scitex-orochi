"""Custom authentication backend that falls back to scitex.ai.

When a user tries to sign in on orochi with credentials that don't match
a local account, this backend authenticates against scitex.ai's API.
If successful, it creates a local user linked to the scitex.ai account.
"""

import logging
import os

import requests
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

log = logging.getLogger("orochi.auth")
User = get_user_model()


class SciTexRemoteBackend(ModelBackend):
    """Authenticate against scitex.ai when local auth fails."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        sso_url = os.environ.get("SCITEX_OROCHI_SSO_URL", "")
        internal_url = os.environ.get("SCITEX_OROCHI_SSO_INTERNAL_URL", sso_url)
        if not internal_url:
            return None

        # Try to authenticate against scitex.ai
        try:
            resp = requests.post(
                f"{internal_url}/auth/api/login/",
                json={"username": username, "password": password},
                headers={"Host": "scitex.ai"},
                timeout=5,
            )
            if resp.status_code != 200:
                return None

            data = resp.json()
            if not data.get("success"):
                return None

            # Get user info from scitex.ai
            remote_user = data.get("user", {})
            remote_username = remote_user.get("username", username)
            remote_email = remote_user.get("email", "")

            # Create or update local user
            user, created = User.objects.get_or_create(
                username=remote_username,
                defaults={"email": remote_email},
            )
            if created:
                # Set unusable password — user authenticates via scitex.ai
                user.set_unusable_password()
                user.save()
                log.info("Created local user '%s' from scitex.ai", remote_username)

            return user

        except requests.RequestException:
            log.debug("scitex.ai auth check failed (network error)")
            return None
        except Exception:
            log.exception("Unexpected error in SciTeX remote auth")
            return None
