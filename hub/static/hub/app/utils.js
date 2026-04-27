var cachedAgentNames = [];
var historyLoaded = false;
var knownMessageKeys = {};
var unreadCount = 0;
var channelUnread = {}; /* per-channel unread counts (#322) */
var baseTitle = document.title;

/* User display name -- from Django auth or fallback to localStorage */
var userName =
  window.__orochiUserName || localStorage.getItem("orochi_username");
if (!userName) {
  userName = prompt("Enter your display name for Orochi:", "");
  if (userName) {
    localStorage.setItem("orochi_username", userName);
  } else {
    userName = "human";
  }
}
var csrfToken = window.__orochiCsrfToken || "";
function getCsrfToken() {
  return window.__orochiCsrfToken || csrfToken || "";
}
function getAgentColor(name) {
  var s = name || "unknown";
  var sum = 0;
  for (var i = 0; i < s.length; i++) {
    sum += s.charCodeAt(i);
  }
  return OROCHI_COLORS[sum % OROCHI_COLORS.length];
}

/* Workspace icon — Slack-style colored rounded square with first letter */
var WORKSPACE_ICON_COLORS = [
  "#4A154B",
  "#1264A3",
  "#2BAC76",
  "#E01E5A",
  "#36C5F0",
  "#ECB22E",
  "#611f69",
  "#0b4f6c",
];

function getWorkspaceColor(name) {
  var s = name || "workspace";
  var sum = 0;
  for (var i = 0; i < s.length; i++) {
    sum += s.charCodeAt(i) * (i + 1);
  }
  return WORKSPACE_ICON_COLORS[sum % WORKSPACE_ICON_COLORS.length];
}

