"""SciTeX OAuth2 views — adapter and callback for django-allauth."""

from allauth.socialaccount.adapter import get_adapter
from allauth.socialaccount.providers.oauth2.views import (
    OAuth2Adapter,
    OAuth2CallbackView,
    OAuth2LoginView,
)

from hub.providers.scitex.provider import SciTexProvider


class SciTexOAuth2Adapter(OAuth2Adapter):
    provider_id = SciTexProvider.id

    @property
    def _base_url(self):
        settings = get_adapter().get_provider(None, SciTexProvider.id).app.settings
        return settings.get("server_url", "https://scitex.ai")

    @property
    def authorize_url(self):
        return f"{self._base_url}/oauth/authorize/"

    @property
    def access_token_url(self):
        return f"{self._base_url}/oauth/token/"

    @property
    def profile_url(self):
        return f"{self._base_url}/oauth/userinfo/"

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
