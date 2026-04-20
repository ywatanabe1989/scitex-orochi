"""Workspace icon image upload endpoint.

Parallel to :mod:`hub.views.avatar` (agent avatars) and
:mod:`hub.views.user_profile` (human avatars). Accepts a multipart image
file and persists the served URL on :attr:`Workspace.icon_image`.

The render cascade on the frontend is
``icon_image`` > ``icon`` (emoji) > first-letter coloured square.
"""

from __future__ import annotations

import logging
import mimetypes
import uuid
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from hub.views._helpers import get_workspace

log = logging.getLogger("orochi.workspace_icon")

_MAX_BYTES = 2 * 1024 * 1024


def _media_url_for(relative: str) -> str:
    """Build a public URL under ``MEDIA_URL`` for a stored file."""
    prefix = "/" + settings.MEDIA_URL.strip("/") + "/"
    return f"{prefix}{relative}"


def _safe_prefix(name: str) -> str:
    """Sanitise the workspace slug for use in a filename prefix."""
    return (name or "workspace").replace("/", "_").replace("\\", "_").replace("..", "_")


def _delete_existing(dest_dir: Path, prefix: str) -> None:
    """Remove any previously-uploaded icon images for this workspace."""
    if not dest_dir.exists():
        return
    for old in dest_dir.glob(f"{prefix}_*"):
        try:
            old.unlink()
        except OSError:
            pass


@csrf_exempt
@login_required
@require_http_methods(["POST", "DELETE"])
def api_workspace_icon(request):
    """POST / DELETE ``/api/workspace/icon/`` — workspace icon image.

    ``POST`` accepts ``multipart/form-data`` with a ``file`` field. On
    success, writes the image to
    ``MEDIA_ROOT/workspace-icons/<slug>_<uuid>.<ext>`` and stores the
    served URL on :attr:`Workspace.icon_image`. Any previous image for
    the same workspace is deleted first so we don't accumulate orphans.

    ``DELETE`` (or ``POST`` with ``?clear=1``) removes the image: the
    file(s) on disk are unlinked and ``Workspace.icon_image`` is cleared.
    The emoji field ``Workspace.icon`` is left untouched so the cascade
    falls back to the emoji (if any) or the first-letter square.

    Response: ``{"status": "ok", "url": "<media-url>"}`` on success.
    Errors are ``{"error": "..."}`` with 4xx status codes.
    """
    workspace = get_workspace(request)
    prefix = _safe_prefix(workspace.name)
    dest_dir = Path(settings.MEDIA_ROOT) / "workspace-icons"

    # Clear path: explicit DELETE or POST with ?clear=1 / form clear=1.
    wants_clear = request.method == "DELETE" or (
        request.GET.get("clear") == "1" or request.POST.get("clear") == "1"
    )
    if wants_clear:
        _delete_existing(dest_dir, prefix)
        workspace.icon_image = ""
        workspace.save(update_fields=["icon_image"])
        log.info("Workspace icon cleared: %s", workspace.name)
        return JsonResponse({"status": "ok", "url": ""})

    uploaded = request.FILES.get("file")
    if not uploaded:
        return JsonResponse({"error": "No file uploaded"}, status=400)

    mime = uploaded.content_type or ""
    if not mime.startswith("image/"):
        return JsonResponse({"error": "Only image files allowed"}, status=400)

    data = uploaded.read()
    if len(data) > _MAX_BYTES:
        return JsonResponse({"error": "Image too large (max 2 MB)"}, status=413)

    ext = Path(uploaded.name).suffix or mimetypes.guess_extension(mime) or ".png"
    file_id = f"{prefix}_{uuid.uuid4().hex[:8]}"

    dest_dir.mkdir(parents=True, exist_ok=True)
    _delete_existing(dest_dir, prefix)

    dest_file = dest_dir / f"{file_id}{ext}"
    dest_file.write_bytes(data)

    url = _media_url_for(f"workspace-icons/{file_id}{ext}")
    workspace.icon_image = url
    workspace.save(update_fields=["icon_image"])

    log.info("Workspace icon uploaded for %s: %s", workspace.name, url)
    return JsonResponse({"status": "ok", "url": url})
