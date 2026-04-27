"""CRUD endpoints for TrackedRepo — user-managed GitHub repos whose
CHANGELOG.md populates the Releases tab sub-tabs.

Lives in its own file (instead of api.py) to avoid concurrent-edit
contention with other agents working on hub/views/api.py.
"""

from __future__ import annotations

import json
import re

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Max
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


def _parse_github_url(raw):
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


def _serialize(tr):
    out = {
        "id": tr.id,
        "owner": tr.owner,
        "repo": tr.repo,
        "label": tr.display_label,
        "key": f"{tr.owner}/{tr.repo}",
        "added_by": tr.added_by.username if tr.added_by_id else None,
        "created_at": tr.created_at.isoformat() if tr.created_at else None,
    }
    # Expose ``order`` only when the column actually exists on the orochi_model —
    # migration 0023 adds it for todo#91 drag-and-drop reorder support but
    # this serializer still has to work before that migration lands.
    if hasattr(tr, "order"):
        out["order"] = tr.order
    return out


@login_required
@require_http_methods(["GET", "POST"])
def api_tracked_repos(request, slug=None):
    """GET  /api/tracked-repos/            -> list repos for current workspace
    POST /api/tracked-repos/ {url: ...}  -> add a new tracked repo.
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

    # New rows land at the bottom of the list. If the ``order`` column
    # isn't present yet (pre-0023 deployments) just omit it so the
    # INSERT uses the orochi_model default.
    defaults = {
        "label": label,
        "added_by": request.user if request.user.is_authenticated else None,
    }
    try:
        next_order = workspace.tracked_repos.aggregate(m=Max("order")).get("m")
        next_order = 0 if next_order is None else int(next_order) + 1
        defaults["order"] = next_order
    except Exception:
        # 'order' column not available — skip.
        pass

    tr, created = TrackedRepo.objects.get_or_create(
        workspace=workspace,
        owner=owner,
        repo=repo,
        defaults=defaults,
    )
    if not created and not tr.label and label:
        tr.label = label
        tr.save(update_fields=["label"])
    return JsonResponse(
        {"repo": _serialize(tr), "created": created},
        status=201 if created else 200,
    )


@login_required
@require_http_methods(["DELETE"])
def api_tracked_repo_detail(request, repo_id, slug=None):
    """DELETE /api/tracked-repos/<id>/ -> remove a tracked repo from current workspace."""
    workspace = get_workspace(request, slug=slug)
    try:
        tr = TrackedRepo.objects.get(id=repo_id, workspace=workspace)
    except TrackedRepo.DoesNotExist:
        return JsonResponse({"error": "not found"}, status=404)
    tr.delete()
    return JsonResponse({"ok": True, "id": repo_id})


@login_required
@require_http_methods(["POST"])
def api_tracked_repos_reorder(request, slug=None):
    """POST /api/tracked-repos/reorder/ {ids: [id1, id2, ...]}

    Sets each row's ``order`` to its index in ``ids``. Workspace rows not
    mentioned in ``ids`` are appended at the end in their existing order
    so the drag-and-drop UI can send only the visible list without losing
    rows. (todo#91)
    """
    workspace = get_workspace(request, slug=slug)

    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "invalid JSON body"}, status=400)

    ids_raw = body.get("ids")
    if not isinstance(ids_raw, list):
        return JsonResponse({"error": "expected body {'ids': [int, ...]}"}, status=400)

    seen = set()
    ids: list[int] = []
    for x in ids_raw:
        try:
            xi = int(x)
        except (TypeError, ValueError):
            return JsonResponse({"error": f"non-integer id in list: {x!r}"}, status=400)
        if xi in seen:
            continue
        seen.add(xi)
        ids.append(xi)

    rows = {tr.id: tr for tr in workspace.tracked_repos.all()}
    ordered_ids = [i for i in ids if i in rows]
    mentioned = set(ordered_ids)
    tail_rows = sorted(
        (tr for tr in rows.values() if tr.id not in mentioned),
        key=lambda tr: (getattr(tr, "order", 0), tr.id),
    )
    ordered_ids.extend(tr.id for tr in tail_rows)

    with transaction.atomic():
        for idx, rid in enumerate(ordered_ids):
            tr = rows[rid]
            if getattr(tr, "order", None) != idx:
                tr.order = idx
                tr.save(update_fields=["order"])

    return JsonResponse(
        {
            "ok": True,
            "repos": [_serialize(tr) for tr in workspace.tracked_repos.all()],
        }
    )
