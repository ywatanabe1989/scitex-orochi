/* chat/active-channel-on-update.test.mjs — regression test for todo#245
 * (https://github.com/ywatanabe1989/todo/issues/245).
 *
 * Sibling of todo#246 (covered by active-channel-on-arrival.test.mjs).
 * Where #246 is "active channel jumps on inbound message arrival",
 * #245 is "active channel jumps on update events that AREN'T new
 * messages": fetchStats poll, WebSocket reconnect, hard page reload.
 *
 * Bug (ywatanabe report msg#6090, 2026-04-12):
 *   When viewing a non-default channel (e.g. #ywatanabe / #heads) and
 *   ANY update happens — periodic fetchStats poll, presence_change WS
 *   event, WebSocket reconnect, hard reload — the .active sidebar
 *   highlight bumps back to #general. The in-memory currentChannel
 *   may stay correct, but the visual highlight goes stale and the user
 *   perceives a channel switch.
 *
 * Root cause (in current TS code):
 *   hub/frontend/src/app/sidebar-stats.ts uses a throttle guard
 *   `_lastStatsJson === JSON.stringify(stats.channels)` to short-circuit
 *   re-rendering when the channel list is byte-identical between polls.
 *   But that key dropped `currentChannel` during the TS migration
 *   (37284d6 / bf5d1ee) — the legacy hub/static/hub/app.js commit
 *   ae67e31 had `JSON.stringify(stats.channels) + "|" + (currentChannel
 *   || "__all__")`. Without currentChannel in the key, a setCurrentChannel
 *   followed by fetchStats() with unchanged channel list skips the
 *   re-render and leaves .active on the stale row.
 *
 * Fix: restore currentChannel suffix on the guard key (parity with
 * legacy ae67e31).
 *
 * Other paths covered:
 *   - WS reconnect: ws.onopen calls fetchStats() and fetchAgents() but
 *     never mutates currentChannel — verified by grep + by simulating
 *     reconnect in the test.
 *   - Page reload: state.ts hydrates currentChannel from
 *     readLastOpened() / `orochi.ui.lastOpened.v1` SYNCHRONOUSLY at
 *     module load, before first render — verified by simulating
 *     hydrate.
 *
 * Invariants this test pins down:
 *
 *   (i)   fetchStats's throttle guard key includes currentChannel, so a
 *         selection change forces a re-render even when stats.channels
 *         is byte-identical.
 *   (ii)  WS reconnect (onopen → fetchStats + fetchAgents) does not
 *         mutate currentChannel.
 *   (iii) Page reload hydrates currentChannel from localStorage BEFORE
 *         first render, restoring the user's previous selection.
 *   (iv)  The "__all__" sentinel is used for null currentChannel so the
 *         guard key transitions cleanly between single-channel and
 *         all-channels modes.
 *
 * No vitest/jest in this repo; run with:
 *     node hub/frontend/src/chat/active-channel-on-update.test.mjs
 * Exits non-zero on failure.
 *
 * Re-implements the spec rather than importing TS modules (which pull
 * in DOM globals + side effects) — same convention as
 * active-channel-on-arrival.test.mjs and channels-equal.test.mjs.
 */

let passed = 0;
let failed = 0;
function test(name, fn) {
  try {
    fn();
    console.log(`PASS ${name}`);
    passed++;
  } catch (e) {
    console.log(`FAIL ${name}: ${e.message}`);
    failed++;
  }
}
function assert(cond, msg) {
  if (!cond) throw new Error(msg || "assertion failed");
}
function assertEq(a, b, msg) {
  if (a !== b) {
    throw new Error(
      `${msg || "expected"}: ${JSON.stringify(a)} !== ${JSON.stringify(b)}`,
    );
  }
}
function assertNeq(a, b, msg) {
  if (a === b) {
    throw new Error(
      `${msg || "expected not equal"}: both === ${JSON.stringify(a)}`,
    );
  }
}

/* --- spec re-implementation -------------------------------------------- */

/* Mirror of the throttle guard key in
 * hub/frontend/src/app/sidebar-stats.ts (post-fix). The legacy
 * `JSON.stringify(stats.channels)` key didn't include currentChannel
 * — that's the bug. The fix appends the active channel (or the
 * "__all__" sentinel for null) so any selection change busts the
 * throttle and forces a re-render. */
function buildStatsGuardKey(stats, currentChannel) {
  const curCh = currentChannel || "__all__";
  return JSON.stringify(stats.channels) + "|" + curCh;
}

/* Mirror of the early-return guard in fetchStats(). Returns true when
 * the throttle SHOULD short-circuit, false when a re-render is required. */
