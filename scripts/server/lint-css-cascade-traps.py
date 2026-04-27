#!/usr/bin/env python3
"""Audit pass for two classes of silent-defeat CSS bugs that hit prod
this session (`mgmt/ENHANCEMENT_IDEAS_2026-04-28.md` §1).

  1. **Display-precondition trap (the `.avatar-clickable` family).**
     A class declares `display: !table-cell` and gets applied to a
     `<td>`. The cell loses table-cell semantics and any
     `vertical-align: middle` rule (which only applies to table-cell /
     inline content) silently turns into a no-op. Past hit:
     `.avatar-clickable { display: inline-flex }` on the agent-table
     icon cell on 2026-04-27.

  2. **Position-anchor advisory (the `.ws-dropdown` family).**
     A class declares `position: absolute` paired with `top: 100%` /
     `bottom: 100%` etc. — i.e. the *"drop below my parent"* pattern.
     This requires the IMMEDIATE intended-anchor parent to be
     positioned (not `position: static`). Past hit: the workspace
     dropdown was rendered at viewport bottom because
     `.sidebar-brand-compact` was static. We can't statically resolve
     the parent in CSS, so this pass only LISTS the candidate rules
     with their file:line for human review at PR time.

Exits 1 on any new display trap found (advisory list never fails the
build). Runs in <1 s on the current tree. Wire into `make lint-css`
so CI fails on re-introduction.

The single ALLOWED display-trap instance is the original
`.avatar-clickable` paired with the explicit override at
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


def _drop_below_parent_candidates() -> list[tuple[str, int, str]]:
    """Find CSS rules of the form

        .<cls> {
          position: absolute;
          top: 100%;        # or bottom: 100%, left: 100%, right: 100%
          ...
        }

    These declare *"render below/above/beside my parent"*. The pattern
    only works when the parent has `position: !static`; otherwise the
    element anchors to the viewport (`.ws-dropdown` 2026-04-27 bug).

    Static analysis can't resolve the parent (it depends on DOM
    nesting at render time), so we just LIST candidates with their
    file:line so the reviewer can spot-check at PR time. Returns
    ``[(class_name, line_no, file_relative_path), …]``.
    """
    out: list[tuple[str, int, str]] = []
    for css in _CSS_ROOT.rglob("*.css"):
        if "/dist/" in str(css):
            continue
        rel = css.relative_to(_REPO)
        text = css.read_text(errors="replace")
        # Iterate rule-by-rule. A "rule" is everything between `.<cls> {`
        # (or other selector) and the matching `}`. We allow combinator
        # selectors as long as the trailing token is a class.
        for m in re.finditer(
            r"(\.[a-zA-Z][a-zA-Z0-9_-]*)\s*\{([^{}]*)\}",
            text,
            re.DOTALL,
        ):
            cls = m.group(1).lstrip(".")
            body = m.group(2)
            if "position:" not in body or "absolute" not in body:
                continue
            # Look for any of the "100%" anchors; this catches the
            # .ws-dropdown shape without flagging every absolutely-
            # positioned element (only the drop-below-parent pattern).
            if not re.search(
                r"(top|bottom|left|right)\s*:\s*100%",
                body,
            ):
                continue
            # Compute line number for the rule head.
            line_no = text[: m.start()].count("\n") + 1
            out.append((cls, line_no, str(rel)))
    return out


def main() -> int:
    # ---- Trap 1: hard fail ---------------------------------------
    bad = _classes_with_bad_display()
    traps: list[tuple[str, str, list[str]]] = []
    for cls, disp in sorted(bad.items()):
        if cls in _KNOWN_TRAPS_OK:
            continue
        usages = _td_uses(cls)
        if usages:
            traps.append((cls, disp, usages))

    failed = False
    if traps:
        failed = True
        print("✗ CSS display trap: NEW traps found")
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
        print(
            "If this is intentional, add the class to _KNOWN_TRAPS_OK in this script."
        )
        print()
    else:
        print(
            "✓ CSS display trap: no class with `display: !table-cell` is "
            f"used as a <td class=…> ({len(bad)} candidate classes scanned)"
        )

    # ---- Trap 2: advisory only -----------------------------------
    anchors = _drop_below_parent_candidates()
    if anchors:
        print()
        print(
            f"ℹ position-anchor advisory: {len(anchors)} rule(s) match the "
            "`position: absolute; <edge>: 100%` (drop-below-parent) shape."
        )
        print(
            "  Each requires its INTENDED-ANCHOR PARENT to be positioned",
            "(not `position: static`); otherwise the element renders",
            "at the viewport edge.",
            sep=" ",
        )
        print(
            "  Manually verify each ancestor in the rendered DOM has",
            "`position: relative|absolute|fixed|sticky`. This is",
            "advisory — the linter cannot resolve parent statically.",
            sep=" ",
        )
        print()
        for cls, line_no, rel in anchors:
            print(f"    .{cls}    {rel}:{line_no}")
        print()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
