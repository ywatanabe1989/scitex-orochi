/* Direct messages sidebar + new-DM picker (todo#60 PR 4)
 *
 * Renders a "Direct messages" sidebar section below #channels by polling
 * GET /api/dms/. Each row sets currentChannel = "dm:<a>|<b>" on click and
 * routes through the existing loadChannelHistory + draft/filter pipeline.
 *
 * Per spec v3.1 §4.1, agents must use the WS `reply` tool with the
 * dm:<a>|<b> channel name for sending — the REST POST path is not the
 * write path. This module only consumes GET /api/dms/ (list) and
 * POST /api/dms/ (create), never POST /api/messages/ for DMs.
 */
/* globals apiUrl, orochiHeaders, currentChannel, setCurrentChannel,
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

  function dmBadgeHtml(row) {
    var others = (row && row.other_participants) || [];
    if (others.length === 0) return "";
    var t = others[0].type === "agent" ? "agent" : "human";
    var label = t === "agent" ? "AI" : "U";
    return '<span class="dm-principal-badge ' + t + '">' + label + "</span>";
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
            typeof currentChannel !== "undefined" && currentChannel === ch
              ? " active"
              : "";
          return (
            '<div class="dm-item' +
            active +
            '" data-channel="' +
            escapeHtml(ch) +
            '" title="' +
            escapeHtml(ch) +
            '">' +
            dmBadgeHtml(row) +
            escapeHtml(dmDisplayName(row)) +
            "</div>"
          );
        })
        .join("");
      container.querySelectorAll(".dm-item").forEach(function (el) {
        el.addEventListener("click", function () {
          var ch = el.getAttribute("data-channel");
          if (!ch) return;
          /* Mirror the channel-link pattern from chat.js:1547 and the
           * #channels click handler in app.js:920. */
          if (typeof currentChannel !== "undefined" && currentChannel === ch) {
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
