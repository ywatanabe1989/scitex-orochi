"""GitHub API proxy — avoids CORS / token exposure for private repos."""

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from django.http import JsonResponse
from django.views.decorators.http import require_GET

# In-process cache: { "owner/repo#N": (expires_epoch, title_or_None) }
# None value is a negative cache to avoid hammering GitHub for missing issues.
_ISSUE_TITLE_CACHE: dict = {}
_ISSUE_TITLE_LOCK = threading.Lock()
_ISSUE_TITLE_TTL = 3600  # 1 hour for hits
_ISSUE_TITLE_NEG_TTL = 300  # 5 minutes for misses
_REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")


def _fetch_issue_title(repo: str, number: int) -> str | None:
    token = os.environ.get("SCITEX_OROCHI_GITHUB_TOKEN") or os.environ.get(
        "GITHUB_TOKEN"
    )
    if not token:
        return None
    url = f"https://api.github.com/repos/{repo}/issues/{number}"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Orochi-Dashboard",
        "Authorization": f"token {token}",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return data.get("title")
    except Exception:
        return None


def resolve_issue_title(repo: str, number: int) -> str | None:
    """Cached lookup — safe for concurrent callers."""
    key = f"{repo}#{number}"
    now = time.time()
    with _ISSUE_TITLE_LOCK:
        entry = _ISSUE_TITLE_CACHE.get(key)
        if entry and entry[0] > now:
            return entry[1]
    title = _fetch_issue_title(repo, number)
    ttl = _ISSUE_TITLE_TTL if title else _ISSUE_TITLE_NEG_TTL
    with _ISSUE_TITLE_LOCK:
        _ISSUE_TITLE_CACHE[key] = (now + ttl, title)
    return title


@require_GET
def github_issue_title(request):
    """GET /api/github/issue-title/?repo=owner/repo&number=N

    Returns {repo, number, title} for a single issue. Used by the chat UI
    to hydrate ``owner/repo#N`` references with an inline title. Fails
    gracefully — when the repo/issue can't be resolved (no token, 404,
    network error) returns title=null so the frontend can just show the
    bare reference.
    """
    repo = (request.GET.get("repo") or "").strip()
    num_raw = (request.GET.get("number") or "").strip()
    if not repo or not _REPO_RE.match(repo):
        return JsonResponse({"error": "invalid repo"}, status=400)
    try:
        number = int(num_raw)
        if number <= 0:
            raise ValueError
    except ValueError:
        return JsonResponse({"error": "invalid number"}, status=400)
    title = resolve_issue_title(repo, number)
    return JsonResponse({"repo": repo, "number": number, "title": title})


@require_GET
def github_issues(request):
    """GET /api/github/issues — proxy to GitHub API for ywatanabe1989/todo issues."""
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

    state = request.GET.get("state", "all")
    if state not in ("open", "closed", "all"):
        state = "all"
    labels = request.GET.get("labels", "").strip()
    label_qs = f"&labels={urllib.parse.quote(labels)}" if labels else ""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Orochi-Dashboard",
        "Authorization": f"token {token}",
    }

    try:
        collected: list = []
        for page in range(1, 11):  # up to 1000 issues
            github_url = (
                "https://api.github.com/repos/ywatanabe1989/todo/issues"
                f"?state={state}&per_page=100&page={page}"
                f"&sort=updated&direction=desc{label_qs}"
            )
            req = urllib.request.Request(github_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                batch = json.loads(resp.read())
            if not isinstance(batch, list) or not batch:
                break
            collected.extend(batch)
            if len(batch) < 100:
                break
        return JsonResponse(collected, safe=False)
    except urllib.error.HTTPError as e:
        return JsonResponse(
            {
                "error": f"GitHub API returned {e.code}: {e.reason}",
                "code": "github_error",
            },
            status=502,
        )
    except Exception as e:
        import traceback

        return JsonResponse(
            {
                "error": str(e),
                "code": "proxy_error",
                "traceback": traceback.format_exc(),
            },
            status=502,
        )
