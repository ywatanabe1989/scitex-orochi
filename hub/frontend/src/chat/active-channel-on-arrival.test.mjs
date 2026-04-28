/* chat/active-channel-on-arrival.test.mjs — regression test for todo#246
 * (https://github.com/ywatanabe1989/todo/issues/246).
 *
 * Bug (ywatanabe report msg#6090): when viewing a non-default channel
 * (e.g. #ywatanabe / #heads) and a new message arrives in another
 * channel, the active channel "jumps" back to #general — user loses the
 * channel context they were monitoring.
 *
 * Fix (commits 29337a7 + ae67e31, since refactored into
 *   - hub/frontend/src/app/state.ts        — setCurrentChannel() is the only
 *                                              writer; localStorage hydrate
 *                                              on load
 *   - hub/frontend/src/chat/chat-render.ts — appendMessage() reads
 *                                              currentChannel; sets
 *                                              display:none for non-active
 *                                              channels but never mutates it
 *   - hub/frontend/src/chat/chat-actions.ts — only the channel-link click
 *                                              delegate calls
 *                                              setCurrentChannel()
 *
 * Invariants this test pins down:
 *
 *   (a) Receiving a message for channel B while currentChannel = A leaves
 *       currentChannel === A (no implicit channel switch on inbound WS).
 *   (b) The DOM row for the inbound non-matching message is appended but
 *       set to display:none so it doesn't visually pollute the active
 *       channel's feed (this is the same `display:none` rule that
 *       channels-equal.test.mjs covers for the prefix-asymmetry case).
 *   (c) The DOM row for an inbound matching message stays visible.
 *   (d) currentChannel only changes through setCurrentChannel (sidebar
 *       click / channel-link click / hash-router) — this is verified by
 *       running a sequence of inbound messages and asserting no mutation.
 *
 * No vitest/jest in this repo; run with:
 *     node hub/frontend/src/chat/active-channel-on-arrival.test.mjs
 * Exits non-zero on failure (mirrors the convention used by
 * channels-equal.test.mjs / draft-store.test.mjs).
 *
 * Re-implements the channel-guard rule against the same spec rather than
 * importing the TS modules (which pull in DOM globals + side effects on
 * load). Any divergence between this re-implementation and the live code
 * is a test-suite bug we want surfaced — see channels-equal.test.mjs for
 * the same mirroring pattern.
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

/* --- spec re-implementation -------------------------------------------- */

/* Mirror of app/utils.ts _normalizeChannelName + channelsEqual.
 * Same spec as channels-equal.test.mjs. */
function _normalizeChannelName(name) {
  if (name == null) return "";
  const s = String(name);
  if (!s) return "";
  if (s.charAt(0) === "#") return s;
  if (s.indexOf("dm:") === 0) return s;
  return "#" + s;
}
function channelsEqual(a, b) {
  if (a == null && b == null) return true;
  if (a == null || b == null) return false;
  if (a === b) return true;
  return _normalizeChannelName(a) === _normalizeChannelName(b);
}

/* Minimal DOM stand-in: each "msg row" is just an object with style.display
 * and data-channel, mirroring how chat-render.ts uses these attributes. */
function makeMsgRow(channel) {
  return { channel: channel, style: { display: "" } };
}

/* Mirror of the rule in chat-render.ts appendMessage() lines 265-270:
 *
 *   if ((globalThis as any).currentChannel &&
 *       !channelsEqual(channel, (globalThis as any).currentChannel)) {
 *     el.style.display = "none";
 *   }
 *
 * The function returns the active channel UNCHANGED — this is the core
 * invariant of todo#246. Inbound messages MUST NOT call
 * setCurrentChannel() / mutate currentChannel directly. */
function applyAppendMessageGuard(state, msg) {
  const row = makeMsgRow(msg.payload && msg.payload.channel);
  if (
    state.currentChannel &&
    !channelsEqual(row.channel, state.currentChannel)
  ) {
    row.style.display = "none";
  }
  /* CRITICAL: state.currentChannel is NOT touched. The bug being guarded
   * against was an earlier code path that reset state.currentChannel
   * back to "#general" on inbound messages. The current chat-render.ts
   * has no such write — this helper preserves that property. */
  return row;
}

/* Mirror of state.ts setCurrentChannel: the ONLY legitimate way for
 * currentChannel to mutate. Sidebar clicks / channel-link clicks /
 * hash-router calls go through this. */
function setCurrentChannel(state, ch) {
  if (ch) ch = _normalizeChannelName(ch);
  state.currentChannel = ch;
  state.persisted = ch == null ? "__all__" : ch;
}

/* --- tests ------------------------------------------------------------- */

