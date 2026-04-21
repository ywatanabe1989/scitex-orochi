#!/usr/bin/env bash
# disk-reaper.sh — reap known-safe caches to free Mac/Linux host disk
# -----------------------------------------------------------------------------
# Authored by healer-mba 2026-04-21 for issue #286 item 1, following the
# 2026-04-21 mba full-disk incident (see skills/infra-hub-docker-disk-full).
#
# Usage:
#   disk-reaper.sh                       # dry-run, list reapable targets + sizes
#   disk-reaper.sh --dry-run             # explicit dry-run (default)
#   disk-reaper.sh --yes                 # actually delete the safe-default targets
#   disk-reaper.sh --yes --only chrome   # delete only Chrome code_sign_clone cache
#   disk-reaper.sh --list                # print known target names and exit
#
# Target categories:
#   safe-default   Deleted when --yes given, no further flag needed.
#                  Known-safe caches that regenerate automatically.
#   opt-in         Requires --include <name> in addition to --yes.
#                  Large user-data-adjacent (e.g. gradle cache — rebuilds
#                  from pom/gradle files; safe but slow on next build).
#   never-auto     Not touched by this script. Human-only (~/Downloads,
#                  ~/Library/Developer/Xcode/Archives, etc.) — listed in
#                  advisory body so the user can decide.
#
# Side effects: only when --yes. Never deletes user data. Never calls
# `docker prune` (daemon may be wedged on a full disk; that's the job of
# infra-hub-docker-disk-full skill and colima restart, not this reaper).
# -----------------------------------------------------------------------------

set -u
set -o pipefail

HOST="$(hostname -s 2>/dev/null || hostname)"
OS="$(uname -s)"

dry_run=1
include=()
only=""
do_list=0

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) dry_run=1; shift ;;
    --yes|-y)  dry_run=0; shift ;;
    --only)    only="$2"; shift 2 ;;
    --include) include+=("$2"); shift 2 ;;
    --list)    do_list=1; shift ;;
    -h|--help)
      sed -n '2,30p' "$0"; exit 0 ;;
    *) printf 'unknown arg: %s\n' "$1" >&2; exit 64 ;;
  esac
done

# -----------------------------------------------------------------------------
# Target registry. One entry = one row in the rows[] array.
#
# Columns (tab-separated, 4 fields):
#   name           short identifier for --only / --include
#   category       safe-default | opt-in | never-auto
#   finder         shell snippet printing newline-separated paths to reap
#   description    one-line reason it's safe/unsafe to reap
# -----------------------------------------------------------------------------

rows=()

# Chrome codesign cache — 13G observed in 2026-04-21 incident. Regenerates.
# macOS-only. Path pattern: /private/var/folders/*/*/X/com.google.Chrome.code_sign_clone
rows+=("chrome-code-sign-clone	safe-default	find /private/var/folders -maxdepth 5 -type d -name 'com.google.Chrome.code_sign_clone' 2>/dev/null	macOS Chrome codesign cache leak — regenerates on next launch")

# Claude Code stale tmp dirs. Our own harness output dirs. Keep recent 2 days.
rows+=("claude-tmp-stale	safe-default	find /private/tmp/claude-${UID:-501} -maxdepth 1 -type d -mtime +2 2>/dev/null	Claude Code tool-output dirs older than 2d — stale session artefacts")

# iOS DeviceSupport — symbols cache, regenerates from attached devices.
rows+=("ios-device-support	safe-default	find \"\$HOME/Library/Developer/Xcode/iOS DeviceSupport\" -mindepth 1 -maxdepth 1 -type d -mtime +30 2>/dev/null	Xcode iOS DeviceSupport older than 30d — regenerates")

# Xcode DerivedData — build products, regenerates. Safe but slow rebuild.
rows+=("xcode-derived-data	safe-default	find \"\$HOME/Library/Developer/Xcode/DerivedData\" -mindepth 1 -maxdepth 1 -type d 2>/dev/null	Xcode DerivedData — rebuilds on next Xcode build")

# Simulator caches (not user data, regenerate)
rows+=("core-simulator-caches	safe-default	find \"\$HOME/Library/Developer/CoreSimulator/Caches\" -mindepth 1 -maxdepth 2 2>/dev/null	CoreSimulator caches — regenerate")

# .gradle caches (rebuild on next gradle invocation; slow but automatic).
rows+=("gradle-caches	opt-in	printf '%s\\n' \"\$HOME/.gradle/caches\" \"\$HOME/.gradle/daemon\"	Gradle caches — regenerate on next build (multi-minute first-build cost)")

