#!/usr/bin/env bash
# bootstrap-host.sh — one-command per-host setup for the Orochi fleet.
#
# Canonical location: ~/proj/scitex-orochi/scripts/client/install/bootstrap-host.sh
# Invoke from any host that has a scitex-orochi checkout cloned at the
# canonical path above. The script auto-derives SCRIPTS_ROOT from its
# own location, so it works from any directory.
#
# Idempotent. Safe to re-run after every `git pull` (scitex-orochi and/or
# ~/.dotfiles for the user-private host override dirs).
#
# 3. Optionally installs claude-hud:
#    - Only if `node` is on PATH (skipped on mba/spartan until node is
#      installed separately).
#    - Clones jarrodwatts/claude-hud to ~/proj/claude-hud (matches the
#      WSL canonical location), builds it, and wires statusLine in
#      ~/.claude/settings.json to the built dist/index.js.
#    - Rerunning is a no-op when the dist is up to date.
#
# Exit codes: 0 on success (partial OK — skipped steps are warnings,
# not failures). Non-zero only if a required step actually errored.

set -euo pipefail

log() { printf "[bootstrap-host] %s\n" "$*"; }
warn() { printf "[bootstrap-host] WARN: %s\n" "$*" >&2; }
err() { printf "[bootstrap-host] ERR: %s\n" "$*" >&2; }

# -- 0. Source the user's canonical PATH setup -------------------------------
# ~/.bashrc exits early on non-interactive shells (`[[ $- != *i* ]] && return`),
# so SSH invocations, cron, and systemd don't see the user's bash.d-derived
# PATH — including ~/.local/nodejs/bin, /opt/homebrew/bin, and the spartan
# EasyBuild node path. Pull in just the two files we need to get a fleet-
# wide consistent PATH without requiring an interactive shell.
# The sourced files include constructs (if_host tests, cleanup_path,
# references to optionally-unset vars like BASH_SOURCE in subshells,
# etc.) that trip `set -e`, `set -u`, and `pipefail`. Relax all three
# around the source block and restore them afterwards.
set +euo pipefail
for _src in \
    "${HOME}/.dotfiles/src/.bash.d/all/000_is.src" \
    "${HOME}/.dotfiles/src/.bash.d/all/001_ENV_PATH.src"; do
    if [[ -f "$_src" ]]; then
        # shellcheck disable=SC1090
        source "$_src" 2>/dev/null || true
    fi
done
set -euo pipefail
# Fallback: if the module command is available (spartan), try the nodejs
# module — this is how EasyBuild exposes node on the HPC login node.
if command -v module >/dev/null 2>&1 && ! command -v node >/dev/null 2>&1; then
    module load nodejs 2>/dev/null || true
fi
# macOS homebrew safety net — 001_ENV_PATH.src already does this but only
# when /opt/homebrew/bin/brew is executable; be belt-and-braces in case
# the file wasn't sourced for any reason.
if [[ -x /opt/homebrew/bin/brew ]] && ! command -v node >/dev/null 2>&1; then
    eval "$(/opt/homebrew/bin/brew shellenv)" 2>/dev/null || true
fi

# -- 1. Canonical hostname ----------------------------------------------------
# Resolution order (via shared/scripts/resolve-hostname helper):
#   1. $SCITEX_OROCHI_HOSTNAME env var (manual override)
#   2. hostname_aliases[$(hostname -s)] from shared/config.yaml
#   3. $(hostname -s) itself (identity fallback)

# -- Script root discovery ---------------------------------------------------
# Resolve this script's own dir (install/), then walk up to scripts/client.
# SCRIPTS_ROOT = .../scitex-orochi/scripts/client  (public, reusable)
# DOTFILES_ROOT = ~/.dotfiles/src/.scitex/orochi   (user-private, tracks
#                                                   host override agents
#                                                   and user-specific hooks)
_BOOTSTRAP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_ROOT="$(cd "${_BOOTSTRAP_DIR}/.." && pwd)"
DOTFILES_ROOT="${HOME}/.dotfiles/src/.scitex/orochi"
DEPLOY_ROOT="${HOME}/.scitex/orochi"