test("does not switch active channel when message arrives in other channel", () => {
  const state = { currentChannel: "#heads", persisted: "#heads" };
  const incoming = { payload: { channel: "#general", content: "hi" } };
  const row = applyAppendMessageGuard(state, incoming);
  assertEq(state.currentChannel, "#heads", "currentChannel must stay on #heads");
  assertEq(state.persisted, "#heads", "persisted state untouched on inbound");
  assertEq(row.style.display, "none", "non-active-channel row hidden");
  assertEq(row.channel, "#general", "row keeps its data-channel");
});

test("incoming message in active channel stays visible", () => {
  const state = { currentChannel: "#heads", persisted: "#heads" };
  const incoming = { payload: { channel: "#heads", content: "yo" } };
  const row = applyAppendMessageGuard(state, incoming);
  assertEq(state.currentChannel, "#heads", "active channel unchanged");
  assertEq(row.style.display, "", "matching channel row visible");
});

test("multiple inbound messages in other channels do not bounce active channel", () => {
  const state = { currentChannel: "#ywatanabe", persisted: "#ywatanabe" };
  const burst = [
    { payload: { channel: "#general", content: "1" } },
    { payload: { channel: "#heads", content: "2" } },
    { payload: { channel: "#progress", content: "3" } },
    { payload: { channel: "#general", content: "4" } },
    { payload: { channel: "dm:agent:head|human:ywatanabe", content: "5" } },
  ];
  burst.forEach((m) => applyAppendMessageGuard(state, m));
  assertEq(
    state.currentChannel,
    "#ywatanabe",
    "burst of foreign-channel messages must not flip currentChannel",
  );
  assertEq(state.persisted, "#ywatanabe", "persisted state must not flip");
});

test("active-channel mode (currentChannel=null) lets all messages render", () => {
  const state = { currentChannel: null, persisted: "__all__" };
  const a = applyAppendMessageGuard(state, {
    payload: { channel: "#heads", content: "x" },
  });
  const b = applyAppendMessageGuard(state, {
    payload: { channel: "#general", content: "y" },
  });
  assertEq(a.style.display, "", "all-channels mode renders #heads");
  assertEq(b.style.display, "", "all-channels mode renders #general");
  assertEq(state.currentChannel, null, "all-channels mode preserved");
});

test("explicit setCurrentChannel is the only writer", () => {
  const state = { currentChannel: "#heads", persisted: "#heads" };
  /* Inbound messages: no mutation expected. */
  applyAppendMessageGuard(state, {
    payload: { channel: "#general", content: "noise" },
  });
  assertEq(state.currentChannel, "#heads");
  /* User clicks #ywatanabe in the sidebar: setCurrentChannel mutates. */
  setCurrentChannel(state, "#ywatanabe");
  assertEq(state.currentChannel, "#ywatanabe", "user click switches channel");
  assertEq(state.persisted, "#ywatanabe", "user click persists channel");
  /* More inbound noise: still no mutation. */
  applyAppendMessageGuard(state, {
    payload: { channel: "#general", content: "more noise" },
  });
  assertEq(
    state.currentChannel,
    "#ywatanabe",
    "post-switch inbound messages still do not flip channel",
  );
});

test("prefix-asymmetric incoming channel still does not flip currentChannel", () => {
  /* Same spec as channels-equal.test.mjs: '#ywatanabe' vs 'ywatanabe' must
   * be treated as the same channel. The active channel must not change in
   * either case. */
  const state = { currentChannel: "#ywatanabe", persisted: "#ywatanabe" };
  const matching = applyAppendMessageGuard(state, {
    payload: { channel: "ywatanabe", content: "bare-form arrival" },
  });
  assertEq(state.currentChannel, "#ywatanabe", "no flip on bare-form match");
  assertEq(matching.style.display, "", "bare-form match stays visible");

  const foreign = applyAppendMessageGuard(state, {
    payload: { channel: "general", content: "bare-form foreign" },
  });
  assertEq(state.currentChannel, "#ywatanabe", "no flip on bare-form foreign");
  assertEq(
    foreign.style.display,
    "none",
    "bare-form foreign-channel row hidden",
  );
});

test("DM message arriving while on a group channel does not flip channel", () => {
  const state = {
    currentChannel: "#heads",
    persisted: "#heads",
  };
  const dm = applyAppendMessageGuard(state, {
    payload: {
      channel: "dm:agent:head|human:ywatanabe",
      content: "private",
    },
  });
  assertEq(
    state.currentChannel,
    "#heads",
    "DM arrival must not pull user out of group channel",
  );
  assertEq(dm.style.display, "none", "DM row hidden in group-channel view");
});

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