# .bundle / .rbenv / .npm / .bun caches — opt-in, regenerate but break dev reproducibility briefly.
rows+=("npm-cache	opt-in	printf '%s\\n' \"\$HOME/.npm/_cacache\"	npm cache — regenerates on next install")
rows+=("bun-install-cache	opt-in	printf '%s\\n' \"\$HOME/.bun/install/cache\"	bun install cache — regenerates")

# Trash — user action required.
rows+=("trash	never-auto	printf '%s\\n' \"\$HOME/.Trash\"	User Trash — emptying is a user decision")

# Downloads — user data.
rows+=("downloads-note	never-auto	printf ''	~/Downloads is user data; not touched by this script")

# ----------------- end of registry -----------------

if [ "$do_list" -eq 1 ]; then
  printf '%-26s  %-13s  %s\n' "name" "category" "description"
  printf '%-26s  %-13s  %s\n' "----" "--------" "-----------"
  for row in "${rows[@]}"; do
    IFS=$'\t' read -r name category _finder desc <<< "$row"
    printf '%-26s  %-13s  %s\n' "$name" "$category" "$desc"
  done
  exit 0
fi

# Reap loop.
total_reclaim_kib=0
reaped_any=0

should_process() {
  # $1=name $2=category
  local n="$1" cat="$2"
  if [ -n "$only" ]; then
    [ "$n" = "$only" ]
    return $?
  fi
  if [ "$cat" = "safe-default" ]; then
    return 0
  fi
  if [ "$cat" = "opt-in" ]; then
    local inc
    for inc in "${include[@]:-}"; do
      [ "$inc" = "$n" ] && return 0
    done
    return 1
  fi
  # never-auto: only if --only exactly matches (still informational)
  return 1
}

size_kib_of() {
  # Sum sizes of stdin-listed paths; missing paths contribute 0.
  local p kib=0 line
  while IFS= read -r p; do
    [ -z "$p" ] && continue
    [ ! -e "$p" ] && continue
    line="$(du -sk -- "$p" 2>/dev/null | awk '{print $1}')"
    [ -n "$line" ] && kib=$(( kib + line ))
  done
  printf '%s' "$kib"
}

human_size() {
  # KiB → human.
  local kib="$1"
  if [ "$kib" -ge 1048576 ]; then
    awk -v k="$kib" 'BEGIN{printf "%.1fG", k/1048576}'
  elif [ "$kib" -ge 1024 ]; then
    awk -v k="$kib" 'BEGIN{printf "%.1fM", k/1024}'
  else
    printf '%dK' "$kib"
  fi
}

printf '# disk-reaper on %s (%s) — mode=%s\n' \
  "$HOST" "$OS" "$([ "$dry_run" -eq 1 ] && echo dry-run || echo REAP)"
printf '%-26s  %-13s  %10s  %s\n' "name" "category" "size" "description"
printf '%-26s  %-13s  %10s  %s\n' "----" "--------" "----" "-----------"

for row in "${rows[@]}"; do
  IFS=$'\t' read -r name category finder desc <<< "$row"

  paths="$(eval "$finder" 2>/dev/null || true)"
  kib="$(printf '%s\n' "$paths" | size_kib_of)"
  size_h="$(human_size "$kib")"

  printf '%-26s  %-13s  %10s  %s\n' "$name" "$category" "$size_h" "$desc"

  if should_process "$name" "$category"; then
    if [ "$dry_run" -eq 1 ]; then
      if [ -n "$paths" ]; then
        printf '%s\n' "$paths" | sed 's/^/    (dry-run) would rm -rf /'
      fi
    else
      if [ -z "$paths" ]; then
        continue
      fi
      while IFS= read -r p; do
        [ -z "$p" ] && continue
        [ ! -e "$p" ] && continue
        rm -rf -- "$p" && printf '    reaped: %s\n' "$p"
      done <<< "$paths"
      reaped_any=1
      total_reclaim_kib=$(( total_reclaim_kib + kib ))
    fi
  fi
done

if [ "$dry_run" -eq 1 ]; then
  printf '\n# dry-run complete. Re-run with --yes to reap safe-default targets.\n'
  printf '# Use --include <name> to add opt-in targets (e.g. --include gradle-caches).\n'
  exit 0
fi

if [ "$reaped_any" -eq 1 ]; then
  printf '\n# reaped ~%s total. Disk state after:\n' "$(human_size "$total_reclaim_kib")"
  df -h / 2>/dev/null | awk 'NR<=2'
else
  printf '\n# nothing reaped (empty targets).\n'
fi
