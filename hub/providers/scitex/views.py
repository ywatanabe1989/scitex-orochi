"""SciTeX OAuth2 views — adapter and callback for django-allauth."""

import logging
import os

from allauth.exceptions import ImmediateHttpResponse
from allauth.socialaccount.providers.oauth2.views import (
    OAuth2Adapter,
    OAuth2CallbackView,
    OAuth2LoginView,
)
from django.shortcuts import render

from hub.providers.scitex.provider import SciTexProvider

logger = logging.getLogger(__name__)

_SSO_URL = os.environ.get("SCITEX_OROCHI_SSO_URL", "https://scitex.ai")

_ALLOWED_USER_TYPES = {"member"}


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
        import requests as http_requests

        resp = http_requests.get(
            self.profile_url,
            headers={"Authorization": f"Bearer {token.token}"},
            timeout=10,
        )
        resp.raise_for_status()
        extra_data = resp.json()

        user_type = extra_data.get("user_type", "unknown")
        if user_type not in _ALLOWED_USER_TYPES:
            username = extra_data.get("username", "unknown")
            logger.warning("SciTeX SSO rejected: user=%s type=%s", username, user_type)
            raise ImmediateHttpResponse(
                render(
                    request,
                    "hub/sso_rejected.html",
                    {"user_type": user_type, "username": username},
                    status=403,
                )
            )

        return self.get_provider().sociallogin_from_response(request, extra_data)


oauth2_login = OAuth2LoginView.adapter_view(SciTexOAuth2Adapter)
oauth2_callback = OAuth2CallbackView.adapter_view(SciTexOAuth2Adapter)
