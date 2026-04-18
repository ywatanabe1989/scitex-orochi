/* Activity tab — real-time agent status board with per-agent sub-tabs */
/* globals: apiUrl, escapeHtml, getAgentColor, cleanAgentName, fetchAgents */

var activityRefreshTimer = null;
var _paneShowRaw = false; /* false = strip ANSI (clean), true = raw */
/* Cache for /api/agents/<name>/detail/ so the per-agent view can show
 * fields that the registry summary omits (full CLAUDE.md, full pane
 * text, redacted MCP). Mirrors _agentDetailCache in agents-tab.js. */
var _activityDetailCache = {};
var _activityDetailInflight = {};
/* todo#47 — Pane view state survives heartbeat-driven re-renders
 * (Expand stays expanded, Follow keeps polling). One agent follows
 * at a time; sub-tab switch or hidden document auto-stops. */
var _activityPaneExpanded = {}; /* name -> bool */
var _activityFollowAgent = null;
var _activityFollowTimer = null;
var ACTIVITY_FOLLOW_INTERVAL_MS = 3000;

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
    if (_overviewExpanded === name) {
      var inlineBox = document.querySelector(
        '.activity-inline-detail[data-detail-for="' +
          String(name).replace(/"/g, '\\"') +
          '"]',
      );
      var agent = (window.__lastAgents || []).find(function (a) {
        return a.name === name;
      });
      if (inlineBox && agent) _renderActivityAgentDetail(agent, inlineBox);
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

/* ── Overview controls state (filter / sort / view / color / expand) ── */
var _overviewFilter = "";
var _overviewSort = "name";
var _overviewView = "list";
var _overviewColor = "name";
var _overviewExpanded = null;
try {
  var _savedSort = localStorage.getItem("orochi.overviewSort");
  if (_savedSort === "name" || _savedSort === "machine")
    _overviewSort = _savedSort;
  var _savedView = localStorage.getItem("orochi.overviewView");
  if (
    _savedView === "list" ||
    _savedView === "tiled" ||
    _savedView === "topology"
  )
    _overviewView = _savedView;
  var _savedColor = localStorage.getItem("orochi.overviewColor");
  if (
    _savedColor === "name" ||
    _savedColor === "host" ||
    _savedColor === "account"
  )
    _overviewColor = _savedColor;
} catch (_e) {
  /* localStorage may be unavailable — fall back to defaults */
}

/* Pick the color key from the agent record based on the user-selected
 * "color by" option. Hash returns a deterministic pastel color for any
 * non-empty string (reuses getAgentColor), so the same machine, name,
 * or account always maps to the same color across rows. Empty key
 * falls back to name so rows never render colorless. */
function _colorKeyFor(a) {
  var key = "";
  if (_overviewColor === "host") key = a.machine || "";
  else if (_overviewColor === "account") key = a.account_email || "";
  if (!key) key = a.name || "";
  return key;
}

/* Render the hook-event panels (recent tools, prompts, Agent calls,
 * background tasks, tool-use counts). All inputs are arrays/objects from
 * the /api/agents/<name>/detail/ endpoint; empty inputs collapse the
 * whole section to an empty string so nothing renders when hooks aren't
 * wired up for this agent. */
function _renderHookPanels(
  recentTools,
  recentPrompts,
  agentCalls,
  backgroundTasks,
  toolCounts,
) {
  var hasAny =
    (recentTools && recentTools.length) ||
    (recentPrompts && recentPrompts.length) ||
    (agentCalls && agentCalls.length) ||
    (backgroundTasks && backgroundTasks.length) ||
    (toolCounts && Object.keys(toolCounts).length);
  if (!hasAny) return "";
  function _hhmmss(ts) {
    if (!ts || ts.length < 19) return "";
    return ts.slice(11, 19);
  }
  function _list(items, keyFn, emptyLabel) {
    if (!items || !items.length)
      return '<li class="hook-empty">' + escapeHtml(emptyLabel) + "</li>";
    return items
      .slice()
      .reverse()
      .map(function (it) {
        var ts = _hhmmss(it.ts || "");
        var txt = keyFn(it);
        return (
          '<li class="hook-row">' +
          '<span class="hook-ts">' +
          escapeHtml(ts) +
          "</span>" +
          '<span class="hook-txt" title="' +
          escapeHtml(txt) +
          '">' +
          escapeHtml(txt) +
          "</span></li>"
        );
      })
      .join("");
  }
  var toolsHtml = _list(
    recentTools,
    function (it) {
      var name = it.tool || it.kind || "?";
      var prev = it.input_preview || "";
      return prev ? name + " — " + prev : name;
    },
    "no tool calls recorded",
  );
  var promptsHtml = _list(
    recentPrompts,
    function (it) {
      return it.prompt_preview || "";
    },
    "no prompts recorded",
  );
  var agentCallsHtml = _list(
    agentCalls,
    function (it) {
      return it.input_preview || "";
    },
    "no Agent tool calls recorded",
  );
  var bgHtml = _list(
    backgroundTasks,
    function (it) {
      return it.input_preview || "";
    },
    "no background tasks recorded",
  );
  var countsHtml = "";
  if (toolCounts && Object.keys(toolCounts).length) {
    var pairs = Object.keys(toolCounts)
      .map(function (k) {
        return [k, Number(toolCounts[k]) || 0];
      })
      .sort(function (a, b) {
        return b[1] - a[1];
      });
    countsHtml = pairs
      .map(function (p) {
        return (
          '<span class="hook-count-chip" title="' +
          escapeHtml(p[0]) +
          " used " +
          p[1] +
          ' times">' +
          escapeHtml(p[0]) +
          " ×" +
          p[1] +
          "</span>"
        );
      })
      .join("");
  }
  function _panel(title, bodyHtml, extraClass) {
    return (
      '<div class="hook-panel ' +
      (extraClass || "") +
      '">' +
      '<div class="hook-panel-title">' +
      escapeHtml(title) +
      "</div>" +
      bodyHtml +
      "</div>"
    );
  }
  var panels =
    _panel("Recent tools", '<ul class="hook-list">' + toolsHtml + "</ul>") +
    _panel("Recent prompts", '<ul class="hook-list">' + promptsHtml + "</ul>") +
    _panel("Agent calls", '<ul class="hook-list">' + agentCallsHtml + "</ul>") +
    _panel(
      "Background tasks (" +
        (backgroundTasks ? backgroundTasks.length : 0) +
        ")",
      '<ul class="hook-list">' + bgHtml + "</ul>",
    ) +
    (countsHtml
      ? _panel(
          "Tool use counts",
          '<div class="hook-counts">' + countsHtml + "</div>",
          "hook-panel-wide",
        )
      : "");
  return '<div class="agent-detail-section hook-panels">' + panels + "</div>";
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
    pane_text_full: d.pane_text_full || "",
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
  /* todo#55/#56/#58: collapse redundant FQDN suffixes and hide
   * <synthetic>-style model placeholders, mirroring the same polish on
   * the Agents tab detail card. */
  var _machine = a.machine || "?";
  var _fqdn = a.hostname_canonical || "";
  var _redundant = [".local", ".localdomain", ".lan", ".home.arpa"];
  var _fqdnUseful = _fqdn && _fqdn !== _machine;
  if (_fqdnUseful) {
    for (var _i = 0; _i < _redundant.length; _i++) {
      if (_fqdn === _machine + _redundant[_i]) {
        _fqdnUseful = false;
        break;
      }
    }
  }
  var _machineDisplay = _fqdnUseful ? _machine + " (" + _fqdn + ")" : _machine;
  var _rawModel = a.model || "";
  var _modelDisplay =
    _rawModel.length > 2 &&
    _rawModel.charAt(0) === "<" &&
    _rawModel.charAt(_rawModel.length - 1) === ">"
      ? "—"
      : _rawModel || "-";
  var metaFields = [
    ["Role", a.role || "agent"],
    ["Machine", _machineDisplay],
    ["Model", _modelDisplay],
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
    [
      "Last tool",
      d.last_tool_at
        ? _fmtSec(_secondsSinceIso(d.last_tool_at)) +
          " ago" +
          (d.last_tool_name ? " (" + d.last_tool_name + ")" : "")
        : "-",
    ],
    [
      "Last MCP",
      d.last_mcp_tool_at
        ? _fmtSec(_secondsSinceIso(d.last_mcp_tool_at)) +
          " ago" +
          (d.last_mcp_tool_name ? " (" + d.last_mcp_tool_name + ")" : "")
        : "-",
    ],
    [
      "Last action",
      d.last_action_at
        ? _fmtSec(_secondsSinceIso(d.last_action_at)) +
          " ago (" +
          (d.last_action_name || "?") +
          " " +
          (d.last_action_outcome || "?") +
          (d.last_action_elapsed_s != null
            ? ", " + Number(d.last_action_elapsed_s).toFixed(1) + "s"
            : "") +
          ")"
        : "-",
    ],
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
  /* Terminal pane — Refresh / Tail / Copy / Expand. Expand only renders
   * when pane_text_full is available (newer agent_meta.py push); older
   * agents just see the short tail. Tail polls /detail every 3 s for a
   * live-tail feel. ANSI is always stripped — the raw/clean toggle was
   * removed (ywatanabe 2026-04-19: "make it clean by default"). */
  var paneFull = a.pane_text_full || "";
  var paneFullAvailable = !!paneFull;
  var _isFollowing = _activityFollowAgent === a.name;
  var _isExpanded = !!_activityPaneExpanded[a.name] && paneFullAvailable;
  var paneSource = _isExpanded ? paneFull : pane || "";
  var paneContent = paneSource ? _stripAnsi(paneSource) : "";
  /* Primary DM channel for web→agent interaction (ywatanabe 2026-04-19:
   * "like sending 'how are you?' in the terminal from web"). We send
   * into the agent's existing dm:agent:<name>|human:<user> channel; the
   * agent is already subscribed to it and sees the text as a Claude
   * Code message in its terminal. Falls back to the first non-#general
   * channel if no explicit DM exists. */
  var agentDmChannel = "";
  var agentChannels = a.channels || [];
  for (var _ci = 0; _ci < agentChannels.length; _ci++) {
    var _c = agentChannels[_ci] || "";
    if (_c.indexOf("dm:agent:" + a.name + "|") === 0) {
      agentDmChannel = _c;
      break;
    }
  }
  if (!agentDmChannel) {
    for (var _cj = 0; _cj < agentChannels.length; _cj++) {
      if ((agentChannels[_cj] || "").indexOf("dm:") === 0) {
        agentDmChannel = agentChannels[_cj];
        break;
      }
    }
  }
  var paneHtml =
    '<div class="agent-detail-pane-wrap">' +
    '<div class="agent-detail-pane-label-row">' +
    '<span class="agent-detail-pane-label">Terminal output</span>' +
    '<span class="agent-detail-pane-controls">' +
    (paneFullAvailable
      ? '<button type="button" class="agent-detail-pane-btn' +
        (_isExpanded ? " agent-detail-pane-btn-on" : "") +
        '" data-act-pane-action="expand" data-agent="' +
        escapeHtml(a.name) +
        '" title="' +
        (_isExpanded
          ? "Show short pane (~10 lines)"
          : "Show ~500-line scrollback") +
        '">' +
        (_isExpanded ? "Collapse" : "Expand") +
        "</button>"
      : "") +
    '<button type="button" class="agent-detail-pane-btn" ' +
    'data-act-pane-action="refresh" data-agent="' +
    escapeHtml(a.name) +
    '" title="Force re-fetch of detail">Refresh</button>' +
    '<button type="button" class="agent-detail-pane-btn' +
    (_isFollowing ? " agent-detail-pane-btn-on" : "") +
    '" data-act-pane-action="follow" data-agent="' +
    escapeHtml(a.name) +
    '" title="' +
    (_isFollowing
      ? "Stop live-tail (auto-refresh every " +
        ACTIVITY_FOLLOW_INTERVAL_MS / 1000 +
        "s)"
      : "Live-tail — re-poll /detail every " +
        ACTIVITY_FOLLOW_INTERVAL_MS / 1000 +
        "s") +
    '">' +
    (_isFollowing ? "Tailing" : "Tail") +
    "</button>" +
    '<button type="button" class="agent-detail-pane-btn" ' +
    'data-act-pane-action="copy" data-agent="' +
    escapeHtml(a.name) +
    '" title="Copy pane text to clipboard">Copy</button>' +
    "</span>" +
    "</div>" +
    '<pre class="agent-detail-pane" id="agent-detail-pane-content" data-agent="' +
    escapeHtml(a.name) +
    '" data-pane-view="' +
    (_isExpanded ? "full" : "short") +
    '">' +
    (paneContent
      ? escapeHtml(paneContent)
      : '<span class="muted-cell">No terminal output available</span>') +
    "</pre>" +
    (agentDmChannel
      ? '<div class="activity-send-row" data-send-agent="' +
        escapeHtml(a.name) +
        '" data-send-channel="' +
        escapeHtml(agentDmChannel) +
        '">' +
        '<input type="text" class="activity-send-input" ' +
        'placeholder="message to agent (Enter to send via ' +
        escapeHtml(agentDmChannel) +
        ')" ' +
        'autocomplete="off" spellcheck="false">' +
        '<button type="button" class="activity-send-btn" ' +
        'title="Send to agent">Send</button>' +
        "</div>"
      : "") +
    "</div>";
  /* CLAUDE.md — always render the section so the slot is visible even
   * before /detail/ returns or when the agent hasn't pushed one. User
   * reported the section silently disappearing ("often occurs"); a
   * placeholder makes the absence explicit instead of a data gap. */
  var claudeMd = a.claude_md || a.claude_md_head || "";
  var claudeMdHtml =
    '<div class="agent-detail-section">' +
    '<div class="agent-detail-pane-label">CLAUDE.md</div>' +
    (claudeMd
      ? '<pre class="agent-detail-claude-md">' + escapeHtml(claudeMd) + "</pre>"
      : '<pre class="agent-detail-claude-md agent-detail-claude-md-empty">' +
        "(loading — fetching /detail/ for this agent; empty here means " +
        "the agent hasn't pushed a CLAUDE.md via agent_meta yet)" +
        "</pre>") +
    "</div>";
  /* Channel subscriptions (with + / x controls, admin-gated server-side). */
  /* DMs are always available for any agent — hiding them from the badge
   * list reduces noise and matches the overview row's channel column,
   * which also filters DMs (ywatanabe 2026-04-19: "dm channel should be
   * dropped as dm is always available"). */
  var uniqueSubs = [...new Set(a.channels || [])].filter(function (c) {
    return c && c.indexOf("dm:") !== 0;
  });
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
  /* Hook-event panels — populated from scitex-agent-container ring buffer
   * (PreToolUse / PostToolUse / UserPromptSubmit). Only visible when the
   * hooks are wired up for this agent; otherwise the lists are empty. */
  var hooksHtml = _renderHookPanels(
    d.recent_tools || [],
    d.recent_prompts || [],
    d.agent_calls || [],
    d.background_tasks || [],
    d.tool_counts || {},
  );
  /* Preserve scrollTop of long, user-scrolled panes across heartbeat-driven
   * re-renders. Without this the CLAUDE.md viewer (and .mcp.json viewer)
   * snaps to the top every poll tick — reported by ywatanabe 2026-04-18
   * 20:45 / 21:02 / 21:13 on the *Agents* tab (which this file renders,
   * despite its historical name of "activity-tab"). Mirrors the fix in
   * agents-tab.js (PR #221, #222). */
  var _preserveScrollClasses = [
    "agent-detail-claude-md",
    "agent-detail-mcp-json",
  ];
  var _savedScrollTops = {};
  _preserveScrollClasses.forEach(function (cls) {
    var el = grid.querySelector("." + cls);
    if (el && el.scrollTop > 0) _savedScrollTops[cls] = el.scrollTop;
  });
  grid.innerHTML =
    '<div class="agent-detail-view">' +
    headerHtml +
    taskHtml +
    channelsHtml +
    splitHtml +
    hooksHtml +
    "</div>";
  var _restoreScroll = function () {
    _preserveScrollClasses.forEach(function (cls) {
      if (_savedScrollTops[cls] != null) {
        var el = grid.querySelector("." + cls);
        if (el) el.scrollTop = _savedScrollTops[cls];
      }
    });
  };
  _restoreScroll();
  if (typeof requestAnimationFrame === "function") {
    requestAnimationFrame(_restoreScroll);
  }
  /* Scroll pane to bottom */
  var pre = grid.querySelector(".agent-detail-pane");
  if (pre) pre.scrollTop = pre.scrollHeight;
  _bindActivityPaneControls(grid, a.name, pane, paneFull);
  _bindActivityChannelControls(grid, a.name);
  _bindActivitySendInput(grid, a.name);
}

/* Web→agent interaction: Enter or Send click posts the text into the
 * agent's DM channel via the existing /api/messages/ REST endpoint.
 * Agent sees it in its next poll as a Claude Code message, which
 * appears in the agent's terminal pane. Mirrors chat.js sendMessage
 * but scoped to a specific agent's DM. */
function _bindActivitySendInput(grid, name) {
  var row = grid.querySelector(
    '.activity-send-row[data-send-agent="' +
      String(name).replace(/"/g, '\\"') +
      '"]',
  );
  if (!row) return;
  var input = row.querySelector(".activity-send-input");
  var btn = row.querySelector(".activity-send-btn");
  if (!input || !btn) return;
  var channel = row.getAttribute("data-send-channel");
  if (!channel) return;
  function _doSend() {
    var text = (input.value || "").trim();
    if (!text) return;
    var payload = { channel: channel, content: text };
    if (typeof sendOrochiMessage === "function") {
      sendOrochiMessage({
        type: "message",
        sender:
          typeof userName !== "undefined" && userName ? userName : "human",
        payload: payload,
      });
      input.value = "";
      btn.textContent = "Sent";
      setTimeout(function () {
        btn.textContent = "Send";
      }, 800);
    } else {
      console.error("sendOrochiMessage unavailable — web→agent send failed");
    }
  }
  btn.addEventListener("click", function (ev) {
    ev.preventDefault();
    _doSend();
  });
  input.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      _doSend();
    }
  });
}

/* todo#47 — Refresh / Copy / Follow / Expand for the Agents-tab pane.
 * Expand state + Follow state live in module vars so heartbeat-driven
 * re-renders preserve them. */
function _bindActivityPaneControls(grid, name, pane, paneFull) {
  grid
    .querySelectorAll('[data-act-pane-action="refresh"]')
    .forEach(function (btn) {
      btn.addEventListener("click", function (ev) {
        ev.preventDefault();
        btn.disabled = true;
        var original = btn.textContent;
        btn.textContent = "Refreshing…";
        delete _activityDetailCache[name];
        _fetchActivityDetail(name);
        setTimeout(function () {
          btn.disabled = false;
          btn.textContent = original;
        }, 1500);
      });
    });
  grid
    .querySelectorAll('[data-act-pane-action="copy"]')
    .forEach(function (btn) {
      btn.addEventListener("click", async function (ev) {
        ev.preventDefault();
        var pre = grid.querySelector("#agent-detail-pane-content");
        var text = pre ? pre.textContent || "" : "";
        try {
          await navigator.clipboard.writeText(text);
          var original = btn.textContent;
          btn.textContent = "Copied";
          setTimeout(function () {
            btn.textContent = original;
          }, 1200);
        } catch (err) {
          alert("Copy failed: " + err.message);
        }
      });
    });
  grid
    .querySelectorAll('[data-act-pane-action="expand"]')
    .forEach(function (btn) {
      btn.addEventListener("click", function (ev) {
        ev.preventDefault();
        var pre = grid.querySelector("#agent-detail-pane-content");
        if (!pre) return;
        var view = pre.getAttribute("data-pane-view") || "short";
        var nextView = view === "short" ? "full" : "short";
        var src = nextView === "full" ? paneFull : pane || "";
        var body = src ? (_paneShowRaw ? src : _stripAnsi(src)) : "";
        pre.innerHTML = body
          ? escapeHtml(body)
          : '<span class="muted-cell">No terminal output available</span>';
        pre.setAttribute("data-pane-view", nextView);
        if (nextView === "full") {
          _activityPaneExpanded[name] = true;
          btn.textContent = "Collapse";
          btn.classList.add("agent-detail-pane-btn-on");
          btn.setAttribute("title", "Show short pane (~10 lines)");
        } else {
          _activityPaneExpanded[name] = false;
          btn.textContent = "Expand";
          btn.classList.remove("agent-detail-pane-btn-on");
          btn.setAttribute("title", "Show ~500-line scrollback");
        }
        pre.scrollTop = pre.scrollHeight;
      });
    });
  grid
    .querySelectorAll('[data-act-pane-action="follow"]')
    .forEach(function (btn) {
      btn.addEventListener("click", function (ev) {
        ev.preventDefault();
        if (_activityFollowAgent === name) {
          _stopActivityFollow();
        } else {
          _startActivityFollow(name);
        }
      });
    });
}

function _stopActivityFollow() {
  if (_activityFollowTimer != null) {
    clearInterval(_activityFollowTimer);
    _activityFollowTimer = null;
  }
  _activityFollowAgent = null;
  document
    .querySelectorAll('[data-act-pane-action="follow"]')
    .forEach(function (b) {
      b.classList.remove("agent-detail-pane-btn-on");
      b.textContent = "Follow";
      b.setAttribute(
        "title",
        "Poll /detail every " +
          ACTIVITY_FOLLOW_INTERVAL_MS / 1000 +
          "s for a live-tail feel",
      );
    });
}

function _startActivityFollow(name) {
  _stopActivityFollow();
  _activityFollowAgent = name;
  document
    .querySelectorAll(
      '[data-act-pane-action="follow"][data-agent="' + name + '"]',
    )
    .forEach(function (b) {
      b.classList.add("agent-detail-pane-btn-on");
      b.textContent = "Following";
      b.setAttribute("title", "Stop live-tail polling");
    });
  _activityFollowTimer = setInterval(function () {
    if (!_activityFollowAgent) return;
    if (typeof document !== "undefined" && document.hidden) return;
    if (_overviewExpanded !== _activityFollowAgent) {
      _stopActivityFollow();
      return;
    }
    delete _activityDetailCache[_activityFollowAgent];
    _fetchActivityDetail(_activityFollowAgent);
  }, ACTIVITY_FOLLOW_INTERVAL_MS);
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
  /* Any membership mutation invalidates the topology arrow cache so
   * next render re-fetches per-channel permissions. */
  if (typeof _invalidateTopoPerms === "function") _invalidateTopoPerms();
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

/* Derive a higher-level "what is the agent doing" state, distinct from
 * the WS-level connection status and the heartbeat-age liveness.
 *
 * Precedence (highest wins):
 *   selecting  — pane classifier says agent is blocked on a choice
 *                (y_n_prompt, compose_pending_unsent) or needs a human
 *                (auth_error, mcp_broken)
 *   running    — LLM fired a tool within the last 30s (active work)
 *   idle       — connected, quiet
 *   offline    — WS is disconnected
 */
function _computeAgentState(a) {
  var pane = a.pane_state || "";
  if (pane === "compacting" || pane === "auto_compact") {
    return "compacting";
  }
  if (
    pane === "y_n_prompt" ||
    pane === "compose_pending_unsent" ||
    pane === "auth_error" ||
    pane === "mcp_broken" ||
    pane === "stuck"
  ) {
    return "selecting";
  }
  var connected = (a.status || "online") !== "offline";
  if (!connected) return "offline";
  /* Heuristic fallback for compact when pane classifier hasn't fired:
   * the last tool name contains "compact" (mcp or slash command). */
  var lastTool = String(a.last_tool_name || "").toLowerCase();
  if (lastTool.indexOf("compact") !== -1) return "compacting";
  var lastToolSec =
    typeof _secondsSinceIso === "function"
      ? _secondsSinceIso(a.last_tool_at || a.last_action)
      : null;
  if (lastToolSec != null && lastToolSec < 30) return "running";
  return "idle";
}

/* Signature cache — topology rebuilds every heartbeat were visibly
 * slow on busy hubs (user: "Viz is quite slow"). The SVG only needs
 * to repaint when the visible set, their statuses, or the expand
 * target changes; the heartbeat-driven re-renders that merely bump
 * `last_heartbeat` / `idle_seconds` would otherwise rebuild every
 * edge and label. We short-circuit on a compact signature. */
var _topoLastSig = "";
var _topoLastExpanded = null;
var _topoViewBox = null; /* {x,y,w,h} — persisted zoom/pan across re-renders */
var _topoViewBoxHistory = []; /* back stack (undo) */
var _topoViewBoxFuture = []; /* forward stack (redo) */
var _topoZoomWired = false;
var _topoLastPositions = { agents: {}, channels: {} };
/* Landing bubbles — short-lived speech-bubble DOM nodes attached to
 * the destination node when a packet arrives. Multiple arrivals at the
 * same node stack vertically; older bubbles lift up to make room.
 * ywatanabe 2026-04-19: "after reaching to the target, as a bubble,
 * the message should be shown and stacked and disappeared with timer
 * like 1 s duration" / "in a fade in/out manner".
 * Shape: { "<x>,<y>": [ {g, expireAt, timer}, ... ] } (oldest first). */
var _topoLandingStacks = Object.create(null);
var _TOPO_LANDING_DUR_MS = 1300;
var _TOPO_LANDING_STACK_MAX = 4;
var _TOPO_LANDING_STEP_PX = 18;
/* Client-side "sticky" subscriptions — edges added via drag-drop that
 * survive server-authoritative refetches until the backend starts
 * returning the membership in a.channels. Without this, the optimistic
 * mutation of window.__lastAgents gets clobbered the moment
 * fetchAgentsThrottled resolves, and the edge vanishes until the user
 * reloads. ywatanabe 2026-04-19: "after subscription by dragging,
 * show the edge soon" / "we need reload or make another subscription".
 * Shape: { "<agent-name>|<channel>": true }. */
var _topoStickyEdges = {};
function _topoStickyKey(agent, channel) {
  return String(agent || "") + "|" + String(channel || "");
}
var _topoHidden = { agents: {}, channels: {} };
try {
  var _topoHiddenRaw = localStorage.getItem("orochi.topoHidden");
  if (_topoHiddenRaw) {
    var _topoHiddenParsed = JSON.parse(_topoHiddenRaw);
    if (_topoHiddenParsed && typeof _topoHiddenParsed === "object") {
      _topoHidden.agents = _topoHiddenParsed.agents || {};
      _topoHidden.channels = _topoHiddenParsed.channels || {};
    }
  }
} catch (_e) {}
function _topoSaveHidden() {
  try {
    localStorage.setItem(
      "orochi.topoHidden",
      JSON.stringify({
        agents: _topoHidden.agents,
        channels: _topoHidden.channels,
      }),
    );
  } catch (_e) {}
}
function _topoHiddenSignature() {
  return (
    "h:" +
    Object.keys(_topoHidden.agents).sort().join(",") +
    ";" +
    Object.keys(_topoHidden.channels).sort().join(",")
  );
}
function _topoHide(kind, name) {
  if (!kind || !name) return;
  var hn =
    (typeof userName !== "undefined" && userName) ||
    window.__orochiUserName ||
    "";
  if (kind === "agent" && hn && name === hn) return;
  if (kind === "agent") _topoHidden.agents[name] = true;
  else if (kind === "channel") _topoHidden.channels[name] = true;
  else return;
  _topoSaveHidden();
  _topoLastSig = "";
  if (typeof renderActivityTab === "function") renderActivityTab();
}
function _topoUnhide(kind, name) {
  if (kind === "agent") delete _topoHidden.agents[name];
  else if (kind === "channel") delete _topoHidden.channels[name];
  _topoSaveHidden();
  _topoLastSig = "";
  if (typeof renderActivityTab === "function") renderActivityTab();
}
function _topoUnhideAll() {
  _topoHidden = { agents: {}, channels: {} };
  _topoSaveHidden();
  _topoLastSig = "";
  if (typeof renderActivityTab === "function") renderActivityTab();
}
window._topoHide = _topoHide;
window._topoUnhide = _topoUnhide;
window._topoUnhideAll = _topoUnhideAll;
function _topoApplyStickyEdges() {
  /* Merge sticky edges into window.__lastAgents so _renderActivity-
   * Topology (and every other consumer of a.channels) sees them as
   * real memberships. Purges sticky entries that the server has
   * caught up to — keeps the set from growing unbounded. */
  var live = window.__lastAgents || [];
  var keep = {};
  Object.keys(_topoStickyEdges).forEach(function (k) {
    var pipe = k.indexOf("|");
    if (pipe < 0) return;
    var agent = k.slice(0, pipe);
    var ch = k.slice(pipe + 1);
    var row = null;
    for (var i = 0; i < live.length; i++) {
      if (live[i].name === agent) {
        row = live[i];
        break;
      }
    }
    if (!row) {
      /* Agent vanished from the live list — drop the sticky too. */
      return;
    }
    var chs = Array.isArray(row.channels) ? row.channels : [];
    if (chs.indexOf(ch) !== -1) {
      /* Server caught up — no need to keep overriding. */
      return;
    }
    row.channels = chs.concat([ch]);
    keep[k] = true;
  });
  _topoStickyEdges = keep;
}

/* Permission-direction arrows: map of "<channel>::<agentName>" → one of
 * "read-only" | "read-write" | "write-only". Populated by
 * _refreshTopoPerms() which calls /api/channel-members/?channel=…
 * per visible channel and caches the result. Missing pairs default to
 * "read-write" (bidirectional arrows — safer than hiding direction).
 * TTL = 30 s; any subscribe/unsubscribe invalidates the whole map. */
var _topoChannelPerms = Object.create(null);
var _topoChannelPermsFetchedAt = 0;
var _topoChannelPermsInflight = Object.create(null); /* channel → bool */
var TOPO_PERMS_TTL_MS = 30000;

function _invalidateTopoPerms() {
  _topoChannelPerms = Object.create(null);
  _topoChannelPermsFetchedAt = 0;
}
window._invalidateTopoPerms = _invalidateTopoPerms;

function _permKey(channel, agentName) {
  return channel + "::" + agentName;
}

/* Fetch membership+permission for one channel and fold the result into
 * _topoChannelPerms. Silent on failure — the caller treats missing
 * entries as read-write. */
async function _fetchTopoPermsForChannel(channel) {
  if (_topoChannelPermsInflight[channel]) return;
  _topoChannelPermsInflight[channel] = true;
  try {
    var res = await fetch(
      apiUrl("/api/channel-members/?channel=" + encodeURIComponent(channel)),
      { credentials: "same-origin" },
    );
    if (!res.ok) return;
    var rows = await res.json();
    if (!Array.isArray(rows)) return;
    rows.forEach(function (row) {
      if (!row || !row.username) return;
      /* Backend usernames for agents are "agent-<name>"; the topology
       * renderer keys on bare agent names. Strip the prefix so the
       * cache lookup matches either form. */
      var uname = String(row.username);
      var bare = uname.indexOf("agent-") === 0 ? uname.slice(6) : uname;
      var perm = row.permission || "read-write";
      _topoChannelPerms[_permKey(channel, bare)] = perm;
      _topoChannelPerms[_permKey(channel, uname)] = perm;
    });
  } catch (_e) {
    /* ignore — fall back to read-write default on missing entries */
  } finally {
    _topoChannelPermsInflight[channel] = false;
    /* Trigger a lightweight repaint so arrows appear once data lands.
     * We don't want to rebuild the whole SVG (would thrash zoom); just
     * re-decorate the existing lines. */
    if (typeof _repaintTopoArrows === "function") _repaintTopoArrows();
  }
}

/* Kick off one fetch per visible channel if the cache is cold or
 * expired. Non-blocking: arrows render with defaults first, then
 * upgrade once each fetch resolves. */
function _refreshTopoPerms(channels) {
  var now = Date.now();
  if (now - _topoChannelPermsFetchedAt < TOPO_PERMS_TTL_MS) return;
  _topoChannelPermsFetchedAt = now;
  channels.forEach(function (c) {
    _fetchTopoPermsForChannel(c);
  });
}

/* Multi-select state for the topology. A Set of agent names currently
 * selected; the renderer adds `.topo-agent-selected` to matching nodes
 * and the floating action bar appears when size ≥ 2. */
var _topoSelected = Object.create(null); /* name → true */
function _topoSelectedNames() {
  return Object.keys(_topoSelected);
}
function _topoSelectClear() {
  _topoSelected = Object.create(null);
}
function _topoSelectToggle(name) {
  if (_topoSelected[name]) delete _topoSelected[name];
  else _topoSelected[name] = true;
}
function _topoSelectAdd(name) {
  if (name) _topoSelected[name] = true;
}

/* Left-pool multi-select — ctrl-click chips to accumulate a selection,
 * then drag the set onto another chip / canvas node to bulk-subscribe.
 * Separate from _topoSelected (which is the canvas lasso selection) so
 * the two affordances don't step on each other. ywatanabe 2026-04-19:
 * "ctrl click should allow multiple select" / "drag and drop should be
 * implemented between pools as well" / "multiple subscription". */
var _topoPoolSelection = {
  agents: Object.create(null),
  channels: Object.create(null),
};
function _topoPoolSelectionSize() {
  return (
    Object.keys(_topoPoolSelection.agents).length +
    Object.keys(_topoPoolSelection.channels).length
  );
}
function _topoPoolSelectionHas(kind, name) {
  var bucket = kind === "channel" ? "channels" : "agents";
  return !!_topoPoolSelection[bucket][name];
}
function _topoPoolSelectToggle(kind, name) {
  var bucket = kind === "channel" ? "channels" : "agents";
  if (_topoPoolSelection[bucket][name]) delete _topoPoolSelection[bucket][name];
  else _topoPoolSelection[bucket][name] = true;
}
function _topoPoolSelectClear() {
  _topoPoolSelection = {
    agents: Object.create(null),
    channels: Object.create(null),
  };
}
function _topoPoolSelectOnly(kind, name) {
  _topoPoolSelectClear();
  var bucket = kind === "channel" ? "channels" : "agents";
  _topoPoolSelection[bucket][name] = true;
}
/* Walk the DOM and re-apply .topo-pool-chip-selected to chips that are
 * in the current selection. Called after every selection mutation so
 * the highlight stays in sync without waiting for a full re-render. */
function _topoPoolSelectionPaint(root) {
  var host = root || document;
  var chips = host.querySelectorAll(".topo-pool-chip");
  for (var i = 0; i < chips.length; i++) {
    var chip = chips[i];
    var ag = chip.getAttribute("data-agent");
    var ch = chip.getAttribute("data-channel");
    var sel = ag
      ? !!_topoPoolSelection.agents[ag]
      : !!(ch && _topoPoolSelection.channels[ch]);
    chip.classList.toggle("topo-pool-chip-selected", sel);
  }
}

/* Map a permission string to the SVG attribute fragment that places
 * arrows on the correct endpoint(s). Each line is drawn agent→channel
 * (x1/y1 = agent, x2/y2 = channel), so marker-start sits at the agent
 * and marker-end sits at the channel.
 *   read-only   (agent reads from channel)  → arrow at agent end
 *   read-write  (bidirectional)              → arrows on both ends
 *   write-only  (agent writes to channel)    → arrow at channel end
 */
function _markerAttrsForPerm(perm) {
  if (perm === "read-only") {
    return ' marker-start="url(#topo-arrow-start)"';
  }
  if (perm === "write-only") {
    return ' marker-end="url(#topo-arrow-end)"';
  }
  /* default = read-write → both */
  return ' marker-start="url(#topo-arrow-start)" marker-end="url(#topo-arrow-end)"';
}

/* After a permission-fetch resolves we only need to update the
 * `marker-start`/`marker-end` attributes on existing <line> elements,
 * NOT rebuild the SVG (that would thrash zoom state). */
function _repaintTopoArrows() {
  var svg = document.querySelector(".activity-view-topology .topo-svg");
  if (!svg) return;
  var lines = svg.querySelectorAll(
    ".topo-edges line[data-agent][data-channel]",
  );
  for (var i = 0; i < lines.length; i++) {
    var ln = lines[i];
    var name = ln.getAttribute("data-agent");
    var ch = ln.getAttribute("data-channel");
    var perm = _topoChannelPerms[_permKey(ch, name)] || "read-write";
    if (perm === "read-only") {
      ln.setAttribute("marker-start", "url(#topo-arrow-start)");
      ln.removeAttribute("marker-end");
    } else if (perm === "write-only") {
      ln.removeAttribute("marker-start");
      ln.setAttribute("marker-end", "url(#topo-arrow-end)");
    } else {
      ln.setAttribute("marker-start", "url(#topo-arrow-start)");
      ln.setAttribute("marker-end", "url(#topo-arrow-end)");
    }
  }
}

/* Spawn one glowing packet traveling from (fromX,fromY) -> (toX,toY)
 * over `dur` ms, optionally delayed. Self-removes after animation. */
/* Modern directional packet. Three-layer glow (outer halo + mid ring
 * + bright core) rotated to face the direction of travel so the
 * whole shape reads as a capsule pointing downstream. Flying a few
 * of these in quick succession gives a "data bus" feel (buzz factor
 * per ywatanabe 2026-04-19). Self-removes ~80ms after animation. */
function _topoSpawnPacket(edges, from, to, dur, delay, klass, opts) {
  var ns = "http://www.w3.org/2000/svg";
  var dx = to.x - from.x;
  var dy = to.y - from.y;
  var inPlace = Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5;
  /* Pure JS requestAnimationFrame animation — SMIL was unreliable in
   * practice (the packets "glowed in place" without visibly moving).
   * rAF gives us a guaranteed per-frame setAttribute on cx/cy, plus
   * easy fade-out control. ywatanabe 2026-04-19: "from start to end,
   * use 1 sec". */
  var g = document.createElementNS(ns, "g");
  g.setAttribute("class", "topo-packet " + (klass || ""));
  var halo, core, burst;
  if (inPlace) {
    burst = document.createElementNS(ns, "circle");
    burst.setAttribute("cx", String(from.x));
    burst.setAttribute("cy", String(from.y));
    burst.setAttribute("r", "4");
    burst.setAttribute("fill-opacity", "0.55");
    g.appendChild(burst);
  } else {
    halo = document.createElementNS(ns, "circle");
    halo.setAttribute("cx", String(from.x));
    halo.setAttribute("cy", String(from.y));
    halo.setAttribute("r", "16");
    halo.setAttribute("fill-opacity", "0.2");
    g.appendChild(halo);
    core = document.createElementNS(ns, "circle");
    core.setAttribute("cx", String(from.x));
    core.setAttribute("cy", String(from.y));
    core.setAttribute("r", "7");
    core.setAttribute("fill-opacity", "0.95");
    g.appendChild(core);
  }
  /* Babble — a small speech-bubble that follows the packet showing the
   * first ~60 chars of the message text (or "📎" for attachment-only
   * packets). Fades out in sync with the packet. Built as an SVG
   * <rect>+<text> pair so it translates naturally with cx/cy updates
   * and stays inside the topology <svg>'s coord system. SVG <text>
   * has no native background, hence the <rect> drawn first. */
  var babbleText = opts && opts.text ? String(opts.text) : "";
  /* Truncate to 60 chars + ellipsis. Also collapse newlines so the
   * bubble stays one line. */
  babbleText = babbleText.replace(/\s+/g, " ").trim();
  if (babbleText.length > 60) babbleText = babbleText.slice(0, 60) + "\u2026";
  var babbleRect = null;
  var babbleTxt = null;
  if (babbleText) {
    babbleTxt = document.createElementNS(ns, "text");
    babbleTxt.setAttribute("class", "topo-packet-babble");
    babbleTxt.setAttribute("x", String(from.x));
    babbleTxt.setAttribute("y", String(from.y - 14));
    babbleTxt.setAttribute("text-anchor", "middle");
    babbleTxt.setAttribute("dominant-baseline", "middle");
    babbleTxt.textContent = babbleText;
    /* Underlay rectangle for legibility — sized after we measure the
     * <text>, since bbox needs the node attached to the DOM. */
    babbleRect = document.createElementNS(ns, "rect");
    babbleRect.setAttribute("class", "topo-packet-babble-bg");
    babbleRect.setAttribute("rx", "3");
    babbleRect.setAttribute("ry", "3");
    /* Insert rect first so text renders on top. */
    g.appendChild(babbleRect);
    g.appendChild(babbleTxt);
  }
  edges.appendChild(g);

  /* Size the bg rect once the text is in the DOM (getBBox needs it). */
  var babbleBBox = null;
  if (babbleTxt && babbleRect) {
    try {
      babbleBBox = babbleTxt.getBBox();
    } catch (_) {
      babbleBBox = null;
    }
    if (babbleBBox) {
      var padX = 4;
      var padY = 1.5;
      babbleRect.setAttribute("x", String(babbleBBox.x - padX));
      babbleRect.setAttribute("y", String(babbleBBox.y - padY));
      babbleRect.setAttribute("width", String(babbleBBox.width + padX * 2));
      babbleRect.setAttribute("height", String(babbleBBox.height + padY * 2));
    }
  }

  var startTime = null;
  function _frame(ts) {
    if (!g.parentNode) return; /* removed externally */
    if (startTime == null) startTime = ts;
    var elapsed = ts - startTime - delay;
    if (elapsed < 0) {
      requestAnimationFrame(_frame);
      return;
    }
    var t = Math.min(1, elapsed / dur);
    var curX = from.x;
    var curY = from.y;
    if (inPlace) {
      /* Expanding fading ring. */
      burst.setAttribute("r", String(4 + (20 - 4) * t));
      burst.setAttribute("fill-opacity", String(0.55 * (1 - t)));
    } else {
      curX = from.x + dx * t;
      curY = from.y + dy * t;
      halo.setAttribute("cx", String(curX));
      halo.setAttribute("cy", String(curY));
      core.setAttribute("cx", String(curX));
      core.setAttribute("cy", String(curY));
      /* Breathing pulse — subtle size modulation while in flight so the
       * packet reads as a live/organic thing, not a rigid dot. Two
       * breaths per traversal, halo ±22%, core ±15%. ywatanabe
       * 2026-04-19: "add animation, to the packet; a bit changing size
       * like breezing". */
      var breath = Math.sin(t * Math.PI * 4);
      halo.setAttribute("r", String(16 * (1 + 0.22 * breath)));
      core.setAttribute("r", String(7 * (1 + 0.15 * breath)));
      /* Fade out in the last 20% so the packet evaporates into the
       * destination node instead of hard-landing with lingering glow. */
      if (t > 0.8) {
        var fade = 1 - (t - 0.8) / 0.2;
        halo.setAttribute("fill-opacity", String(0.2 * fade));
        core.setAttribute("fill-opacity", String(0.95 * fade));
      }
    }
    /* Move the babble bubble along with the packet. The bubble sits
     * ~14px above the packet so it never overlaps the core dot. It
     * fades out on the same last-20% curve so landing feels clean. */
    if (babbleTxt) {
      babbleTxt.setAttribute("x", String(curX));
      babbleTxt.setAttribute("y", String(curY - 14));
      if (babbleRect && babbleBBox) {
        /* Recompute rect position based on current text-anchor=middle. */
        babbleRect.setAttribute("x", String(curX - babbleBBox.width / 2 - 4));
        babbleRect.setAttribute(
          "y",
          String(curY - 14 - babbleBBox.height / 2 - 1.5),
        );
      }
      var bfade = t > 0.8 ? 1 - (t - 0.8) / 0.2 : 1;
      babbleTxt.setAttribute("fill-opacity", String(bfade));
      if (babbleRect) {
        babbleRect.setAttribute("fill-opacity", String(0.8 * bfade));
      }
    }
    if (t < 1) {
      requestAnimationFrame(_frame);
    } else {
      /* Landing bubble — show the message text as a speech bubble
       * attached to the destination node (stacks with concurrent
       * arrivals, fades in/out over 1s). Skipped for inPlace packets
       * (those are already at the origin) and when there's no text. */
      if (!inPlace && babbleText) {
        try {
          var svgRoot = edges && edges.ownerSVGElement;
          if (svgRoot) _topoLandingBubble(svgRoot, to, babbleText);
        } catch (_) {
          /* non-fatal */
        }
      }
      /* Remove shortly after landing so no lingering glow remains. */
      setTimeout(function () {
        if (g.parentNode) g.parentNode.removeChild(g);
      }, 20);
    }
  }
  requestAnimationFrame(_frame);
  /* Safety removal in case the tab is backgrounded and rAF stalls. */
  setTimeout(
    function () {
      if (g.parentNode) g.parentNode.removeChild(g);
    },
    dur + delay + 500,
  );
}

/* Landing bubble — a short-lived speech bubble ATTACHED to the
 * destination node when a packet arrives. Separate from the in-flight
 * babble that rides the packet. Multiple arrivals at the same node
 * stack vertically (newest at bottom, older bubbles lift ~18px up).
 * Fade driven by CSS (@keyframes topo-landing-fade 1s ease-out);
 * lifecycle (stack cleanup) driven by JS setTimeout.
 * ywatanabe 2026-04-19: "after reaching to the target, as a bubble,
 * the message should be shown and stacked and disappeared with timer
 * like 1 s duration" / "and as bubble on the destination". */
function _topoLandingBubble(svgRoot, target, text) {
  if (!svgRoot || !target || text == null) return;
  var txt = String(text).replace(/\s+/g, " ").trim();
  if (!txt) return;
  if (txt.length > 60) txt = txt.slice(0, 60) + "\u2026";
  /* Prefer a dedicated .topo-landings layer so bubbles render above
   * edges/nodes. Create it lazily (render() doesn't know we exist). */
  var layer = svgRoot.querySelector(".topo-landings");
  if (!layer) {
    layer = document.createElementNS("http://www.w3.org/2000/svg", "g");
    layer.setAttribute("class", "topo-landings");
    svgRoot.appendChild(layer);
  }
  var ns = "http://www.w3.org/2000/svg";
  var key = Math.round(target.x) + "," + Math.round(target.y);
  var stack = _topoLandingStacks[key];
  if (!stack) {
    stack = [];
    _topoLandingStacks[key] = stack;
  }
  /* Cap stack — drop oldest (index 0) if we'd exceed the cap. */
  while (stack.length >= _TOPO_LANDING_STACK_MAX) {
    var dropped = stack.shift();
    if (dropped) {
      if (dropped.timer) clearTimeout(dropped.timer);
      if (dropped.g && dropped.g.parentNode) {
        dropped.g.parentNode.removeChild(dropped.g);
      }
    }
  }
  /* Two-level group so CSS transform-driven fade (translateY) composes
   * with our JS-driven stack position (translate(x,y)) without one
   * overwriting the other. Outer <g> = position attribute; inner
   * <g class="topo-landing"> = CSS keyframe animation. */
  var g = document.createElementNS(ns, "g");
  var inner = document.createElementNS(ns, "g");
  inner.setAttribute("class", "topo-landing");
  var label = document.createElementNS(ns, "text");
  label.setAttribute("class", "topo-landing-text");
  label.setAttribute("text-anchor", "middle");
  label.setAttribute("dominant-baseline", "middle");
  label.textContent = txt;
  var rect = document.createElementNS(ns, "rect");
  rect.setAttribute("class", "topo-landing-bg");
  rect.setAttribute("rx", "4");
  rect.setAttribute("ry", "4");
  inner.appendChild(rect);
  inner.appendChild(label);
  g.appendChild(inner);
  layer.appendChild(g);
  /* Position — newest bubble sits closest to the node (offset 0);
   * older entries (already in stack) get pushed up one step each. */
  function _placeStack() {
    for (var i = 0; i < stack.length; i++) {
      var entry = stack[i];
      if (!entry || !entry.g) continue;
      /* Index (stack.length - 1 - i) counted from newest: 0 = closest. */
      var posFromBottom = stack.length - 1 - i;
      var dy = -24 - posFromBottom * _TOPO_LANDING_STEP_PX;
      entry.g.setAttribute(
        "transform",
        "translate(" + target.x + "," + (target.y + dy) + ")",
      );
    }
  }
  var entry = {
    g: g,
    timer: null,
    expireAt: Date.now() + _TOPO_LANDING_DUR_MS,
  };
  stack.push(entry);
  /* Need the text in the DOM first so getBBox works; then size the rect. */
  try {
    var bbox = label.getBBox();
    var padX = 6;
    var padY = 2;
    rect.setAttribute("x", String(bbox.x - padX));
    rect.setAttribute("y", String(bbox.y - padY));
    rect.setAttribute("width", String(bbox.width + padX * 2));
    rect.setAttribute("height", String(bbox.height + padY * 2));
  } catch (_) {
    /* bbox may fail if tab is hidden — harmless, bubble will still animate. */
  }
  _placeStack();
  entry.timer = setTimeout(function () {
    /* Remove from stack + DOM. Then re-place remaining so they drop
     * back toward the node as older ones expire. */
    var idx = stack.indexOf(entry);
    if (idx >= 0) stack.splice(idx, 1);
    if (g.parentNode) g.parentNode.removeChild(g);
    if (stack.length === 0) {
      delete _topoLandingStacks[key];
    } else {
      _placeStack();
    }
  }, _TOPO_LANDING_DUR_MS);
}

/* Briefly brighten the line matching the given endpoints. */
function _topoFlashEdge(edges, a, b, delay, dur) {
  var lines = edges.querySelectorAll("line");
  for (var i = 0; i < lines.length; i++) {
    var ln = lines[i];
    var x1 = Number(ln.getAttribute("x1"));
    var y1 = Number(ln.getAttribute("y1"));
    var x2 = Number(ln.getAttribute("x2"));
    var y2 = Number(ln.getAttribute("y2"));
    var matchA =
      Math.abs(x1 - a.x) < 0.5 &&
      Math.abs(y1 - a.y) < 0.5 &&
      Math.abs(x2 - b.x) < 0.5 &&
      Math.abs(y2 - b.y) < 0.5;
    var matchB =
      Math.abs(x1 - b.x) < 0.5 &&
      Math.abs(y1 - b.y) < 0.5 &&
      Math.abs(x2 - a.x) < 0.5 &&
      Math.abs(y2 - a.y) < 0.5;
    if (matchA || matchB) {
      (function (line) {
        setTimeout(function () {
          line.classList.add("topo-edge-live");
          setTimeout(function () {
            line.classList.remove("topo-edge-live");
          }, dur);
        }, delay);
      })(ln);
      break;
    }
  }
}

/* Message-pass animation:
 *   leg 1 (0-900ms):   sender-agent → channel-node
 *   leg 2 (900-1800ms): channel-node → each other subscribed agent
 * So a post visibly propagates through the graph in two stages, the
 * way real pub/sub traffic would. If msg carries attachments, the
 * packet variant "topo-packet-artifact" is used (styled differently
 * as a babble bubble). ywatanabe 2026-04-19. */
function _topoPulseEdge(sender, channel, opts) {
  /* Diagnostic tap — logs every bail-out with the relevant inputs so we
   * can see in DevTools console exactly why an expected pulse didn't
   * fire (most common: sender/recipient not in _topoLastPositions, or
   * topology tab not visible). Set window.__topoPulseDebug = false to
   * silence. ywatanabe 2026-04-19: "DM does not work in visual
   * feedback. why???". */
  var _dbg = window.__topoPulseDebug !== false;
  if (!channel) {
    if (_dbg)
      console.warn("[topo-pulse] bail: no channel", { sender, channel });
    return;
  }
  var svg = document.querySelector(".activity-view-topology .topo-svg");
  if (!svg) {
    if (_dbg)
      console.warn("[topo-pulse] bail: topology svg not in DOM (tab hidden?)", {
        sender,
        channel,
      });
    return;
  }
  var edges = svg.querySelector(".topo-edges");
  if (!edges) {
    if (_dbg)
      console.warn("[topo-pulse] bail: .topo-edges not found", {
        sender,
        channel,
      });
    return;
  }
  var klass =
    opts && opts.isArtifact ? "topo-packet-artifact" : "topo-packet-message";
  /* Babble text that rides each packet. Caller passes the message
   * preview via opts.text (or opts.babble). Attachment-only posts
   * pass "📎" from app.js. */
  var babble = "";
  if (opts) {
    babble = opts.text || opts.babble || "";
  }
  var packetOpts = { text: babble };
  /* 0.5 second per leg — balance between legibility and not blocking
   * rapid multi-message bursts (ywatanabe 2026-04-19: "0.5s / edge
   * would be good in balance"). */
  var LEG = 500;
  /* DM branch — DMs don't flow through a channel node on the canvas.
   * Reuse the standard 2-leg pattern but with a virtual invisible
   * midpoint between sender and each recipient, so legs 1+2 form a
   * straight line from sender to recipient. ywatanabe 2026-04-19:
   * "just place invisible node between user/agents and apply the same
   * pattern to them". Channel formats:
   *   dm:agent:<agent>|human:<user>  → recipients = [agent, user]
   *   dm:group:<csv names>           → recipients = [name1, name2, ...]
   */
  if (channel.indexOf("dm:") === 0) {
    var humanKeyDm =
      (typeof userName !== "undefined" && userName) ||
      window.__orochiUserName ||
      "";
    var dmRecipients = [];
    if (channel.indexOf("dm:group:") === 0) {
      dmRecipients = channel.slice("dm:group:".length).split(",");
    } else {
      /* Canonical DM names (backend api.py::_canonical_dm_name):
       *   dm:<principal>|<principal>...  where each principal is
       *   "agent:<name>" or "human:<user>" in sorted order. Split on
       *   "|" and strip known prefixes — handles any permutation and
       *   any N-party DM. */
      var dmBody = channel.slice("dm:".length);
      dmBody.split("|").forEach(function (part) {
        if (!part) return;
        if (part.indexOf("agent:") === 0) dmRecipients.push(part.slice(6));
        else if (part.indexOf("human:") === 0) dmRecipients.push(part.slice(6));
        else dmRecipients.push(part);
      });
    }
    var dmFrom = sender ? _topoLastPositions.agents[sender] : null;
    if (_dbg) {
      var _now = new Date();
      var _ts =
        _now.toISOString().slice(11, 23) + " (" + _now.getTime() + "ms)";
      console.info("%c[topo-pulse] DM", "color:#4ecdc4;font-weight:700", _ts);
      console.info("[topo-pulse]   sender:", sender);
      console.info("[topo-pulse]   channel:", channel);
      console.info("[topo-pulse]   recipients:", dmRecipients);
      console.info(
        "[topo-pulse]   sender pos:",
        dmFrom ? { x: dmFrom.x, y: dmFrom.y } : "(not on graph)",
      );
      dmRecipients.forEach(function (rn) {
        var rp = _topoLastPositions.agents[rn];
        console.info(
          "[topo-pulse]   recipient pos [" + rn + "]:",
          rp ? { x: rp.x, y: rp.y } : "(not on graph)",
        );
      });
      console.info(
        "[topo-pulse]   available node keys:",
        Object.keys(_topoLastPositions.agents),
      );
    }
    if (!dmRecipients.length && _dbg) {
      console.warn("[topo-pulse] DM bail: parsed zero recipients", {
        channel,
      });
    }
    dmRecipients.forEach(function (rn) {
      if (!rn || rn === sender) return;
      var rp = _topoLastPositions.agents[rn];
      if (!rp) {
        if (_dbg)
          console.warn("[topo-pulse] DM bail: recipient not on graph", {
            recipient: rn,
            channel,
          });
        return;
      }
      if (!dmFrom) {
        if (_dbg)
          console.warn(
            "[topo-pulse] DM: sender not on graph; falling back to in-place pulse at recipient",
            { sender, recipient: rn },
          );
        _topoSpawnPacket(edges, rp, rp, 220, 0, klass, { text: babble });
        return;
      }
      /* Invisible midpoint — exactly between sender and recipient so
       * legs render as a single straight line. */
      var mid = {
        x: (dmFrom.x + rp.x) / 2,
        y: (dmFrom.y + rp.y) / 2,
      };
      _topoSpawnPacket(edges, dmFrom, mid, LEG, 0, klass, { text: babble });
      _topoSpawnPacket(edges, mid, rp, LEG, LEG, klass, { text: babble });
    });
    return;
  }
  var cp = _topoLastPositions.channels[channel];
  if (!cp) return;
  /* Leg 1 — sender → channel IF the sender is a visible agent. Human
   * posts (sender = username, not an agent name) skip leg 1 and start
   * from the channel node — so the user still sees their post
   * propagate via leg 2 ("double-click channel → post" case). */
  var ap = sender ? _topoLastPositions.agents[sender] : null;
  var leg2Delay = 0;
  if (ap) {
    _topoSpawnPacket(edges, ap, cp, LEG, 0, klass, packetOpts);
    leg2Delay = LEG;
  } else {
    /* Brief in-place pulse on the channel so the origin is visible
     * before the fan-out leg. */
    _topoSpawnPacket(edges, cp, cp, 180, 0, klass, packetOpts);
  }
  /* Leg 2 — channel → every other connected node (subscribed agents
   * AND the human user). The human is in _topoLastPositions.agents
   * keyed by username but is NOT present in window.__lastAgents, so
   * the filter has two paths: an agent record with the channel in
   * its a.channels OR the human node (always treated as reachable,
   * since the dashed edges imply full connectivity). Sender is
   * excluded so replies don't bounce back to the poster. ywatanabe
   * 2026-04-19: "from the channel node, it should be sent to user
   * as well (or other connected nodes than the sender itself)". */
  var humanKey =
    (typeof userName !== "undefined" && userName) ||
    window.__orochiUserName ||
    "";
  var subscribers = Object.keys(_topoLastPositions.agents).filter(function (n) {
    if (n === sender) return false;
    if (humanKey && n === humanKey) return true;
    var ag = (window.__lastAgents || []).find(function (x) {
      return x.name === n;
    });
    return (
      ag && Array.isArray(ag.channels) && ag.channels.indexOf(channel) !== -1
    );
  });
  subscribers.forEach(function (n) {
    var target = _topoLastPositions.agents[n];
    if (!target) return;
    _topoSpawnPacket(edges, cp, target, LEG, leg2Delay, klass, packetOpts);
  });
}
window._topoPulseEdge = _topoPulseEdge;

/* Drag-rectangle zoom + shift-drag pan + double-click reset on the
 * topology SVG. State lives in _topoViewBox so heartbeat-driven
 * re-renders preserve the zoom. The inner .topo-zoombox <rect> is
 * reused as the drag overlay. Bound ONCE — the inner SVG is replaced
 * on each render but the grid wrapper is stable. */
function _wireTopoZoomPan(grid, W, H) {
  if (_topoZoomWired || !grid) return;
  _topoZoomWired = true;
  function _svgPoint(svg, clientX, clientY) {
    var pt = svg.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    var m = svg.getScreenCTM();
    if (!m) return { x: clientX, y: clientY };
    var inv = m.inverse();
    var p = pt.matrixTransform(inv);
    return { x: p.x, y: p.y };
  }
  function _pushVB() {
    if (_topoViewBox)
      _topoViewBoxHistory.push({
        x: _topoViewBox.x,
        y: _topoViewBox.y,
        w: _topoViewBox.w,
        h: _topoViewBox.h,
      });
    else _topoViewBoxHistory.push(null);
    if (_topoViewBoxHistory.length > 30) _topoViewBoxHistory.shift();
    /* Any new zoom/pan invalidates the redo chain — matches browser
     * history semantics. */
    _topoViewBoxFuture.length = 0;
  }
  function _applyVB(svg, vb) {
    if (!vb) svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    else
      svg.setAttribute(
        "viewBox",
        vb.x.toFixed(1) +
          " " +
          vb.y.toFixed(1) +
          " " +
          vb.w.toFixed(1) +
          " " +
          vb.h.toFixed(1),
      );
  }
  function _zoomAt(svg, factor, cx, cy) {
    var vb = _topoViewBox || { x: 0, y: 0, w: W, h: H };
    if (cx == null) cx = vb.x + vb.w / 2;
    if (cy == null) cy = vb.y + vb.h / 2;
    var nw = vb.w * factor;
    var nh = vb.h * factor;
    var nx = cx - (cx - vb.x) * factor;
    var ny = cy - (cy - vb.y) * factor;
    _pushVB();
    _topoViewBox = { x: nx, y: ny, w: nw, h: nh };
    _applyVB(svg, _topoViewBox);
  }
  function _popVB(svg) {
    if (!_topoViewBoxHistory.length) return;
    /* Save current state onto the future stack so Forward can redo. */
    _topoViewBoxFuture.push(
      _topoViewBox
        ? {
            x: _topoViewBox.x,
            y: _topoViewBox.y,
            w: _topoViewBox.w,
            h: _topoViewBox.h,
          }
        : null,
    );
    var prev = _topoViewBoxHistory.pop();
    _topoViewBox = prev;
    _applyVB(svg, prev);
  }
  function _forwardVB(svg) {
    if (!_topoViewBoxFuture.length) return;
    _topoViewBoxHistory.push(
      _topoViewBox
        ? {
            x: _topoViewBox.x,
            y: _topoViewBox.y,
            w: _topoViewBox.w,
            h: _topoViewBox.h,
          }
        : null,
    );
    var next = _topoViewBoxFuture.pop();
    _topoViewBox = next;
    _applyVB(svg, next);
  }
  function _resetVB(svg) {
    _pushVB();
    _topoViewBox = null;
    _applyVB(svg, null);
  }
  /* Expose for button handlers below */
  grid._topoZoomAt = _zoomAt;
  grid._topoPopVB = _popVB;
  grid._topoResetVB = _resetVB;

  var dragging = null; /* {mode:"zoom"|"pan"|"lasso", ...} */
  grid.addEventListener("mousedown", function (ev) {
    var svg = ev.target.closest && ev.target.closest(".topo-svg");
    if (!svg) return;
    if (ev.target.closest(".topo-agent, .topo-channel")) return;
    if (ev.button !== 0) return;
    ev.preventDefault();
    var start = _svgPoint(svg, ev.clientX, ev.clientY);
    /* Semantic:
     *   plain drag     = rectangle zoom
     *   shift/meta drag = pan
     *   ctrl drag       = lasso multi-select (new — ywatanabe
     *                     2026-04-19, todo#multiselect)
     * Cursor class toggles so it's default when just hovering and
     * becomes crosshair / grab / copy only during the actual drag. */
    var panMode = ev.shiftKey || ev.metaKey;
    var lassoMode = ev.ctrlKey && !panMode;
    if (lassoMode) {
      dragging = {
        mode: "lasso",
        svg: svg,
        startSvg: start,
        endSvg: start,
        additive: true,
      };
      var lrect = svg.querySelector(".topo-lasso");
      if (lrect) {
        lrect.setAttribute("x", String(start.x));
        lrect.setAttribute("y", String(start.y));
        lrect.setAttribute("width", "0");
        lrect.setAttribute("height", "0");
        lrect.style.display = "";
      }
      svg.classList.add("topo-lassoing");
    } else if (panMode) {
      var vb = _topoViewBox || { x: 0, y: 0, w: W, h: H };
      dragging = {
        mode: "pan",
        svg: svg,
        startX: ev.clientX,
        startY: ev.clientY,
        startVB: { x: vb.x, y: vb.y, w: vb.w, h: vb.h },
      };
      svg.classList.add("topo-panning");
    } else {
      dragging = {
        mode: "zoom",
        svg: svg,
        startSvg: start,
        endSvg: start,
      };
      var rect = svg.querySelector(".topo-zoombox");
      if (rect) {
        rect.setAttribute("x", String(start.x));
        rect.setAttribute("y", String(start.y));
        rect.setAttribute("width", "0");
        rect.setAttribute("height", "0");
        rect.style.display = "";
      }
      svg.classList.add("topo-zooming");
    }
  });
  grid.addEventListener("mousemove", function (ev) {
    if (!dragging) return;
    if (dragging.mode === "zoom") {
      var p = _svgPoint(dragging.svg, ev.clientX, ev.clientY);
      dragging.endSvg = p;
      var rect = dragging.svg.querySelector(".topo-zoombox");
      if (rect) {
        var x = Math.min(dragging.startSvg.x, p.x);
        var y = Math.min(dragging.startSvg.y, p.y);
        var w = Math.abs(p.x - dragging.startSvg.x);
        var h = Math.abs(p.y - dragging.startSvg.y);
        rect.setAttribute("x", x.toFixed(1));
        rect.setAttribute("y", y.toFixed(1));
        rect.setAttribute("width", w.toFixed(1));
        rect.setAttribute("height", h.toFixed(1));
      }
    } else if (dragging.mode === "lasso") {
      var pL = _svgPoint(dragging.svg, ev.clientX, ev.clientY);
      dragging.endSvg = pL;
      var lrect = dragging.svg.querySelector(".topo-lasso");
      if (lrect) {
        var lx = Math.min(dragging.startSvg.x, pL.x);
        var ly = Math.min(dragging.startSvg.y, pL.y);
        var lw = Math.abs(pL.x - dragging.startSvg.x);
        var lh = Math.abs(pL.y - dragging.startSvg.y);
        lrect.setAttribute("x", lx.toFixed(1));
        lrect.setAttribute("y", ly.toFixed(1));
        lrect.setAttribute("width", lw.toFixed(1));
        lrect.setAttribute("height", lh.toFixed(1));
      }
    } else if (dragging.mode === "pan") {
      /* Translate clientX/Y delta to SVG coordinates via the viewBox
       * aspect ratio. Simpler: work in screen px scaled by current
       * viewBox/screen ratio. */
      var dxScreen = ev.clientX - dragging.startX;
      var dyScreen = ev.clientY - dragging.startY;
      var svgW = dragging.svg.clientWidth || W;
      var svgH = dragging.svg.clientHeight || H;
      var sx = dragging.startVB.w / svgW;
      var sy = dragging.startVB.h / svgH;
      var nx = dragging.startVB.x - dxScreen * sx;
      var ny = dragging.startVB.y - dyScreen * sy;
      _topoViewBox = {
        x: nx,
        y: ny,
        w: dragging.startVB.w,
        h: dragging.startVB.h,
      };
      dragging.svg.setAttribute(
        "viewBox",
        _topoViewBox.x.toFixed(1) +
          " " +
          _topoViewBox.y.toFixed(1) +
          " " +
          _topoViewBox.w.toFixed(1) +
          " " +
          _topoViewBox.h.toFixed(1),
      );
    }
  });
  grid.addEventListener("mouseup", function (ev) {
    if (!dragging) return;
    var svg = dragging.svg;
    if (dragging.mode === "zoom") {
      var p = _svgPoint(svg, ev.clientX, ev.clientY);
      var x = Math.min(dragging.startSvg.x, p.x);
      var y = Math.min(dragging.startSvg.y, p.y);
      var w = Math.abs(p.x - dragging.startSvg.x);
      var h = Math.abs(p.y - dragging.startSvg.y);
      if (w > 8 && h > 8) {
        _pushVB();
        _topoViewBox = { x: x, y: y, w: w, h: h };
        _applyVB(svg, _topoViewBox);
      }
      var rect = svg.querySelector(".topo-zoombox");
      if (rect) rect.style.display = "none";
    } else if (dragging.mode === "lasso") {
      var pL = _svgPoint(svg, ev.clientX, ev.clientY);
      var lx = Math.min(dragging.startSvg.x, pL.x);
      var ly = Math.min(dragging.startSvg.y, pL.y);
      var lw = Math.abs(pL.x - dragging.startSvg.x);
      var lh = Math.abs(pL.y - dragging.startSvg.y);
      var lrect = svg.querySelector(".topo-lasso");
      if (lrect) lrect.style.display = "none";
      /* Select every agent whose center lies inside the box. Tiny
       * stray-click boxes are ignored (treat as cancel). */
      if (lw > 3 && lh > 3) {
        if (!dragging.additive) _topoSelectClear();
        var added = 0;
        Object.keys(_topoLastPositions.agents || {}).forEach(function (name) {
          var pos = _topoLastPositions.agents[name];
          if (!pos) return;
          if (
            pos.x >= lx &&
            pos.x <= lx + lw &&
            pos.y >= ly &&
            pos.y <= ly + lh
          ) {
            _topoSelectAdd(name);
            added++;
          }
        });
        if (added) {
          /* Nudge the signature so the next render reflects the new
           * .topo-agent-selected classes AND shows the action bar. */
          _topoLastSig = "";
          renderActivityTab();
        }
      }
    }
    svg.classList.remove("topo-zooming");
    svg.classList.remove("topo-panning");
    svg.classList.remove("topo-lassoing");
    dragging = null;
  });
  grid.addEventListener("dblclick", function (ev) {
    var svg = ev.target.closest && ev.target.closest(".topo-svg");
    if (!svg) return;
    /* Channel dblclick-to-compose is now handled by the click-counter
     * (_topoBumpClick with kind="channel") so that triple-click can
     * open Chat on the same node. Only plain empty-area dblclick
     * resets zoom here. */
    if (ev.target.closest(".topo-channel[data-channel]")) return;
    if (ev.target.closest(".topo-agent[data-agent]")) return;
    _resetVB(svg);
  });
  /* Button controls — back / minus / reset / plus. */
  grid.addEventListener("click", function (ev) {
    var btn = ev.target.closest(".topo-ctrl-btn[data-topo-ctrl]");
    if (!btn || !grid.contains(btn)) return;
    ev.stopPropagation();
    var svg = grid.querySelector(".topo-svg");
    if (!svg) return;
    var action = btn.getAttribute("data-topo-ctrl");
    if (action === "back") _popVB(svg);
    else if (action === "forward") _forwardVB(svg);
    else if (action === "reset") _resetVB(svg);
    else if (action === "plus") _zoomAt(svg, 1 / 1.25, null, null);
    else if (action === "minus") _zoomAt(svg, 1.25, null, null);
  });
  /* Keyboard — Escape = back; 0 = reset; +/= = zoom in; - = zoom out.
   * Only fires when an SVG is visible and no text input is focused. */
  document.addEventListener("keydown", function (ev) {
    var svg = document.querySelector(".activity-view-topology .topo-svg");
    if (!svg) return;
    var tag = (document.activeElement && document.activeElement.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    if (ev.key === "Escape") {
      /* Priority: cancel an in-flight drag before popping zoom history
       * — Escape should feel like "abort current gesture". */
      if (_topoDragState && _topoDragState.moved) {
        ev.preventDefault();
        _topoCleanupDrag();
        return;
      }
      ev.preventDefault();
      _popVB(svg);
    } else if (ev.key === "0") {
      ev.preventDefault();
      _resetVB(svg);
    } else if (ev.key === "+" || ev.key === "=") {
      ev.preventDefault();
      _zoomAt(svg, 1 / 1.25, null, null);
    } else if (ev.key === "-" || ev.key === "_") {
      ev.preventDefault();
      _zoomAt(svg, 1.25, null, null);
    }
  });
  /* Wheel interactions — standard GIS/CAD convention:
   *   ctrl + wheel  = cursor-anchored zoom (10% per tick)
   *   plain wheel   = vertical pan (deltaY)
   *   shift + wheel = horizontal pan (shift remaps deltaY to deltaX,
   *                   or deltaX from a trackpad is honored)
   * ywatanabe 2026-04-19: "mouse mid should allow shift to directions,
   * supporting horizontal and vertical move" / "ctrl scroll should
   * change the zoom". */
  grid.addEventListener(
    "wheel",
    function (ev) {
      var svg = ev.target.closest && ev.target.closest(".topo-svg");
      if (!svg) return;
      ev.preventDefault();
      if (ev.ctrlKey || ev.metaKey) {
        var p = _svgPoint(svg, ev.clientX, ev.clientY);
        var factor = ev.deltaY > 0 ? 1.1 : 1 / 1.1;
        _zoomAt(svg, factor, p.x, p.y);
        return;
      }
      /* Pan — translate the viewBox. Trackpads deliver deltaX natively;
       * a plain mouse wheel sends deltaY only, which we remap to
       * horizontal when Shift is held. Screen-space delta → viewBox-
       * space via the current scale. */
      var vb = _topoViewBox || { x: 0, y: 0, w: W, h: H };
      var svgW = svg.clientWidth || W;
      var svgH = svg.clientHeight || H;
      var sx = vb.w / svgW;
      var sy = vb.h / svgH;
      var deltaX = ev.deltaX;
      var deltaY = ev.deltaY;
      if (ev.shiftKey && deltaX === 0) {
        deltaX = deltaY;
        deltaY = 0;
      }
      _pushVB();
      _topoViewBox = {
        x: vb.x + deltaX * sx,
        y: vb.y + deltaY * sy,
        w: vb.w,
        h: vb.h,
      };
      _applyVB(svg, _topoViewBox);
    },
    { passive: false },
  );
}

/* ─── Multi-select group compose modal ───────────────────────────
 * Opened from the floating action bar when ≥2 agents are selected.
 * Two posting modes:
 *   mention  → a single post in a chosen channel with @agent1 @agent2
 *              prepended to the text (needs a channel selector).
 *   group-dm → create/ensure a DM channel named
 *              "dm:group:<sorted,comma-joined,names>", subscribe each
 *              selected agent as read-write, then post the text.
 * Modal Escape closes it; we use a capture-phase listener that stops
 * propagation so the topology Escape = zoom-back handler doesn't also
 * fire while the modal is open. */
var _topoComposeEl = null;
var _topoComposeEscapeHandler = null;

function _closeTopoGroupCompose() {
  if (_topoComposeEl && _topoComposeEl.parentNode) {
    _topoComposeEl.parentNode.removeChild(_topoComposeEl);
  }
  _topoComposeEl = null;
  if (_topoComposeEscapeHandler) {
    document.removeEventListener("keydown", _topoComposeEscapeHandler, true);
    _topoComposeEscapeHandler = null;
  }
}

function _openTopoGroupCompose(agents) {
  if (!Array.isArray(agents) || agents.length < 2) return;
  _closeTopoGroupCompose();
  /* Channel options come from the global _channelPrefs map (app.js).
   * Skip dm: entries; they aren't useful as mention destinations. */
  var prefs = (typeof _channelPrefs !== "undefined" && _channelPrefs) || {};
  var chOpts = Object.keys(prefs)
    .filter(function (n) {
      return n && n.indexOf("dm:") !== 0;
    })
    .sort()
    .map(function (n) {
      return (
        '<option value="' + escapeHtml(n) + '">' + escapeHtml(n) + "</option>"
      );
    })
    .join("");
  var chips = agents
    .map(function (n) {
      return '<span class="topo-compose-chip">' + escapeHtml(n) + "</span>";
    })
    .join("");
  var overlay = document.createElement("div");
  overlay.className = "topo-compose-overlay";
  overlay.innerHTML =
    '<div class="topo-compose-modal" role="dialog" aria-modal="true">' +
    '<div class="topo-compose-header">' +
    '<span class="topo-compose-title">Post to ' +
    agents.length +
    " selected agents</span>" +
    '<button type="button" class="topo-compose-close" data-topo-compose="cancel" title="Close (Esc)">×</button>' +
    "</div>" +
    '<div class="topo-compose-body">' +
    '<div class="topo-compose-targets">' +
    chips +
    "</div>" +
    '<label class="topo-compose-label">Message</label>' +
    '<textarea class="topo-compose-text" rows="4" placeholder="Type your message…"></textarea>' +
    '<fieldset class="topo-compose-mode">' +
    '<legend class="topo-compose-label">Delivery</legend>' +
    '<label class="topo-compose-radio"><input type="radio" name="topo-compose-mode" value="mention"> mention in channel</label>' +
    '<label class="topo-compose-radio"><input type="radio" name="topo-compose-mode" value="group-dm" checked> group DM</label>' +
    "</fieldset>" +
    '<div class="topo-compose-channel" style="display:none">' +
    '<label class="topo-compose-label">Channel</label>' +
    '<select class="topo-compose-channel-select">' +
    chOpts +
    "</select>" +
    "</div>" +
    "</div>" +
    '<div class="topo-compose-footer">' +
    '<button type="button" class="topo-compose-btn" data-topo-compose="cancel">Cancel</button>' +
    '<button type="button" class="topo-compose-btn topo-compose-btn-primary" data-topo-compose="post">Post</button>' +
    "</div></div>";
  document.body.appendChild(overlay);
  _topoComposeEl = overlay;

  var textEl = overlay.querySelector(".topo-compose-text");
  var modeRadios = overlay.querySelectorAll('input[name="topo-compose-mode"]');
  var chBox = overlay.querySelector(".topo-compose-channel");
  var chSelect = overlay.querySelector(".topo-compose-channel-select");
  function _currentMode() {
    for (var i = 0; i < modeRadios.length; i++) {
      if (modeRadios[i].checked) return modeRadios[i].value;
    }
    return "group-dm";
  }
  function _syncModeUI() {
    chBox.style.display = _currentMode() === "mention" ? "" : "none";
  }
  modeRadios.forEach(function (r) {
    r.addEventListener("change", _syncModeUI);
  });
  _syncModeUI();
  setTimeout(function () {
    if (textEl) textEl.focus();
  }, 40);

  overlay.addEventListener("click", function (ev) {
    if (ev.target === overlay) {
      _closeTopoGroupCompose();
      return;
    }
    var btn = ev.target.closest("[data-topo-compose]");
    if (!btn) return;
    var action = btn.getAttribute("data-topo-compose");
    if (action === "cancel") {
      _closeTopoGroupCompose();
      return;
    }
    if (action !== "post") return;
    var text = (textEl && textEl.value ? textEl.value : "").trim();
    if (!text) {
      if (textEl) textEl.focus();
      return;
    }
    if (_currentMode() === "mention") {
      var ch = chSelect && chSelect.value ? chSelect.value : "";
      if (!ch) {
        alert("Pick a channel to mention in.");
        return;
      }
      _submitTopoMentionPost(ch, agents, text);
      _closeTopoGroupCompose();
    } else {
      _submitTopoGroupDmPost(agents, text).catch(function (err) {
        alert("Group DM failed: " + (err && err.message ? err.message : err));
      });
    }
  });

  /* Capture-phase Escape: close the modal AND stop propagation before
   * the topology Escape-handler (which pops zoom history) sees it. */
  _topoComposeEscapeHandler = function (ev) {
    if (ev.key !== "Escape") return;
    ev.preventDefault();
    ev.stopPropagation();
    _closeTopoGroupCompose();
  };
  document.addEventListener("keydown", _topoComposeEscapeHandler, true);
}

function _submitTopoMentionPost(channel, agents, text) {
  var mentions = agents
    .map(function (n) {
      return "@" + n;
    })
    .join(" ");
  var body = mentions + " " + text;
  if (typeof sendOrochiMessage !== "function") {
    alert("sendOrochiMessage unavailable — cannot post");
    return;
  }
  sendOrochiMessage({
    type: "message",
    sender: typeof userName !== "undefined" && userName ? userName : "human",
    payload: { channel: channel, content: body },
  });
}

async function _submitTopoGroupDmPost(agents, text) {
  var sorted = agents.slice().sort();
  var channel = "dm:group:" + sorted.join(",");
  /* Subscribe each selected agent to the new channel (read-write).
   * The backend creates the channel on first POST and the call is
   * idempotent for already-subscribed agents. Run sequentially so
   * any failure surfaces with a clear error instead of a race. */
  for (var i = 0; i < sorted.length; i++) {
    await _activityChannelRequest("POST", sorted[i], channel);
  }
  /* Invalidate perm cache since we just mutated memberships. */
  _invalidateTopoPerms();
  if (typeof sendOrochiMessage === "function") {
    sendOrochiMessage({
      type: "message",
      sender: typeof userName !== "undefined" && userName ? userName : "human",
      payload: { channel: channel, content: text },
    });
  }
  _closeTopoGroupCompose();
  /* Refresh agents so the list view reflects the new subscriptions. */
  if (typeof fetchAgents === "function") fetchAgents();
}

function _topoSignature(visible) {
  /* Digest: color-key selection + multi-select set + per-agent (name +
   * online-ness + liveness bucket + pinned + channel count).
   * _overviewColor goes in because swapping "color: host / account"
   * changes the text fill on every node — without it, the cache would
   * skip the re-render. Selected-set is included so toggling
   * multi-select triggers a repaint (adds/removes the
   * .topo-agent-selected class). Individual idle-seconds are NOT —
   * those flap every second and would cause pointless repaints. */
  var selSig = _topoSelectedNames().sort().join(",");
  var prefs = window._channelPrefs || {};
  var prefSig = Object.keys(prefs)
    .sort()
    .map(function (k) {
      var p = prefs[k] || {};
      return (
        k +
        (p.is_starred ? "*" : "") +
        (p.is_muted ? "m" : "") +
        (p.is_hidden ? "h" : "")
      );
    })
    .join(",");
  var stickySig = Object.keys(_topoStickyEdges).sort().join(",");
  var parts = [
    _overviewColor || "name",
    "sel:" + selSig,
    "prefs:" + prefSig,
    "sticky:" + stickySig,
    _topoHiddenSignature(),
  ];
  for (var i = 0; i < visible.length; i++) {
    var a = visible[i];
    var chCount = Array.isArray(a.channels) ? a.channels.length : 0;
    parts.push(
      (a.name || "") +
        ":" +
        (a.status === "offline" ? "0" : "1") +
        ":" +
        (a.liveness || a.status || "online") +
        ":" +
        (a.pinned ? "1" : "0") +
        ":" +
        chCount,
    );
  }
  return parts.join("|");
}

/* Radial topology renderer. Agents sit on an outer ring, channels on
 * an inner ring, with straight-line edges between subscribed pairs.
 * Pure SVG + vanilla JS — no d3, no external deps. Click an agent node
 * to toggle the inline detail panel (same hook the list view uses;
 * re-uses _renderActivityAgentDetail + _fetchActivityDetail so state
 * survives heartbeat-driven re-renders). */
function _renderActivityTopology(visible, grid) {
  _topoApplyStickyEdges();
  /* Filter out agents the user hid via right-click. Edges involving
   * hidden agents collapse automatically because they're dropped from
   * the visible loop. Human node is protected inside _topoHide. */
  visible = visible.filter(function (a) {
    return !_topoHidden.agents[a.name];
  });
  var sig = _topoSignature(visible);
  var existingSvg = grid.querySelector(".topo-svg");
  if (
    existingSvg &&
    sig === _topoLastSig &&
    _overviewExpanded === _topoLastExpanded
  ) {
    /* Nothing structurally changed — the existing SVG is still
     * accurate. Skip the full rebuild; just refresh the inline detail
     * panel if one is open (its contents DO change on heartbeat). */
    if (_overviewExpanded) {
      var agent0 = (window.__lastAgents || []).find(function (x) {
        return x.name === _overviewExpanded;
      });
      var inlineBox0 = grid.querySelector(
        '.activity-inline-detail[data-detail-for="' +
          String(_overviewExpanded).replace(/"/g, '\\"') +
          '"]',
      );
      if (agent0 && inlineBox0) {
        _renderActivityAgentDetail(agent0, inlineBox0);
      }
    }
    return;
  }
  _topoLastSig = sig;
  _topoLastExpanded = _overviewExpanded;
  /* Collect channels referenced by at least one visible agent, minus
   * DMs (implicit per-agent; not interesting in a topology view). */
  var chSet = {};
  visible.forEach(function (a) {
    (a.channels || []).forEach(function (c) {
      if (!c || c.indexOf("dm:") === 0) return;
      chSet[c] = true;
    });
  });
  /* Also include every workspace channel from _channelPrefs (the
   * sidebar channel list) so zero-subscriber channels still appear
   * as connectable nodes — ywatanabe 2026-04-19 "channels must be
   * there all the time even with 0 subscribers to allow connection".
   */
  if (typeof _channelPrefs !== "undefined" && _channelPrefs) {
    Object.keys(_channelPrefs).forEach(function (c) {
      if (!c || c.indexOf("dm:") === 0) return;
      chSet[c] = true;
    });
  }
  /* Filter out channels the user hid via channel-ctx-menu. ywatanabe
   * 2026-04-19: "hide channel does not hide as well" — the sidebar
   * respected is_hidden but the topology did not. */
  var _chPrefs = window._channelPrefs || {};
  var channels = Object.keys(chSet)
    .filter(function (c) {
      if ((_chPrefs[c] || {}).is_hidden) return false;
      if (_topoHidden.channels[c]) return false;
      return true;
    })
    .sort();

  /* Size from the grid's inner box. Fall back to generous defaults on
   * first render when clientWidth is still 0. Leave room for labels so
   * long agent names don't get clipped at the viewport edge. */
  var W = Math.max(grid.clientWidth || 0, 600);
  var H = Math.max(grid.clientHeight || 0, 420);
  /* pad: reserved edge space for agent badges (they have long names
   * like head-mba@Yusukes-MacBook-Air.local). Pushed agents toward
   * the canvas edge; inner channel ring is more compact so the two
   * rings don't crowd each other. ywatanabe 2026-04-19: "agents
   * should be more outside as they sometimes overlaps channels". */
  var pad = 100;
  var cx = W / 2;
  var cy = H / 2;
  var rOuter = Math.max(80, Math.min(W, H) / 2 - pad);
  var rInner = Math.max(40, rOuter * 0.42);

  function _pt(r, i, n) {
    /* Start at -90° so the first node sits at 12 o'clock. */
    var theta = (i / Math.max(1, n)) * Math.PI * 2 - Math.PI / 2;
    return { x: cx + r * Math.cos(theta), y: cy + r * Math.sin(theta) };
  }

  /* Human user node — the signed-in human sits on the outer ring
   * alongside agents so their posts animate from a real origin node
   * (not just an in-place channel burst) and incoming replies animate
   * back to them. ywatanabe 2026-04-19: "me, user should be another
   * node". Slotted first so it sits at 12 o'clock and is easy to
   * locate. Key in agentPos is the literal username so the existing
   * _topoPulseEdge(sender,channel) path finds it without special-
   * casing the sender field. */
  var humanName =
    (typeof userName !== "undefined" && userName) ||
    window.__orochiUserName ||
    "";
  var nSlots = visible.length + (humanName ? 1 : 0);
  var agentPos = {};
  if (humanName) {
    agentPos[humanName] = _pt(rOuter, 0, nSlots);
  }
  visible.forEach(function (a, i) {
    agentPos[a.name] = _pt(rOuter, i + (humanName ? 1 : 0), nSlots);
  });
  var chPos = {};
  channels.forEach(function (c, i) {
    chPos[c] = _pt(rInner, i, channels.length);
  });
  /* Stash for the message-pulse animator (_topoPulseEdge). Re-computed
   * on every render so a window-resize or agent add/remove still
   * targets the right coordinates. */
  _topoLastPositions = { agents: agentPos, channels: chPos };

  /* Kick off (or refresh) the per-channel permission fetch. Arrows
   * render immediately with the read-write default and upgrade in
   * place once each fetch resolves. */
  _refreshTopoPerms(channels);

  /* Edges — iterate visible agents, intersect with the channel set.
   * Each <line> carries data-channel/data-agent so _repaintTopoArrows()
   * can re-apply marker-start/marker-end without touching geometry. */
  var edgesSvg = "";
  visible.forEach(function (a) {
    var ap = agentPos[a.name];
    (a.channels || []).forEach(function (c) {
      var cp = chPos[c];
      if (!ap || !cp) return;
      var perm = _topoChannelPerms[_permKey(c, a.name)] || "read-write";
      var markers = _markerAttrsForPerm(perm);
      edgesSvg +=
        '<line class="topo-edge" data-agent="' +
        escapeHtml(a.name) +
        '" data-channel="' +
        escapeHtml(c) +
        '" x1="' +
        ap.x.toFixed(1) +
        '" y1="' +
        ap.y.toFixed(1) +
        '" x2="' +
        cp.x.toFixed(1) +
        '" y2="' +
        cp.y.toFixed(1) +
        '" stroke="#2a3a40" stroke-opacity="0.6" stroke-width="1"' +
        markers +
        "/>";
    });
  });

  /* Human → every channel edge. The signed-in human can in principle
   * post to any channel (and often reads most), so we draw an edge
   * from the human node to every channel diamond. Lines are dashed
   * + fainter so they read as "possible path" rather than a firm
   * subscription. Packets animating along them still travel at full
   * opacity. */
  if (humanName) {
    var hap = agentPos[humanName];
    if (hap) {
      channels.forEach(function (c) {
        var cp = chPos[c];
        if (!cp) return;
        edgesSvg +=
          '<line data-agent="' +
          escapeHtml(humanName) +
          '" data-channel="' +
          escapeHtml(c) +
          '" x1="' +
          hap.x.toFixed(1) +
          '" y1="' +
          hap.y.toFixed(1) +
          '" x2="' +
          cp.x.toFixed(1) +
          '" y2="' +
          cp.y.toFixed(1) +
          '" stroke="#fbbf24" stroke-opacity="0.25" stroke-width="1"' +
          ' stroke-dasharray="3 4"/>';
      });
    }
  }

  /* Per-channel subscriber counts across the visible agents. Used to
   * scale each channel diamond — "based on the number of agents, the
   * channel node can be larger" (ywatanabe 2026-04-19). */
  var chAgentCounts = {};
  visible.forEach(function (a) {
    (a.channels || []).forEach(function (c) {
      if (!chSet[c]) return;
      chAgentCounts[c] = (chAgentCounts[c] || 0) + 1;
    });
  });
  /* Channel diamonds (rotated squares) with label above. Size scales
   * with subscriber count: r ranges 8 (1 agent) to 22 (7+ agents)
   * following sqrt so visual area grows sub-linearly and busy hubs
   * don't completely overpower the layout. */
  var chSvg = channels
    .map(function (c) {
      var p = chPos[c];
      var count = chAgentCounts[c] || 1;
      var r = Math.min(22, 8 + Math.sqrt(count - 1) * 5);
      var labelText = c + " (" + count + ")";
      var pts =
        p.x +
        "," +
        (p.y - r) +
        " " +
        (p.x + r) +
        "," +
        p.y +
        " " +
        p.x +
        "," +
        (p.y + r) +
        " " +
        (p.x - r) +
        "," +
        p.y;
      var _pref = _chPrefs[c] || {};
      var chCls = " topo-node topo-channel";
      if (_pref.is_starred) chCls += " topo-channel-starred";
      if (_pref.is_muted) chCls += " topo-channel-muted";
      var starGlyph = _pref.is_starred
        ? '<text class="topo-ch-star" x="' +
          (p.x + r + 2).toFixed(1) +
          '" y="' +
          (p.y - r + 4).toFixed(1) +
          '" font-size="11" fill="#fbbf24">★</text>'
        : "";
      var muteGlyph = _pref.is_muted
        ? '<text class="topo-ch-mute" x="' +
          (p.x - r - 12).toFixed(1) +
          '" y="' +
          (p.y - r + 4).toFixed(1) +
          '" font-size="11" fill="#94a3b8">\uD83D\uDD07</text>'
        : "";
      return (
        '<g class="' +
        chCls +
        '" data-channel="' +
        escapeHtml(c) +
        '" data-agent-count="' +
        count +
        '">' +
        '<polygon points="' +
        pts +
        '" fill="#1a1a1a" stroke="#444" stroke-width="1"/>' +
        starGlyph +
        muteGlyph +
        '<text class="topo-label topo-label-ch" x="' +
        p.x +
        '" y="' +
        (p.y - r - 6).toFixed(1) +
        '" text-anchor="middle">' +
        escapeHtml(labelText) +
        "</text>" +
        "</g>"
      );
    })
    .join("");

  /* Agent nodes — no big identity disc (the disc + two LEDs read as a
   * "face", ywatanabe 2026-04-19). Just the twin-LED pair the list
   * view uses — WS on the left, functional liveness on the right —
   * followed by the agent name (identity color goes on the text).
   * Pinned agents get a small gold pushpin prefix instead of a ring. */
  var FN_COLORS = {
    online: "#4ecdc4",
    idle: "#ffd93d",
    stale: "#ff8c42",
    offline: "#555",
  };
  var agentSvg = visible
    .map(function (a) {
      var p = agentPos[a.name];
      var color = getAgentColor(_colorKeyFor(a));
      var connected = (a.status || "online") !== "offline";
      var liveness =
        a.liveness || a.status || (connected ? "online" : "offline");
      /* Dead-state detection — heartbeat is fresh but the agent has
       * shown no reaction (no tool call, no recorded action) for
       * >3min. This catches the classic "silent death" where the
       * sidecar keeps heartbeating but the LLM process is gone.
       * ywatanabe 2026-04-19: "please implement dead color, red with
       * logics like 3 min no-reaction". */
      var toolSec =
        typeof _secondsSinceIso === "function"
          ? _secondsSinceIso(a.last_tool_at)
          : null;
      var actSec =
        typeof _secondsSinceIso === "function"
          ? _secondsSinceIso(a.last_action)
          : null;
      var noTool = toolSec == null || toolSec > 180;
      var noAct = actSec == null || actSec > 180;
      var isDead = connected && noTool && noAct;
      var wsColor = connected ? "#4ecdc4" : "#555";
      var fnColor = FN_COLORS[liveness] || "#555";
      if (isDead) fnColor = "#ef4444";
      var nameText =
        typeof hostedAgentName === "function"
          ? hostedAgentName(a)
          : cleanAgentName
            ? cleanAgentName(a.name)
            : a.name;
      /* Two small LEDs centered on the ring position, then the label to
       * the right. Gap between LEDs = 10px so they read as a pair, not
       * a single smear. */
      var LED_R = 4;
      var GAP = 5;
      var wsCx = p.x - (LED_R + GAP / 2);
      var fnCx = p.x + (LED_R + GAP / 2);
      var wsLed =
        '<circle cx="' +
        wsCx.toFixed(1) +
        '" cy="' +
        p.y.toFixed(1) +
        '" r="' +
        LED_R +
        '" fill="' +
        wsColor +
        '" stroke="#0a0a0a" stroke-width="0.5"><title>WebSocket: ' +
        (connected ? "connected" : "disconnected") +
        "</title></circle>";
      var fnLed =
        '<circle cx="' +
        fnCx.toFixed(1) +
        '" cy="' +
        p.y.toFixed(1) +
        '" r="' +
        LED_R +
        '" fill="' +
        fnColor +
        '" stroke="#0a0a0a" stroke-width="0.5"><title>Liveness: ' +
        escapeHtml(liveness) +
        "</title></circle>";
      var pinMark = a.pinned
        ? '<text class="topo-label-pin" x="' +
          (p.x + LED_R + GAP / 2 + 8).toFixed(1) +
          '" y="' +
          (p.y + 4).toFixed(1) +
          '" fill="#fbbf24" font-size="11">\uD83D\uDCCC</text>'
        : "";
      var nameX = p.x + LED_R + GAP / 2 + (a.pinned ? 22 : 8);
      var selCls = _topoSelected[a.name] ? " topo-agent-selected" : "";
      var deadCls = isDead ? " topo-agent-dead" : "";
      /* Button-like badge background so the agent reads as clickable.
       * Approx width from the rendered text + LEDs + optional pin. ch
       * width ≈ 6.5px at 11px monospace. ywatanabe 2026-04-19:
       * "agent nodes should be easily clickable, make them button-like
       * object would be better (surround them by small border, like a
       * bit of badge)" */
      /* Robot glyph prefix — agent identity icon, parallel to the human
       * node's 👤. Sits just inside the left edge of the pill with
       * ample gap before the two LEDs so the emoji doesn't overlap the
       * WebSocket indicator. ywatanabe 2026-04-19: "add icon to agents
       * with robotic one as well" / "add margins to icons and
       * indicators now overlapping". */
      var agentIconX = p.x - LED_R - GAP / 2 - 28;
      var badgeLeft = agentIconX - 14;
      var textW = Math.max(40, nameText.length * 6.5);
      var badgeRight = nameX + textW + 6;
      var badgeWidth = badgeRight - badgeLeft;
      var badgeY = p.y - 11;
      var badgeH = 22;
      var bg =
        '<rect class="topo-agent-bg" x="' +
        badgeLeft.toFixed(1) +
        '" y="' +
        badgeY.toFixed(1) +
        '" width="' +
        badgeWidth.toFixed(1) +
        '" height="' +
        badgeH +
        '" rx="11" ry="11"/>';
      /* y=p.y (same as LED cy) + dominant-baseline:middle (CSS) so
       * the glyph center aligns with the LEDs and the text baseline.
       * ywatanabe 2026-04-19: "icons must have aligned in vertical
       * axis with text and indicators". */
      var agentGlyph =
        '<text class="topo-agent-glyph" x="' +
        agentIconX.toFixed(1) +
        '" y="' +
        p.y.toFixed(1) +
        '" font-size="12" dominant-baseline="central" text-anchor="middle">\uD83E\uDD16</text>';
      return (
        '<g class="topo-node topo-agent' +
        selCls +
        deadCls +
        '" data-agent="' +
        escapeHtml(a.name) +
        '">' +
        bg +
        agentGlyph +
        wsLed +
        fnLed +
        pinMark +
        '<text class="topo-label topo-label-agent" x="' +
        nameX.toFixed(1) +
        '" y="' +
        (p.y + 4).toFixed(1) +
        '" fill="' +
        color +
        '">' +
        escapeHtml(nameText) +
        "</text>" +
        "</g>"
      );
    })
    .join("");

  /* Human node — rendered after agents so it layers on top. Gold
   * pill with a 👤 glyph prefix; wired through the same data-agent
   * hook so the packet animator's sender lookup works unchanged. */
  var humanSvg = "";
  if (humanName && agentPos[humanName]) {
    var hp = agentPos[humanName];
    var hLabel = humanName;
    var hTextW = Math.max(40, hLabel.length * 6.5);
    var hBadgeLeft = hp.x - 18;
    var hBadgeWidth = 18 + 14 + hTextW + 6;
    humanSvg =
      '<g class="topo-node topo-agent topo-human" data-agent="' +
      escapeHtml(humanName) +
      '">' +
      '<rect class="topo-agent-bg topo-human-bg" x="' +
      hBadgeLeft.toFixed(1) +
      '" y="' +
      (hp.y - 11).toFixed(1) +
      '" width="' +
      hBadgeWidth.toFixed(1) +
      '" height="22" rx="11" ry="11"/>' +
      '<text class="topo-human-glyph" x="' +
      (hp.x - 10).toFixed(1) +
      '" y="' +
      (hp.y + 4).toFixed(1) +
      '" font-size="13">\uD83D\uDC64</text>' +
      '<text class="topo-label topo-label-agent" x="' +
      (hp.x + 6).toFixed(1) +
      '" y="' +
      (hp.y + 4).toFixed(1) +
      '" fill="#fbbf24">' +
      escapeHtml(hLabel) +
      "</text>" +
      "</g>";
  }

  /* Auto-fit viewBox on first render: compute bbox over every node
   * (agents + human + channel diamonds) with rough badge-width
   * estimates so long-name agents on the right/bottom aren't
   * clipped. Persisted zoom/pan overrides this once user has
   * interacted. ywatanabe 2026-04-19: "by default the size of the
   * graph must be maximized to include all elements". */
  var vb;
  if (_topoViewBox) {
    vb = _topoViewBox;
  } else {
    var bMinX = Infinity,
      bMinY = Infinity,
      bMaxX = -Infinity,
      bMaxY = -Infinity;
    visible.forEach(function (a) {
      var p = agentPos[a.name];
      if (!p) return;
      var nm = a.name || "";
      var w = Math.max(40, nm.length * 6.5) + 60; /* badge + glyph + LEDs */
      bMinX = Math.min(bMinX, p.x - 34);
      bMaxX = Math.max(bMaxX, p.x + w);
      bMinY = Math.min(bMinY, p.y - 14);
      bMaxY = Math.max(bMaxY, p.y + 14);
    });
    if (humanName && agentPos[humanName]) {
      var hp2 = agentPos[humanName];
      var hw = Math.max(40, humanName.length * 6.5) + 40;
      bMinX = Math.min(bMinX, hp2.x - 20);
      bMaxX = Math.max(bMaxX, hp2.x + hw);
      bMinY = Math.min(bMinY, hp2.y - 14);
      bMaxY = Math.max(bMaxY, hp2.y + 14);
    }
    channels.forEach(function (c) {
      var p = chPos[c];
      if (!p) return;
      var r = 22; /* max diamond radius */
      bMinX = Math.min(bMinX, p.x - r - (c.length * 6.5) / 2);
      bMaxX = Math.max(bMaxX, p.x + r + (c.length * 6.5) / 2);
      bMinY = Math.min(bMinY, p.y - r - 16);
      bMaxY = Math.max(bMaxY, p.y + r + 6);
    });
    if (isFinite(bMinX)) {
      var pad2 = 24;
      var vbW = bMaxX - bMinX + pad2 * 2;
      var vbH = bMaxY - bMinY + pad2 * 2;
      vb = { x: bMinX - pad2, y: bMinY - pad2, w: vbW, h: vbH };
    } else {
      vb = { x: 0, y: 0, w: W, h: H };
    }
  }
  /* <defs> carries two permission-direction markers. refX is placed
   * so the arrow tip sits just off the line end — otherwise it would
   * overlap the LED/diamond node. markerUnits=userSpaceOnUse so the
   * triangle scales with viewBox zoom (vanishes gracefully when the
   * user zooms out to survey the whole graph). */
  var markerDefs =
    "<defs>" +
    '<marker id="topo-arrow-end" viewBox="0 0 10 10" refX="9" refY="5"' +
    ' markerWidth="6" markerHeight="6" orient="auto-start-reverse"' +
    ' markerUnits="userSpaceOnUse">' +
    '<path d="M0,0 L10,5 L0,10 z" fill="#4ecdc4" class="topo-arrow-head"/>' +
    "</marker>" +
    '<marker id="topo-arrow-start" viewBox="0 0 10 10" refX="9" refY="5"' +
    ' markerWidth="6" markerHeight="6" orient="auto-start-reverse"' +
    ' markerUnits="userSpaceOnUse">' +
    '<path d="M0,0 L10,5 L0,10 z" fill="#4ecdc4" class="topo-arrow-head"/>' +
    "</marker>" +
    "</defs>";
  var svg =
    '<svg class="topo-svg" width="' +
    W +
    '" height="' +
    H +
    '" viewBox="' +
    vb.x.toFixed(1) +
    " " +
    vb.y.toFixed(1) +
    " " +
    vb.w.toFixed(1) +
    " " +
    vb.h.toFixed(1) +
    '" xmlns="http://www.w3.org/2000/svg">' +
    markerDefs +
    '<g class="topo-edges">' +
    edgesSvg +
    "</g>" +
    '<g class="topo-channels">' +
    chSvg +
    "</g>" +
    '<g class="topo-agents">' +
    agentSvg +
    humanSvg +
    "</g>" +
    '<rect class="topo-zoombox" x="0" y="0" width="0" height="0"' +
    ' fill="rgba(78,205,196,0.1)" stroke="#4ecdc4" stroke-width="1"' +
    ' stroke-dasharray="4 4" style="display:none;pointer-events:none"/>' +
    '<rect class="topo-lasso" x="0" y="0" width="0" height="0"' +
    ' fill="rgba(251,191,36,0.12)" stroke="#fbbf24" stroke-width="1"' +
    ' stroke-dasharray="3 3" style="display:none;pointer-events:none"/>' +
    "</svg>";

  var detailBox = "";
  if (_overviewExpanded) {
    detailBox =
      '<div class="activity-inline-detail" data-detail-for="' +
      escapeHtml(_overviewExpanded) +
      '"><p class="empty-notice">Loading detail…</p></div>';
  }
  var hint =
    '<div class="topo-hint">drag = rectangle zoom · shift+drag = pan · ctrl+drag = lasso · shift+click agent = multi-select · wheel = zoom · esc = back · 0 = reset · dbl-click channel = post</div>';
  /* Floating action bar — visible only when ≥2 agents are selected.
   * Markup always rendered so the same event-delegation wiring works;
   * visibility toggled via a CSS class. */
  var selNames = _topoSelectedNames();
  var barCls =
    "topo-actionbar" + (selNames.length >= 2 ? " topo-actionbar-show" : "");
  var actionBar =
    '<div class="' +
    barCls +
    '" role="toolbar">' +
    '<span class="topo-actionbar-count">' +
    selNames.length +
    " selected</span>" +
    '<button type="button" class="topo-actionbar-btn" data-topo-action="post">post to selected agents</button>' +
    '<button type="button" class="topo-actionbar-btn topo-actionbar-btn-ghost" data-topo-action="clear">clear</button>' +
    "</div>";
  var ctrls =
    '<div class="topo-ctrls">' +
    '<button type="button" class="topo-ctrl-btn" data-topo-ctrl="back" title="Previous zoom (Escape)">↶</button>' +
    '<button type="button" class="topo-ctrl-btn" data-topo-ctrl="forward" title="Next zoom (redo)">↷</button>' +
    '<button type="button" class="topo-ctrl-btn" data-topo-ctrl="minus" title="Zoom out (−)">−</button>' +
    '<button type="button" class="topo-ctrl-btn" data-topo-ctrl="reset" title="Reset zoom (0)">0</button>' +
    '<button type="button" class="topo-ctrl-btn" data-topo-ctrl="plus" title="Zoom in (+)">+</button>' +
    "</div>";
  /* Left-side pool — all agents and all channels as chips so the user
   * can see the full universe at a glance even when the canvas is
   * zoomed / cluttered. ywatanabe 2026-04-19: "place channels pool;
   * agents pool in the left side" / "so immediately create pool for
   * agents and channels!!!!". Click a chip → scroll its node into
   * view by re-centering the viewBox on it. */
  var poolAgentsHtml = visible
    .slice()
    .sort(function (a, b) {
      return (a.name || "").localeCompare(b.name || "");
    })
    .map(function (a) {
      var selCls = _topoPoolSelection.agents[a.name]
        ? " topo-pool-chip-selected"
        : "";
      return (
        '<div class="topo-pool-chip topo-pool-chip-agent' +
        selCls +
        '" data-agent="' +
        escapeHtml(a.name) +
        '" title="' +
        escapeHtml(a.name) +
        '"><span class="topo-pool-chip-icon">\uD83E\uDD16</span>' +
        escapeHtml(a.name) +
        "</div>"
      );
    })
    .join("");
  var poolChSet = {};
  channels.forEach(function (c) {
    poolChSet[c] = true;
  });
  Object.keys(window._channelPrefs || {}).forEach(function (c) {
    if (c && c.charAt(0) === "#") poolChSet[c] = true;
  });
  var poolChannelsHtml = Object.keys(poolChSet)
    .sort()
    .map(function (c) {
      var selCls = _topoPoolSelection.channels[c]
        ? " topo-pool-chip-selected"
        : "";
      return (
        '<div class="topo-pool-chip topo-pool-chip-channel' +
        selCls +
        '" data-channel="' +
        escapeHtml(c) +
        '" title="' +
        escapeHtml(c) +
        '">' +
        escapeHtml(c) +
        "</div>"
      );
    })
    .join("");
  var pool =
    '<div class="topo-pool">' +
    '<div class="topo-pool-section"><div class="topo-pool-title">Agents</div>' +
    poolAgentsHtml +
    "</div>" +
    '<div class="topo-pool-section"><div class="topo-pool-title">Channels</div>' +
    poolChannelsHtml +
    "</div>" +
    "</div>";
  grid.innerHTML =
    '<div class="topo-wrap">' +
    hint +
    ctrls +
    pool +
    svg +
    actionBar +
    "</div>" +
    detailBox;

  /* Delegated click: agent node → toggle expand. Bound ONCE on the
   * grid (the delegation helper guards with _overviewGridWired). We
   * extend its reach here because the grid rewrites its innerHTML on
   * every heartbeat and per-element listeners would be lost. */
  _wireOverviewGridDelegation(grid);
  _wireTopoZoomPan(grid, W, H);

  if (_overviewExpanded) {
    var agent = (window.__lastAgents || []).find(function (x) {
      return x.name === _overviewExpanded;
    });
    var inlineBox = grid.querySelector(
      '.activity-inline-detail[data-detail-for="' +
        String(_overviewExpanded).replace(/"/g, '\\"') +
        '"]',
    );
    if (agent && inlineBox) {
      _renderActivityAgentDetail(agent, inlineBox);
      _fetchActivityDetail(agent.name);
    }
  }
}

/* Overview list/tile renderer. One-line rows (or compact tiles) for
 * every agent passing the visibility rule. Click a row → inline expand
 * (single at a time). Expand is toggled via _overviewExpanded state.
 *
 * Each row carries THREE indicators so connection, heartbeat-age, and
 * LLM-level activity are all visible at a glance without opening the
 * detail panel:
 *
 *   WS LED       — WebSocket functional connection (status online/offline)
 *   Functional LED — heartbeat-age liveness (online/idle/stale/offline)
 *   State chip   — synthesized pane+tool state: running/idle/selecting
 *
 * Visibility rule (functional, NOT duration-based):
 *   status==="online" (WS connected)  → always shown (online/idle/stale)
 *   status==="offline" + pinned       → shown as ghost (dimmed)
 *   status==="offline" + unpinned     → hidden
 */
function _renderActivityCards(agents, grid) {
  var summary = document.getElementById("activity-summary");
  var all = agents || [];
  var counts = { online: 0, idle: 0, stale: 0, offline: 0 };
  all.forEach(function (a) {
    var l = a.liveness || a.status || "online";
    if (counts[l] != null) counts[l]++;
  });
  if (summary) {
    summary.innerHTML =
      '<span class="activity-pill activity-pill-online" title="connected &amp; active">' +
      '<span class="activity-pill-dot"></span>' +
      counts.online +
      " active</span>" +
      '<span class="activity-pill activity-pill-idle" title="connected, quiet 2–10 min">' +
      '<span class="activity-pill-dot"></span>' +
      counts.idle +
      " idle</span>" +
      '<span class="activity-pill activity-pill-stale" title="connected, quiet &gt;10 min — probably stuck">' +
      '<span class="activity-pill-dot"></span>' +
      counts.stale +
      " stale</span>" +
      '<span class="activity-pill activity-pill-offline" title="not connected">' +
      '<span class="activity-pill-dot"></span>' +
      counts.offline +
      " offline</span>";
  }

  var visible = all.filter(function (a) {
    var connected = (a.status || "online") !== "offline";
    return connected || !!a.pinned;
  });

  if (!visible.length) {
    grid.innerHTML = '<p class="empty-notice">No agents connected.</p>';
    return;
  }

  if (_overviewView === "topology") {
    _renderActivityTopology(visible, grid);
    return;
  }

  var LIVENESS_HINTS = {
    online: "connected & active — heartbeat <2 min",
    idle: "connected, quiet 2–10 min",
    stale: "connected, quiet >10 min — probably stuck",
    offline: "not connected",
  };

  grid.innerHTML = visible
    .map(function (a) {
      var rawName = a.name || "";
      var liveness = a.liveness || a.status || "online";
      var connected = (a.status || "online") !== "offline";
      var ghostClass = !connected && a.pinned ? " activity-card-ghost" : "";
      var idleStr = _formatIdle(a.idle_seconds);
      var color = getAgentColor(_colorKeyFor(a));
      var channels = Array.isArray(a.channels) ? a.channels : [];
      var channelsStr = channels
        .filter(function (c) {
          return c && c.indexOf("dm:") !== 0;
        })
        .join(" ");
      var name = escapeHtml(
        typeof hostedAgentName === "function"
          ? hostedAgentName(a)
          : cleanAgentName(rawName),
      );
      var pinOn = a.pinned ? " activity-pin-on" : "";
      var pinTitle = a.pinned
        ? "Unpin (will hide when offline)"
        : "Pin (keeps as ghost when offline, floats to top)";
      var livenessHint = LIVENESS_HINTS[liveness] || liveness;
      var wsHint = connected ? "WebSocket connected" : "WebSocket disconnected";
      var state = _computeAgentState(a);
      var stateLabel = state.toUpperCase();
      var stateHint =
        {
          running: "LLM fired a tool within the last 30s",
          idle: "connected, no recent tool calls",
          selecting: "agent is blocked on a choice or needs attention",
          offline: "not connected",
        }[state] || state;
      var ageStr = idleStr ? idleStr : "";
      var row =
        '<div class="activity-card activity-' +
        liveness +
        ghostClass +
        '" data-agent="' +
        escapeHtml(rawName) +
        '" data-machine="' +
        escapeHtml(a.machine || "") +
        '">' +
        '<button type="button" class="activity-pin-btn' +
        pinOn +
        '" data-pin-name="' +
        escapeHtml(rawName) +
        '" data-pin-next="' +
        (a.pinned ? "false" : "true") +
        '" title="' +
        escapeHtml(pinTitle) +
        '">\uD83D\uDCCC</button>' +
        '<span class="activity-led activity-led-ws activity-led-ws-' +
        (connected ? "on" : "off") +
        '" title="' +
        escapeHtml(wsHint) +
        '"></span>' +
        '<span class="activity-led activity-led-fn activity-led-fn-' +
        liveness +
        '" title="' +
        escapeHtml(livenessHint) +
        '"></span>' +
        '<span class="activity-state activity-state-' +
        state +
        '" title="' +
        escapeHtml(stateHint) +
        '">' +
        escapeHtml(stateLabel) +
        "</span>" +
        '<span class="activity-name" style="color:' +
        color +
        '">' +
        name +
        "</span>" +
        '<span class="activity-channels" title="' +
        escapeHtml(channelsStr || "no channels") +
        '">' +
        escapeHtml(channelsStr) +
        "</span>" +
        (ageStr
          ? '<span class="activity-age" title="' +
            escapeHtml(livenessHint) +
            '">' +
            escapeHtml(ageStr) +
            "</span>"
          : "") +
        "</div>";
      if (_overviewExpanded === rawName) {
        row +=
          '<div class="activity-inline-detail" data-detail-for="' +
          escapeHtml(rawName) +
          '"><p class="empty-notice">Loading detail…</p></div>';
      }
      return row;
    })
    .join("");

  if (typeof runFilter === "function") runFilter();

  /* Single delegated click listener on the grid — bound ONCE, survives
   * innerHTML rewrites (the grid element itself is never replaced).
   * Per-element listeners were silently lost between heartbeat re-
   * renders, causing the pin button to become unclickable after a poll
   * tick (ywatanabe 2026-04-19). */
  _wireOverviewGridDelegation(grid);

  if (_overviewExpanded) {
    var agent = all.find(function (a) {
      return a.name === _overviewExpanded;
    });
    var inlineBox = grid.querySelector(
      '.activity-inline-detail[data-detail-for="' +
        String(_overviewExpanded).replace(/"/g, '\\"') +
        '"]',
    );
    if (agent && inlineBox) {
      _renderActivityAgentDetail(agent, inlineBox);
      _fetchActivityDetail(agent.name);
    }
  }
}

/* Apply layout class (list vs tiled vs topology) to the overview grid.
 * The three modes are mutually exclusive CSS scopes — each adds one
 * class and the renderer dispatches on _overviewView internally. */
function _applyOverviewViewClass(grid) {
  if (!grid) return;
  grid.classList.remove(
    "activity-view-list",
    "activity-view-tiled",
    "activity-view-topology",
    "activity-grid-detail",
  );
  var cls = "activity-view-list";
  if (_overviewView === "tiled") cls = "activity-view-tiled";
  else if (_overviewView === "topology") cls = "activity-view-topology";
  grid.classList.add(cls);
}

var _overviewGridWired = false;
/* Topology click-counter: collects successive clicks on the same agent
 * node within CLICK_WINDOW_MS and dispatches a single action (1/2/3-
 * click). Double-click native event is also wired below as a fallback
 * for legacy browsers — the guard re-uses the same counter. */
var _topoClickState = null; /* {kind, name, count, timer, x, y} */
var TOPO_CLICK_WINDOW_MS = 350;
function _topoFlushClick() {
  if (!_topoClickState) return;
  var s = _topoClickState;
  _topoClickState = null;
  if (!s.name) return;
  if (s.kind === "channel") {
    /* Channel multi-click:
     *   2 = open inline compose popup
     *   3 = jump to the Chat tab focused on this channel
     *       (ywatanabe 2026-04-19: "triple click a channel → show in
     *       Chat channel"). */
    if (s.count >= 3) {
      if (typeof setCurrentChannel === "function") setCurrentChannel(s.name);
      if (typeof loadChannelHistory === "function") loadChannelHistory(s.name);
      var chatBtn = document.querySelector('[data-tab="chat"]');
      if (chatBtn) chatBtn.click();
    } else if (s.count === 2) {
      _topoOpenChannelCompose(s.name, s.x || 0, s.y || 0);
    }
    /* count === 1 is a no-op (preserves rectangle-zoom path for
     * empty-area clicks — channels still mark a click as "handled" by
     * virtue of being a clickable node, but we don't want a single
     * click to trigger anything destructive). */
    return;
  }
  /* Default: agent multi-click. */
  if (s.count >= 3) {
    _overviewExpanded = _overviewExpanded === s.name ? null : s.name;
    if (typeof renderActivityTab === "function") renderActivityTab();
  } else if (s.count === 2) {
    var human =
      (typeof userName !== "undefined" && userName) ||
      window.__orochiUserName ||
      "human";
    var dmCh = "dm:agent:" + s.name + "|human:" + human;
    _topoOpenChannelCompose(dmCh, s.x || 0, s.y || 0);
  }
  /* count === 1 for agents is handled as drag-source on mousedown. */
}
function _topoBumpClick(name, clientX, clientY, kind) {
  var k = kind || "agent";
  if (
    _topoClickState &&
    _topoClickState.name === name &&
    _topoClickState.kind === k
  ) {
    _topoClickState.count += 1;
    _topoClickState.x = clientX;
    _topoClickState.y = clientY;
    clearTimeout(_topoClickState.timer);
  } else {
    if (_topoClickState) clearTimeout(_topoClickState.timer);
    _topoClickState = {
      kind: k,
      name: name,
      count: 1,
      timer: 0,
      x: clientX,
      y: clientY,
    };
  }
  _topoClickState.timer = setTimeout(_topoFlushClick, TOPO_CLICK_WINDOW_MS);
}

/* Open (or create-and-open) the DM channel between the signed-in human
 * and the given agent. Channel name mirrors the backend convention
 *   dm:agent:<agent>|human:<user>
 * (see hub/views/api.py::api_dms + _dm_canonical_name). We use POST
 * /api/dms/ to get-or-create because it runs full_clean() AND sets
 * kind=KIND_DM — the /api/channel-members/ path would create a bogus
 * KIND_GROUP row with a reserved dm: name AND would 403 for non-staff
 * users. Once the backend confirms the canonical name we switch the UI
 * (setCurrentChannel + loadChannelHistory + activate Chat tab). */
function _openAgentDm(agentName) {
  if (!agentName) return;
  var human =
    (typeof userName !== "undefined" && userName) ||
    window.__orochiUserName ||
    "human";
  var fallback = "dm:agent:" + agentName + "|human:" + human;
  function _switchTo(channel) {
    try {
      if (typeof setCurrentChannel === "function") setCurrentChannel(channel);
      if (typeof loadChannelHistory === "function") loadChannelHistory(channel);
      var chatTabBtn = document.querySelector('[data-tab="chat"]');
      if (chatTabBtn) chatTabBtn.click();
    } catch (_) {}
  }
  var csrf = typeof getCsrfToken === "function" ? getCsrfToken() : "";
  var url = typeof apiUrl === "function" ? apiUrl("/api/dms/") : "/api/dms/";
  try {
    fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrf,
      },
      body: JSON.stringify({ recipient: "agent:" + agentName }),
    })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (j) {
        /* POST /api/dms/ returns the canonical {name, ...} row. Fall
         * back to our constructed name if the response shape is
         * unexpected. */
        var ch =
          (j && (j.name || j.channel || (j.dm && j.dm.name))) || fallback;
        _switchTo(ch);
      })
      .catch(function () {
        /* Still switch — if the channel pre-exists (common: agents
         * register their DM on startup) the UI will load it even
         * though the create endpoint errored. */
        _switchTo(fallback);
      });
  } catch (_) {
    _switchTo(fallback);
  }
}

/* ── Drag-to-subscribe on the topology canvas ──
 *   mousedown on .topo-agent or .topo-channel starts a drag session.
 *   After a 4px threshold a ghost <text> follows the cursor.
 *   While dragging, hovered .topo-channel / .topo-agent nodes get
 *   .topo-drop-target. Release on a valid opposite-kind node calls the
 *   subscribe endpoint with the right permission; release elsewhere
 *   cancels silently.
 *
 *   Zoom/pan gestures (_wireTopoZoomPan) guard themselves with an early
 *   return when the mousedown target is an agent/channel, so the two
 *   handlers coexist without conflict. */
var _topoDragState = null;
function _topoClearDrop() {
  if (!_topoDragState) return;
  if (_topoDragState.lastDrop) {
    _topoDragState.lastDrop.classList.remove("topo-drop-target");
    _topoDragState.lastDrop = null;
  }
}
function _topoCleanupDrag() {
  if (!_topoDragState) return;
  _topoClearDrop();
  if (_topoDragState.ghost && _topoDragState.ghost.parentNode) {
    _topoDragState.ghost.parentNode.removeChild(_topoDragState.ghost);
  }
  _topoDragState = null;
}
/* Inline compose popup anchored near a clicked channel node. Opens on
 * double-click channel; replaces the old window.prompt() UX
 * (ywatanabe 2026-04-19: "this is too much; just show a simple one
 * near clicked point is enough"). Minimal by default: text input +
 * send button + expand chevron. When expanded, surfaces attach /
 * camera / sketch / voice buttons that delegate to the global
 * helpers already used by the Chat compose. Drag-drop files onto the
 * popup always works (collapsed or expanded). Keyboard: Enter sends,
 * Shift+Enter = newline, Esc closes. */
function _topoOpenChannelCompose(channel, clientX, clientY) {
  /* Kill any previous popup first. */
  var prev = document.getElementById("topo-channel-compose");
  if (prev && prev.parentNode) prev.parentNode.removeChild(prev);
  var pop = document.createElement("div");
  pop.id = "topo-channel-compose";
  pop.className = "topo-channel-compose";
  pop.setAttribute("data-channel", channel);
  pop.style.left = Math.max(8, clientX - 140) + "px";
  pop.style.top = Math.max(8, clientY + 12) + "px";
  /* Minimal popup: no header, no close button, no + button, no send
   * button. Just a textarea whose tooltip documents all the keyboard
   * shortcuts, plus a small ▾ chevron at the bottom-right corner that
   * reveals attach / camera / sketch / voice buttons. Enter sends, Esc
   * closes, outside click closes. ywatanabe 2026-04-19: "make the
   * modal minimal; no send button needed; no dm nor channel label
   * needed; no plus button needed; not x button needed; just add a
   * small chevron to the bottom to show other buttons; show tooltip
   * with keyboard shortcuts even when they are not expanded to use". */
  var tccShortcuts =
    "Enter — send\n" +
    "Shift+Enter — newline\n" +
    "Esc — close\n" +
    "Drop files to attach\n" +
    "Paste image/file to attach\n" +
    "Click ▾ for attach / camera / sketch / voice";
  pop.innerHTML =
    '<textarea class="tcc-input" rows="2" placeholder="message #' +
    escapeHtml(channel).replace(/^#/, "") +
    '" title="' +
    tccShortcuts.replace(/"/g, "&quot;") +
    '"></textarea>' +
    '<div class="tcc-extras" style="display:none">' +
    '<button type="button" class="tcc-x tcc-attach" title="Attach file (paste also works)">\uD83D\uDCCE</button>' +
    '<button type="button" class="tcc-x tcc-camera" title="Camera">\uD83D\uDCF7</button>' +
    '<button type="button" class="tcc-x tcc-sketch" title="Sketch">\u270F\uFE0F</button>' +
    '<button type="button" class="tcc-x tcc-voice" title="Voice input">\uD83C\uDFA4</button>' +
    "</div>" +
    '<button type="button" class="tcc-expand" title="' +
    tccShortcuts.replace(/"/g, "&quot;") +
    '" aria-label="More options">\u25BE</button>';
  document.body.appendChild(pop);
  var input = pop.querySelector(".tcc-input");
  var extras = pop.querySelector(".tcc-extras");
  var expandBtn = pop.querySelector(".tcc-expand");
  setTimeout(function () {
    if (input) input.focus();
  }, 10);

  function close() {
    if (pop.parentNode) pop.parentNode.removeChild(pop);
    document.removeEventListener("mousedown", outsideClick, true);
  }
  function outsideClick(ev) {
    if (!pop.contains(ev.target)) close();
  }
  setTimeout(function () {
    document.addEventListener("mousedown", outsideClick, true);
  }, 50);

  function send() {
    var text = (input.value || "").trim();
    if (!text) return;
    var payload = { channel: channel, content: text };
    if (
      typeof wsConnected !== "undefined" &&
      wsConnected &&
      typeof ws !== "undefined" &&
      ws &&
      ws.readyState === WebSocket.OPEN
    ) {
      ws.send(JSON.stringify({ type: "message", payload: payload }));
    } else if (typeof sendOrochiMessage === "function") {
      sendOrochiMessage({
        type: "message",
        sender:
          typeof userName !== "undefined" && userName ? userName : "human",
        payload: payload,
      });
    }
    close();
  }
  input.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      send();
    } else if (ev.key === "Escape") {
      ev.preventDefault();
      close();
    }
  });
  /* Paste support — images / files / long text. Native paste of plain
   * text keeps the default behavior (lands in the textarea). If the
   * clipboard carries a file/image, route to the Chat composer (the
   * canonical paste-to-attach pipeline lives there) and re-dispatch
   * the paste event so the upload.js handler does the work.
   * ywatanabe 2026-04-19: "small input modal should support pasting". */
  input.addEventListener("paste", function (ev) {
    var cd =
      ev.clipboardData || (ev.originalEvent && ev.originalEvent.clipboardData);
    if (!cd) return;
    var hasFile = false;
    if (cd.files && cd.files.length) hasFile = true;
    else if (cd.items) {
      for (var i = 0; i < cd.items.length; i++) {
        var it = cd.items[i];
        if (it && it.type && it.type.indexOf("image/") === 0) {
          hasFile = true;
          break;
        }
      }
    }
    /* Long text still attaches as a file via upload.js's
     * _pastedTextShouldAttach heuristic — route for that case too. */
    var text = "";
    try {
      text = cd.getData("text/plain") || "";
    } catch (_) {}
    var isLong = text.length > 1000;
    if (hasFile || isLong) {
      ev.preventDefault();
      ev.stopPropagation();
      close();
      _routeToChat();
      setTimeout(function () {
        var msgInput = document.getElementById("msg-input");
        if (!msgInput) return;
        msgInput.focus();
        /* Synthesize a paste event on msg-input so upload.js's
         * handleClipboardPaste processes the same clipboard payload. */
        try {
          var newEv = new ClipboardEvent("paste", {
            clipboardData: cd,
            bubbles: true,
            cancelable: true,
          });
          msgInput.dispatchEvent(newEv);
        } catch (_) {
          /* Some browsers don't allow constructing ClipboardEvent with
           * populated data — let the user paste again in that case. */
        }
      }, 50);
    }
  });
  expandBtn.addEventListener("click", function () {
    var on = extras.style.display === "none";
    extras.style.display = on ? "" : "none";
    expandBtn.textContent = on ? "\u25B4" : "\u25BE";
  });
  /* Delegate extras — pop the channel into currentChannel so existing
   * global helpers target the right place, then invoke them. Fallback
   * to focusing the main composer for modes that don't have a headless
   * API surface. */
  function _routeToChat() {
    if (typeof setCurrentChannel === "function") setCurrentChannel(channel);
    if (typeof loadChannelHistory === "function") loadChannelHistory(channel);
    var tabBtn = document.querySelector('[data-tab="chat"]');
    if (tabBtn) tabBtn.click();
    close();
  }
  pop.querySelector(".tcc-attach").addEventListener("click", function () {
    _routeToChat();
    if (typeof openAttachmentPicker === "function") openAttachmentPicker();
  });
  pop.querySelector(".tcc-camera").addEventListener("click", function () {
    _routeToChat();
    if (typeof openCameraCapture === "function") openCameraCapture();
  });
  pop.querySelector(".tcc-sketch").addEventListener("click", function () {
    _routeToChat();
    if (typeof openSketchPanel === "function") openSketchPanel();
  });
  pop.querySelector(".tcc-voice").addEventListener("click", function () {
    _routeToChat();
    if (typeof startVoiceInput === "function") startVoiceInput();
  });
  /* Drop files onto popup → route to Chat with attachments primed. */
  pop.addEventListener("dragover", function (ev) {
    ev.preventDefault();
    pop.classList.add("tcc-drag-over");
  });
  pop.addEventListener("dragleave", function () {
    pop.classList.remove("tcc-drag-over");
  });
  pop.addEventListener("drop", function (ev) {
    ev.preventDefault();
    pop.classList.remove("tcc-drag-over");
    var files = ev.dataTransfer && ev.dataTransfer.files;
    if (files && files.length && typeof handleFileUpload === "function") {
      _routeToChat();
      for (var i = 0; i < files.length; i++) handleFileUpload(files[i]);
    }
  });
}

function _topoSpawnGhost(svg, text, x, y) {
  var ns = "http://www.w3.org/2000/svg";
  var t = document.createElementNS(ns, "text");
  t.setAttribute("class", "topo-drag-ghost");
  t.setAttribute("x", x);
  t.setAttribute("y", y);
  t.setAttribute("pointer-events", "none");
  t.textContent = text;
  svg.appendChild(t);
  return t;
}
function _topoShowSubscribeToast(agent, channel, perm) {
  if (typeof _showMiniToast === "function") {
    var verb = perm === "read-write" ? "read-write" : "read-only";
    _showMiniToast(
      "Added " + agent + " to " + channel + " (" + verb + ")",
      "ok",
    );
  }
}

/* Edge-click unsubscribe: clicking (or right-clicking) a topology edge
 * offers to remove that agent's subscription to the channel.
 * ywatanabe 2026-04-19: "edges (lines) must be selectable to
 * unsubscribe".
 *
 * Optimistic: drop the channel from window.__lastAgents[i].channels and
 * from _topoStickyEdges so the edge disappears immediately. The DELETE
 * request to /api/channel-members/ then confirms with the backend.
 * _agentSubscribe's throttled fetchAgents will reconcile any drift. */
var _topoEdgeMenuEl = null;
function _topoCloseEdgeMenu() {
  if (_topoEdgeMenuEl && _topoEdgeMenuEl.parentNode) {
    _topoEdgeMenuEl.parentNode.removeChild(_topoEdgeMenuEl);
  }
  _topoEdgeMenuEl = null;
  document.removeEventListener("click", _topoEdgeMenuOutsideClick, true);
  document.removeEventListener("keydown", _topoEdgeMenuKeyHandler, true);
}
function _topoEdgeMenuOutsideClick(ev) {
  if (!_topoEdgeMenuEl) return;
  if (_topoEdgeMenuEl.contains(ev.target)) return;
  _topoCloseEdgeMenu();
}
function _topoEdgeMenuKeyHandler(ev) {
  if (ev.key === "Escape") {
    ev.stopPropagation();
    _topoCloseEdgeMenu();
  }
}
function _topoDoEdgeUnsubscribe(agent, channel) {
  /* Optimistic removal: drop from __lastAgents + sticky set before
   * firing the DELETE so the edge vanishes on the next render. */
  var live = window.__lastAgents || [];
  for (var i = 0; i < live.length; i++) {
    if (live[i].name === agent) {
      var chs = Array.isArray(live[i].channels) ? live[i].channels : [];
      live[i].channels = chs.filter(function (c) {
        return c !== channel;
      });
      break;
    }
  }
  if (typeof _topoStickyKey === "function") {
    delete _topoStickyEdges[_topoStickyKey(agent, channel)];
  }
  _topoLastSig = "";
  if (typeof renderActivityTab === "function") renderActivityTab();
  if (typeof _invalidateTopoPerms === "function") _invalidateTopoPerms();

  /* Fire DELETE /api/channel-members/ directly so we control the toast
   * wording exactly (app.js::_toggleAgentChannelSubscription emits its
   * own "Unsubscribed ← channel" toast; we want "from" here). */
  if (typeof _showMiniToast === "function") {
    _showMiniToast("Unsubscribed " + agent + " from " + channel, "ok");
  }
  if (typeof _agentDjangoUsername !== "function") return;
  var username = _agentDjangoUsername(agent);
  if (!username) return;
  var url =
    typeof apiUrl === "function"
      ? apiUrl("/api/channel-members/")
      : "/api/channel-members/";
  fetch(url, {
    method: "DELETE",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": typeof getCsrfToken === "function" ? getCsrfToken() : "",
    },
    body: JSON.stringify({ channel: channel, username: username }),
  })
    .then(function (res) {
      if (!res.ok) {
        return res
          .json()
          .catch(function () {
            return { error: res.status };
          })
          .then(function (j) {
            var msg =
              (j && j.error) || "HTTP " + res.status + " — check permissions";
            if (typeof _showMiniToast === "function") {
              _showMiniToast("Unsubscribe failed: " + msg, "err");
            }
          });
      }
      /* Reconcile with server state so a subsequent subscribe sees the
       * authoritative channel list, not our optimistic mutation. */
      if (typeof fetchAgentsThrottled === "function") fetchAgentsThrottled();
      else if (typeof fetchAgents === "function") fetchAgents();
    })
    .catch(function (_) {});
}
function _topoShowEdgeMenu(agent, channel, clientX, clientY) {
  _topoCloseEdgeMenu();
  if (!agent || !channel) return;
  var menu = document.createElement("div");
  menu.className = "topo-edge-menu";
  menu.setAttribute("role", "menu");
  /* Position near click; clamp inside viewport so it doesn't overflow. */
  var x = clientX;
  var y = clientY;
  menu.style.position = "fixed";
  menu.style.left = x + "px";
  menu.style.top = y + "px";
  menu.innerHTML =
    '<div class="topo-edge-menu-title">' +
    escapeHtml(agent) +
    " &rarr; " +
    escapeHtml(channel) +
    "</div>" +
    '<button type="button" class="topo-edge-menu-btn topo-edge-menu-btn-danger" data-topo-edge-action="unsubscribe">Unsubscribe ' +
    escapeHtml(agent) +
    " from " +
    escapeHtml(channel) +
    "</button>" +
    '<button type="button" class="topo-edge-menu-btn" data-topo-edge-action="cancel">Cancel</button>';
  document.body.appendChild(menu);
  /* Clamp inside viewport. */
  var mw = menu.offsetWidth;
  var mh = menu.offsetHeight;
  var vw = window.innerWidth || document.documentElement.clientWidth;
  var vh = window.innerHeight || document.documentElement.clientHeight;
  if (x + mw + 8 > vw) menu.style.left = Math.max(4, vw - mw - 8) + "px";
  if (y + mh + 8 > vh) menu.style.top = Math.max(4, vh - mh - 8) + "px";
  _topoEdgeMenuEl = menu;
  menu.addEventListener("click", function (ev) {
    var btn = ev.target.closest("[data-topo-edge-action]");
    if (!btn) return;
    var action = btn.getAttribute("data-topo-edge-action");
    ev.stopPropagation();
    if (action === "unsubscribe") {
      _topoDoEdgeUnsubscribe(agent, channel);
    }
    _topoCloseEdgeMenu();
  });
  /* Dismiss on outside click / Escape. Defer to next tick so the
   * current click that opened the menu doesn't immediately close it. */
  setTimeout(function () {
    document.addEventListener("click", _topoEdgeMenuOutsideClick, true);
    document.addEventListener("keydown", _topoEdgeMenuKeyHandler, true);
  }, 0);
}

function _wireOverviewGridDelegation(grid) {
  if (_overviewGridWired || !grid) return;
  grid.addEventListener("click", function (ev) {
    var pinBtn = ev.target.closest(".activity-pin-btn[data-pin-name]");
    if (pinBtn && grid.contains(pinBtn)) {
      ev.stopPropagation();
      var pname = pinBtn.getAttribute("data-pin-name");
      var nextPin = pinBtn.getAttribute("data-pin-next") === "true";
      var live = window.__lastAgents || [];
      for (var i = 0; i < live.length; i++) {
        if (live[i].name === pname) {
          live[i].pinned = nextPin;
          break;
        }
      }
      pinBtn.classList.toggle("activity-pin-on", nextPin);
      pinBtn.setAttribute("data-pin-next", nextPin ? "false" : "true");
      if (typeof togglePinAgent === "function") {
        togglePinAgent(pname, nextPin);
      } else {
        console.error(
          "togglePinAgent unavailable — pin click had no effect for",
          pname,
        );
      }
      return;
    }
    var card = ev.target.closest(".activity-card[data-agent]");
    if (card && grid.contains(card)) {
      /* ignore clicks that originate inside the inline-detail panel —
       * those should be handled by the detail's own widgets, not toggle
       * expand. */
      if (ev.target.closest(".activity-inline-detail")) return;
      var cname = card.getAttribute("data-agent");
      if (!cname) return;
      if (ev.shiftKey || ev.ctrlKey || ev.metaKey) {
        if (typeof addTag === "function") addTag("agent", cname);
        return;
      }
      _overviewExpanded = _overviewExpanded === cname ? null : cname;
      renderActivityTab();
      return;
    }
    /* Topology edge click → unsubscribe popover. Edges are bare <line>
     * elements inside <g class="topo-edges">; only agent→channel edges
     * carry .topo-edge (human→channel dashed guides are skipped so the
     * signed-in human can't "unsubscribe" themselves from a channel
     * they never explicitly joined). */
    var topoEdge = ev.target.closest(".topo-edges line.topo-edge");
    if (topoEdge && grid.contains(topoEdge)) {
      if (ev.shiftKey || ev.ctrlKey || ev.metaKey) return;
      var eAgent = topoEdge.getAttribute("data-agent");
      var eCh = topoEdge.getAttribute("data-channel");
      if (eAgent && eCh) {
        ev.preventDefault();
        ev.stopPropagation();
        _topoShowEdgeMenu(eAgent, eCh, ev.clientX, ev.clientY);
        return;
      }
    }
    /* Left-pool chip click: ctrl/meta = toggle membership in the pool
     * selection set; plain click = clear + select only this chip.
     * Drag-to-subscribe between chips is handled by the mousedown/
     * mouseup block further down. Suppress the click that follows a
     * just-completed drag so the drop doesn't also mutate selection. */
    var poolChip = ev.target.closest(".topo-pool-chip");
    if (poolChip && grid.contains(poolChip)) {
      if (_topoDragState && _topoDragState.suppressClick) {
        _topoDragState.suppressClick = false;
        ev.stopPropagation();
        return;
      }
      var pcKind = poolChip.classList.contains("topo-pool-chip-channel")
        ? "channel"
        : "agent";
      var pcName = poolChip.getAttribute(
        pcKind === "channel" ? "data-channel" : "data-agent",
      );
      if (!pcName) return;
      /* Plain click on a HIDDEN chip = un-hide (the pool is the
       * canonical "bring it back" affordance). ywatanabe 2026-04-19:
       * "once hidden channels cannot be shown for good" / "are there
       * no interface to show once hidden channels???". Ctrl/meta
       * still toggles selection so multi-select can include hidden. */
      var prefHidden =
        pcKind === "channel" && (window._channelPrefs || {})[pcName]
          ? !!(window._channelPrefs[pcName] || {}).is_hidden
          : false;
      var isHidden =
        (pcKind === "agent" && _topoHidden.agents[pcName]) ||
        (pcKind === "channel" && _topoHidden.channels[pcName]) ||
        prefHidden;
      if (isHidden && !(ev.ctrlKey || ev.metaKey)) {
        if (typeof _topoUnhide === "function") _topoUnhide(pcKind, pcName);
        if (prefHidden && typeof _setChannelPref === "function") {
          _setChannelPref(pcName, { is_hidden: false });
        }
        _topoLastSig = "";
        if (typeof renderActivityTab === "function") renderActivityTab();
        ev.stopPropagation();
        return;
      }
      if (ev.ctrlKey || ev.metaKey) {
        _topoPoolSelectToggle(pcKind, pcName);
      } else {
        _topoPoolSelectOnly(pcKind, pcName);
      }
      _topoPoolSelectionPaint(grid);
      ev.stopPropagation();
      return;
    }
    /* Topology view — agent node click dispatch. Modifiers take
     * precedence over the 1/2/3-click timer:
     *   shift+click          → toggle multi-select membership
     *   ctrl/meta+click      → addTag (routes to Ctrl+K global search)
     *   plain 1-click        → drag source (handled on mousedown; click is a no-op)
     *   plain 2-click        → open DM with that agent
     *   plain 3-click        → toggle inline detail expand
     * The click that immediately follows a successful drag-drop is
     * suppressed so the drop doesn't also trigger expand. */
    var topoAgent = ev.target.closest(".topo-agent[data-agent]");
    if (topoAgent && grid.contains(topoAgent)) {
      if (ev.target.closest(".activity-inline-detail")) return;
      var tname = topoAgent.getAttribute("data-agent");
      if (!tname) return;
      if (ev.shiftKey) {
        _topoSelectToggle(tname);
        _topoLastSig = "";
        renderActivityTab();
        return;
      }
      if (ev.ctrlKey || ev.metaKey) {
        if (typeof addTag === "function") addTag("agent", tname);
        return;
      }
      /* Suppress click dispatched immediately after a successful drop
       * (prevents accidental expand after drag-release). */
      if (_topoDragState && _topoDragState.suppressClick) {
        _topoDragState.suppressClick = false;
        return;
      }
      _topoBumpClick(tname, ev.clientX, ev.clientY, "agent");
    }
    /* Channel node click counter — 2 = inline compose popup,
     * 3 = jump to Chat tab on this channel. ywatanabe 2026-04-19
     * "triple click a channel → show in Chat channel". */
    var topoChannel = ev.target.closest(".topo-channel[data-channel]");
    if (topoChannel && grid.contains(topoChannel)) {
      if (ev.target.closest(".activity-inline-detail")) return;
      var chName = topoChannel.getAttribute("data-channel");
      if (!chName) return;
      _topoBumpClick(chName, ev.clientX, ev.clientY, "channel");
    }
    /* Topology action-bar buttons (post / clear). These live outside
     * the SVG but inside `grid`, so the delegation catches them here. */
    var abBtn = ev.target.closest(".topo-actionbar-btn[data-topo-action]");
    if (abBtn && grid.contains(abBtn)) {
      ev.stopPropagation();
      var action = abBtn.getAttribute("data-topo-action");
      if (action === "clear") {
        _topoSelectClear();
        _topoLastSig = "";
        renderActivityTab();
      } else if (action === "post") {
        _openTopoGroupCompose(_topoSelectedNames());
      }
      return;
    }
  });
  /* Native dblclick fallback — bumps the counter to 2 so the same
   * _topoFlushClick codepath opens the DM. Prevents the grid-level
   * dblclick handler (which resets zoom) from also firing when the
   * target is an agent node. */
  grid.addEventListener("dblclick", function (ev) {
    var topoAgent = ev.target.closest(".topo-agent[data-agent]");
    if (!topoAgent || !grid.contains(topoAgent)) return;
    var tname = topoAgent.getAttribute("data-agent");
    if (!tname) return;
    ev.stopPropagation();
    /* The two clicks that made up the dblclick already bumped the
     * counter via the click handler, so we don't need to bump again —
     * but if the counter was flushed (rare: very fast dblclick with
     * synthesized click events not firing twice), ensure count >= 2. */
    if (!_topoClickState || _topoClickState.name !== tname) {
      _openAgentDm(tname);
    } else if (_topoClickState.count < 2) {
      _topoClickState.count = 2;
    }
  });
  /* Drag-to-subscribe — mousedown on an agent OR channel node (canvas
   * or left-pool chip) starts a drag session. This coexists with
   * _wireTopoZoomPan because that handler short-circuits when the
   * target is .topo-agent/.topo-channel; pool chips live outside the
   * SVG so there's no zoom-pan conflict there. */
  grid.addEventListener("mousedown", function (ev) {
    if (ev.button !== 0) return;
    if (ev.shiftKey || ev.ctrlKey || ev.metaKey) return;
    /* Canvas SVG is still the ghost host (pool chips live in HTML, but
     * the ghost is an SVG <text> element, so we need the SVG handle
     * regardless of where the drag originated). */
    var svg = grid.querySelector(".topo-svg");
    var agentNode = ev.target.closest(".topo-agent[data-agent]");
    var channelNode = ev.target.closest(".topo-channel[data-channel]");
    var poolChip = ev.target.closest(".topo-pool-chip");
    var source = null;
    var kind = null;
    var name = null;
    if (agentNode || channelNode) {
      /* Require the canvas SVG context so zoom-pan doesn't fight us. */
      if (!ev.target.closest(".topo-svg")) return;
      source = "canvas";
      kind = agentNode ? "agent" : "channel";
      name = agentNode
        ? agentNode.getAttribute("data-agent")
        : channelNode.getAttribute("data-channel");
    } else if (poolChip) {
      source = "pool";
      kind = poolChip.classList.contains("topo-pool-chip-channel")
        ? "channel"
        : "agent";
      name = poolChip.getAttribute(
        kind === "channel" ? "data-channel" : "data-agent",
      );
    } else {
      return;
    }
    if (!name || !svg) return;
    /* If the pressed chip is part of the current pool selection, drag
     * the whole selection (multi-subscribe on drop). Otherwise drag
     * only this single name. Canvas-originated drags always drag just
     * the one node (the canvas selection is a separate affordance). */
    var items = [{ kind: kind, name: name }];
    if (source === "pool" && _topoPoolSelectionHas(kind, name)) {
      items = [];
      Object.keys(_topoPoolSelection.agents).forEach(function (n) {
        items.push({ kind: "agent", name: n });
      });
      Object.keys(_topoPoolSelection.channels).forEach(function (n) {
        items.push({ kind: "channel", name: n });
      });
    }
    _topoDragState = {
      svg: svg,
      source: source,
      kind: kind,
      name: name,
      items: items,
      startX: ev.clientX,
      startY: ev.clientY,
      ghost: null,
      lastDrop: null,
      moved: false,
      suppressClick: false,
    };
  });
  grid.addEventListener("mousemove", function (ev) {
    var s = _topoDragState;
    if (!s) return;
    var dx = ev.clientX - s.startX;
    var dy = ev.clientY - s.startY;
    if (!s.moved && dx * dx + dy * dy < 16) return; /* 4px threshold */
    s.moved = true;
    /* Spawn ghost once we cross the threshold. Multi-item drags show a
     * compact "N items" label; single-item drags keep the verbose
     * "→ subscribe <name>" style. Which kinds the bundle contains
     * determines the arrow direction. ywatanabe 2026-04-19: "when
     * an agent moved, it must be moved there simply no need for the
     * → subscribe ghost; they should subscribe only when destination
     * hits a channel" — handled downstream via drop-target validation,
     * not the ghost label. */
    if (!s.ghost) {
      var p0 = _topoSvgPoint(s.svg, ev.clientX, ev.clientY);
      var label;
      if (s.items && s.items.length > 1) {
        var nA = 0;
        var nC = 0;
        for (var k = 0; k < s.items.length; k++) {
          if (s.items[k].kind === "agent") nA++;
          else nC++;
        }
        var parts = [];
        if (nA) parts.push(nA + " agent" + (nA === 1 ? "" : "s"));
        if (nC) parts.push(nC + " channel" + (nC === 1 ? "" : "s"));
        label = "\u2192 " + parts.join(" + ");
      } else {
        label = s.name;
      }
      s.ghost = _topoSpawnGhost(s.svg, label, p0.x + 8, p0.y - 8);
    }
    var p = _topoSvgPoint(s.svg, ev.clientX, ev.clientY);
    s.ghost.setAttribute("x", (p.x + 8).toFixed(1));
    s.ghost.setAttribute("y", (p.y - 8).toFixed(1));
    /* Hover highlight. Valid target = opposite-kind node, either on
     * canvas (.topo-channel / .topo-agent) or in the pool (.topo-pool-
     * chip-channel / .topo-pool-chip-agent). Bundles of mixed kinds
     * accept both — whichever we hit first is valid because we'll
     * filter per-item on drop. */
    var haveAgent = false;
    var haveChannel = false;
    if (s.items && s.items.length) {
      for (var ii = 0; ii < s.items.length; ii++) {
        if (s.items[ii].kind === "agent") haveAgent = true;
        else haveChannel = true;
      }
    } else {
      haveAgent = s.kind === "agent";
      haveChannel = s.kind === "channel";
    }
    var target = null;
    var stack = document.elementsFromPoint
      ? document.elementsFromPoint(ev.clientX, ev.clientY)
      : [];
    for (var i = 0; i < stack.length; i++) {
      var el = stack[i];
      var chHit =
        el.closest &&
        (el.closest(".topo-channel[data-channel]") ||
          el.closest(".topo-pool-chip-channel[data-channel]"));
      var agHit =
        el.closest &&
        (el.closest(".topo-agent[data-agent]") ||
          el.closest(".topo-pool-chip-agent[data-agent]"));
      /* Don't self-target: the chip we started the drag on must not
       * count as a drop target. */
      if (agHit && s.source === "pool" && s.kind === "agent") {
        var agN = agHit.getAttribute("data-agent");
        if (s.items && s.items.length === 1 && agN === s.name) agHit = null;
      }
      if (chHit && s.source === "pool" && s.kind === "channel") {
        var chN = chHit.getAttribute("data-channel");
        if (s.items && s.items.length === 1 && chN === s.name) chHit = null;
      }
      if (haveAgent && chHit) {
        target = chHit;
        break;
      }
      if (haveChannel && agHit) {
        target = agHit;
        break;
      }
    }
    if (s.lastDrop !== target) {
      if (s.lastDrop) s.lastDrop.classList.remove("topo-drop-target");
      if (target) target.classList.add("topo-drop-target");
      s.lastDrop = target;
      /* Update ghost label to reflect intent: over a valid target we
       * show the subscribe/read arrow, off-target we show just the
       * name so the drag reads as repositioning. */
      if (s.ghost) {
        var tgtLabel = "";
        if (target && s.kind === "agent") {
          tgtLabel = " → " + (target.getAttribute("data-channel") || "");
        } else if (target && s.kind === "channel") {
          tgtLabel = " → " + (target.getAttribute("data-agent") || "");
        }
        s.ghost.textContent = s.name + tgtLabel;
      }
    }
  });
  grid.addEventListener("mouseup", function (ev) {
    var s = _topoDragState;
    if (!s) return;
    var target = s.lastDrop;
    if (s.moved && target) {
      /* Optimistic: mutate __lastAgents so the channel membership
       * renders into the topology on the very next re-render, before
       * the server round-trip completes. Backend-authoritative state
       * still arrives via fetchAgentsThrottled() called inside
       * _agentSubscribe. */
      function _optimisticAdd(agentName, channel) {
        var live = window.__lastAgents || [];
        for (var i = 0; i < live.length; i++) {
          if (live[i].name === agentName) {
            var chs = Array.isArray(live[i].channels)
              ? live[i].channels.slice()
              : [];
            if (chs.indexOf(channel) === -1) chs.push(channel);
            live[i].channels = chs;
            break;
          }
        }
      }
      /* Resolve the drop target. Prefer canvas node, fall back to pool
       * chip. Both carry data-agent / data-channel attributes. */
      var targetCh = target.getAttribute("data-channel");
      var targetAg = target.getAttribute("data-agent");
      /* Bundle subscribes: loop each source item against the target.
       * Agents-in-bundle + channel-target ⇒ subscribe each agent.
       * Channels-in-bundle + agent-target ⇒ subscribe target to each.
       * Mixed bundles handle both branches in one drop. */
      var items =
        s.items && s.items.length ? s.items : [{ kind: s.kind, name: s.name }];
      var subscribedAgentsOnCh = 0;
      var subscribedChsOnAg = 0;
      for (var ix = 0; ix < items.length; ix++) {
        var it = items[ix];
        if (it.kind === "agent" && targetCh) {
          if (typeof _agentSubscribe === "function") {
            _topoStickyEdges[_topoStickyKey(it.name, targetCh)] = true;
            _optimisticAdd(it.name, targetCh);
            _agentSubscribe(it.name, targetCh, "read-write");
            subscribedAgentsOnCh++;
          }
        } else if (it.kind === "channel" && targetAg) {
          if (typeof _agentSubscribe === "function") {
            _topoStickyEdges[_topoStickyKey(targetAg, it.name)] = true;
            _optimisticAdd(targetAg, it.name);
            _agentSubscribe(targetAg, it.name, "read-only");
            subscribedChsOnAg++;
          }
        }
      }
      if (subscribedAgentsOnCh + subscribedChsOnAg > 0) {
        if (subscribedAgentsOnCh === 1 && subscribedChsOnAg === 0) {
          /* Single-agent → single-channel: keep the existing toast. */
          _topoShowSubscribeToast(items[0].name, targetCh, "read-write");
        } else if (subscribedAgentsOnCh === 0 && subscribedChsOnAg === 1) {
          _topoShowSubscribeToast(targetAg, items[0].name, "read-only");
        } else {
          /* Bundle drop — summary toast per user spec. */
          if (typeof _showMiniToast === "function") {
            if (subscribedAgentsOnCh > 0) {
              _showMiniToast(
                "Subscribed " +
                  subscribedAgentsOnCh +
                  " agent" +
                  (subscribedAgentsOnCh === 1 ? "" : "s") +
                  " \u2192 " +
                  targetCh,
                "ok",
              );
            }
            if (subscribedChsOnAg > 0) {
              _showMiniToast(
                "Subscribed " +
                  targetAg +
                  " \u2192 " +
                  subscribedChsOnAg +
                  " channel" +
                  (subscribedChsOnAg === 1 ? "" : "s"),
                "ok",
              );
            }
          }
        }
        /* Clear pool selection after a bundle subscribe so the next
         * drag isn't an accidental re-apply. */
        if (s.source === "pool" && items.length > 1) _topoPoolSelectClear();
        _topoLastSig = ""; /* force re-render with new edges */
        renderActivityTab();
      }
    }
    if (s.moved) {
      /* Any drag motion → suppress the trailing synthetic click so it
       * doesn't trigger the single/triple dispatcher. We keep the state
       * around for one tick so the click handler sees suppressClick,
       * then tear it down. */
      s.suppressClick = true;
      _topoClearDrop();
      /* Fade the ghost out over 250ms instead of hard-removing — the
       * babble just "evaporates" instead of popping. ywatanabe
       * 2026-04-19: "babble should disappear soon with animation". */
      if (s.ghost) {
        var ghost = s.ghost;
        ghost.style.transition = "opacity 0.25s ease-out";
        ghost.style.opacity = "0";
        setTimeout(function () {
          if (ghost.parentNode) ghost.parentNode.removeChild(ghost);
        }, 280);
        s.ghost = null;
      }
      setTimeout(function () {
        if (_topoDragState === s) _topoDragState = null;
      }, 0);
    } else {
      _topoCleanupDrag();
    }
  });
  /* Cancel on window blur / escape. */
  window.addEventListener("blur", _topoCleanupDrag);
  /* Delegated right-click on overview cards, topology agent nodes, and
   * topology channel diamonds → open the entity-specific context menu
   * from app.js. Survives innerHTML rewrites. ywatanabe 2026-04-19:
   * "right click should have menus based on the entity clicked;
   * (channel, agent)". Channel menu resolved first so the shared
   * .topo-channel + .topo-agent hit-test order doesn't misroute. */
  grid.addEventListener("contextmenu", function (ev) {
    if (ev.shiftKey) return;
    /* Right-click on an agent→channel edge → same unsubscribe popover
     * as the left-click path. Channel/agent nodes are resolved by later
     * branches so the order here matters — edge check first, since a
     * line never overlaps a diamond/circle hit box. */
    var topoEdge = ev.target.closest(".topo-edges line.topo-edge");
    if (topoEdge && grid.contains(topoEdge)) {
      var eAgent = topoEdge.getAttribute("data-agent");
      var eCh = topoEdge.getAttribute("data-channel");
      if (eAgent && eCh) {
        ev.preventDefault();
        ev.stopPropagation();
        _topoShowEdgeMenu(eAgent, eCh, ev.clientX, ev.clientY);
        return;
      }
    }
    var topoCh = ev.target.closest(".topo-channel[data-channel]");
    if (topoCh && grid.contains(topoCh)) {
      if (typeof _showChannelCtxMenu !== "function") return;
      var ch = topoCh.getAttribute("data-channel");
      if (!ch) return;
      ev.preventDefault();
      ev.stopPropagation();
      _showChannelCtxMenu(ch, ev.clientX, ev.clientY);
      return;
    }
    var card = ev.target.closest(".activity-card[data-agent]");
    var topo = ev.target.closest(".topo-agent[data-agent]");
    var host = card || topo;
    if (!host || !grid.contains(host)) return;
    var name = host.getAttribute("data-agent");
    if (!name) return;
    if (typeof _showAgentContextMenu !== "function") return;
    ev.preventDefault();
    ev.stopPropagation();
    _showAgentContextMenu(name, ev.clientX, ev.clientY);
  });
  _overviewGridWired = true;
}

/* Standalone copy of the client→SVG-point transform (the one inside
 * _wireTopoZoomPan is scoped). Kept separate so both wire helpers can
 * use it without sharing closure state. */
function _topoSvgPoint(svg, clientX, clientY) {
  if (!svg || !svg.createSVGPoint) return { x: clientX, y: clientY };
  var pt = svg.createSVGPoint();
  pt.x = clientX;
  pt.y = clientY;
  var m = svg.getScreenCTM();
  if (!m) return { x: clientX, y: clientY };
  return pt.matrixTransform(m.inverse());
}

var _overviewControlsWired = false;
function _wireOverviewControls() {
  if (_overviewControlsWired) return;
  var sortSelect = document.getElementById("activity-sort-select");
  var viewSwitch = document.querySelector(".activity-view-switch");
  var colorSelect = document.getElementById("activity-color-select");
  if (!sortSelect || !viewSwitch) return;
  sortSelect.value = _overviewSort;
  /* Legacy localStorage value "tiled" -> fall back to "list" since the
   * switch is now binary (Viz / List). "topology" still accepted. */
  if (_overviewView !== "list" && _overviewView !== "topology")
    _overviewView = "list";
  if (colorSelect) colorSelect.value = _overviewColor;
  /* Filter input removed — users filter via the global Ctrl+K fuzzy
   * search which already applies across every tab (ywatanabe 2026-04-
   * 19: "filtering should be always Ctrl K in the scope"). The module
   * var _overviewFilter stays zero so the old filter logic is a no-op. */
  _overviewFilter = "";
  function _setViewBtnActive() {
    viewSwitch
      .querySelectorAll(".activity-view-switch-btn")
      .forEach(function (b) {
        b.classList.toggle(
          "active",
          b.getAttribute("data-view") === _overviewView,
        );
      });
  }
  _setViewBtnActive();
  sortSelect.addEventListener("change", function () {
    _overviewSort = sortSelect.value;
    try {
      localStorage.setItem("orochi.overviewSort", _overviewSort);
    } catch (_e) {}
    renderActivityTab();
  });
  viewSwitch.addEventListener("click", function (ev) {
    var btn = ev.target.closest(".activity-view-switch-btn[data-view]");
    if (!btn) return;
    var next = btn.getAttribute("data-view");
    if (next === _overviewView) return;
    _overviewView = next;
    try {
      localStorage.setItem("orochi.overviewView", _overviewView);
    } catch (_e) {}
    _setViewBtnActive();
    renderActivityTab();
  });
  if (colorSelect) {
    colorSelect.addEventListener("change", function () {
      _overviewColor = colorSelect.value;
      try {
        localStorage.setItem("orochi.overviewColor", _overviewColor);
      } catch (_e) {}
      renderActivityTab();
    });
  }
  _overviewControlsWired = true;
}

/* Universal Escape-cancel for the topology canvas.
 *   - Closes open context menus (agent / channel) if the respective
 *     _hide*CtxMenu helpers are exposed by app.js.
 *   - Cancels an in-flight drag-subscribe gesture via _topoCleanupDrag.
 *   - Hides any active rectangle-zoom or lasso overlay so a half-drawn
 *     selection doesn't leave ghost rectangles on-screen.
 * Bound once (guarded by _topoEscWired) at document level in capture
 * phase so it fires before per-widget handlers. Text-input focus is
 * respected — we early-return when an editable element is focused so
 * users can still Escape out of inputs without triggering these.
 * ywatanabe 2026-04-19. */
var _topoEscWired = false;
function _wireTopoEscCancel() {
  if (_topoEscWired) return;
  _topoEscWired = true;
  document.addEventListener(
    "keydown",
    function (ev) {
      if (ev.key !== "Escape") return;
      var t = ev.target;
      if (t) {
        var tag = (t.tagName || "").toUpperCase();
        if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
        if (t.isContentEditable) return;
      }
      /* Close any open context menus first. */
      if (typeof window._hideAgentCtxMenu === "function") {
        try {
          window._hideAgentCtxMenu();
        } catch (_) {}
      }
      if (typeof window._hideChannelCtxMenu === "function") {
        try {
          window._hideChannelCtxMenu();
        } catch (_) {}
      }
      /* Cancel in-flight topology drag (subscribe-by-drag). */
      if (typeof _topoDragState !== "undefined" && _topoDragState) {
        try {
          _topoCleanupDrag();
        } catch (_) {}
      }
      /* Hide any lingering rectangle-zoom / lasso overlay rects. The
       * actual `dragging` state lives in _wireTopoZoomPan's closure and
       * isn't reachable from here, but hiding the visual overlay is the
       * user-visible cancel — the next mouseup will reset the closure. */
      var zb = document.querySelector(".topo-svg .topo-zoombox");
      if (zb) zb.style.display = "none";
      var lz = document.querySelector(".topo-svg .topo-lasso");
      if (lz) lz.style.display = "none";
      var svg = document.querySelector(".topo-svg");
      if (svg) {
        svg.classList.remove("topo-zooming");
        svg.classList.remove("topo-panning");
        svg.classList.remove("topo-lassoing");
      }
    },
    { capture: true },
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

  _wireTopoEscCancel();
  _wireOverviewControls();
  _applyOverviewViewClass(grid);

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

  /* Sort: pinned always first (they're "locked to the top"), then by
   * the user-selected key. Same ordering rule is intended to apply to
   * future topology/connection-map view too. */
  var agents = src.slice().sort(function (a, b) {
    var pa = a.pinned ? 0 : 1;
    var pb = b.pinned ? 0 : 1;
    if (pa !== pb) return pa - pb;
    var ka, kb;
    if (_overviewSort === "machine") {
      ka = (a.machine || "") + "/" + (a.name || "");
      kb = (b.machine || "") + "/" + (b.name || "");
    } else {
      ka = a.name || "";
      kb = b.name || "";
    }
    return ka.localeCompare(kb);
  });

  if (_overviewFilter) {
    var q = _overviewFilter.toLowerCase();
    agents = agents.filter(function (a) {
      var hay = (
        (a.name || "") +
        " " +
        (a.machine || "") +
        " " +
        (a.role || "")
      ).toLowerCase();
      return hay.indexOf(q) !== -1;
    });
  }

  _renderActivityCards(agents, grid);

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
