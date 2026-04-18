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

/* ── Overview controls state (filter / sort / view / inline-expand) ──── */
var _overviewFilter = "";
var _overviewSort = "name";
var _overviewView = "list";
var _overviewExpanded = null;
try {
  var _savedSort = localStorage.getItem("orochi.overviewSort");
  if (_savedSort === "name" || _savedSort === "machine")
    _overviewSort = _savedSort;
  var _savedView = localStorage.getItem("orochi.overviewView");
  if (_savedView === "list" || _savedView === "tiled")
    _overviewView = _savedView;
} catch (_e) {
  /* localStorage may be unavailable — fall back to defaults */
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
  var lastToolSec =
    typeof _secondsSinceIso === "function"
      ? _secondsSinceIso(a.last_tool_at || a.last_action)
      : null;
  if (lastToolSec != null && lastToolSec < 30) return "running";
  return "idle";
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
      var color = getAgentColor(rawName);
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

  Array.prototype.forEach.call(
    grid.querySelectorAll(".activity-card[data-agent]"),
    function (card) {
      card.style.cursor = "pointer";
      card.addEventListener("click", function (ev) {
        if (ev.target.closest(".activity-pin-btn")) return;
        var name = card.getAttribute("data-agent");
        if (!name) return;
        if (ev.shiftKey || ev.ctrlKey || ev.metaKey) {
          if (typeof addTag === "function") addTag("agent", name);
          return;
        }
        _overviewExpanded = _overviewExpanded === name ? null : name;
        renderActivityTab();
      });
      card.addEventListener("mouseenter", function () {
        var host = card.getAttribute("data-machine");
        if (host && typeof syncHostHover === "function")
          syncHostHover(host, true);
      });
      card.addEventListener("mouseleave", function () {
        var host = card.getAttribute("data-machine");
        if (host && typeof syncHostHover === "function")
          syncHostHover(host, false);
      });
    },
  );

  Array.prototype.forEach.call(
    grid.querySelectorAll(".activity-pin-btn[data-pin-name]"),
    function (btn) {
      btn.addEventListener("click", function (ev) {
        ev.stopPropagation();
        var name = btn.getAttribute("data-pin-name");
        var nextPin = btn.getAttribute("data-pin-next") === "true";
        /* Optimistic UI: flip local __lastAgents entry and the button
         * state immediately so the pin feels responsive, then hit the
         * API. fetchAgents() will re-render with authoritative server
         * data once the POST/DELETE lands. */
        var live = window.__lastAgents || [];
        for (var i = 0; i < live.length; i++) {
          if (live[i].name === name) {
            live[i].pinned = nextPin;
            break;
          }
        }
        btn.classList.toggle("activity-pin-on", nextPin);
        btn.setAttribute("data-pin-next", nextPin ? "false" : "true");
        if (typeof togglePinAgent === "function") {
          togglePinAgent(name, nextPin);
        } else {
          console.error(
            "togglePinAgent unavailable — pin click had no effect for",
            name,
          );
        }
      });
    },
  );

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

/* Apply layout class (list vs tile) to the overview grid. */
function _applyOverviewViewClass(grid) {
  if (!grid) return;
  grid.classList.remove(
    "activity-view-list",
    "activity-view-tiled",
    "activity-grid-detail",
  );
  grid.classList.add(
    _overviewView === "tiled" ? "activity-view-tiled" : "activity-view-list",
  );
}

var _overviewControlsWired = false;
function _wireOverviewControls() {
  if (_overviewControlsWired) return;
  var filterInput = document.getElementById("activity-filter-input");
  var sortSelect = document.getElementById("activity-sort-select");
  var viewSelect = document.getElementById("activity-view-select");
  if (!filterInput || !sortSelect || !viewSelect) return;
  sortSelect.value = _overviewSort;
  viewSelect.value = _overviewView;
  filterInput.value = _overviewFilter;
  filterInput.addEventListener("input", function () {
    _overviewFilter = filterInput.value || "";
    renderActivityTab();
  });
  sortSelect.addEventListener("change", function () {
    _overviewSort = sortSelect.value;
    try {
      localStorage.setItem("orochi.overviewSort", _overviewSort);
    } catch (_e) {}
    renderActivityTab();
  });
  viewSelect.addEventListener("change", function () {
    _overviewView = viewSelect.value;
    try {
      localStorage.setItem("orochi.overviewView", _overviewView);
    } catch (_e) {}
    renderActivityTab();
  });
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
