/* Activity tab — real-time agent status board with per-agent sub-tabs */
/* globals: apiUrl, escapeHtml, getAgentColor, cleanAgentName, fetchAgents */

var activityRefreshTimer = null;
var _activitySubTab = "overview"; /* "overview" or agent name */
var _paneShowRaw = false; /* false = strip ANSI (clean), true = raw */
/* Cache for /api/agents/<name>/detail/ so the per-agent view can show
 * fields that the registry summary omits (full CLAUDE.md, full pane
 * text, redacted MCP). Mirrors _agentDetailCache in agents-tab.js. */
var _activityDetailCache = {};
var _activityDetailInflight = {};

async function _fetchActivityDetail(name) {
  if (!name || name === "overview") return;
  if (_activityDetailInflight[name]) return;
  _activityDetailInflight[name] = true;
  try {
    var res = await fetch(
      apiUrl("/api/agents/" + encodeURIComponent(name) + "/detail/"),
    );
    if (!res.ok) return;
    _activityDetailCache[name] = await res.json();
    if (_activitySubTab === name) {
      var grid = document.getElementById("activity-grid");
      var agent = (window.__lastAgents || []).find(function (a) {
        return a.name === name;
      });
      if (grid && agent) _renderActivityAgentDetail(agent, grid);
    }
  } catch (_e) {
    /* ignore; registry fallback still renders */
  } finally {
    _activityDetailInflight[name] = false;
  }
}

/* Strip ANSI escape sequences for clean terminal display */
function _stripAnsi(str) {
  /* eslint-disable-next-line no-control-regex */
  return str
    .replace(/\x1B\[[0-9;]*[A-Za-z]/g, "")
    .replace(/\x1B\][^\x07\x1B]*(?:\x07|\x1B\\)/g, "")
    .replace(/\x1B[@-_][0-?]*[ -/]*[@-~]/g, "")
    .replace(/\r/g, "");
}

/* ── Sub-tab bar ────────────────────────────────────────────────────── */
function _renderActivitySubTabBar(agents) {
  var bar = document.getElementById("activity-subtabs");
  if (!bar) return;
  var tabs = [{ id: "overview", label: "Overview" }];
  agents.forEach(function (a) {
    tabs.push({ id: a.name, label: a.name });
  });
  var html = "";
  tabs.forEach(function (t) {
    var active = t.id === _activitySubTab ? " agent-subtab-active" : "";
    var isOffline = false;
    if (t.id !== "overview") {
      var ag = agents.find(function (a) {
        return a.name === t.id;
      });
      if (ag) {
        var lv = ag.liveness || ag.status || "online";
        isOffline = lv === "offline";
      }
    }
    html +=
      '<button class="agent-subtab' +
      active +
      (isOffline ? " agent-subtab-offline" : "") +
      '" ' +
      'data-actsubtab="' +
      escapeHtml(t.id) +
      '">' +
      escapeHtml(t.label) +
      "</button>";
  });
  bar.innerHTML = html;
  bar.addEventListener(
    "click",
    function (e) {
      var btn = e.target.closest(".agent-subtab");
      if (!btn) return;
      _activitySubTab = btn.getAttribute("data-actsubtab");
      _applyActivitySubTab(agents);
    },
    { once: true },
  ); /* removed and re-bound each render — use capture once trick */
}

/* Re-bind sub-tab click handler (called every render to avoid duplicate handlers) */
function _bindActivitySubTabBar(agents) {
  var bar = document.getElementById("activity-subtabs");
  if (!bar) return;
  var newBar = bar.cloneNode(true); /* clone to strip old listeners */
  bar.parentNode.replaceChild(newBar, bar);
  newBar.addEventListener("click", function (e) {
    var btn = e.target.closest(".agent-subtab");
    if (!btn) return;
    _activitySubTab = btn.getAttribute("data-actsubtab");
    /* If selected agent no longer in list, fall back */
    if (
      _activitySubTab !== "overview" &&
      !agents.find(function (a) {
        return a.name === _activitySubTab;
      })
    ) {
      _activitySubTab = "overview";
    }
    _applyActivitySubTab(agents);
  });
}

