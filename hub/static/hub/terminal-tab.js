/* Web-terminal tab (todo#47).
 *
 * xterm.js front-end for the /ws/terminal/<host>/ WebSocket backend.
 * One terminal instance at a time. Host is chosen from a small picker
 * populated from the known fleet machines (same whitelist the backend
 * enforces — ordering mirrors the Machines tab for operator muscle
 * memory).
 *
 * xterm.js + xterm-addon-fit are loaded lazily from CDN on first tab
 * activation. We don't bundle them because the terminal is a minor
 * tool and pulling ~300kB of JS on every page load for every user
 * would hurt the dashboard cold-start time.
 *
 * globals: activeTab
 */

var _termState = {
  term: null,
  fitAddon: null,
  ws: null,
  host: null,
  loaded: false,
  loadingPromise: null,
};

var TERMINAL_HOSTS = [
  { id: "local", label: "local (hub container)" },
  { id: "mba", label: "mba" },
  { id: "nas", label: "nas" },
  { id: "ywata-note-win", label: "ywata-note-win" },
  { id: "spartan", label: "spartan (HPC)" },
];

function _termLoadAssets() {
  if (_termState.loaded) return Promise.resolve();
  if (_termState.loadingPromise) return _termState.loadingPromise;
  _termState.loadingPromise = new Promise(function (resolve, reject) {
    /* CSS */
    var css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = "https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.min.css";
    document.head.appendChild(css);
    /* xterm.js core */
    var script = document.createElement("script");
    script.src = "https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.min.js";
    script.onload = function () {
      /* fit addon */
      var fit = document.createElement("script");
      fit.src =
        "https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.min.js";
      fit.onload = function () {
        _termState.loaded = true;
        resolve();
      };
      fit.onerror = function () {
        reject(new Error("failed to load xterm-addon-fit"));
      };
      document.head.appendChild(fit);
    };
    script.onerror = function () {
      reject(new Error("failed to load xterm.js"));
    };
    document.head.appendChild(script);
  });
  return _termState.loadingPromise;
}

function _termRenderPicker() {
  var picker = document.getElementById("terminal-host-picker");
  if (!picker) return;
  picker.innerHTML = TERMINAL_HOSTS.map(function (h) {
    return (
      '<button type="button" class="terminal-host-btn" data-host="' +
      h.id +
      '">' +
      h.label +
      "</button>"
    );
  }).join("");
  picker.querySelectorAll(".terminal-host-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      openTerminalForHost(btn.getAttribute("data-host"));
    });
  });
}

function _termStatus(msg, cls) {
  var el = document.getElementById("terminal-status");
  if (!el) return;
  el.textContent = msg || "";
  el.className = "terminal-status" + (cls ? " " + cls : "");
}

function _termCloseExisting() {
  if (_termState.ws) {
    try {
      _termState.ws.close();
    } catch (_) {}
    _termState.ws = null;
  }
  if (_termState.term) {
    try {
      _termState.term.dispose();
    } catch (_) {}
    _termState.term = null;
    _termState.fitAddon = null;
  }
  var container = document.getElementById("terminal-xterm-container");
  if (container) container.innerHTML = "";
}

function openTerminalForHost(host) {
  _termLoadAssets()
    .then(function () {
      _termCloseExisting();
      _termState.host = host;
      var container = document.getElementById("terminal-xterm-container");
      if (!container) return;
      container.style.display = "block";
      /* eslint-disable no-undef */
      var term = new Terminal({
        fontFamily: 'Menlo, Monaco, "Courier New", monospace',
        fontSize: 13,
        theme: { background: "#111", foreground: "#eee" },
        cursorBlink: true,
        scrollback: 5000,
      });
      var fit = new FitAddon.FitAddon();
      /* eslint-enable no-undef */
      term.loadAddon(fit);
      term.open(container);
      _termState.term = term;
      _termState.fitAddon = fit;
      setTimeout(function () {
        try {
          fit.fit();
        } catch (_) {}
      }, 50);

      var proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      var wsUrl =
        proto +
        "//" +
        window.location.host +
        "/ws/terminal/" +
        encodeURIComponent(host) +
        "/";
      _termStatus("connecting to " + host + "...", "connecting");
      var ws = new WebSocket(wsUrl);
      _termState.ws = ws;

      ws.onopen = function () {
        _termStatus("connected: " + host, "ok");
        /* Send initial size */
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
        if (frame.type === "output") {
          term.write(frame.data || "");
        } else if (frame.type === "status") {
          _termStatus(frame.msg || frame.state || "", frame.state);
          if (frame.state === "closed") {
            try {
              ws.close();
            } catch (_) {}
          }
        }
      };
      ws.onclose = function (e) {
        _termStatus(
          "disconnected (code " +
            e.code +
            ")" +
            (e.reason ? ": " + e.reason : ""),
          "closed",
        );
      };
      ws.onerror = function () {
        _termStatus("websocket error", "closed");
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

      window.addEventListener("resize", _termHandleWindowResize);
    })
    .catch(function (err) {
      _termStatus("failed to load terminal: " + (err && err.message), "closed");
    });
}

function _termHandleWindowResize() {
  if (_termState.fitAddon && activeTab === "terminal") {
    try {
      _termState.fitAddon.fit();
    } catch (_) {}
  }
}

function renderTerminalTab() {
  _termRenderPicker();
  /* Re-fit on re-entry so the terminal adapts to the current viewport */
  if (_termState.fitAddon) {
    setTimeout(function () {
      try {
        _termState.fitAddon.fit();
      } catch (_) {}
    }, 50);
  }
}

function stopTerminalTab() {
  /* keep session alive across tab switches; only cleanup on explicit close */
}

document.addEventListener("DOMContentLoaded", function () {
  var closeBtn = document.getElementById("terminal-close-btn");
  if (closeBtn) {
    closeBtn.addEventListener("click", function () {
      _termCloseExisting();
      _termStatus("closed", "closed");
    });
  }
});
