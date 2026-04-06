"""SciTeX OAuth2 views — adapter and callback for django-allauth."""

import os

from allauth.socialaccount.providers.oauth2.views import (
    OAuth2Adapter,
    OAuth2CallbackView,
    OAuth2LoginView,
)

from hub.providers.scitex.provider import SciTexProvider

_SSO_URL = os.environ.get("SCITEX_OROCHI_SSO_URL", "https://scitex.ai")


class SciTexOAuth2Adapter(OAuth2Adapter):
    provider_id = SciTexProvider.id

    @property
    def authorize_url(self):
        return f"{_SSO_URL}/oauth/authorize/"

    @property
    def access_token_url(self):
        return f"{_SSO_URL}/oauth/token/"

    @property
    def profile_url(self):
        return f"{_SSO_URL}/oauth/userinfo/"

    def complete_login(self, request, app, token, **kwargs):
        import requests

        resp = requests.get(
            self.profile_url,
            headers={"Authorization": f"Bearer {token.token}"},
            timeout=10,
        )
        resp.raise_for_status()
        extra_data = resp.json()
        return self.get_provider().sociallogin_from_response(request, extra_data)


oauth2_login = OAuth2LoginView.adapter_view(SciTexOAuth2Adapter)
oauth2_callback = OAuth2CallbackView.adapter_view(SciTexOAuth2Adapter)
