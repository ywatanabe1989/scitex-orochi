// @ts-nocheck
import { renderAgentBadge } from "./agent-badge";
import { _setChannelPref } from "./app/channel-prefs";
import { _channelPrefs } from "./app/members";
import { fetchStats } from "./app/sidebar-stats";
import { setCurrentChannel } from "./app/state";
import { apiUrl, escapeHtml } from "./app/utils";
import { loadChannelHistory, loadHistory } from "./chat/chat-history";

/* Direct messages sidebar + new-DM picker (todo#60 PR 4)
 *
 * Renders a "Direct messages" sidebar section below #channels by polling
 * GET /api/dms/. Each row sets (globalThis as any).currentChannel = "dm:<a>|<b>" on click and
 * routes through the existing loadChannelHistory + draft/filter pipeline.
 *
 * Per spec v3.1 §4.1, agents must use the WS `reply` tool with the
 * dm:<a>|<b> channel name for sending — the REST POST path is not the
 * write path. This module only consumes GET /api/dms/ (list) and
 * POST /api/dms/ (create), never POST /api/messages/ for DMs.
 */
/* globals apiUrl, orochiHeaders, (globalThis as any).currentChannel, setCurrentChannel,
   loadChannelHistory, loadHistory, addTag, fetchStats, escapeHtml */

