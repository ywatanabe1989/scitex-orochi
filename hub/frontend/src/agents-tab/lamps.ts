// @ts-nocheck
// Migrated classic-script file. Types intentionally loose during
// the big-bang JS-to-TS bundle migration. Narrow later, per-file.
/* Agents Tab — indicator-lamp bank (HB/RT/PN/MCP/HL) + pane-state badge.
 * Loaded after state.js (livenessColor, paneStateColor) and before
 * detail.js, which calls _renderIndicatorLamps from inside _renderAgentDetail.
 * Also exposes renderPaneStateBadge used by overview.js buildAgentRow. */

/* todo#57: multi-lamp connectivity indicator bank on the detail header.
 * Instead of one status dot, surface the independent signals the user
 * needs to triage a broken agent: heartbeat freshness, pane classifier,
 * MCP sidecar, and explicit health. Each lamp renders as a 10px dot
 * with a hover tooltip explaining what it tracks and the current state
 * value. Gray = no signal reported (distinct from red = bad signal). */
function _buildIndicatorLamps(a, d) {
  var lamps = [];
  var liveness =
    d.liveness || a.liveness || (isAgentInactive(a) ? "offline" : "online");
  lamps.push({
    key: "heartbeat",
    color: livenessColor(liveness),
    label: "HB",
    title:
      "Heartbeat freshness · " +
      liveness +
      " (online <2m · idle 2–10m · stale >10m · offline no push)",
  });

  // todo#46 — Hub→agent round-trip ping lamp (RT). last_pong_ts is an
  // ISO8601 string from the agent detail / agents projection; treat
  // missing-or-stale-beyond-60s as "no signal" (gray). RTT color
  // thresholds: <=250ms teal, <=1000ms amber, >1000ms red.
  var pongIso = d.last_pong_ts || a.last_pong_ts || null;
  var rttMs = d.last_rtt_ms;
  if (typeof rttMs !== "number") rttMs = a.last_rtt_ms;
  var pongAgeSec = null;
  if (pongIso) {
    var pongDate = new Date(pongIso);
    if (!isNaN(pongDate.getTime())) {
      pongAgeSec = Math.max(0, (Date.now() - pongDate.getTime()) / 1000);
    }
  }
  var rtColor;
  var rtTitle;
  if (pongAgeSec === null || pongAgeSec > 60) {
    rtColor = "#888";
    rtTitle = "Hub ping RTT · no recent pong — hub→agent channel may be stuck";
  } else if (typeof rttMs !== "number") {
    rtColor = "#888";
    rtTitle = "Hub ping RTT · pong received but no RTT sample";
  } else if (rttMs <= 250) {
    rtColor = "#4ecdc4";
    rtTitle =
      "Hub ping RTT · " +
      Math.round(rttMs) +
      " ms (last pong " +
      Math.round(pongAgeSec) +
      "s ago)";
  } else if (rttMs <= 1000) {
    rtColor = "#ffd93d";
    rtTitle =
      "Hub ping RTT · " +
      Math.round(rttMs) +
      " ms — slow (last pong " +
      Math.round(pongAgeSec) +
      "s ago)";
  } else {
    rtColor = "#ef4444";
    rtTitle =
      "Hub ping RTT · " +
      Math.round(rttMs) +
      " ms — very slow (last pong " +
      Math.round(pongAgeSec) +
      "s ago)";
  }
  lamps.push({
    key: "rtt",
    color: rtColor,
    label: "RT",
    title: rtTitle,
  });

  var paneState = d.pane_state || a.pane_state || "";
  var paneOk = ["", "running", "idle", "unknown"];
  var paneStuck = [
    "y_n_prompt",
    "auth_error",
    "mcp_broken",
    "compose_pending_unsent",
    "stuck",
  ];
  var paneColor = "#888";
  if (paneOk.indexOf(paneState) !== -1) paneColor = "#4ecdc4";
  else if (paneStuck.indexOf(paneState) !== -1) paneColor = "#ef4444";
  else paneColor = "#ffd93d";
  lamps.push({
    key: "pane",
    color: paneColor,
    label: "PN",
    title:
      "Pane classifier · " +
      (paneState || "(no classification)") +
      " — red=stuck / amber=unusual / teal=ok / gray=no signal",
  });
  var mcpServers = d.mcp_servers || a.mcp_servers || [];
  var mcpColor = mcpServers.length > 0 ? "#4ecdc4" : "#888";
  lamps.push({
    key: "mcp",
    color: mcpColor,
    label: "MCP",
    title:
      "MCP sidecar · " +
      (mcpServers.length > 0
        ? mcpServers.length + " server(s) connected"
        : "(none reported — sidecar may be down)"),
  });
  var health = (d.health || a.health || {}).status || "";
  var healthColor;
  if (!health) healthColor = "#888";
  else if (health === "healthy" || health === "ok") healthColor = "#4ecdc4";
  else if (health === "degraded" || health === "warn") healthColor = "#ffd93d";
  else healthColor = "#ef4444";
  lamps.push({
    key: "health",
    color: healthColor,
    label: "HL",
    title:
      "Self-reported health · " +
      (health || "(none reported)") +
      " — teal=healthy / amber=degraded / red=unhealthy / gray=no signal",
  });
  return lamps;
}

function _renderIndicatorLamps(a, d) {
  var lamps = _buildIndicatorLamps(a, d);
  return (
    '<span class="agent-detail-lamps" role="status">' +
    lamps
      .map(function (l) {
        return (
          '<span class="agent-detail-lamp" data-lamp="' +
          escapeHtml(l.key) +
          '" title="' +
          escapeHtml(l.title) +
          '"><span class="agent-detail-lamp-dot" style="background:' +
          l.color +
          '"></span><span class="agent-detail-lamp-label">' +
          escapeHtml(l.label) +
          "</span></span>"
        );
      })
      .join("") +
    "</span>"
  );
}

function renderPaneStateBadge(paneState, stuckPromptText) {
  if (!paneState) return '<span class="muted-cell">-</span>';
  var color = paneStateColor(paneState);
  var label = paneState.replace(
    /_/g,
    "\u2009",
  ); /* thin space for readability */
  var title = stuckPromptText
    ? "Stuck at: " + stuckPromptText.slice(0, 200)
    : paneState;
  var badge =
    '<span class="pane-state-badge" style="color:' +
    color +
    ";border-color:" +
    color +
    '" title="' +
    escapeHtml(title) +
    '">' +
    escapeHtml(label) +
    "</span>";
  /* For stuck states, show a truncated excerpt of the prompt inline */
  var promptHtml = "";
  if (
    stuckPromptText &&
    ["y_n_prompt", "auth_error", "compose_pending"].indexOf(paneState) !== -1
  ) {
    promptHtml =
      '<span class="pane-state-prompt muted-cell" title="' +
      escapeHtml(stuckPromptText) +
      '">' +
      escapeHtml(stuckPromptText.slice(0, 60)) +
      (stuckPromptText.length > 60 ? "\u2026" : "") +
      "</span>";
  }
  return badge + promptHtml;
}
