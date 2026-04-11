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
var currentChannel = null;
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
    fetchAgents();
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
    fetchAgents();
    fetchStats();
    fetchResources();
  } else if (msg.type === "reaction_update") {
    if (typeof handleReactionUpdate === "function") handleReactionUpdate(msg);
  } else if (msg.type === "thread_reply") {
    if (typeof handleThreadReply === "function") handleThreadReply(msg);
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
    loadHistory();
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
    if (agents.length === 0) {
      container.innerHTML = '<p id="no-agents">No agents connected</p>';
      var cEl = document.getElementById("sidebar-count-agents");
      if (cEl) cEl.textContent = "";
      return;
    }
    var cEl = document.getElementById("sidebar-count-agents");
    if (cEl) cEl.textContent = "(" + agents.length + ")";
    agents.forEach(function (a) {
      cacheAgentIcons([a]);
    });
    container.innerHTML = agents
      .map(function (a) {
        var color = getResolvedAgentColor(a.name);
        var inactive = isAgentInactive(a);
        var statusClass =
          (a.status || "online") + (inactive ? " inactive" : "");
        var agentIcon = getSenderIcon(a.name, true, 32);
        /* Tiny health pill — mirrors the Agents tab classification. */
        var healthHtml = "";
        if (a.health && a.health.status) {
          var hs = String(a.health.status);
          var hReason = a.health.reason
            ? ' title="' + escapeHtml(a.health.reason) + '"'
            : "";
          healthHtml =
            '<span class="sidebar-health sidebar-health-' +
            escapeHtml(hs) +
            '"' +
            hReason +
            ">\uD83E\uDE7A " +
            escapeHtml(hs) +
            "</span>";
        }
        var pinIcon = a.pinned ? "\uD83D\uDCCC" : "\uD83D\uDCCD";
        var pinTitle = a.pinned ? "Unpin agent" : "Pin agent";
        var pinBtnHtml =
          '<button class="pin-btn' +
          (a.pinned ? " pinned" : "") +
          '" data-pin-name="' +
          escapeHtml(a.name) +
          '" title="' +
          pinTitle +
          '">' +
          pinIcon +
          "</button>";
        /* Compact badges for role + machine */
        var roleBadge =
          '<span class="agent-badge agent-badge-role">' +
          escapeHtml(a.role || "agent") +
          "</span>";
        var machineBadge =
          '<span class="agent-badge agent-badge-machine">' +
          escapeHtml(a.machine || "unknown") +
          "</span>";
        /* Tooltip metadata (shown on hover) */
        var uniqueChannels = [...new Set(a.channels || [])];
        var tooltipLines = [];
        tooltipLines.push("Agent ID: " + (a.agent_id || a.name));
        tooltipLines.push("Role: " + (a.role || "agent"));
        tooltipLines.push("Host: " + (a.machine || "unknown"));
        if (a.model) tooltipLines.push("Model: " + a.model);
        if (uniqueChannels.length)
          tooltipLines.push("Channels: " + uniqueChannels.join(", "));
        if (a.project) tooltipLines.push("Project: " + a.project);
        if (a.workdir)
          tooltipLines.push(
            "Workdir: " + a.workdir.replace(/^\/home\/[^/]+/, "~"),
          );
        if (a.current_task) tooltipLines.push("Task: " + a.current_task);
        /* Popup detail panel (click to expand) */
        var detailHtml =
          '<div class="agent-detail-popup">' +
          '<div class="agent-detail-row"><span class="agent-detail-label">Channels</span>' +
          (uniqueChannels.length
            ? uniqueChannels
                .map(function (c) {
                  return '<span class="ch-badge">' + escapeHtml(c) + "</span>";
                })
                .join(" ")
            : '<span class="muted-cell">-</span>') +
          "</div>" +
          (a.model
            ? '<div class="agent-detail-row"><span class="agent-detail-label">Model</span>' +
              escapeHtml(a.model) +
              "</div>"
            : "") +
          (a.project
            ? '<div class="agent-detail-row"><span class="agent-detail-label">Project</span>' +
              escapeHtml(a.project) +
              "</div>"
            : "") +
          (a.workdir
            ? '<div class="agent-detail-row"><span class="agent-detail-label">Workdir</span><span class="monospace-cell">' +
              escapeHtml(a.workdir.replace(/^\/home\/[^/]+/, "~")) +
              "</span></div>"
            : "") +
          (a.current_task
            ? '<div class="agent-detail-row"><span class="agent-detail-label">Task</span>' +
              escapeHtml(a.current_task) +
              "</div>"
            : "") +
          "</div>";
        return (
          '<div class="agent-card' +
          (inactive ? " inactive" : "") +
          (a.pinned && inactive ? " pinned-offline" : "") +
          '" data-agent-name="' +
          escapeHtml(a.name) +
          '" title="' +
          escapeHtml(tooltipLines.join("\n")) +
          '">' +
          '<div class="agent-card-top">' +
          '<span class="agent-card-icon avatar-clickable" data-avatar-agent="' +
          escapeHtml(a.name) +
          '" title="Click to change avatar">' +
          agentIcon +
          "</span>" +
          '<span class="status-dot ' +
          statusClass +
          '"></span>' +
          '<span class="name">' +
          escapeHtml(hostedAgentName(a)) +
          "</span>" +
          pinBtnHtml +
          "</div>" +
          '<div class="agent-card-badges">' +
          roleBadge +
          machineBadge +
          healthHtml +
          "</div>" +
          detailHtml +
          "</div>"
        );
      })
      .join("");
    container
      .querySelectorAll(".agent-card[data-agent-name]")
      .forEach(function (el) {
        el.addEventListener("click", function (ev) {
          if (ev.target.closest(".pin-btn")) return; /* handled separately */
          if (ev.target.closest(".avatar-clickable"))
            return; /* handled below */
          /* Toggle detail popup on click */
          var popup = el.querySelector(".agent-detail-popup");
          if (popup) {
            var isOpen = popup.classList.contains("open");
            /* Close all others first */
            container
              .querySelectorAll(".agent-detail-popup.open")
              .forEach(function (p) {
                p.classList.remove("open");
              });
            if (!isOpen) popup.classList.add("open");
          }
          addTag("agent", el.getAttribute("data-agent-name"));
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
  } catch (e) {
    /* fetch error */
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
    chContainer.innerHTML = stats.channels
      .map(function (c, i) {
        var active = currentChannel === c ? " active" : "";
        var chColor = OROCHI_COLORS[i % OROCHI_COLORS.length];
        return (
          '<div class="channel-item' +
          active +
          '" data-channel="' +
          escapeHtml(c) +
          '">' +
          escapeHtml(c) +
          "</div>"
        );
      })
      .join("");
    chContainer.querySelectorAll(".channel-item").forEach(function (el) {
      el.addEventListener("click", function () {
        var ch = el.getAttribute("data-channel");
        if (currentChannel === ch) {
          currentChannel = null;
          loadHistory();
        } else {
          currentChannel = ch;
          loadChannelHistory(ch);
        }
        addTag("channel", ch);
        fetchStats();
      });
    });
    var chCountEl = document.getElementById("sidebar-count-channels");
    if (chCountEl) chCountEl.textContent = "(" + stats.channels.length + ")";
  } catch (e) {
    /* fetch error */
  }
}
/* Init is deferred to init.js (loaded after all modules) */
