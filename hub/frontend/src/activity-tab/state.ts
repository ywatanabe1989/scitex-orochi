// @ts-nocheck
/* activity-tab/state.js — module-level state, config, localStorage bootstrap
 * for the canonical Agents UI renderer (split from activity-tab.js).
 * Classic-script semantics; no ES modules; every var stays global.
 * globals: apiUrl, escapeHtml, getAgentColor, cleanAgentName, fetchAgents */

/* Activity tab — real-time agent status board with per-agent sub-tabs */
/* globals: apiUrl, escapeHtml, getAgentColor, cleanAgentName, fetchAgents */

var activityRefreshTimer = null;
var _paneShowRaw = false; /* false = strip ANSI (clean), true = raw */
/* Cache for /api/agents/<name>/detail/ so the per-agent view can show
 * fields that the registry summary omits (full CLAUDE.md, full pane
 * text, redacted MCP). Mirrors _agentDetailCache in agents-tab.js. */
var _activityDetailCache = {};
var _activityDetailInflight = {};
/* todo#47 — Pane view state survives heartbeat-driven re-renders
 * (Expand stays expanded, Follow keeps polling). One agent follows
 * at a time; sub-tab switch or hidden document auto-stops. */
var _activityPaneExpanded = {}; /* name -> bool */
var _activityFollowAgent = null;
var _activityFollowTimer = null;
var ACTIVITY_FOLLOW_INTERVAL_MS = 3000;



/* ── Overview controls state (filter / sort / view / color / expand) ── */
var _overviewFilter = "";
var _overviewSort = "name";
var _overviewView = "list";
var _overviewColor = "name";
var _overviewExpanded = null;
/* Topology channel-node size mode. "equal" = fixed radius; "subscribers" =
 * scaled by sqrt(n_agents_subscribed). "posts" is reserved — /api/stats
 * does not yet expose per-channel post counts, so the dropdown advertises
 * it for parity with future backend work but falls through to "equal"
 * today (ywatanabe 2026-04-19 todo#95). */
var _topoSizeBy = "subscribers";
try {
  var _savedSort = localStorage.getItem("orochi.overviewSort");
  if (_savedSort === "name" || _savedSort === "machine")
    _overviewSort = _savedSort;
  var _savedView = localStorage.getItem("orochi.overviewView");
  if (
    _savedView === "list" ||
    _savedView === "tiled" ||
    _savedView === "topology"
  )
    _overviewView = _savedView;
  var _savedColor = localStorage.getItem("orochi.overviewColor");
  if (
    _savedColor === "name" ||
    _savedColor === "host" ||
    _savedColor === "account"
  )
    _overviewColor = _savedColor;
  var _savedSize = localStorage.getItem("orochi.topoSizeBy");
  if (
    _savedSize === "equal" ||
    _savedSize === "subscribers" ||
    _savedSize === "posts"
  )
    _topoSizeBy = _savedSize;
} catch (_e) {
  /* localStorage may be unavailable — fall back to defaults */
}

/* Pick the color key from the agent record based on the user-selected
 * "color by" option. Hash returns a deterministic pastel color for any
 * non-empty string (reuses getAgentColor), so the same machine, name,
 * or account always maps to the same color across rows. Empty key
 * falls back to name so rows never render colorless. */
function _colorKeyFor(a) {
  var key = "";
  if (_overviewColor === "host") key = a.machine || "";
  else if (_overviewColor === "account") key = a.account_email || "";
  if (!key) key = a.name || "";
  return key;
}


/* Signature cache — topology rebuilds every heartbeat were visibly
 * slow on busy hubs (user: "Viz is quite slow"). The SVG only needs
 * to repaint when the visible set, their statuses, or the expand
 * target changes; the heartbeat-driven re-renders that merely bump
 * `last_heartbeat` / `idle_seconds` would otherwise rebuild every
 * edge and label. We short-circuit on a compact signature. */
