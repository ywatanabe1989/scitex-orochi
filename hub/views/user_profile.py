"""Per-user profile + avatar endpoints for logged-in humans.

Mirrors :mod:`hub.views.avatar` (which is agent-scoped) so that human
users can configure their own avatar — image, emoji, text, colour —
that is shown across every workspace they belong to.

Endpoints
---------

``GET  /api/user-profile/``         – fetch current user's profile (auto-creates empty row)
``PATCH /api/user-profile/``        – update emoji / text / colour
``POST  /api/user-profile/avatar/`` – multipart image upload
``GET  /api/workspace-members/avatars/`` – roster of human avatars in a workspace

All endpoints require an authenticated Django session (``@login_required``).
Agent avatars continue to flow through ``/api/agents/avatar/`` untouched.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import uuid
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from hub.models import UserProfile, WorkspaceMember
from hub.views._helpers import get_workspace

log = logging.getLogger("orochi.user_profile")


def _profile_payload(profile: UserProfile) -> dict:
    return {
        "icon_image": profile.icon_image,
        "icon_emoji": profile.icon_emoji,
        "icon_text": profile.icon_text,
        "color": profile.color,
    }


@csrf_exempt
@login_required
@require_http_methods(["GET", "PATCH"])
def api_user_profile(request):
    """GET / PATCH the current user's display profile.

    ``GET``  — returns ``{icon_image, icon_emoji, icon_text, color}``.
    ``PATCH`` body: any subset of ``{icon_emoji, icon_text, color}``.

    An empty profile row is created on first GET so callers never have
    to special-case "no profile yet".
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if request.method == "GET":
        return JsonResponse(_profile_payload(profile))

    # PATCH
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid json"}, status=400)

    changed = []
    if "icon_emoji" in body:
        profile.icon_emoji = (body.get("icon_emoji") or "")[:16]
        changed.append("icon_emoji")
    if "icon_text" in body:
        profile.icon_text = (body.get("icon_text") or "")[:16]
        changed.append("icon_text")
    if "color" in body:
        profile.color = (body.get("color") or "")[:16]
        changed.append("color")

    if changed:
        profile.save(update_fields=changed + ["updated_at"])

    return JsonResponse(_profile_payload(profile))


@csrf_exempt
@login_required
@require_http_methods(["POST"])
def api_user_profile_avatar(request):
    """POST /api/user-profile/avatar/ — upload avatar image for request.user.

    Storage layout mirrors the agent avatar endpoint but scoped by user
    id so two users can't clobber each other's image: files land in
    ``MEDIA_ROOT/avatars/user_<id>_<token>.<ext>`` and the resulting URL
    is written to :attr:`UserProfile.icon_image`.
    """
    uploaded = request.FILES.get("file")
    if not uploaded:
        return JsonResponse({"error": "No file uploaded"}, status=400)

    mime = uploaded.content_type or ""
    if not mime.startswith("image/"):
        return JsonResponse({"error": "Only image files allowed"}, status=400)

    data = uploaded.read()
    if len(data) > 2 * 1024 * 1024:
        return JsonResponse({"error": "Image too large (max 2 MB)"}, status=413)

    ext = Path(uploaded.name).suffix or mimetypes.guess_extension(mime) or ".png"
    prefix = f"user_{request.user.id}"
    file_id = f"{prefix}_{uuid.uuid4().hex[:8]}"

    dest_dir = Path(settings.MEDIA_ROOT) / "avatars"
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Drop any previous avatar images for this user so we don't
    # accumulate orphaned files every time they re-upload.
    for old in dest_dir.glob(f"{prefix}_*"):
        try:
            old.unlink()
        except OSError:
            pass

    dest_file = dest_dir / f"{file_id}{ext}"
    dest_file.write_bytes(data)

    media_prefix = "/" + settings.MEDIA_URL.strip("/") + "/"
    url = f"{media_prefix}avatars/{file_id}{ext}"

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    profile.icon_image = url
    profile.save(update_fields=["icon_image", "updated_at"])

    log.info("User avatar uploaded for %s: %s", request.user, url)
    return JsonResponse({"status": "ok", "url": url, **_profile_payload(profile)})


@login_required
@require_GET
def api_workspace_member_avatars(request, slug=None):
    """GET /api/workspace-members/avatars/?slug=<workspace>

    Return the list of human members in the workspace plus their avatar
    data so other browsers can render them. Agents already flow through
    ``/api/agents`` — this endpoint is humans-only.
    """
    workspace = get_workspace(request, slug=slug or request.GET.get("slug"))
    members = WorkspaceMember.objects.filter(workspace=workspace).select_related("user")

    # Prefetch all profiles in a single query.
    user_ids = [m.user_id for m in members]
    profile_by_user = {
        p.user_id: p for p in UserProfile.objects.filter(user_id__in=user_ids)
    }

    data = []
    for m in members:
        p = profile_by_user.get(m.user_id)
        data.append(
            {
                "username": m.user.username,
                "icon_image": p.icon_image if p else "",
                "icon_emoji": p.icon_emoji if p else "",
                "icon_text": p.icon_text if p else "",
                "color": p.color if p else "",
            }
        )
    return JsonResponse(data, safe=False)
