/* activity-tab/detail-bind.js — detail-pane event wiring:
 * send-to-agent input, Refresh/Copy/Follow/Expand pane controls,
 * SSH terminal lifecycle, follow timer. */

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
  /* SSH — swap the read-only scrollback <pre> for a live xterm
   * connected to this agent's host via /ws/terminal/<host>/. Reuses
   * the lazy asset loader from terminal-tab.js. TODO.md Web Terminal
   * "expected to implement in the Agents List expanded space". */
  grid.querySelectorAll('[data-act-pane-action="ssh"]').forEach(function (btn) {
    btn.addEventListener("click", function (ev) {
      ev.preventDefault();
      var orochi_machine = btn.getAttribute("data-orochi_machine") || "";
      _activityPaneOpenSsh(grid, name, orochi_machine, btn);
    });
  });
}

/* Per-agent terminal singleton — only one SSH session at a time per
 * expanded pane. Kept in a module-level map so switching agents
 * disposes the previous session cleanly. */
var _activityPaneSshState = Object.create(null);

function _activityPaneOpenSsh(grid, name, orochi_machine, btn) {
  var loadAssets = window._termLoadAssets;
  if (typeof loadAssets !== "function") {
    alert("Terminal assets not available.");
    return;
  }
  var pre = grid.querySelector("#agent-detail-pane-content");
  if (!pre) return;
  /* If this pane already has an SSH session, clicking toggles back to
   * the scrollback view. */
  var existing = _activityPaneSshState[name];
  if (existing && existing.host === (orochi_machine || "local")) {
    _activityPaneCloseSsh(name);
    if (btn) {
      btn.classList.remove("agent-detail-pane-btn-on");
      btn.textContent = "SSH";
    }
    return;
  }
  loadAssets()
    .then(function () {
      /* Re-query pre inside .then — the outer reference can be stale
       * if a heartbeat re-rendered the agent-detail-pane between the
       * click and the resolved Promise. */
      var liveGrid = document.querySelector(".activity-grid");
      var livePre =
        (liveGrid && liveGrid.querySelector("#agent-detail-pane-content")) ||
        pre;
      if (!livePre || !livePre.parentNode) return;
      if (!existing) {
        _activityPaneSshState[name] = {
          host: orochi_machine || "local",
          ws: null,
          term: null,
          fitAddon: null,
          originalHtml: livePre.innerHTML,
          originalClass: livePre.className,
          originalTag: "pre",
        };
      }
      var container = document.createElement("div");
      container.className = "agent-detail-ssh-container";
      container.id = "agent-detail-pane-content";
      container.setAttribute("data-agent", name);
      livePre.parentNode.replaceChild(container, livePre);
      /* eslint-disable no-undef */
      var term = new Terminal({
        fontFamily: 'Menlo, Monaco, "Courier New", monospace',
        fontSize: 12,
        theme: { background: "#0d1117", foreground: "#c9d1d9" },
        cursorBlink: true,
        scrollback: 2000,
      });
      var fit = new FitAddon.FitAddon();
      /* eslint-enable no-undef */
      term.loadAddon(fit);
      term.open(container);
      setTimeout(function () {
        try {
          fit.fit();
        } catch (_) {}
      }, 50);
      var proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      var host = orochi_machine || "local";
      var wsUrl =
        proto +
        "//" +
        window.location.host +
        "/ws/terminal/" +
        encodeURIComponent(host) +
        "/";
      var ws = new WebSocket(wsUrl);
      _activityPaneSshState[name].ws = ws;
      _activityPaneSshState[name].term = term;
      _activityPaneSshState[name].fitAddon = fit;
      ws.onopen = function () {
        try {
          ws.send(
            JSON.stringify({
              type: "resize",
              cols: term.cols,
              rows: term.rows,
            }),
          );
        } catch (_) {}
        term.focus();
      };
      ws.onmessage = function (evt) {
        var frame;
        try {
          frame = JSON.parse(evt.data);
        } catch (_) {
          return;
        }
        if (frame.type === "output") term.write(frame.data || "");
        else if (frame.type === "status" && frame.state === "closed") {
          try {
            ws.close();
          } catch (_) {}
        }
      };
      term.onData(function (data) {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "input", data: data }));
        }
      });
      term.onResize(function (sz) {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(
            JSON.stringify({ type: "resize", cols: sz.cols, rows: sz.rows }),
          );
        }
      });
      if (btn) {
        btn.classList.add("agent-detail-pane-btn-on");
        btn.textContent = "Close SSH";
      }
    })
    .catch(function (err) {
      alert("Failed to load terminal: " + (err && err.message));
    });
}

function _activityPaneCloseSsh(name) {
  var s = _activityPaneSshState[name];
  if (!s) return;
  try {
    if (s.ws) s.ws.close();
  } catch (_) {}
  try {
    if (s.term) s.term.dispose();
  } catch (_) {}
  /* Restore the <pre> element so the scrollback view returns. */
  var container = document.getElementById("agent-detail-pane-content");
  if (container && s.originalHtml != null) {
    var pre = document.createElement("pre");
    pre.className = s.originalClass || "agent-detail-pane";
    pre.id = "agent-detail-pane-content";
    pre.setAttribute("data-agent", name);
    pre.innerHTML = s.originalHtml;
    container.parentNode.replaceChild(pre, container);
  }
  delete _activityPaneSshState[name];
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

