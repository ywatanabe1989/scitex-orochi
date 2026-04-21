#!/bin/bash
# -*- coding: utf-8 -*-
# Timestamp: "2026-04-20 (ywatanabe)"
# File: scripts/client/pkg-audit.sh
# Description: Shell-level venv drift detector for scitex-* packages.
#
# Given a list of scitex-family packages, verify two independent invariants
# per package:
#   1. `pip show <pkg>` succeeds       (package known to the active venv)
#   2. `python -c 'import <pkg>'` works (import actually resolves at runtime)
#
# Classification:
#   ok       — both checks pass
#   drift    — pip shows the package but import fails (stale metadata, .pth
#              mismatch, editable install pointing at a moved path, etc.)
#   missing  — pip show fails (package not installed at all)
#
# With --auto-fix, drift/missing packages whose source repo is present on
# this host are reinstalled with `pip install -e <repo>`.
#
# Output modes:
#   default     — human-readable one-liner per package, colored
#   --json      — NDJSON (one JSON object per package, no colors)
#   --quiet     — suppress all stdout; exit code is the signal
#
# Exit codes:
#   0  — all packages ok (or fixed cleanly with --auto-fix)
#   1  — drift/missing observed, no fix attempted
#   2  — --auto-fix attempted but at least one install failed
#   3  — `pip` binary not found in PATH
#
# Intended caller: the mgr-pkg cron job defined in
# deployment/host-setup/orochi-cron/cron.yaml.example. Safe to run
# interactively; safe to run under cron (silent-success with --quiet).

set -uo pipefail

# ──────────────────────────────────────────
# Defaults / flag parsing
# ──────────────────────────────────────────
AUTO_FIX=0
JSON_OUT=0
QUIET=0
SINGLE_PKG=""

usage() {
    cat <<EOF
Usage: $(basename "$0") [--auto-fix] [--json] [--quiet] [--pkg <name>]

Audit scitex-* packages for pip/import drift.

Options:
  --auto-fix       Reinstall drifting/missing packages via 'pip install -e'
                   when the source repo is present on this host.
  --json           Emit NDJSON (one line per package) instead of human text.
  --quiet          Suppress all stdout; communicate only via exit code.
  --pkg <name>     Audit a single package (default: full scitex-* list).
  -h, --help       Show this help and exit.

Environment:
  PACKAGES         Space-separated override of the default package list.

Exit codes:
  0 ok, 1 drift/missing, 2 fix failed, 3 pip not found.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --auto-fix) AUTO_FIX=1; shift ;;
        --json) JSON_OUT=1; shift ;;
        --quiet) QUIET=1; shift ;;
        --pkg)
            if [[ $# -lt 2 ]]; then
                echo "error: --pkg requires an argument" >&2
                exit 64
            fi
            SINGLE_PKG="$2"
            shift 2
            ;;
        -h|--help) usage; exit 0 ;;
        *)
            echo "error: unknown argument: $1" >&2
            usage >&2
            exit 64
            ;;
    esac
done

# ──────────────────────────────────────────
# Dependencies
# ──────────────────────────────────────────
PIP_BIN="${PIP_BIN:-pip}"
PYTHON_BIN="${PYTHON_BIN:-python}"

if ! command -v "$PIP_BIN" >/dev/null 2>&1; then
    if [[ "$QUIET" -eq 0 ]]; then
        echo "error: '$PIP_BIN' not found in PATH" >&2
    fi
    exit 3
fi

# ──────────────────────────────────────────
# Package list + repo-path map
# ──────────────────────────────────────────
DEFAULT_PACKAGES="scitex scitex-orochi scitex-agent-container scitex-clew scitex-cloud"
PACKAGES="${PACKAGES:-$DEFAULT_PACKAGES}"

if [[ -n "$SINGLE_PKG" ]]; then
    PACKAGES="$SINGLE_PKG"
fi

# Expand ~ once so the map lookups are direct string compares.
HOME_DIR="${HOME:-/root}"

repo_path_for() {
    # Return the canonical source repo path for a package, or empty if
    # this package isn't one we know how to auto-fix.
    case "$1" in
        scitex)                   echo "$HOME_DIR/proj/scitex-python" ;;
        scitex-orochi)            echo "$HOME_DIR/proj/scitex-orochi" ;;
        scitex-agent-container)   echo "$HOME_DIR/proj/scitex-agent-container" ;;
        scitex-clew)              echo "$HOME_DIR/proj/scitex-clew" ;;
        scitex-cloud)             echo "$HOME_DIR/proj/scitex-cloud" ;;
        *)                        echo "" ;;
    esac
}

import_name_for() {
    # PEP 8 import name: scitex-orochi → scitex_orochi.
    echo "${1//-/_}"
}

# ──────────────────────────────────────────
# Colors (only when interactive & not JSON/quiet)
# ──────────────────────────────────────────
if [[ -t 1 ]] && [[ "$JSON_OUT" -eq 0 ]] && [[ "$QUIET" -eq 0 ]]; then
    C_OK='\033[0;32m'
    C_WARN='\033[0;33m'
    C_ERR='\033[0;31m'
    C_DIM='\033[2m'
    C_RESET='\033[0m'
else
    C_OK=''; C_WARN=''; C_ERR=''; C_DIM=''; C_RESET=''
fi

