// @ts-nocheck
import { _renderActivityTopology } from "./topology";

/* activity-tab/row.js — overview canvas renderer and view-class toggle.
 *
 * Historically this module also rendered an agent LIST (one-line rows
 * or compact tiles) for the legacy Viz/List toggle inside Overview.
 * msg#16337 retired that toggle: Overview is Viz-only, the Agents tab
 * owns the list surface. The entry point below now just delegates to
 * the topology renderer (after the summary-pill counts are updated),
 * and the view-class helper always applies the topology CSS scope. */


/* Overview canvas renderer — updates the summary pill counts and
 * delegates to the topology view. Kept under the legacy name
 * _renderActivityCards so callers in init.ts don't have to be touched
 * on every iteration of this refactor; the implementation is now a
 * thin shim over _renderActivityTopology. */
export function _renderActivityCards(agents, grid) {
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

  _renderActivityTopology(visible, grid);
}

/* Apply layout class to the overview grid. Overview is Viz-only
 * (msg#16337) — the grid always runs topology. The older "list" and
 * "tiled" CSS scopes are still removed defensively so a stale class
 * from a prior render can't leak into the topology canvas. */
export function _applyOverviewViewClass(grid) {
  if (!grid) return;
  grid.classList.remove(
    "activity-view-list",
    "activity-view-tiled",
    "activity-view-topology",
    "activity-grid-detail",
  );
  grid.classList.add("activity-view-topology");
}