/* Switch grid content based on active sub-tab */
function _applyActivitySubTab(agents) {
  /* Update active class on tab buttons */
  var bar = document.getElementById("activity-subtabs");
  if (bar) {
    bar.querySelectorAll(".agent-subtab").forEach(function (btn) {
      btn.classList.toggle(
        "agent-subtab-active",
        btn.getAttribute("data-actsubtab") === _activitySubTab,
      );
    });
  }
  var grid = document.getElementById("activity-grid");
  if (!grid) return;
  if (_activitySubTab === "overview") {
    /* Re-render overview cards */
    grid.classList.remove("activity-grid-detail");
    _renderActivityCards(agents, grid);
    return;
  }
  var agent = agents.find(function (a) {
    return a.name === _activitySubTab;
  });
  if (!agent) {
    grid.classList.remove("activity-grid-detail");
    grid.innerHTML = '<p class="empty-notice">Agent not found.</p>';
    return;
  }
  grid.classList.add("activity-grid-detail");
  _renderActivityAgentDetail(agent, grid);
  _fetchActivityDetail(agent.name);
}

/* Per-agent full detail view */
function _renderActivityAgentDetail(a, grid) {
  /* Merge the registry row with any cached /detail/ payload so we
   * display the full CLAUDE.md and redacted pane_text when available,
   * while still rendering something immediately from the registry. */
  var d = _activityDetailCache[a.name] || {};
  a = Object.assign({}, a, {
    claude_md: d.claude_md || a.claude_md || a.claude_md_head || "",
    pane_tail_block: d.pane_text || a.pane_tail_block || a.pane_tail || "",
  });
  var liveness = a.liveness || a.status || "online";
  var livenessColors = {
    online: "#4ecdc4",
    idle: "#ffd93d",
    stale: "#ff8c42",
    offline: "#ef4444",
  };
  var statusColor = livenessColors[liveness] || "#888";
  var pane = a.pane_tail_block || a.pane_tail || "";
  var ctxPct = a.context_pct != null ? Number(a.context_pct) : null;
  var q5 = a.quota_5h_used_pct != null ? Number(a.quota_5h_used_pct) : null;
  var q7 = a.quota_7d_used_pct != null ? Number(a.quota_7d_used_pct) : null;
  var subCnt = a.subagent_count != null ? Number(a.subagent_count) : null;
  var chips = [];
  if (ctxPct != null) chips.push("ctx " + ctxPct.toFixed(1) + "%");
  if (q5 != null) chips.push("5h " + q5.toFixed(0) + "%");
  if (q7 != null) chips.push("7d " + q7.toFixed(0) + "%");
  if (subCnt != null) chips.push("subagents " + subCnt);
  if (a.model) chips.push(a.model);
  if (a.multiplexer) chips.push(a.multiplexer);
  if (a.pid) chips.push("pid " + a.pid);
  var uniqueCh = [...new Set(a.channels || [])];
  if (uniqueCh.length) chips.push("ch: " + uniqueCh.join(", "));
  function _fmtPct(v) {
    return v == null ? "-" : Number(v).toFixed(0) + "%";
  }
  function _fmtSec(v) {
    if (v == null) return "-";
    v = Number(v);
    if (v < 60) return Math.round(v) + "s";
    if (v < 3600) return Math.round(v / 60) + "m";
    if (v < 86400) {
      var h = Math.floor(v / 3600);
      return h + "h " + Math.round((v % 3600) / 60) + "m";
    }
    var d = Math.floor(v / 86400);
    return d + "d " + Math.round((v % 86400) / 3600) + "h";
  }
  var metaFields = [
    ["Role", a.role || "agent"],
    ["Machine", a.machine || "?"],
    ["Model", a.model || "-"],
    ["Multiplexer", a.multiplexer || "-"],
    ["PID", a.pid || "-"],
    ["Liveness", liveness],
    ["Context", ctxPct != null ? ctxPct.toFixed(1) + "%" : "-"],
    [
      "5h quota",
      a.quota_5h_used_pct != null
        ? _fmtPct(a.quota_5h_used_pct) +
          (a.quota_5h_reset_at ? " (resets " + a.quota_5h_reset_at + ")" : "")
        : "-",
    ],
    [
      "7d quota",
      a.quota_7d_used_pct != null
        ? _fmtPct(a.quota_7d_used_pct) +
          (a.quota_7d_reset_at ? " (resets " + a.quota_7d_reset_at + ")" : "")
        : "-",
    ],
    [
      "Subagents (" + (subCnt != null ? subCnt : 0) + ")",
      subCnt != null ? String(subCnt) : "-",
    ],
    ["Pane state", a.pane_state || "-"],
    ["Idle", _fmtSec(a.idle_seconds)],
    ["Workdir", a.workdir || "-"],
    ["Registered", a.registered_at || "-"],
    ["Last heartbeat", a.last_heartbeat || "-"],
  ];
  var metaGridHtml = metaFields
    .map(function (f) {
      return (
        "<span><strong>" +
        escapeHtml(f[0]) +
        ":</strong>" +
        escapeHtml(String(f[1])) +
        "</span>"
      );
    })
    .join("");
  var headerHtml =
    '<div class="agent-detail-header">' +
    '<div class="agent-detail-header-line">' +
    '<span class="status-dot-inline" style="background:' +
    statusColor +
    '"></span>' +
    '<span class="agent-detail-header-title" style="color:' +
    escapeHtml(getAgentColor ? getAgentColor(a.name) : "#4ecdc4") +
    '">' +
    escapeHtml(
      typeof cleanAgentName === "function" ? cleanAgentName(a.name) : a.name,
    ) +
    "</span>" +
    (a.current_task
      ? '<em class="agent-detail-task">' + escapeHtml(a.current_task) + "</em>"
      : "") +
    "</div>" +
    '<div class="agent-detail-meta-grid">' +
    metaGridHtml +
    "</div>" +
    "</div>";
  /* Task */
  var taskHtml =
    a.current_task || a.last_message_preview
      ? '<div class="agent-detail-section"><span class="agent-detail-pane-label">Task: </span>' +
        escapeHtml(a.current_task || a.last_message_preview) +
        "</div>"
      : "";
  /* Terminal pane — with Raw/Clean toggle */
  var paneContent = pane ? (_paneShowRaw ? pane : _stripAnsi(pane)) : "";
  var paneHtml =
    '<div class="agent-detail-pane-wrap">' +
    '<div class="agent-detail-pane-label-row">' +
    '<span class="agent-detail-pane-label">Terminal output</span>' +
    '<button class="pane-raw-toggle" id="pane-raw-toggle" title="Toggle raw/clean terminal output">' +
    (_paneShowRaw ? "Raw" : "Clean") +
    "</button>" +
    "</div>" +
    '<pre class="agent-detail-pane" id="agent-detail-pane-content">' +
    (paneContent
      ? escapeHtml(paneContent)
      : '<span class="muted-cell">No terminal output available</span>') +
    "</pre></div>";
  /* CLAUDE.md (full if available, head otherwise) */
  var claudeMd = a.claude_md || a.claude_md_head || "";
  var claudeMdHtml = claudeMd
    ? '<div class="agent-detail-section">' +
      '<div class="agent-detail-pane-label">CLAUDE.md</div>' +
      '<pre class="agent-detail-claude-md">' +
      escapeHtml(claudeMd) +
      "</pre></div>"
    : "";
  /* Channel subscriptions (with + / x controls, admin-gated server-side). */
  var uniqueSubs = [...new Set(a.channels || [])];
  var channelBadgesHtml = uniqueSubs
    .map(function (c) {
      return (
        '<span class="ch-badge ch-badge-interactive" data-channel="' +
        escapeHtml(c) +
        '">' +
        escapeHtml(c) +
        '<button type="button" class="ch-badge-remove" title="Unsubscribe ' +
        escapeHtml(c) +
        '" data-agent="' +
        escapeHtml(a.name) +
        '" data-channel="' +
        escapeHtml(c) +
        '">&times;</button>' +
        "</span>"
      );
    })
    .join("");
  var channelsHtml =
    '<div class="agent-detail-section agent-detail-channels" data-agent="' +
    escapeHtml(a.name) +
    '">' +
    '<span class="agent-detail-pane-label">Channels: </span>' +
    '<span class="ch-badges">' +
    channelBadgesHtml +
    "</span>" +
    '<button type="button" class="ch-add-btn" data-agent="' +
    escapeHtml(a.name) +
    '" title="Subscribe to a channel">+</button>' +
    "</div>";

  var splitHtml =
    '<div class="agent-detail-split">' +
    '<div class="agent-detail-split-col">' +
    paneHtml +
    "</div>" +
    '<div class="agent-detail-split-col">' +
    claudeMdHtml +
    "</div>" +
    "</div>";
  grid.innerHTML =
    '<div class="agent-detail-view">' +
    headerHtml +
    taskHtml +
    channelsHtml +
    splitHtml +
    "</div>";
  /* Scroll pane to bottom */
  var pre = grid.querySelector(".agent-detail-pane");
  if (pre) pre.scrollTop = pre.scrollHeight;
  /* Wire Raw/Clean toggle */
  var toggleBtn = grid.querySelector("#pane-raw-toggle");
  if (toggleBtn) {
    toggleBtn.addEventListener("click", function () {
      _paneShowRaw = !_paneShowRaw;
      toggleBtn.textContent = _paneShowRaw ? "Raw" : "Clean";
      var paneEl = grid.querySelector("#agent-detail-pane-content");
      if (paneEl) {
        var rawPaneContent = pane
          ? _paneShowRaw
            ? pane
            : _stripAnsi(pane)
          : "";
        paneEl.innerHTML = rawPaneContent
          ? escapeHtml(rawPaneContent)
          : '<span class="muted-cell">No terminal output available</span>';
        paneEl.scrollTop = paneEl.scrollHeight;
      }
    });
  }
  _bindActivityChannelControls(grid, a.name);
}