HOST="$("${SCRIPTS_ROOT}/resolve-hostname" 2>/dev/null || true)"
if [[ -z "$HOST" ]]; then
    HOST="${SCITEX_OROCHI_HOSTNAME:-$(hostname -s)}"
fi
if [[ -z "$HOST" ]]; then
    err "could not resolve hostname"
    exit 1
fi
log "canonical host: $HOST"
log "scripts root: $SCRIPTS_ROOT"

if [[ ! -d "$DOTFILES_ROOT" ]]; then
    warn "dotfiles root missing: $DOTFILES_ROOT — user-private host overrides will not apply"
fi
mkdir -p "$DEPLOY_ROOT"

# Runtime dirs live under $DEPLOY_ROOT/runtime/ (per 2026-04-17 layout). Each
# host regenerates these; contents are never committed. Created empty so
# first-time bootstrap doesn't fail when an agent tries to write a log
# before any heartbeat has landed. Agent *definitions* live in shared/agents/
# or <host>/agents/ (tracked source); they are NOT created here.
DEPLOY_RUNTIME_SUBDIRS=(
    runtime
    runtime/workspaces
    runtime/logs
    runtime/quota-telemetry
    runtime/tmux-unstick-state
    runtime/fleet-watch
    runtime/fleet-watch/machine-info
    runtime/fleet-watch/ping
    runtime/fleet-watch/connection
    runtime/fleet-watch/process-info
)

# -- 2. Deploy-side runtime dirs ---------------------------------------------

log "ensuring deployed runtime dirs under $DEPLOY_ROOT/runtime/"
for s in "${DEPLOY_RUNTIME_SUBDIRS[@]}"; do
    if [[ ! -d "$DEPLOY_ROOT/$s" ]]; then
        mkdir -p "$DEPLOY_ROOT/$s"
        log "created $DEPLOY_ROOT/$s"
    fi
done

# -- 2a. Legacy-path cleanup (pre-runtime/ layout) ---------------------------
# Earlier bootstrap versions created flat top-level runtime dirs
# (~/.scitex/orochi/{logs,fleet-watch,workspaces,quota-telemetry,tmux-unstick-state}).
# The canonical source-side symlinks pointing at these have been removed, but
# empty top-level real dirs may still exist from prior installs. Remove them
# if empty — keep if they still hold data (user can migrate manually).
for legacy_sub in logs fleet-watch quota-telemetry tmux-unstick-state workspaces agents; do
    legacy_path="$DEPLOY_ROOT/$legacy_sub"
    if [[ -L "$legacy_path" ]]; then
        # symlink leftover — safe to remove
        target="$(readlink "$legacy_path")"
        log "removing stale top-level symlink $legacy_path -> $target"
        rm -f "$legacy_path"
    elif [[ -d "$legacy_path" ]] && [[ -z "$(ls -A "$legacy_path" 2>/dev/null)" ]]; then
        log "removing empty legacy top-level dir $legacy_path"
        rmdir "$legacy_path"
    fi
done

