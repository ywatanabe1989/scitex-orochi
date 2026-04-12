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


def get_workspace(request, slug=None):
    """Get workspace from middleware (subdomain) or by ``slug`` kwarg.

    The subdomain middleware sets ``request.workspace`` for hosts of the
    form ``<slug>.scitex-orochi.com``. For test clients (default
    ``testserver`` host) and the path-based ``/api/workspace/<slug>/...``
    routes in :mod:`hub.urls`, the URL kwarg ``slug`` is used as a
    fallback so the same view function works in both contexts.
    """
    workspace = getattr(request, "workspace", None)
    if workspace:
        return workspace
    if slug:
        from hub.models import Workspace

        try:
            return Workspace.objects.get(name=slug)
        except Workspace.DoesNotExist:
            raise Http404(f"Workspace {slug!r} not found")
    raise Http404("No workspace context")