async function _activityChannelRequest(method, agent, channel) {
  var body = { channel: channel, username: "agent-" + agent };
  if (method === "POST" || method === "PATCH") body.permission = "read-write";
  var m = document.cookie.match(/csrftoken=([^;]+)/);
  var res = await fetch(apiUrl("/api/channel-members/"), {
    method: method,
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": m ? decodeURIComponent(m[1]) : "",
    },
    credentials: "same-origin",
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    var txt = await res.text().catch(function () {
      return "";
    });
    throw new Error(res.status + ": " + txt.slice(0, 200));
  }
  return res.json();
}

function _bindActivityChannelControls(grid, agentName) {
  grid.querySelectorAll(".ch-badge-remove").forEach(function (btn) {
    btn.addEventListener("click", async function (ev) {
      ev.stopPropagation();
      var channel = btn.getAttribute("data-channel");
      var agent = btn.getAttribute("data-agent");
      if (!agent || !channel) return;
      if (!confirm("Unsubscribe " + agent + " from " + channel + "?")) return;
      try {
        await _activityChannelRequest("DELETE", agent, channel);
        delete _activityDetailCache[agent];
        _fetchActivityDetail(agent);
        if (typeof fetchAgents === "function") fetchAgents();
      } catch (e) {
        alert("Unsubscribe failed: " + e.message);
      }
    });
  });
  grid.querySelectorAll(".ch-add-btn").forEach(function (btn) {
    btn.addEventListener("click", async function (ev) {
      ev.stopPropagation();
      var agent = btn.getAttribute("data-agent");
      if (!agent) return;
      var raw = prompt("Subscribe " + agent + " to which channel?", "#");
      if (raw == null) return;
      var channel = raw.trim();
      if (!channel) return;
      if (!channel.startsWith("#") && !channel.startsWith("dm:")) {
        channel = "#" + channel;
      }
      try {
        await _activityChannelRequest("POST", agent, channel);
        delete _activityDetailCache[agent];
        _fetchActivityDetail(agent);
        if (typeof fetchAgents === "function") fetchAgents();
      } catch (e) {
        alert("Subscribe failed: " + e.message);
      }
    });
  });
}

