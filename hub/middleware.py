"""Workspace subdomain middleware — Slack-style routing.

Extracts workspace from Host header subdomain:
  <slug>.scitex-orochi.com → request.workspace = Workspace(name=slug)
  scitex-orochi.com        → request.workspace = None (bare domain)
"""

from django.conf import settings
from django.shortcuts import redirect

from hub.models import Workspace


class WorkspaceSubdomainMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(":")[0]
        base = settings.OROCHI_BASE_DOMAIN.split(":")[0]

        request.workspace = None
        request.is_bare_domain = False

        if host == base or host in ("localhost", "127.0.0.1", "lvh.me"):
            request.is_bare_domain = True
            request.urlconf = "hub.urls_bare"
        elif host.endswith("." + base):
            subdomain = host[: -(len(base) + 1)]
            if "." in subdomain:
                return redirect(f"https://{base}/")
            try:
                request.workspace = Workspace.objects.get(name=subdomain)
                request.urlconf = "hub.urls_workspace"
            except Workspace.DoesNotExist:
                return redirect(f"https://{base}/")
        # else: unknown host, let ALLOWED_HOSTS handle it

        return self.get_response(request)
