"""GitHub-backed releases / repo changelog endpoints."""

from hub.views.api._common import (
    JsonResponse,
    get_workspace,
    login_required,
    os,
    require_GET,
    time,
)


@login_required
@require_GET
def api_releases(request):
    """GET /api/releases/ — recent commits sourced from the GitHub API.

    This used to shell `git log` against a container-local `.git` dir, which
    broke whenever the image didn't ship with git/.git (the normal case).
    We now proxy GitHub's commits API using the existing GITHUB_TOKEN, so
    the endpoint works on any stripped image and always reflects what
    `origin` actually has.
    """
    import json
    import os
    import urllib.error
    import urllib.request

    token = os.environ.get("SCITEX_OROCHI_GITHUB_TOKEN") or os.environ.get(
        "GITHUB_TOKEN"
    )
    if not token:
        return JsonResponse(
            {
                "error": "GitHub token not configured (set SCITEX_OROCHI_GITHUB_TOKEN)",
                "code": "missing_token",
            },
            status=503,
        )

    repo = os.environ.get("SCITEX_OROCHI_GITHUB_REPO") or os.environ.get(
        "GITHUB_REPO", "ywatanabe1989/scitex-orochi"
    )
    limit = min(int(request.GET.get("limit", "100")), 100)
    url = f"https://api.github.com/repos/{repo}/commits?per_page={limit}"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Orochi-Dashboard",
        "Authorization": f"token {token}",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return JsonResponse(
            {
                "error": f"GitHub API returned {e.code}: {e.reason}",
                "code": "github_error",
            },
            status=502,
        )
    except Exception as e:
        return JsonResponse(
            {"error": str(e), "code": "proxy_error"},
            status=502,
        )

    items = []
    for c in raw:
        commit = c.get("commit", {}) or {}
        author = commit.get("author", {}) or {}
        msg = commit.get("message", "") or ""
        subject, _, body = msg.partition("\n")
        items.append(
            {
                "sha": c.get("sha", ""),
                "short_sha": (c.get("sha") or "")[:7],
                "date": author.get("date", ""),
                "author": author.get("name", ""),
                "subject": subject,
                "body": body.strip(),
                "refs": "",
                "url": c.get("html_url", ""),
            }
        )
    return JsonResponse(items, safe=False)


_changelog_cache = {}  # key: "owner/repo" -> (expires_ts, payload_dict)
_CHANGELOG_TTL = 300  # 5 minutes
# Fallback allowlist — kept so existing deployments still work before the
# 0022_trackedrepo migration runs. Real authorization is DB-backed via
# TrackedRepo (todo#90).
_CHANGELOG_ALLOWED = {
    "ywatanabe1989/scitex-orochi",
    "ywatanabe1989/scitex-cloud",
    "ywatanabe1989/scitex-python",
    "ywatanabe1989/scitex",
    "ywatanabe1989/scitex-agent-container",
}


def _is_changelog_allowed(request, owner: str, repo: str) -> bool:
    """Allow the repo if it is either in the static fallback list or present
    in the current workspace's TrackedRepo table."""
    key = f"{owner}/{repo}"
    if key in _CHANGELOG_ALLOWED:
        return True
    try:
        from hub.models import TrackedRepo

        workspace = get_workspace(request)
        return TrackedRepo.objects.filter(
            workspace=workspace, owner=owner, repo=repo
        ).exists()
    except Exception:
        return False


@login_required
@require_GET
def api_repo_changelog(request, owner, repo):
    """GET /api/repo/<owner>/<repo>/changelog/ — fetch CHANGELOG.md from a GitHub repo.

    Returns {"content": "<markdown>", "owner": ..., "repo": ...} on success.
    Cached in-process for 5 minutes per (owner, repo) to avoid GitHub rate limits.
    Only repos registered via TrackedRepo (or in the legacy static allowlist)
    are accessible.
    """
    import base64
    import json
    import urllib.error
    import urllib.request

    key = f"{owner}/{repo}"
    if not _is_changelog_allowed(request, owner, repo):
        return JsonResponse(
            {"error": f"repo not allowed: {key}", "code": "not_allowed"},
            status=403,
        )

    now = time.time()
    cached = _changelog_cache.get(key)
    if cached and cached[0] > now:
        payload = cached[1]
        status = payload.get("_status", 200)
        return JsonResponse(
            {k: v for k, v in payload.items() if not k.startswith("_")},
            status=status,
        )

    token = os.environ.get("SCITEX_OROCHI_GITHUB_TOKEN") or os.environ.get(
        "GITHUB_TOKEN"
    )
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Orochi-Dashboard",
    }
    if token:
        headers["Authorization"] = f"token {token}"

    url = f"https://api.github.com/repos/{owner}/{repo}/contents/CHANGELOG.md"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = json.loads(resp.read())
        encoded = raw.get("content", "")
        encoding = raw.get("encoding", "base64")
        if encoding == "base64":
            content = base64.b64decode(encoded).decode("utf-8", errors="replace")
        else:
            content = encoded
        payload = {
            "owner": owner,
            "repo": repo,
            "content": content,
            "html_url": raw.get("html_url", ""),
            "_status": 200,
        }
        _changelog_cache[key] = (now + _CHANGELOG_TTL, payload)
        return JsonResponse({k: v for k, v in payload.items() if not k.startswith("_")})
    except urllib.error.HTTPError as e:
        status = 404 if e.code == 404 else 502
        err = {
            "error": f"GitHub API returned {e.code}: {e.reason}",
            "code": "github_error",
            "owner": owner,
            "repo": repo,
            "_status": status,
        }
        _changelog_cache[key] = (now + _CHANGELOG_TTL, err)
        return JsonResponse(
            {k: v for k, v in err.items() if not k.startswith("_")},
            status=status,
        )
    except Exception as e:
        return JsonResponse(
            {"error": str(e), "code": "proxy_error", "owner": owner, "repo": repo},
            status=502,
        )
