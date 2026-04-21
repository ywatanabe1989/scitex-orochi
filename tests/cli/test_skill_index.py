"""Validate ``src/scitex_orochi/_skills/SKILL_INDEX.md``.

Phase 1d Step A — PR #337 §11: every `.md` shipped under `_skills/` must
be listed in the index so a fleet agent can grep once and find the right
file.

Also asserts:

* ``docs/cli.md`` exists and references the canonical
  ``convention-cli.md`` (Q3 decision, two discovery paths / one source
  of truth).
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "src" / "scitex_orochi" / "_skills"
INDEX_PATH = SKILLS_DIR / "SKILL_INDEX.md"
DOCS_CLI = REPO_ROOT / "docs" / "cli.md"
CANONICAL_CLI_CONV = (
    SKILLS_DIR / "scitex-orochi" / "convention-cli.md"
)


def _all_skill_mds() -> list[Path]:
    """Walk the _skills tree; exclude:

    * ``SKILL_INDEX.md`` (this is the index, not an indexable skill).
    * Any path whose component starts with ``.`` (hidden archive dirs
      such as ``.old/`` are not user-facing skills).
    """
    found: list[Path] = []
    for p in SKILLS_DIR.rglob("*.md"):
        if p.name == "SKILL_INDEX.md":
            continue
        if any(part.startswith(".") for part in p.relative_to(SKILLS_DIR).parts):
            continue
        found.append(p)
    return sorted(found)


def test_skill_index_exists() -> None:
    assert INDEX_PATH.is_file(), f"missing: {INDEX_PATH}"


def test_every_skill_file_is_listed() -> None:
    """Every `.md` under `_skills/` is referenced in SKILL_INDEX.md."""
    index_text = INDEX_PATH.read_text(encoding="utf-8")
    missing: list[str] = []
    for md in _all_skill_mds():
        rel = md.relative_to(SKILLS_DIR).as_posix()
        if rel not in index_text:
            missing.append(rel)
    assert not missing, (
        "SKILL_INDEX.md is missing rows for these files (add them to the "
        "appropriate table):\n  - " + "\n  - ".join(missing)
    )


def test_index_only_lists_real_files() -> None:
    """Every path-shaped string in the index that ends with `.md` must
    resolve to a real file under ``_skills/``. Catches stale entries."""
    index_text = INDEX_PATH.read_text(encoding="utf-8")
    # Very conservative: look for tokens matching `scitex-orochi/.../file.md`
    # inside backtick spans. Only validate the relative paths; prose
    # sentences that happen to end with `.md` would not be in backticks.
    import re

    for match in re.finditer(r"`([A-Za-z0-9_./\-]+\.md)`", index_text):
        rel = match.group(1)
        # Ignore absolute / cross-repo references; index uses bare
        # relative paths under `_skills/`.
        if rel.startswith(("/", "http", "..")):
            continue
        # Bare file names (e.g. `SKILL.md` when mentioned in prose) are
        # not table path references — they only count if a resolved path
        # under either the top-level or the scitex-orochi subdir exists.
        if "/" not in rel:
            continue
        path = SKILLS_DIR / rel
        assert path.is_file(), f"SKILL_INDEX.md references missing file: {rel}"


# ---------------------------------------------------------------------------
# docs/cli.md pointer — Q3 decision
# ---------------------------------------------------------------------------


def test_docs_cli_exists() -> None:
    assert DOCS_CLI.is_file(), f"missing: {DOCS_CLI}"


def test_docs_cli_points_to_canonical_convention() -> None:
    text = DOCS_CLI.read_text(encoding="utf-8")
    # The pointer must reference the canonical path (either as a markdown
    # link or a bare relative path).
    assert "convention-cli.md" in text, (
        "docs/cli.md must reference the canonical convention file"
    )
    assert CANONICAL_CLI_CONV.is_file(), (
        f"canonical convention file missing: {CANONICAL_CLI_CONV}"
    )


def test_convention_cli_declares_noun_verb_shape() -> None:
    """Sanity: convention-cli.md contains the canonical shape string and
    lists the flat-keeper set."""
    text = CANONICAL_CLI_CONV.read_text(encoding="utf-8")
    assert "scitex-orochi <noun> <verb>" in text
    assert "mcp start" in text
    assert "SCITEX_OROCHI_NO_DEPRECATION" in text