var _topoLastSig = "";
var _topoLastExpanded = null;
var _topoViewBox = null; /* {x,y,w,h} — persisted zoom/pan across re-renders */
var _topoViewBoxHistory = []; /* back stack (undo) */
var _topoViewBoxFuture = []; /* forward stack (redo) */
var _topoZoomWired = false;
var _topoLastPositions = { agents: {}, channels: {} };
/* todo#67 — Time seekbar + play button for packet replay.
 * _topoSeekEvents: ring buffer of recent pulses {ts, sender, channel, opts}.
 * Default mode is "live" (seek head glued to latest). Dragging the slider
 * enters "playback" — live pulses are suppressed so the viewer can step
 * through history; press Play to auto-advance. Buffer is trimmed to the
 * last TOPO_SEEK_WINDOW_MS (5 min) to keep memory bounded. */
var TOPO_SEEK_WINDOW_MS = 5 * 60 * 1000; /* 5 minutes */
var _topoSeekEvents = [];
var _topoSeekMode = "live"; /* "live" | "playback" */
var _topoSeekTime = 0; /* unix-ms playhead, only used in playback */
var _topoSeekPlaying = false;
var _topoSeekRafId = null;
var _topoSeekLastFrameTs = 0;
var _topoSeekSpeed = 1; /* playback speed multiplier */
var _topoSeekWired = false;
var _topoSeekReplayInProgress = false;
/* Prevent the heartbeat re-render from stomping the slider that the user
 * is actively dragging — we reconcile slider value from seek state only
 * when not actively interacting. */
var _topoSeekInteracting = false;
/* Landing bubbles — short-lived speech-bubble DOM nodes attached to
 * the destination node when a packet arrives. Multiple arrivals at the
 * same node stack vertically; older bubbles lift up to make room.
 * ywatanabe 2026-04-19: "after reaching to the target, as a bubble,
 * the message should be shown and stacked and disappeared with timer
 * like 1 s duration" / "in a fade in/out manner".
 * Shape: { "<x>,<y>": [ {g, expireAt, timer}, ... ] } (oldest first). */
var _topoLandingStacks = Object.create(null);
var _TOPO_LANDING_DUR_MS = 1300;
var _TOPO_LANDING_STACK_MAX = 4;
var _TOPO_LANDING_STEP_PX = 18;
/* Client-side "sticky" subscriptions — edges added via drag-drop that
 * survive server-authoritative refetches until the backend starts
 * returning the membership in a.channels. Without this, the optimistic
 * mutation of window.__lastAgents gets clobbered the moment
 * fetchAgentsThrottled resolves, and the edge vanishes until the user
 * reloads. ywatanabe 2026-04-19: "after subscription by dragging,
 * show the edge soon" / "we need reload or make another subscription".
 * Shape: { "<agent-name>|<channel>": true }. */

var _topoStickyEdges = {};
function _topoStickyKey(agent, channel) {
  return String(agent || "") + "|" + String(channel || "");
}
var _topoHidden = { agents: {}, channels: {} };
try {
  var _topoHiddenRaw = localStorage.getItem("orochi.topoHidden");
  if (_topoHiddenRaw) {
    var _topoHiddenParsed = JSON.parse(_topoHiddenRaw);
    if (_topoHiddenParsed && typeof _topoHiddenParsed === "object") {
      _topoHidden.agents = _topoHiddenParsed.agents || {};
      _topoHidden.channels = _topoHiddenParsed.channels || {};
    }
  }
} catch (_e) {}
function _topoSaveHidden() {
  try {
    localStorage.setItem(
      "orochi.topoHidden",
      JSON.stringify({
        agents: _topoHidden.agents,
        channels: _topoHidden.channels,
      }),
    );
  } catch (_e) {}
  /* If a memory slot is currently "recording", roll the hidden-set
   * change into its snapshot too — the whole view is what M<slot>
   * restores. */
  if (typeof _topoAutoSaveActiveSlot === "function") {
    _topoAutoSaveActiveSlot();
  }
}
function _topoHiddenSignature() {
  return (
    "h:" +
    Object.keys(_topoHidden.agents).sort().join(",") +
    ";" +
    Object.keys(_topoHidden.channels).sort().join(",")
  );
}
function _topoHide(kind, name) {
  if (!kind || !name) return;
  var hn =
    (typeof userName !== "undefined" && userName) ||
    window.__orochiUserName ||
    "";
  if (kind === "agent" && hn && name === hn) return;
  if (kind === "agent") _topoHidden.agents[name] = true;
  else if (kind === "channel") _topoHidden.channels[name] = true;
  else return;
  _topoSaveHidden();
  _topoLastSig = "";
  if (typeof renderActivityTab === "function") renderActivityTab();
}
function _topoUnhide(kind, name) {
  if (kind === "agent") delete _topoHidden.agents[name];
  else if (kind === "channel") delete _topoHidden.channels[name];
  _topoSaveHidden();
  _topoLastSig = "";
  if (typeof renderActivityTab === "function") renderActivityTab();
}
function _topoUnhideAll() {
  _topoHidden = { agents: {}, channels: {} };
  _topoSaveHidden();
  _topoLastSig = "";
  if (typeof renderActivityTab === "function") renderActivityTab();
}
window._topoHide = _topoHide;
window._topoUnhide = _topoUnhide;
window._topoUnhideAll = _topoUnhideAll;

