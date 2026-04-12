/* Activity tab — real-time agent status board */
/* globals: apiUrl, escapeHtml, getAgentColor, cleanAgentName, fetchAgents */

var activityRefreshTimer = null;

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
    case "stale": return 0;
    case "online": return 1;
    case "idle": return 2;
    case "offline": return 3;
    default: return 4;
  }
}

function _renderHealthField(health) {
  if (!health || !health.status) return "";
  var st = String(health.status);
  var reason = health.reason ? ' · ' + escapeHtml(health.reason) : "";
  var src = health.source ? ' (' + escapeHtml(health.source) + ')' : "";
  return (
    '<div class="activity-health activity-health-' + escapeHtml(st) + '">' +
    '<span class="activity-health-icon">\uD83E\uDE7A</span> ' +
    '<span class="activity-health-status">' + escapeHtml(st) + '</span>' +
    reason + src +
    '</div>'
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
    ? '<span class="activity-task-age" title="seconds since last heartbeat">' + escapeHtml(age) + '</span>'
    : "";
  if (!task) {
    if (fallback) {
      return (
        '<div class="activity-task-row activity-task-prose">' +
        '<span class="activity-task-fallback" title="last activity (no structured task set)">' +
        _linkifyIssues(escapeHtml(fallback)) +
        '</span>' +
        ageChip +
        '</div>'
      );
    }
    return (
      '<div class="activity-task-row">' +
      '<span class="activity-task-empty">no task reported</span>' +
      ageChip +
      '</div>'
    );
  }
  var parsed = _parseCurrentTask(task);
  var fullTitle = escapeHtml(task);
  if (parsed.isProse) {
    return (
      '<div class="activity-task-row activity-task-prose" title="' + fullTitle + '">' +
      '<span class="activity-tool-prose">' + _linkifyIssues(escapeHtml(parsed.arg)) + '</span>' +
      ageChip +
      '</div>'
    );
  }
  var toolHtml = parsed.tool
    ? '<span class="activity-tool-name">' + escapeHtml(parsed.tool) + '</span>'
    : "";
  var argHtml = parsed.arg
    ? '<span class="activity-tool-arg">' + _linkifyIssues(escapeHtml(parsed.arg)) + '</span>'
    : "";
  return (
    '<div class="activity-task-row activity-task-tool" title="' + fullTitle + '">' +
    toolHtml + argHtml + ageChip +
    '</div>'
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
      try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
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

  var counts = { online: 0, idle: 0, stale: 0, offline: 0 };
  agents.forEach(function (a) {
    var l = a.liveness || a.status || "online";
    if (counts[l] != null) counts[l]++;
  });

  if (summary) {
    /* Legend explains the card left-border colors. ywatanabe at msg#6567
     * asked what the highlight color means — there was no key anywhere
     * on the page. Each pill in the summary doubles as the legend swatch
     * for the corresponding card border, and a hover title gives the
     * timing definition. */
    summary.innerHTML =
      '<span class="activity-pill activity-pill-online" title="recently active (heartbeat &lt; 2 min)">' +
      '<span class="activity-pill-dot"></span>' + counts.online + ' active</span>' +
      '<span class="activity-pill activity-pill-idle" title="quiet 2–10 min — likely thinking or waiting">' +
      '<span class="activity-pill-dot"></span>' + counts.idle + ' idle</span>' +
      '<span class="activity-pill activity-pill-stale" title="quiet &gt;10 min — probably stuck, check it">' +
      '<span class="activity-pill-dot"></span>' + counts.stale + ' stale</span>' +
      '<span class="activity-pill activity-pill-offline" title="not connected to the hub right now">' +
      '<span class="activity-pill-dot"></span>' + counts.offline + ' offline</span>' +
      '<span class="activity-legend-hint">← border color matches</span>';
  }

  grid.innerHTML = agents.map(function (a) {
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
    var subagentCount = a.subagent_count != null
      ? Number(a.subagent_count)
      : (Array.isArray(a.subagents) ? a.subagents.length : null);
    var skillsLoaded = Array.isArray(a.skills_loaded) ? a.skills_loaded : [];
    var channels = Array.isArray(a.channels) ? a.channels : [];
    var name = escapeHtml(
      typeof hostedAgentName === "function" ? hostedAgentName(a) : cleanAgentName(a.name),
    );
    var rawName = a.name || "";
    /* Task age: prefer idle_seconds (from last_action) but fall back to
     * last_heartbeat. Used as a compact "5s"/"2m" tag beside the task. */
    var ageSec = a.idle_seconds != null
      ? Number(a.idle_seconds)
      : _secondsSinceIso(a.last_heartbeat || a.last_action);
    var ageStr = ageSec != null ? _formatIdle(ageSec) : "";
    /* "stuck" — no task, no subagents, not heard from in 5+ minutes */
    var isStuck = (
      (ageSec != null && ageSec > 300) &&
      (!subagentCount || subagentCount === 0) &&
      !task
    );
    /* Uptime from started_at */
    var uptimeSec = _secondsSinceIso(a.started_at);
    var uptimeStr = uptimeSec != null ? _formatUptime(uptimeSec) : "";

    /* Build the rich-fields chip row. Each chip is added only when its
     * underlying value is non-null/non-empty so cards stay clean. */
    var chips = [];
    /* Subagent badge — prominent when >0, muted "idle" when 0 so ywatanabe
     * can tell at a glance whether the agent is actually doing work. */
    if (subagentCount != null && subagentCount > 0) {
      chips.push(
        '<span class="activity-chip activity-chip-subs activity-chip-subs-active" title="active subagents">' +
        '\u25B6 ' + subagentCount + ' sub' + (subagentCount === 1 ? '' : 's') +
        '</span>'
      );
    } else {
      chips.push(
        '<span class="activity-chip activity-chip-subs-idle" title="no subagents running">idle (no subs)</span>'
      );
    }
    if (ctxPct != null) {
      var ctxClass = ctxPct < 50 ? "ctx-ok" : ctxPct < 80 ? "ctx-warn" : "ctx-hot";
      chips.push('<span class="activity-chip activity-chip-ctx ' + ctxClass + '" title="context usage">ctx ' + ctxPct.toFixed(1) + '%</span>');
    }
    if (model) chips.push('<span class="activity-chip activity-chip-model" title="model">' + model + '</span>');
    if (multiplexer) chips.push('<span class="activity-chip activity-chip-mux" title="multiplexer">' + multiplexer + '</span>');
    if (uptimeStr) {
      chips.push('<span class="activity-chip activity-chip-uptime" title="time since process start: ' + escapeHtml(a.started_at || "") + '">' + escapeHtml(uptimeStr) + '</span>');
    }
    if (skillsLoaded.length > 0) {
      var skillsTitle = skillsLoaded.join("\n");
      chips.push('<span class="activity-chip activity-chip-skills" title="' + escapeHtml(skillsTitle) + '">skills ' + skillsLoaded.length + '</span>');
    }
    if (channels.length > 0) {
      var chTitle = channels.join("\n");
      chips.push('<span class="activity-chip activity-chip-channels" title="' + escapeHtml(chTitle) + '">ch ' + channels.length + '</span>');
    }
    if (pid != null) chips.push('<span class="activity-chip activity-chip-pid" title="process id">pid ' + pid + '</span>');
    var chipsHtml = chips.length > 0 ? '<div class="activity-chips">' + chips.join("") + '</div>' : "";

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
              '<li class="activity-subagent activity-subagent-' + sstatus + '">' +
              '<span class="activity-subagent-branch">└─</span>' +
              '<span class="activity-subagent-name">' + sname + '</span>' +
              '<span class="activity-subagent-task">' + stask + '</span>' +
              '</li>'
            );
          })
          .join("") +
        "</ul>";
    }
    var copyPayload = (rawName + " — " + (task || preview || "(no task)")).replace(/"/g, "&quot;");
    var copyBtn =
      '<button type="button" class="activity-copy-btn" title="copy name + task to clipboard" ' +
      'data-copy="' + escapeHtml(copyPayload) + '">\uD83D\uDCCB</button>';
    var stuckClass = isStuck ? ' activity-stuck' : '';
    /* Recent actions log: 10 most recent meaningful tool_use entries
     * with timestamps. agent_meta.py emits this as `recent_actions`
     * after filtering out housekeeping mcp__scitex-orochi__* tools.
     * ywatanabe at msg#6608: 「最後 10 個の行動をタイムスタンプと一緒に
     * かくとかは？」. msg#6587: showing only the last single action is
     * pointless — needs the recent flow. */
    var recentActions = Array.isArray(a.recent_actions) ? a.recent_actions : [];
    var recentHtml = "";
    if (recentActions.length > 0) {
      recentHtml =
        '<ul class="activity-recent" title="recent tool calls (latest at bottom)">' +
        recentActions.map(function (act) {
          var ts = (act && act.ts) || "";
          var hh = "";
          if (ts && ts.length >= 19) hh = ts.slice(11, 19);
          var prev = (act && act.preview) || "";
          return (
            '<li class="activity-recent-row">' +
            '<span class="activity-recent-ts">' + escapeHtml(hh) + '</span>' +
            '<span class="activity-recent-preview" title="' + escapeHtml(prev) + '">' +
            escapeHtml(prev) + '</span></li>'
          );
        }).join("") +
        '</ul>';
    }
    /* Live tail of the agent's tmux pane (~10 most recent non-empty
     * lines). Falls back when recent_actions is empty (e.g. remote
     * hosts whose JSONL transcript isn't reachable). */
    var paneTailBlock = a.pane_tail_block || a.pane_tail || "";
    var paneTailHtml = (recentActions.length === 0 && paneTailBlock)
      ? '<pre class="activity-pane-tail" title="recent lines from this agent\'s tmux pane">' +
        escapeHtml(paneTailBlock) +
        '</pre>'
      : "";
    /* CLAUDE.md role hint + MCP server list — agent_meta.py extracts
     * the first non-empty line of the workspace CLAUDE.md and the
     * keys of .mcp.json. Both shown only if non-empty. msg#6579. */
    var claudeMdHead = a.claude_md_head || "";
    var mcpServers = Array.isArray(a.mcp_servers) ? a.mcp_servers : [];
    var roleLine = claudeMdHead
      ? '<div class="activity-role-hint" title="from workspace CLAUDE.md">' +
        escapeHtml(claudeMdHead) + '</div>'
      : "";
    var mcpLine = mcpServers.length > 0
      ? '<div class="activity-mcp-line" title="MCP servers configured for this agent">' +
        mcpServers.map(function (s) {
          return '<span class="activity-mcp-chip">' + escapeHtml(s) + '</span>';
        }).join("") +
        '</div>'
      : "";
    return (
      '<div class="activity-card activity-' + liveness + stuckClass + '" ' +
      'data-agent="' + escapeHtml(rawName) + '">' +
      '<div class="activity-card-header">' +
      '<span class="activity-status-dot activity-dot-' + liveness + '"></span>' +
      '<span class="activity-name" style="color:' + color + '">' + name + '</span>' +
      copyBtn +
      '<span class="activity-liveness">' + _livenessLabel(liveness) + (idleStr ? ' · ' + idleStr : '') + '</span>' +
      '</div>' +
      '<div class="activity-meta">' + machine + ' · ' + role + '</div>' +
      roleLine +
      '<div class="activity-task">' + _renderTaskField(task, preview, ageStr) + '</div>' +
      paneTailHtml +
      chipsHtml +
      mcpLine +
      _renderHealthField(a.health) +
      subagentsHtml +
      '</div>'
    );
  }).join("");

  /* Wire up copy buttons — delegated per-render to avoid leaks */
  Array.prototype.forEach.call(
    grid.querySelectorAll(".activity-copy-btn"),
    function (btn) {
      btn.addEventListener("click", function (ev) {
        ev.stopPropagation();
        var txt = btn.getAttribute("data-copy") || "";
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(txt).then(function () {
            btn.classList.add("activity-copy-ok");
            setTimeout(function () { btn.classList.remove("activity-copy-ok"); }, 900);
          }).catch(function () {});
        }
      });
    },
  );
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
  }
}

async function refreshActivityFromApi() {
  try {
    var res = await fetch(apiUrl("/api/agents"), { credentials: "same-origin" });
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
