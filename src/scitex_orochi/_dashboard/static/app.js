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
  var highlightedContent = escapeHtml(content)
    .replace(/\n/g, "<br>")
    .replace(/@([\w-]+)/g, '<span class="mention-highlight">@$1</span>');
  var attachmentsHtml = "";
  var attachments = (msg.payload && msg.payload.attachments) || msg.attachments || [];
  attachments.forEach(function (att) {
    if (att.mime_type && att.mime_type.startsWith("image/")) {
      attachmentsHtml +=
        '<div class="attachment-img">' +
        '<a href="' + escapeHtml(att.url) + '" target="_blank">' +
        '<img src="' + escapeHtml(att.url) + '" alt="' +
        escapeHtml(att.filename || "image") + '" loading="lazy"></a></div>';
    } else if (att.url) {
      var sizeStr = att.size ? " (" + (att.size > 1024 * 1024 ? (att.size / 1024 / 1024).toFixed(1) + " MB" : (att.size / 1024).toFixed(0) + " KB") + ")" : "";
      attachmentsHtml +=
        '<div class="attachment-file">' +
        '<a href="' + escapeHtml(att.url) + '" target="_blank" download>' +
        "\uD83D\uDCCE " + escapeHtml(att.filename || "attachment") + escapeHtml(sizeStr) + "</a></div>";
    }
  });
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
    attachmentsHtml +
    "";
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
        var inactive = isAgentInactive(a);
        var statusClass = (a.status || "online") + (inactive ? " inactive" : "");
        var taskHtml = a.current_task
          ? '<div class="task">' + escapeHtml(a.current_task) + "</div>"
          : "";
        return (
          '<div class="agent-card' +
          (inactive ? " inactive" : "") +
          '" style="border-left: 3px solid ' +
          color +
          '">' +
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
            ? ' <span style="color:#888;font-size:0.8em">(' +
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
          attachments: (row.metadata && row.metadata.attachments) || row.attachments || [],
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
  input.style.height = "auto";
}

/* Auto-resize textarea as content grows */
document.getElementById("msg-input").addEventListener("input", function () {
  this.style.height = "auto";
  this.style.height = Math.min(this.scrollHeight, 120) + "px";
});

document.getElementById("msg-send").addEventListener("click", sendMessage);
document.getElementById("msg-input").addEventListener("keydown", function (e) {
  if (e.key === "Enter") {
    var dd = document.getElementById("mention-dropdown");
    if (dd && dd.classList.contains("visible")) return;
    if (e.shiftKey) return; /* Shift+Enter inserts newline naturally */
    e.preventDefault();
    sendMessage();
  }
});

/* Mention autocomplete with Tab support */
var mentionDropdown = document.getElementById("mention-dropdown");
var mentionSelectedIndex = -1;
var cachedAgentNames = [];

async function refreshAgentNames() {
  try {
    var res = await fetch("/api/agents");
    var agents = await res.json();
    cachedAgentNames = agents.map(function (a) {
      return a.name;
    });
  } catch (e) {
    /* ignore */
  }
}

function getMentionQuery(input) {
  var val = input.value;
  var pos = input.selectionStart;
  var before = val.substring(0, pos);
  var match = before.match(/@([\w-]*)$/);
  if (match) return { query: match[1].toLowerCase(), start: match.index };
  return null;
}

function showMentionDropdown(items) {
  mentionSelectedIndex = 0;
  mentionDropdown.innerHTML = items
    .map(function (name, i) {
      return (
        '<div class="mention-item' +
        (i === 0 ? " selected" : "") +
        '" data-name="' +
        escapeHtml(name) +
        '">' +
        escapeHtml(name) +
        "</div>"
      );
    })
    .join("");
  mentionDropdown.classList.add("visible");
}

function hideMentionDropdown() {
  mentionDropdown.classList.remove("visible");
  mentionDropdown.innerHTML = "";
  mentionSelectedIndex = -1;
}

function insertMention(name) {
  var input = document.getElementById("msg-input");
  var info = getMentionQuery(input);
  if (!info) return;
  var before = input.value.substring(0, info.start);
  var after = input.value.substring(input.selectionStart);
  input.value = before + "@" + name + " " + after;
  var newPos = info.start + name.length + 2;
  input.setSelectionRange(newPos, newPos);
  input.focus();
  hideMentionDropdown();
}

document.getElementById("msg-input").addEventListener("input", function () {
  var info = getMentionQuery(this);
  if (!info) {
    hideMentionDropdown();
    return;
  }
  var filtered = cachedAgentNames.filter(function (n) {
    return n.toLowerCase().indexOf(info.query) === 0;
  });
  if (filtered.length === 0) {
    hideMentionDropdown();
    return;
  }
  showMentionDropdown(filtered);
});

