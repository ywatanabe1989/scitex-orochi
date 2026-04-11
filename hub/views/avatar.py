"""Avatar upload endpoint for agent profile images."""

from __future__ import annotations

import logging
import mimetypes
import uuid
from pathlib import Path

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from hub.models import AgentProfile, WorkspaceToken
from hub.views._helpers import get_workspace

log = logging.getLogger("orochi.avatar")


@csrf_exempt
@require_http_methods(["POST"])
def api_agents_avatar(request):
    """POST /api/agents/avatar/ -- upload an avatar image for an agent.

    Accepts multipart form data with:
      - name: agent name (required)
      - file: image file (required)
      - token: workspace token (optional, for non-session auth)

    Saves the image to MEDIA_ROOT/avatars/<agent_name>_<id>.<ext> and
    updates AgentProfile.icon_image with the served URL.
    """
    # Auth: session OR workspace token
    if not (request.user and request.user.is_authenticated):
        token = request.GET.get("token") or request.POST.get("token")
        if not token:
            return JsonResponse({"error": "Authentication required"}, status=401)
        try:
            WorkspaceToken.objects.get(token=token)
        except WorkspaceToken.DoesNotExist:
            return JsonResponse({"error": "Invalid token"}, status=401)

    workspace = get_workspace(request)
    name = (request.POST.get("name") or "").strip()
    if not name:
        return JsonResponse({"error": "name required"}, status=400)

    uploaded = request.FILES.get("file")
    if not uploaded:
        return JsonResponse({"error": "No file uploaded"}, status=400)

    # Validate image type
    mime = uploaded.content_type or ""
    if not mime.startswith("image/"):
        return JsonResponse({"error": "Only image files allowed"}, status=400)

    # Size limit: 2 MB
    data = uploaded.read()
    if len(data) > 2 * 1024 * 1024:
        return JsonResponse({"error": "Image too large (max 2 MB)"}, status=413)

    ext = Path(uploaded.name).suffix or mimetypes.guess_extension(mime) or ".png"
    safe_name = name.replace("/", "_").replace("\\", "_").replace("..", "_")
    file_id = f"{safe_name}_{uuid.uuid4().hex[:8]}"

    dest_dir = Path(settings.MEDIA_ROOT) / "avatars"
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Remove old avatars for this agent (glob by safe_name prefix)
    for old in dest_dir.glob(f"{safe_name}_*"):
        try:
            old.unlink()
        except OSError:
            pass

    dest_file = dest_dir / f"{file_id}{ext}"
    dest_file.write_bytes(data)

    media_prefix = "/" + settings.MEDIA_URL.strip("/") + "/"
    url = f"{media_prefix}avatars/{file_id}{ext}"

    # Update AgentProfile
    profile, _ = AgentProfile.objects.update_or_create(
        workspace=workspace,
        name=name,
        defaults={"icon_image": url},
    )

    # Push into in-memory registry so the sidebar updates immediately
    from hub.registry import _agents, _lock

    with _lock:
        if name in _agents:
            _agents[name]["icon"] = url

    log.info("Avatar uploaded for %s: %s", name, url)
    return JsonResponse({"status": "ok", "name": name, "url": url})