# ──────────────────────────────────────────
# Emit helpers
# ──────────────────────────────────────────
emit_human() {
    # $1=status, $2=pkg, $3=detail
    local status="$1" pkg="$2" detail="$3"
    local color symbol
    case "$status" in
        ok)        color="$C_OK";   symbol="✓" ;;
        drift)     color="$C_WARN"; symbol="?" ;;
        missing)   color="$C_ERR";  symbol="✗" ;;
        fixed)     color="$C_OK";   symbol="↻" ;;
        fix_failed) color="$C_ERR"; symbol="!" ;;
        *)         color="";        symbol="·" ;;
    esac
    printf "%b%s %-28s %s%b %s\n" \
        "$color" "$symbol" "$pkg" "$status" "$C_RESET" \
        "${detail:+($detail)}"
}

emit_json() {
    # $1=pkg $2=status $3=pip_ok $4=import_ok $5=fixed $6=repo_path $7=detail
    local pkg="$1" status="$2" pip_ok="$3" import_ok="$4" fixed="$5" repo="$6" detail="$7"
    # Hand-rolled JSON — we avoid a python dependency on the emit path so the
    # script stays callable even if the venv is the thing that's broken.
    local repo_json detail_json
    if [[ -n "$repo" ]]; then
        repo_json="\"$repo\""
    else
        repo_json="null"
    fi
    if [[ -n "$detail" ]]; then
        # Escape backslash + double-quote for JSON.
        local esc="${detail//\\/\\\\}"
        esc="${esc//\"/\\\"}"
        detail_json="\"$esc\""
    else
        detail_json="null"
    fi
    printf '{"package":"%s","status":"%s","pip_ok":%s,"import_ok":%s,"fixed":%s,"repo_path":%s,"detail":%s}\n' \
        "$pkg" "$status" "$pip_ok" "$import_ok" "$fixed" "$repo_json" "$detail_json"
}

output() {
    # Route a result through the right emitter. All arguments are passed
    # to both emit_human and emit_json in the shapes they each need.
    local pkg="$1" status="$2" pip_ok="$3" import_ok="$4" fixed="$5" repo="$6" detail="$7"
    if [[ "$QUIET" -eq 1 ]]; then
        return 0
    fi
    if [[ "$JSON_OUT" -eq 1 ]]; then
        emit_json "$pkg" "$status" "$pip_ok" "$import_ok" "$fixed" "$repo" "$detail"
    else
        emit_human "$status" "$pkg" "$detail"
    fi
}

# ──────────────────────────────────────────
# Per-package audit
# ──────────────────────────────────────────
TOTAL=0
NUM_DRIFT=0
NUM_MISSING=0
NUM_FIXED=0
NUM_FIX_FAILED=0

for pkg in $PACKAGES; do
    TOTAL=$((TOTAL + 1))
    import_name="$(import_name_for "$pkg")"
    repo="$(repo_path_for "$pkg")"

    # 1. pip show
    if "$PIP_BIN" show "$pkg" >/dev/null 2>&1; then
        pip_ok=true
        pip_ok_int=1
    else
        pip_ok=false
        pip_ok_int=0
    fi

    # 2. python -c 'import <import_name>'
    if "$PYTHON_BIN" -c "import ${import_name}" >/dev/null 2>&1; then
        import_ok=true
        import_ok_int=1
    else
        import_ok=false
        import_ok_int=0
    fi

    # 3. classify
    if $pip_ok && $import_ok; then
        status="ok"
    elif $pip_ok && ! $import_ok; then
        status="drift"
        NUM_DRIFT=$((NUM_DRIFT + 1))
    else
        status="missing"
        NUM_MISSING=$((NUM_MISSING + 1))
    fi

    fixed_flag=false
    detail=""

    # 4. optional auto-fix
    if [[ "$AUTO_FIX" -eq 1 ]] && [[ "$status" != "ok" ]]; then
        if [[ -n "$repo" ]] && [[ -d "$repo" ]]; then
            if "$PIP_BIN" install -e "$repo" >/dev/null 2>&1; then
                status="fixed"
                fixed_flag=true
                NUM_FIXED=$((NUM_FIXED + 1))
                detail="reinstalled from $repo"
            else
                status="fix_failed"
                NUM_FIX_FAILED=$((NUM_FIX_FAILED + 1))
                detail="pip install -e $repo failed"
            fi
        else
            # Nothing we can do automatically; stay in drift/missing.
            detail="no repo at ${repo:-<unmapped>}"
        fi
    elif [[ "$status" = "drift" ]]; then
        detail="pip ok, import fails ($import_name)"
    elif [[ "$status" = "missing" ]]; then
        detail="not installed"
    fi

    # 5. emit
    fixed_json=false
    if $fixed_flag; then fixed_json=true; fi
    output "$pkg" "$status" "$pip_ok" "$import_ok" "$fixed_json" "$repo" "$detail"
done

# ──────────────────────────────────────────
# Summary + exit code
# ──────────────────────────────────────────
if [[ "$QUIET" -eq 0 ]] && [[ "$JSON_OUT" -eq 0 ]]; then
    printf "%b" "$C_DIM"
    printf "── %d audited · drift=%d missing=%d fixed=%d fix_failed=%d ──\n" \
        "$TOTAL" "$NUM_DRIFT" "$NUM_MISSING" "$NUM_FIXED" "$NUM_FIX_FAILED"
    printf "%b" "$C_RESET"
fi

# Exit code ladder. 2 wins over 1 (fix_failed implies we tried and failed).
if [[ "$NUM_FIX_FAILED" -gt 0 ]]; then
    exit 2
fi

# After a successful --auto-fix, remaining drift/missing are ones where
# the repo was missing — still a problem to report.
REMAINING_BAD=$((NUM_DRIFT + NUM_MISSING - NUM_FIXED))
if [[ "$REMAINING_BAD" -gt 0 ]]; then
    exit 1
fi

exit 0

# EOF
