"""CRUD endpoints for TrackedRepo — user-managed GitHub repos whose
CHANGELOG.md populates the Releases tab sub-tabs.

Lives in its own file (instead of api.py) to avoid concurrent-edit
contention with other agents working on hub/views/api.py.
"""

from __future__ import annotations

import json
import re

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from hub.models import TrackedRepo
from hub.views._helpers import get_workspace

# Accept either full URL forms or bare "owner/repo" input.
_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)
_SLUG_RE = re.compile(r"^([\w.-]+)/([\w.-]+)$")


def _parse_github_url(raw: str) -> tuple[str, str] | None:
    """Extract ``(owner, repo)`` from a GitHub URL or ``owner/repo`` slug.

    Trailing ``.git`` and a trailing slash are both stripped. Returns
    ``None`` when the input is unrecognisable so the caller can emit a
    400 with a helpful message.
    """
    s = (raw or "").strip()
    if not s:
        return None
    m = _URL_RE.match(s)
    if m:
        return m.group(1), m.group(2)
    m = _SLUG_RE.match(s)
    if m:
        return m.group(1), m.group(2)
    return None


def _serialize(tr: TrackedRepo) -> dict:
    return {
        "id": tr.id,
        "owner": tr.owner,
        "repo": tr.repo,
        "label": tr.display_label,
        "key": f"{tr.owner}/{tr.repo}",
        "added_by": tr.added_by.username if tr.added_by_id else None,
        "created_at": tr.created_at.isoformat() if tr.created_at else None,
    }


@login_required
@require_http_methods(["GET", "POST"])
def api_tracked_repos(request, slug=None):
    """GET  /api/tracked-repos/            → list repos for current workspace
    POST /api/tracked-repos/ {url: ...}  → add a new tracked repo.
    """
    workspace = get_workspace(request, slug=slug)

    if request.method == "GET":
        items = [_serialize(tr) for tr in workspace.tracked_repos.all()]
        return JsonResponse({"repos": items})

    # POST
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "invalid JSON body"}, status=400)

    raw = body.get("url") or body.get("repo") or ""
    parsed = _parse_github_url(raw)
    if not parsed:
        return JsonResponse(
            {
                "error": (
                    "Unrecognised GitHub URL. Expected "
                    "'https://github.com/owner/repo' or 'owner/repo'."
                ),
            },
            status=400,
        )
    owner, repo = parsed
    label = (body.get("label") or "").strip() or repo

    tr, created = TrackedRepo.objects.get_or_create(
        workspace=workspace,
        owner=owner,
        repo=repo,
        defaults={
            "label": label,
            "added_by": request.user if request.user.is_authenticated else None,
        },
    )
    if not created and not tr.label and label:
        tr.label = label
        tr.save(update_fields=["label"])
    return JsonResponse(
        {"repo": _serialize(tr), "created": created}, status=201 if created else 200
    )


@login_required
@require_http_methods(["DELETE"])
def api_tracked_repo_detail(request, repo_id, slug=None):
    """DELETE /api/tracked-repos/<id>/ → remove a tracked repo from current workspace."""
    workspace = get_workspace(request, slug=slug)
    try:
        tr = TrackedRepo.objects.get(id=repo_id, workspace=workspace)
    except TrackedRepo.DoesNotExist:
        return JsonResponse({"error": "not found"}, status=404)
    tr.delete()
    return JsonResponse({"ok": True, "id": repo_id})
