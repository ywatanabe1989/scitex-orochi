// @ts-nocheck
/* activity-tab/row.js — overview list + tiled card renderer
 * (_renderActivityCards) and view-class toggle. */


/* Overview list/tile renderer. One-line rows (or compact tiles) for
 * every agent passing the visibility rule. Click a row → inline expand
 * (single at a time). Expand is toggled via _overviewExpanded state.
 *
 * Each row carries THREE indicators so connection, heartbeat-age, and
 * LLM-level activity are all visible at a glance without opening the
 * detail panel:
 *
 *   WS LED       — WebSocket functional connection (status online/offline)
 *   Functional LED — heartbeat-age liveness (online/idle/stale/offline)
 *   State chip   — synthesized pane+tool state: running/idle/selecting
 *
 * Visibility rule (functional, NOT duration-based):
 *   status==="online" (WS connected)  → always shown (online/idle/stale)
 *   status==="offline" + pinned       → shown as ghost (dimmed)
 *   status==="offline" + unpinned     → hidden
 */
function _renderActivityCards(agents, grid) {
  var summary = document.getElementById("activity-summary");
  var all = agents || [];
  var counts = { online: 0, idle: 0, stale: 0, offline: 0 };
  all.forEach(function (a) {
    var l = a.liveness || a.status || "online";
    if (counts[l] != null) counts[l]++;
  });
  if (summary) {
    summary.innerHTML =
      '<span class="activity-pill activity-pill-online" title="connected &amp; active">' +
      '<span class="activity-pill-dot"></span>' +
      counts.online +
      " active</span>" +
      '<span class="activity-pill activity-pill-idle" title="connected, quiet 2–10 min">' +
      '<span class="activity-pill-dot"></span>' +
      counts.idle +
      " idle</span>" +
      '<span class="activity-pill activity-pill-stale" title="connected, quiet &gt;10 min — probably stuck">' +
      '<span class="activity-pill-dot"></span>' +
      counts.stale +
      " stale</span>" +
      '<span class="activity-pill activity-pill-offline" title="not connected">' +
      '<span class="activity-pill-dot"></span>' +
      counts.offline +
      " offline</span>";
  }

  var visible = all.filter(function (a) {
    /* ywatanabe 2026-04-20: hide criterion is the strict
     * conjunction "all LEDs not green AND not starred". Any single
     * green indicator means show; any star means show; only fully-
     * dead unstarred agents disappear. Maps the four-indicator
     * contract from fleet-liveness-four-indicators.md to the
     * filter:
     *   1. WS    — green when status != "offline"
     *   2. Ping  — green when last_pong_ts within 60s
     *   3. Local — green when liveness == "online"
     *   4. Remote — green when last_nonce_echo_at within 90s
     */
    if (a.pinned) return true;
    if ((a.status || "online") !== "offline") return true; // WS green
    var pongAge =
      a.last_pong_ts != null
        ? (Date.now() - new Date(a.last_pong_ts).getTime()) / 1000
        : null;
    if (pongAge != null && pongAge < 60) return true; // Ping green
    var liveness = a.liveness || a.status || "";
    if (liveness === "online") return true; // Local green
    var echoAge =
      a.last_nonce_echo_at != null
        ? (Date.now() - new Date(a.last_nonce_echo_at).getTime()) / 1000
        : null;
    if (echoAge != null && echoAge < 90) return true; // Remote green
    return false;
  });

  if (!visible.length) {
    grid.innerHTML = '<p class="empty-notice">No agents connected.</p>';
    return;
  }

  if (_overviewView === "topology") {
    _renderActivityTopology(visible, grid);
    return;
  }

  var LIVENESS_HINTS = {
    online: "connected & active — heartbeat <2 min",
    idle: "connected, quiet 2–10 min",
    stale: "connected, quiet >10 min — probably stuck",
    offline: "not connected",
  };

  /* Preserve a live SSH inline-detail block across heartbeat
   * re-renders — otherwise grid.innerHTML = ... below would wipe the
   * xterm DOM and kill the shell session. If the currently-expanded
   * agent has an active SSH session, snapshot its inline-detail
   * element and splice it back in after the grid is rebuilt. */
  var _preservedInlineDetail = null;
  if (
    _overviewExpanded &&
    _activityPaneSshState &&
    _activityPaneSshState[_overviewExpanded]
  ) {
    var _liveInline = grid.querySelector(
      '.activity-inline-detail[data-detail-for="' +
        String(_overviewExpanded).replace(/"/g, '\\"') +
        '"]',
    );
    if (
      _liveInline &&
      _liveInline.querySelector(".agent-detail-ssh-container")
    ) {
      _preservedInlineDetail = _liveInline;
    }
  }

  grid.innerHTML = visible
    .map(function (a) {
      var rawName = a.name || "";
      var liveness = a.liveness || a.status || "online";
      var connected = (a.status || "online") !== "offline";
      /* Shadow treatment when not all four indicators are green —
       * makes degraded agents visually distinct without hiding them.
       * ywatanabe 2026-04-20: "Registered agents must be shown as
       * shadowed when all LEDs not green". The four-LED green test
       * mirrors the visibility filter above (which keeps an agent
       * listed as long as ≥1 LED is green or it's starred). */
      var pongAge =
        a.last_pong_ts != null
          ? (Date.now() - new Date(a.last_pong_ts).getTime()) / 1000
          : null;
      var echoAge =
        a.last_nonce_echo_at != null
          ? (Date.now() - new Date(a.last_nonce_echo_at).getTime()) / 1000
          : null;
      var allGreen =
        connected &&
        pongAge != null &&
        pongAge < 60 &&
        liveness === "online" &&
        echoAge != null &&
        echoAge < 90;
      var ghostClass = allGreen ? "" : " activity-card-ghost";
      var idleStr = _formatIdle(a.idle_seconds);
      var color = getAgentColor(_colorKeyFor(a));
      var channels = Array.isArray(a.channels) ? a.channels : [];
      var channelsStr = channels
        .filter(function (c) {
          return c && c.indexOf("dm:") !== 0;
        })
        .join(" ");
      var name = escapeHtml(
        typeof hostedAgentName === "function"
          ? hostedAgentName(a)
          : cleanAgentName(rawName),
      );
      var pinOn = a.pinned ? " activity-pin-on" : "";
      var pinTitle = a.pinned
        ? "Unstar (will hide when offline)"
        : "Star (keeps as ghost when offline, floats to top)";
      var livenessHint = LIVENESS_HINTS[liveness] || liveness;
      var wsHint = connected ? "WebSocket connected" : "WebSocket disconnected";
      var state = _computeAgentState(a);
      var stateLabel = state.toUpperCase();
      var stateHint =
        {
          running: "LLM fired a tool within the last 30s",
          idle: "connected, no recent tool calls",
          selecting: "agent is blocked on a choice or needs attention",
          offline: "not connected",
        }[state] || state;
      var ageStr = idleStr ? idleStr : "";
      // Single source of truth — agent-badge.js. Same call appears in
      // app.js sidebar and topology pool chip. NEVER fork the markup.
      var row =
        '<div class="activity-card activity-' +
        liveness +
        ghostClass +
        '" data-agent="' +
        escapeHtml(rawName) +
        '" data-machine="' +
        escapeHtml(a.machine || "") +
        '">' +
        renderAgentBadge(a) +
        '<span class="activity-channels" title="' +
        escapeHtml(channelsStr || "no channels") +
        '">' +
        escapeHtml(channelsStr) +
        "</span>" +
        (ageStr
          ? '<span class="activity-age" title="' +
            escapeHtml(livenessHint) +
            '">' +
            escapeHtml(ageStr) +
            "</span>"
          : "") +
        "</div>";
      if (_overviewExpanded === rawName) {
        row +=
          '<div class="activity-inline-detail" data-detail-for="' +
          escapeHtml(rawName) +
          '"><p class="empty-notice">Loading detail…</p></div>';
      }
      return row;
    })
    .join("");

  if (typeof runFilter === "function") runFilter();

  /* Single delegated click listener on the grid — bound ONCE, survives
   * innerHTML rewrites (the grid element itself is never replaced).
   * Per-element listeners were silently lost between heartbeat re-
   * renders, causing the pin button to become unclickable after a poll
   * tick (ywatanabe 2026-04-19). */
  _wireOverviewGridDelegation(grid);

  if (_overviewExpanded) {
    var agent = all.find(function (a) {
      return a.name === _overviewExpanded;
    });
    var inlineBox = grid.querySelector(
      '.activity-inline-detail[data-detail-for="' +
        String(_overviewExpanded).replace(/"/g, '\\"') +
        '"]',
    );
    /* SSH active: splice the preserved inline-detail (with its live
     * xterm) back in place of the fresh loading placeholder, and
     * SKIP the detail re-render so the DOM node the xterm lives in
     * is not replaced. */
    if (_preservedInlineDetail && inlineBox && inlineBox.parentNode) {
      inlineBox.parentNode.replaceChild(_preservedInlineDetail, inlineBox);
    } else if (agent && inlineBox) {
      _renderActivityAgentDetail(agent, inlineBox);
      _fetchActivityDetail(agent.name);
    }
  }
}

/* Apply layout class (list vs tiled vs topology) to the overview grid.
 * The three modes are mutually exclusive CSS scopes — each adds one
 * class and the renderer dispatches on _overviewView internally. */
function _applyOverviewViewClass(grid) {
  if (!grid) return;
  grid.classList.remove(
    "activity-view-list",
    "activity-view-tiled",
    "activity-view-topology",
    "activity-grid-detail",
  );
  var cls = "activity-view-list";
  if (_overviewView === "tiled") cls = "activity-view-tiled";
  else if (_overviewView === "topology") cls = "activity-view-topology";
  grid.classList.add(cls);
}

