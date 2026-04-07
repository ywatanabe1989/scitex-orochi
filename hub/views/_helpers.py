"""Shared helpers for hub views."""

from django.conf import settings
from django.http import Http404


def workspace_url(workspace_name, path="/"):
    """Build full URL for a workspace subdomain."""
    base = settings.OROCHI_BASE_DOMAIN
    scheme = "http" if "localhost" in base or "lvh.me" in base else "https"
    return f"{scheme}://{workspace_name}.{base}{path}"


def bare_url(path="/"):
    """Build full URL for the bare domain."""
    base = settings.OROCHI_BASE_DOMAIN
    scheme = "http" if "localhost" in base or "lvh.me" in base else "https"
    return f"{scheme}://{base}{path}"


def get_workspace(request):
    """Get workspace from middleware (subdomain) or raise 404."""
    workspace = getattr(request, "workspace", None)
    if not workspace:
        raise Http404("No workspace context")
    return workspace
