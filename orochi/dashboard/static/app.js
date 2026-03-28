/* Orochi Dashboard -- WebSocket observer client */

/* Yamata no Orochi color palette (from mascot icon heads) */
var OROCHI_COLORS = [
  "#C4A6E8" /* purple */,
  "#7EC8E3" /* light blue */,
  "#FF9B9B" /* pink */,
  "#A8E6A3" /* green */,
  "#FFD93D" /* yellow */,
  "#FFB374" /* orange */,
  "#B8D4E3" /* ice blue */,
  "#E8A6C8" /* rose */,
];
var currentChannel = null;

function getAgentColor(name) {
  var s = name || "unknown";
  var sum = 0;
  for (var i = 0; i < s.length; i++) {
    sum += s.charCodeAt(i);
  }
  return OROCHI_COLORS[sum % OROCHI_COLORS.length];
}

var wsProto = location.protocol === "https:" ? "wss:" : "ws:";
var token = new URLSearchParams(location.search).get("token") || "";
var wsUrl = wsProto + "//" + location.host + "/ws?token=" + token;
var ws;

function escapeHtml(s) {
  var d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function connect() {
  ws = new WebSocket(wsUrl);
  var statusEl = document.getElementById("conn-status");

  ws.onopen = function () {
    statusEl.textContent = "connected";
    statusEl.classList.add("connected");
    fetchStats();
    fetchAgents();
    loadHistory();
  };

  ws.onclose = function () {
    statusEl.textContent = "disconnected";
    statusEl.classList.remove("connected");
    setTimeout(connect, 3000);
  };

  ws.onmessage = function (event) {
    try {
      var msg = JSON.parse(event.data);
      handleMessage(msg);
    } catch (e) {
      /* ignore parse errors */
    }
  };
}

function handleMessage(msg) {
  if (msg.type === "message") {
    appendMessage(msg);
  } else if (msg.type === "presence_change" || msg.type === "status_update") {
    fetchAgents();
    fetchStats();
  }
}

function appendMessage(msg) {
  var el = document.createElement("div");
  el.className = "msg";
  var ts = "";
  if (msg.ts) {
    var d = new Date(msg.ts);
    ts = isNaN(d.getTime()) ? "" : d.toLocaleTimeString();
  }
  var channel = (msg.payload && msg.payload.channel) || "";
  var content = "";
  if (msg.payload) {
    content =
      msg.payload.content || msg.payload.text || msg.payload.message || "";
  }
  if (!content) return;
  var senderColor = getAgentColor(msg.sender || "unknown");
  if (channel) {
    el.setAttribute("data-channel", channel);
  }
  el.style.borderLeftColor = senderColor;
  var highlightedContent = escapeHtml(content).replace(
    /@([\w-]+)/g,
    '<span class="mention-highlight">@$1</span>',
  );
  var contentPreview =
    content.length > 30 ? content.substring(0, 30) + "..." : content;
  el.innerHTML =
    '<div class="msg-header">' +
    '<span class="sender" style="color:' +
    senderColor +
    '">' +
    escapeHtml(msg.sender) +
    "</span>" +
    '<span class="channel" style="color:' +
    senderColor +
    '">' +
    escapeHtml(channel) +
    "</span>" +
    '<span class="ts">' +
    ts +
    "</span>" +
    "</div>" +
    '<div class="content">' +
    highlightedContent +
    "</div>" +
    '<div class="msg-reactions">' +
    '<button class="reaction-btn" data-emoji="👍" data-sender="' +
    escapeHtml(msg.sender) +
    '" data-preview="' +
    escapeHtml(contentPreview) +
    '" data-channel="' +
    escapeHtml(channel) +
    '">👍</button>' +
    '<button class="reaction-btn" data-emoji="👎" data-sender="' +
    escapeHtml(msg.sender) +
    '" data-preview="' +
    escapeHtml(contentPreview) +
    '" data-channel="' +
    escapeHtml(channel) +
    '">👎</button>' +
    "</div>";
  if (currentChannel && channel !== currentChannel) {
    el.style.display = "none";
  }
  var container = document.getElementById("messages");
  container.appendChild(el);
  container.scrollTop = container.scrollHeight;
}

function filterMessages() {
  var msgs = document.querySelectorAll(".msg");
  msgs.forEach(function (el) {
    if (!currentChannel) {
      el.style.display = "";
    } else {
      var ch = el.getAttribute("data-channel");
      el.style.display = ch === currentChannel ? "" : "none";
    }
  });
}

async function fetchAgents() {
  try {
    var res = await fetch("/api/agents");
    var agents = await res.json();
    var container = document.getElementById("agents");
    if (agents.length === 0) {
      container.innerHTML = '<p id="no-agents">No agents connected</p>';
      return;
    }
    container.innerHTML = agents
      .map(function (a) {
        var color = getAgentColor(a.name);
        var taskHtml = a.current_task
          ? '<div class="task">' + escapeHtml(a.current_task) + "</div>"
          : "";
        return (
          '<div class="agent-card" style="border-left: 3px solid ' +
          color +
          '">' +
          '<span class="status-dot ' +
          (a.status || "online") +
          '" style="background:' +
          color +
          '"></span>' +
          '<span class="name" style="color:' +
          color +
          '">' +
          escapeHtml(a.name) +
          "</span>" +
          '<div class="meta">' +
          escapeHtml(a.machine || "unknown") +
          " / " +
          escapeHtml(a.role || "agent") +
          "</div>" +
          taskHtml +
          '<div class="meta">channels: ' +
          a.channels
            .map(function (c) {
              return escapeHtml(c);
            })
            .join(", ") +
          "</div>" +
          "</div>"
        );
      })
      .join("");
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
        } else {
          currentChannel = ch;
        }
        filterMessages();
        fetchStats();
      });
    });
    updateChannelSelect(stats.channels);
  } catch (e) {
    /* fetch error */
  }
}