function _formatIdle(seconds) {
  if (seconds == null) return "";
  if (seconds < 60) return seconds + "s";
  if (seconds < 3600) return Math.floor(seconds / 60) + "m";
  return Math.floor(seconds / 3600) + "h";
}

/* Compute seconds since an ISO timestamp. Returns null if unparseable. */
function _secondsSinceIso(iso) {
  if (!iso) return null;
  var t = Date.parse(iso);
  if (isNaN(t)) return null;
  return Math.max(0, Math.floor((Date.now() - t) / 1000));
}

/* Format a duration in seconds as "up 3h 14m" style. */
function _formatUptime(seconds) {
  if (seconds == null) return "";
  var h = Math.floor(seconds / 3600);
  var m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return "up " + h + "h " + m + "m";
  if (m > 0) return "up " + m + "m";
  return "up " + seconds + "s";
}

/* Split a current_task string like "Bash: docker compose build" into
 * a tool name + argument preview. Returns {tool, arg, isProse}. If no
 * colon separator is found we treat the whole string as prose (e.g. a
 * last_user_msg snippet, not a tool call). */
function _parseCurrentTask(task) {
  if (!task) return { tool: "", arg: "", isProse: false };
  var idx = task.indexOf(": ");
  if (idx > 0 && idx < 40) {
    var tool = task.slice(0, idx);
    /* Heuristic: tool names are short alnum/underscore (incl. mcp__ prefix) */
    if (/^[A-Za-z_][A-Za-z0-9_]{0,60}$/.test(tool)) {
      return { tool: tool, arg: task.slice(idx + 2), isProse: false };
    }
  }
  /* Pure tool name with no argument (e.g. "Bash") */
  if (/^[A-Za-z_][A-Za-z0-9_]{0,60}$/.test(task)) {
    return { tool: task, arg: "", isProse: false };
  }
  return { tool: "", arg: task, isProse: true };
}

function _livenessLabel(liveness) {
  switch (liveness) {
    case "online":
      return "active";
    case "idle":
      return "idle";
    case "stale":
      return "stale";
    case "offline":
      return "offline";
    default:
      return liveness || "unknown";
  }
}

