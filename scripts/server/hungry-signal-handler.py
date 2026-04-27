#!/usr/bin/env python3
"""hungry-signal-handler.py — lead-side responder for Layer 2 hungry DMs.

Companion to ``scripts/client/hungry-signal.sh``. When an idle head DMs
``lead`` with a ``head-<host>: hungry …`` message, lead needs to pick a
high-priority todo matching the head's lane (skipping claimed and
under-review issues) and reply in the same DM.

This file is both:

1. A **pure-function library** (``parse_hungry_signal``, ``pick_for_lane``,
   ``format_dispatch_reply``) that lead's agent loop or an in-context
   subagent can call directly. No side effects.
2. A **CLI** that can run as a standalone responder — read hungry DMs
   arriving in lead's inbox, invoke the same picker, and POST the reply
   back via the hub REST API.

Most deployments will use (1): lead's Claude pane reads its own DM traffic
via MCP, calls :func:`handle_hungry_message` on each match, and sends the
reply via the MCP ``reply`` tool. The CLI form exists for out-of-band
smoke tests and for hosts where lead is offline but the responder still
needs to answer.

Data source: ``gh issue list`` + ``gh pr list`` against the todo repo.
Filtering rules (lead msg#16310):

* ``--state open --label high-priority``
* skip issues whose number appears in any open PR title
* skip issues with the ``audit-review-2026-04-22`` label
  (stale-under-review)
* prefer issues with the sender's lane label; fall back to any unlabeled
  high-priority issue when no lane match exists
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

# Label used to suppress stale issues that are under review but still open
# (lead msg#16310). Keep as a module constant so tests can reference it
# without string-copy drift.
AUDIT_REVIEW_LABEL = os.environ.get(
    "SCITEX_HUNGRY_AUDIT_LABEL", "audit-review-2026-04-22"
)

# Hungry-signal DM format, emitted by scripts/client/hungry-signal.sh:
#   "head-<host>: hungry — 0 orochi_subagents × N cycles, ready for dispatch.
#    lane: <label>, orochi_alive: <list>"
# We only need sender + lane for the handler; "orochi_alive" is cosmetic.
_HUNGRY_RE = re.compile(
    r"""^\s*
        (?P<sender>head-[A-Za-z0-9_.-]+)
        \s*:\s*hungry\b
        .*?
        lane:\s*(?P<lane>[A-Za-z0-9_.-]+)
    """,
    re.VERBOSE | re.DOTALL,
)

# Re-used from auto-dispatch-pick-todo.py — any "#123" / "todo#45" reference.
_ISSUE_REF_RE = re.compile(r"(?:^|[\s\(\[#])#?(\d+)\b")


# -----------------------------------------------------------------------------
# Pure-function core (unit-tested)
# -----------------------------------------------------------------------------


def parse_hungry_signal(text: str) -> dict | None:
    """Extract sender + lane from a hungry-signal DM.

    Returns ``{"sender": "head-mba", "lane": "infrastructure"}`` or
    ``None`` if the text doesn't match. Lane is lower-cased because
    GitHub labels are case-insensitive on the client side and the DM
    generator may vary over time.
    """
    if not text:
        return None
    m = _HUNGRY_RE.search(text)
    if not m:
        return None
    return {"sender": m.group("sender"), "lane": m.group("lane").strip()}


def _extract_issue_refs(text: str) -> set[int]:
    out: set[int] = set()
    if not text:
        return out
    for m in _ISSUE_REF_RE.finditer(text):
        try:
            out.add(int(m.group(1)))
        except (TypeError, ValueError):
            continue
    return out


def claimed_numbers_from_prs(open_prs: list[dict]) -> set[int]:
    """Collect issue numbers referenced by any open PR's title/body.

    Mirrors the auto-dispatch helper so the two daemons treat "already
    claimed" identically. Best-effort: PRs that forget to cross-reference
    slip through.
    """
    claimed: set[int] = set()
    for pr in open_prs or []:
        claimed.update(_extract_issue_refs(pr.get("title") or ""))
        claimed.update(_extract_issue_refs(pr.get("body") or ""))
    return claimed


def _issue_labels(issue: dict) -> set[str]:
    return {(lab.get("name") or "").strip() for lab in issue.get("labels") or []}


def pick_for_lane(
    issues: list[dict],
    open_prs: list[dict],
    lane: str,
    extra_exclude: Iterable[int] = (),
    audit_label: str = AUDIT_REVIEW_LABEL,
) -> dict | None:
    """Pick the best open high-priority issue for the sender's ``lane``.

    1. Skip issues already referenced in any open PR title/body.
    2. Skip issues carrying ``audit_label`` (stale-under-review).
    3. Skip issues already assigned to a human.
    4. Prefer issues with the ``lane`` label. Fall back to first open
       high-priority without any lane label when no direct match exists
       (lead msg#16310 spec: "fall back to any unlabelled high-priority").

    The returned dict matches :func:`auto_dispatch_pick_todo.pick_todo` so
    downstream formatters can treat them interchangeably.
    """
    claimed = claimed_numbers_from_prs(open_prs) | set(extra_exclude)

    KNOWN_LANES = {
        "infrastructure",
        "hub-admin",
        "scitex-cloud",
        "specialized-hub-admin",
        "specialized-wsl-access",
        "specialized-domain",
    }

    best_lane: dict | None = None
    best_unlabelled: dict | None = None

    for issue in issues or []:
        num = int(issue.get("number") or 0)
        if not num or num in claimed:
            continue
        if issue.get("assignees"):
            continue
        labels = _issue_labels(issue)
        if audit_label in labels:
            continue

        if lane in labels and best_lane is None:
            best_lane = {
                "number": num,
                "title": issue.get("title") or "",
                "labels": sorted(labels),
                "reason": f"lane={lane};direct-match",
            }
            continue

        # Fall-back pool: high-priority without any recognised lane label.
        has_any_lane = bool(labels & KNOWN_LANES)
        if not has_any_lane and best_unlabelled is None:
            best_unlabelled = {
                "number": num,
                "title": issue.get("title") or "",
                "labels": sorted(labels),
                "reason": "fallback=unlabelled-high-priority",
            }

    return best_lane or best_unlabelled


def format_dispatch_reply(
    pick: dict | None,
    sender: str,
    lane: str,
    brief: str | None = None,
) -> str:
    """Compose the one-line DM reply in the `dispatch:` idiom (msg#16310)."""
    if not pick:
        return (
            f"dispatch: none matching lane={lane} — "
            f"no open high-priority todo fits {sender}. "
            f"Stand by; I'll route when one appears."
        )
    title = pick.get("title") or ""
    tail = f" — {brief}" if brief else ""
    return f"dispatch: todo#{pick['number']} — {title}{tail}"


def handle_hungry_message(
    text: str,
    issues: list[dict],
    open_prs: list[dict],
    brief: str | None = None,
    audit_label: str = AUDIT_REVIEW_LABEL,
) -> dict | None:
    """One-shot: parse a DM, pick a todo, format a reply.

    Returns ``None`` when ``text`` is not a hungry signal. Otherwise
    returns a dict with ``sender``, ``lane``, ``pick`` (or ``None``), and
    ``reply`` (the text lead should DM back).
    """
    parsed = parse_hungry_signal(text)
    if not parsed:
        return None
    pick = pick_for_lane(issues, open_prs, parsed["lane"], audit_label=audit_label)
    return {
        "sender": parsed["sender"],
        "lane": parsed["lane"],
        "pick": pick,
        "reply": format_dispatch_reply(pick, parsed["sender"], parsed["lane"], brief),
    }


# -----------------------------------------------------------------------------
# CLI — shell out to gh for issues + PRs. Useful for out-of-band smoke tests.
# -----------------------------------------------------------------------------


def _gh_json(args: list[str]) -> list[dict]:
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


def _fetch_todo_context(repo: str, limit: int = 50) -> tuple[list[dict], list[dict]]:
    issues = _gh_json(
        [
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--label",
            "high-priority",
            "--json",
            "number,title,labels,assignees",
            "--limit",
            str(limit),
        ]
    )
    open_prs = _gh_json(
        [
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--json",
            "title,body",
            "--limit",
            "100",
        ]
    )
    return issues, open_prs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--text",
        help="hungry-signal DM text to parse + respond to. If omitted, read stdin.",
    )
    parser.add_argument(
        "--repo",
        default=TODO_REPO,
        help=f"todo repo (default: {TODO_REPO})",
    )
    parser.add_argument(
        "--brief",
        default=None,
        help="optional brief appended to the reply",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="max issues to fetch",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the full response dict as JSON on stdout",
    )
    args = parser.parse_args()

    text = args.text
    if not text:
        text = sys.stdin.read()

    issues, open_prs = _fetch_todo_context(args.repo, limit=args.limit)
    result = handle_hungry_message(text, issues, open_prs, brief=args.brief)

    if result is None:
        print("not-a-hungry-signal", file=sys.stderr)
        return 2

    if args.json:
        sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
    else:
        sys.stdout.write(result["reply"] + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
