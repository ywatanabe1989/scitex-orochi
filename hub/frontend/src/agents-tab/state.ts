// @ts-nocheck
// Migrated classic-script file. Types intentionally loose during
// the big-bang JS-to-TS bundle migration. Narrow later, per-file.
/* Agents Tab — shared state, detail-fetch, and small formatters.
 * Loaded first; later sub-files (detail.js, controls.js, overview.js)
 * depend on the globals declared here. */
/* globals: escapeHtml, getAgentColor, isAgentInactive, timeAgo,
   addTag, activeTab, apiUrl */
var _agentsTabInterval = null;
var _selectedAgentTab = "overview"; /* "overview" or agent name */
var _lastAgentsData = []; /* cached for sub-tab renders */
var _agentDetailCache = {}; /* name -> last /detail response */
var _agentDetailInflight = {}; /* name -> bool (in-flight guard) */
/* todo#47 — pane view state survives heartbeat-driven re-renders so
 * Expand and Follow don't reset every poll. */
var _paneExpanded = {}; /* name -> bool */
var _followAgent = null; /* name currently in follow mode (only one) */
var _followTimer = null; /* setInterval handle */
var FOLLOW_INTERVAL_MS = 3000;

/* Fetch the full per-agent detail payload (todo#420).
 *
 * Responses are cached into _agentDetailCache and rendered via
 * _renderAgentContent. The registry-based fallback in
 * _renderAgentDetail still runs on first paint so the user never
 * sees a blank screen while the detail call is in flight. */
async function _fetchAgentDetail(name) {
  if (!name || name === "overview") return;
  if (_agentDetailInflight[name]) return;
  _agentDetailInflight[name] = true;
  try {
    var res = await fetch(
      apiUrl("/api/agents/" + encodeURIComponent(name) + "/detail/"),
    );
    if (!res.ok) {
      console.warn("agent detail fetch failed:", name, res.status);
      return;
    }
    var data = await res.json();
    _agentDetailCache[name] = data;
    /* Only re-render if still viewing this agent */
    if (_selectedAgentTab === name) {
      var grid = document.getElementById("agents-grid");
      if (grid) _renderAgentContent(grid);
    }
  } catch (e) {
    console.warn("agent detail fetch error:", name, e);
  } finally {
    _agentDetailInflight[name] = false;
  }
}

function _invalidateAgentDetail(name) {
  delete _agentDetailCache[name];
  _fetchAgentDetail(name);
}

/* todo#47 — live read-only pane tier.
 *
 * Exported entry point called by app.js on every `agent_info` /
 * `agent_pong` WebSocket event. If the dashboard is currently showing
 * the detail tab for *this* agent, re-fetch detail so the pane_tail /
 * RTT / last_action surfaces refresh within seconds instead of waiting
 * for the user to re-click. No-op when the user is on the Overview tab
 * or looking at a different agent — avoids hammering the API with
 * unrelated heartbeats. */
function onAgentInfoEvent(name) {
  if (!name) return;
  if (_selectedAgentTab !== name) return;
  _invalidateAgentDetail(name);
}
window.onAgentInfoEvent = onAgentInfoEvent;

/* Compact human-friendly seconds formatter used in the detail header. */
function _fmtDuration(sec) {
  sec = Number(sec) || 0;
  if (sec < 60) return sec + "s";
  var m = Math.floor(sec / 60);
  if (m < 60) return m + "m";
  var h = Math.floor(m / 60);
  if (h < 24) return h + "h " + (m % 60) + "m";
  var d = Math.floor(h / 24);
  return d + "d " + (h % 24) + "h";
}

function livenessColor(liveness) {
  switch (liveness) {
    case "online":
      return "#4ecdc4";
    case "idle":
      return "#ffd93d";
    case "stale":
      return "#ff8c42";
    case "offline":
      return "#ef4444";
    default:
      return "#888";
  }
}

/* todo#418: pane_state badge — maps classifier label to display color+icon.
 * Labels are defined in pane_state.py (scitex-orochi/hub/utils/pane_state.py).
 * Stuck states (y_n_prompt, auth_error, mcp_broken, compose_pending) use
 * amber/red so they visually pop in the Agents tab row. */
function paneStateColor(ps) {
  switch (ps) {
    case "running":
      return "#4ecdc4";
    case "waiting":
      return "#ffd93d";
    case "y_n_prompt":
      return "#ff8c42";
    case "auth_error":
      return "#ef4444";
    case "mcp_broken":
      return "#ef4444";
    case "compose_pending":
      return "#ff8c42";
    case "booting":
      return "#888";
    case "ghost":
      return "#555";
    case "dead":
      return "#ef4444";
    default:
      return "#888";
  }
}

function formatUptime(isoStr) {
  if (!isoStr) return "-";
  var d = new Date(isoStr);
  if (isNaN(d.getTime())) return "-";
  var sec = Math.floor((Date.now() - d.getTime()) / 1000);
  if (sec < 60) return sec + "s";
  var min = Math.floor(sec / 60);
  if (min < 60) return min + "m";
  var hr = Math.floor(min / 60);
  if (hr < 24) return hr + "h " + (min % 60) + "m";
  var days = Math.floor(hr / 24);
  return days + "d " + (hr % 24) + "h";
}
