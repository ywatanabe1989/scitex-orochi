/* app/channels-equal.test.mjs — node-runner for the channel-name equality
 * helper (msg#16691).
 *
 * Matches the style of composer/composer-paste.test.mjs (no vitest/jest
 * in this repo; run via
 * `node hub/frontend/src/app/channels-equal.test.mjs`).
 *
 * Covers the bug that silenced the ``#ywatanabe`` feed: a message whose
 * server-side canonical channel was ``#ywatanabe`` but whose client-side
 * ``currentChannel`` had been restored from a bare ``ywatanabe`` value
 * (legacy persisted or pre-normalize sidebar row) caused the chat-render
 * guard to evaluate ``"#ywatanabe" !== "ywatanabe"`` and hide every row.
 *
 * Re-implements the helpers against the same spec instead of importing
 * the TS module (which pulls in DOM / localStorage on load).
 */

function _normalizeChannelName(name) {
  if (name == null) return "";
  var s = String(name);
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

/* --- _normalizeChannelName ------------------------------------------------ */

test("normalize: null → empty", () => {
  assertEq(_normalizeChannelName(null), "");
});
test("normalize: undefined → empty", () => {
  assertEq(_normalizeChannelName(undefined), "");
});
test("normalize: empty string → empty string", () => {
  assertEq(_normalizeChannelName(""), "");
});
test("normalize: bare name gets '#' prefix", () => {
  assertEq(_normalizeChannelName("ywatanabe"), "#ywatanabe");
});
test("normalize: already-prefixed name unchanged", () => {
  assertEq(_normalizeChannelName("#ywatanabe"), "#ywatanabe");
});
test("normalize: DM prefix preserved", () => {
  assertEq(
    _normalizeChannelName("dm:agent:head|human:ywatanabe"),
    "dm:agent:head|human:ywatanabe",
  );
});
test("normalize: nested folder channel kept intact", () => {
  assertEq(_normalizeChannelName("#proj/ripple-wm"), "#proj/ripple-wm");
  assertEq(_normalizeChannelName("proj/ripple-wm"), "#proj/ripple-wm");
});
test("normalize: number coerced to string", () => {
  assertEq(_normalizeChannelName(42), "#42");
});

/* --- channelsEqual (the ywatanabe-feed regression guard) ------------------ */

test("equal: identical '#ywatanabe'", () => {
  assert(channelsEqual("#ywatanabe", "#ywatanabe"));
});
test("equal: '#ywatanabe' vs 'ywatanabe' — the bug case", () => {
  assert(
    channelsEqual("#ywatanabe", "ywatanabe"),
    "prefix-asymmetric comparison must match to keep the feed visible",
  );
  assert(channelsEqual("ywatanabe", "#ywatanabe"));
});
test("equal: both bare", () => {
  assert(channelsEqual("ywatanabe", "ywatanabe"));
});
test("equal: different channels stay unequal", () => {
  assert(!channelsEqual("#ywatanabe", "#general"));
  assert(!channelsEqual("ywatanabe", "general"));
  assert(!channelsEqual("#ywatanabe", "#ywatanabe2"));
});
test("equal: DM channels match themselves and not a group channel", () => {
  assert(
    channelsEqual(
      "dm:agent:head|human:ywatanabe",
      "dm:agent:head|human:ywatanabe",
    ),
  );
  assert(!channelsEqual("dm:agent:head|human:ywatanabe", "#ywatanabe"));
  /* DM prefix must NOT collapse onto a ``#dm:...`` form. */
  assert(
    !channelsEqual("dm:agent:head|human:ywatanabe", "#dm:agent:head|human:ywatanabe"),
  );
});
test("equal: both null → true (all-channels mode invariant)", () => {
  assert(channelsEqual(null, null));
  assert(channelsEqual(undefined, undefined));
  assert(channelsEqual(null, undefined));
});
test("equal: one side null → false", () => {
  assert(!channelsEqual(null, "#ywatanabe"));
  assert(!channelsEqual("#ywatanabe", null));
});
test("equal: empty string treated as falsy-but-equal with empty string", () => {
  assert(channelsEqual("", ""));
});
test("equal: folder channels", () => {
  assert(channelsEqual("#proj/ripple-wm", "proj/ripple-wm"));
  assert(!channelsEqual("#proj/ripple-wm", "#proj/neurovista"));
});

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