document.getElementById("msg-input").addEventListener("keydown", function (e) {
  if (!mentionDropdown || !mentionDropdown.classList.contains("visible"))
    return;
  var items = mentionDropdown.querySelectorAll(".mention-item");
  if (items.length === 0) return;

  if (e.key === "ArrowDown") {
    e.preventDefault();
    mentionSelectedIndex = Math.min(mentionSelectedIndex + 1, items.length - 1);
    items.forEach(function (el, i) {
      el.classList.toggle("selected", i === mentionSelectedIndex);
    });
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    mentionSelectedIndex = Math.max(mentionSelectedIndex - 1, 0);
    items.forEach(function (el, i) {
      el.classList.toggle("selected", i === mentionSelectedIndex);
    });
  } else if (
    (e.key === "Tab" || e.key === "Enter") &&
    mentionSelectedIndex >= 0
  ) {
    e.preventDefault();
    insertMention(items[mentionSelectedIndex].getAttribute("data-name"));
  } else if (e.key === "Escape") {
    e.preventDefault();
    hideMentionDropdown();
  }
});

mentionDropdown.addEventListener("click", function (e) {
  var item = e.target.closest(".mention-item");
  if (item) insertMention(item.getAttribute("data-name"));
});

document.getElementById("msg-input").addEventListener("blur", function () {
  setTimeout(hideMentionDropdown, 150);
});

setInterval(refreshAgentNames, 15000);
refreshAgentNames();

/* Inactive agent detection -- stale heartbeat (>60s) or explicit offline status */
function isAgentInactive(agent) {
  if (agent.status === "offline") return true;
  if (!agent.last_heartbeat) return false;
  var hb = new Date(agent.last_heartbeat);
  if (isNaN(hb.getTime())) return false;
  return Date.now() - hb.getTime() > 60000;
}

/* Task progress panel -- collapsed by default to avoid sidebar redundancy */
var taskPanelCollapsed = true;

document
  .getElementById("task-panel-toggle")
  .addEventListener("click", function () {
    taskPanelCollapsed = !taskPanelCollapsed;
    var body = document.getElementById("task-panel-body");
    var arrow = document.getElementById("task-panel-arrow");
    if (taskPanelCollapsed) {
      body.classList.add("collapsed");
      arrow.classList.add("collapsed");
    } else {
      body.classList.remove("collapsed");
      arrow.classList.remove("collapsed");
    }
  });

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

async function fetchTaskCards() {
  try {
    var res = await fetch("/api/agents");
    var agents = await res.json();
    var container = document.getElementById("task-cards");
    if (agents.length === 0) {
      container.innerHTML =
        '<div class="task-cards-empty">No agents connected</div>';
      return;
    }
    container.innerHTML = agents
      .map(function (a) {
        var color = getAgentColor(a.name);
        var inactive = isAgentInactive(a);
        var statusLabel = inactive ? "inactive" : (a.status || "online");
        var displayColor = inactive ? "#555" : color;
        var taskText = a.current_task
          ? '<div class="tc-task">' + escapeHtml(a.current_task) + "</div>"
          : '<div class="tc-task idle">idle</div>';
        return (
          '<div class="task-card' +
          (inactive ? " inactive" : "") +
          '" style="border-left-color:' +
          displayColor +
          '">' +
          '<div class="tc-name" style="color:' +
          displayColor +
          '">' +
          escapeHtml(a.name) +
          (a.model
            ? ' <span style="color:#888;font-size:0.8em">(' +
              escapeHtml(a.model) +
              ")</span>"
            : "") +
          "</div>" +
          '<div class="tc-status"><span class="dot" style="background:' +
          (inactive
            ? "#555"
            : statusLabel === "busy"
              ? "#ffd93d"
              : statusLabel === "error"
                ? "#ff6b6b"
                : "#4ecdc4") +
          '"></span>' +
          escapeHtml(statusLabel) +
          "</div>" +
          taskText +
          '<div class="tc-meta">up ' +
          uptime(a.registered_at) +
          " | hb " +
          timeAgo(a.last_heartbeat) +
          "</div>" +
          "</div>"
        );
      })
      .join("");
  } catch (e) {
    /* fetch error */
  }
}

/* File attachment upload */
document.getElementById("msg-attach").addEventListener("click", function () {
  document.getElementById("file-input").click();
});

document.getElementById("file-input").addEventListener("change", async function () {
  var file = this.files[0];
  if (!file) return;
  var formData = new FormData();
  formData.append("file", file);
  try {
    var res = await fetch("/api/upload?token=" + token, {
      method: "POST",
      body: formData,
    });
    if (!res.ok) {
      console.error("Upload failed:", res.status);
      return;
    }
    var result = await res.json();
    var channel = currentChannel || "#general";
    ws.send(
      JSON.stringify({
        type: "message",
        sender: "human",
        payload: {
          channel: channel,
          content: file.name,
          attachments: [result],
        },
      })
    );
  } catch (e) {
    console.error("Upload error:", e);
  }
  this.value = "";
});

connect();
setInterval(fetchStats, 10000);
setInterval(fetchAgents, 10000);
setInterval(fetchTaskCards, 5000);
fetchTaskCards();