function _livenessOrder(liveness) {
  /* Sort: stale first (needs attention), then online, idle, offline */
  switch (liveness) {
    case "stale":
      return 0;
    case "online":
      return 1;
    case "idle":
      return 2;
    case "offline":
      return 3;
    default:
      return 4;
  }
}

function _renderHealthField(health) {
  if (!health || !health.status) return "";
  var st = String(health.status);
  var reason = health.reason ? " · " + escapeHtml(health.reason) : "";
  var src = health.source ? " (" + escapeHtml(health.source) + ")" : "";
  return (
    '<div class="activity-health activity-health-' +
    escapeHtml(st) +
    '">' +
    '<span class="activity-health-icon">\uD83E\uDE7A</span> ' +
    '<span class="activity-health-status">' +
    escapeHtml(st) +
    "</span>" +
    reason +
    src +
    "</div>"
  );
}

/* Linkify #NNN issue refs in an already-escaped HTML string */
function _linkifyIssues(safeHtml) {
  return safeHtml.replace(
    /#(\d+)\b/g,
    '<a class="issue-link" href="https://github.com/ywatanabe1989/scitex-orochi/issues/$1" target="_blank">#$1</a>',
  );
}

/* Prominent task renderer — this is the card's hero row. `task` is the
 * rich current_task string (e.g. "Bash: docker compose build"). `age`
 * is a pre-formatted age label or empty. `fallback` is last_message_preview
 * used when there is no task at all. */
function _renderTaskField(task, fallback, age) {
  var ageChip = age
    ? '<span class="activity-task-age" title="seconds since last heartbeat">' +
      escapeHtml(age) +
      "</span>"
    : "";
  if (!task) {
    if (fallback) {
      return (
        '<div class="activity-task-row activity-task-prose">' +
        '<span class="activity-task-fallback" title="last activity (no structured task set)">' +
        _linkifyIssues(escapeHtml(fallback)) +
        "</span>" +
        ageChip +
        "</div>"
      );
    }
    return (
      '<div class="activity-task-row">' +
      '<span class="activity-task-empty">no task reported</span>' +
      ageChip +
      "</div>"
    );
  }
  var parsed = _parseCurrentTask(task);
  var fullTitle = escapeHtml(task);
  if (parsed.isProse) {
    return (
      '<div class="activity-task-row activity-task-prose" title="' +
      fullTitle +
      '">' +
      '<span class="activity-tool-prose">' +
      _linkifyIssues(escapeHtml(parsed.arg)) +
      "</span>" +
      ageChip +
      "</div>"
    );
  }
  var toolHtml = parsed.tool
    ? '<span class="activity-tool-name">' + escapeHtml(parsed.tool) + "</span>"
    : "";
  var argHtml = parsed.arg
    ? '<span class="activity-tool-arg">' +
      _linkifyIssues(escapeHtml(parsed.arg)) +
      "</span>"
    : "";
  return (
    '<div class="activity-task-row activity-task-tool" title="' +
    fullTitle +
    '">' +
    toolHtml +
    argHtml +
    ageChip +
    "</div>"
  );
}

