// @ts-nocheck
import { agentIdentity } from "./agent-icons";
import { cleanAgentName, escapeHtml, getAgentColor, hostedAgentName } from "./app/utils";

/**
 * agent-badge.js — single source of truth for the agent badge UI.
 *
 * Every place the dashboard shows an agent (sidebar row, list-view row,
 * topology pool chip, future widgets) MUST use ``renderAgentBadge(a, opts)``
 * from this file. NEVER inline a fork of the markup. ywatanabe directive
 * 2026-04-20: "ALL agent card MUST HAVE THE IDENTICAL AND SYNCHRONIZED
 * BADGES, INCLUDING ICON (changeable on click), STAR (toglable), 4 LEDs,
 * name, and host; NEVER ACCEPT ANY DIFFERENCES".
 *
 * Badge layout (left → right), todo#305 Task 7 (lead msg#15548):
 *   [icon][star][eye][LED1 WS][LED2 Ping][LED3 Local][LED4 Remote][name@host]
 *
 * The 👁 eye slot was added after ★ and before the LEDs per lead's
 * explicit ordering directive in msg#15548 / companion reference
 * image `sidebar-agents-reference-2026-04-21.png`. Channel cards carry
 * eye too — keeping parity across both entity types so a user who
 * learned "eye = hide this row" on channels finds the same on agents.
 *
 * Loaded BEFORE app.js / activity-tab.js / agents-tab.js so the helpers
 * are in scope at render time. See dashboard.html <script> ordering.
 *
 * Composable parts (also exported so call sites can compose differently
 * when they need to interleave other elements — e.g. drag handles):
 *   - renderAgentIcon(a, size)     — clickable avatar / emoji
 *   - renderAgentStar(a)           — togglable ☆/★
 *   - renderAgentEye(a)            — togglable 👁 show/hide
 *   - renderAgentLeds(a, opts)     — four-LED liveness strip
 *   - renderAgentName(a)           — colored name (with @host suffix)
 *
 * Composed:
 *   - renderAgentBadge(a, opts)    — all of the above in canonical order
 *
 * `opts` (all optional):
 *   - extraClass : string appended to each LED's class (used by
 *                  topology pool chips for sizing without forking)
 *   - iconSize   : pixel size for icon (default 14)
 *   - hideName   : skip the name span (when caller renders name itself
 *                  with custom layout — e.g. SVG canvas)
 *   - hideHost   : drop @host from the name (compact contexts)
 *
 * Hard rule: if you need a new variant, add an opt — never inline a
 * different markup. dashboard-development-discipline.md rule 1.
 */

