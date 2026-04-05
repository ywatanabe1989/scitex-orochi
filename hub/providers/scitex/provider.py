"""SciTeX OAuth2 provider for django-allauth.

Allows orochi users to sign in with their scitex.ai account.
"""

from allauth.socialaccount.providers.base import ProviderAccount
from allauth.socialaccount.providers.oauth2.provider import OAuth2Provider


class SciTexAccount(ProviderAccount):
    def get_avatar_url(self):
        return None

    def to_str(self):
        return self.account.extra_data.get("username", super().to_str())


class SciTexProvider(OAuth2Provider):
    id = "scitex"
    name = "SciTeX"
    account_class = SciTexAccount

    def get_default_scope(self):
        return ["openid", "profile", "email"]

    def extract_uid(self, data):
        return str(data.get("sub", data.get("id", "")))

    def extract_common_fields(self, data):
        return {
            "username": data.get("username", ""),
            "email": data.get("email", ""),
            "name": data.get("name", ""),
        }


provider_classes = [SciTexProvider]