/* Render the overview cards grid (extracted for sub-tab use) */
function _renderActivityCards(agents, grid) {
  if (!agents || !agents.length) {
    grid.innerHTML = '<p class="empty-notice">No agents connected.</p>';
    return;
  }
  var summary = document.getElementById("activity-summary");
  var counts = { online: 0, idle: 0, stale: 0, offline: 0 };
  agents.forEach(function (a) {
    var l = a.liveness || a.status || "online";
    if (counts[l] != null) counts[l]++;
  });
  if (summary) {
    summary.innerHTML =
      '<span class="activity-pill activity-pill-online" title="recently active (heartbeat &lt; 2 min)">' +
      '<span class="activity-pill-dot"></span>' +
      counts.online +
      " active</span>" +
      '<span class="activity-pill activity-pill-idle" title="quiet 2–10 min — likely thinking or waiting">' +
      '<span class="activity-pill-dot"></span>' +
      counts.idle +
      " idle</span>" +
      '<span class="activity-pill activity-pill-stale" title="quiet &gt;10 min — probably stuck, check it">' +
      '<span class="activity-pill-dot"></span>' +
      counts.stale +
      " stale</span>" +
      '<span class="activity-pill activity-pill-offline" title="not connected to the hub right now">' +
      '<span class="activity-pill-dot"></span>' +
      counts.offline +
      " offline</span>" +
      '<span class="activity-legend-hint">← border color matches</span>';
  }
  grid.innerHTML = agents
    .map(function (a) {
      var color = getAgentColor(a.name);
      var liveness = a.liveness || a.status || "online";
      var idleStr = _formatIdle(a.idle_seconds);
      var task = a.current_task || "";
      var preview = a.last_message_preview || "";
      var machine = escapeHtml(a.machine || "—");
      var role = escapeHtml(a.role || "agent");
      var model = a.model ? escapeHtml(a.model) : "";
      var multiplexer = a.multiplexer ? escapeHtml(a.multiplexer) : "";
      var pid = a.pid != null && a.pid !== 0 ? a.pid : null;
      var ctxPct = a.context_pct != null ? Number(a.context_pct) : null;
      var subagentCount =
        a.subagent_count != null
          ? Number(a.subagent_count)
          : Array.isArray(a.subagents)
            ? a.subagents.length
            : null;
      var skillsLoaded = Array.isArray(a.skills_loaded) ? a.skills_loaded : [];
      var channels = Array.isArray(a.channels) ? a.channels : [];
      var name = escapeHtml(
        typeof hostedAgentName === "function"
          ? hostedAgentName(a)
          : cleanAgentName(a.name),
      );
      var rawName = a.name || "";
      var ageSec =
        a.idle_seconds != null
          ? Number(a.idle_seconds)
          : _secondsSinceIso(a.last_heartbeat || a.last_action);
      var ageStr = ageSec != null ? _formatIdle(ageSec) : "";
      var isStuck =
        ageSec != null &&
        ageSec > 300 &&
        (!subagentCount || subagentCount === 0) &&
        !task;
      var uptimeSec = _secondsSinceIso(a.started_at);
      var uptimeStr = uptimeSec != null ? _formatUptime(uptimeSec) : "";
      var chips = [];
      if (subagentCount != null && subagentCount > 0) {
        chips.push(
          '<span class="activity-chip activity-chip-subs activity-chip-subs-active" title="active subagents">' +
            "\u25B6 " +
            subagentCount +
            " sub" +
            (subagentCount === 1 ? "" : "s") +
            "</span>",
        );
      } else {
        chips.push(
          '<span class="activity-chip activity-chip-subs-idle" title="no subagents running">idle (no subs)</span>',
        );
      }
      if (ctxPct != null) {
        var ctxClass =
          ctxPct < 50 ? "ctx-ok" : ctxPct < 80 ? "ctx-warn" : "ctx-hot";
        chips.push(
          '<span class="activity-chip activity-chip-ctx ' +
            ctxClass +
            '" title="context usage">ctx ' +
            ctxPct.toFixed(1) +
            "%</span>",
        );
      }
      var q5 = a.quota_5h_pct != null ? Number(a.quota_5h_pct) : null;
      var qw = a.quota_weekly_pct != null ? Number(a.quota_weekly_pct) : null;
      if (q5 != null) {
        var q5Class = q5 < 50 ? "ctx-ok" : q5 < 80 ? "ctx-warn" : "ctx-hot";
        var q5Rem = a.quota_5h_remaining
          ? " (" + escapeHtml(a.quota_5h_remaining) + ")"
          : "";
        chips.push(
          '<span class="activity-chip activity-chip-ctx ' +
            q5Class +
            '" title="5h quota">5h ' +
            q5.toFixed(0) +
            "%" +
            q5Rem +
            "</span>",
        );
      }
      if (qw != null) {
        var qwClass = qw < 50 ? "ctx-ok" : qw < 80 ? "ctx-warn" : "ctx-hot";
        var qwRem = a.quota_weekly_remaining
          ? " (" + escapeHtml(a.quota_weekly_remaining) + ")"
          : "";
        chips.push(
          '<span class="activity-chip activity-chip-ctx ' +
            qwClass +
            '" title="weekly quota">wk ' +
            qw.toFixed(0) +
            "%" +
            qwRem +
            "</span>",
        );
      }
      if (model)
        chips.push(
          '<span class="activity-chip activity-chip-model" title="model">' +
            model +
            "</span>",
        );
      if (multiplexer)
        chips.push(
          '<span class="activity-chip activity-chip-mux" title="multiplexer">' +
            multiplexer +
            "</span>",
        );
      if (uptimeStr) {
        chips.push(
          '<span class="activity-chip activity-chip-uptime" title="time since process start: ' +
            escapeHtml(a.started_at || "") +
            '">' +
            escapeHtml(uptimeStr) +
            "</span>",
        );
      }
      if (skillsLoaded.length > 0) {
        var skillsTitle = skillsLoaded.join("\n");
        chips.push(
          '<span class="activity-chip activity-chip-skills" title="' +
            escapeHtml(skillsTitle) +
            '">skills ' +
            skillsLoaded.length +
            "</span>",
        );
      }
      if (channels.length > 0) {
        var chTitle = channels.join("\n");
        chips.push(
          '<span class="activity-chip activity-chip-channels" title="' +
            escapeHtml(chTitle) +
            '">ch ' +
            channels.length +
            "</span>",
        );
      }
      if (pid != null)
        chips.push(
          '<span class="activity-chip activity-chip-pid" title="process id">pid ' +
            pid +
            "</span>",
        );
      var chipsHtml =
        chips.length > 0
          ? '<div class="activity-chips">' + chips.join("") + "</div>"
          : "";
      var subagents = Array.isArray(a.subagents) ? a.subagents : [];
      var subagentsHtml = "";
      if (subagents.length > 0) {
        subagentsHtml =
          '<ul class="activity-subagents">' +
          subagents
            .map(function (s) {
              var sname = escapeHtml(s.name || "subagent");
              var stask = _renderTaskField(s.task || "", "", "");
              var sstatus = escapeHtml(s.status || "running");
              return (
                '<li class="activity-subagent activity-subagent-' +
                sstatus +
                '">' +
                '<span class="activity-subagent-branch">└─</span>' +
                '<span class="activity-subagent-name">' +
                sname +
                "</span>" +
                '<span class="activity-subagent-task">' +
                stask +
                "</span>" +
                "</li>"
              );
            })
            .join("") +
          "</ul>";
      }
      var copyPayload = (
        rawName +
        " — " +
        (task || preview || "(no task)")
      ).replace(/"/g, "&quot;");
      var copyBtn =
        '<button type="button" class="activity-copy-btn" title="copy name + task to clipboard" ' +
        'data-copy="' +
        escapeHtml(copyPayload) +
        '">\uD83D\uDCCB</button>';
      var stuckClass = isStuck ? " activity-stuck" : "";
      var recentActions = Array.isArray(a.recent_actions)
        ? a.recent_actions
        : [];
      var recentHtml = "";
      if (recentActions.length > 0) {
        recentHtml =
          '<ul class="activity-recent" title="recent tool calls (latest at bottom)">' +
          recentActions
            .map(function (act) {
              var ts = (act && act.ts) || "";
              var hh = "";
              if (ts && ts.length >= 19) hh = ts.slice(11, 19);
              var prev = (act && act.preview) || "";
              return (
                '<li class="activity-recent-row">' +
                '<span class="activity-recent-ts">' +
                escapeHtml(hh) +
                "</span>" +
                '<span class="activity-recent-preview" title="' +
                escapeHtml(prev) +
                '">' +
                escapeHtml(prev) +
                "</span></li>"
              );
            })
            .join("") +
          "</ul>";
      }
      var paneTailBlock = a.pane_tail_block || a.pane_tail || "";
      var paneTailHtml =
        recentActions.length === 0 && paneTailBlock
          ? '<pre class="activity-pane-tail" title="recent lines from this agent\'s tmux pane">' +
            escapeHtml(paneTailBlock) +
            "</pre>"
          : "";
      var claudeMdHead = a.claude_md_head || "";
      var mcpServers = Array.isArray(a.mcp_servers) ? a.mcp_servers : [];
      var roleLine = claudeMdHead
        ? '<div class="activity-role-hint" title="from workspace CLAUDE.md">' +
          escapeHtml(claudeMdHead) +
          "</div>"
        : "";
      var mcpLine =
        mcpServers.length > 0
          ? '<div class="activity-mcp-line" title="MCP servers configured for this agent">' +
            mcpServers
              .map(function (s) {
                return (
                  '<span class="activity-mcp-chip">' + escapeHtml(s) + "</span>"
                );
              })
              .join("") +
            "</div>"
          : "";
      return (
        '<div class="activity-card activity-' +
        liveness +
        stuckClass +
        '" ' +
        'data-agent="' +
        escapeHtml(rawName) +
        '">' +
        '<div class="activity-card-header">' +
        '<span class="activity-status-dot activity-dot-' +
        liveness +
        '"></span>' +
        '<span class="activity-name" style="color:' +
        color +
        '">' +
        name +
        "</span>" +
        copyBtn +
        '<span class="activity-liveness">' +
        _livenessLabel(liveness) +
        (idleStr ? " · " + idleStr : "") +
        "</span>" +
        "</div>" +
        '<div class="activity-meta">' +
        machine +
        " · " +
        role +
        "</div>" +
        roleLine +
        '<div class="activity-task">' +
        _renderTaskField(task, preview, ageStr) +
        "</div>" +
        paneTailHtml +
        chipsHtml +
        mcpLine +
        _renderHealthField(a.health) +
        subagentsHtml +
        "</div>"
      );
    })
    .join("");
  /* Click card -> switch to that agent's sub-tab (Shift/Ctrl/Cmd keeps
   * the legacy addTag filter behaviour so power users are not
   * surprised). Copy button and other inline controls stop propagation. */
  Array.prototype.forEach.call(
    grid.querySelectorAll(".activity-card[data-agent]"),
    function (card) {
      card.style.cursor = "pointer";
      card.addEventListener("click", function (ev) {
        var name = card.getAttribute("data-agent");
        if (!name) return;
        if (ev.shiftKey || ev.ctrlKey || ev.metaKey) {
          if (typeof addTag === "function") addTag("agent", name);
          return;
        }
        _activitySubTab = name;
        _applyActivitySubTab(window.__lastAgents || []);
      });
    },
  );
  /* Wire up copy buttons */
  Array.prototype.forEach.call(
    grid.querySelectorAll(".activity-copy-btn"),
    function (btn) {
      btn.addEventListener("click", function (ev) {
        ev.stopPropagation();
        var txt = btn.getAttribute("data-copy") || "";
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard
            .writeText(txt)
            .then(function () {
              btn.classList.add("activity-copy-ok");
              setTimeout(function () {
                btn.classList.remove("activity-copy-ok");
              }, 900);
            })
            .catch(function () {});
        }
      });
    },
  );
}

