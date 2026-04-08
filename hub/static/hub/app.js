/* Orochi Dashboard -- core globals, WS connection, sidebar (Django hub) */

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

/* Inline SVG icon generators for branding */
function getSnakeIcon(size, color) {
  size = size || 20;
  color = color || "#4ecdc4";
  return (
    '<svg class="orochi-icon" width="' +
    size +
    '" height="' +
    size +
    '" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">' +
    '<path d="M12 2C8 2 6 4 6 6c0 2 1 3 2 3.5C7 10 5 11 5 13c0 2.5 2 4 4 4.5-.5.5-1 1.5-1 3 0 1 .5 1.5 1.5 1.5s2-.5 2.5-1.5c.5 1 1.5 1.5 2.5 1.5s1.5-.5 1.5-1.5c0-1.5-.5-2.5-1-3 2-.5 4-2 4-4.5 0-2-2-3-3-3.5 1-.5 2-1.5 2-3.5 0-2-2-4-6-4z" ' +
    'fill="' +
    color +
    '" opacity="0.9"/>' +
    '<circle cx="10" cy="6" r="1" fill="#0a0a0a"/>' +
    '<circle cx="14" cy="6" r="1" fill="#0a0a0a"/>' +
    '<path d="M10 9c0 0 1 1.5 2 1.5s2-1.5 2-1.5" stroke="#0a0a0a" stroke-width="0.7" fill="none" stroke-linecap="round"/>' +
    "</svg>"
  );
}

function getPersonIcon(size, color) {
  size = size || 20;
  color = color || "#c4a6e8";
  return (
    '<svg class="orochi-icon" width="' +
    size +
    '" height="' +
    size +
    '" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">' +
    '<circle cx="12" cy="8" r="4" fill="' +
    color +
    '" opacity="0.9"/>' +
    '<path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" fill="' +
    color +
    '" opacity="0.7"/>' +
    "</svg>"
  );
}

function getSenderIcon(senderName, isAgent) {
  if (isAgent) {
    return getSnakeIcon(18, getAgentColor(senderName));
  }
  return getPersonIcon(18, "#c4a6e8");
}

/* Large snake logo for header branding */
function getSnakeLogo() {
  return getSnakeIcon(32, "#4ecdc4");
}

function escapeHtml(s) {
  var d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
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
  var then = new Date(isoStr);
  if (isNaN(then.getTime())) return "";
  var diff = Math.floor((Date.now() - then.getTime()) / 1000);
  if (diff < 60) return diff + "s ago";
  if (diff < 3600) return Math.floor(diff / 60) + "m ago";
  if (diff < 86400) return Math.floor(diff / 3600) + "h ago";
  return Math.floor(diff / 86400) + "d ago";
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
    /* Hub sends flat messages: {type, sender, channel, text, ts} */
    if (msg.text || msg.channel) {
      content = msg.text || "";
      if (!msg.payload) {
        msg.payload = {
          channel: msg.channel || "",
          content: content,
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
  } else if (
    msg.type === "presence_change" ||
    msg.type === "status_update" ||
    msg.type === "agent_presence" ||
    msg.type === "agent_info"
  ) {
    fetchAgents();
    fetchStats();
  }
}

function connect() {
  var statusEl = document.getElementById("conn-status");
  /* Build WS URL: prefer Django WS, fallback to upstream or auto-detect */
  var wsUrl;
  if (window.__orochiWsUrl) {
    wsUrl = window.__orochiWsUrl;
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
    statusEl.textContent = "ws: polling";
    statusEl.classList.remove("connected");
    statusEl.classList.add("rest-mode");
    startRestPolling();
    return;
  }
  ws.onopen = function () {
    wsConnected = true;
    statusEl.textContent = "ws: live";
    statusEl.classList.add("connected");
    statusEl.classList.remove("rest-mode");
    stopRestPolling();
    fetchStats();
    fetchAgents();
    loadHistory();
  };
  ws.onclose = function () {
    wsConnected = false;
    statusEl.textContent = "ws: polling";
    statusEl.classList.remove("connected");
    statusEl.classList.add("rest-mode");
    startRestPolling();
    setTimeout(connect, 3000);
  };
  ws.onerror = function () {
    if (!wsConnected) startRestPolling();
  };
  ws.onmessage = function (event) {
    try {
      handleMessage(JSON.parse(event.data));
    } catch (e) {
      /* ignore parse errors */
    }
  };
}

/* Sidebar agents + stats fetching */
async function fetchAgents() {
  try {
    var res = await fetch(apiUrl("/api/agents"));
    var agents = await res.json();
    var container = document.getElementById("agents");
    if (agents.length === 0) {
      container.innerHTML = '<p id="no-agents">No agents connected</p>';
      return;
    }
    container.innerHTML = agents
      .map(function (a) {
        var color = getAgentColor(a.name);
        var inactive = isAgentInactive(a);
        var statusClass =
          (a.status || "online") + (inactive ? " inactive" : "");
        var taskHtml = a.current_task
          ? '<div class="task">' + escapeHtml(a.current_task) + "</div>"
          : "";
        var agentIcon = getSnakeIcon(16, color);
        return (
          '<div class="agent-card' +
          (inactive ? " inactive" : "") +
          '" data-agent-name="' +
          escapeHtml(a.name) +
          '">' +
          '<span class="agent-card-icon">' +
          agentIcon +
          "</span>" +
          '<span class="status-dot ' +
          statusClass +
          '"></span>' +
          '<span class="name">' +
          escapeHtml(a.name) +
          (a.model
            ? ' <span class="meta">(' + escapeHtml(a.model) + ")</span>"
            : "") +
          "</span>" +
          '<div class="meta">' +
          escapeHtml(a.machine || "unknown") +
          " / " +
          escapeHtml(a.role || "agent") +
          "</div>" +
          taskHtml +
          '<div class="meta">channels: ' +
          [...new Set(a.channels)].map(escapeHtml).join(", ") +
          "</div></div>"
        );
      })
      .join("");
    container
      .querySelectorAll(".agent-card[data-agent-name]")
      .forEach(function (el) {
        el.addEventListener("click", function () {
          addTag("agent", el.getAttribute("data-agent-name"));
        });
      });
  } catch (e) {
    /* fetch error */
  }
}

async function fetchStats() {
  try {
    var res = await fetch(apiUrl("/api/stats"));
    var stats = await res.json();
    document.getElementById("stat-agents").textContent = stats.agents_online;
    document.getElementById("stat-channels").textContent =
      stats.channels_active;
    document.getElementById("stat-observers").textContent =
      stats.observers_connected;
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
        fetchStats();
      });
    });
    updateChannelSelect(stats.channels);
    var tgEl = document.getElementById("stat-telegram");
    var tgStatus = document.getElementById("stat-telegram-status");
    if (stats.telegram_bridge && tgEl && tgStatus) {
      tgEl.style.display = "";
      if (stats.telegram_bridge.running) {
        tgStatus.textContent = "\u2713";
      } else if (stats.telegram_bridge.enabled) {
        tgStatus.textContent = "stopped";
      } else {
        tgEl.style.display = "none";
      }
    }
  } catch (e) {
    /* fetch error */
  }
}

/* Init is deferred to init.js (loaded after all modules) */
