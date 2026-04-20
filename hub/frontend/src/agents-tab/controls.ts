// @ts-nocheck
/* Agents Tab — sub-tab bar, content rendering, pane controls,
 * follow-mode polling, and channel-subscription controls.
 * Depends on state.js (selected tab, caches, follow vars) and
 * detail.js (_renderAgentDetail). overview.js calls _buildOverviewHtml
 * which is defined in overview.js — but _renderAgentContent dispatches
 * to it by name, so load order must be: state → detail → controls →
 * overview (overview defines _buildOverviewHtml before any user
 * interaction triggers _renderAgentContent). */

/* ── Sub-tab bar ────────────────────────────────────────────────────── */
function _renderSubTabBar(agents) {
  var tabs = [{ id: "overview", label: "Overview" }];
  agents.forEach(function (a) {
    tabs.push({ id: a.name, label: a.name });
  });
  var html = '<div class="agent-subtab-bar" id="agent-subtab-bar">';
  tabs.forEach(function (t) {
    var active = t.id === _selectedAgentTab ? " agent-subtab-active" : "";
    var inactive =
      t.id !== "overview" &&
      isAgentInactive(
        agents.find(function (a) {
          return a.name === t.id;
        }) || {},
      )
        ? " agent-subtab-offline"
        : "";
    html +=
      '<button class="agent-subtab' +
      active +
      inactive +
      '" ' +
      'data-subtab="' +
      escapeHtml(t.id) +
      '">' +
      escapeHtml(t.label) +
      "</button>";
  });
  html += "</div>";
  return html;
}

function _bindSubTabBar(grid) {
  var bar = grid.querySelector("#agent-subtab-bar");
  if (!bar) return;
  bar.addEventListener("click", function (e) {
    var btn = e.target.closest(".agent-subtab");
    if (!btn) return;
    var nextTab = btn.getAttribute("data-subtab");
    /* todo#47 — any agent switch (including → overview) cancels Follow
     * so we're not polling an agent the user can no longer see. */
    if (_followAgent && _followAgent !== nextTab) {
      _stopFollow();
    }
    _selectedAgentTab = nextTab;
    /* Re-render content area only, not the whole tab (preserve scroll) */
    _renderAgentContent(grid);
  });
}

