/* Agents Tab -- registry table with per-agent sub-tab terminal views */
/* globals: escapeHtml, getAgentColor, isAgentInactive, timeAgo,
   addTag, activeTab, apiUrl */
var _agentsTabInterval = null;
var _selectedAgentTab = "overview"; /* "overview" or agent name */
var _lastAgentsData = []; /* cached for sub-tab renders */
var _agentDetailCache = {}; /* name -> last /detail response */
var _agentDetailInflight = {}; /* name -> bool (in-flight guard) */

/* Fetch the full per-agent detail payload (todo#420).
 *
 * Responses are cached into _agentDetailCache and rendered via
 * _renderAgentContent. The registry-based fallback in
 * _renderAgentDetail still runs on first paint so the user never
 * sees a blank screen while the detail call is in flight. */
async function _fetchAgentDetail(name) {
  if (!name || name === "overview") return;
  if (_agentDetailInflight[name]) return;
  _agentDetailInflight[name] = true;
  try {
    var res = await fetch(
      apiUrl("/api/agents/" + encodeURIComponent(name) + "/detail/"),
    );
    if (!res.ok) {
      console.warn("agent detail fetch failed:", name, res.status);
      return;
    }
    var data = await res.json();
    _agentDetailCache[name] = data;
    /* Only re-render if still viewing this agent */
    if (_selectedAgentTab === name) {
      var grid = document.getElementById("agents-grid");
      if (grid) _renderAgentContent(grid);
    }
  } catch (e) {
    console.warn("agent detail fetch error:", name, e);
  } finally {
    _agentDetailInflight[name] = false;
  }
}

/* ── Sub-tab bar ────────────────────────────────────────────────────── */
function _renderSubTabBar(agents) {
  var tabs = [{ id: "overview", label: "Overview" }];
  agents.forEach(function (a) {
    tabs.push({ id: a.name, label: a.name });
  });
  var html = '<div class="agent-subtab-bar" id="agent-subtab-bar">';
  tabs.forEach(function (t) {
    var active = t.id === _selectedAgentTab ? " agent-subtab-active" : "";
    var inactive =
      t.id !== "overview" &&
      isAgentInactive(
        agents.find(function (a) {
          return a.name === t.id;
        }) || {},
      )
        ? " agent-subtab-offline"
        : "";
    html +=
      '<button class="agent-subtab' +
      active +
      inactive +
      '" ' +
      'data-subtab="' +
      escapeHtml(t.id) +
      '">' +
      escapeHtml(t.label) +
      "</button>";
  });
  html += "</div>";
  return html;
}

function _bindSubTabBar(grid) {
  var bar = grid.querySelector("#agent-subtab-bar");
  if (!bar) return;
  bar.addEventListener("click", function (e) {
    var btn = e.target.closest(".agent-subtab");
    if (!btn) return;
    _selectedAgentTab = btn.getAttribute("data-subtab");
    /* Re-render content area only, not the whole tab (preserve scroll) */
    _renderAgentContent(grid);
  });
}

/* ── Per-agent detail view ──────────────────────────────────────────── */
/* Merges registry row (`a`) with cached /api/agents/<name>/detail/
 * payload (`d`). The merge is forgiving: either source can be missing
 * a field, and the view always renders something so the user is never
 * staring at an empty panel while the detail call is in flight. */