(function () {
  var lastDmJson = "";
  var memberCache = null;
  var agentCache = null;

  function selfPrincipalKey() {
    var u = window.__orochiUserName || "";
    return u ? "human:" + u : "";
  }

  function dmDisplayName(row) {
    var others = (row && row.other_participants) || [];
    if (others.length === 0) return row && row.name ? row.name : "(empty DM)";
    return others
      .map(function (p) {
        return p.identity_name || "?";
      })
      .join(", ");
  }

  /* #284: DM card === Agent card.
   *
   * DM rows render through the shared renderAgentBadge() so markup,
   * CSS classes and icon/star/LEDs/name layout are IDENTICAL to the
   * Agent card. For DMs where the counterparty is a live agent, we
   * pick up its record from window.__lastAgents so real liveness LEDs
   * light up. For human-to-human DMs, we synthesise a minimal agent-
   * shaped object keyed off the human's name — the same badge renders
   * with all LEDs off/unknown (humans don't have a WS/ping/pane/echo
   * signal) and the star/name columns line up with the agent sidebar.
   *
   * Returns a plain object shaped like an agent-registry row. Never
   * forks the markup — see agent-badge.ts renderAgentBadge. */
  function dmCounterpartyAgentLike(row) {
    var others = (row && row.other_participants) || [];
    /* Empty DM (no counterparty yet): fall back to the channel key as
     * name so at least the row shows something stable. */
    if (others.length === 0) {
      return {
        name: row && row.name ? row.name : "(empty DM)",
        status: "offline",
        liveness: "offline",
      };
    }
    /* Collapse multi-participant DMs to the first counterparty so we
     * always render one badge. The remaining names still appear in the
     * fallback label via the data-channel tooltip. */
    var p = others[0];
    var label = (p && p.identity_name) || "?";
    /* Agent principal: look up the live record so LEDs reflect truth. */
    if (p && p.type === "agent") {
      var live = Array.isArray(window.__lastAgents) ? window.__lastAgents : [];
      var match = null;
      for (var i = 0; i < live.length; i++) {
        var a = live[i];
        if (!a || !a.name) continue;
        var bare = String(a.name).split("@")[0];
        if (bare === label || a.name === label) {
          match = a;
          break;
        }
      }
      if (match) return match;
      /* Agent is listed in the DM but not currently in __lastAgents
       * (offline / not yet registered) — synth an offline-agent-like
       * record so the badge still renders. */
      return {
        name: label,
        status: "offline",
        liveness: "offline",
        machine: (p && p.machine) || "",
      };
    }
    /* Human principal: synthesise a minimal agent-shape object. All
     * LEDs render grey/off because there's no WS/ping/pane/echo signal
     * for humans. Star + icon + name layout match the agent card. */
    return {
      name: label,
      status: "offline",
      liveness: "offline",
      /* Keep the type hint so CSS can style humans differently if it
       * ever needs to (today it does not — identity is identical). */
      _dm_counterparty_type: "human",
    };
  }

  function renderDms(rows) {
    var container = document.getElementById("dms");
    if (!container) return;
    if (!rows || rows.length === 0) {
      container.innerHTML = '<div class="dm-empty">No direct messages</div>';
    } else {
      container.innerHTML = rows
        .map(function (row) {
          var ch = row.name;
          var active =
            typeof (globalThis as any).currentChannel !== "undefined" && (globalThis as any).currentChannel === ch
              ? " active"
              : "";
          /* Reuse the same _channelPrefs lookup the channels section uses so
           * pin/mute state is shared between the Channels and DM sidebars. */
          var prefs =
            (typeof _channelPrefs !== "undefined" && _channelPrefs[ch]) || {};
          var muted = !!prefs.is_muted;
          var pinned = !!prefs.is_starred;
          var counterparty = dmCounterpartyAgentLike(row);
          /* Override .pinned so the star glyph reflects the DM-channel's
           * is_starred pref rather than the underlying agent's own pin
           * state — DMs are pinned on the conversation, not on the agent. */
          var cpWithDmPin = {};
          for (var k in counterparty)
            if (Object.prototype.hasOwnProperty.call(counterparty, k))
              cpWithDmPin[k] = counterparty[k];
          cpWithDmPin.pinned = pinned;
          /* DM card shares the .agent-card markup + class so CSS rules
           * (hover, selected, drag affordances) apply uniformly across
           * the Agent sidebar and the DM sidebar. .dm-item is retained
           * as an extra hook for DM-specific behaviours (the per-row
           * click handler attaches by that class); markup underneath
           * is rendered by renderAgentBadge exactly as on the Agents
           * sidebar. */
          return (
            '<div class="dm-item agent-card' +
            active +
            (muted ? " ch-muted" : "") +
            '" data-channel="' +
            escapeHtml(ch) +
            '" data-agent-name="' +
            escapeHtml(counterparty.name || "") +
            '" title="' +
            escapeHtml(ch) +
            '">' +
            (typeof renderAgentBadge === "function"
              ? renderAgentBadge(cpWithDmPin, { iconSize: 14 })
              : escapeHtml(dmDisplayName(row))) +
            "</div>"
          );
        })
        .join("");
      container.querySelectorAll(".dm-item").forEach(function (el) {
        /* Star inside the shared agent-badge markup — override the
         * default agent-pin behaviour so clicking the star on a DM row
         * toggles is_starred on the CHANNEL pref (pin the conversation)
         * rather than pin-to-top the underlying agent. Uses the .dm-item
         * row's data-channel, not the button's own data-pin-name which
         * points at the counterparty agent. Runs on capture phase so we
         * beat the global agent-pin handler wired elsewhere. */
        var starEl = el.querySelector(".agent-badge-star");
        if (starEl && typeof _setChannelPref === "function") {
          starEl.addEventListener(
            "click",
            function (ev) {
              ev.stopPropagation();
              ev.preventDefault();
              var chName = el.getAttribute("data-channel");
              if (!chName) return;
              var pref =
                (typeof _channelPrefs !== "undefined" &&
                  _channelPrefs[chName]) ||
                {};
              _setChannelPref(chName, { is_starred: !pref.is_starred });
            },
            true,
          );
        }
        el.addEventListener("click", function (ev) {
          /* Don't treat star / avatar clicks as row-clicks. */
          if (
            ev.target.closest(".agent-badge-star") ||
            ev.target.closest(".avatar-clickable")
          )
            return;
          var ch = el.getAttribute("data-channel");
          if (!ch) return;
          /* Mirror the channel-link pattern from chat.js:1547 and the
           * #channels click handler in app.js:920. */
          if (typeof (globalThis as any).currentChannel !== "undefined" && (globalThis as any).currentChannel === ch) {
            if (typeof setCurrentChannel === "function")
              setCurrentChannel(null);
            if (typeof loadHistory === "function") loadHistory();
          } else {
            if (typeof setCurrentChannel === "function") setCurrentChannel(ch);
            if (typeof loadChannelHistory === "function")
              loadChannelHistory(ch);
          }
          /* Do NOT push a channel:<raw-dm-name> filter tag — DM routing
           * already goes through setCurrentChannel() above, and the raw
           * "dm:agent:X|human:Y" string surfaced in a filter chip is
           * unreadable (msg 082849 screenshot). */
          fetchDms();
          if (typeof fetchStats === "function") fetchStats();
        });
      });
    }
    var countEl = document.getElementById("sidebar-count-dms");
    if (countEl) countEl.textContent = "(" + (rows ? rows.length : 0) + ")";
  }

  async function fetchDms() {
    try {
      var res = await fetch(apiUrl("/api/dms/"), {
        credentials: "same-origin",
      });
      if (!res.ok) {
        /* 401/403/404 — silently render empty so we don't pollute the UI */
        if (res.status === 404 || res.status === 401 || res.status === 403) {
          renderDms([]);
        }
        return;
      }
      var data = await res.json();
      var rows = (data && data.dms) || [];
      var json = JSON.stringify(rows);
      if (json === lastDmJson) return;
      lastDmJson = json;
      renderDms(rows);
    } catch (e) {
      /* network error — leave UI alone */
    }
  }
  window.fetchDms = fetchDms;

  /* ---------------- New-DM picker modal ---------------- */

  async function loadCandidates() {
    var candidates = [];
    var selfKey = selfPrincipalKey();
    var seen = {};
    /* Humans via /api/members/ */
    try {
      if (memberCache === null) {
        var r1 = await fetch(apiUrl("/api/members/"), {
          credentials: "same-origin",
        });
        memberCache = r1.ok ? await r1.json() : [];
      }
      (memberCache || []).forEach(function (m) {
        var name = m && m.username;
        if (!name) return;
        var key, label, type;
        if (name.indexOf("agent-") === 0) {
          type = "agent";
          label = name.slice("agent-".length);
          key = "agent:" + label;
        } else {
          type = "human";
          label = name;
          key = "human:" + name;
        }
        if (key === selfKey) return;
        if (seen[key]) return;
        seen[key] = true;
        candidates.push({ key: key, label: label, type: type });
      });
    } catch (_) {}
    /* Live agents via /api/agents to surface ones not yet in members table */
    try {
      if (agentCache === null) {
        var r2 = await fetch(apiUrl("/api/agents"), {
          credentials: "same-origin",
        });
        agentCache = r2.ok ? await r2.json() : [];
      }
      (agentCache || []).forEach(function (a) {
        var n = a && a.name ? String(a.name).split("@")[0] : "";
        if (!n) return;
        var key = "agent:" + n;
        if (seen[key]) return;
        seen[key] = true;
        candidates.push({ key: key, label: n, type: "agent" });
      });
    } catch (_) {}
    candidates.sort(function (a, b) {
      return a.label.localeCompare(b.label);
    });
    return candidates;
  }

  function renderPickerResults(candidates, query) {
    var container = document.getElementById("new-dm-results");
    if (!container) return;
    var q = (query || "").toLowerCase();
    var filtered = candidates.filter(function (c) {
      if (!q) return true;
      return c.label.toLowerCase().indexOf(q) !== -1;
    });
    if (filtered.length === 0) {
      container.innerHTML = '<div class="dm-modal-empty">No matches</div>';
      return;
    }
    container.innerHTML = filtered
      .map(function (c) {
        var badge =
          '<span class="dm-principal-badge ' +
          c.type +
          '">' +
          (c.type === "agent" ? "AI" : "U") +
          "</span>";
        return (
          '<div class="dm-modal-result" data-key="' +
          escapeHtml(c.key) +
          '">' +
          badge +
          escapeHtml(c.label) +
          "</div>"
        );
      })
      .join("");
    container.querySelectorAll(".dm-modal-result").forEach(function (el) {
      el.addEventListener("click", function () {
        var key = el.getAttribute("data-key");
        if (key) openDmWith(key);
      });
    });
  }

  async function openDmWith(principalKey) {
    try {
      var headers = { "Content-Type": "application/json" };
      var token = window.__orochiCsrfToken || "";
      if (token) headers["X-CSRFToken"] = token;
      var res = await fetch(apiUrl("/api/dms/"), {
        method: "POST",
        headers: headers,
        credentials: "same-origin",
        body: JSON.stringify({ recipient: principalKey }),
      });
      if (!res.ok) {
        var t = await res.text();
        console.error("Create DM failed:", res.status, t);
        return;
      }
      var row = await res.json();
      closeModal();
      lastDmJson = "";
      await fetchDms();
      var ch = row && row.name;
      if (ch) {
        if (typeof setCurrentChannel === "function") setCurrentChannel(ch);
        if (typeof loadChannelHistory === "function") loadChannelHistory(ch);
        /* Intentionally no addTag("channel", ch) — see click handler above. */
        if (typeof fetchStats === "function") fetchStats();
      }
    } catch (e) {
      console.error("openDmWith error:", e);
    }
  }

  function openModal() {
    var modal = document.getElementById("new-dm-modal");
    if (!modal) return;
    modal.hidden = false;
    var search = document.getElementById("new-dm-search");
    if (search) {
      search.value = "";
      search.focus();
    }
    /* Force refresh on open so newly-onboarded members appear. */
    memberCache = null;
    agentCache = null;
    loadCandidates().then(function (cands) {
      renderPickerResults(cands, "");
      if (search) {
        search.oninput = function () {
          renderPickerResults(cands, search.value);
        };
      }
    });
  }

  function closeModal() {
    var modal = document.getElementById("new-dm-modal");
    if (modal) modal.hidden = true;
  }

  function wireModal() {
    var btn = document.getElementById("new-dm-btn");
    if (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        openModal();
      });
    }
    var close = document.getElementById("new-dm-close");
    if (close) close.addEventListener("click", closeModal);
    var modal = document.getElementById("new-dm-modal");
    if (modal) {
      var bd = modal.querySelector(".dm-modal-backdrop");
      if (bd) bd.addEventListener("click", closeModal);
    }
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeModal();
      /* Focus trap for a11y (#262) */
      if (e.key === "Tab" && modal && !modal.hidden) {
        var focusable = modal.querySelectorAll(
          'input, button, [tabindex]:not([tabindex="-1"])',
        );
        if (focusable.length === 0) return;
        var first = focusable[0];
        var last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    });
  }

  function init() {
    wireModal();
    fetchDms();
    setInterval(fetchDms, 10000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

// Auto-generated module re-exports for symbols assigned to `window`
// inside the file-level IIFE above. These run after the IIFE's side
// effects so other ES modules can import these names instead of
// reaching into `window`.
export const fetchDms = (window as any).fetchDms;