function renderActivityTab() {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  var grid = document.getElementById("activity-grid");
  var summary = document.getElementById("activity-summary");
  if (!grid) return;

  /* Reuse the global agents cache populated by fetchAgents() */
  var src = window.__lastAgents || [];
  if (!src.length) {
    grid.innerHTML = '<p class="empty-notice">No agents connected.</p>';
    if (summary) summary.textContent = "";
    if (inputHasFocus && document.activeElement !== msgInput) {
      msgInput.focus();
      try {
        msgInput.setSelectionRange(savedStart, savedEnd);
      } catch (_) {}
    }
    return;
  }

  /* Stable position: alphabetical by name only. ywatanabe at msg#6592
   * / msg#6596 / msg#6598 said the worst UX is cards moving around mid-
   * read — so we never reorder by status anymore. The status difference
   * is conveyed entirely through the border color and the summary
   * pills at the top. Pinned agents float to the top of the alphabet
   * group as a soft hint, no liveness reorder. */
  var agents = src.slice().sort(function (a, b) {
    var pa = a.pinned ? 0 : 1;
    var pb = b.pinned ? 0 : 1;
    if (pa !== pb) return pa - pb;
    return (a.name || "").localeCompare(b.name || "");
  });

  /* Build/update the sub-tab bar */
  _renderActivitySubTabBar(agents);
  _bindActivitySubTabBar(agents);

  /* Render content based on the active sub-tab */
  if (
    _activitySubTab !== "overview" &&
    !agents.find(function (a) {
      return a.name === _activitySubTab;
    })
  ) {
    _activitySubTab = "overview";
  }
  if (_activitySubTab === "overview") {
    _renderActivityCards(agents, grid);
  } else {
    var detailAgent = agents.find(function (a) {
      return a.name === _activitySubTab;
    });
    if (detailAgent) _renderActivityAgentDetail(detailAgent, grid);
  }
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try {
      msgInput.setSelectionRange(savedStart, savedEnd);
    } catch (_) {}
  }
}

async function refreshActivityFromApi() {
  try {
    var res = await fetch(apiUrl("/api/agents"), {
      credentials: "same-origin",
    });
    if (!res.ok) return;
    window.__lastAgents = await res.json();
    renderActivityTab();
  } catch (e) {
    /* ignore */
  }
}

function startActivityAutoRefresh() {
  if (activityRefreshTimer) return;
  /* 30s instead of 10s — ywatanabe at msg#6575 said the tab was
   * "ちかちかしすぎ". 30 s is still fast enough to feel live but
   * cuts the visual churn down to 1/3. */
  activityRefreshTimer = setInterval(refreshActivityFromApi, 30000);
}

function stopActivityAutoRefresh() {
  if (activityRefreshTimer) {
    clearInterval(activityRefreshTimer);
    activityRefreshTimer = null;
  }
}

document.addEventListener("DOMContentLoaded", function () {
  var btn = document.querySelector('[data-tab="activity"]');
  if (btn) {
    btn.addEventListener("click", function () {
      refreshActivityFromApi();
      startActivityAutoRefresh();
    });
  }
});
