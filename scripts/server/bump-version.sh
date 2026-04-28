#!/usr/bin/env bash
# bump-version.sh — Increment version in pyproject.toml and orochi/settings.py
# Usage: ./scripts/bump-version.sh [--major|--minor|--patch] [--no-commit]
# Default: --patch
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PYPROJECT="$REPO_ROOT/pyproject.toml"
SETTINGS="$REPO_ROOT/orochi/settings.py"
INIT_PY="$REPO_ROOT/src/scitex_orochi/__init__.py"

# --- Parse flags --------------------------------------------------------
BUMP="patch"
COMMIT=true
for arg in "$@"; do
    case "$arg" in
    --major) BUMP="major" ;;
    --minor) BUMP="minor" ;;
    --patch) BUMP="patch" ;;
    --no-commit) COMMIT=false ;;
    -h | --help)
        echo "Usage: $0 [--major|--minor|--patch] [--no-commit]"
        echo "  --major      bump major (X.0.0)"
        echo "  --minor      bump minor (x.Y.0)"
        echo "  --patch      bump patch (x.y.Z)  [default]"
        echo "  --no-commit  skip git commit"
        exit 0
        ;;
    *)
        echo "Unknown flag: $arg"
        exit 1
        ;;
    esac
done

# --- Read current version -----------------------------------------------
CURRENT=$(grep -m1 '^version' "$PYPROJECT" | sed 's/.*"\(.*\)".*/\1/')
if [[ -z "$CURRENT" ]]; then
    echo "ERROR: could not read version from $PYPROJECT" >&2
    exit 1
fi

IFS='.' read -r MAJOR MINOR PATCH <<<"$CURRENT"

# --- Compute new version ------------------------------------------------
case "$BUMP" in
major)
    MAJOR=$((MAJOR + 1))
    MINOR=0
    PATCH=0
    ;;
minor)
    MINOR=$((MINOR + 1))
    PATCH=0
    ;;
patch) PATCH=$((PATCH + 1)) ;;
esac

NEW="${MAJOR}.${MINOR}.${PATCH}"
echo "Bumping version: $CURRENT → $NEW ($BUMP)"

# --- Update pyproject.toml ----------------------------------------------
sed -i "s/^version = \"$CURRENT\"/version = \"$NEW\"/" "$PYPROJECT"

# --- Update fallback in orochi/settings.py ------------------------------
if [[ -f "$SETTINGS" ]]; then
    sed -i "s/OROCHI_VERSION = \"[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\"/OROCHI_VERSION = \"$NEW\"/" "$SETTINGS"
fi

# --- Update src/scitex_orochi/__init__.py -------------------------------
# The package metadata constant must stay in lockstep with pyproject.toml
# so consumers that `import scitex_orochi; scitex_orochi.__version__`
# don't see a stale value. ywatanabe 2026-04-27.
if [[ -f "$INIT_PY" ]]; then
    sed -i "s/^__version__ = \"[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\"/__version__ = \"$NEW\"/" "$INIT_PY"
fi

# --- Verify -------------------------------------------------------------
VERIFY=$(grep -m1 '^version' "$PYPROJECT" | sed 's/.*"\(.*\)".*/\1/')
if [[ "$VERIFY" != "$NEW" ]]; then
    echo "ERROR: pyproject.toml was not updated correctly (got $VERIFY)" >&2
    exit 1
fi
echo "Updated pyproject.toml:      version = \"$NEW\""

if [[ -f "$SETTINGS" ]]; then
    VERIFY_S=$(grep 'OROCHI_VERSION = "' "$SETTINGS" | grep -v _pkg_version | sed 's/.*"\(.*\)".*/\1/')
    echo "Updated orochi/settings.py:  OROCHI_VERSION = \"$VERIFY_S\""
fi

# --- Git commit ----------------------------------------------------------
if $COMMIT; then
    cd "$REPO_ROOT"
    git add "$PYPROJECT" "$SETTINGS" "$INIT_PY"
    git commit -m "chore: bump version to $NEW"
    echo "Committed: chore: bump version to $NEW"
else
    echo "Skipped git commit (--no-commit)"
fi