function _renderAgentDetail(a) {
  var d = _agentDetailCache[a.name] || {};
  var liveness =
    d.liveness || a.liveness || (isAgentInactive(a) ? "offline" : "online");
  var statusColor = livenessColor(liveness);
  var role = d.role || a.role || "agent";
  var machine = d.machine || a.machine || "?";
  var model = d.model || a.model || "-";
  var ctxPct = d.context_pct != null ? d.context_pct : a.context_pct;
  var currentTask = d.current_task || a.current_task || "";
  var channels = d.channel_subs || a.channels || [];
  var claudeMd = d.claude_md || a.claude_md || "";
  /* todo#460: .mcp.json is served by the detail endpoint only (not in the
   * registry summary row). Empty string = agent has not yet heartbeated
   * with dotfiles PR#71 agent_meta.py --push; we render an explicit
   * empty-state so the absence is discoverable rather than invisible. */
  var mcpJson = d.mcp_json || "";
  var mcpServers = d.mcp_servers || a.mcp_servers || [];
  /* pane_text from the detail endpoint is already redacted; the
   * registry fallback (pane_tail_block / pane_tail) is NOT, so prefer
   * detail whenever we have it. */
  var pane = "";
  var paneSource = "unavailable";
  if (d.pane_text != null) {
    pane = d.pane_text;
    paneSource = d.pane_text_source || (pane ? "cached" : "unavailable");
  } else {
    pane = a.pane_tail_block || a.pane_tail || "";
    paneSource = pane ? "cached" : "unavailable";
  }

  var workdir = d.workdir || a.workdir || "";
  var pid = d.pid || a.pid || "";
  var multiplexer = d.multiplexer || a.multiplexer || "";
  var idleSec = d.idle_seconds != null ? d.idle_seconds : a.idle_seconds;
  var lastHeartbeat = d.last_heartbeat || a.last_heartbeat || "";
  var registeredAt = d.registered_at || a.registered_at || "";
  var subagentCount =
    d.subagent_count != null ? d.subagent_count : a.subagent_count;
  var q5 =
    d.quota_5h_used_pct != null ? d.quota_5h_used_pct : a.quota_5h_used_pct;
  var q7 =
    d.quota_7d_used_pct != null ? d.quota_7d_used_pct : a.quota_7d_used_pct;
  var q5Reset = d.quota_5h_reset_at || a.quota_5h_reset_at || "";
  var q7Reset = d.quota_7d_reset_at || a.quota_7d_reset_at || "";
  function _fmtQuota(pct, reset) {
    if (pct == null) return "-";
    var s = Number(pct).toFixed(0) + "%";
    if (reset) s += " (resets " + reset + ")";
    return s;
  }
  var metaFields = [
    ["Role", role],
    ["Machine", machine],
    ["Model", model],
    ["Multiplexer", multiplexer || "-"],
    ["PID", pid || "-"],
    ["Liveness", liveness],
    ["Context", ctxPct != null ? Number(ctxPct).toFixed(1) + "%" : "-"],
    ["5h quota", _fmtQuota(q5, q5Reset)],
    ["7d quota", _fmtQuota(q7, q7Reset)],
    [
      "Subagents (" + (subagentCount != null ? subagentCount : 0) + ")",
      subagentCount != null ? String(subagentCount) : "-",
    ],
    ["Uptime", d.uptime_seconds != null ? _fmtDuration(d.uptime_seconds) : "-"],
    ["Idle", idleSec != null ? _fmtDuration(idleSec) : "-"],
    ["Workdir", workdir || "-"],
    ["Registered", registeredAt || "-"],
    ["Last heartbeat", lastHeartbeat || "-"],
  ];
  var metaHtml = metaFields
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
    '<span class="agent-detail-header-title">' +
    escapeHtml(a.name) +
    "</span>" +
    (currentTask
      ? '<em class="agent-detail-task">' + escapeHtml(currentTask) + "</em>"
      : "") +
    '<span class="agent-detail-actions">' +
    '<button class="agent-detail-dm-btn" data-dm-name="' +
    escapeHtml(a.name) +
    '" title="Open DM with ' +
    escapeHtml(a.name) +
    '">DM</button>' +
    "</span>" +
    "</div>" +
    '<div class="agent-detail-meta-grid">' +
    metaHtml +
    "</div>" +
    "</div>";

  var paneLabel =
    'Terminal output <span class="agent-detail-pane-source">(' +
    escapeHtml(paneSource) +
    ")</span>";
  var paneHtml =
    '<div class="agent-detail-pane-wrap">' +
    '<div class="agent-detail-pane-label">' +
    paneLabel +
    "</div>" +
    '<pre class="agent-detail-pane">' +
    (pane
      ? escapeHtml(pane)
      : '<span class="muted-cell">No terminal output available (pane_text_source=' +
        escapeHtml(paneSource) +
        ")</span>") +
    "</pre>" +
    "</div>";

  var claudeMdHtml = claudeMd
    ? '<div class="agent-detail-section">' +
      '<div class="agent-detail-pane-label">CLAUDE.md</div>' +
      '<pre class="agent-detail-claude-md">' +
      escapeHtml(claudeMd) +
      "</pre>" +
      "</div>"
    : "";

  /* todo#460: .mcp.json viewer. Collapsed by default so the per-agent
   * card stays scannable — users opt in when they actually need to
   * inspect the agent's MCP wiring. Content is already redacted
   * server-side (redact_secrets); we pretty-print best-effort but fall
   * back to the raw string on JSON.parse failure so a future schema
   * change never blanks the viewer. */
  var mcpJsonPretty = mcpJson;
  if (mcpJson) {
    try {
      mcpJsonPretty = JSON.stringify(JSON.parse(mcpJson), null, 2);
    } catch (_e) {
      mcpJsonPretty = mcpJson;
    }
  }
  var mcpJsonBodyHtml = mcpJson
    ? '<pre class="agent-detail-mcp-json">' +
      escapeHtml(mcpJsonPretty) +
      "</pre>"
    : '<div class="agent-detail-mcp-json-empty muted-cell">' +
      "No .mcp.json (agent has not heartbeated with agent_meta.py yet)" +
      "</div>";
  var mcpJsonHtml =
    '<div class="agent-detail-section">' +
    '<details class="agent-detail-mcp-json-wrap"' +
    (mcpJson ? "" : " open") +
    ">" +
    '<summary class="agent-detail-pane-label agent-detail-mcp-json-summary">' +
    ".mcp.json" +
    "</summary>" +
    mcpJsonBodyHtml +
    "</details>" +
    "</div>";

  /* todo#channel-refactor — per-agent channel subscription controls.
   * Admin-only server-side gating (API returns 403 for non-admins); the
   * UI shows the controls universally and surfaces errors inline. */
  var uniqueSubs = channels ? [...new Set(channels)] : [];
  var badgesHtml = uniqueSubs
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
    badgesHtml +
    "</span>" +
    '<button type="button" class="ch-add-btn" data-agent="' +
    escapeHtml(a.name) +
    '" title="Subscribe to a channel">+</button>' +
    "</div>";

  var mcpHtml = "";
  if (mcpServers && mcpServers.length) {
    mcpHtml =
      '<div class="agent-detail-section">' +
      '<span class="agent-detail-pane-label">MCP servers: </span>' +
      mcpServers
        .map(function (m) {
          var label = typeof m === "string" ? m : m.name || JSON.stringify(m);
          return '<span class="ch-badge">' + escapeHtml(label) + "</span>";
        })
        .join("") +
      "</div>";
  }

  var splitHtml =
    '<div class="agent-detail-split">' +
    '<div class="agent-detail-split-col">' +
    paneHtml +
    "</div>" +
    '<div class="agent-detail-split-col">' +
    claudeMdHtml +
    "</div>" +
    "</div>";

  return (
    '<div class="agent-detail-view">' +
    headerHtml +
    channelsHtml +
    splitHtml +
    mcpHtml +
    mcpJsonHtml +
    "</div>"
  );
}