(function () {
  "use strict";

  // ── Helper: HTML escape ────────────────────────────────────────────
  function _escape(s) {
    if (typeof escapeHtml === "function") return escapeHtml(s);
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return (
        { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[
          c
        ] || c
      );
    });
  }

  function _connected(a) {
    if (typeof connected === "function") return connected(a);
    return (a.status || "online") !== "offline";
  }

  // ── 1. Icon ───────────────────────────────────────────────────────
  function renderAgentIcon(a, size) {
    var px = size || 14;
    var name = a.name || "";
    // Prefer the global identity helper if present (handles avatar URL,
    // emoji, color-keyed initial) — fall back to a colored circle with
    // the first character of the name.
    if (typeof agentIdentity === "function") {
      var ident = agentIdentity(a);
      if (ident && typeof ident.iconHtml === "function") {
        return (
          '<span class="agent-badge-icon avatar-clickable"' +
          ' data-avatar-agent="' +
          _escape(name) +
          '" title="Click to change avatar">' +
          ident.iconHtml(px) +
          "</span>"
        );
      }
    }
    var initial = (name[0] || "?").toUpperCase();
    var color =
      typeof getAgentColor === "function" ? getAgentColor(name) : "#888";
    return (
      '<span class="agent-badge-icon avatar-clickable"' +
      ' data-avatar-agent="' +
      _escape(name) +
      '" title="Click to change avatar"' +
      ' style="display:inline-flex;align-items:center;justify-content:center;' +
      "width:" +
      px +
      "px;height:" +
      px +
      "px;border-radius:50%;background:" +
      color +
      ";color:#111;font-size:" +
      Math.round(px * 0.7) +
      'px;font-weight:600">' +
      _escape(initial) +
      "</span>"
    );
  }

  // ── 2. Star (togglable, always visible) ───────────────────────────
  function renderAgentStar(a) {
    var pinned = !!a.pinned;
    return (
      '<button type="button" class="agent-badge-star pin-btn activity-pin-btn' +
      (pinned ? " pinned activity-pin-on" : "") +
      '" data-pin-name="' +
      _escape(a.name || "") +
      '" data-pin-next="' +
      (pinned ? "false" : "true") +
      '" title="' +
      _escape(pinned ? "Unstar" : "Star (keeps as ghost when offline)") +
      '">' +
      (pinned ? "\u2605" : "\u2606") +
      "</button>"
    );
  }

  // ── 2c. Subagent count (msg#16116 Item 4 / lead msg#16116).
  //        Tiny chip showing the number of active Agent-tool subagents
  //        spawned by this agent. Source: ``a.orochi_subagent_count`` from the
  //        /api/agents/ payload (already present per PR #318 — fleet-wide
  //        terse whitelist). Hidden entirely when the value is undefined
  //        or 0 so idle agents keep the compact row silhouette.
  //        Rendered in every surface that uses renderAgentBadge (sidebar
  //        list, detail-pane header, agent-card composer). The SVG
  //        topology node renders its own variant via agent-badge-svg.ts.
  function renderAgentSubagentCount(a) {
    var n = a && a.orochi_subagent_count != null ? Number(a.orochi_subagent_count) : 0;
    if (!n || !isFinite(n) || n < 1) return "";
    /* Class name ``agent-badge-subcount`` intentionally distinct from
     * the pre-existing ``.agent-badge-subagents`` pill in
     * components-agent-cards.css — that rule is a full-width meta pill
     * rendered on the Agents-tab card; this one is an inline count
     * chip appended to the badge strip. */
    return (
      '<span class="agent-badge-subcount" title="' +
      _escape(n + " active subagent(s)") +
      '">' +
      "\uD83E\uDDD2\uFE0F\u00A0" + /* 🧒 + non-breaking space */
      n +
      "</span>"
    );
  }

  // ── 2b. Eye (togglable show/hide, always visible, placeholder even when
  //        not hidden so column geometry stays constant across rows).
  // Mirrors the channel .ch-eye pattern 1:1: same 👁 glyph in both states,
  // red diagonal strike drawn via the .agent-badge-eye-off::after CSS
  // rule (defined in style-agents.css alongside the channel variant).
  // todo#305 Task 7 (lead msg#15548).
  function renderAgentEye(a) {
    var hidden = !!a.is_hidden;
    return (
      '<span class="agent-badge-eye ' +
      (hidden ? "agent-badge-eye-off" : "agent-badge-eye-on") +
      '" data-eye-agent="' +
      _escape(a.name || "") +
      '" title="' +
      _escape(
        hidden
          ? "Show agent (un-hide)"
          : "Hide agent (remove from list + graph)",
      ) +
      '" style="cursor:pointer">\uD83D\uDC41</span>'
    );
  }

  // ── 3. Four-LED liveness strip ────────────────────────────────────
  function renderAgentLeds(a, opts) {
    var extra = opts && opts.extraClass ? " " + opts.extraClass : "";
    var liveness = a.liveness || a.status || "online";
    var paneState = a.pane_state || "unknown";
    // 1. WS
    var wsOn = _connected(a);
    var ledWs =
      '<span class="activity-led activity-led-ws activity-led-ws-' +
      (wsOn ? "on" : "off") +
      extra +
      '" title="' +
      _escape(
        "1. WebSocket — " +
          (wsOn ? "connected" : "disconnected") +
          "\n  TCP+WS handshake; green = sidecar holds an open WS.",
      ) +
      '"></span>';
    // 2. Ping
    var pong = a.last_pong_ts;
    var pongAge =
      pong != null ? (Date.now() - new Date(pong).getTime()) / 1000 : null;
    var pingState = "off";
    var pingLabel = "no pong yet";
    if (pongAge != null) {
      if (pongAge < 60) {
        pingState = "on";
        pingLabel = "pong " + Math.round(pongAge) + "s ago";
        if (a.last_rtt_ms != null)
          pingLabel += " (" + Math.round(a.last_rtt_ms) + "ms round-trip)";
      } else if (pongAge < 180) {
        pingState = "warn";
        pingLabel = "stale pong " + Math.round(pongAge) + "s ago";
      } else {
        pingState = "off";
        pingLabel = "no recent pong (" + Math.round(pongAge) + "s)";
      }
    }
    var ledPing =
      '<span class="activity-led activity-led-ping activity-led-ping-' +
      pingState +
      extra +
      '" title="' +
      _escape(
        "2. Ping — " +
          pingLabel +
          "\n  Hub sends ping every 25s; sidecar echoes pong.\n  Green = fresh, yellow = stale, grey = none.",
      ) +
      '"></span>';
    // 3. Local functional state
    var ledFn =
      '<span class="activity-led activity-led-fn activity-led-fn-' +
      liveness +
      extra +
      '" title="' +
      _escape(
        "3. Local functional state — " +
          liveness.toUpperCase() +
          " (pane: " +
          paneState +
          ")\n  Heuristic from local pane text; not fully reliable.\n  green = running, yellow = idle, blue = waiting,\n  red = auth_error, orange = stale.",
      ) +
      '"></span>';
    // 4. Remote functional state — "last proof of life".
    // msg#15538: ``last_nonce_echo_at`` is advanced by EITHER the
    // hub→agent nonce round-trip (hub/consumers/_echo.py) OR by any
    // inbound agent message (hub/consumers/_agent_message.py via
    // mark_echo_alive). The renderer does not need to know which
    // mechanism wrote the timestamp — either path turns the LED green.
    var echo = a.last_nonce_echo_at;
    var echoAge =
      echo != null ? (Date.now() - new Date(echo).getTime()) / 1000 : null;
    var echoState = "pending";
    var echoLabel = "not yet probed by any peer";
    if (echoAge != null) {
      if (echoAge < 90) {
        echoState = "on";
        echoLabel = "echoed " + Math.round(echoAge) + "s ago";
      } else if (echoAge < 300) {
        echoState = "warn";
        echoLabel = "stale echo " + Math.round(echoAge) + "s ago";
      } else {
        echoState = "fail";
        echoLabel = "no echo (" + Math.round(echoAge) + "s)";
      }
    }
    var ledEcho =
      '<span class="activity-led activity-led-echo activity-led-echo-' +
      echoState +
      extra +
      '" title="' +
      _escape(
        "4. Remote functional state — " +
          echoLabel +
          "\n  Active probe: peer host posts random nonce; agent must\n  echo it back through Claude. Strongest proof-of-life.\n  green = recent, yellow = stale, red = no echo, grey = pending.",
      ) +
      '"></span>';
    return ledWs + ledPing + ledFn + ledEcho;
  }

  // ── 4. Name + host ────────────────────────────────────────────────
  function renderAgentName(a, opts) {
    var hideHost = opts && opts.hideHost;
    var displayName = a.name || "";
    if (typeof hostedAgentName === "function") {
      displayName = hostedAgentName(a);
    } else if (!hideHost && a.machine && displayName.indexOf("@") === -1) {
      displayName = displayName + "@" + a.machine;
    }
    if (typeof cleanAgentName === "function") {
      displayName = cleanAgentName(displayName);
    }
    var color =
      typeof getAgentColor === "function" ? getAgentColor(a.name || "") : "";
    return (
      '<span class="agent-badge-name"' +
      (color ? ' style="color:' + color + '"' : "") +
      ">" +
      _escape(displayName) +
      "</span>"
    );
  }

  // ── Composed badge (canonical layout) ─────────────────────────────
  function renderAgentBadge(a, opts) {
    opts = opts || {};
    /* Canonical order, todo#305 Task 7 (lead msg#15548):
     *   icon + star + eye + 4 LEDs + name@hostname
     * Matches the channel badge column order (icon + star + eye +
     * mute + name) so a user who learned the glyph map on channels
     * finds the same on agents. The eye was inserted between ★ and
     * the LED strip per lead's explicit ordering directive in
     * msg#15548 (deviation from Task 3's baseline, but Task 7 owns
     * the slot for agents going forward).
     *
     * msg#16116 Item 4: a tiny subagent-count chip is appended AFTER
     * the name. Hidden by default when count is 0/undefined so idle
     * agents keep their existing row silhouette; only busy agents
     * grow the extra glyph. Caller can opt out via
     * ``opts.hideSubagentCount``. */
    var icon = renderAgentIcon(a, opts.iconSize);
    var star = renderAgentStar(a);
    var eye = opts.hideEye ? "" : renderAgentEye(a);
    var leds = renderAgentLeds(a, { extraClass: opts.extraClass });
    var name = opts.hideName ? "" : renderAgentName(a, opts);
    var subs = opts.hideSubagentCount ? "" : renderAgentSubagentCount(a);
    return icon + star + eye + leds + name + subs;
  }

  // ── Background-class helper: dim when not all four LEDs green ─────
  // Centralises the "shadow when not fully healthy" rule so every
  // render site shadows on the same condition.
  function isAgentAllGreen(a) {
    if (!_connected(a)) return false;
    var pongAge =
      a.last_pong_ts != null
        ? (Date.now() - new Date(a.last_pong_ts).getTime()) / 1000
        : null;
    if (!(pongAge != null && pongAge < 60)) return false;
    if ((a.liveness || a.status || "") !== "online") return false;
    var echoAge =
      a.last_nonce_echo_at != null
        ? (Date.now() - new Date(a.last_nonce_echo_at).getTime()) / 1000
        : null;
    if (!(echoAge != null && echoAge < 90)) return false;
    return true;
  }

  // Visibility rule: keep listed if any LED green OR pinned.
  // Hide only when fully dead AND unstarred.
  function isAgentVisible(a) {
    if (a.pinned) return true;
    if (_connected(a)) return true;
    var pongAge =
      a.last_pong_ts != null
        ? (Date.now() - new Date(a.last_pong_ts).getTime()) / 1000
        : null;
    if (pongAge != null && pongAge < 60) return true;
    if ((a.liveness || a.status || "") === "online") return true;
    var echoAge =
      a.last_nonce_echo_at != null
        ? (Date.now() - new Date(a.last_nonce_echo_at).getTime()) / 1000
        : null;
    if (echoAge != null && echoAge < 90) return true;
    return false;
  }

  // ── Eye toggle — persistent flip of AgentProfile.is_hidden ──────────
  // Body-level delegated handler so EVERY agent-eye glyph anywhere in
  // the DOM (sidebar row, Activity overview card, topology SVG) gets
  // the same behavior without per-render binding. Mirrors the
  // .ch-eye delegation pattern in channel-badge.js (see
  // attachChannelBadgeHandlers there). Idempotent: only binds once.
  var _agentEyeAttached = false;
  function attachAgentEyeHandler() {
    if (_agentEyeAttached) return;
    _agentEyeAttached = true;
    if (typeof document === "undefined") return;
    document.body.addEventListener(
      "click",
      function (ev) {
        var eye = ev.target.closest && ev.target.closest(
          ".agent-badge-eye[data-eye-agent], .topo-agent-eye[data-eye-agent]",
        );
        if (!eye) return;
        var name = eye.getAttribute("data-eye-agent");
        if (!name) return;
        ev.stopPropagation();
        ev.preventDefault();
        /* Current state — read from live registry if available, fall
         * back to the glyph's own class for first-click after load
         * (before __lastAgents is populated). */
        var live = (window as any).__lastAgents || [];
        var curAgent = null;
        for (var i = 0; i < live.length; i++) {
          if (live[i] && live[i].name === name) {
            curAgent = live[i];
            break;
          }
        }
        var curHidden = curAgent
          ? !!curAgent.is_hidden
          : eye.classList.contains("agent-badge-eye-off") ||
            eye.classList.contains("topo-agent-eye-off");
        var nextHidden = !curHidden;
        /* Optimistic local update so the glyph flips immediately; the
         * re-render triggered by _setAgentHidden → fetchAgents lands
         * ~200-500ms later and is idempotent. */
        if (curAgent) curAgent.is_hidden = nextHidden;
        eye.classList.toggle("agent-badge-eye-on", !nextHidden);
        eye.classList.toggle("agent-badge-eye-off", nextHidden);
        eye.classList.toggle("topo-agent-eye-on", !nextHidden);
        eye.classList.toggle("topo-agent-eye-off", nextHidden);
        /* Persist via the existing agent-profiles endpoint — same
         * mutation path as icon / color edits. The backend accepts
         * is_hidden as an optional PATCH-style field (todo#305 Task 7;
         * hub/views/api/_agents.py::api_agent_profiles). */
        var setHidden = (window as any)._setAgentHidden;
        if (typeof setHidden === "function") {
          setHidden(name, nextHidden);
        }
      },
      true, // capture — beat site-local click handlers that stopPropagation
    );
  }
  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", attachAgentEyeHandler);
    } else {
      attachAgentEyeHandler();
    }
  }

  // Expose globals — script is loaded as a plain <script> tag.
  window.renderAgentIcon = renderAgentIcon;
  window.renderAgentStar = renderAgentStar;
  window.renderAgentEye = renderAgentEye;
  window.renderAgentSubagentCount = renderAgentSubagentCount;
  window.renderAgentLeds = renderAgentLeds;
  window.renderAgentName = renderAgentName;
  window.renderAgentBadge = renderAgentBadge;
  window.isAgentAllGreen = isAgentAllGreen;
  window.isAgentVisible = isAgentVisible;
})();

// Auto-generated module re-exports for symbols assigned to `window`
// inside the file-level IIFE above. These run after the IIFE's side
// effects so other ES modules can import these names instead of
// reaching into `window`.
export const isAgentAllGreen = (window as any).isAgentAllGreen;
export const isAgentVisible = (window as any).isAgentVisible;
export const renderAgentBadge = (window as any).renderAgentBadge;
export const renderAgentEye = (window as any).renderAgentEye;
export const renderAgentIcon = (window as any).renderAgentIcon;
export const renderAgentLeds = (window as any).renderAgentLeds;
export const renderAgentName = (window as any).renderAgentName;
export const renderAgentStar = (window as any).renderAgentStar;
export const renderAgentSubagentCount = (window as any).renderAgentSubagentCount;