/* Render only the content area (below tab bar) */
function _renderAgentContent(grid) {
  var content = grid.querySelector("#agent-tab-content");
  if (!content) return;

  /* Update active state on tab bar */
  grid.querySelectorAll(".agent-subtab").forEach(function (btn) {
    btn.classList.toggle(
      "agent-subtab-active",
      btn.getAttribute("data-subtab") === _selectedAgentTab,
    );
  });

  if (_selectedAgentTab === "overview") {
    content.innerHTML = _buildOverviewHtml(_lastAgentsData);
    /* Click an agent card → switch to that agent's sub-tab. Shift-click
     * (or Ctrl/Cmd-click) preserves the legacy filter-tag behaviour. */
    content
      .querySelectorAll(".agent-row[data-agent-name]")
      .forEach(function (el) {
        el.style.cursor = "pointer";
        el.addEventListener("click", function (ev) {
          var name = el.getAttribute("data-agent-name");
          if (ev.shiftKey || ev.ctrlKey || ev.metaKey) {
            if (typeof addTag === "function") addTag("agent", name);
            return;
          }
          _selectedAgentTab = name;
          _renderAgentContent(grid);
        });
      });
    /* Re-apply Ctrl+K fuzzy filter after the innerHTML rewrite — see
     * todo-tab.js rationale. */
    if (typeof runFilter === "function") runFilter();
    return;
  }

  var agent = _lastAgentsData.find(function (a) {
    return a.name === _selectedAgentTab;
  });
  if (!agent) {
    content.innerHTML =
      '<p class="empty-notice">Agent "' +
      escapeHtml(_selectedAgentTab) +
      '" not found.</p>';
    return;
  }
  /* Preserve scrollTop of long, user-scrolled panes across heartbeat-driven
   * re-renders. Without this the CLAUDE.md viewer (and .mcp.json viewer)
   * snaps to the top every poll tick — reported by ywatanabe 2026-04-18
   * 20:45 / 21:02 ("sometimes it automatically scrolls up to the top").
   * Restore is double-applied: synchronously after innerHTML, and again
   * from rAF so the browser has a chance to finish layout on a long
   * <pre> before we set its scroll offset. */
  var _preserveScrollClasses = [
    "agent-detail-claude-md",
    "agent-detail-mcp-json",
  ];
  var _savedScrollTops = {};
  _preserveScrollClasses.forEach(function (cls) {
    var el = content.querySelector("." + cls);
    if (el && el.scrollTop > 0) _savedScrollTops[cls] = el.scrollTop;
  });
  content.innerHTML = _renderAgentDetail(agent);
  var _restoreScroll = function () {
    _preserveScrollClasses.forEach(function (cls) {
      if (_savedScrollTops[cls] != null) {
        var el = content.querySelector("." + cls);
        if (el) el.scrollTop = _savedScrollTops[cls];
      }
    });
  };
  _restoreScroll();
  if (typeof requestAnimationFrame === "function") {
    requestAnimationFrame(_restoreScroll);
  }
  /* Scroll pane to bottom so latest output is visible */
  var pre = content.querySelector(".agent-detail-pane");
  if (pre) pre.scrollTop = pre.scrollHeight;
  /* Kick off an async detail fetch so the next re-render has the
   * redacted pane_text, MCP servers, uptime, etc. The cache shields
   * subsequent renders from flicker. */
  _fetchAgentDetail(agent.name);
  /* Wire the DM quick-action: reuse the existing DM pipeline by
   * dispatching a lightweight custom event the dashboard listens for.
   * Falls back to addTag so even without a global DM opener the user
   * at least gets the agent pre-filtered into the feed. */
  var dmBtn = content.querySelector(".agent-detail-dm-btn");
  if (dmBtn) {
    dmBtn.addEventListener("click", function (ev) {
      ev.stopPropagation();
      var name = dmBtn.getAttribute("data-dm-name");
      try {
        if (typeof window.openDmWithAgent === "function") {
          window.openDmWithAgent(name);
          return;
        }
        document.dispatchEvent(
          new CustomEvent("orochi:open-dm", {
            detail: { agent: name },
          }),
        );
      } catch (_) {}
      if (typeof addTag === "function") addTag("agent", name);
    });
  }

  _bindChannelControls(content);
  _bindPaneControls(content);
}

/* todo#47 — wire Refresh / Copy buttons in the pane viewer. Refresh
 * invalidates the detail cache and re-renders; Copy dumps pane text
 * to the clipboard. Both are scoped per-agent via data-agent on the
 * button itself so there's no ambiguity when multiple agents are
 * stacked in the DOM. */
