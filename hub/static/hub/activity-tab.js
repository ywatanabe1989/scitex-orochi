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
var _topoViewBoxHistory = []; /* stack for Escape = undo zoom */
var _topoZoomWired = false;
var _topoLastPositions = { agents: {}, channels: {} };

/* Spawn one glowing packet traveling from (fromX,fromY) -> (toX,toY)
 * over `dur` ms, optionally delayed. Self-removes after animation. */
function _topoSpawnPacket(edges, from, to, dur, delay, klass) {
  var ns = "http://www.w3.org/2000/svg";
  var g = document.createElementNS(ns, "g");
  g.setAttribute("class", "topo-packet " + (klass || ""));
  var glow = document.createElementNS(ns, "circle");
  glow.setAttribute("cx", from.x);
  glow.setAttribute("cy", from.y);
  glow.setAttribute("r", "6");
  glow.setAttribute("fill-opacity", "0.35");
  var core = document.createElementNS(ns, "circle");
  core.setAttribute("cx", from.x);
  core.setAttribute("cy", from.y);
  core.setAttribute("r", "3");
  [glow, core].forEach(function (node) {
    var ax = document.createElementNS(ns, "animate");
    ax.setAttribute("attributeName", "cx");
    ax.setAttribute("from", String(from.x));
    ax.setAttribute("to", String(to.x));
    ax.setAttribute("dur", dur + "ms");
    ax.setAttribute("begin", delay + "ms");
    ax.setAttribute("fill", "freeze");
    var ay = document.createElementNS(ns, "animate");
    ay.setAttribute("attributeName", "cy");
    ay.setAttribute("from", String(from.y));
    ay.setAttribute("to", String(to.y));
    ay.setAttribute("dur", dur + "ms");
    ay.setAttribute("begin", delay + "ms");
    ay.setAttribute("fill", "freeze");
    node.appendChild(ax);
    node.appendChild(ay);
  });
  g.appendChild(glow);
  g.appendChild(core);
  edges.appendChild(g);
  setTimeout(
    function () {
      if (g.parentNode) g.parentNode.removeChild(g);
    },
    dur + delay + 80,
  );
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
  if (!sender || !channel) return;
  var svg = document.querySelector(".activity-view-topology .topo-svg");
  if (!svg) return;
  var ap = _topoLastPositions.agents[sender];
  var cp = _topoLastPositions.channels[channel];
  if (!ap || !cp) return;
  var edges = svg.querySelector(".topo-edges");
  if (!edges) return;
  var klass =
    opts && opts.isArtifact ? "topo-packet-artifact" : "topo-packet-message";
  var LEG = 900;
  /* Leg 1 — sender → channel. */
  _topoSpawnPacket(edges, ap, cp, LEG, 0, klass);
  _topoFlashEdge(edges, ap, cp, 0, LEG);
  /* Leg 2 — channel → each subscribed agent (except sender). Propagate
   * only through visible agents (positions known). */
  var subscribers = Object.keys(_topoLastPositions.agents).filter(function (n) {
    if (n === sender) return false;
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
    _topoSpawnPacket(edges, cp, target, LEG, LEG, klass);
    _topoFlashEdge(edges, cp, target, LEG, LEG);
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
    var prev = _topoViewBoxHistory.pop();
    _topoViewBox = prev;
    _applyVB(svg, prev);
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

  var dragging = null; /* {mode:"zoom"|"pan", ...} */
  grid.addEventListener("mousedown", function (ev) {
    var svg = ev.target.closest && ev.target.closest(".topo-svg");
    if (!svg) return;
    if (ev.target.closest(".topo-agent, .topo-channel")) return;
    if (ev.button !== 0) return;
    ev.preventDefault();
    var start = _svgPoint(svg, ev.clientX, ev.clientY);
    /* Semantic: plain drag = rectangle zoom, shift/ctrl-drag = pan.
     * Cursor class toggles so it's default when just hovering and
     * becomes crosshair/grab only during the actual drag. */
    var panMode = ev.ctrlKey || ev.metaKey || ev.shiftKey;
    if (panMode) {
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
    }
    svg.classList.remove("topo-zooming");
    svg.classList.remove("topo-panning");
    dragging = null;
  });
  grid.addEventListener("dblclick", function (ev) {
    var svg = ev.target.closest && ev.target.closest(".topo-svg");
    if (!svg) return;
    /* Double-click on a channel diamond → open a compose-to-channel
     * prompt. The graph becomes a posting interface (ywatanabe
     * 2026-04-19: "the graph itself should be a message posting
     * interface; like double click a channel -> post"). */
    var ch = ev.target.closest(".topo-channel[data-channel]");
    if (ch) {
      ev.preventDefault();
      ev.stopPropagation();
      var chName = ch.getAttribute("data-channel");
      if (!chName) return;
      var text = window.prompt("Post to " + chName + ":", "");
      if (text == null) return;
      text = String(text).trim();
      if (!text) return;
      var payload = { channel: chName, content: text };
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
      return;
    }
    /* Plain double-click on empty area = reset zoom. */
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
  /* Mouse wheel zoom — cursor-anchored, 10% per tick; routes through
   * _zoomAt so history / reset work. */
  grid.addEventListener(
    "wheel",
    function (ev) {
      var svg = ev.target.closest && ev.target.closest(".topo-svg");
      if (!svg) return;
      ev.preventDefault();
      var p = _svgPoint(svg, ev.clientX, ev.clientY);
      var factor = ev.deltaY > 0 ? 1.1 : 1 / 1.1;
      _zoomAt(svg, factor, p.x, p.y);
    },
    { passive: false },
  );
}
function _topoSignature(visible) {
  /* Cheap digest: name + online-ness + liveness bucket + pinned +
   * channel count. Liveness is in so the FN LED color follows the
   * online→idle→stale transitions. Individual idle-seconds are NOT —
   * those flap every second and would cause pointless repaints. */
  var parts = [];
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
  var channels = Object.keys(chSet).sort();

  /* Size from the grid's inner box. Fall back to generous defaults on
   * first render when clientWidth is still 0. Leave room for labels so
   * long agent names don't get clipped at the viewport edge. */
  var W = Math.max(grid.clientWidth || 0, 600);
  var H = Math.max(grid.clientHeight || 0, 420);
  var pad = 140; /* label-safe margin */
  var cx = W / 2;
  var cy = H / 2;
  var rOuter = Math.max(80, Math.min(W, H) / 2 - pad);
  var rInner = Math.max(40, rOuter * 0.55);

  function _pt(r, i, n) {
    /* Start at -90° so the first node sits at 12 o'clock. */
    var theta = (i / Math.max(1, n)) * Math.PI * 2 - Math.PI / 2;
    return { x: cx + r * Math.cos(theta), y: cy + r * Math.sin(theta) };
  }

  var agentPos = {};
  visible.forEach(function (a, i) {
    agentPos[a.name] = _pt(rOuter, i, visible.length);
  });
  var chPos = {};
  channels.forEach(function (c, i) {
    chPos[c] = _pt(rInner, i, channels.length);
  });
  /* Stash for the message-pulse animator (_topoPulseEdge). Re-computed
   * on every render so a window-resize or agent add/remove still
   * targets the right coordinates. */
  _topoLastPositions = { agents: agentPos, channels: chPos };

  /* Edges — iterate visible agents, intersect with the channel set. */
  var edgesSvg = "";
  visible.forEach(function (a) {
    var ap = agentPos[a.name];
    (a.channels || []).forEach(function (c) {
      var cp = chPos[c];
      if (!ap || !cp) return;
      edgesSvg +=
        '<line x1="' +
        ap.x.toFixed(1) +
        '" y1="' +
        ap.y.toFixed(1) +
        '" x2="' +
        cp.x.toFixed(1) +
        '" y2="' +
        cp.y.toFixed(1) +
        '" stroke="#2a3a40" stroke-opacity="0.6" stroke-width="1"/>';
    });
  });

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
      return (
        '<g class="topo-node topo-channel" data-channel="' +
        escapeHtml(c) +
        '" data-agent-count="' +
        count +
        '">' +
        '<polygon points="' +
        pts +
        '" fill="#1a1a1a" stroke="#444" stroke-width="1"/>' +
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
      var wsColor = connected ? "#4ecdc4" : "#555";
      var fnColor = FN_COLORS[liveness] || "#555";
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
      return (
        '<g class="topo-node topo-agent" data-agent="' +
        escapeHtml(a.name) +
        '">' +
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

  /* viewBox persisted in _topoViewBox across re-renders so zoom/pan
   * state survives heartbeat-driven rebuilds. If null, use the natural
   * (0 0 W H) frame so the whole scene fits. */
  var vb = _topoViewBox || { x: 0, y: 0, w: W, h: H };
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
    '<g class="topo-edges">' +
    edgesSvg +
    "</g>" +
    '<g class="topo-channels">' +
    chSvg +
    "</g>" +
    '<g class="topo-agents">' +
    agentSvg +
    "</g>" +
    '<rect class="topo-zoombox" x="0" y="0" width="0" height="0"' +
    ' fill="rgba(78,205,196,0.1)" stroke="#4ecdc4" stroke-width="1"' +
    ' stroke-dasharray="4 4" style="display:none;pointer-events:none"/>' +
    "</svg>";

  var detailBox = "";
  if (_overviewExpanded) {
    detailBox =
      '<div class="activity-inline-detail" data-detail-for="' +
      escapeHtml(_overviewExpanded) +
      '"><p class="empty-notice">Loading detail…</p></div>';
  }
  var hint =
    '<div class="topo-hint">drag = pan · ctrl+drag = rectangle zoom · wheel = zoom · esc = back · 0 = reset</div>';
  var ctrls =
    '<div class="topo-ctrls">' +
    '<button type="button" class="topo-ctrl-btn" data-topo-ctrl="back" title="Previous zoom (Escape)">↶</button>' +
    '<button type="button" class="topo-ctrl-btn" data-topo-ctrl="minus" title="Zoom out (−)">−</button>' +
    '<button type="button" class="topo-ctrl-btn" data-topo-ctrl="reset" title="Reset zoom (0)">0</button>' +
    '<button type="button" class="topo-ctrl-btn" data-topo-ctrl="plus" title="Zoom in (+)">+</button>' +
    "</div>";
  grid.innerHTML =
    '<div class="topo-wrap">' + hint + ctrls + svg + "</div>" + detailBox;

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
    /* Topology view — tap an agent-node <g data-agent="…"> to toggle
     * expand. Channel nodes are a no-op for now (future: filter to
     * that channel). */
    var topoAgent = ev.target.closest(".topo-agent[data-agent]");
    if (topoAgent && grid.contains(topoAgent)) {
      if (ev.target.closest(".activity-inline-detail")) return;
      var tname = topoAgent.getAttribute("data-agent");
      if (!tname) return;
      if (ev.shiftKey || ev.ctrlKey || ev.metaKey) {
        if (typeof addTag === "function") addTag("agent", tname);
        return;
      }
      _overviewExpanded = _overviewExpanded === tname ? null : tname;
      renderActivityTab();
    }
  });
  /* Delegated right-click on overview cards (and topology agent nodes) →
   * open the agent context menu from app.js. Survives innerHTML rewrites. */
  grid.addEventListener("contextmenu", function (ev) {
    if (ev.shiftKey) return;
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

function renderActivityTab() {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  var grid = document.getElementById("activity-grid");
  var summary = document.getElementById("activity-summary");
  if (!grid) return;

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
