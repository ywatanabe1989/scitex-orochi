#!/usr/bin/env bash
# test_tmux_unstick_stability.sh
# -----------------------------------------------------------------------------
# Regression test for scitex-orochi#155 — Safety B (two-sample stability)
# of `tmux-unstick.sh` was a no-op in v2.0 because the stamp files were
# overwritten on every sweep, resetting their mtime, so prior_age never
# reached STABILITY_SEC.
#
# This test exercises the full --once path with a mocked `tmux` binary
# placed first on PATH, so no real tmux server is required and the test
# runs in any CI / sandbox environment.
#
# To eliminate wall-clock flakiness, the test backdates the stamp_hash
# file directly (`touch -d`) between sweeps to deterministically
# simulate "STABILITY_SEC has elapsed since the prior observation".
# This isolates the stability-check logic from real-time scheduling.
#
# Five assertions:
#
#   1. Sweep 1 against fresh state writes both stamp files and emits
#      a `first-sighting` event without firing recovery.
#   2. Sweep 2 immediately after sweep 1 (prior_age ~= 0 << STABILITY_SEC)
#      preserves the stamp mtime EXACTLY (the v2.1 fix for #155 — v2.0
#      would reset it because it overwrote the stamp on every match).
#   3. Sweep 2 also does not fire recovery (still first-sighting).
#   4. After backdating stamp_hash mtime to >= STABILITY_SEC ago, the
#      next sweep graduates to `stable-match` AND emits a `fired` event.
#   5. The fired event triggers a real `send-keys Enter` call (caught
#      via the mock tmux), and the per-pane cooldown stamp is created.
#
# Run:
#
#   bash deployment/fleet/test_tmux_unstick_stability.sh
#
# Exit codes:
#   0  all assertions pass
#   1  any assertion fails (with a `FAIL: ...` line on stderr)
#   2  setup error
# -----------------------------------------------------------------------------

set -u
set -o pipefail

UNSTICK_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/tmux-unstick.sh"
[[ -x "$UNSTICK_SCRIPT" ]] || { echo "setup error: $UNSTICK_SCRIPT not executable" >&2; exit 2; }

TESTDIR="$(mktemp -d "${TMPDIR:-/tmp}/tmux-unstick-stability-test.XXXXXX")"
trap 'rm -rf "$TESTDIR"' EXIT

mkdir -p "$TESTDIR/state" "$TESTDIR/log" "$TESTDIR/mock_bin"

# Mock tmux: list-panes returns one fake pane, capture-pane returns a
# tail that matches the paste-buffer-unsent regex, send-keys is a no-op
# that records what was "sent" so we can inspect it.
cat > "$TESTDIR/mock_bin/tmux" <<'MOCK_TMUX'
#!/usr/bin/env bash
case "$1" in
  list-panes)
    # tmux list-panes -a -F '#{pane_id}|#{session_name}:#{window_index}.#{pane_index}'
    printf '%%99|fake-session:0.0\n'
    ;;
  capture-pane)
    # Always return the same tail so the (pattern, hash) is identical
    # across sweeps. The 4th line matches the paste-buffer-unsent regex
    # at prompt level.
    cat <<'PANE'
old line 1
old line 2
────────────────────────────────────────────────────────────────────────────────
❯ [Pasted text #1 +5 lines]
────────────────────────────────────────────────────────────────────────────────
PANE
    ;;
  send-keys)
    # Record the keystroke for assertion. The args are e.g. "-t %99 Enter"
    # or "-t %99 2 Enter".
    printf 'SEND-KEYS %s\n' "$*" >> "$TMUX_UNSTICK_TEST_SENT_KEYS"
    ;;
  *)
    # Unhandled subcommand — exit 0 so the script does not abort.
    :
    ;;
esac
exit 0
MOCK_TMUX
chmod +x "$TESTDIR/mock_bin/tmux"

export PATH="$TESTDIR/mock_bin:$PATH"
export TMUX_UNSTICK_LOG="$TESTDIR/log/test.ndjson"
export TMUX_UNSTICK_STATE_DIR="$TESTDIR/state"
export TMUX_UNSTICK_COOLDOWN_SEC=60
export TMUX_UNSTICK_STABILITY_SEC=120                    # production default
export TMUX_UNSTICK_TEST_SENT_KEYS="$TESTDIR/sent_keys.log"
unset TMUX_PANE                                          # ensure self-exclusion does not skip our fake pane

PASS=0
FAIL=0

