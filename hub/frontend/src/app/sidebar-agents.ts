// @ts-nocheck
import { renderActivityTab } from "../activity-tab/init";
import { _colorKeyFor } from "../activity-tab/state";
import { isAgentAllGreen, renderAgentBadge } from "../agent-badge";
import { agentIdentity, cacheAgentIcons, openAvatarPicker } from "../agent-icons";
import { _addAgentContextMenu } from "./context-menus";
import { _rebuildAgentChannelMap } from "./members";
import { apiUrl, escapeHtml, getAgentColor, hostedAgentName, orochiHeaders } from "./utils";
import { applyFeedFilter } from "../chat/chat-render";
import { runFilter } from "../filter/runner";

/* Sidebar agents + stats fetching */
export async function fetchAgents() {
  try {
    var res = await fetch(apiUrl("/api/agents"));
    var agents = await res.json();
    /* Cache for the Activity tab and other consumers */
    window.__lastAgents = agents;
    /* Rebuild channel→members map for topic banner subscriber list */
    _rebuildAgentChannelMap(agents);
    if (typeof renderActivityTab === "function") renderActivityTab();
    var container = document.getElementById("agents");
    /* Focus guard — see todo#225. This path fires on every WS
     * presence/status event and on REST poll; mobile Safari can blur
     * the compose textarea on large innerHTML swaps. */
    var msgInput = document.getElementById("msg-input");
    var inputHasFocus = msgInput && document.activeElement === msgInput;
    var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
    var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
    if (agents.length === 0) {
      container.innerHTML = '<p id="no-agents">No agents connected</p>';
      var cEl = document.getElementById("sidebar-count-agents");
      if (cEl) cEl.textContent = "";
      if (inputHasFocus && document.activeElement !== msgInput) {
        msgInput.focus();
        try {
          msgInput.setSelectionRange(savedStart, savedEnd);
        } catch (e) {}
      }
      return;
    }
    var cEl = document.getElementById("sidebar-count-agents");
    if (cEl) cEl.textContent = "(" + agents.length + ")";
    agents.forEach(function (a) {
      cacheAgentIcons([a]);
    });
    /* Skip full DOM rebuild if agent data hasn't changed (#225) */
    var newAgentsJson = JSON.stringify(agents);
    if (container._lastAgentsJson === newAgentsJson) return;
    container._lastAgentsJson = newAgentsJson;
    /* Preserve Ctrl+Click multi-select state across re-renders (#274 Part 2).
     * Without this, every fetchAgents() poll/WS presence event clobbers
     * .selected on agent-cards, defeating multi-select. */
    var prevSelectedAgents = {};
    container
      .querySelectorAll(".agent-card.selected[data-agent-name]")
      .forEach(function (el) {
        var n = el.getAttribute("data-agent-name");
        if (n) prevSelectedAgents[n] = true;
      });
    /* todo#320: sidebar agent cards are now compact — name + status
     * dot only. Full detail (badges, kill/pin/restart, task rows,
     * detail popup, health pill, tooltip) lives in the Agents tab. */
    /* Sidebar agent rows mirror the Agents-tab overview one-liner so the
     * two stay visually in sync (ywatanabe 2026-04-19). Same columns:
     *   [pin][ws-led][fn-led][state-badge-compact][name@host]
     * Compact widths so it fits in the ~260px sidebar. Visibility rule
     * matches the overview: offline agents are hidden unless pinned. */
    var connected = function (x) {
      return (x.status || "online") !== "offline";
    };
    var _computeStateLocal = function (a) {
      var pane = a.orochi_pane_state || "";
      if (pane === "compacting" || pane === "auto_compact") return "compacting";
      // auth_error and mcp_broken are functional failures — agent is alive
      // at the network/heartbeat layer but cannot do work. Surface as
      // their own state so the dashboard renders red rather than blending
      // into the yellow "selecting" bucket alongside y_n_prompt.
      if (pane === "auth_error") return "auth_error";
      if (pane === "mcp_broken") return "mcp_broken";
      if (
        pane === "y_n_prompt" ||
        pane === "compose_pending_unsent" ||
        pane === "stuck"
      )
        return "selecting";
      if (!connected(a)) return "offline";
      var lastToolName = String(a.last_tool_name || "").toLowerCase();
      if (lastToolName.indexOf("compact") !== -1) return "compacting";
      var lastToolSec =
        a.last_tool_at || a.last_action
          ? (Date.now() - new Date(a.last_tool_at || a.last_action).getTime()) /
            1000
          : null;
      if (lastToolSec != null && lastToolSec < 30) return "running";
      // Waiting: freshly registered, never recorded a tool call. Derived
      // from hub-side hook events (PreToolUse), NOT pane text scraping —
      // no claude-hud / statusline dependency. last_tool_at is null until
      // the first PreToolUse hook fires, so a connected agent with no
      // tool history is provably "alive but never worked".
      if (lastToolSec == null) return "waiting";
      return "idle";
    };
    var sidebarVisible = agents.filter(function (a) {
      return connected(a) || !!a.pinned;
    });
    /* Starred first (like channels), then apply the sort-dropdown
     * selection (name / machine) within each group. ywatanabe
     * 2026-04-21: "starred agents should be placed upper" +
     * "functionally, no; please make it functional" (sort dropdown
     * must actually sort the sidebar list, not just the Agents tab).
     *
     * todo#305 Task 7 (lead msg#15548): hidden agents (👁 eye off)
     * sort to the BOTTOM, mirroring the sidebar Channels section —
     * channels.firstHiddenIdx is the same pattern. The row stays in
     * the DOM at opacity 1 (no row dim — PR #293/#295 rule) so users
     * can click the eye again to un-hide. */
    var sortBy =
      typeof (globalThis as any)._overviewSort === "string" && (globalThis as any)._overviewSort
        ? (globalThis as any)._overviewSort
        : "name";
    var sortKey = function (a) {
      if (sortBy === "machine") {
        return (a.machine || "") + "\u0001" + (a.name || "");
      }
      /* Default "name" — use the same display-name that renders in the
       * badge so visual order matches what the user reads. */
      var dn =
        typeof hostedAgentName === "function"
          ? hostedAgentName(a)
          : a.name || "";
      return String(dn || "").toLowerCase();
    };
    sidebarVisible.sort(function (a, b) {
      /* Hidden → bottom. Same treatment as channel-prefs.is_hidden
       * sort in sidebar-stats.ts. */
      var ha = a.is_hidden ? 1 : 0;
      var hb = b.is_hidden ? 1 : 0;
      if (ha !== hb) return ha - hb;
      var pa = a.pinned ? 0 : 1;
      var pb = b.pinned ? 0 : 1;
      if (pa !== pb) return pa - pb;
      var ka = sortKey(a);
      var kb = sortKey(b);
      if (ka < kb) return -1;
      if (ka > kb) return 1;
      return 0;
    });
    container.innerHTML = sidebarVisible
      .map(function (a) {
        var liveness = a.liveness || (connected(a) ? "online" : "offline");
        var state = _computeStateLocal(a);
        /* Per ywatanabe 2026-04-21: the whole point of starring is to
         * keep the agent prominently visible; dimming a starred agent
         * contradicts that. Keep starred rows at full opacity even when
         * disconnected. The ghost class only still applies to non-
         * starred rows that are rendered as "shadow" for the other
         * visibility paths — but those don't pass the filter above. */
        var ghostClass = "";
        var rawName = a.name || "";
        /* todo#96: route identity (icon, color, display-name, tooltip)
         * through the shared agentIdentity helper so the sidebar row,
         * Activity pool chip and canvas node all agree. Falls back to
         * the legacy inline derivation when the helper hasn't loaded
         * yet (e.g. during very early bootstrap). */
        var ident =
          typeof agentIdentity === "function"
            ? agentIdentity(a)
            : {
                displayName: hostedAgentName(a),
                color:
                  typeof _colorKeyFor === "function"
                    ? getAgentColor(_colorKeyFor(a))
                    : getAgentColor(a.name),
                tooltip:
                  (a.agent_id || rawName) +
                  " (" +
                  (a.machine || "unknown") +
                  ")",
                iconHtml: function () {
                  return "";
                },
              };
        var chList = Array.isArray(a.channels) ? a.channels.join(",") : "";
        var pinOn = a.pinned ? " activity-pin-on" : "";
        var pinTitle = a.pinned
          ? "Unstar"
          : "Star (keeps as ghost when offline, floats to top)";
        return (
          // Single source of truth — agent-badge.js owns icon + star +
          // eye + 4 LEDs + name. Same call lives in activity-tab.js
          // list view and topology pool chip. NEVER inline a fork here.
          '<div class="agent-card sidebar-agent-row' +
          (typeof isAgentAllGreen === "function" && !isAgentAllGreen(a)
            ? " activity-card-ghost"
            : "") +
          /* todo#305 Task 7: agent-hidden class mirrors .ch-hidden on
           * channel rows. Keeps the row in the DOM at full opacity
           * (PR #293/#295 rule) — only the eye-slash glyph signals
           * hidden state. Class is kept so CSS can add affordances
           * (cursor:pointer, subtle divider above first hidden row)
           * without touching brightness. */
          (a.is_hidden ? " agent-hidden" : "") +
          ghostClass +
          '" data-agent-name="' +
          escapeHtml(rawName) +
          (a.is_hidden ? '" data-hidden="1' : "") +
          '" data-agent-channels="' +
          escapeHtml(chList) +
          '" draggable="true" title="' +
          escapeHtml(ident.tooltip) +
          '">' +
          renderAgentBadge(a, { iconSize: 14 }) +
          "</div>"
        );
      })
      .join("");
    container
      .querySelectorAll(".agent-card[data-agent-name]")
      .forEach(function (el) {
        /* Restore .selected from before re-render (#274 Part 2) */
        var elName = el.getAttribute("data-agent-name");
        if (elName && prevSelectedAgents[elName]) el.classList.add("selected");
        /* todo#49: drag agent card onto a channel to subscribe / unsubscribe. */
        el.addEventListener("dragstart", function (ev) {
          var n = el.getAttribute("data-agent-name") || "";
          var chs = el.getAttribute("data-agent-channels") || "";
          el.classList.add("agent-dragging");
          try {
            ev.dataTransfer.effectAllowed = "link";
            ev.dataTransfer.setData("application/x-orochi-agent", n);
            ev.dataTransfer.setData("text/plain", n);
            /* Carry current subscriptions so the drop handler can render
             * add/remove affordance without an extra fetch. */
            ev.dataTransfer.setData("application/x-orochi-agent-channels", chs);
            /* msg#16988 (a): browser default ghost is often just the
             * text node under the cursor, leaving the drop position
             * invisible. Hand setDragImage a full off-screen clone of
             * the card (bg + border + icon + name) so the user sees
             * exactly what they're moving. The clone is removed on
             * the next microtask — the browser has already rasterised
             * it by the time dragstart returns. */
            var rect = el.getBoundingClientRect();
            var clone = el.cloneNode(true);
            clone.style.position = "absolute";
            clone.style.top = "-10000px";
            clone.style.left = "-10000px";
            clone.style.width = rect.width + "px";
            clone.style.pointerEvents = "none";
            clone.classList.remove("agent-dragging");
            document.body.appendChild(clone);
            var ox = ev.clientX - rect.left;
            var oy = ev.clientY - rect.top;
            ev.dataTransfer.setDragImage(clone, ox, oy);
            setTimeout(function () {
              if (clone.parentNode) clone.parentNode.removeChild(clone);
            }, 0);
          } catch (e) {}
          window.__orochiDragAgent = { name: n, channels: chs };
        });
        el.addEventListener("dragend", function () {
          el.classList.remove("agent-dragging");
          window.__orochiDragAgent = null;
          document
            .querySelectorAll(
              ".channel-item.drop-target-agent-add,.channel-item.drop-target-agent-remove",
            )
            .forEach(function (t) {
              t.classList.remove("drop-target-agent-add");
              t.classList.remove("drop-target-agent-remove");
              var hint = t.querySelector(".ch-hint");
              if (hint) hint.remove();
            });
        });
        el.addEventListener("click", function (ev) {
          if (ev.target.closest(".pin-btn")) return; /* handled separately */
          if (ev.target.closest(".kill-btn")) return; /* handled separately */
          if (ev.target.closest(".restart-btn"))
            return; /* handled separately */
          if (ev.target.closest(".avatar-clickable"))
            return; /* handled below */
          var multi = ev.ctrlKey || ev.metaKey;
          /* todo#274 Part 2: Ctrl/Cmd+Click toggles multi-select. */
          if (multi) {
            el.classList.toggle("selected");
          } else {
            /* todo#274 Part 1: single-select highlight (toggle on 2nd click). */
            var cards = container.querySelectorAll(
              ".agent-card[data-agent-name]",
            );
            var wasSelected = el.classList.contains("selected");
            cards.forEach(function (c) {
              c.classList.remove("selected");
            });
            if (!wasSelected) el.classList.add("selected");
          }
          if (typeof applyFeedFilter === "function") applyFeedFilter();
        });
        /* Right-click: open agent context menu (channel subscribe / DM). */
        _addAgentContextMenu(el);
      });
    container
      .querySelectorAll(".pin-btn[data-pin-name]")
      .forEach(function (btn) {
        btn.addEventListener("click", function (ev) {
          ev.stopPropagation();
          togglePinAgent(
            btn.getAttribute("data-pin-name"),
            !btn.classList.contains("pinned"),
          );
        });
      });
    container
      .querySelectorAll(".avatar-clickable[data-avatar-agent]")
      .forEach(function (el) {
        el.addEventListener("click", function (ev) {
          ev.stopPropagation();
          openAvatarPicker(el.getAttribute("data-avatar-agent"));
        });
      });
    container
      .querySelectorAll(".kill-btn[data-kill-name]")
      .forEach(function (btn) {
        btn.addEventListener("click", function (ev) {
          ev.stopPropagation();
          killAgent(btn.getAttribute("data-kill-name"), btn);
        });
      });
    container
      .querySelectorAll(".restart-btn[data-restart-name]")
      .forEach(function (btn) {
        btn.addEventListener("click", function (ev) {
          ev.stopPropagation();
          restartAgent(btn.getAttribute("data-restart-name"), btn);
        });
      });
    if (inputHasFocus && document.activeElement !== msgInput) {
      msgInput.focus();
      try {
        msgInput.setSelectionRange(savedStart, savedEnd);
      } catch (e) {}
    }
    /* Re-apply sidebar filter after DOM rebuild so display:none isn't lost */
    if (typeof runFilter === "function") runFilter();
  } catch (e) {
    /* fetch error */
  }
}

