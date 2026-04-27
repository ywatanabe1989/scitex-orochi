/* Orochi Dashboard -- core globals, WS connection, init */

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

/* User display name */
var userName = localStorage.getItem("orochi_username");
if (!userName) {
  userName = prompt("Enter your display name for Orochi:", "");
  if (userName) {
    localStorage.setItem("orochi_username", userName);
  } else {
    userName = "human";
  }
}

function getAgentColor(name) {
  var s = name || "unknown";
  var sum = 0;
  for (var i = 0; i < s.length; i++) {
    sum += s.charCodeAt(i);
  }
  return OROCHI_COLORS[sum % OROCHI_COLORS.length];
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

/* WebSocket connection */
var wsProto = location.protocol === "https:" ? "wss:" : "ws:";
var token =
  window.__orochiToken ||
  new URLSearchParams(location.search).get("token") ||
  "";
var wsHost = window.__orochiWsUpstream
  ? window.__orochiWsUpstream.replace(/^https?:\/\//, "")
  : location.host;
var wsUrl = wsProto + "//" + wsHost + "/ws?token=" + token;
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

function sendOrochiMessage(msgData) {
  fetch((window.__orochiApiUpstream || "") + "/api/messages?token=" + token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(msgData),
  })
    .then(function (res) {
      if (!res.ok) console.error("REST send failed:", res.status);
    })
    .catch(function (e) {
      console.error("REST send error:", e);
    });
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
      var res = await fetch("/api/messages?limit=50");
      if (!res.ok) return;
      var messages = await res.json();
      messages.forEach(function (row) {
        var key = messageKey(row.sender, row.ts, row.content);
        if (knownMessageKeys[key]) return;
        knownMessageKeys[key] = true;
        appendMessage({
          type: "message",
          sender: row.sender,
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
    if (msg.payload) {
      content =
        msg.payload.content || msg.payload.text || msg.payload.message || "";
    }
    var key = messageKey(msg.sender, msg.ts, content);
    if (knownMessageKeys[key]) return;
    knownMessageKeys[key] = true;
    appendMessage(msg);
  } else if (msg.type === "presence_change" || msg.type === "status_update") {
    fetchAgentsThrottled();
    fetchStatsThrottled();
  }
}

function connect() {
  var statusEl = document.getElementById("conn-status");
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
    var res = await fetch("/api/agents");
    var agents = await res.json();
    var container = document.getElementById("agents");
    if (agents.length === 0) {
      container.innerHTML = '<p id="no-agents">No agents connected</p>';
      return;
    }
    /* Skip full DOM rebuild if agent data hasn't changed (#225) */
    var newAgentsJson = JSON.stringify(agents);
    if (container._lastAgentsJson === newAgentsJson) return;
    container._lastAgentsJson = newAgentsJson;
    container.innerHTML = agents
      .map(function (a) {
        var color = getAgentColor(a.name);
        var inactive = isAgentInactive(a);
        var statusClass =
          (a.status || "online") + (inactive ? " inactive" : "");
        var taskHtml = a.orochi_current_task
          ? '<div class="task">' + escapeHtml(a.orochi_current_task) + "</div>"
          : "";
        return (
          '<div class="agent-card' +
          (inactive ? " inactive" : "") +
          '" data-agent-name="' +
          escapeHtml(a.name) +
          '" style="border-left:3px solid ' +
          color +
          ';cursor:pointer">' +
          '<span class="status-dot ' +
          statusClass +
          '" style="background:' +
          (inactive ? "#555" : color) +
          '"></span>' +
          '<span class="name" style="color:' +
          (inactive ? "#666" : color) +
          '">' +
          escapeHtml(a.name) +
          (a.model
            ? ' <span style="color:#666;font-size:0.8em">(' +
              escapeHtml(a.model) +
              ")</span>"
            : "") +
          "</span>" +
          '<div class="meta">' +
          escapeHtml(a.machine || "unknown") +
          " / " +
          escapeHtml(a.role || "agent") +
          "</div>" +
          taskHtml +
          '<div class="meta">channels: ' +
          a.channels.map(escapeHtml).join(", ") +
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
    var res = await fetch("/api/stats");
    var stats = await res.json();
    document.getElementById("stat-agents").textContent = stats.agents_online;
    document.getElementById("stat-channels").textContent =
      stats.channels_active;
    document.getElementById("stat-observers").textContent =
      stats.observers_connected;
    var chContainer = document.getElementById("channels");
    var newStatsJson = JSON.stringify(stats.channels);
    if (chContainer._lastStatsJson === newStatsJson) return;
    chContainer._lastStatsJson = newStatsJson;
    chContainer.innerHTML = stats.channels
      .map(function (c, i) {
        var active = currentChannel === c ? " active" : "";
        var chColor = OROCHI_COLORS[i % OROCHI_COLORS.length];
        return (
          '<div class="channel-item' +
          active +
          '" data-channel="' +
          escapeHtml(c) +
          '" style="color:' +
          chColor +
          ";cursor:pointer" +
          (active ? ";font-weight:bold" : "") +
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
        tgStatus.style.color = "#4ecdc4";
      } else if (stats.telegram_bridge.enabled) {
        tgStatus.textContent = "stopped";
        tgStatus.style.color = "#ef4444";
      } else {
        tgEl.style.display = "none";
      }
    }
  } catch (e) {
    /* fetch error */
  }
}

/* Init is deferred to init.js (loaded after all modules) */