/* Manual position overrides — user-dragged node coordinates that
 * supersede the ring-layout slot for that node. Persisted to
 * localStorage under "orochi.topoPositions". Key format:
 *   "agent:<name>" or "channel:<name>"
 * Value: { x: <svg x>, y: <svg y> }.
 * ywatanabe 2026-04-19: canvas drag-to-reposition — dragging a node
 * on the canvas and dropping on empty SVG space pins it at the drop
 * coordinate; ring layout is only the default, not a force.
 * Shape: { "agent:<name>": {x, y}, "channel:<name>": {x, y} }. */
var _topoManualPositions = {};
try {
  var _topoPosRaw = localStorage.getItem("orochi.topoPositions");
  if (_topoPosRaw) {
    var _topoPosParsed = JSON.parse(_topoPosRaw);
    if (_topoPosParsed && typeof _topoPosParsed === "object") {
      _topoManualPositions = _topoPosParsed;
    }
  }
} catch (_e) {}
function _topoManualKey(kind, name) {
  return String(kind || "") + ":" + String(name || "");
}
function _topoSaveManualPositions() {
  try {
    localStorage.setItem(
      "orochi.topoPositions",
      JSON.stringify(_topoManualPositions),
    );
  } catch (_e) {}
}
function _topoSetManualPosition(kind, name, x, y) {
  if (!kind || !name) return;
  if (typeof x !== "number" || typeof y !== "number") return;
  _topoManualPositions[_topoManualKey(kind, name)] = { x: x, y: y };
  _topoSaveManualPositions();
  _topoLastSig = "";
}
function _topoClearManualPosition(kind, name) {
  delete _topoManualPositions[_topoManualKey(kind, name)];
  _topoSaveManualPositions();
  _topoLastSig = "";
}
function _topoManualPositionsSignature() {
  return "mp:" + Object.keys(_topoManualPositions).sort().join(",");
}
window._topoSetManualPosition = _topoSetManualPosition;
window._topoClearManualPosition = _topoClearManualPosition;
function _topoApplyStickyEdges() {
  /* Merge sticky edges into window.__lastAgents so _renderActivity-
   * Topology (and every other consumer of a.channels) sees them as
   * real memberships. Purges sticky entries that the server has
   * caught up to — keeps the set from growing unbounded. */
  var live = window.__lastAgents || [];
  var keep = {};
  Object.keys(_topoStickyEdges).forEach(function (k) {
    var pipe = k.indexOf("|");
    if (pipe < 0) return;
    var agent = k.slice(0, pipe);
    var ch = k.slice(pipe + 1);
    var row = null;
    for (var i = 0; i < live.length; i++) {
      if (live[i].name === agent) {
        row = live[i];
        break;
      }
    }
    if (!row) {
      /* Agent vanished from the live list — drop the sticky too. */
      return;
    }
    var chs = Array.isArray(row.channels) ? row.channels : [];
    if (chs.indexOf(ch) !== -1) {
      /* Server caught up — no need to keep overriding. */
      return;
    }
    row.channels = chs.concat([ch]);
    keep[k] = true;
  });
  _topoStickyEdges = keep;
}

/* Permission-direction arrows: map of "<channel>::<agentName>" → one of
 * "read-only" | "read-write" | "write-only". Populated by
 * _refreshTopoPerms() which calls /api/channel-members/?channel=…
 * per visible channel and caches the result. Missing pairs default to
 * "read-write" (bidirectional arrows — safer than hiding direction).
 * TTL = 30 s; any subscribe/unsubscribe invalidates the whole map. */

