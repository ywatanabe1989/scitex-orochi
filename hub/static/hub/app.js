/* Orochi Dashboard -- core globals, WS connection, sidebar (Django hub) */

/* System error banner — shown at top of page for critical errors */
function showSystemBanner(message, level) {
  var existing = document.getElementById("system-banner");
  if (existing) existing.remove();
  var banner = document.createElement("div");
  banner.id = "system-banner";
  banner.textContent = message;
  banner.style.cssText =
    "position:fixed;top:0;left:0;right:0;z-index:9999;padding:12px 20px;" +
    "text-align:center;font-weight:bold;font-size:14px;" +
    (level === "error"
      ? "background:#d32f2f;color:#fff;"
      : "background:#f57c00;color:#fff;");
  var close = document.createElement("span");
  close.textContent = " ✕";
  close.style.cssText = "cursor:pointer;margin-left:16px;";
  close.onclick = function () {
    banner.remove();
  };
  banner.appendChild(close);
  document.body.prepend(banner);
}

/* Yamata no Orochi color palette (from mascot icon heads) */
var OROCHI_COLORS = [
  "#C4A6E8",
  "#7EC8E3",
  "#FF9B9B",
  "#A8E6A3",
  "#FFD93D",
  "#FFB374",
  "#B8D4E3",
  "#E8A6C8",
];
/* Restored from localStorage on every page load so that ywatanabe stays
 * in the channel they were viewing across deploys, WS reconnects, and
 * any other re-render cascade. Persisted on every channel switch in
 * setCurrentChannel(). null = unfiltered (show all channels) which is
 * also persisted as the literal string "__all__". todo#246 / msg 6090. */
var currentChannel = null;
try {
  var _persistedCh = localStorage.getItem("orochi_active_channel");
  if (_persistedCh && _persistedCh !== "__all__") {
    currentChannel = _persistedCh;
  }
} catch (_) {}
function setCurrentChannel(ch) {
  currentChannel = ch;
  try {
    localStorage.setItem("orochi_active_channel", ch == null ? "__all__" : ch);
  } catch (_) {}
}
window.setCurrentChannel = setCurrentChannel;
var cachedAgentNames = [];
var historyLoaded = false;
var knownMessageKeys = {};
var unreadCount = 0;
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

/* Strip hostname suffix: "head@mba@Host" → "head@mba" */
function cleanAgentName(name) {
  if (!name) return name;
  var parts = name.split("@");
  if (parts.length >= 3) {
    return parts[0] + "@" + parts[1];
  }
  return name;
}

/**
 * Return the agent name with host suffix. If the registered name already
 * contains @host (e.g. "head@mba"), return as-is. Otherwise append
 * "@<machine>" from the agent record so the sidebar always shows an
 * identity tied to a host (mamba shows as "mamba@ywata-note-win" even if
 * the agent config still registered plain "mamba").
 */
