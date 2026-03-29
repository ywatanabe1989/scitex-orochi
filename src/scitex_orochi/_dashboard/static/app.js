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

/* User display name -- prompt on first visit, store in localStorage */
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

var wsProto = location.protocol === "https:" ? "wss:" : "ws:";
var token = new URLSearchParams(location.search).get("token") || "";
var wsUrl = wsProto + "//" + location.host + "/ws?token=" + token;
var ws;

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

/* REST fallback state -- when WS is down, poll REST APIs for new messages */
var wsConnected = false;
var restPollTimer = null;
var restPollInterval = 5000; /* poll every 5s when WS is down */
var lastRestPollTs =
  null; /* track last message timestamp for incremental polling */

function startRestPolling() {
  if (restPollTimer) return; /* already polling */
  restPollTimer = setInterval(async function () {
    if (wsConnected)
      return; /* WS recovered, stop polling (timer cleared elsewhere) */
    try {
      var res = await fetch("/api/messages?limit=50");
      if (!res.ok) return;
      var messages = await res.json();
      var newCount = 0;
      messages.forEach(function (row) {
        var key = messageKey(row.sender, row.ts, row.content);
        if (knownMessageKeys[key]) return;
        knownMessageKeys[key] = true;
        newCount++;
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
    /* Also refresh agents and stats during REST polling */
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

function connect() {
  var statusEl = document.getElementById("conn-status");

  try {
    ws = new WebSocket(wsUrl);
  } catch (e) {
    /* WebSocket constructor can throw on some mobile browsers */
    console.warn("WebSocket constructor failed:", e);
    statusEl.textContent = "REST mode";
    statusEl.classList.remove("connected");
    statusEl.classList.add("rest-mode");
    startRestPolling();
    return;
  }

  ws.onopen = function () {
    wsConnected = true;
    statusEl.textContent = "connected";
    statusEl.classList.add("connected");
    statusEl.classList.remove("rest-mode");
    stopRestPolling();
    fetchStats();
    fetchAgents();
    loadHistory();
  };

  ws.onclose = function () {
    wsConnected = false;
    statusEl.textContent = "REST mode";
    statusEl.classList.remove("connected");
    statusEl.classList.add("rest-mode");
    /* Start REST polling as fallback while WS is down */
    startRestPolling();
    setTimeout(connect, 3000);
  };

  ws.onerror = function () {
    /* onerror fires before onclose on some browsers; ensure REST polling starts */
    if (!wsConnected) {
      startRestPolling();
    }
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
    /* Deduplicate: skip if this message was already loaded from history */
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
  /* Intercept resource reports */
  var meta = (msg.payload && msg.payload.metadata) || {};
  if (meta.type === "resource_report" && meta.data) {
    updateResourcePanel(meta.data);
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
  var attachments =
    (msg.payload && msg.payload.attachments) || msg.attachments || [];
  attachments.forEach(function (att) {
    if (att.mime_type && att.mime_type.startsWith("image/")) {
      attachmentsHtml +=
        '<div class="attachment-img">' +
        '<a href="' +
        escapeHtml(att.url) +
        '" target="_blank">' +
        '<img src="' +
        escapeHtml(att.url) +
        '" alt="' +
        escapeHtml(att.filename || "image") +
        '" loading="lazy"></a></div>';
    } else if (att.url) {
      var sizeStr = att.size
        ? " (" +
          (att.size > 1024 * 1024
            ? (att.size / 1024 / 1024).toFixed(1) + " MB"
            : (att.size / 1024).toFixed(0) + " KB") +
          ")"
        : "";
      attachmentsHtml +=
        '<div class="attachment-file">' +
        '<a href="' +
        escapeHtml(att.url) +
        '" target="_blank" download>' +
        "\uD83D\uDCCE " +
        escapeHtml(att.filename || "attachment") +
        escapeHtml(sizeStr) +
        "</a></div>";
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
        var statusClass =
          (a.status || "online") + (inactive ? " inactive" : "");
        var taskHtml = a.current_task
          ? '<div class="task">' + escapeHtml(a.current_task) + "</div>"
          : "";
        return (
          '<div class="agent-card' +
          (inactive ? " inactive" : "") +
          '" data-agent-name="' +
          escapeHtml(a.name) +
          '" style="border-left: 3px solid ' +
          color +
          ';cursor:pointer" title="Click to filter by this agent">' +
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
    /* Click agent card → add agent: tag */
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

var historyLoaded = false;
var knownMessageKeys = {};

function messageKey(sender, ts, content) {
  return (
    (sender || "") + "|" + (ts || "") + "|" + (content || "").substring(0, 80)
  );
}

async function loadHistory() {
  try {
    var res = await fetch("/api/messages?limit=100");
    var messages = await res.json();
    /* Clear existing messages to avoid duplicates on reconnect */
    var container = document.getElementById("messages");
    container.innerHTML = "";
    knownMessageKeys = {};
    messages.forEach(function (row) {
      var key = messageKey(row.sender, row.ts, row.content);
      knownMessageKeys[key] = true;
      appendMessage({
        type: "message",
        sender: row.sender,
        ts: row.ts,
        payload: {
          channel: row.channel,
          content: row.content,
          attachments:
            (row.metadata && row.metadata.attachments) || row.attachments || [],
        },
      });
    });
    container.scrollTop = container.scrollHeight;
    historyLoaded = true;
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
  if (!text) return;

  sendOrochiMessage({
    type: "message",
    sender: userName,
    payload: {
      channel: channel,
      content: text,
    },
  });
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

/* Send a message via REST API.
 * Always uses REST POST instead of WebSocket because Cloudflare tunnels
 * may complete the WS handshake but silently drop client-to-server frames. */
function sendOrochiMessage(msgData) {
  fetch("/api/messages?token=" + token, {
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

/* File attachment upload */
document.getElementById("msg-attach").addEventListener("click", function () {
  document.getElementById("file-input").click();
});

document
  .getElementById("file-input")
  .addEventListener("change", async function () {
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
      sendOrochiMessage({
        type: "message",
        sender: userName,
        payload: {
          channel: channel,
          content: file.name,
          attachments: [result],
        },
      });
    } catch (e) {
      console.error("Upload error:", e);
    }
    this.value = "";
  });

/* Sketch Canvas -- freehand drawing tool */
var sketchOverlay = null;
var sketchCanvas = null;
var sketchCtx = null;
var sketchDrawing = false;
var sketchTool = "pen";
var sketchColor = "#ffffff";
var sketchLineWidth = 5;
var SKETCH_COLORS = [
  "#ffffff",
  "#ef4444",
  "#f59e0b",
  "#22c55e",
  "#3b82f6",
  "#8b5cf6",
  "#ec4899",
  "#6b7280",
];
var SKETCH_WIDTHS = [2, 5, 10];
var SKETCH_WIDTH_LABELS = ["Thin", "Med", "Thick"];

function openSketch() {
  if (sketchOverlay) return;
  sketchOverlay = document.createElement("div");
  sketchOverlay.className = "sketch-overlay";

  var panel = document.createElement("div");
  panel.className = "sketch-panel";
  sketchOverlay.appendChild(panel);

  // Toolbar
  var toolbar = document.createElement("div");
  toolbar.className = "sketch-toolbar";
  panel.appendChild(toolbar);

  // Pen button
  var penBtn = document.createElement("button");
  penBtn.className = "sketch-tool-btn active";
  penBtn.textContent = "Pen";
  penBtn.addEventListener("click", function () {
    sketchTool = "pen";
    toolbar.querySelectorAll(".sketch-tool-btn").forEach(function (b) {
      b.classList.remove("active");
    });
    penBtn.classList.add("active");
  });
  toolbar.appendChild(penBtn);

  // Eraser button
  var eraserBtn = document.createElement("button");
  eraserBtn.className = "sketch-tool-btn";
  eraserBtn.textContent = "Eraser";
  eraserBtn.addEventListener("click", function () {
    sketchTool = "eraser";
    toolbar.querySelectorAll(".sketch-tool-btn").forEach(function (b) {
      b.classList.remove("active");
    });
    eraserBtn.classList.add("active");
  });
  toolbar.appendChild(eraserBtn);

  // Separator
  var sep1 = document.createElement("span");
  sep1.className = "sketch-sep";
  toolbar.appendChild(sep1);

  // Color swatches
  SKETCH_COLORS.forEach(function (c) {
    var swatch = document.createElement("button");
    swatch.className = "sketch-color" + (c === sketchColor ? " active" : "");
    swatch.style.background = c;
    swatch.addEventListener("click", function () {
      toolbar.querySelectorAll(".sketch-color").forEach(function (s) {
        s.classList.remove("active");
      });
      swatch.classList.add("active");
      sketchColor = c;
      sketchTool = "pen";
      toolbar.querySelectorAll(".sketch-tool-btn").forEach(function (b) {
        b.classList.toggle("active", b.textContent === "Pen");
      });
    });
    toolbar.appendChild(swatch);
  });

  // Separator
  var sep2 = document.createElement("span");
  sep2.className = "sketch-sep";
  toolbar.appendChild(sep2);

  // Width buttons
  SKETCH_WIDTHS.forEach(function (w, i) {
    var btn = document.createElement("button");
    btn.className =
      "sketch-width-btn" + (w === sketchLineWidth ? " active" : "");
    btn.textContent = SKETCH_WIDTH_LABELS[i];
    btn.addEventListener("click", function () {
      toolbar.querySelectorAll(".sketch-width-btn").forEach(function (b) {
        b.classList.remove("active");
      });
      btn.classList.add("active");
      sketchLineWidth = w;
    });
    toolbar.appendChild(btn);
  });

  // Canvas
  sketchCanvas = document.createElement("canvas");
  sketchCanvas.className = "sketch-canvas";
  sketchCanvas.width = 1200;
  sketchCanvas.height = 800;
  panel.appendChild(sketchCanvas);
  sketchCtx = sketchCanvas.getContext("2d");
  sketchCtx.fillStyle = "#1a1a2e";
  sketchCtx.fillRect(0, 0, 1200, 800);

  // Drawing events
  sketchCanvas.style.touchAction = "none";
  sketchCanvas.addEventListener("pointerdown", function (e) {
    sketchDrawing = true;
    sketchCtx.beginPath();
    var r = sketchCanvas.getBoundingClientRect();
    sketchCtx.moveTo(
      ((e.clientX - r.left) / r.width) * 1200,
      ((e.clientY - r.top) / r.height) * 800,
    );
  });
  sketchCanvas.addEventListener("pointermove", function (e) {
    if (!sketchDrawing) return;
    var r = sketchCanvas.getBoundingClientRect();
    var x = ((e.clientX - r.left) / r.width) * 1200;
    var y = ((e.clientY - r.top) / r.height) * 800;
    sketchCtx.lineWidth = sketchLineWidth;
    sketchCtx.lineCap = "round";
    sketchCtx.lineJoin = "round";
    if (sketchTool === "eraser") {
      sketchCtx.globalCompositeOperation = "destination-out";
      sketchCtx.strokeStyle = "rgba(0,0,0,1)";
    } else {
      sketchCtx.globalCompositeOperation = "source-over";
      sketchCtx.strokeStyle = sketchColor;
    }
    sketchCtx.lineTo(x, y);
    sketchCtx.stroke();
    sketchCtx.beginPath();
    sketchCtx.moveTo(x, y);
  });
  sketchCanvas.addEventListener("pointerup", function () {
    sketchDrawing = false;
  });
  sketchCanvas.addEventListener("pointerleave", function () {
    sketchDrawing = false;
  });

  // Action buttons
  var actions = document.createElement("div");
  actions.className = "sketch-actions";

  var clearBtn = document.createElement("button");
  clearBtn.className = "sketch-btn";
  clearBtn.textContent = "Clear";
  clearBtn.addEventListener("click", function () {
    sketchCtx.globalCompositeOperation = "source-over";
    sketchCtx.fillStyle = "#1a1a2e";
    sketchCtx.fillRect(0, 0, 1200, 800);
  });

  var cancelBtn = document.createElement("button");
  cancelBtn.className = "sketch-btn";
  cancelBtn.textContent = "Cancel";
  cancelBtn.addEventListener("click", closeSketch);

  var sendBtn = document.createElement("button");
  sendBtn.className = "sketch-btn sketch-btn-primary";
  sendBtn.textContent = "Send";
  sendBtn.addEventListener("click", sendSketch);

  actions.append(clearBtn, cancelBtn, sendBtn);
  panel.appendChild(actions);

  // Close on overlay click
  sketchOverlay.addEventListener("click", function (e) {
    if (e.target === sketchOverlay) closeSketch();
  });

  // Esc to close
  var onKey = function (e) {
    if (e.key === "Escape") {
      closeSketch();
      document.removeEventListener("keydown", onKey);
    }
  };
  document.addEventListener("keydown", onKey);

  document.body.appendChild(sketchOverlay);
}

function closeSketch() {
  if (sketchOverlay) {
    sketchOverlay.remove();
    sketchOverlay = null;
    sketchCanvas = null;
    sketchCtx = null;
  }
}

async function sendSketch() {
  if (!sketchCanvas) return;
  var dataUrl = sketchCanvas.toDataURL("image/png");
  var b64 = dataUrl.split(",")[1];
  closeSketch();
  try {
    var res = await fetch("/api/upload-base64?token=" + token, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        data: b64,
        filename: "sketch.png",
        mime_type: "image/png",
      }),
    });
    if (!res.ok) {
      console.error("Sketch upload failed:", res.status);
      return;
    }
    var result = await res.json();
    var channel = currentChannel || "#general";
    sendOrochiMessage({
      type: "message",
      sender: userName,
      payload: { channel: channel, content: "sketch", attachments: [result] },
    });
  } catch (e) {
    console.error("Sketch upload error:", e);
  }
}

document.getElementById("msg-sketch").addEventListener("click", openSketch);

/* Drag-and-drop file upload */
var msgInput = document.getElementById("msg-input");

async function uploadFile(file) {
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
    sendOrochiMessage({
      type: "message",
      sender: userName,
      payload: { channel: channel, content: file.name, attachments: [result] },
    });
  } catch (e) {
    console.error("Upload error:", e);
  }
}

msgInput.addEventListener("dragover", function (e) {
  e.preventDefault();
  this.classList.add("drag-over");
});
msgInput.addEventListener("dragleave", function () {
  this.classList.remove("drag-over");
});
msgInput.addEventListener("drop", function (e) {
  e.preventDefault();
  this.classList.remove("drag-over");
  var files = e.dataTransfer.files;
  for (var i = 0; i < files.length; i++) {
    uploadFile(files[i]);
  }
});

/* Clipboard paste image upload -- attached to document for broader compatibility */
document.addEventListener("paste", function (e) {
  var items = (e.clipboardData || {}).items;
  if (!items) return;
  for (var i = 0; i < items.length; i++) {
    if (items[i].type.indexOf("image/") === 0) {
      e.preventDefault();
      var file = items[i].getAsFile();
      if (file) uploadFile(file);
      return;
    }
  }
});

/* Resource Monitor Panel */
var resourceData = {};

function updateResourcePanel(data) {
  var key = data.hostname || data.agent || "unknown";
  resourceData[key] = data;
  renderResources();
}

function healthColor(status) {
  if (status === "critical") return "#ef4444";
  if (status === "warning") return "#f59e0b";
  return "#4ecdc4";
}

function barHtml(label, percent, warn) {
  var color = percent > 90 ? "#ef4444" : percent > 75 ? "#f59e0b" : "#4ecdc4";
  return (
    '<div class="res-bar-row"><span class="res-bar-label">' +
    label +
    '</span><div class="res-bar-track"><div class="res-bar-fill" style="width:' +
    Math.min(percent, 100) +
    "%;background:" +
    color +
    '"></div></div>' +
    '<span class="res-bar-val">' +
    Math.round(percent) +
    "%</span></div>"
  );
}

function renderResources() {
  var container = document.getElementById("resources");
  var keys = Object.keys(resourceData);
  if (keys.length === 0) {
    container.innerHTML =
      '<p style="color:#555;font-size:11px;padding:4px 0;">No reports yet</p>';
    return;
  }
  container.innerHTML = keys
    .map(function (k) {
      var d = resourceData[k];
      var health = (d.health && d.health.status) || "healthy";
      var hColor = healthColor(health);
      var cpu = (d.cpu && d.cpu.percent) || 0;
      var mem = (d.memory && d.memory.percent) || 0;
      var diskPct = 0;
      if (d.disk) {
        var dk = Object.keys(d.disk)[0];
        if (dk) diskPct = d.disk[dk].percent || 0;
      }
      var html =
        '<div class="res-card" style="border-left-color:' +
        hColor +
        '">' +
        '<div class="res-host"><span class="res-dot" style="background:' +
        hColor +
        '"></span>' +
        escapeHtml(k) +
        "</div>" +
        barHtml("CPU", cpu) +
        barHtml("Mem", mem) +
        barHtml("Disk", diskPct);
      if (d.gpu && d.gpu.length > 0) {
        d.gpu.forEach(function (g) {
          html += barHtml("GPU", g.utilization_percent || 0);
        });
      }
      if (d.slurm && d.slurm.total_jobs > 0) {
        html +=
          '<div class="res-meta">SLURM: ' + d.slurm.total_jobs + " jobs</div>";
      }
      html += "</div>";
      return html;
    })
    .join("");
}

/* TODO List -- GitHub Issues from ywatanabe1989/todo */
async function fetchTodoList() {
  try {
    var res = await fetch("/api/github/issues");
    if (!res.ok) {
      console.error("Failed to fetch TODO list:", res.status);
      return;
    }
    var issues = await res.json();
    var container = document.getElementById("todo-grid");
    if (!issues || issues.length === 0) {
      container.innerHTML =
        '<p style="color:#555;font-size:11px;padding:4px 0;">No open issues</p>';
      return;
    }
    container.innerHTML = issues
      .map(function (issue) {
        var labelsHtml = "";
        if (issue.labels && issue.labels.length > 0) {
          labelsHtml = issue.labels
            .map(function (label) {
              var bg = label.color ? "#" + label.color : "#333";
              var fg = isLightColor(label.color || "333333") ? "#000" : "#fff";
              return (
                '<span class="todo-label" style="background:' +
                bg +
                ";color:" +
                fg +
                '">' +
                escapeHtml(label.name) +
                "</span>"
              );
            })
            .join("");
        }
        var assigneeHtml = "";
        if (issue.assignee && issue.assignee.login) {
          assigneeHtml =
            '<span class="todo-assignee">' +
            escapeHtml(issue.assignee.login) +
            "</span>";
        }
        return (
          '<a class="todo-item" href="' +
          escapeHtml(issue.html_url) +
          '" target="_blank" rel="noopener">' +
          '<span class="todo-number">#' +
          issue.number +
          "</span>" +
          '<span class="todo-title">' +
          escapeHtml(issue.title) +
          "</span>" +
          (labelsHtml
            ? '<div class="todo-labels">' + labelsHtml + "</div>"
            : "") +
          assigneeHtml +
          "</a>"
        );
      })
      .join("");
  } catch (e) {
    console.error("TODO list fetch error:", e);
  }
}

function isLightColor(hex) {
  if (!hex || hex.length < 6) return false;
  var r = parseInt(hex.substring(0, 2), 16);
  var g = parseInt(hex.substring(2, 4), 16);
  var b = parseInt(hex.substring(4, 6), 16);
  var luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return luminance > 0.5;
}

/* Agents Tab -- full-width agent cards with resource info */
async function renderAgentsTab() {
  var grid = document.getElementById("agents-grid");
  try {
    var res = await fetch("/api/agents");
    var agents = await res.json();
    if (agents.length === 0) {
      grid.innerHTML =
        '<p style="color:#555;font-size:13px;">No agents connected</p>';
      return;
    }
    grid.innerHTML = agents
      .map(function (a) {
        var color = getAgentColor(a.name);
        var inactive = isAgentInactive(a);
        var statusClass =
          (a.status || "online") + (inactive ? " inactive" : "");
        var taskHtml = a.current_task
          ? '<div style="color:#ffd93d;font-size:12px;margin-top:6px;">Task: ' +
            escapeHtml(a.current_task) +
            "</div>"
          : "";
        var resHtml = "";
        var rd = resourceData[a.machine || a.name];
        if (rd) {
          var cpu = (rd.cpu && rd.cpu.percent) || 0;
          var mem = (rd.memory && rd.memory.percent) || 0;
          var diskPct = 0;
          if (rd.disk) {
            var dk = Object.keys(rd.disk)[0];
            if (dk) diskPct = rd.disk[dk].percent || 0;
          }
          resHtml =
            '<div style="margin-top:6px">' +
            barHtml("CPU", cpu) +
            barHtml("Mem", mem) +
            barHtml("Disk", diskPct) +
            "</div>";
        }
        return (
          '<div class="agent-card" data-agent-name="' +
          escapeHtml(a.name) +
          '" style="border-left:3px solid ' +
          color +
          ';width:calc(33.333% - 8px);min-width:280px;cursor:pointer" title="Click to filter by this agent">' +
          '<span class="status-dot ' +
          statusClass +
          '" style="background:' +
          (inactive ? "#555" : color) +
          '"></span>' +
          '<span class="name" style="color:' +
          (inactive ? "#666" : color) +
          '">' +
          escapeHtml(a.name) +
          "</span>" +
          (a.model
            ? ' <span style="color:#888;font-size:0.8em">(' +
              escapeHtml(a.model) +
              ")</span>"
            : "") +
          '<div class="meta">' +
          escapeHtml(a.machine || "unknown") +
          " / " +
          escapeHtml(a.role || "agent") +
          "</div>" +
          '<div class="meta">channels: ' +
          a.channels
            .map(function (c) {
              return escapeHtml(c);
            })
            .join(", ") +
          "</div>" +
          taskHtml +
          resHtml +
          "</div>"
        );
      })
      .join("");
    /* Click agent card → add agent: tag */
    grid
      .querySelectorAll(".agent-card[data-agent-name]")
      .forEach(function (el) {
        el.addEventListener("click", function () {
          addTag("agent", el.getAttribute("data-agent-name"));
        });
      });
  } catch (e) {
    console.error("Agents tab error:", e);
  }
}

/* Resources Tab -- per-host resource cards */
function renderResourcesTab() {
  var grid = document.getElementById("resources-grid");
  var keys = Object.keys(resourceData);
  if (keys.length === 0) {
    grid.innerHTML =
      '<p style="color:#555;font-size:13px;">No resource reports yet. Waiting for heartbeats from agents...</p>';
    return;
  }
  grid.innerHTML = keys
    .map(function (k) {
      var d = resourceData[k];
      var health = (d.health && d.health.status) || "healthy";
      var hColor = healthColor(health);
      var cpu = (d.cpu && d.cpu.percent) || 0;
      var mem = (d.memory && d.memory.percent) || 0;
      var diskPct = 0;
      if (d.disk) {
        var dk = Object.keys(d.disk)[0];
        if (dk) diskPct = d.disk[dk].percent || 0;
      }
      var html =
        '<div class="res-card" data-host-name="' +
        escapeHtml(k) +
        '" style="border-left-color:' +
        hColor +
        ';width:calc(33.333% - 8px);min-width:280px;cursor:pointer" title="Click to filter by this host">' +
        '<div class="res-host"><span class="res-dot" style="background:' +
        hColor +
        '"></span>' +
        escapeHtml(k) +
        "</div>" +
        barHtml("CPU", cpu) +
        barHtml("Mem", mem) +
        barHtml("Disk", diskPct);
      if (d.gpu && d.gpu.length > 0) {
        d.gpu.forEach(function (g) {
          html += barHtml("GPU", g.utilization_percent || 0);
        });
      }
      if (d.subagents !== undefined) {
        html += '<div class="res-meta">Subagents: ' + d.subagents + "</div>";
      }
      if (d.docker && d.docker.containers !== undefined) {
        html +=
          '<div class="res-meta">Containers: ' + d.docker.containers + "</div>";
      }
      if (d.uptime) {
        html +=
          '<div class="res-meta">Uptime: ' + escapeHtml(d.uptime) + "</div>";
      }
      html += "</div>";
      return html;
    })
    .join("");
  /* Click resource card → add host: tag */
  grid.querySelectorAll(".res-card[data-host-name]").forEach(function (el) {
    el.addEventListener("click", function () {
      addTag("host", el.getAttribute("data-host-name"));
    });
  });
}

/* Tab switching logic */
var activeTab = "chat";

document.querySelectorAll(".tab-btn").forEach(function (btn) {
  btn.addEventListener("click", function () {
    var tab = btn.getAttribute("data-tab");
    if (tab === activeTab) return;
    activeTab = tab;
    document.querySelectorAll(".tab-btn").forEach(function (b) {
      b.classList.toggle("active", b.getAttribute("data-tab") === tab);
    });
    var messagesEl = document.getElementById("messages");
    var inputBar = document.querySelector(".input-bar");
    var todoView = document.getElementById("todo-view");
    var resourcesView = document.getElementById("resources-view");
    var agentsTabView = document.getElementById("agents-tab-view");
    messagesEl.style.display = "none";
    inputBar.style.display = "none";
    todoView.style.display = "none";
    resourcesView.style.display = "none";
    agentsTabView.style.display = "none";
    if (tab === "chat") {
      messagesEl.style.display = "";
      inputBar.style.display = "";
    } else if (tab === "todo") {
      todoView.style.display = "block";
      todoView.style.flex = "1";
      fetchTodoList();
    } else if (tab === "agents-tab") {
      agentsTabView.style.display = "block";
      agentsTabView.style.flex = "1";
      renderAgentsTab();
    } else if (tab === "resources") {
      resourcesView.style.display = "block";
      resourcesView.style.flex = "1";
      renderResourcesTab();
    }
  });
});

/* Collapsible sidebar sections */
(function () {
  var saved = {};
  try {
    saved = JSON.parse(localStorage.getItem("orochi_collapsed") || "{}");
  } catch (e) {}

  document.querySelectorAll(".collapsible-heading").forEach(function (h2) {
    var key = h2.textContent.trim();
    var section = h2.nextElementSibling;
    if (saved[key]) {
      h2.classList.add("collapsed");
      if (section) section.classList.add("collapsed");
    }
    h2.addEventListener("click", function () {
      var isCollapsed = h2.classList.toggle("collapsed");
      if (section) section.classList.toggle("collapsed", isCollapsed);
      try {
        var state = JSON.parse(
          localStorage.getItem("orochi_collapsed") || "{}",
        );
        if (isCollapsed) {
          state[key] = true;
        } else {
          delete state[key];
        }
        localStorage.setItem("orochi_collapsed", JSON.stringify(state));
      } catch (e) {}
    });
  });
})();

/* Tag-based unified filter with fuzzy matching */
var filterInput = document.getElementById("filter-input");
var filterTagsEl = document.getElementById("filter-tags");
var filterSuggestEl = document.getElementById("filter-suggest");
var activeTags = []; /* [{type:"agent", value:"nas-agent"}, ...] */
var suggestIndex = -1;

/* Parse tag prefixes from input: "agent:nas foo" → {tags:[{type:"agent",value:"nas"}], text:"foo"} */
function parseFilterInput(raw) {
  var parts = raw.split(/\s+/);
  var tags = [];
  var textParts = [];
  parts.forEach(function (p) {
    var m = p.match(/^(agent|host|channel|label|project):(.+)$/i);
    if (m) {
      tags.push({ type: m[1].toLowerCase(), value: m[2] });
    } else if (p) {
      textParts.push(p);
    }
  });
  return { tags: tags, text: textParts.join(" ") };
}

function addTag(type, value) {
  /* No duplicates */
  var exists = activeTags.some(function (t) {
    return t.type === type && t.value === value;
  });
  if (exists) return;
  activeTags.push({ type: type, value: value });
  renderTags();
  runFilter();
}

function removeTag(index) {
  activeTags.splice(index, 1);
  renderTags();
  runFilter();
}

function renderTags() {
  filterTagsEl.innerHTML = activeTags
    .map(function (t, i) {
      return (
        '<span class="filter-tag" data-type="' +
        t.type +
        '" onclick="removeTag(' +
        i +
        ')">' +
        t.type +
        ":" +
        escapeHtml(t.value) +
        ' <span class="tag-remove">\u00D7</span></span>'
      );
    })
    .join("");
}

/* Collect known values for autocomplete */
function getTagSuggestions(prefix) {
  var results = [];
  var pLower = prefix.toLowerCase();

  /* Agent names */
  cachedAgentNames.forEach(function (n) {
    if (fuzzyMatch(pLower, n.toLowerCase())) {
      results.push({ type: "agent", value: n });
    }
  });

  /* Host names from resource data */
  Object.keys(resourceData).forEach(function (h) {
    if (fuzzyMatch(pLower, h.toLowerCase())) {
      results.push({ type: "host", value: h });
    }
  });

  /* Channel names */
  document.querySelectorAll("#channels .channel-item").forEach(function (el) {
    var ch = el.getAttribute("data-channel") || el.textContent.trim();
    if (fuzzyMatch(pLower, ch.toLowerCase())) {
      results.push({ type: "channel", value: ch });
    }
  });

  /* Deduplicate */
  var seen = {};
  return results
    .filter(function (r) {
      var key = r.type + ":" + r.value;
      if (seen[key]) return false;
      seen[key] = true;
      return true;
    })
    .slice(0, 8);
}

function showSuggestions(items) {
  if (items.length === 0) {
    hideSuggestions();
    return;
  }
  suggestIndex = 0;
  filterSuggestEl.innerHTML = items
    .map(function (item, i) {
      return (
        '<div class="filter-suggest-item' +
        (i === 0 ? " selected" : "") +
        '" data-type="' +
        item.type +
        '" data-value="' +
        escapeHtml(item.value) +
        '">' +
        '<span class="suggest-type">' +
        item.type +
        ":</span>" +
        escapeHtml(item.value) +
        "</div>"
      );
    })
    .join("");
  filterSuggestEl.classList.add("visible");
}

function hideSuggestions() {
  filterSuggestEl.classList.remove("visible");
  filterSuggestEl.innerHTML = "";
  suggestIndex = -1;
}

filterSuggestEl.addEventListener("click", function (e) {
  var item = e.target.closest(".filter-suggest-item");
  if (item) {
    addTag(item.getAttribute("data-type"), item.getAttribute("data-value"));
    filterInput.value = "";
    hideSuggestions();
  }
});

filterInput.addEventListener("input", function () {
  var raw = this.value.trim();
  /* Show suggestions if typing */
  if (raw.length >= 1) {
    var suggestions = getTagSuggestions(raw);
    showSuggestions(suggestions);
  } else {
    hideSuggestions();
  }
  runFilter();
});

filterInput.addEventListener("keydown", function (e) {
  var items = filterSuggestEl.querySelectorAll(".filter-suggest-item");
  if (items.length > 0 && filterSuggestEl.classList.contains("visible")) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      suggestIndex = Math.min(suggestIndex + 1, items.length - 1);
      items.forEach(function (el, i) {
        el.classList.toggle("selected", i === suggestIndex);
      });
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      suggestIndex = Math.max(suggestIndex - 1, 0);
      items.forEach(function (el, i) {
        el.classList.toggle("selected", i === suggestIndex);
      });
    } else if ((e.key === "Tab" || e.key === "Enter") && suggestIndex >= 0) {
      e.preventDefault();
      var sel = items[suggestIndex];
      addTag(sel.getAttribute("data-type"), sel.getAttribute("data-value"));
      filterInput.value = "";
      hideSuggestions();
    } else if (e.key === "Escape") {
      hideSuggestions();
    }
  } else if (e.key === "Backspace" && !this.value && activeTags.length > 0) {
    /* Remove last tag on backspace in empty input */
    removeTag(activeTags.length - 1);
  }
});

filterInput.addEventListener("blur", function () {
  setTimeout(hideSuggestions, 150);
});

/* Check if an element matches all active tags */
function matchesTags(el, extraData) {
  if (activeTags.length === 0) return true;
  var data = extraData || {};
  return activeTags.every(function (tag) {
    var val = tag.value.toLowerCase();
    if (tag.type === "agent") {
      var sender =
        data.sender ||
        (el.querySelector(".sender")
          ? el.querySelector(".sender").textContent
          : "");
      return fuzzyMatch(val, sender.toLowerCase());
    }
    if (tag.type === "channel") {
      var ch =
        data.channel ||
        el.getAttribute("data-channel") ||
        (el.querySelector(".channel")
          ? el.querySelector(".channel").textContent
          : "");
      return fuzzyMatch(val, ch.toLowerCase());
    }
    if (tag.type === "host") {
      var text = data.host || el.textContent;
      return fuzzyMatch(val, text.toLowerCase());
    }
    if (tag.type === "label") {
      var labels = el.querySelectorAll(".todo-label");
      if (labels.length === 0) return false;
      var found = false;
      labels.forEach(function (l) {
        if (fuzzyMatch(val, l.textContent.toLowerCase())) found = true;
      });
      return found;
    }
    if (tag.type === "project") {
      return fuzzyMatch(val, el.textContent.toLowerCase());
    }
    return true;
  });
}

function runFilter() {
  var parsed = parseFilterInput(filterInput.value.trim());
  /* Combine inline tags with chip tags */
  var allTags = activeTags.concat(parsed.tags);
  var q = parsed.text;

  /* Filter chat messages */
  document.querySelectorAll(".msg").forEach(function (el) {
    var sender = el.querySelector(".sender");
    var channel = el.querySelector(".channel");
    var content = el.querySelector(".content");
    var text =
      (sender ? sender.textContent : "") +
      " " +
      (channel ? channel.textContent : "") +
      " " +
      (content ? content.textContent : "");
    var show = fuzzyMatch(q, text);
    /* Apply tag filters */
    if (show && allTags.length > 0) {
      show = allTags.every(function (tag) {
        var val = tag.value.toLowerCase();
        if (tag.type === "agent")
          return fuzzyMatch(
            val,
            (sender ? sender.textContent : "").toLowerCase(),
          );
        if (tag.type === "channel")
          return fuzzyMatch(
            val,
            (el.getAttribute("data-channel") || "").toLowerCase(),
          );
        return fuzzyMatch(val, text.toLowerCase());
      });
    }
    /* Respect currentChannel filter too */
    if (show && currentChannel) {
      var ch = el.getAttribute("data-channel");
      show = ch === currentChannel;
    }
    el.style.display = show ? "" : "none";
  });

  /* Filter TODO cards */
  document.querySelectorAll(".todo-item").forEach(function (el) {
    var text = el.textContent;
    var show = fuzzyMatch(q, text);
    if (show && allTags.length > 0) {
      show = allTags.every(function (tag) {
        var val = tag.value.toLowerCase();
        if (tag.type === "label") {
          var labels = el.querySelectorAll(".todo-label");
          if (labels.length === 0) return false;
          var found = false;
          labels.forEach(function (l) {
            if (fuzzyMatch(val, l.textContent.toLowerCase())) found = true;
          });
          return found;
        }
        return fuzzyMatch(val, text.toLowerCase());
      });
    }
    el.style.display = show ? "" : "none";
  });

  /* Filter sidebar agent cards */
  document.querySelectorAll("#agents .agent-card").forEach(function (el) {
    var text = el.textContent;
    el.style.display =
      fuzzyMatch(q, text) && matchesAllTags(allTags, text) ? "" : "none";
  });

  /* Filter sidebar channel items */
  document.querySelectorAll("#channels .channel-item").forEach(function (el) {
    var text = el.textContent;
    el.style.display =
      fuzzyMatch(q, text) && matchesAllTags(allTags, text) ? "" : "none";
  });

  /* Filter sidebar resource cards */
  document.querySelectorAll("#resources .res-card").forEach(function (el) {
    var text = el.textContent;
    el.style.display =
      fuzzyMatch(q, text) && matchesAllTags(allTags, text) ? "" : "none";
  });

  /* Filter agents tab cards */
  document.querySelectorAll("#agents-grid .agent-card").forEach(function (el) {
    var text = el.textContent;
    el.style.display =
      fuzzyMatch(q, text) && matchesAllTags(allTags, text) ? "" : "none";
  });

  /* Filter resources tab cards */
  document.querySelectorAll("#resources-grid .res-card").forEach(function (el) {
    var text = el.textContent;
    el.style.display =
      fuzzyMatch(q, text) && matchesAllTags(allTags, text) ? "" : "none";
  });
}

/* Simple tag matcher for flat text elements */
function matchesAllTags(tags, text) {
  if (tags.length === 0) return true;
  var lower = text.toLowerCase();
  return tags.every(function (tag) {
    return fuzzyMatch(tag.value.toLowerCase(), lower);
  });
}

/* Mobile sidebar hamburger toggle */
(function () {
  var toggle = document.getElementById("sidebar-toggle");
  var sidebar = document.getElementById("sidebar");
  if (!toggle || !sidebar) return;

  /* Create backdrop element */
  var backdrop = document.createElement("div");
  backdrop.className = "sidebar-backdrop";
  document.body.appendChild(backdrop);

  function openSidebar() {
    sidebar.classList.add("open");
    toggle.classList.add("open");
    toggle.innerHTML = "&#10005;"; /* X */
    backdrop.classList.add("visible");
  }

  function closeSidebar() {
    sidebar.classList.remove("open");
    toggle.classList.remove("open");
    toggle.innerHTML = "&#9776;"; /* hamburger */
    backdrop.classList.remove("visible");
  }

  toggle.addEventListener("click", function () {
    if (sidebar.classList.contains("open")) {
      closeSidebar();
    } else {
      openSidebar();
    }
  });

  backdrop.addEventListener("click", closeSidebar);

  /* Close sidebar when selecting a channel on mobile */
  var channelsEl = document.getElementById("channels");
  channelsEl.addEventListener("click", function (e) {
    if (e.target.closest(".channel-item") && window.innerWidth <= 600) {
      closeSidebar();
    }
  });
})();

/* Load history immediately via HTTP (before WebSocket connects) so messages
   survive Ctrl+Shift+R hard refresh without waiting for WS handshake. */
loadHistory();
fetchStats();
fetchAgents();
connect();

/* Periodic refresh via REST (these work regardless of WS state) */
setInterval(fetchStats, 10000);
setInterval(fetchAgents, 10000);
fetchTodoList();
setInterval(fetchTodoList, 60000);

/* If WS hasn't connected after 3 seconds, start REST polling for messages.
   This handles mobile Safari / Cloudflare where WS may never connect. */
setTimeout(function () {
  if (!wsConnected) {
    console.warn(
      "WebSocket not connected after 3s, starting REST fallback polling",
    );
    startRestPolling();
  }
}, 3000);
