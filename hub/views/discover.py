"""Discovery endpoint — resolve workspace server URLs from a token."""

import logging

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from hub.models import WorkspaceToken

log = logging.getLogger("orochi.api.discover")


@csrf_exempt
@require_GET
def api_discover(request):
    """GET /api/discover/ — resolve workspace server URLs from a token.

    Accepts the workspace token as:
      - query param: ?token=wks_...
      - Authorization header: Bearer wks_...

    Returns the WebSocket and HTTP base URLs for the workspace so that
    agents can discover the server address without hardcoding IPs.
    """
    token_str = request.GET.get("token", "")
    if not token_str:
        auth = request.META.get("HTTP_AUTHORIZATION", "")
        if auth.startswith("Bearer "):
            token_str = auth[7:].strip()

    if not token_str:
        return JsonResponse(
            {"error": "token required (query param or Authorization header)"},
            status=400,
        )

    try:
        wt = WorkspaceToken.objects.select_related("workspace").get(token=token_str)
    except WorkspaceToken.DoesNotExist:
        return JsonResponse({"error": "invalid token"}, status=401)

    ws_name = wt.workspace.name
    base = settings.OROCHI_BASE_DOMAIN
    scheme = "http" if "localhost" in base or "lvh.me" in base else "https"
    ws_scheme = "ws" if scheme == "http" else "wss"

    return JsonResponse(
        {
            "workspace": ws_name,
            "http_url": f"{scheme}://{ws_name}.{base}",
            "ws_url": f"{ws_scheme}://{ws_name}.{base}/ws/agent/",
        }
    )
