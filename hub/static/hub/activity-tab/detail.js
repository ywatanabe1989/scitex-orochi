/* activity-tab/detail.js — per-agent full detail view renderer
 * (_renderActivityAgentDetail). */

/* Per-agent full detail view */
function _renderActivityAgentDetail(a, grid) {
  /* SSH guard — when a live xterm session is running in this agent's
   * pane, skip the heartbeat re-render. Otherwise innerHTML reset
   * would destroy the xterm DOM node + its internal canvas/texture
   * state, killing the user's shell session mid-typing. The detail
   * fields go stale for the duration of the SSH session; Refresh /
   * Close SSH restores live updates. */
  if (_activityPaneSshState && _activityPaneSshState[a.name]) {
    var _sshLive = grid.querySelector(".agent-detail-ssh-container");
    if (_sshLive) return;
  }
  /* Merge the registry row with any cached /detail/ payload so we
   * display the full CLAUDE.md and redacted pane_text when available,
   * while still rendering something immediately from the registry. */
  var d = _activityDetailCache[a.name] || {};
  a = Object.assign({}, a, {
    orochi_claude_md: d.orochi_claude_md || a.orochi_claude_md || a.orochi_claude_md_head || "",
    orochi_pane_tail_block: d.pane_text || a.orochi_pane_tail_block || a.orochi_pane_tail || "",
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
  var pane = a.orochi_pane_tail_block || a.orochi_pane_tail || "";
  var ctxPct = a.orochi_context_pct != null ? Number(a.orochi_context_pct) : null;
  var q5 = a.quota_5h_used_pct != null ? Number(a.quota_5h_used_pct) : null;
  var q7 = a.quota_7d_used_pct != null ? Number(a.quota_7d_used_pct) : null;
  var subCnt = a.orochi_subagent_count != null ? Number(a.orochi_subagent_count) : null;
  var chips = [];
  var cm = a.context_management || null;
  var cmTrig =
    cm && cm.strategy && cm.strategy !== "noop" && cm.trigger_at_percent != null
      ? Number(cm.trigger_at_percent)
      : null;
  if (ctxPct != null) {
    var ctxChip = "ctx " + ctxPct.toFixed(1) + "%";
    if (cmTrig != null) {
      var glyph = cm.strategy === "restart" ? "↻" : "↺";
      ctxChip += " " + glyph + cmTrig.toFixed(0) + "%";
    }
    chips.push(ctxChip);
  }
  if (q5 != null) chips.push("5h " + q5.toFixed(0) + "%");
  if (q7 != null) chips.push("7d " + q7.toFixed(0) + "%");
  if (subCnt != null) chips.push("orochi_subagents " + subCnt);
  if (a.orochi_model) chips.push(a.orochi_model);
  if (a.orochi_multiplexer) chips.push(a.orochi_multiplexer);
  if (a.orochi_pid) chips.push("orochi_pid " + a.orochi_pid);
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
   * <synthetic>-style orochi_model placeholders, mirroring the same polish on
   * the Agents tab detail card. */
  var _machine = a.orochi_machine || "?";
  var _fqdn = a.orochi_hostname_canonical || "";
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
  var _rawModel = a.orochi_model || "";
  var _modelDisplay =
    _rawModel.length > 2 &&
    _rawModel.charAt(0) === "<" &&
    _rawModel.charAt(_rawModel.length - 1) === ">"
      ? "—"
      : _rawModel || "-";
  /* #257 + #261: surface the canonical heartbeat metadata so humans
   * scanning the detail pane can verify "where am I really running"
   * at a glance. `Hostname` is the live orochi_hostname(1); distinct from
   * `Machine` (the YAML config label). `Instance` truncates the UUID
   * to 8 chars (full UUID is in dev tools). `Launch` renders as a
   * sigil so sac vs manual is obvious. Empty fields collapse to "-"
   * for legacy agents that haven't been upgraded yet. */
  var _launchSigil = {
    "sac": "🤖 sac",
    "sac-ssh": "🛰 sac-ssh",
    "sbatch": "💼 sbatch",
    "manual-tmux": "👤 tmux",
    "manual-direct": "👤 direct",
    "unknown": "?",
  };
  var _launchDisplay = a.launch_method
    ? (_launchSigil[a.launch_method] || a.launch_method)
    : "-";
  var _instanceShort = a.instance_id
    ? String(a.instance_id).slice(0, 8) + "…"
    : "-";
  var _proxyDisplay = a.is_proxy
    ? "yes (rank " + (a.priority_rank != null ? a.priority_rank : "?") + ")"
    : (a.priority_rank === 0 ? "no (primary)" : "-");
  var _priorityListDisplay = (a.priority_list && a.priority_list.length)
    ? a.priority_list.join(" → ")
    : "-";
  var metaFields = [
    ["Role", a.role || "agent"],
    ["Machine", _machineDisplay],
    /* Live orochi_hostname(1). When this disagrees with Machine, the agent
     * yaml is misconfigured (or the agent moved hosts). */
    ["Hostname", a.orochi_hostname || "-"],
    ["Uname", a.uname || "-"],
    ["Instance", _instanceShort],
    ["Launch", _launchDisplay],
    ["Proxy?", _proxyDisplay],
    ["Priority list", _priorityListDisplay],
    ["Model", _modelDisplay],
    ["Multiplexer", a.orochi_multiplexer || "-"],
    ["PID", a.orochi_pid || "-"],
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
    ["Pane state", a.orochi_pane_state || "-"],
    ["Idle", _fmtSec(a.idle_seconds)],
    [
      "Last tool",
      d.sac_hooks_last_tool_at
        ? _fmtSec(_secondsSinceIso(d.sac_hooks_last_tool_at)) +
          " ago" +
          (d.sac_hooks_last_tool_name ? " (" + d.sac_hooks_last_tool_name + ")" : "")
        : "-",
    ],
    [
      "Last MCP",
      d.sac_hooks_last_mcp_tool_at
        ? _fmtSec(_secondsSinceIso(d.sac_hooks_last_mcp_tool_at)) +
          " ago" +
          (d.sac_hooks_last_mcp_tool_name ? " (" + d.sac_hooks_last_mcp_tool_name + ")" : "")
        : "-",
    ],
    [
      "Last action",
      d.sac_hooks_last_action_at
        ? _fmtSec(_secondsSinceIso(d.sac_hooks_last_action_at)) +
          " ago (" +
          (d.sac_hooks_last_action_name || "?") +
          " " +
          (d.sac_hooks_last_action_outcome || "?") +
          (d.sac_hooks_last_action_elapsed_s != null
            ? ", " + Number(d.sac_hooks_last_action_elapsed_s).toFixed(1) + "s"
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
    escapeHtml(
      typeof getAgentColor === "function"
        ? getAgentColor(
            typeof _colorKeyFor === "function" ? _colorKeyFor(a) : a.name,
          )
        : "#4ecdc4",
    ) +
    '">' +
    escapeHtml(
      typeof cleanAgentName === "function" ? cleanAgentName(a.name) : a.name,
    ) +
    "</span>" +
    (a.orochi_current_task
      ? '<em class="agent-detail-task">' + escapeHtml(a.orochi_current_task) + "</em>"
      : "") +
    "</div>" +
    '<div class="agent-detail-meta-grid">' +
    metaGridHtml +
    "</div>" +
    "</div>";
  /* Task */
  var taskHtml =
    a.orochi_current_task || a.last_message_preview
      ? '<div class="agent-detail-section"><span class="agent-detail-pane-label">Task: </span>' +
        escapeHtml(a.orochi_current_task || a.last_message_preview) +
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
    /* SSH — swap the read-only scrollback for a live xterm connected
     * to this agent's host. TODO.md "Web Terminal ... expected to
     * implement in the Agents List expanded space". */
    '<button type="button" class="agent-detail-pane-btn" ' +
    'data-act-pane-action="ssh" data-agent="' +
    escapeHtml(a.name) +
    '" data-orochi_machine="' +
    escapeHtml(a.orochi_machine || "") +
    '" title="Open SSH terminal to ' +
    escapeHtml(a.orochi_machine || "this host") +
    '">SSH</button>' +
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
  var claudeMd = a.orochi_claude_md || a.orochi_claude_md_head || "";
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
    d.sac_hooks_recent_tools || [],
    d.sac_hooks_recent_prompts || [],
    d.sac_hooks_agent_calls || [],
    d.sac_hooks_background_tasks || [],
    d.sac_hooks_tool_counts || {},
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
  /* Preserve an active SSH terminal across heartbeat re-renders — the
   * xterm container lives in #agent-detail-pane-content and would
   * otherwise be wiped by the innerHTML reset. Grab it before the
   * reset and splice it back in after. */
  var _preservedSsh = null;
  if (_activityPaneSshState && _activityPaneSshState[a.name]) {
    var _sshCur = grid.querySelector(".agent-detail-ssh-container");
    if (_sshCur) _preservedSsh = _sshCur;
  }
  grid.innerHTML =
    '<div class="agent-detail-view">' +
    headerHtml +
    taskHtml +
    channelsHtml +
    splitHtml +
    hooksHtml +
    "</div>";
  if (_preservedSsh) {
    /* Replace the fresh <pre> with the live xterm container. The SSH
     * state (ws, term, fitAddon) is unchanged so input/output keep
     * flowing without a reconnect. */
    var _newPre = grid.querySelector("#agent-detail-pane-content");
    if (_newPre && _newPre.parentNode) {
      _newPre.parentNode.replaceChild(_preservedSsh, _newPre);
    }
  }
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
  var pre = grid.querySelector("pre.agent-detail-pane");
  if (pre) pre.scrollTop = pre.scrollHeight;
  _bindActivityPaneControls(grid, a.name, pane, paneFull);
  _bindActivityChannelControls(grid, a.name);
  _bindActivitySendInput(grid, a.name);
  /* If SSH was preserved, reflect "Close SSH" on the fresh button. */
  if (_preservedSsh) {
    var _sshBtn = grid.querySelector('[data-act-pane-action="ssh"]');
    if (_sshBtn) {
      _sshBtn.classList.add("agent-detail-pane-btn-on");
      _sshBtn.textContent = "Close SSH";
    }
  }
}


