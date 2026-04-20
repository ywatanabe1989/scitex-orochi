/* activity-tab/click.js — multi-click counter for topology agent/
 * channel nodes + DM open helper. */


var _overviewGridWired = false;
/* Topology click-counter: collects successive clicks on the same agent
 * node within CLICK_WINDOW_MS and dispatches a single action (1/2/3-
 * click). Double-click native event is also wired below as a fallback
 * for legacy browsers — the guard re-uses the same counter. */
var _topoClickState = null; /* {kind, name, count, timer, x, y} */
var TOPO_CLICK_WINDOW_MS = 350;
function _topoFlushClick() {
  if (!_topoClickState) return;
  var s = _topoClickState;
  _topoClickState = null;
  if (!s.name) return;
  if (s.kind === "channel") {
    /* Channel multi-click:
     *   2 = open inline compose popup
     *   3 = jump to the Chat tab focused on this channel
     *       (ywatanabe 2026-04-19: "triple click a channel → show in
     *       Chat channel"). */
    if (s.count >= 3) {
      if (typeof setCurrentChannel === "function") setCurrentChannel(s.name);
      if (typeof loadChannelHistory === "function") loadChannelHistory(s.name);
      var chatBtn = document.querySelector('[data-tab="chat"]');
      if (chatBtn) chatBtn.click();
    } else if (s.count === 2) {
      _topoOpenChannelCompose(s.name, s.x || 0, s.y || 0);
    }
    /* count === 1 is a no-op (preserves rectangle-zoom path for
     * empty-area clicks — channels still mark a click as "handled" by
     * virtue of being a clickable node, but we don't want a single
     * click to trigger anything destructive). */
    return;
  }
  /* Default: agent multi-click. */
  if (s.count >= 3) {
    _overviewExpanded = _overviewExpanded === s.name ? null : s.name;
    if (typeof renderActivityTab === "function") renderActivityTab();
  } else if (s.count === 2) {
    var human =
      (typeof userName !== "undefined" && userName) ||
      window.__orochiUserName ||
      "human";
    var dmCh = "dm:agent:" + s.name + "|human:" + human;
    _topoOpenChannelCompose(dmCh, s.x || 0, s.y || 0);
  }
  /* count === 1 for agents is handled as drag-source on mousedown. */
}
function _topoBumpClick(name, clientX, clientY, kind) {
  var k = kind || "agent";
  if (
    _topoClickState &&
    _topoClickState.name === name &&
    _topoClickState.kind === k
  ) {
    _topoClickState.count += 1;
    _topoClickState.x = clientX;
    _topoClickState.y = clientY;
    clearTimeout(_topoClickState.timer);
  } else {
    if (_topoClickState) clearTimeout(_topoClickState.timer);
    _topoClickState = {
      kind: k,
      name: name,
      count: 1,
      timer: 0,
      x: clientX,
      y: clientY,
    };
  }
  _topoClickState.timer = setTimeout(_topoFlushClick, TOPO_CLICK_WINDOW_MS);
}

/* Open (or create-and-open) the DM channel between the signed-in human
 * and the given agent. Channel name mirrors the backend convention
 *   dm:agent:<agent>|human:<user>
 * (see hub/views/api.py::api_dms + _dm_canonical_name). We use POST
 * /api/dms/ to get-or-create because it runs full_clean() AND sets
 * kind=KIND_DM — the /api/channel-members/ path would create a bogus
 * KIND_GROUP row with a reserved dm: name AND would 403 for non-staff
 * users. Once the backend confirms the canonical name we switch the UI
 * (setCurrentChannel + loadChannelHistory + activate Chat tab). */
function _openAgentDm(agentName) {
  if (!agentName) return;
  var human =
    (typeof userName !== "undefined" && userName) ||
    window.__orochiUserName ||
    "human";
  var fallback = "dm:agent:" + agentName + "|human:" + human;
  function _switchTo(channel) {
    try {
      if (typeof setCurrentChannel === "function") setCurrentChannel(channel);
      if (typeof loadChannelHistory === "function") loadChannelHistory(channel);
      var chatTabBtn = document.querySelector('[data-tab="chat"]');
      if (chatTabBtn) chatTabBtn.click();
    } catch (_) {}
  }
  var csrf = typeof getCsrfToken === "function" ? getCsrfToken() : "";
  var url = typeof apiUrl === "function" ? apiUrl("/api/dms/") : "/api/dms/";
  try {
    fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrf,
      },
      body: JSON.stringify({ recipient: "agent:" + agentName }),
    })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (j) {
        /* POST /api/dms/ returns the canonical {name, ...} row. Fall
         * back to our constructed name if the response shape is
         * unexpected. */
        var ch =
          (j && (j.name || j.channel || (j.dm && j.dm.name))) || fallback;
        _switchTo(ch);
      })
      .catch(function () {
        /* Still switch — if the channel pre-exists (common: agents
         * register their DM on startup) the UI will load it even
         * though the create endpoint errored. */
        _switchTo(fallback);
      });
  } catch (_) {
    _switchTo(fallback);
  }
}