function _bindPaneControls(content) {
  content
    .querySelectorAll('[data-action="refresh-pane"]')
    .forEach(function (btn) {
      btn.addEventListener("click", function (ev) {
        ev.preventDefault();
        var name = btn.getAttribute("data-agent") || "";
        if (!name) return;
        btn.disabled = true;
        btn.textContent = "Refreshing…";
        _invalidateAgentDetail(name);
        setTimeout(function () {
          btn.disabled = false;
          btn.textContent = "Refresh";
        }, 1500);
      });
    });
  content.querySelectorAll('[data-action="copy-pane"]').forEach(function (btn) {
    btn.addEventListener("click", async function (ev) {
      ev.preventDefault();
      var name = btn.getAttribute("data-agent") || "";
      if (!name) return;
      var pre = content.querySelector(
        '.agent-detail-pane[data-agent="' + name + '"]',
      );
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
  // todo#47 — Expand / Collapse between short and full scrollback.
  // The full pane is stashed on data-pane-full so no network round-
  // trip is needed to toggle. data-pane-view tracks which is shown.
  // State is mirrored into _paneExpanded so heartbeat-driven re-renders
  // don't snap the user back to the short view.
  content
    .querySelectorAll('[data-action="expand-pane"]')
    .forEach(function (btn) {
      btn.addEventListener("click", function (ev) {
        ev.preventDefault();
        var name = btn.getAttribute("data-agent") || "";
        if (!name) return;
        var pre = content.querySelector(
          '.agent-detail-pane[data-agent="' + name + '"]',
        );
        if (!pre) return;
        var view = pre.getAttribute("data-pane-view") || "short";
        if (view === "short") {
          pre.textContent = pre.getAttribute("data-pane-full") || "";
          pre.setAttribute("data-pane-view", "full");
          btn.textContent = "Collapse";
          btn.classList.add("agent-detail-pane-btn-on");
          btn.setAttribute("title", "Show short pane (~10 lines)");
          _paneExpanded[name] = true;
          pre.scrollTop = pre.scrollHeight;
        } else {
          pre.textContent = pre.getAttribute("data-pane-short") || "";
          pre.setAttribute("data-pane-view", "short");
          btn.textContent = "Expand";
          btn.classList.remove("agent-detail-pane-btn-on");
          btn.setAttribute("title", "Show ~500-line scrollback");
          _paneExpanded[name] = false;
        }
      });
    });
  // todo#47 — Follow: poll /detail every FOLLOW_INTERVAL_MS for a
  // live-tail feel. Only one agent can follow at a time; switching
  // agents or toggling off clears the timer. Hidden tab pauses so we
  // don't keep hammering when the dashboard is in a background tab.
  content
    .querySelectorAll('[data-action="follow-pane"]')
    .forEach(function (btn) {
      btn.addEventListener("click", function (ev) {
        ev.preventDefault();
        var name = btn.getAttribute("data-agent") || "";
        if (!name) return;
        if (_followAgent === name) {
          _stopFollow();
        } else {
          _startFollow(name);
        }
      });
    });
}

function _stopFollow() {
  if (_followTimer != null) {
    clearInterval(_followTimer);
    _followTimer = null;
  }
  _followAgent = null;
  document
    .querySelectorAll('[data-action="follow-pane"]')
    .forEach(function (b) {
      b.classList.remove("agent-detail-pane-btn-on");
      b.textContent = "Follow";
      b.setAttribute(
        "title",
        "Poll /detail every " +
          FOLLOW_INTERVAL_MS / 1000 +
          "s for a live-tail feel",
      );
    });
}

function _startFollow(name) {
  _stopFollow();
  _followAgent = name;
  document
    .querySelectorAll('[data-action="follow-pane"][data-agent="' + name + '"]')
    .forEach(function (b) {
      b.classList.add("agent-detail-pane-btn-on");
      b.textContent = "Following";
      b.setAttribute("title", "Stop live-tail polling");
    });
  _followTimer = setInterval(function () {
    if (!_followAgent) return;
    if (typeof document !== "undefined" && document.hidden) return;
    if (_selectedAgentTab !== _followAgent) {
      _stopFollow();
      return;
    }
    _invalidateAgentDetail(_followAgent);
  }, FOLLOW_INTERVAL_MS);
}

/* ── Channel subscription controls (Phase 3) ────────────────────────── */
async function _channelMembersRequest(method, agent, channel) {
  var body = {
    channel: channel,
    username: "agent-" + agent,
  };
  if (method === "POST" || method === "PATCH") {
    body.permission = "read-write";
  }
  var res = await fetch(apiUrl("/api/channel-members/"), {
    method: method,
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": _csrfTokenForChannels(),
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

function _csrfTokenForChannels() {
  var m = document.cookie.match(/csrftoken=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

function _bindChannelControls(content) {
  content.querySelectorAll(".ch-badge-remove").forEach(function (btn) {
    btn.addEventListener("click", async function (ev) {
      ev.stopPropagation();
      var agent = btn.getAttribute("data-agent");
      var channel = btn.getAttribute("data-channel");
      if (!agent || !channel) return;
      if (!confirm("Unsubscribe " + agent + " from " + channel + "?")) return;
      try {
        await _channelMembersRequest("DELETE", agent, channel);
        _invalidateAgentDetail(agent);
      } catch (e) {
        alert("Unsubscribe failed: " + e.message);
      }
    });
  });
  content.querySelectorAll(".ch-add-btn").forEach(function (btn) {
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
        await _channelMembersRequest("POST", agent, channel);
        _invalidateAgentDetail(agent);
      } catch (e) {
        alert("Subscribe failed: " + e.message);
      }
    });
  });
}