/* Compact human-friendly seconds formatter used in the detail header. */
function _fmtDuration(sec) {
  sec = Number(sec) || 0;
  if (sec < 60) return sec + "s";
  var m = Math.floor(sec / 60);
  if (m < 60) return m + "m";
  var h = Math.floor(m / 60);
  if (h < 24) return h + "h " + (m % 60) + "m";
  var d = Math.floor(h / 24);
  return d + "d " + (h % 24) + "h";
}

/* Render only the content area (below tab bar) */
function _renderAgentContent(grid) {
  var content = grid.querySelector("#agent-tab-content");
  if (!content) return;

  /* Update active state on tab bar */
  grid.querySelectorAll(".agent-subtab").forEach(function (btn) {
    btn.classList.toggle(
      "agent-subtab-active",
      btn.getAttribute("data-subtab") === _selectedAgentTab,
    );
  });

  if (_selectedAgentTab === "overview") {
    content.innerHTML = _buildOverviewHtml(_lastAgentsData);
    /* Click an agent card → switch to that agent's sub-tab. Shift-click
     * (or Ctrl/Cmd-click) preserves the legacy filter-tag behaviour. */
    content
      .querySelectorAll(".agent-row[data-agent-name]")
      .forEach(function (el) {
        el.style.cursor = "pointer";
        el.addEventListener("click", function (ev) {
          var name = el.getAttribute("data-agent-name");
          if (ev.shiftKey || ev.ctrlKey || ev.metaKey) {
            if (typeof addTag === "function") addTag("agent", name);
            return;
          }
          _selectedAgentTab = name;
          _renderAgentContent(grid);
        });
      });
    /* Re-apply Ctrl+K fuzzy filter after the innerHTML rewrite — see
     * todo-tab.js rationale. */
    if (typeof runFilter === "function") runFilter();
    return;
  }

  var agent = _lastAgentsData.find(function (a) {
    return a.name === _selectedAgentTab;
  });
  if (!agent) {
    content.innerHTML =
      '<p class="empty-notice">Agent "' +
      escapeHtml(_selectedAgentTab) +
      '" not found.</p>';
    return;
  }
  content.innerHTML = _renderAgentDetail(agent);
  /* Scroll pane to bottom so latest output is visible */
  var pre = content.querySelector(".agent-detail-pane");
  if (pre) pre.scrollTop = pre.scrollHeight;
  /* Kick off an async detail fetch so the next re-render has the
   * redacted pane_text, MCP servers, uptime, etc. The cache shields
   * subsequent renders from flicker. */
  _fetchAgentDetail(agent.name);
  /* Wire the DM quick-action: reuse the existing DM pipeline by
   * dispatching a lightweight custom event the dashboard listens for.
   * Falls back to addTag so even without a global DM opener the user
   * at least gets the agent pre-filtered into the feed. */
  var dmBtn = content.querySelector(".agent-detail-dm-btn");
  if (dmBtn) {
    dmBtn.addEventListener("click", function (ev) {
      ev.stopPropagation();
      var name = dmBtn.getAttribute("data-dm-name");
      try {
        if (typeof window.openDmWithAgent === "function") {
          window.openDmWithAgent(name);
          return;
        }
        document.dispatchEvent(
          new CustomEvent("orochi:open-dm", {
            detail: { agent: name },
          }),
        );
      } catch (_) {}
      if (typeof addTag === "function") addTag("agent", name);
    });
  }

  _bindChannelControls(content);
}