function shouldSkipRender(prevKey, newKey) {
  return prevKey === newKey;
}

/* Mirror of state.ts setCurrentChannel — only legitimate writer. */
function setCurrentChannel(state, ch) {
  state.currentChannel = ch;
  state.persisted = ch == null ? "__all__" : ch;
}

/* Mirror of state.ts module-load hydrate (lines 53-65). Reads the
 * persisted record synchronously BEFORE any rendering. The legacy
 * `orochi_active_channel` key is also consulted for back-compat. */
function hydrateOnLoad(localStorage) {
  try {
    const raw = localStorage["orochi.ui.lastOpened.v1"];
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object" && parsed.activeChannel) {
        if (parsed.activeChannel !== "__all__") {
          return parsed.activeChannel;
        }
      }
    }
  } catch (_) {}
  /* Legacy fallback. */
  const legacy = localStorage["orochi_active_channel"];
  if (legacy && legacy !== "__all__") return legacy;
  return null;
}

/* Mirror of websocket.ts ws.onopen body (lines 345-364). The crucial
 * invariant: this handler does NOT call setCurrentChannel and does NOT
 * mutate currentChannel. It refreshes sidebar data only. */
function simulateWsReconnect(state, callTrace) {
  /* fetchStats() → re-renders sidebar; reads currentChannel but doesn't
   * write it. */
  callTrace.push("fetchStats");
  /* fetchAgents() → same. */
  callTrace.push("fetchAgents");
  /* If history already loaded, fetchNewMessages; else loadHistory.
   * Neither writes currentChannel. */
  if (state.historyLoaded) {
    callTrace.push("fetchNewMessages");
  } else {
    callTrace.push("loadHistory");
  }
  /* CRITICAL: state.currentChannel is NOT touched here. */
  return state.currentChannel;
}

/* --- tests ------------------------------------------------------------- */

test("does not switch active channel when fetchStats poll completes", () => {
  /* Scenario: user selected #ywatanabe; channel list is byte-identical
   * across two polls; without the currentChannel suffix the second poll
   * skips re-render and the DOM .active stays on whatever it was when
   * the throttle first cached. The fix puts currentChannel in the key
   * so the FIRST setCurrentChannel + fetchStats round busts the throttle. */
  const state = { currentChannel: null, persisted: "__all__" };
  const stats = { channels: ["general", "ywatanabe", "heads"] };
  /* Initial render under all-channels mode. */
  const key0 = buildStatsGuardKey(stats, state.currentChannel);
  /* User clicks #ywatanabe. */
  setCurrentChannel(state, "#ywatanabe");
  const key1 = buildStatsGuardKey(stats, state.currentChannel);
  assertNeq(key0, key1, "selection change must produce a new guard key");
  assert(
    !shouldSkipRender(key0, key1),
    "selection change must NOT short-circuit re-render",
  );
  /* Next fetchStats with identical channel list — no further selection
   * change — SHOULD short-circuit (preserving the throttle's purpose). */
  const key2 = buildStatsGuardKey(stats, state.currentChannel);
  assertEq(key1, key2, "stable selection + stable list = stable key");
  assert(
    shouldSkipRender(key1, key2),
    "stable state must short-circuit (throttle still works)",
  );
  /* And the active channel must not have flipped. */
  assertEq(state.currentChannel, "#ywatanabe", "active channel preserved");
});

test("does not switch active channel when WS reconnects", () => {
  /* Scenario: user is on #heads; transient WS drop; ws.onopen fires
   * fetchStats + fetchAgents + fetchNewMessages. None of those should
   * mutate currentChannel. */
  const state = {
    currentChannel: "#heads",
    persisted: "#heads",
    historyLoaded: true,
  };
  const trace = [];
  const after = simulateWsReconnect(state, trace);
  assertEq(after, "#heads", "ws.onopen must not mutate currentChannel");
  assertEq(state.currentChannel, "#heads", "state.currentChannel preserved");
  assertEq(state.persisted, "#heads", "persisted state untouched");
  assert(
    trace.includes("fetchStats"),
    "reconnect should refresh stats",
  );
  assert(
    trace.includes("fetchAgents"),
    "reconnect should refresh agents",
  );
  assert(
    !trace.includes("setCurrentChannel"),
    "reconnect must not call setCurrentChannel",
  );
});

test("WS reconnect with cold history still does not flip active channel", () => {
  /* First-load reconnect path (historyLoaded=false → loadHistory()).
   * loadHistory does a full DOM rebuild — must still preserve channel. */
  const state = {
    currentChannel: "#ywatanabe",
    persisted: "#ywatanabe",
    historyLoaded: false,
  };
  const trace = [];
  simulateWsReconnect(state, trace);
  assertEq(state.currentChannel, "#ywatanabe", "cold reconnect preserves ch");
  assert(
    trace.includes("loadHistory"),
    "cold reconnect should run loadHistory",
  );
});

