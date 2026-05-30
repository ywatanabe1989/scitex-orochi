"""URL patterns for SciTeX OAuth2 provider."""

from allauth.socialaccount.providers.oauth2.urls import default_urlpatterns

from apps.hub.providers.scitex.provider import SciTexProvider

urlpatterns = default_urlpatterns(SciTexProvider)
