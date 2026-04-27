"""Validate scitex-orochi CLI convention pointers.

Index-coverage and dead-link checks now live in ``tests/test_skills_quality.py``
(driven by ``scitex_dev._skills_quality``). This file retains only the
orochi_project-specific invariants that the generic quality checker does not know
about:

* ``docs/cli.md`` must point to the canonical convention file.
* The canonical convention file declares the noun/verb shape.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "src" / "scitex_orochi" / "_skills"
DOCS_CLI = REPO_ROOT / "docs" / "cli.md"
CANONICAL_CLI_CONV = SKILLS_DIR / "scitex-orochi" / "20_convention-cli.md"


def test_docs_cli_exists() -> None:
    assert DOCS_CLI.is_file(), f"missing: {DOCS_CLI}"


def test_docs_cli_points_to_canonical_convention() -> None:
    text = DOCS_CLI.read_text(encoding="utf-8")
    assert "convention-cli.md" in text, (
        "docs/cli.md must reference the canonical convention file"
    )
    assert CANONICAL_CLI_CONV.is_file(), (
        f"canonical convention file missing: {CANONICAL_CLI_CONV}"
    )


def test_convention_cli_declares_noun_verb_shape() -> None:
    text = CANONICAL_CLI_CONV.read_text(encoding="utf-8")
    assert "scitex-orochi <noun> <verb>" in text
    assert "mcp start" in text
    assert "SCITEX_OROCHI_NO_DEPRECATION" in text
