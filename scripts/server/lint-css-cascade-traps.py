#!/usr/bin/env python3
"""Audit pass for the `.avatar-clickable`-class CSS cascade trap.

The 2026-04-27 incident: a `<td class="agent-icon-cell avatar-clickable">`
inherited `display: inline-flex` from `.avatar-clickable` (declared in
`style-agents.css` for sidebar buttons), which knocked the cell out of
`display: table-cell` and silently disabled `vertical-align: middle`.
The bug was invisible to grep on `.agent-icon-cell` alone — the winner
was a different class.

This script catches future regressions of the same shape:

  CSS class C declares `display: <not table-cell>` AND
  HTML/TS source uses `<td class="... C ...">`        →  TRAP

Exits 1 on any new trap found, 0 otherwise. Runs in <1 s on the
current tree. Wire into the `make lint-frontend` target so CI fails on
re-introduction.

The single ALLOWED instance is the original `.avatar-clickable` paired
with the explicit override at
`hub/static/hub/components/components-agent-cards.css:325-329` —
listed in `_KNOWN_TRAPS_OK` below.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

_REPO = pathlib.Path(__file__).resolve().parent.parent.parent
_CSS_ROOT = _REPO / "hub" / "static" / "hub"
_TS_ROOT = _REPO / "hub" / "frontend" / "src"
_TEMPLATES_ROOT = _REPO / "hub" / "templates"

# Cell-incompatible display values. `table-cell` would obviously work,
# `none` is fine (cell hidden), `revert` defers to UA stylesheet.
_BAD_DISPLAYS = {"flex", "inline-flex", "grid", "inline-grid", "block", "inline-block"}

# Whitelist: classes where the trap exists but is explicitly handled by
# a follow-up rule in components-agent-cards.css.
_KNOWN_TRAPS_OK = {
    "avatar-clickable",  # countered by `.agent-row > td.avatar-clickable
    # { display: table-cell !important }` in
    # components-agent-cards.css
}


def _classes_with_bad_display() -> dict[str, str]:
    """Return {class_name: display_value} for every class that sets a
    cell-incompatible display value.

    Multiple-rule overlap returns the FIRST hit per class (subsequent
    rules might override it back to table-cell, but we still report so
    the reviewer is aware the class is used in a table context)."""
    out: dict[str, str] = {}
    for css in _CSS_ROOT.rglob("*.css"):
        if "/dist/" in str(css):
            continue
        text = css.read_text(errors="replace")
        # Find all `.foo {... display: bar ...}` rule pairs. Use a
        # simple scan because we only care about the class+display
        # association, not the full selector list.
        for m in re.finditer(
            r"\.([a-zA-Z][a-zA-Z0-9_-]*)\s*[,{][^}]*?display\s*:\s*([a-z-]+)",
            text,
        ):
            cls, disp = m.group(1), m.group(2)
            if disp in _BAD_DISPLAYS:
                out.setdefault(cls, disp)
    return out


def _td_uses(cls: str) -> list[str]:
    """grep TS + templates for `<td class="... <cls> ...">` patterns.
    Returns the matching ``file:line: <line>`` strings (capped at 5 per
    class so the report stays readable)."""
    pattern = rf'<td[^>]*class="[^"]*\b{re.escape(cls)}\b'
    cmd = [
        "grep",
        "-rEnH",
        pattern,
        str(_TS_ROOT),
        str(_TEMPLATES_ROOT),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode not in (0, 1):
        # 0 = matches; 1 = no matches; anything else = real error
        print(f"grep error for {cls}: {r.stderr}", file=sys.stderr)
        return []
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    return lines[:5]


def main() -> int:
    bad = _classes_with_bad_display()
    traps: list[tuple[str, str, list[str]]] = []
    for cls, disp in sorted(bad.items()):
        if cls in _KNOWN_TRAPS_OK:
            continue
        usages = _td_uses(cls)
        if usages:
            traps.append((cls, disp, usages))

    if not traps:
        print(
            "✓ CSS cascade trap audit: no class with `display: !table-cell` is "
            f"used as a <td class=…> ({len(bad)} candidate classes scanned)"
        )
        return 0

    print("✗ CSS cascade trap audit: NEW traps found")
    print()
    print(
        "These classes would put a `<td>` into the wrong display primitive,",
        "silently breaking `vertical-align: middle` and any other",
        "table-cell-only properties:",
        sep=" ",
    )
    print()
    for cls, disp, usages in traps:
        print(f"  .{cls} (display: {disp})")
        for u in usages:
            print(f"      {u}")
    print()
    print(
        "Fix: add `.agent-row > td.<class> { display: table-cell !important }`",
        "in `components-agent-cards.css` (mirroring the `.avatar-clickable`",
        "fix), OR rename the class so it's not also used on a <td>.",
        sep=" ",
    )
    print()
    print("If this is intentional, add the class to _KNOWN_TRAPS_OK in this script.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