function hostedAgentName(a) {
  var name = a && a.name ? a.name : "";
  if (!name) return name;
  if (name.indexOf("@") !== -1) return cleanAgentName(name);
  var host = a && a.machine ? a.machine : "";
  return host ? name + "@" + host : name;
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

/* WebSocket connection */
var ws;
var wsConnected = false;
var restPollTimer = null;
var restPollInterval = 5000;

/* fetchAgents throttle — prevents focus theft on rapid WS events (#225) */
var _fetchAgentsTimer = null;
var _fetchAgentsPending = false;
var FETCH_AGENTS_THROTTLE_MS = 2000;

function fetchAgentsThrottled() {
  if (_fetchAgentsTimer) {
    _fetchAgentsPending = true;
    return;
  }
  fetchAgents();
  _fetchAgentsTimer = setTimeout(function () {
    _fetchAgentsTimer = null;
    if (_fetchAgentsPending) {
      _fetchAgentsPending = false;
      fetchAgentsThrottled();
    }
  }, FETCH_AGENTS_THROTTLE_MS);
}

var _fetchStatsTimer = null;
var _fetchStatsPending = false;

function fetchStatsThrottled() {
  if (_fetchStatsTimer) {
    _fetchStatsPending = true;
    return;
  }
  fetchStats();
  _fetchStatsTimer = setTimeout(function () {
    _fetchStatsTimer = null;
    if (_fetchStatsPending) {
      _fetchStatsPending = false;
      fetchStatsThrottled();
    }
  }, FETCH_AGENTS_THROTTLE_MS);
}

function startRestPolling() {
  if (restPollTimer) return;
  restPollTimer = setInterval(async function () {
    if (wsConnected) return;
    try {
      var res = await fetch(apiUrl("/api/messages/?limit=50"), {
        credentials: "same-origin",
      });
      if (!res.ok) return;
      var messages = await res.json();
      /* API returns newest-first; reverse so new messages append chronologically */
      messages.reverse();
      messages.forEach(function (row) {
        var key = messageKey(row.sender, row.ts, row.content);
        if (knownMessageKeys[key]) return;
        knownMessageKeys[key] = true;
        appendMessage({
          type: "message",
          sender: row.sender,
          sender_type: row.sender_type,
          ts: row.ts,
          payload: {
            channel: row.channel,
            content: row.content,
            attachments:
              (row.metadata && row.metadata.attachments) ||
              row.attachments ||
              [],
          },
        });
      });
    } catch (e) {
      console.warn("REST poll failed:", e);
    }
    fetchAgentsThrottled();
    fetchStats();
  }, restPollInterval);
}

function stopRestPolling() {
  if (restPollTimer) {
    clearInterval(restPollTimer);
    restPollTimer = null;
  }
}

function handleMessage(msg) {
  if (msg.type === "message") {
    var content = "";
    /* Hub sends flat messages: {type, sender, channel, text, ts, metadata} */
    if (msg.text || msg.channel) {
      content = msg.text || "";
      if (!msg.payload) {
        var attachments = (msg.metadata && msg.metadata.attachments) || [];
        msg.payload = {
          channel: msg.channel || "",
          content: content,
          metadata: msg.metadata || {},
          attachments: attachments,
        };
      }
    } else if (msg.payload) {
      content =
        msg.payload.content || msg.payload.text || msg.payload.message || "";
    }
    var key = messageKey(msg.sender, msg.ts, content);
    if (knownMessageKeys[key]) return;
    knownMessageKeys[key] = true;
    appendMessage(msg);
    /* If this message is a reply and the matching thread panel is open,
     * also live-append it there (deduped by reply id). */
    if (typeof appendToThreadPanelIfOpen === "function") {
      appendToThreadPanelIfOpen(msg);
    }
    if (document.hidden) {
      unreadCount++;
      document.title = "(" + unreadCount + ") " + baseTitle;
    }
  } else if (msg.type === "system_message") {
    if (typeof appendSystemMessage === "function") {
      appendSystemMessage(msg);
    }
  } else if (
    msg.type === "presence_change" ||
    msg.type === "status_update" ||
    msg.type === "agent_presence" ||
    msg.type === "agent_info"
  ) {
    fetchAgentsThrottled();
    fetchStatsThrottled();
    fetchResources();
  } else if (msg.type === "reaction_update") {
    if (typeof handleReactionUpdate === "function") handleReactionUpdate(msg);
  } else if (msg.type === "thread_reply") {
    if (typeof handleThreadReply === "function") handleThreadReply(msg);
  } else if (msg.type === "message_edit") {
    if (typeof handleMessageEdit === "function") handleMessageEdit(msg);
  } else if (msg.type === "message_delete") {
    if (typeof handleMessageDelete === "function") handleMessageDelete(msg);
  }
}

/* Reset unread count when tab becomes visible */
document.addEventListener("visibilitychange", function () {
  if (!document.hidden) {
    unreadCount = 0;
    document.title = baseTitle;
  }
});

function connect() {
  var statusEl = document.getElementById("conn-status");
  /* Build WS URL: prefer Django WS, fallback to upstream or auto-detect */
  var wsUrl;
  if (window.__orochiWsUrl) {
    wsUrl = window.__orochiWsUrl;
    /* Append token if not already present (fallback for stripped cookies) */
    if (token && wsUrl.indexOf("token=") === -1) {
      wsUrl += (wsUrl.indexOf("?") === -1 ? "?" : "&") + "token=" + token;
    }
  } else {
    var wsProto = location.protocol === "https:" ? "wss:" : "ws:";
    var wsHost = window.__orochiWsUpstream
      ? window.__orochiWsUpstream.replace(/^https?:\/\//, "")
      : location.host;
    wsUrl = wsProto + "//" + wsHost + "/ws";
    if (token) wsUrl += "?token=" + token;
  }
  try {
    ws = new WebSocket(wsUrl);
  } catch (e) {
    console.warn("WebSocket constructor failed:", e);
    statusEl.textContent = "polling";
    statusEl.className = "status conn-poll";
    statusEl.title = "WebSocket unavailable — falling back to REST polling";
    startRestPolling();
    return;
  }
  ws.onopen = function () {
    wsConnected = true;
    /* Compact, muted when fine; state class drives the styling */
    statusEl.textContent = "";
    statusEl.title = "Connected to Orochi server";
    statusEl.className = "status conn-ok";
    stopRestPolling();
    fetchStats();
    fetchAgents();
    /* On reconnect (historyLoaded=true), fetch only new messages
     * incrementally instead of doing a full DOM rebuild.  A full
     * loadHistory() on mobile Safari causes massive innerHTML churn
     * that can reset the textarea value / dismiss the keyboard while
     * the user is typing. */
    if (historyLoaded) {
      fetchNewMessages();
    } else {
      loadHistory();
    }
  };
  ws.onclose = function (event) {
    wsConnected = false;
    statusEl.textContent = "disconnected";
    statusEl.className = "status conn-down";
    startRestPolling();
    if (event.code === 4001) {
      statusEl.title = "Session expired — please log in again";
      showSystemBanner(
        "Session expired. Please reload and log in again.",
        "error",
      );
    } else if (event.code === 4003) {
      statusEl.title = "No access to this workspace";
      showSystemBanner("Access denied to this workspace.", "error");
    } else if (event.code === 4004) {
      statusEl.title = "Workspace not found";
      showSystemBanner("Workspace not found.", "error");
    } else {
      statusEl.title = "Disconnected — retrying every 3s";
      statusEl.textContent = "reconnecting";
      setTimeout(connect, 3000);
    }
  };
  ws.onerror = function () {
    if (!wsConnected) startRestPolling();
  };
  ws.onmessage = function (event) {
    try {
      handleMessage(JSON.parse(event.data));
    } catch (e) {
      console.error(
        "[orochi-ws] message handling error:",
        e,
        "raw:",
        event.data.substring(0, 200),
      );
    }
  };
}
/* Sidebar agents + stats fetching */
async function fetchAgents() {
  try {
    var res = await fetch(apiUrl("/api/agents"));
    var agents = await res.json();
    /* Cache for the Activity tab and other consumers */
    window.__lastAgents = agents;
    if (typeof renderActivityTab === "function") renderActivityTab();
    var container = document.getElementById("agents");
    /* Focus guard — see todo#225. This path fires on every WS
     * presence/status event and on REST poll; mobile Safari can blur
     * the compose textarea on large innerHTML swaps. */
    var msgInput = document.getElementById("msg-input");
    var inputHasFocus = msgInput && document.activeElement === msgInput;
    var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
    var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
    if (agents.length === 0) {
      container.innerHTML = '<p id="no-agents">No agents connected</p>';
      var cEl = document.getElementById("sidebar-count-agents");
      if (cEl) cEl.textContent = "";
      if (inputHasFocus && document.activeElement !== msgInput) {
        msgInput.focus();
        try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (e) {}
      }
      return;
    }
    var cEl = document.getElementById("sidebar-count-agents");
    if (cEl) cEl.textContent = "(" + agents.length + ")";
    agents.forEach(function (a) {
      cacheAgentIcons([a]);
    });
    /* Skip full DOM rebuild if agent data hasn't changed (#225) */
    var newAgentsJson = JSON.stringify(agents);
    if (container._lastAgentsJson === newAgentsJson) return;
    container._lastAgentsJson = newAgentsJson;
    /* Preserve Ctrl+Click multi-select state across re-renders (#274 Part 2).
     * Without this, every fetchAgents() poll/WS presence event clobbers
     * .selected on agent-cards, defeating multi-select. */
    var prevSelectedAgents = {};
    container
      .querySelectorAll(".agent-card.selected[data-agent-name]")
      .forEach(function (el) {
        var n = el.getAttribute("data-agent-name");
        if (n) prevSelectedAgents[n] = true;
      });
    /* todo#320: sidebar agent cards are now compact — name + status
     * dot only. Full detail (badges, kill/pin/restart, task rows,
     * detail popup, health pill, tooltip) lives in the Agents tab. */
    container.innerHTML = agents
      .map(function (a) {
        var inactive = isAgentInactive(a);
        var liveness = a.liveness || (inactive ? "offline" : "online");
        var statusClassCompact = liveness === "online" ? "online" : "offline";
        var tooltip = (a.agent_id || a.name) + " (" + (a.machine || "unknown") + ")";
        return (
          '<div class="agent-card sidebar-compact' +
          (inactive ? " inactive" : "") +
          '" data-agent-name="' +
          escapeHtml(a.name) +
          '" title="' +
          escapeHtml(tooltip) +
          '">' +
          '<span class="agent-status ' +
          statusClassCompact +
          '"></span>' +
          '<span class="agent-name">' +
          escapeHtml(hostedAgentName(a)) +
          "</span>" +
          "</div>"
        );
      })
      .join("");
    container
      .querySelectorAll(".agent-card[data-agent-name]")
      .forEach(function (el) {
        /* Restore .selected from before re-render (#274 Part 2) */
        var elName = el.getAttribute("data-agent-name");
        if (elName && prevSelectedAgents[elName]) el.classList.add("selected");
        el.addEventListener("click", function (ev) {
          if (ev.target.closest(".pin-btn")) return; /* handled separately */
          if (ev.target.closest(".kill-btn")) return; /* handled separately */
          if (ev.target.closest(".restart-btn")) return; /* handled separately */
          if (ev.target.closest(".avatar-clickable"))
            return; /* handled below */
          var multi = ev.ctrlKey || ev.metaKey;
          /* todo#274 Part 2: Ctrl/Cmd+Click toggles multi-select. */
          if (multi) {
            el.classList.toggle("selected");
          } else {
            /* todo#274 Part 1: single-select highlight (toggle on 2nd click). */
            var cards = container.querySelectorAll(".agent-card[data-agent-name]");
            var wasSelected = el.classList.contains("selected");
            cards.forEach(function (c) { c.classList.remove("selected"); });
            if (!wasSelected) el.classList.add("selected");
          }
          if (typeof applyFeedFilter === "function") applyFeedFilter();
        });
      });
    container
      .querySelectorAll(".pin-btn[data-pin-name]")
      .forEach(function (btn) {
        btn.addEventListener("click", function (ev) {
          ev.stopPropagation();
          togglePinAgent(
            btn.getAttribute("data-pin-name"),
            !btn.classList.contains("pinned"),
          );
        });
      });
    container
      .querySelectorAll(".avatar-clickable[data-avatar-agent]")
      .forEach(function (el) {
        el.addEventListener("click", function (ev) {
          ev.stopPropagation();
          openAvatarPicker(el.getAttribute("data-avatar-agent"));
        });
      });
    container
      .querySelectorAll(".kill-btn[data-kill-name]")
      .forEach(function (btn) {
        btn.addEventListener("click", function (ev) {
          ev.stopPropagation();
          killAgent(btn.getAttribute("data-kill-name"), btn);
        });
      });
    container
      .querySelectorAll(".restart-btn[data-restart-name]")
      .forEach(function (btn) {
        btn.addEventListener("click", function (ev) {
          ev.stopPropagation();
          restartAgent(btn.getAttribute("data-restart-name"), btn);
        });
      });
    if (inputHasFocus && document.activeElement !== msgInput) {
      msgInput.focus();
      try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (e) {}
    }
  } catch (e) {
    /* fetch error */
  }
}

async function restartAgent(name, btn) {
  if (!confirm("Restart agent " + name + "?")) return;
  var origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "\u23F3";
  btn.classList.add("restarting");
  try {
    var headers = orochiHeaders();
    var res = await fetch(apiUrl("/api/agents/restart/"), {
      method: "POST",
      headers: headers,
      credentials: "same-origin",
      body: JSON.stringify({ name: name }),
    });
    var data = await res.json();
    if (res.ok) {
      btn.textContent = "\u2713";
      setTimeout(function () {
        btn.textContent = origText;
        btn.disabled = false;
        btn.classList.remove("restarting");
        fetchAgents();
      }, 3000);
    } else {
      btn.textContent = "\u2717";
      console.error("Restart failed:", data.error || res.status);
      setTimeout(function () {
        btn.textContent = origText;
        btn.disabled = false;
        btn.classList.remove("restarting");
      }, 3000);
    }
  } catch (e) {
    console.error("Restart error:", e);
    btn.textContent = origText;
    btn.disabled = false;
    btn.classList.remove("restarting");
  }
}

async function killAgent(name, btn) {
  if (!confirm("Kill agent " + name + "?\nThis will terminate screen, bun sidecar, and disconnect.")) return;
  var origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "\u23F3";
  btn.classList.add("killing");
  try {
    var headers = orochiHeaders();
    var res = await fetch(apiUrl("/api/agents/kill/"), {
      method: "POST",
      headers: headers,
      credentials: "same-origin",
      body: JSON.stringify({ name: name }),
    });
    var data = await res.json();
    if (res.ok) {
      btn.textContent = "\u2713";
      setTimeout(function () {
        btn.textContent = origText;
        btn.disabled = false;
        btn.classList.remove("killing");
        fetchAgents();
      }, 2000);
    } else {
      btn.textContent = "\u2717";
      console.error("Kill failed:", data.error || res.status);
      setTimeout(function () {
        btn.textContent = origText;
        btn.disabled = false;
        btn.classList.remove("killing");
      }, 3000);
    }
  } catch (e) {
    console.error("Kill error:", e);
    btn.textContent = origText;
    btn.disabled = false;
    btn.classList.remove("killing");
  }
}

async function togglePinAgent(name, shouldPin) {
  try {
    var token = window.__orochiCsrfToken || "";
    var headers = { "Content-Type": "application/json" };
    if (token) headers["X-CSRFToken"] = token;
    var method = shouldPin ? "POST" : "DELETE";
    var res = await fetch(apiUrl("/api/agents/pin/"), {
      method: method,
      headers: headers,
      credentials: "same-origin",
      body: JSON.stringify({ name: name }),
    });
    if (res.ok) {
      fetchAgents();
    } else {
      console.error("Pin/unpin failed:", res.status);
    }
  } catch (e) {
    console.error("Pin/unpin error:", e);
  }
}

async function fetchStats() {
  try {
    var res = await fetch(apiUrl("/api/stats"));
    var stats = await res.json();
    var chContainer = document.getElementById("channels");
    var newStatsJson = JSON.stringify(stats.channels);
    if (chContainer._lastStatsJson === newStatsJson) return;
    chContainer._lastStatsJson = newStatsJson;
    var msgInput = document.getElementById("msg-input");
    var inputHasFocus = msgInput && document.activeElement === msgInput;
    var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
    var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
    /* Preserve Ctrl+Click multi-select state across re-renders (#274 Part 2) */
    var prevSelected = {};
    chContainer.querySelectorAll(".channel-item.selected").forEach(function (el) {
      var ch = el.getAttribute("data-channel");
      if (ch) prevSelected[ch] = true;
    });
    /* todo#325: hide dm:* channels from the public Channels list
     * (they still render in the DM tab via its own path).
     * todo#326: normalize "general" -> "#general" and dedupe by
     * normalized name so legacy rows collapse into a single entry. */
    var seenNames = {};
    var displayChannels = [];
    stats.channels.forEach(function (c) {
      if (typeof c !== "string") return;
      if (c.indexOf("dm:") === 0) return;
      var norm = c.charAt(0) === "#" ? c : "#" + c;
      if (seenNames[norm]) return;
      seenNames[norm] = true;
      displayChannels.push({ raw: c, norm: norm });
    });
    chContainer.innerHTML = displayChannels
      .map(function (entry, i) {
        var c = entry.raw;
        var active = currentChannel === c ? " active" : "";
        var chColor = OROCHI_COLORS[i % OROCHI_COLORS.length];
        return (
          '<div class="channel-item' +
          active +
          '" data-channel="' +
          escapeHtml(c) +
          '">' +
          escapeHtml(entry.norm) +
          "</div>"
        );
      })
      .join("");
    chContainer.querySelectorAll(".channel-item").forEach(function (el) {
      /* Restore selected state from before re-render */
      var elCh = el.getAttribute("data-channel");
      if (elCh && prevSelected[elCh]) el.classList.add("selected");
      el.addEventListener("click", function (ev) {
        var ch = el.getAttribute("data-channel");
        var multi = ev.ctrlKey || ev.metaKey;
        /* todo#274 Part 2: Ctrl/Cmd+Click toggles multi-select without
         * disturbing siblings; plain click keeps legacy single-select. */
        if (multi) {
          el.classList.toggle("selected");
          if (typeof applyFeedFilter === "function") applyFeedFilter();
          return;
        }
        if (currentChannel === ch) {
          setCurrentChannel(null);
          loadHistory();
        } else {
          setCurrentChannel(ch);
          loadChannelHistory(ch);
        }
        /* todo#274 Part 1: pure visual highlight, toggle on second click. */
        var items = chContainer.querySelectorAll(".channel-item");
        var wasSelected = el.classList.contains("selected");
        items.forEach(function (it) { it.classList.remove("selected"); });
        if (!wasSelected && currentChannel === ch) {
          el.classList.add("selected");
        }
        if (typeof applyFeedFilter === "function") applyFeedFilter();
        fetchStats();
      });
    });
    var chCountEl = document.getElementById("sidebar-count-channels");
    if (chCountEl) chCountEl.textContent = "(" + displayChannels.length + ")";
    if (inputHasFocus && document.activeElement !== msgInput) {
      msgInput.focus();
      try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
    }
  } catch (e) {
    /* fetch error */
  }
}
/* Init is deferred to init.js (loaded after all modules) */

/* Global ESC handler — close any visible popups/modals (#207) */
document.addEventListener("keydown", function (e) {
  if (e.key !== "Escape") return;
  if (typeof closeEmojiPicker === "function") {
    var emojiOverlay = document.querySelector(".emoji-picker-overlay.visible");
    if (emojiOverlay) { closeEmojiPicker(); e.preventDefault(); return; }
  }
  if (typeof closeThreadPanel === "function") {
    var threadPanel = document.querySelector(".thread-panel.open");
    if (threadPanel) { closeThreadPanel(); e.preventDefault(); return; }
  }
  if (typeof closeSketchPanel === "function") {
    var sketchPanel = document.querySelector(".sketch-panel.open");
    if (sketchPanel) { closeSketchPanel(); e.preventDefault(); return; }
  }
  var generic = document.querySelector(".emoji-picker-overlay.visible, .modal.open, .popup.visible, .long-press-menu");
  if (generic) {
    generic.classList.remove("visible", "open");
    if (generic.classList.contains("long-press-menu")) generic.remove();
    e.preventDefault();
  }
});
