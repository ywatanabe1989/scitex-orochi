/* Agents Tab — per-agent detail view + indicator lamps + pane-state badge.
 * Depends on state.js (livenessColor, _fmtDuration, _agentDetailCache,
 * _paneExpanded, _followAgent, FOLLOW_INTERVAL_MS). */

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
  var orochi_machine = d.orochi_machine || a.orochi_machine || "?";
  /* todo#56: some transcripts surface <synthetic> / <none> / <compact>
   * placeholder tokens for orochi_model when the assistant turn was synthesised
   * (e.g. after /compact). Show a dash with the raw token in the tooltip
   * instead of exposing the placeholder verbatim in the detail card. */
  function _cleanModel(m) {
    if (!m) return { display: "-", tooltip: "" };
    var raw = String(m);
    if (
      raw.length > 2 &&
      raw.charAt(0) === "<" &&
      raw.charAt(raw.length - 1) === ">"
    ) {
      return { display: "—", tooltip: "heartbeat reported " + raw };
    }
    return { display: raw, tooltip: "" };
  }
  /* todo#55/#58: canonical FQDN for the Machine row. Render
   * "<label> (<fqdn>)" only when the FQDN adds real information beyond
   * the short label. Drops redundant suffixes like ".local" /
   * ".localdomain" / ".lan" / ".home.arpa" that macOS and WSL attach to
   * their mDNS names — those contribute nothing (ywatanabe msg 2026-04-18
   * "2" flagged the duplication for the 7 ywata-note-win agents whose
   * FQDN was just the short label + ".localdomain"). */
  var machineCanonical = d.orochi_hostname_canonical || a.orochi_hostname_canonical || "";
  function _fqdnAddsInfo(short, fqdn) {
    if (!fqdn) return false;
    if (fqdn === short) return false;
    var redundantSuffixes = [".local", ".localdomain", ".lan", ".home.arpa"];
    for (var i = 0; i < redundantSuffixes.length; i++) {
      if (fqdn === short + redundantSuffixes[i]) return false;
    }
    return true;
  }
  var machineDisplay = _fqdnAddsInfo(orochi_machine, machineCanonical)
    ? orochi_machine + " (" + machineCanonical + ")"
    : orochi_machine;
  var modelClean = _cleanModel(d.orochi_model || a.orochi_model || "");
  var ctxPct = d.orochi_context_pct != null ? d.orochi_context_pct : a.orochi_context_pct;
  var currentTask = d.orochi_current_task || a.orochi_current_task || "";
  var channels = d.channel_subs || a.channels || [];
  var claudeMd = d.orochi_claude_md || a.orochi_claude_md || "";
  /* todo#460: .mcp.json is served by the detail endpoint only (not in the
   * registry summary row). Empty string = agent has not yet heartbeated
   * with dotfiles PR#71 agent_meta.py --push; we render an explicit
   * empty-state so the absence is discoverable rather than invisible. */
  var mcpJson = d.orochi_mcp_json || "";
  var mcpServers = d.orochi_mcp_servers || a.orochi_mcp_servers || [];
  /* pane_text from the detail endpoint is already redacted; the
   * registry fallback (orochi_pane_tail_block / orochi_pane_tail) is NOT, so prefer
   * detail whenever we have it. */
  var pane = "";
  var paneSource = "unavailable";
  if (d.pane_text != null) {
    pane = d.pane_text;
    paneSource = d.pane_text_source || (pane ? "cached" : "unavailable");
  } else {
    pane = a.orochi_pane_tail_block || a.orochi_pane_tail || "";
    paneSource = pane ? "cached" : "unavailable";
  }
  // todo#47 — longer scrollback (up to ~500 filtered lines) pushed
  // by newer agent_meta.py clients. Empty string when the agent
  // hasn't updated yet; the "Full pane" toggle falls back to the
  // short pane in that case.
  var paneFull = d.pane_text_full || "";
  var paneFullAvailable = !!paneFull;

  var orochi_workdir = d.orochi_workdir || a.orochi_workdir || "";
  var orochi_pid = d.orochi_pid || a.orochi_pid || "";
  var orochi_multiplexer = d.orochi_multiplexer || a.orochi_multiplexer || "";
  var idleSec = d.idle_seconds != null ? d.idle_seconds : a.idle_seconds;
  var lastHeartbeat = d.last_heartbeat || a.last_heartbeat || "";
  var registeredAt = d.registered_at || a.registered_at || "";
  var subagentCount =
    d.orochi_subagent_count != null ? d.orochi_subagent_count : a.orochi_subagent_count;
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
  /* Smart middle-truncation for long paths (e.g. workdirs). Keep the
   * first and last segments readable and drop the middle so the cell
   * doesn't steal a full row. Full path goes into the title tooltip. */
  function _smartTruncatePath(p, max) {
    if (!p) return p;
    var home = /^\/home\/[^/]+/;
    var display = String(p).replace(home, "~");
    if (display.length <= max) return display;
    var head = Math.floor((max - 1) / 2);
    var tail = max - 1 - head;
    return display.slice(0, head) + "\u2026" + display.slice(-tail);
  }
  /* [label, value, tooltip] — tooltip optional. The detail-meta-grid
   * renderer below writes the tooltip onto the <span> so hovering a
   * cell reveals the full value (critical for orochi_workdir paths that get
   * middle-truncated). */
  var metaFields = [
    ["Role", role, "declared agent role (head / healer / expert-scitex / ...)"],
    [
      "Machine",
      machineDisplay,
      _fqdnAddsInfo(orochi_machine, machineCanonical)
        ? "short label · canonical FQDN reported by the heartbeat"
        : machineCanonical
          ? "FQDN is just the short label + redundant mDNS suffix; hidden"
          : "orochi_hostname the agent is running on (short label — no FQDN reported)",
    ],
    [
      "Model",
      modelClean.display,
      modelClean.tooltip || "Claude orochi_model id the agent is running against",
    ],
    [
      "Multiplexer",
      orochi_multiplexer || "-",
      "tmux / screen session hosting the agent process",
    ],
    ["PID", orochi_pid || "-", "host-side process id of the claude-code binary"],
    [
      "Liveness",
      liveness,
      "push-freshness: online <2m, idle 2–10m, stale >10m, offline disconnected",
    ],
    [
      "Context",
      ctxPct != null ? Number(ctxPct).toFixed(1) + "%" : "-",
      "context-window usage reported by claude-hud",
    ],
    [
      "5h quota",
      _fmtQuota(q5, q5Reset),
      "rolling 5-hour Claude usage quota consumed",
    ],
    [
      "7d quota",
      _fmtQuota(q7, q7Reset),
      "rolling 7-day Claude usage quota consumed",
    ],
    [
      "Subagents (" + (subagentCount != null ? subagentCount : 0) + ")",
      subagentCount != null ? String(subagentCount) : "-",
      "active Agent-tool orochi_subagents spawned by this agent",
    ],
    [
      "Uptime",
      d.uptime_seconds != null ? _fmtDuration(d.uptime_seconds) : "-",
      "time since this agent first registered",
    ],
    [
      "Idle",
      idleSec != null ? _fmtDuration(idleSec) : "-",
      "time since this agent last reported activity",
    ],
    [
      "Workdir",
      _smartTruncatePath(orochi_workdir, 40) || "-",
      orochi_workdir || "(no orochi_workdir reported)",
    ],
    [
      "Registered",
      registeredAt || "-",
      "iso timestamp of the first register heartbeat",
    ],
    [
      "Last heartbeat",
      lastHeartbeat || "-",
      "iso timestamp of the most recent push",
    ],
  ];
  var metaHtml = metaFields
    .map(function (f) {
      var tip = f[2] ? ' title="' + escapeHtml(String(f[2])) + '"' : "";
      return (
        "<span" +
        tip +
        "><strong>" +
        escapeHtml(f[0]) +
        ":</strong>" +
        escapeHtml(String(f[1])) +
        "</span>"
      );
    })
    .join("");
  /* msg#16116 Item 4: inline subagent-count chip in the detail header. */
  var headerSubagents =
    typeof window.renderAgentSubagentCount === "function"
      ? window.renderAgentSubagentCount({ orochi_subagent_count: subagentCount })
      : "";
  var headerHtml =
    '<div class="agent-detail-header">' +
    '<div class="agent-detail-header-line">' +
    _renderIndicatorLamps(a, d) +
    '<span class="agent-detail-header-title">' +
    escapeHtml(a.name) +
    "</span>" +
    headerSubagents +
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

  // todo#47 — Terminal output controls: Refresh / Copy / Follow /
  // (optional) Expand. Expand only appears when the newer
  // agent_meta.py push delivered pane_text_full. Follow polls /detail
  // every 3s for a live-tail feel. Buttons are data-hooked per-agent
  // so multiple stacked detail panels don't collide.
  var _isFollowing = _followAgent === a.name;
  var _isExpanded = _paneExpanded[a.name] && paneFullAvailable;
  var paneLabel =
    'Terminal output <span class="agent-detail-pane-source">(' +
    escapeHtml(paneSource) +
    ")</span>" +
    '<span class="agent-detail-pane-controls">' +
    (paneFullAvailable
      ? '<button type="button" class="agent-detail-pane-btn' +
        (_isExpanded ? " agent-detail-pane-btn-on" : "") +
        '" data-action="expand-pane" data-agent="' +
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
    'data-action="refresh-pane" data-agent="' +
    escapeHtml(a.name) +
    '" title="Force re-fetch of detail (pane + RTT + last action)">Refresh</button>' +
    '<button type="button" class="agent-detail-pane-btn' +
    (_isFollowing ? " agent-detail-pane-btn-on" : "") +
    '" data-action="follow-pane" data-agent="' +
    escapeHtml(a.name) +
    '" title="' +
    (_isFollowing
      ? "Stop live-tail polling"
      : "Poll /detail every " +
        FOLLOW_INTERVAL_MS / 1000 +
        "s for a live-tail feel") +
    '">' +
    (_isFollowing ? "Following" : "Follow") +
    "</button>" +
    '<button type="button" class="agent-detail-pane-btn" ' +
    'data-action="copy-pane" data-agent="' +
    escapeHtml(a.name) +
    '" title="Copy pane text to clipboard">Copy</button>' +
    "</span>";
  // Initial view honors preserved _paneExpanded so heartbeat re-renders
  // don't snap the user back to the short view.
  var _initialView = _isExpanded ? "full" : "short";
  var _initialBody = _isExpanded
    ? paneFull
    : pane ||
      '<span class="muted-cell">No terminal output available (pane_text_source=' +
        paneSource +
        ")</span>";
  var paneHtml =
    '<div class="agent-detail-pane-wrap">' +
    '<div class="agent-detail-pane-label">' +
    paneLabel +
    "</div>" +
    '<pre class="agent-detail-pane" data-agent="' +
    escapeHtml(a.name) +
    '" data-pane-short="' +
    escapeHtml(pane || "") +
    '" data-pane-full="' +
    escapeHtml(paneFull) +
    '" data-pane-view="' +
    _initialView +
    '">' +
    (_isExpanded || pane
      ? escapeHtml(_initialBody)
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
