/* Orochi Dashboard -- WebSocket observer client */

const wsProto = location.protocol === "https:" ? "wss:" : "ws:";
const token = new URLSearchParams(location.search).get("token") || "";
const wsUrl = `${wsProto}//${location.host}/ws?token=${token}`;
let ws;

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function connect() {
  ws = new WebSocket(wsUrl);
  const statusEl = document.getElementById("conn-status");

  ws.onopen = function () {
    statusEl.textContent = "connected";
    statusEl.classList.add("connected");
    fetchStats();
    fetchAgents();
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
  var ts = msg.ts ? new Date(msg.ts).toLocaleTimeString() : "";
  var channel = (msg.payload && msg.payload.channel) || "";
  var content = "";
  if (msg.payload) {
    content =
      msg.payload.content || msg.payload.text || msg.payload.message || "";
    if (!content && typeof msg.payload === "object") {
      content = JSON.stringify(msg.payload);
    }
  }
  el.innerHTML =
    '<span class="ts">' +
    ts +
    "</span> " +
    '<span class="channel">' +
    escapeHtml(channel) +
    "</span> " +
    '<span class="sender">' +
    escapeHtml(msg.sender) +
    "</span> " +
    '<span class="content">' +
    escapeHtml(content) +
    "</span>";
  var container = document.getElementById("messages");
  container.appendChild(el);
  container.scrollTop = container.scrollHeight;
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
        var taskHtml = a.current_task
          ? '<div class="task">' + escapeHtml(a.current_task) + "</div>"
          : "";
        return (
          '<div class="agent-card">' +
          '<span class="status-dot ' +
          (a.status || "online") +
          '"></span>' +
          '<span class="name">' +
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
      .map(function (c) {
        var active = currentChannel === c ? " active" : "";
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
      el.style.cursor = "pointer";
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
  } catch (e) {
    /* fetch error */
  }
}

connect();
setInterval(fetchStats, 10000);
setInterval(fetchAgents, 10000);