function getWorkspaceIcon(name, size) {
  size = size || 20;
  /* Render cascade:
   *   1. uploaded image (window.__orochiWorkspaceIconImage) → <img>
   *   2. emoji (window.__orochiWorkspaceIcon)               → handled by callers
   *   3. coloured square with first letter                  → default below.
   * The emoji branch stays in the call sites (init.js / emoji-picker /
   * settings.js) so this helper only needs to distinguish image vs
   * first-letter fallback. */
  var imgUrl = window.__orochiWorkspaceIconImage || "";
  if (imgUrl) {
    var radiusPx = Math.round(size * 0.22);
    return (
      '<img class="ws-icon-img" src="' +
      escapeHtml(imgUrl) +
      '" alt="" width="' +
      size +
      '" height="' +
      size +
      '" style="width:' +
      size +
      "px;height:" +
      size +
      "px;border-radius:" +
      radiusPx +
      'px;object-fit:cover;display:block" />'
    );
  }
  var color = getWorkspaceColor(name);
  var letter = (name || "W").charAt(0).toUpperCase();
  var fontSize = Math.round(size * 0.55);
  var radius = Math.round(size * 0.22);
  return (
    '<svg class="ws-icon-svg" width="' +
    size +
    '" height="' +
    size +
    '" viewBox="0 0 ' +
    size +
    " " +
    size +
    '" xmlns="http://www.w3.org/2000/svg">' +
    '<rect width="' +
    size +
    '" height="' +
    size +
    '" rx="' +
    radius +
    '" fill="' +
    color +
    '"/>' +
    '<text x="50%" y="50%" dominant-baseline="central" text-anchor="middle" ' +
    'fill="#fff" font-family="-apple-system,BlinkMacSystemFont,sans-serif" ' +
    'font-weight="700" font-size="' +
    fontSize +
    '">' +
    letter +
    "</text></svg>"
  );
}
function escapeHtml(s) {
  var d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

/* Collapse agent-name redundancy:
 *
 *  - "head@mba@Host"             → "head@mba"     (strip extra @host)
 *  - "head-mba@mba"              → "head@mba"     (role-host@host)
 *  - "healer-ywata-note-win@ywata-note-win"
 *                                → "healer@ywata-note-win"
 *  - "mamba-todo-manager-mba@mba"→ "mamba-todo-manager@mba"
 *  - "expert-scitex@ywata-note-win" → unchanged (no duplicated host)
 *
 * Rationale: agent IDs are registered as "<role>-<host>" because the
 * agent-container config generates them that way (head.yaml on mba ⇒
 * "head-mba"), but the dashboard already shows "@<host>" separately,
 * so the duplication just adds noise. This renderer-level fix keeps
 * the registered IDs intact and only affects display. */
function cleanAgentName(name) {
  if (!name) return name;
  var parts = name.split("@");
  if (parts.length >= 3) {
    /* Legacy double-@ form: "head@mba@Host" → "head@mba". Re-enter so
     * the role-host dedupe below also runs on the survivor. */
    name = parts[0] + "@" + parts[1];
    parts = name.split("@");
  }
  if (parts.length === 2) {
    var lead = parts[0];
    var host = parts[1];
    var suffix = "-" + host;
    if (host && lead.length > suffix.length && lead.endsWith(suffix)) {
      return lead.slice(0, -suffix.length) + "@" + host;
    }
  }
  return name;
}

/**
 * Return the agent name with host suffix. If the registered name already
 * contains @host (e.g. "head@mba"), return as-is. Otherwise append
 * "@<orochi_machine>" from the agent record so the sidebar always shows an
 * identity tied to a host (mamba shows as "mamba@ywata-note-win" even if
 * the agent config still registered plain "mamba").
 */
function hostedAgentName(a) {
  var name = a && a.name ? a.name : "";
  if (!name) return name;
  if (name.indexOf("@") !== -1) return cleanAgentName(name);
  /* #256 — host label MUST come from the live `hostname(1)` reported
   * in the heartbeat, NOT from the YAML config `orochi_machine` field.
   * Pre-fix, an agent_handlers `orochi_machine: mba` line in YAML caused the
   * dashboard to show `proj-neurovista@mba` even when no process was
   * running on mba (the ghost-mba bug). Falls back to `orochi_machine` for
   * legacy agents whose heartbeat hasn't been upgraded yet. */
  var host = a && a.hostname ? a.hostname : a && a.orochi_machine ? a.orochi_machine : "";
  /* Always pipe the constructed "<name>@<host>" string through
   * cleanAgentName so the role-host suffix gets collapsed
   * (head-mba@mba → head@mba). The earlier form returned the raw
   * concatenation and the dedupe never fired. */
  return host ? cleanAgentName(name + "@" + host) : name;
}

/**
 * @deprecated In-file copy retained for backward compat with any caller
 * that loaded before agent-badge.js was wired in. The canonical helper
 * lives in `agent-badge.js` and overrides this one at script-load time.
 * Do not edit this body — edit `agent-badge.js`.
 */
function _legacyRenderAgentLeds(a, opts) {
  var extra = opts && opts.extraClass ? " " + opts.extraClass : "";
  var liveness = a.liveness || a.status || "online";
  var paneState = a.orochi_pane_state || "unknown";
  // 1. WS
  var wsOn =
    typeof connected === "function" ? connected(a) : a.status !== "offline";
  var ledWs =
    '<span class="activity-led activity-led-ws activity-led-ws-' +
    (wsOn ? "on" : "off") +
    extra +
    '" title="' +
    escapeHtml(
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
    escapeHtml(
      "2. Ping — " +
        pingLabel +
        "\n  Hub sends ping every 25s; sidecar must echo pong.\n  Green = fresh, yellow = stale, grey = none.",
    ) +
    '"></span>';
  // 3. Local functional state
  var ledFn =
    '<span class="activity-led activity-led-fn activity-led-fn-' +
    liveness +
    extra +
    '" title="' +
    escapeHtml(
      "3. Local functional state — " +
        liveness.toUpperCase() +
        " (pane: " +
        paneState +
        ")\n  Heuristic from local pane text; not fully reliable.\n  green = running, yellow = idle, blue = waiting,\n  red = auth_error, orange = stale.",
    ) +
    '"></span>';
  // 4. Remote functional state — nonce-echo (publisher TBD; grey-dashed
  // until first echo lands so the gap is visible to operators).
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
    escapeHtml(
      "4. Remote functional state — " +
        echoLabel +
        "\n  Active probe: peer host posts random nonce; agent must\n  echo it back through Claude. Strongest proof-of-life.\n  green = recent, yellow = stale, red = no echo, grey = pending.",
    ) +
    '"></span>';
  return ledWs + ledPing + ledFn + ledEcho;
}

function fuzzyMatch(query, text) {
  if (!query) return true;
  query = query.toLowerCase();
  text = text.toLowerCase();
  var qi = 0;
  for (var ti = 0; ti < text.length && qi < query.length; ti++) {
    if (text[ti] === query[qi]) qi++;
  }
  return qi === query.length;
}

function messageKey(sender, ts, content) {
  return (
    (sender || "") + "|" + (ts || "") + "|" + (content || "").substring(0, 80)
  );
}

/* Channel-name normalization for client-side equality checks (msg#16691).
 * See hub/frontend/src/app/utils.ts for the full rationale — root cause of
 * the #ywatanabe feed-silence regression was ``#ywatanabe !== ywatanabe``
 * in the chat-render channel guard when legacy sidebar rows or persisted
 * localStorage handed the bare form into setCurrentChannel. */
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

function isAgentInactive(agent) {
  if (agent.status === "offline") return true;
  if (!agent.last_heartbeat) return false;
  var hb = new Date(agent.last_heartbeat);
  if (isNaN(hb.getTime())) return false;
  return Date.now() - hb.getTime() > 60000;
}

function relativeAge(isoStr) {
  if (!isoStr) return "";
  var d = new Date(isoStr);
  if (isNaN(d.getTime())) return "";
  var sec = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
  if (sec < 5) return "just now";
  if (sec < 60) return sec + "s ago";
  var min = Math.floor(sec / 60);
  if (min < 60) return min + "m ago";
  var hr = Math.floor(min / 60);
  if (hr < 24) return hr + "h ago";
  var days = Math.floor(hr / 24);
  return days + "d ago";
}

function timeAgo(isoStr) {
  if (!isoStr) return "";
  var d = new Date(isoStr);
  if (isNaN(d.getTime())) return "";
  var pad = function (n) {
    return n < 10 ? "0" + n : "" + n;
  };
  return (
    d.getFullYear() +
    "-" +
    pad(d.getMonth() + 1) +
    "-" +
    pad(d.getDate()) +
    " " +
    pad(d.getHours()) +
    ":" +
    pad(d.getMinutes()) +
    ":" +
    pad(d.getSeconds())
  );
}

function uptime(isoStr) {
  if (!isoStr) return "";
  var then = new Date(isoStr);
  if (isNaN(then.getTime())) return "";
  var diff = Math.floor((Date.now() - then.getTime()) / 1000);
  var h = Math.floor(diff / 3600);
  var m = Math.floor((diff % 3600) / 60);
  return h + "h " + m + "m";
}

/* REST helper -- Django uses CSRF + session auth, no token param */
function orochiHeaders() {
  var h = { "Content-Type": "application/json" };
  if (csrfToken) h["X-CSRFToken"] = csrfToken;
  return h;
}

/* token for API calls (Flask upstream or Django) */
var token =
  window.__orochiToken ||
  window.__orochiDashboardToken ||
  new URLSearchParams(location.search).get("token") ||
  "";

function apiUrl(path) {
  var base = window.__orochiApiUpstream || "";
  var sep = path.indexOf("?") === -1 ? "?" : "&";
  return base + path + (token ? sep + "token=" + token : "");
}

function sendOrochiMessage(msgData) {
  fetch(apiUrl("/api/messages/"), {
    method: "POST",
    headers: orochiHeaders(),
    body: JSON.stringify(msgData),
  })
    .then(function (res) {
      if (!res.ok) console.error("REST send failed:", res.status);
    })
    .catch(function (e) {
      console.error("REST send error:", e);
    });
}
