/* filter/pretty-tag-label.test.mjs — unit tests for _prettyTagLabel.
 *
 * Re-implements the helper inline (same pattern as channels-equal.test.mjs)
 * to avoid DOM/localStorage pull-in from state.ts on load.
 *
 * Run: node hub/frontend/src/filter/pretty-tag-label.test.mjs
 */

import assert from "node:assert/strict";

function _prettyTagLabel(type, value) {
  if (type === "channel" && value.indexOf("dm:") === 0) {
    var after = value.slice(3);
    var firstPart = after.split("|")[0] || "";
    var colonIdx = firstPart.indexOf(":");
    var name = colonIdx >= 0 ? firstPart.slice(colonIdx + 1) : firstPart;
    return "DM: " + name;
  }
  return type + ":" + value;
}

// --- DM cases ---------------------------------------------------------------

assert.strictEqual(
  _prettyTagLabel("channel", "dm:agent:mamba-todo-manager-mba|human:ywatanabe"),
  "DM: mamba-todo-manager-mba",
  "agent|human DM shows agent name"
);

assert.strictEqual(
  _prettyTagLabel("channel", "dm:agent:head-mba|agent:mamba-worker-mba"),
  "DM: head-mba",
  "agent|agent DM shows first agent name"
);

assert.strictEqual(
  _prettyTagLabel("channel", "dm:human:ywatanabe|human:other"),
  "DM: ywatanabe",
  "human|human DM shows first name"
);

// --- Non-DM cases -----------------------------------------------------------

assert.strictEqual(
  _prettyTagLabel("channel", "#heads"),
  "channel:#heads",
  "regular channel tag unchanged"
);

assert.strictEqual(
  _prettyTagLabel("agent", "head-mba"),
  "agent:head-mba",
  "agent tag unchanged"
);

assert.strictEqual(
  _prettyTagLabel("host", "mba"),
  "host:mba",
  "host tag unchanged"
);

// --- Edge cases -------------------------------------------------------------

assert.strictEqual(
  _prettyTagLabel("channel", "dm:"),
  "DM: ",
  "empty dm key degrades gracefully"
);

assert.strictEqual(
  _prettyTagLabel("channel", "dm:agent:x"),
  "DM: x",
  "dm key with no pipe separator"
);

console.log("All _prettyTagLabel tests passed.");