export async function restartAgent(name, btn) {
  if (!confirm("Restart agent " + name + "?")) return;
  var origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "\u23F3";
  btn.classList.add("restarting");
  try {
    var headers = orochiHeaders();
    var res = await fetch(apiUrl("/api/agents/restart/"), {
      method: "POST",
      headers: headers,
      credentials: "same-origin",
      body: JSON.stringify({ name: name }),
    });
    var data = await res.json();
    if (res.ok) {
      btn.textContent = "\u2713";
      setTimeout(function () {
        btn.textContent = origText;
        btn.disabled = false;
        btn.classList.remove("restarting");
        fetchAgents();
      }, 3000);
    } else {
      btn.textContent = "\u2717";
      console.error("Restart failed:", data.error || res.status);
      setTimeout(function () {
        btn.textContent = origText;
        btn.disabled = false;
        btn.classList.remove("restarting");
      }, 3000);
    }
  } catch (e) {
    console.error("Restart error:", e);
    btn.textContent = origText;
    btn.disabled = false;
    btn.classList.remove("restarting");
  }
}

export async function killAgent(name, btn) {
  if (
    !confirm(
      "Kill agent " +
        name +
        "?\nThis will terminate screen, bun sidecar, and disconnect.",
    )
  )
    return;
  var origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "\u23F3";
  btn.classList.add("killing");
  try {
    var headers = orochiHeaders();
    var res = await fetch(apiUrl("/api/agents/kill/"), {
      method: "POST",
      headers: headers,
      credentials: "same-origin",
      body: JSON.stringify({ name: name }),
    });
    var data = await res.json();
    if (res.ok) {
      btn.textContent = "\u2713";
      setTimeout(function () {
        btn.textContent = origText;
        btn.disabled = false;
        btn.classList.remove("killing");
        fetchAgents();
      }, 2000);
    } else {
      btn.textContent = "\u2717";
      console.error("Kill failed:", data.error || res.status);
      setTimeout(function () {
        btn.textContent = origText;
        btn.disabled = false;
        btn.classList.remove("killing");
      }, 3000);
    }
  } catch (e) {
    console.error("Kill error:", e);
    btn.textContent = origText;
    btn.disabled = false;
    btn.classList.remove("killing");
  }
}

export async function togglePinAgent(name, shouldPin) {
  try {
    var token = window.__orochiCsrfToken || "";
    var headers = { "Content-Type": "application/json" };
    if (token) headers["X-CSRFToken"] = token;
    var method = shouldPin ? "POST" : "DELETE";
    var res = await fetch(apiUrl("/api/agents/pin/"), {
      method: method,
      headers: headers,
      credentials: "same-origin",
      body: JSON.stringify({ name: name }),
    });
    if (res.ok) {
      fetchAgents();
    } else {
      console.error("Pin/unpin failed:", res.status);
    }
  } catch (e) {
    console.error("Pin/unpin error:", e);
  }
}