/* ── Channel subscription controls (Phase 3) ────────────────────────── */
async function _channelMembersRequest(method, agent, channel) {
  var body = {
    channel: channel,
    username: "agent-" + agent,
  };
  if (method === "POST" || method === "PATCH") {
    body.permission = "read-write";
  }
  var res = await fetch(apiUrl("/api/channel-members/"), {
    method: method,
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": _csrfTokenForChannels(),
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

function _csrfTokenForChannels() {
  var m = document.cookie.match(/csrftoken=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

function _bindChannelControls(content) {
  content.querySelectorAll(".ch-badge-remove").forEach(function (btn) {
    btn.addEventListener("click", async function (ev) {
      ev.stopPropagation();
      var agent = btn.getAttribute("data-agent");
      var channel = btn.getAttribute("data-channel");
      if (!agent || !channel) return;
      if (!confirm("Unsubscribe " + agent + " from " + channel + "?")) return;
      try {
        await _channelMembersRequest("DELETE", agent, channel);
        _invalidateAgentDetail(agent);
      } catch (e) {
        alert("Unsubscribe failed: " + e.message);
      }
    });
  });
  content.querySelectorAll(".ch-add-btn").forEach(function (btn) {
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
        await _channelMembersRequest("POST", agent, channel);
        _invalidateAgentDetail(agent);
      } catch (e) {
        alert("Subscribe failed: " + e.message);
      }
    });
  });
}

function _invalidateAgentDetail(name) {
  delete _agentDetailCache[name];
  _fetchAgentDetail(name);
}

/* ── Overview HTML builder (extracted from renderAgentsTab) ─────────── */
function _buildOverviewHtml(agents) {
  var machineMap = {};
  agents.forEach(function (a) {
    var m = a.machine || "unknown";
    if (!machineMap[m]) machineMap[m] = [];
    machineMap[m].push(a);
  });
  var onlineCount = agents.filter(function (a) {
    return !isAgentInactive(a);
  }).length;
  var offlineCount = agents.length - onlineCount;
  var purgeBtn =
    offlineCount > 0
      ? ' <button class="purge-btn" onclick="purgeStaleAgents()" title="Remove all offline agents">Purge offline (' +
        offlineCount +
        ")</button>"
      : "";
  var summaryHtml =
    '<div class="agents-summary">' +
    '<span class="agents-count">' +
    onlineCount +
    " online, " +
    offlineCount +
    " offline across " +
    Object.keys(machineMap).length +
    " machine(s)" +
    "</span>" +
    purgeBtn +
    Object.keys(machineMap)
      .map(function (m) {
        var online = machineMap[m].filter(function (a) {
          return a.status === "online";
        }).length;
        var total = machineMap[m].length;
        var cls =
          online === total
            ? "machine-ok"
            : online > 0
              ? "machine-warn"
              : "machine-off";
        return (
          '<span class="machine-badge ' +
          cls +
          '">' +
          escapeHtml(m) +
          " (" +
          online +
          "/" +
          total +
          ")</span>"
        );
      })
      .join("") +
    "</div>";
  var tableHtml =
    '<table class="agents-registry-table">' +
    "<thead><tr>" +
    "<th>Pin</th><th></th><th>Icon</th><th>Status</th><th>Agent ID</th>" +
    "<th>Role</th><th>Host / Machine</th><th>Model</th><th>Mux</th>" +
    "<th>Ctx</th><th>Skills</th><th>PID</th><th>Channels</th>" +
    "<th>Project</th><th>Workdir</th><th>Pane</th><th>Task</th><th>Subagents</th>" +
    "<th>Config</th><th>Uptime</th><th>Last Activity</th><th>Last Seen</th>" +
    "</tr></thead><tbody>" +
    agents.map(buildAgentRow).join("") +
    "</tbody></table>";
  return summaryHtml + tableHtml;
}

/* ── Main render entry point ────────────────────────────────────────── */
async function renderAgentsTab() {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  var grid = document.getElementById("agents-grid");
  try {
    var res = await fetch(apiUrl("/api/agents/registry"));
    var agents = await res.json();

    if (agents.length === 0) {
      grid.innerHTML = '<p class="empty-notice">No agents connected</p>';
      _lastAgentsData = [];
      return;
    }

    /* Sort: online first, then offline */
    agents.sort(function (a, b) {
      var aOff = isAgentInactive(a) ? 1 : 0;
      var bOff = isAgentInactive(b) ? 1 : 0;
      return aOff - bOff || a.name.localeCompare(b.name);
    });
    _lastAgentsData = agents;

    /* If selected tab no longer exists (agent departed), revert to overview */
    if (
      _selectedAgentTab !== "overview" &&
      !agents.find(function (a) {
        return a.name === _selectedAgentTab;
      })
    ) {
      _selectedAgentTab = "overview";
    }

    /* Check if sub-tab bar already exists (preserve scroll position) */
    var existingBar = grid.querySelector("#agent-subtab-bar");
    if (!existingBar) {
      /* First render — build full layout */
      grid.innerHTML =
        _renderSubTabBar(agents) +
        '<div id="agent-tab-content" class="agent-tab-content"></div>';
      _bindSubTabBar(grid);
    } else {
      /* Update tab bar labels/active state without destroying it */
      var newBar = document.createElement("div");
      newBar.innerHTML = _renderSubTabBar(agents);
      var updatedBar = newBar.firstChild;
      existingBar.parentNode.replaceChild(updatedBar, existingBar);
      _bindSubTabBar(grid);
    }

    _renderAgentContent(grid);
  } catch (e) {
    console.error("Agents tab error:", e);
  }
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try {
      msgInput.setSelectionRange(savedStart, savedEnd);
    } catch (_) {}
  }
}

function livenessColor(liveness) {
  switch (liveness) {
    case "online":
      return "#4ecdc4";
    case "idle":
      return "#ffd93d";
    case "stale":
      return "#ff8c42";
    case "offline":
      return "#ef4444";
    default:
      return "#888";
  }
}

/* todo#418: pane_state badge — maps classifier label to display color+icon.
 * Labels are defined in pane_state.py (scitex-orochi/hub/utils/pane_state.py).
 * Stuck states (y_n_prompt, auth_error, mcp_broken, compose_pending) use
 * amber/red so they visually pop in the Agents tab row. */
function paneStateColor(ps) {
  switch (ps) {
    case "running":
      return "#4ecdc4";
    case "waiting":
      return "#ffd93d";
    case "y_n_prompt":
      return "#ff8c42";
    case "auth_error":
      return "#ef4444";
    case "mcp_broken":
      return "#ef4444";
    case "compose_pending":
      return "#ff8c42";
    case "booting":
      return "#888";
    case "ghost":
      return "#555";
    case "dead":
      return "#ef4444";
    default:
      return "#888";
  }
}

function renderPaneStateBadge(paneState, stuckPromptText) {
  if (!paneState) return '<span class="muted-cell">-</span>';
  var color = paneStateColor(paneState);
  var label = paneState.replace(
    /_/g,
    "\u2009",
  ); /* thin space for readability */
  var title = stuckPromptText
    ? "Stuck at: " + stuckPromptText.slice(0, 200)
    : paneState;
  var badge =
    '<span class="pane-state-badge" style="color:' +
    color +
    ";border-color:" +
    color +
    '" title="' +
    escapeHtml(title) +
    '">' +
    escapeHtml(label) +
    "</span>";
  /* For stuck states, show a truncated excerpt of the prompt inline */
  var promptHtml = "";
  if (
    stuckPromptText &&
    ["y_n_prompt", "auth_error", "compose_pending"].indexOf(paneState) !== -1
  ) {
    promptHtml =
      '<span class="pane-state-prompt muted-cell" title="' +
      escapeHtml(stuckPromptText) +
      '">' +
      escapeHtml(stuckPromptText.slice(0, 60)) +
      (stuckPromptText.length > 60 ? "\u2026" : "") +
      "</span>";
  }
  return badge + promptHtml;
}

function formatUptime(isoStr) {
  if (!isoStr) return "-";
  var d = new Date(isoStr);
  if (isNaN(d.getTime())) return "-";
  var sec = Math.floor((Date.now() - d.getTime()) / 1000);
  if (sec < 60) return sec + "s";
  var min = Math.floor(sec / 60);
  if (min < 60) return min + "m";
  var hr = Math.floor(min / 60);
  if (hr < 24) return hr + "h " + (min % 60) + "m";
  var days = Math.floor(hr / 24);
  return days + "d " + (hr % 24) + "h";
}

function buildAgentRow(a) {
  var inactive = isAgentInactive(a);
  var color = getResolvedAgentColor(a.name);
  var liveness = a.liveness || (inactive ? "offline" : "online");
  var statusColor = livenessColor(liveness);
  var statusLabel = liveness;
  var agentIcon = getSenderIcon(a.name, true, 24);
  var dotHtml =
    '<span class="status-dot-inline" style="background:' +
    statusColor +
    '"></span>' +
    '<span class="status-label" style="color:' +
    statusColor +
    '">' +
    statusLabel +
    "</span>";
  var uniqueChannels = [...new Set(a.channels || [])];
  var channelsHtml = uniqueChannels
    .map(function (c) {
      return '<span class="ch-badge">' + escapeHtml(c) + "</span>";
    })
    .join("");
  var pinIcon = a.pinned ? "\uD83D\uDCCC" : "\uD83D\uDCCD";
  var pinTitle = a.pinned ? "Unpin" : "Pin";
  var pinBtnHtml =
    '<button class="pin-btn' +
    (a.pinned ? " pinned" : "") +
    '" data-pin-name="' +
    escapeHtml(a.name) +
    '" title="' +
    pinTitle +
    '" onclick="event.stopPropagation();togglePinAgent(\'' +
    escapeHtml(a.name).replace(/'/g, "\\'") +
    "', " +
    !a.pinned +
    ')">' +
    pinIcon +
    "</button>";
  var rowClass =
    "agent-row" +
    (inactive ? " agent-inactive" : "") +
    (a.pinned && inactive ? " pinned-offline" : "");
  return (
    '<tr class="' +
    rowClass +
    '" data-agent-name="' +
    escapeHtml(a.name) +
    '">' +
    "<td>" +
    pinBtnHtml +
    "</td>" +
    '<td><button class="kill-btn" data-kill-name="' +
    escapeHtml(a.name) +
    '" title="Kill agent" onclick="event.stopPropagation();killAgent(\'' +
    escapeHtml(a.name).replace(/'/g, "\\'") +
    "', this)\">\u2715</button>" +
    '<button class="restart-btn" data-restart-name="' +
    escapeHtml(a.name) +
    '" title="Restart agent" onclick="event.stopPropagation();restartAgent(\'' +
    escapeHtml(a.name).replace(/'/g, "\\'") +
    "', this)\">\u21BB</button></td>" +
    '<td class="agent-icon-cell avatar-clickable" data-avatar-agent="' +
    escapeHtml(a.name) +
    '" title="Click to change avatar" onclick="event.stopPropagation();openAvatarPicker(\'' +
    escapeHtml(a.name).replace(/'/g, "\\'") +
    "')\">" +
    agentIcon +
    "</td>" +
    "<td>" +
    dotHtml +
    "</td>" +
    '<td class="agent-id-cell">' +
    escapeHtml(cleanAgentName(a.agent_id || a.name)) +
    "</td>" +
    "<td>" +
    escapeHtml(a.role || "agent") +
    "</td>" +
    '<td class="monospace-cell">' +
    escapeHtml(a.machine || "unknown") +
    "</td>" +
    '<td class="muted-cell">' +
    escapeHtml(a.model || "-") +
    "</td>" +
    '<td class="muted-cell">' +
    escapeHtml(a.multiplexer || "-") +
    "</td>" +
    '<td class="ctx-cell">' +
    renderContextBadge(a.context_pct) +
    "</td>" +
    '<td class="skills-cell">' +
    renderSkillsBadge(a.skills_loaded) +
    "</td>" +
    '<td class="pid-cell muted-cell">' +
    (a.pid ? String(a.pid) : "-") +
    "</td>" +
    '<td class="small-cell">' +
    channelsHtml +
    "</td>" +
    '<td class="muted-cell">' +
    escapeHtml(a.project || "-") +
    "</td>" +
    '<td class="monospace-cell small-cell" title="' +
    escapeHtml(a.workdir || "") +
    '">' +
    escapeHtml(a.workdir ? a.workdir.replace(/^\/home\/[^/]+/, "~") : "-") +
    "</td>" +
    '<td class="pane-state-cell">' +
    renderPaneStateBadge(a.pane_state, a.stuck_prompt_text) +
    "</td>" +
    '<td class="task-cell">' +
    escapeHtml(a.current_task || "-") +
    "</td>" +
    '<td class="small-cell">' +
    (a.subagents && a.subagents.length > 0
      ? a.subagents
          .map(function (s) {
            var sClass =
              s.status === "done" ? "subagent-done" : "subagent-running";
            return (
              '<span class="subagent-badge ' +
              sClass +
              '" title="' +
              escapeHtml(s.task || "") +
              '">' +
              escapeHtml(s.name || "subagent") +
              "</span>"
            );
          })
          .join(" ")
      : a.subagent_count && a.subagent_count > 0
        ? '<span class="subagent-badge subagent-running" title="' +
          a.subagent_count +
          ' subagent(s)">\uD83D\uDD27 ' +
          a.subagent_count +
          "</span>"
        : '<span class="muted-cell">-</span>') +
    "</td>" +
    "<td>" +
    (a.claude_md
      ? '<button class="claude-md-btn" onclick="event.stopPropagation();toggleClaudeMd(this)" title="View CLAUDE.md">CLAUDE.md</button>'
      : '<span class="muted-cell">-</span>') +
    "</td>" +
    '<td class="muted-cell" title="Registered: ' +
    escapeHtml(a.registered_at || "") +
    '">' +
    formatUptime(a.registered_at) +
    "</td>" +
    '<td class="muted-cell" title="' +
    escapeHtml(a.last_action || "") +
    '">' +
    (a.idle_seconds != null
      ? '<span class="idle-badge idle-' +
        liveness +
        '">' +
        formatUptime(a.last_action) +
        " ago</span>"
      : timeAgo(a.last_action)) +
    "</td>" +
    '<td class="muted-cell" title="' +
    escapeHtml(a.last_heartbeat || "") +
    '">' +
    (typeof relativeAge === "function"
      ? relativeAge(a.last_heartbeat)
      : timeAgo(a.last_heartbeat)) +
    "</td>" +
    "</tr>" +
    (function () {
      var raw = a.pane_tail_block || a.pane_tail || "";
      if (!raw) return "";
      var lines = String(raw).split(/\r?\n/);
      var tail = lines.slice(-10).join("\n");
      return (
        '<tr class="agent-pane-row"><td colspan="22">' +
        '<pre class="agent-pane-preview" title="Last 10 lines of ' +
        escapeHtml(a.name) +
        ' tmux pane">' +
        escapeHtml(tail) +
        "</pre></td></tr>"
      );
    })() +
    (a.claude_md
      ? '<tr class="claude-md-detail" style="display:none"><td colspan="22"><pre class="claude-md-content">' +
        escapeHtml(a.claude_md) +
        "</pre></td></tr>"
      : "")
  );
}

/* Toggle CLAUDE.md detail row visibility */
function toggleClaudeMd(btn) {
  var row = btn.closest("tr");
  var detailRow = row.nextElementSibling;
  if (detailRow && detailRow.classList.contains("claude-md-detail")) {
    var visible = detailRow.style.display !== "none";
    detailRow.style.display = visible ? "none" : "table-row";
    btn.textContent = visible ? "CLAUDE.md" : "Hide";
  }
}

function renderContextBadge(pct) {
  if (pct == null) return '<span class="muted-cell">-</span>';
  var n = Number(pct);
  if (isNaN(n)) return '<span class="muted-cell">-</span>';
  var color;
  if (n < 50) color = "#4ecdc4";
  else if (n < 80) color = "#ffd93d";
  else color = "#ef4444";
  return (
    '<span class="ctx-badge" title="Context window used" ' +
    'style="background:' +
    color +
    ";color:#111;padding:1px 6px;" +
    'border-radius:10px;font-size:11px;font-weight:600">ctx ' +
    n.toFixed(1) +
    "%</span>"
  );
}

function renderSkillsBadge(skills) {
  if (!skills || !skills.length) return '<span class="muted-cell">-</span>';
  var tip = skills
    .map(function (s) {
      return String(s);
    })
    .join("\n");
  return (
    '<span class="skills-badge" title="' +
    escapeHtml(tip) +
    '" ' +
    'style="background:#2a3340;color:#9ecbff;padding:1px 6px;' +
    'border-radius:10px;font-size:11px">skills:' +
    skills.length +
    "</span>"
  );
}

/* Auto-refresh: 3s when a per-agent tab is active, 1s for overview */
function startAgentsTabRefresh() {
  stopAgentsTabRefresh();
  _agentsTabInterval = setInterval(function () {
    if (activeTab === "agents-tab") renderAgentsTab();
  }, 3000);
}
function stopAgentsTabRefresh() {
  if (_agentsTabInterval) {
    clearInterval(_agentsTabInterval);
    _agentsTabInterval = null;
  }
}

async function purgeStaleAgents() {
  try {
    var token = window.__orochiCsrfToken || "";
    var headers = { "Content-Type": "application/json" };
    if (token) headers["X-CSRFToken"] = token;
    var res = await fetch(apiUrl("/api/agents/purge/"), {
      method: "POST",
      headers: headers,
      credentials: "same-origin",
    });
    if (res.ok) {
      renderAgentsTab();
    } else {
      console.error("Purge failed:", res.status);
    }
  } catch (e) {
    console.error("Purge error:", e);
  }
}

startAgentsTabRefresh();
