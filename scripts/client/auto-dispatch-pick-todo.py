#!/usr/bin/env python3
"""auto-dispatch-pick-todo.py — pick the next high-priority TODO for a lane.

Companion to ``scripts/client/auto-dispatch-probe.sh``. Given:
  * a lane label (e.g. ``infrastructure``, ``specialized-hub-admin``,
    ``specialized-wsl-access``, ``specialized-domain``, ``hub-admin``,
    ``scitex-cloud``) — required
  * an "already-claimed" filter: best-effort by consulting open PRs in the
    same todo repo that reference ``#<N>`` in the title or body

… this returns a JSON object on stdout with the chosen TODO:

    {"number": 123, "title": "...", "labels": [...], "assignees": [...]}

…or ``null`` if nothing matches.

Data source: ``gh issue list`` + ``gh pr list`` against
``ywatanabe1989/todo``. The bash probe invokes this helper, reads stdout,
and injects the dispatch prompt into the head's tmux pane.

Why Python and not jq-in-bash:
  * The pick heuristic combines three JSON arrays (issues, PRs, state file)
    and the already-claimed filter is non-trivial.
  * A pure-bash version exploded in size and was hard to unit-test.

Unit-testable seam: ``pick_todo(issues, open_prs, lane, extra_exclude)``
is a pure function. The CLI layer invokes it after calling out to ``gh``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Iterable

TODO_REPO = os.environ.get("SCITEX_TODO_REPO", "ywatanabe1989/todo")

# Regex that matches a comment-based claim following the documented protocol:
#   gh issue comment <N> --body "claimed by head-<host>, ..."
_CLAIM_COMMENT_RE = re.compile(r"claimed by head-", re.IGNORECASE)
# How far back to look for claim comments (in hours).
_CLAIM_WINDOW_HOURS = 4


# -----------------------------------------------------------------------------
# Pure-function core (unit-tested)
# -----------------------------------------------------------------------------

_ISSUE_REF_RE = re.compile(r"(?:^|[\s\(\[#])#?(\d+)\b")


def _extract_issue_refs(text: str) -> set[int]:
    """Return {123, 45} from "fixes #123 and todo#45"."""
    if not text:
        return set()
    out: set[int] = set()
    for m in _ISSUE_REF_RE.finditer(text):
        try:
            out.add(int(m.group(1)))
        except (TypeError, ValueError):
            continue
    return out


def claimed_numbers_from_prs(open_prs: list[dict]) -> set[int]:
    """Collect issue numbers referenced by any open PR's title/body.

    This is intentionally best-effort: an open PR that mentions ``#123`` in
    its body is presumed to be "working on" todo#123. It misses PRs that
    forgot to cross-reference — but the daemon is about restoring dispatch,
    not strict policy; a 15-min cooldown buffers the failure mode.
    """
    claimed: set[int] = set()
    for pr in open_prs or []:
        title = pr.get("title") or ""
        body = pr.get("body") or ""
        claimed.update(_extract_issue_refs(title))
        claimed.update(_extract_issue_refs(body))
    return claimed


def claimed_numbers_from_comments(
    repo: str,
    issue_numbers: Iterable[int],
    window_hours: int = _CLAIM_WINDOW_HOURS,
) -> set[int]:
    """Return issue numbers whose recent comments contain a claim marker.

    Fetches up to 10 recent comments per candidate issue via ``gh api``
    with a ``since`` filter so only the last ``window_hours`` are checked.
    Any comment matching :data:`_CLAIM_COMMENT_RE` marks the issue as taken
    (todo#469 Bug 2).
    """
    from datetime import datetime, timedelta, timezone

    since_dt = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    since = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    claimed: set[int] = set()
    for num in issue_numbers:
        try:
            out = subprocess.run(
                [
                    "gh", "api",
                    f"repos/{repo}/issues/{num}/comments?since={since}&per_page=10",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout
            comments: list[dict] = json.loads(out or "[]")
            if not isinstance(comments, list):
                continue
        except Exception:
            continue
        if any(_CLAIM_COMMENT_RE.search(c.get("body") or "") for c in comments):
            claimed.add(num)
    return claimed


def pick_todo(
    issues: list[dict],
    open_prs: list[dict],
    lane: str,
    extra_exclude: Iterable[int] = (),
) -> dict | None:
    """Pick the first issue matching ``lane`` that isn't already claimed.

    * ``issues`` — ``gh issue list --json number,title,labels,assignees`` output
    * ``open_prs`` — ``gh pr list --state open --json title,body`` output
    * ``lane`` — a label name the issue must carry (exact match)
    * ``extra_exclude`` — additional numbers to skip (cooldown / just-dispatched)

    Returns the raw issue dict (with added ``reason``) or ``None``.
    """
    claimed = claimed_numbers_from_prs(open_prs) | set(extra_exclude)

    for issue in issues or []:
        num = int(issue.get("number") or 0)
        if not num or num in claimed:
            continue
        labels = {(lab.get("name") or "").strip() for lab in issue.get("labels") or []}
        if lane not in labels:
            continue
        # Skip anything already assigned to a human — that's explicit ownership.
        assignees = issue.get("assignees") or []
        if assignees:
            continue
        return {
            "number": num,
            "title": issue.get("title") or "",
            "labels": sorted(labels),
            "reason": f"lane={lane};first-open-unclaimed",
        }
    return None


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def _gh_json(args: list[str]) -> list[dict]:
    """Invoke gh, return parsed JSON array. Returns [] on failure."""
    try:
        out = subprocess.run(
            ["gh", *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return []
    try:
        data = json.loads(out or "[]")
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lane", required=True, help="label to filter on")
    parser.add_argument(
        "--repo",
        default=TODO_REPO,
        help=f"todo repo (default: {TODO_REPO})",
    )
    parser.add_argument(
        "--exclude",
        default="",
        help="comma-sep issue numbers to skip (cooldown list)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="max issues to fetch",
    )
    args = parser.parse_args()

    extra: list[int] = []
    for tok in (args.exclude or "").split(","):
        tok = tok.strip()
        if tok.isdigit():
            extra.append(int(tok))

    issues = _gh_json(
        [
            "issue",
            "list",
            "--repo",
            args.repo,
            "--state",
            "open",
            "--label",
            "high-priority",
            "--json",
            "number,title,labels,assignees",
            "--limit",
            str(args.limit),
        ]
    )
    open_prs = _gh_json(
        [
            "pr",
            "list",
            "--repo",
            args.repo,
            "--state",
            "open",
            "--json",
            "title,body",
            "--limit",
            "100",
        ]
    )

    # Also exclude issues with recent comment-claims (todo#469 Bug 2).
    candidate_nums = [int(i.get("number") or 0) for i in issues if i.get("number")]
    comment_claimed = claimed_numbers_from_comments(args.repo, candidate_nums)
    extra += list(comment_claimed)

    pick = pick_todo(issues, open_prs, args.lane, extra)
    sys.stdout.write(json.dumps(pick, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