async function loadHistory() {
  try {
    var res = await fetch("/api/messages?limit=100");
    var messages = await res.json();
    messages.forEach(function (row) {
      appendMessage({
        type: "message",
        sender: row.sender,
        ts: row.ts,
        payload: {
          channel: row.channel,
          content: row.content,
        },
      });
    });
    var msgs = document.getElementById("messages");
    msgs.scrollTop = msgs.scrollHeight;
  } catch (e) {
    /* fetch error */
  }
}

function updateChannelSelect(channels) {
  /* Channel select removed -- using sidebar selection instead */
}

function sendMessage() {
  var input = document.getElementById("msg-input");
  var channel = currentChannel || "#general";
  var text = input.value.trim();
  if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(
    JSON.stringify({
      type: "message",
      sender: "human",
      payload: {
        channel: channel,
        content: text,
      },
    }),
  );
  input.value = "";
}

document.getElementById("msg-send").addEventListener("click", sendMessage);
document.getElementById("msg-input").addEventListener("keydown", function (e) {
  if (e.key === "Enter") {
    sendMessage();
  }
});

/* Reaction button handler */
document.getElementById("messages").addEventListener("click", function (e) {
  var btn = e.target.closest(".reaction-btn");
  if (!btn) return;
  var emoji = btn.getAttribute("data-emoji");
  var sender = btn.getAttribute("data-sender");
  var preview = btn.getAttribute("data-preview");
  var channel =
    btn.getAttribute("data-channel") || currentChannel || "#general";
  if (!ws || ws.readyState !== WebSocket.OPEN || !channel) return;
  ws.send(
    JSON.stringify({
      type: "message",
      sender: "human",
      payload: {
        channel: channel,
        content: "human reacted " + emoji + ' to "' + preview + '"',
      },
    }),
  );
});

connect();
setInterval(fetchStats, 10000);
setInterval(fetchAgents, 10000);
