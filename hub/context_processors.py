"""Template context processors for workspace subdomain routing."""

from django.conf import settings


def workspace_context(request):
    return {
        "current_workspace": getattr(request, "workspace", None),
        "base_domain": settings.OROCHI_BASE_DOMAIN,
        "is_bare_domain": getattr(request, "is_bare_domain", True),
    }
