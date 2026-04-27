// @ts-nocheck
import { _renderIndicatorLamps } from "./lamps";
import {
  FOLLOW_INTERVAL_MS,
  _agentDetailCache,
  _fmtDuration,
  _paneExpanded,
  livenessColor,
} from "./state";
import { escapeHtml, isAgentInactive } from "../app/utils";

/* Agents Tab — per-agent detail view + indicator lamps + pane-state badge.
 * Depends on state.js (livenessColor, _fmtDuration, _agentDetailCache,
 * _paneExpanded, (globalThis as any)._followAgent, FOLLOW_INTERVAL_MS). */

/* ── Per-agent detail view ──────────────────────────────────────────── */
/* Merges registry row (`a`) with cached /api/agents/<name>/detail/
 * payload (`d`). The merge is forgiving: either source can be missing
 * a field, and the view always renders something so the user is never
 * staring at an empty panel while the detail call is in flight. */
export function _renderAgentDetail(a) {
  var d = _agentDetailCache[a.name] || {};
  var liveness =
    d.liveness || a.liveness || (isAgentInactive(a) ? "offline" : "online");
  var statusColor = livenessColor(liveness);
  var role = d.role || a.role || "agent";
  var machine = d.machine || a.machine || "?";
  /* todo#56: some transcripts surface <synthetic> / <none> / <compact>
   * placeholder tokens for model when the assistant turn was synthesised
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
  var machineCanonical =
    d.orochi_hostname_canonical || a.orochi_hostname_canonical || "";
  function _fqdnAddsInfo(short, fqdn) {
    if (!fqdn) return false;
    if (fqdn === short) return false;
    var redundantSuffixes = [".local", ".localdomain", ".lan", ".home.arpa"];
    for (var i = 0; i < redundantSuffixes.length; i++) {
      if (fqdn === short + redundantSuffixes[i]) return false;
    }
    return true;
  }
  var machineDisplay = _fqdnAddsInfo(machine, machineCanonical)
    ? machine + " (" + machineCanonical + ")"
    : machine;
  var modelClean = _cleanModel(d.model || a.model || "");
  var ctxPct =
    d.orochi_context_pct != null ? d.orochi_context_pct : a.orochi_context_pct;
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

  var workdir = d.workdir || a.workdir || "";
  var pid = d.pid || a.pid || "";
  var multiplexer = d.multiplexer || a.multiplexer || "";
  var idleSec = d.idle_seconds != null ? d.idle_seconds : a.idle_seconds;
  var lastHeartbeat = d.last_heartbeat || a.last_heartbeat || "";
  var registeredAt = d.registered_at || a.registered_at || "";
  var subagentCount =
    d.orochi_subagent_count != null
      ? d.orochi_subagent_count
      : a.orochi_subagent_count;
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
   * cell reveals the full value (critical for workdir paths that get
   * middle-truncated). */
  var metaFields = [
    ["Role", role, "declared agent role (head / healer / expert-scitex / ...)"],
    [
      "Machine",
      machineDisplay,
      _fqdnAddsInfo(machine, machineCanonical)
        ? "short label · canonical FQDN reported by the heartbeat"
        : machineCanonical
          ? "FQDN is just the short label + redundant mDNS suffix; hidden"
          : "hostname the agent is running on (short label — no FQDN reported)",
    ],
    [
      "Model",
      modelClean.display,
      modelClean.tooltip || "Claude model id the agent is running against",
    ],
    [
      "Multiplexer",
      multiplexer || "-",
      "tmux / screen session hosting the agent process",
    ],
    ["PID", pid || "-", "host-side process id of the claude-code binary"],
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
      "active Agent-tool subagents spawned by this agent",
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
      _smartTruncatePath(workdir, 40) || "-",
      workdir || "(no workdir reported)",
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
  /* msg#16116 Item 4: inline subagent-count chip in the detail header.
   * Visible only when the agent has >=1 active subagent; hidden by the
   * `return ""` branch inside renderAgentSubagentCount when 0. Source:
   * d.orochi_subagent_count (detail endpoint) falling back to a.orochi_subagent_count
   * (registry). Separate from the Subagents meta-field row below — the
   * header chip is an at-a-glance cue so users don't need to scan the
   * meta grid. */
  var headerSubagents =
    typeof (window as any).renderAgentSubagentCount === "function"
      ? (window as any).renderAgentSubagentCount({
          orochi_subagent_count: subagentCount,
        })
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
  var _isFollowing = (globalThis as any)._followAgent === a.name;
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
   * UI shows the controls universally and surfaces errors inline.
   * `dm:` channels are filtered out — DM is always implicitly available
   * between any two agents/users, so listing DM subscriptions per agent
   * just clutters the channels row. (ywatanabe 2026-04-27.) */
  var uniqueSubs = channels
    ? [...new Set(channels)].filter(function (c) {
        return typeof c === "string" && c.indexOf("dm:") !== 0;
      })
    : [];
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

  /* File viewers as tabs (Terminal / CLAUDE.md / .mcp.json) instead of
   * a side-by-side split — each pane gets the full width when active so
   * the agent detail panel respects the viewport instead of stacking
   * two half-width columns into the page (ywatanabe 2026-04-27). */
  var hasMcpJson = !!mcpJson;
  var hasClaudeMd = !!claudeMd;
  var fileTabsHtml =
    '<div class="agent-detail-files-tabs" data-agent="' +
    escapeHtml(a.name) +
    '">' +
    '<div class="agent-detail-files-tabbar" role="tablist">' +
    '<button type="button" class="agent-detail-files-tab agent-detail-files-tab-active"' +
    ' data-action="files-tab" data-pane-id="terminal">Terminal</button>' +
    (hasClaudeMd
      ? '<button type="button" class="agent-detail-files-tab"' +
        ' data-action="files-tab" data-pane-id="claude-md">CLAUDE.md</button>'
      : "") +
    (hasMcpJson
      ? '<button type="button" class="agent-detail-files-tab"' +
        ' data-action="files-tab" data-pane-id="mcp-json">.mcp.json</button>'
      : "") +
    "</div>" +
    '<div class="agent-detail-files-panes">' +
    '<div class="agent-detail-files-pane agent-detail-files-pane-active" data-pane-id="terminal">' +
    paneHtml +
    "</div>" +
    (hasClaudeMd
      ? '<div class="agent-detail-files-pane" data-pane-id="claude-md" hidden>' +
        claudeMdHtml +
        "</div>"
      : "") +
    (hasMcpJson
      ? '<div class="agent-detail-files-pane" data-pane-id="mcp-json" hidden>' +
        mcpJsonBodyHtml +
        "</div>"
      : "") +
    "</div>" +
    "</div>";

  /* Layered state sections (see AGENT_STATES.md):
   *   1. orochi_pane_state v3 — verdict + evidence string + version
   *   2. orochi_comm_state v1 — verdict + evidence + tasks_by_state
   *   3. raw observations    — collapsed JSON viewer for power users
   * Hidden when no data is available so legacy / non-A2A agents stay
   * tidy. */
  var stateHtml = _renderStateSections(a, d);

  return (
    '<div class="agent-detail-view">' +
    headerHtml +
    channelsHtml +
    stateHtml +
    fileTabsHtml +
    mcpHtml +
    "</div>"
  );
}

/* ── Pane / Comm state sections ─────────────────────────────────────── */
function _renderStateSections(a, d) {
  var paneState = d.orochi_pane_state || a.orochi_pane_state || "";
  var paneEvidence = d.orochi_pane_state_evidence || "";
  var paneVersion = d.orochi_pane_state_version || "";
  var paneObs = d.orochi_pane_observations || a.orochi_pane_observations || {};

  var commState = d.orochi_comm_state || "";
  var commEvidence = d.orochi_comm_state_evidence || "";
  var commVersion = d.orochi_comm_state_version || "";
  var a2aObs = d.sac_a2a_observations || {};

  var paneSection = "";
  if (paneState || paneEvidence || (paneObs && Object.keys(paneObs).length)) {
    var paneMarkers = (paneObs && paneObs.busy_marker_hits) || [];
    var paneCycles = (paneObs && paneObs.unchanged_cycles) || 0;
    paneSection =
      '<div class="agent-detail-section agent-detail-state">' +
      '<div class="agent-detail-pane-label">Pane state ' +
      (paneVersion
        ? '<span class="agent-detail-state-ver">' +
          escapeHtml(paneVersion) +
          "</span>"
        : "") +
      "</div>" +
      '<div class="agent-detail-state-row">' +
      '<span class="agent-detail-state-label agent-detail-state-label-' +
      escapeHtml(paneState || "unknown") +
      '">' +
      escapeHtml(paneState || "(no verdict)") +
      "</span>" +
      (paneEvidence
        ? '<span class="agent-detail-state-evidence">' +
          escapeHtml(paneEvidence) +
          "</span>"
        : "") +
      "</div>" +
      (paneObs && Object.keys(paneObs).length
        ? '<div class="agent-detail-state-meta">' +
          (paneCycles
            ? '<span title="cycles since digest changed">unchanged ' +
              paneCycles +
              " cycles</span>"
            : "") +
          (paneMarkers.length
            ? '<span title="busy-animation markers seen">busy: ' +
              escapeHtml(paneMarkers.slice(0, 3).join(", ")) +
              (paneMarkers.length > 3
                ? " (+" + (paneMarkers.length - 3) + ")"
                : "") +
              "</span>"
            : "") +
          "</div>"
        : "") +
      "</div>";
  }

  var commSection = "";
  if (commState || commEvidence || (a2aObs && a2aObs.endpoint_configured)) {
    var byState = (a2aObs && a2aObs.tasks_by_state) || {};
    var byStateKeys = Object.keys(byState);
    var secsSince = a2aObs && a2aObs.seconds_since_most_recent_event;
    commSection =
      '<div class="agent-detail-section agent-detail-state">' +
      '<div class="agent-detail-pane-label">Comm state ' +
      (commVersion
        ? '<span class="agent-detail-state-ver">' +
          escapeHtml(commVersion) +
          "</span>"
        : "") +
      "</div>" +
      '<div class="agent-detail-state-row">' +
      '<span class="agent-detail-state-label agent-detail-state-label-' +
      escapeHtml(commState || "unknown") +
      '">' +
      escapeHtml(commState || "(no verdict)") +
      "</span>" +
      (commEvidence
        ? '<span class="agent-detail-state-evidence">' +
          escapeHtml(commEvidence) +
          "</span>"
        : "") +
      "</div>" +
      '<div class="agent-detail-state-meta">' +
      (byStateKeys.length
        ? '<span title="A2A task histogram">tasks: ' +
          escapeHtml(
            byStateKeys
              .map(function (k) {
                return k.replace(/^TASK_STATE_/, "") + "=" + byState[k];
              })
              .join(", "),
          ) +
          "</span>"
        : "") +
      (typeof secsSince === "number"
        ? '<span title="seconds since most recent A2A event">last event ' +
          Math.round(secsSince) +
          "s ago</span>"
        : "") +
      "</div>" +
      "</div>";
  }

  var rawSection = "";
  if (
    (paneObs && Object.keys(paneObs).length) ||
    (a2aObs && Object.keys(a2aObs).length)
  ) {
    var rawJson = JSON.stringify(
      {
        orochi_pane_observations: paneObs,
        sac_a2a_observations: a2aObs,
      },
      null,
      2,
    );
    rawSection =
      '<div class="agent-detail-section">' +
      '<details class="agent-detail-raw-obs-wrap">' +
      '<summary class="agent-detail-pane-label">Raw observations</summary>' +
      '<pre class="agent-detail-raw-obs">' +
      escapeHtml(rawJson) +
      "</pre>" +
      "</details>" +
      "</div>";
  }

  return paneSection + commSection + rawSection;
}
