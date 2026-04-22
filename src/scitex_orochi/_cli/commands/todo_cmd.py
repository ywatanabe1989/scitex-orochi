"""``scitex-orochi todo {list,next,triage}`` subcommands.

Operator-facing wrappers around the ``gh issue list --repo
ywatanabe1989/todo`` fleet workflow that the server-side auto-dispatch
and the client-side probe share. Mirrors ``scripts/client/
auto-dispatch-pick-todo.py`` (PR #320) but exposes three verbs:

``list``   — JSON list of open high-priority todos (optionally lane-filtered).
``next``   — Single recommendation for the given lane; null if nothing
             matches (the classic "pick one" path; same logic as
             auto-dispatch-pick-todo.py).
``triage`` — Classifier: score every open todo on staleness, lane fit,
             claimed-by-PR, and assignee presence. ``--json`` honoured.

Data source: ``gh issue list`` + ``gh pr list`` against
``ywatanabe1989/todo``. The ``pick`` core logic is re-imported from
``scripts/client/auto-dispatch-pick-todo.py`` so any behavioural fix
there propagates here without duplication.

Per ywatanabe msg#16477: fill the operator UX gap so that a head
doesn't need to hand-roll ``gh issue list --label high-priority --label
infrastructure`` to see the same list auto-dispatch sees.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Any

import click

from ._host_ops import _repo_root_candidate

TODO_REPO_DEFAULT = os.environ.get("SCITEX_TODO_REPO", "ywatanabe1989/todo")


# ---------------------------------------------------------------------------
# Pick-helper import (reuse the pure-function core from PR #320)
# ---------------------------------------------------------------------------

def _import_pick_helper() -> Any:
    """Load ``auto-dispatch-pick-todo.py`` as a module and return it.

    Falls back to prepending ``scripts/client`` to sys.path — consistent
    with how ``machine_cmd._import_agent_meta_pkg`` bootstraps.

    The file is hyphenated (not a valid module name) so we load it via
    ``importlib.util.spec_from_file_location`` keyed to the underscored
    stem. Result is cached in module globals to avoid the exec cost on
    every CLI invocation.
    """
    global _PICK_MOD_CACHE
    cached = globals().get("_PICK_MOD_CACHE")
    if cached is not None:
        return cached
    import importlib.util

    helper = _repo_root_candidate() / "scripts" / "client" / "auto-dispatch-pick-todo.py"
    if not helper.is_file():
        raise click.ClickException(
            f"pick-helper not found at {helper} — set SCITEX_OROCHI_REPO_ROOT "
            "or run from a scitex-orochi checkout."
        )
    spec = importlib.util.spec_from_file_location(
        "auto_dispatch_pick_todo", helper
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise click.ClickException(f"could not load helper spec from {helper}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    globals()["_PICK_MOD_CACHE"] = mod
    return mod


# ---------------------------------------------------------------------------
# gh shell-out (shared between list/next/triage)
# ---------------------------------------------------------------------------

def _gh_json(args: list[str], timeout: int = 20) -> list[dict]:
    """Run ``gh <args>`` and parse stdout as JSON array.

    Returns ``[]`` on any failure (missing gh, non-zero exit, bad JSON)
    — the command should degrade gracefully for operators without gh
    auth (they'll just see an empty result).
    """
    try:
        proc = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if proc.returncode != 0:
        return []
    try:
        data = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _fetch_open_todos(repo: str, limit: int = 100) -> list[dict]:
    """All open high-priority todos in the repo, flattened to dicts."""
    return _gh_json(
        [
            "issue", "list",
            "--repo", repo,
            "--state", "open",
            "--label", "high-priority",
            "--json", "number,title,labels,assignees,updatedAt,createdAt",
            "--limit", str(limit),
        ]
    )


def _fetch_open_prs(repo: str, limit: int = 100) -> list[dict]:
    """All open PRs in the repo — title + body only (used for claim filter)."""
    return _gh_json(
        [
            "pr", "list",
            "--repo", repo,
            "--state", "open",
            "--json", "title,body",
            "--limit", str(limit),
        ]
    )


# ---------------------------------------------------------------------------
# Scoring (for `triage`)
# ---------------------------------------------------------------------------

def _staleness_score(updated_at: str | None, now_iso: float) -> float:
    """0.0 (just updated) .. 1.0 (untouched > 30 days). Best-effort."""
    if not updated_at:
        return 0.0
    try:
        # gh emits RFC3339 strings. Fall back to a naïve parse.
        from datetime import datetime

        ts = datetime.fromisoformat(updated_at.rstrip("Z")).timestamp()
    except (ValueError, TypeError):
        return 0.0
    delta_days = max(0.0, (now_iso - ts) / 86400.0)
    return min(1.0, delta_days / 30.0)


def _score_issue(
    issue: dict,
    lane: str | None,
    claimed: set[int],
    now_ts: float,
) -> dict:
    """Return the issue dict augmented with a ``score`` + ``score_reason`` field.

    Score components (all in [0,1], summed):
      * staleness (up to +1.0)
      * lane fit (+1.0 if label present when lane given; 0 otherwise — or
        not penalised if ``lane`` is ``None``)
      * unclaimed (+0.5 if no PR refers to it)
      * unassigned (+0.5 if no human assignee)

    Higher score = better pick. Operator can re-rank by any column of
    the JSON output.
    """
    labels = {
        (lab.get("name") or "").strip() for lab in (issue.get("labels") or [])
    }
    assignees = issue.get("assignees") or []
    num = int(issue.get("number") or 0)
    staleness = _staleness_score(issue.get("updatedAt"), now_ts)
    lane_fit = 0.0
    if lane is None:
        lane_fit = 0.0  # neutral when no lane filter
    elif lane in labels:
        lane_fit = 1.0
    unclaimed = 0.5 if num not in claimed else 0.0
    unassigned = 0.5 if not assignees else 0.0
    score = round(staleness + lane_fit + unclaimed + unassigned, 3)
    reason_parts = []
    if lane is not None:
        reason_parts.append(f"lane={'fit' if lane_fit else 'miss'}")
    reason_parts.append(f"stale={staleness:.2f}")
    if num in claimed:
        reason_parts.append("claimed")
    if assignees:
        reason_parts.append("assigned")
    return {
        "number": num,
        "title": issue.get("title") or "",
        "labels": sorted(labels),
        "assignees": [a.get("login") or "" for a in assignees],
        "updated_at": issue.get("updatedAt"),
        "claimed_by_pr": num in claimed,
        "score": score,
        "score_reason": ";".join(reason_parts),
    }


# ---------------------------------------------------------------------------
# Click group
# ---------------------------------------------------------------------------

@click.group("todo")
def todo() -> None:
    """Fleet todo queue — list, pick, triage."""


# ---------------------------------------------------------------------------
# todo list
# ---------------------------------------------------------------------------

@todo.command("list")
@click.option(
    "--lane",
    default=None,
    help="Label name to filter on (e.g. infrastructure, hub-admin). "
    "Omit to see every open high-priority todo.",
)
@click.option(
    "--repo",
    default=TODO_REPO_DEFAULT,
    show_default=True,
    help="Todo repo [$SCITEX_TODO_REPO].",
)
@click.option(
    "--limit",
    type=int,
    default=100,
    show_default=True,
    help="Max issues to fetch.",
)
@click.pass_context
def todo_list(
    ctx: click.Context,
    lane: str | None,
    repo: str,
    limit: int,
) -> None:
    """List open high-priority todos (optionally lane-filtered)."""
    issues = _fetch_open_todos(repo, limit=limit)
    if lane is not None:
        issues = [
            i
            for i in issues
            if lane in {(lab.get("name") or "").strip() for lab in (i.get("labels") or [])}
        ]
    as_json = bool(ctx.obj and ctx.obj.get("json"))
    # Default output is JSON array of the essentials.
    slim = [
        {
            "number": int(i.get("number") or 0),
            "title": i.get("title") or "",
            "labels": sorted(
                (lab.get("name") or "") for lab in (i.get("labels") or [])
            ),
            "assignees": [a.get("login") or "" for a in (i.get("assignees") or [])],
            "updated_at": i.get("updatedAt"),
        }
        for i in issues
    ]
    if as_json:
        click.echo(json.dumps(slim, indent=2))
        return
    if not slim:
        click.echo("no open high-priority todos matching this filter.")
        return
    click.echo(f"{'#':>5}  {'labels':<40}  {'title':<60}")
    for row in slim:
        labels_s = ",".join(row["labels"])[:38]
        title_s = row["title"][:58]
        click.echo(f"{row['number']:>5}  {labels_s:<40}  {title_s:<60}")


# ---------------------------------------------------------------------------
# todo next
# ---------------------------------------------------------------------------

@todo.command("next")
@click.option(
    "--lane",
    required=True,
    help="Label to filter on (e.g. infrastructure, hub-admin). "
    "Required — ``next`` is the 'pick one' path and needs a lane.",
)
@click.option(
    "--repo",
    default=TODO_REPO_DEFAULT,
    show_default=True,
    help="Todo repo [$SCITEX_TODO_REPO].",
)
@click.option(
    "--exclude",
    default="",
    help="Comma-sep issue numbers to skip (cooldown list).",
)
@click.option(
    "--limit",
    type=int,
    default=50,
    show_default=True,
    help="Max issues to fetch before picking.",
)
@click.pass_context
def todo_next(
    ctx: click.Context,
    lane: str,
    repo: str,
    exclude: str,
    limit: int,
) -> None:
    """Pick the next todo for ``--lane``.

    Exits non-zero when nothing matches (so cron / subshells can branch).
    """
    extra: list[int] = []
    for tok in (exclude or "").split(","):
        tok = tok.strip()
        if tok.isdigit():
            extra.append(int(tok))

    issues = _fetch_open_todos(repo, limit=limit)
    prs = _fetch_open_prs(repo, limit=100)

    pick_mod = _import_pick_helper()
    pick = pick_mod.pick_todo(issues, prs, lane, extra)
    as_json = bool(ctx.obj and ctx.obj.get("json"))
    if pick is None:
        if as_json:
            click.echo("null")
        else:
            click.echo("no unclaimed todo matched this lane.", err=True)
        sys.exit(1)
    if as_json:
        click.echo(json.dumps(pick, indent=2))
    else:
        click.echo(f"#{pick['number']}  {pick['title']}")
        click.echo(f"  labels: {','.join(pick['labels'])}")
        click.echo(f"  reason: {pick['reason']}")


# ---------------------------------------------------------------------------
# todo triage
# ---------------------------------------------------------------------------

@todo.command("triage")
@click.option(
    "--lane",
    default=None,
    help="Label to weight lane-fit against. Omit for lane-agnostic scoring.",
)
@click.option(
    "--repo",
    default=TODO_REPO_DEFAULT,
    show_default=True,
    help="Todo repo [$SCITEX_TODO_REPO].",
)
@click.option(
    "--limit",
    type=int,
    default=100,
    show_default=True,
    help="Max issues to fetch.",
)
@click.pass_context
def todo_triage(
    ctx: click.Context,
    lane: str | None,
    repo: str,
    limit: int,
) -> None:
    """Score every open todo on staleness + lane-fit + claimed + assigned.

    Output is a JSON array sorted by descending score. Use ``--json`` for
    machine-readable output; the human form is a ranked table.
    """
    issues = _fetch_open_todos(repo, limit=limit)
    prs = _fetch_open_prs(repo, limit=100)

    pick_mod = _import_pick_helper()
    claimed = pick_mod.claimed_numbers_from_prs(prs)
    now_ts = time.time()

    scored = [_score_issue(i, lane, claimed, now_ts) for i in issues]
    scored.sort(key=lambda row: row["score"], reverse=True)

    as_json = bool(ctx.obj and ctx.obj.get("json"))
    if as_json:
        click.echo(json.dumps(scored, indent=2))
        return
    if not scored:
        click.echo("no open high-priority todos to triage.")
        return
    click.echo(
        f"{'score':>6}  {'#':>5}  {'reason':<40}  {'title':<60}"
    )
    for row in scored:
        title_s = row["title"][:58]
        reason_s = row["score_reason"][:38]
        click.echo(
            f"{row['score']:>6.2f}  {row['number']:>5}  {reason_s:<40}  {title_s:<60}"
        )


__all__ = ["todo"]