# -- 2b. Clean up pre-restructure leftovers ----------------------------------
# Earlier bootstrap versions created per-host symlink stubs under
# $DOTFILES_ROOT/$HOST/{agents,workspaces,...} pointing at top-level dirs
# that no longer exist (now live under shared/). Those stubs block
# `git pull` when upstream deletes them. Clear them if they're all dead.
legacy_perhost="$DOTFILES_ROOT/$HOST"
if [[ -d "$legacy_perhost" ]]; then
    all_broken=1
    has_any=0
    # Enumerate both regular entries AND symlinks (even dangling ones).
    # A dangling symlink fails `-e`, so probe with `-L` as well, otherwise
    # the cleanup never triggers for the very case it was written for.
    shopt -s nullglob
    for entry in "$legacy_perhost"/* "$legacy_perhost"/.[!.]*; do
        [[ -e "$entry" || -L "$entry" ]] || continue
        has_any=1
        if [[ -L "$entry" && ! -e "$entry" ]]; then
            continue # dangling symlink — counts as broken
        fi
        all_broken=0
        break
    done
    shopt -u nullglob
    if ((has_any)) && ((all_broken)); then
        log "removing stale per-host stub dir $legacy_perhost (all symlinks dead)"
        rm -rf "$legacy_perhost"
    fi
fi

# -- 3. claude-hud install (optional) ----------------------------------------

install_claude_hud() {
    if ! command -v node >/dev/null 2>&1; then
        warn "node not on PATH; skipping claude-hud install (hub will show statusline=unset for this host)"
        return 0
    fi

    local hud_dir="${HOME}/proj/claude-hud"
    local dist="$hud_dir/dist/index.js"

    if [[ ! -d "$hud_dir/.git" ]]; then
        mkdir -p "$(dirname "$hud_dir")"
        log "cloning jarrodwatts/claude-hud -> $hud_dir"
        if ! git clone --quiet https://github.com/jarrodwatts/claude-hud.git "$hud_dir"; then
            err "git clone failed; skipping claude-hud setup"
            return 0
        fi
    fi

    # Build if dist is missing or older than src.
    local need_build=0
    if [[ ! -f "$dist" ]]; then
        need_build=1
    else
        # Bash-portable "any src file newer than dist" check.
        if [[ -n "$(find "$hud_dir/src" -newer "$dist" -print -quit 2>/dev/null || true)" ]]; then
            need_build=1
        fi
    fi

    if ((need_build)); then
        log "building claude-hud ($hud_dir)"
        (
            cd "$hud_dir"
            if [[ ! -d node_modules ]]; then
                npm install --silent --no-audit --no-fund || {
                    err "npm install failed; skipping build"
                    exit 1
                }
            fi
            if ! npm run build --silent; then
                err "npm run build failed"
                exit 1
            fi
        ) || return 0
    else
        log "claude-hud dist/ already up to date"
    fi

    # Wire statusLine into ~/.claude/settings.json (merge-safe).
    local settings="${HOME}/.claude/settings.json"
    local node_bin
    node_bin="$(command -v node)"
    local want_cmd="$node_bin $dist"

    mkdir -p "$(dirname "$settings")"
    if [[ ! -f "$settings" ]]; then
        printf '{}\n' >"$settings"
    fi

    python3 - "$settings" "$want_cmd" <<'PY'
import json, sys, pathlib
path = pathlib.Path(sys.argv[1])
want_cmd = sys.argv[2]
try:
    doc = json.loads(path.read_text())
except Exception:
    doc = {}
if not isinstance(doc, dict):
    doc = {}
sl = doc.get("statusLine")
cur_cmd = sl.get("command", "") if isinstance(sl, dict) else ""
# Preserve the user's existing statusLine when it already points at a
# claude-hud build — different hosts may reference a different node
# binary (/usr/bin/node vs ~/.local/nodejs/bin/node) and both work.
# We only (re)write when the entry is missing or points elsewhere.
if "claude-hud/dist/index.js" in cur_cmd:
    sys.exit(0)
doc["statusLine"] = {"type": "command", "command": want_cmd}
# Atomic-ish write so a concurrent Claude Code read sees either old or new,
# never a half-written file.
tmp = path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(doc, indent=2) + "\n")
tmp.replace(path)
print(f"[bootstrap-host] wrote statusLine -> {want_cmd}")
PY
}

install_claude_hud

# -- 4. Orchestration install (systemd user units on Linux) ------------------
# Canonical on-boot launcher + heartbeat pusher, shipped from
# shared/scripts/systemd/ with per-host substitution.

install_orchestration_systemd() {
    local os
    os="$(uname -s 2>/dev/null || echo unknown)"
    if [[ "$os" != "Linux" ]]; then
        log "orchestration: $os — systemd not applicable, using launchd path instead"
        return 0
    fi

    local templates="$SCRIPTS_ROOT/install/systemd"
    local unit_dir="${HOME}/.config/systemd/user"
    mkdir -p "$unit_dir"

    # Resolve required absolute paths.
    local sac_bin agent_meta
    sac_bin="$(command -v sac 2>/dev/null || true)"
    if [[ -z "$sac_bin" ]]; then
        # Probe canonical venv locations (bootstrap doesn't source bashrc so
        # PATH may be minimal). Order matches per-host conventions:
        #   WSL/spartan: ~/.env-3.11, ~/.venv-3.11, ~/.venv
        #   mba/nas:     ~/.venv, ~/.venv-3.11
        local candidate
        for candidate in \
            "${HOME}/.env-3.11/bin/sac" \
            "${HOME}/.venv-3.11/bin/sac" \
            "${HOME}/.venv/bin/sac" \
            "${HOME}/.env/bin/sac"; do
            if [[ -x "$candidate" ]]; then
                sac_bin="$candidate"
                log "sac resolved via venv probe: $sac_bin"
                break
            fi
        done
    fi
    if [[ -z "$sac_bin" ]]; then
        warn "sac not found on PATH or in canonical venvs; skipping systemd install"
        return 0
    fi
    agent_meta="$SCRIPTS_ROOT/collect_agent_metadata.py"
    if [[ ! -x "$agent_meta" ]]; then
        warn "collect_agent_metadata.py not executable at $agent_meta; skipping systemd install"
        return 0
    fi

    # Render a template to its deployed location, substituting tokens.
    _render_unit() {
        local src="$1"
        local dest="$2"
        sed \
            -e "s|@SAC@|$sac_bin|g" \
            -e "s|@AGENT_META@|$agent_meta|g" \
            -e "s|@CANONICAL_HOST@|$HOST|g" \
            "$src" >"$dest"
        log "rendered $dest"
    }

    _render_unit "$templates/orochi-fleet-start.service.template" \
        "$unit_dir/orochi-fleet-start.service"
    _render_unit "$templates/orochi-agent-meta-push.service.template" \
        "$unit_dir/orochi-agent-meta-push.service"
    _render_unit "$templates/orochi-agent-meta-push.timer.template" \
        "$unit_dir/orochi-agent-meta-push.timer"

    # Write env file if SCITEX_OROCHI_TOKEN is available in the bootstrap shell.
    local env_file="$unit_dir/orochi.env"
    if [[ -n "${SCITEX_OROCHI_TOKEN:-}" ]]; then
        umask 077
        printf 'SCITEX_OROCHI_TOKEN=%s\n' "$SCITEX_OROCHI_TOKEN" >"$env_file"
        log "wrote $env_file (mode 600)"
    elif [[ ! -f "$env_file" ]]; then
        warn "SCITEX_OROCHI_TOKEN unset; heartbeat push will be a no-op until $env_file is populated"
    fi

    # Retire any pre-2026-04-18 per-agent units that point at the dead
    # ~/.dotfiles/src/.scitex/orochi/agents/<name>/ path.
    for stale in "$unit_dir"/orochi-*.service; do
        [[ -f "$stale" ]] || continue
        case "$stale" in
        *orochi-fleet-start.service | *orochi-agent-meta-push.service) continue ;;
        esac
        if grep -q '/\.scitex/orochi/agents/' "$stale" 2>/dev/null; then
            log "retiring stale per-agent unit $(basename "$stale") (points at removed agents/<name>/ path)"
            systemctl --user disable --now "$(basename "$stale")" 2>/dev/null || true
            mv "$stale" "$stale.retired-$(date -u +%Y%m%d)"
        fi
    done

    # Reload + enable + start.
    systemctl --user daemon-reload 2>&1 | tail -2 || true
    systemctl --user enable --now orochi-agent-meta-push.timer 2>&1 | tail -2 || true
    systemctl --user enable --now orochi-fleet-start.service 2>&1 | tail -5 || true

    log "orchestration installed. Fleet start: systemctl --user status orochi-fleet-start"
}

install_sac_config_symlink() {
    # sac's hostname_aliases lookup reads ~/.scitex/agent-container/config.yaml.
    # Orochi's canonical config lives at ~/.scitex/orochi/shared/config.yaml
    # and carries the alias map. Symlink so both paths resolve to one file.
    local sac_root="${HOME}/.scitex/agent-container"
    local sac_cfg="$sac_root/config.yaml"
    local orochi_cfg="${HOME}/.scitex/orochi/shared/config.yaml"
    mkdir -p "$sac_root"
    if [[ -L "$sac_cfg" ]]; then
        return 0
    fi
    if [[ -f "$sac_cfg" ]]; then
        warn "$sac_cfg exists as a real file; leaving it alone"
        return 0
    fi
    if [[ -f "$orochi_cfg" ]]; then
        ln -s "$orochi_cfg" "$sac_cfg"
        log "symlinked $sac_cfg -> $orochi_cfg"
    fi
}

install_sac_config_symlink
install_orchestration_systemd

# -- 5. Orchestration install (launchd on macOS) ---------------------------

install_orchestration_launchd() {
    local os
    os="$(uname -s 2>/dev/null || echo unknown)"
    if [[ "$os" != "Darwin" ]]; then
        return 0
    fi

    local templates="$SCRIPTS_ROOT/install/launchd"
    local install_dir="${HOME}/Library/LaunchAgents"
    mkdir -p "$install_dir"
    mkdir -p "${HOME}/.scitex/agent-container/logs"

    # Resolve required absolute paths.
    local sac_bin agent_meta
    sac_bin="$(command -v sac 2>/dev/null || command -v scitex-agent-container 2>/dev/null || true)"
    if [[ -z "$sac_bin" ]]; then
        local candidate
        for candidate in \
            "${HOME}/.venv/bin/sac" \
            "${HOME}/.venv-3.11/bin/sac" \
            "${HOME}/.venv/bin/scitex-agent-container" \
            "${HOME}/.venv-3.11/bin/scitex-agent-container"; do
            if [[ -x "$candidate" ]]; then
                sac_bin="$candidate"
                log "sac resolved via venv probe: $sac_bin"
                break
            fi
        done
    fi
    if [[ -z "$sac_bin" ]]; then
        warn "sac not found; skipping launchd install"
        return 0
    fi
    agent_meta="$SCRIPTS_ROOT/collect_agent_metadata.py"
    if [[ ! -x "$agent_meta" ]]; then
        warn "collect_agent_metadata.py not executable at $agent_meta; skipping launchd install"
        return 0
    fi

    _render_plist() {
        local src="$1"
        local dest="$2"
        sed \
            -e "s|@SAC@|$sac_bin|g" \
            -e "s|@AGENT_META@|$agent_meta|g" \
            -e "s|@CANONICAL_HOST@|$HOST|g" \
            -e "s|@HOME@|$HOME|g" \
            "$src" >"$dest"
        log "rendered $dest"
    }

    local fleet_start_plist="$install_dir/com.scitex.orochi.fleet-start.plist"
    local meta_push_plist="$install_dir/com.scitex.orochi.agent-meta-push.plist"

    _render_plist "$templates/com.scitex.orochi.fleet-start.plist.template" "$fleet_start_plist"
    _render_plist "$templates/com.scitex.orochi.agent-meta-push.plist.template" "$meta_push_plist"

    # Retire any pre-2026-04-18 per-agent plists that point at the dead
    # ~/.dotfiles/src/.scitex/orochi/agents/<name>/ flat path.
    for stale in "$install_dir"/com.scitex.orochi.*.plist; do
        [[ -f "$stale" ]] || continue
        case "$stale" in
        *com.scitex.orochi.fleet-start.plist | *com.scitex.orochi.agent-meta-push.plist) continue ;;
        esac
        if grep -q '/\.scitex/orochi/agents/' "$stale" 2>/dev/null; then
            local label
            label="$(basename "$stale" .plist)"
            log "retiring stale per-agent plist $label (points at removed agents/<name>/ path)"
            launchctl bootout "gui/$(id -u)" "$stale" 2>/dev/null || true
            mv "$stale" "$stale.retired-$(date -u +%Y%m%d)"
        fi
    done

    # Load/reload each plist. bootstrap replaces bootout-then-bootstrap so a
    # second bootstrap run picks up template edits.
    for p in "$fleet_start_plist" "$meta_push_plist"; do
        launchctl bootout "gui/$(id -u)" "$p" 2>/dev/null || true
        launchctl bootstrap "gui/$(id -u)" "$p" 2>&1 | tail -3 || true
        launchctl enable "gui/$(id -u)/$(basename "$p" .plist)" 2>/dev/null || true
    done

    log "launchd orchestration installed. status: launchctl list | grep scitex.orochi"
}

install_orchestration_launchd

log "done. host=$HOST deploy=$DEPLOY_ROOT/"