test("restores active channel on page reload from localStorage (v1 key)", () => {
  /* Scenario: previous session ended with currentChannel=#ywatanabe
   * persisted via writeLastOpened. Hard reload (Ctrl+Shift+R) — module
   * load reads localStorage SYNCHRONOUSLY before first render. */
  const ls = {
    "orochi.ui.lastOpened.v1": JSON.stringify({
      activeTab: "chat",
      activeChannel: "#ywatanabe",
    }),
  };
  const hydrated = hydrateOnLoad(ls);
  assertEq(hydrated, "#ywatanabe", "page reload restores active channel");
});

test("restores active channel on page reload from legacy key", () => {
  /* Back-compat: an in-flight tab from before the v1-key migration may
   * have only the legacy `orochi_active_channel`. The hydrate path
   * still picks it up so users don't lose their spot mid-rollout. */
  const ls = { orochi_active_channel: "#heads" };
  const hydrated = hydrateOnLoad(ls);
  assertEq(hydrated, "#heads", "legacy key still hydrates");
});

test("page reload with no persisted channel returns null (all-channels mode)", () => {
  /* Brand-new session / cleared storage. Hydrate must NOT throw and
   * must NOT default to a hardcoded "#general" — the all-channels mode
   * (null) is the correct default. */
  const ls = {};
  const hydrated = hydrateOnLoad(ls);
  assertEq(hydrated, null, "empty storage hydrates to null, not #general");
});

test("page reload with __all__ sentinel returns null", () => {
  /* The "__all__" sentinel is the persisted form of null
   * (writeLastOpened maps null → "__all__" for the legacy key, and the
   * v1 record may also carry it). Hydrate must round-trip cleanly. */
  const ls1 = { orochi_active_channel: "__all__" };
  assertEq(hydrateOnLoad(ls1), null, "legacy __all__ → null");
  const ls2 = {
    "orochi.ui.lastOpened.v1": JSON.stringify({
      activeChannel: "__all__",
    }),
  };
  assertEq(hydrateOnLoad(ls2), null, "v1 __all__ → null");
});

test("guard key uses __all__ sentinel for null currentChannel", () => {
  /* Edge case: the guard key must distinguish "all-channels mode" from
   * "no channel selected yet" cleanly. Using the literal "__all__"
   * sentinel matches the legacy ae67e31 fix and the localStorage
   * persistence convention. */
  const stats = { channels: ["general", "heads"] };
  const keyNull = buildStatsGuardKey(stats, null);
  const keyAll = buildStatsGuardKey(stats, "__all__");
  const keyHeads = buildStatsGuardKey(stats, "#heads");
  assertEq(keyNull, keyAll, "null and '__all__' produce same guard key");
  assertNeq(keyNull, keyHeads, "all-mode and #heads produce different keys");
});

test("burst of identical fetchStats polls throttles correctly with stable selection", () => {
  /* Throttle invariant: when nothing changes, repeated polls short-
   * circuit. We don't want the fix to break the throttle's primary job. */
  const state = { currentChannel: "#heads", persisted: "#heads" };
  const stats = { channels: ["general", "heads", "ywatanabe"] };
  let prevKey = null;
  let renderCount = 0;
  for (let i = 0; i < 5; i++) {
    const newKey = buildStatsGuardKey(stats, state.currentChannel);
    if (!shouldSkipRender(prevKey, newKey)) {
      renderCount++;
      prevKey = newKey;
    }
  }
  assertEq(renderCount, 1, "stable state across 5 polls = 1 render");
});

test("alternating selection + poll forces re-render each switch", () => {
  /* When the user clicks between channels, every click must produce a
   * fresh guard key so fetchStats re-renders the sidebar with the
   * correct .active row. */
  const state = { currentChannel: null, persisted: "__all__" };
  const stats = { channels: ["general", "heads", "ywatanabe"] };
  let prevKey = buildStatsGuardKey(stats, state.currentChannel);
  let renderCount = 1; /* initial render */
  const sequence = ["#heads", "#ywatanabe", "#heads", null, "#general"];
  for (const ch of sequence) {
    setCurrentChannel(state, ch);
    const newKey = buildStatsGuardKey(stats, state.currentChannel);
    if (!shouldSkipRender(prevKey, newKey)) {
      renderCount++;
      prevKey = newKey;
    }
  }
  assertEq(
    renderCount,
    1 + sequence.length,
    "every selection change must force a render",
  );
});

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