ok() { printf 'PASS: %s\n' "$1"; PASS=$(( PASS + 1 )); }
ng() { printf 'FAIL: %s\n' "$1" >&2; FAIL=$(( FAIL + 1 )); }

STAMP_PAT="$TESTDIR/state/_99.pattern"
STAMP_HASH="$TESTDIR/state/_99.hash"
STAMP_COOL="$TESTDIR/state/_99.cooldown"

# ---------- Sweep 1: first sighting on fresh state ----------
bash "$UNSTICK_SCRIPT" --once >/dev/null 2>&1 || { ng "sweep 1 exited non-zero"; }

if grep -q '"event":"first-sighting"' "$TMUX_UNSTICK_LOG"; then
  ok "sweep 1 emitted first-sighting"
else
  ng "sweep 1 did not emit first-sighting"
fi

if [[ -f "$STAMP_PAT" && -f "$STAMP_HASH" ]]; then
  ok "sweep 1 wrote both stamp files"
else
  ng "sweep 1 did not write stamp files"
fi

if [[ ! -s "$TMUX_UNSTICK_TEST_SENT_KEYS" ]]; then
  ok "sweep 1 sent no keys (correct: not yet stable)"
else
  ng "sweep 1 incorrectly sent keys before stability"
fi

MTIME_AFTER_SWEEP_1=$(stat -c %Y "$STAMP_HASH" 2>/dev/null || echo "")
[[ -n "$MTIME_AFTER_SWEEP_1" ]] || { ng "sweep 1 stamp mtime unreadable"; }

# ---------- Sweep 2: same observation, well within STABILITY_SEC ----------
# No sleep — production default STABILITY_SEC=120 is far longer than
# the wall time between two back-to-back script invocations, so this
# sweep MUST observe `prior_age << STABILITY_SEC` and stay in
# first-sighting (stamp mtime preserved).
bash "$UNSTICK_SCRIPT" --once >/dev/null 2>&1 || { ng "sweep 2 exited non-zero"; }

MTIME_AFTER_SWEEP_2=$(stat -c %Y "$STAMP_HASH" 2>/dev/null || echo "")
if [[ -n "$MTIME_AFTER_SWEEP_2" && "$MTIME_AFTER_SWEEP_1" == "$MTIME_AFTER_SWEEP_2" ]]; then
  ok "sweep 2 PRESERVED stamp mtime (the v2.1 fix for #155)"
else
  ng "sweep 2 RESET stamp mtime ($MTIME_AFTER_SWEEP_1 -> $MTIME_AFTER_SWEEP_2) — v2.0 bug regression"
fi

if [[ ! -s "$TMUX_UNSTICK_TEST_SENT_KEYS" ]]; then
  ok "sweep 2 sent no keys (correct: not yet stable)"
else
  ng "sweep 2 incorrectly sent keys before stability"
fi

# ---------- Sweep 3: backdate stamp_hash to simulate STABILITY_SEC elapsed ----------
# This is the deterministic substitute for "wait STABILITY_SEC seconds
# of wall time" — it touches the stamp file mtime to a moment far
# enough in the past that prior_age >= STABILITY_SEC on the next
# sweep. The pattern file mtime does not matter (the script only
# reads stat %Y on stamp_hash).
BACKDATED_TIME=$(( MTIME_AFTER_SWEEP_1 - TMUX_UNSTICK_STABILITY_SEC - 5 ))
touch -d "@$BACKDATED_TIME" "$STAMP_HASH" 2>/dev/null || {
  ng "could not backdate stamp_hash mtime via touch -d @epoch"
}

bash "$UNSTICK_SCRIPT" --once >/dev/null 2>&1 || { ng "sweep 3 exited non-zero"; }

if grep -q '"event":"stable-match"' "$TMUX_UNSTICK_LOG"; then
  ok "sweep 3 graduated to stable-match"
else
  ng "sweep 3 did not graduate to stable-match (Safety B still broken)"
fi

if grep -q '"event":"fired"' "$TMUX_UNSTICK_LOG"; then
  ok "sweep 3 emitted fired event"
else
  ng "sweep 3 did not emit fired event"
fi

if grep -q 'SEND-KEYS .*Enter' "$TMUX_UNSTICK_TEST_SENT_KEYS"; then
  ok "sweep 3 actually called tmux send-keys (recovery action ran)"
else
  ng "sweep 3 did not call tmux send-keys"
fi

if [[ -f "$STAMP_COOL" ]]; then
  ok "sweep 3 created the per-pane cooldown stamp"
else
  ng "sweep 3 did not create the cooldown stamp"
fi

printf '\n--- summary: %d passed, %d failed ---\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]
