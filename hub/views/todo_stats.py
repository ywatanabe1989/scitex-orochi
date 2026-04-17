"""TODO stats endpoint for the TODO tab (scitex-orochi#171).

Returns aggregated GitHub issue stats across the canonical fleet repos
(``ywatanabe1989/todo``, ``ywatanabe1989/scitex-orochi``,
``ywatanabe1989/scitex-agent-container``, etc.) so the dashboard's TODO
tab can render burn-down + filing/closing velocity + label breakdown +
starvation list, per ywatanabe msg#13109 ("to do 消費を視覚化").

Implementation:

- Shells out to ``gh issue list --json ...`` per repo. Cached for
  CACHE_TTL_S seconds in module-level dict so the dashboard can
  auto-refresh without saturating the GitHub rate limit.
- Aggregates open vs closed counts, daily filing/closing velocity over
  a 14-day window, per-label distribution, and a starvation list of
  open-for-N-days items sorted by age descending.
- Read-only: never mutates GitHub state. Token comes from the
  ambient ``gh`` config or ``GH_TOKEN`` env, not from the request.

The endpoint is admin-gated (login_required) because the underlying
``gh`` CLI uses ywatanabe's PAT and the data could leak issue titles
that may not be public yet.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET

log = logging.getLogger("orochi.todo_stats")

# Repos to aggregate. Adding a new fleet repo = add to this list.
_REPOS = (
    "ywatanabe1989/todo",
    "ywatanabe1989/scitex-orochi",
    "ywatanabe1989/scitex-agent-container",
    "ywatanabe1989/scitex-cloud",
    "ywatanabe1989/scitex-python",
    "ywatanabe1989/scitex-io",
    "ywatanabe1989/.dotfiles",
)

CACHE_TTL_S = 60  # refresh GitHub data at most once per minute
WINDOW_DAYS = 14  # burn-down chart window
STARVATION_DAYS = 7  # threshold for "open too long" list

_cache: dict[str, object] = {"ts": 0.0, "payload": None}


def _github_token() -> str:
    """Return a GitHub API token from env (GH_TOKEN or GITHUB_TOKEN).

    Falls back to the ``gh`` CLI only if it is available — the production
    docker container does not ship ``gh``, so the HTTP path is primary.
    """
    for var in ("GH_TOKEN", "GITHUB_TOKEN"):
        tok = os.environ.get(var)
        if tok:
            return tok
    try:
        out = subprocess.check_output(
            ["gh", "auth", "token"], stderr=subprocess.DEVNULL, timeout=3
        )
        return out.decode().strip()
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ):
        return ""


def _gh_issue_list(repo: str, state: str = "all") -> list[dict]:
    """Fetch issues via the GitHub REST API.

    Returns a list of dicts with ``gh`` CLI-style keys so the aggregator
    does not need to change: ``number, title, state (OPEN/CLOSED),
    createdAt, closedAt, labels [{name}], url``.

    Paginates up to 5 pages (500 issues). Silently returns ``[]`` on
    auth/network failure so the endpoint degrades to an empty chart
    rather than 500.
    """
    token = _github_token()
    state_param = {"all": "all", "open": "open", "closed": "closed"}.get(state, "all")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "scitex-orochi-todo-stats",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    collected: list[dict] = []
    for page in range(1, 6):
        url = (
            f"https://api.github.com/repos/{repo}/issues"
            f"?state={state_param}&per_page=100&page={page}"
        )
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                batch = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            log.warning("github api %s -> HTTP %s", repo, e.code)
            break
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
            log.warning("github api %s -> %s", repo, e)
            break
        if not isinstance(batch, list) or not batch:
            break
        for item in batch:
            # Skip pull requests — /issues endpoint returns both.
            if "pull_request" in item:
                continue
            collected.append(
                {
                    "number": item.get("number"),
                    "title": item.get("title") or "",
                    "state": "OPEN" if item.get("state") == "open" else "CLOSED",
                    "createdAt": item.get("created_at"),
                    "closedAt": item.get("closed_at"),
                    "labels": [
                        {"name": lab.get("name")} for lab in (item.get("labels") or [])
                    ],
                    "assignees": [
                        {"login": a.get("login")} for a in (item.get("assignees") or [])
                    ],
                    "url": item.get("html_url"),
                }
            )
        if len(batch) < 100:
            break
    return collected


def _aggregate(repos: tuple[str, ...]) -> dict:
    """Aggregate issues across repos into the TODO stats payload."""
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=WINDOW_DAYS)
    starvation_cutoff = now - timedelta(days=STARVATION_DAYS)

    by_repo_open: dict[str, int] = {}
    by_repo_closed: dict[str, int] = {}
    daily_opened: dict[str, int] = defaultdict(int)
    daily_closed: dict[str, int] = defaultdict(int)
    label_counts: Counter[str] = Counter()
    starvation: list[dict] = []
    total_open = 0
    total_closed = 0

    for repo in repos:
        issues = _gh_issue_list(repo, state="all")
        n_open = sum(1 for i in issues if i.get("state") == "OPEN")
        n_closed = sum(1 for i in issues if i.get("state") == "CLOSED")
        by_repo_open[repo] = n_open
        by_repo_closed[repo] = n_closed
        total_open += n_open
        total_closed += n_closed

        for issue in issues:
            created = _parse_iso(issue.get("createdAt"))
            closed = _parse_iso(issue.get("closedAt"))
            state = issue.get("state")

            if created and created >= window_start:
                daily_opened[created.strftime("%Y-%m-%d")] += 1
            if closed and closed >= window_start:
                daily_closed[closed.strftime("%Y-%m-%d")] += 1

            if state == "OPEN":
                for label in issue.get("labels") or []:
                    name = label.get("name") if isinstance(label, dict) else str(label)
                    if name:
                        label_counts[name] += 1
                if created and created < starvation_cutoff:
                    age_days = int((now - created).days)
                    starvation.append(
                        {
                            "repo": repo,
                            "number": issue.get("number"),
                            "title": (issue.get("title") or "")[:160],
                            "age_days": age_days,
                            "url": issue.get("url"),
                            "labels": [
                                (l.get("name") if isinstance(l, dict) else str(l))
                                for l in (issue.get("labels") or [])
                            ],
                        }
                    )

    starvation.sort(key=lambda r: r["age_days"], reverse=True)

    daily_series = []
    for i in range(WINDOW_DAYS, -1, -1):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        daily_series.append(
            {
                "date": d,
                "opened": daily_opened.get(d, 0),
                "closed": daily_closed.get(d, 0),
            }
        )

    return {
        "ts": now.isoformat(),
        "totals": {
            "open": total_open,
            "closed": total_closed,
        },
        "by_repo": [
            {"repo": r, "open": by_repo_open[r], "closed": by_repo_closed[r]}
            for r in repos
        ],
        "daily_velocity": daily_series,
        "label_breakdown": [
            {"label": name, "open_count": count}
            for name, count in label_counts.most_common(30)
        ],
        "starvation": starvation[:50],
        "window_days": WINDOW_DAYS,
        "starvation_threshold_days": STARVATION_DAYS,
        "cache_ttl_s": CACHE_TTL_S,
    }


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


@require_GET
@login_required
def api_todo_stats(request):
    """``GET /api/todo/stats`` -- aggregated TODO stats payload.

    Cached for ``CACHE_TTL_S`` seconds. Pass ``?refresh=1`` to bypass cache.

    Response shape::

        {
          "ts": iso8601,
          "totals": {"open": int, "closed": int},
          "by_repo": [{"repo": str, "open": int, "closed": int}, ...],
          "daily_velocity": [{"date": "YYYY-MM-DD", "opened": int, "closed": int}, ...],
          "label_breakdown": [{"label": str, "open_count": int}, ...],
          "starvation": [{"repo": str, "number": int, "title": str, "age_days": int, "url": str, "labels": [str]}, ...],
          "window_days": int,
          "starvation_threshold_days": int,
          "cache_ttl_s": int
        }
    """
    refresh = request.GET.get("refresh") == "1"
    now = time.time()
    if (
        not refresh
        and _cache.get("payload")
        and (now - float(_cache.get("ts", 0))) < CACHE_TTL_S
    ):
        return JsonResponse(_cache["payload"])

    payload = _aggregate(_REPOS)
    _cache["ts"] = now
    _cache["payload"] = payload
    return JsonResponse(payload)
