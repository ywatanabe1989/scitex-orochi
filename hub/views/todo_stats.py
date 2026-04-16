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


def _gh_issue_list(repo: str, state: str = "all") -> list[dict]:
    """Shell out to ``gh issue list`` for one repo. Returns a list of issue dicts."""
    cmd = [
        "gh", "issue", "list",
        "--repo", repo,
        "--state", state,
        "--limit", "500",
        "--json", "number,title,state,createdAt,closedAt,labels,assignees,url",
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.PIPE, timeout=30)
        return json.loads(out.decode())
    except subprocess.CalledProcessError as e:
        log.warning("gh issue list failed for %s: %s", repo, e.stderr.decode()[:200])
        return []
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        log.warning("gh issue list parse failed for %s: %s", repo, e)
        return []


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
                    starvation.append({
                        "repo": repo,
                        "number": issue.get("number"),
                        "title": (issue.get("title") or "")[:160],
                        "age_days": age_days,
                        "url": issue.get("url"),
                        "labels": [
                            (l.get("name") if isinstance(l, dict) else str(l))
                            for l in (issue.get("labels") or [])
                        ],
                    })

    starvation.sort(key=lambda r: r["age_days"], reverse=True)

    daily_series = []
    for i in range(WINDOW_DAYS, -1, -1):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        daily_series.append({
            "date": d,
            "opened": daily_opened.get(d, 0),
            "closed": daily_closed.get(d, 0),
        })

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