var _topoChannelPerms = Object.create(null);
var _topoChannelPermsFetchedAt = 0;
var _topoChannelPermsInflight = Object.create(null); /* channel → bool */
var TOPO_PERMS_TTL_MS = 30000;


/* Left-pool multi-select — ctrl-click chips to accumulate a selection,
 * then drag the set onto another chip / canvas node to bulk-subscribe.
 * Separate from _topoSelected (which is the canvas lasso selection) so
 * the two affordances don't step on each other. ywatanabe 2026-04-19:
 * "ctrl click should allow multiple select" / "drag and drop should be
 * implemented between pools as well" / "multiple subscription".
 *
 * todo#79: "Pools as filters" — when selection is non-empty the canvas
 * is filtered to selected entities + their direct neighbors + incident
 * edges; everything else is dimmed/hidden. Selection is persisted to
 * localStorage so it survives reload, and up to 5 memory slots (M1..M5)
 * act as named presets (recall on click, save via shift-click / the
 * +Save button). */
var _TOPO_POOL_SEL_KEY = "orochi.topoPoolSelection";
/* Memory slots are scoped by workspace so switching workspaces doesn't
 * show the wrong presets. Falls back to the legacy unscoped key on
 * first read so existing snapshots aren't nuked after upgrade. todo#98
 * "Memory slots snapshot current filter state" — each slot now captures
 * pool selection + sidebar filter input + activeTags chips + per-entity
 * hidden set, so recall restores the *whole* view. */
var _TOPO_POOL_MEM_KEY_LEGACY = "orochi.topoPoolMemories";
function _topoMemWorkspaceKey() {
  var ws =
    (typeof window !== "undefined" &&
      (window.__orochiWorkspace || window.__orochiWorkspaceName)) ||
    "default";
  return "orochi.memoryslots." + String(ws);
}
var _TOPO_POOL_MEM_MAX = 5;
var _topoPoolSelection = (function _loadPoolSel() {
  var empty = {
    agents: Object.create(null),
    channels: Object.create(null),
  };
  try {
    var raw = localStorage.getItem(_TOPO_POOL_SEL_KEY);
    if (!raw) return empty;
    var parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return empty;
    (parsed.agents || []).forEach(function (n) {
      if (typeof n === "string") empty.agents[n] = true;
    });
    (parsed.channels || []).forEach(function (n) {
      if (typeof n === "string") empty.channels[n] = true;
    });
  } catch (_e) {
    /* localStorage unavailable or malformed — fall back to empty set. */
  }
  return empty;
})();
var _topoPoolMemories = (function _loadPoolMem() {
  try {
    var raw = localStorage.getItem(_topoMemWorkspaceKey());
    if (!raw) {
      /* todo#98 back-compat: bootstrap from legacy unscoped key so users
       * who saved slots pre-upgrade don't silently lose them. Migrate by
       * writing the data under the new namespaced key on next persist. */
      raw = localStorage.getItem(_TOPO_POOL_MEM_KEY_LEGACY);
    }
    if (!raw) return {};
    var parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (_e) {
    return {};
  }
})();
/* Active memory slot — when non-null, every selection / hidden /
 * filter change auto-saves into _topoPoolMemories[slot]. Click M1 to
 * activate; click again to deactivate. User 2026-04-20 spec: "click
 * M1 -> M1 must be highlighted -> last state of M1 filtering is
 * saved as M1 automatically. No need to save". */
var _TOPO_ACTIVE_MEM_KEY = "orochi.topoActiveMemSlot";
var _topoActiveMemSlot = (function () {
  try {
    var v = parseInt(localStorage.getItem(_TOPO_ACTIVE_MEM_KEY) || "", 10);
    return isFinite(v) && v >= 1 && v <= 5 ? v : null;
  } catch (_) {
    return null;
  }
})();

var TOPO_SEEK_HEAT_BINS = 200;
var TOPO_SEEK_HEAT_THROTTLE_MS = 250;
var _topoSeekHeatLastSig = "";
var _topoSeekHeatLastPaint = 0;


