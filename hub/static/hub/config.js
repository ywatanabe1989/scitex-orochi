/* Dashboard config loader -- fetches /api/config before app.js runs.
 *
 * Sets:
 *   window.__orochiWsUpstream  -- WS URL override (dev -> stable sync)
 *   window.__orochiApiUpstream -- REST URL override (dev -> stable sends)
 *   window.__orochiVersion     -- package orochi_version for display
 *   window.__orochiToken       -- dashboard token for WS + REST auth
 */
(function () {
  var xhr = new XMLHttpRequest();
  xhr.open("GET", "/api/config", false); /* synchronous -- before app.js */
  try {
    xhr.send();
    if (xhr.status === 200) {
      var cfg = JSON.parse(xhr.responseText);
      if (cfg.ws_upstream) {
        window.__orochiWsUpstream = cfg.ws_upstream;
        window.__orochiApiUpstream = cfg.ws_upstream.replace(/\/$/, "");
      }
      /* todo#341/#342/#345: live wall-clock with date next to logo */
      (function _initBrandClock() {
        var clockEl = document.getElementById("brand-clock");
        if (!clockEl) return;
        function _tick() {
          var now = new Date();
          var pad = function (n) { return n < 10 ? "0" + n : "" + n; };
          clockEl.textContent =
            now.getFullYear() + "-" +
            pad(now.getMonth() + 1) + "-" +
            pad(now.getDate()) + " " +
            pad(now.getHours()) + ":" +
            pad(now.getMinutes()) + ":" +
            pad(now.getSeconds());
        }
        _tick();
        setInterval(_tick, 1000);
      })();
      if (cfg.orochi_version) {
        window.__orochiVersion = cfg.orochi_version;
        window.__orochiDeployedAt = cfg.deployed_at || "";
        var el = document.getElementById("orochi-orochi_version");
        if (el) {
          /* Compact: just orochi_version, full build ID in tooltip */
          el.textContent = "v" + cfg.orochi_version;
          if (cfg.build_id) {
            el.title = "build " + cfg.build_id +
              (cfg.deployed_at ? " (" + cfg.deployed_at + ")" : "");
          }
          /* Show "Updated X ago" badge if deploy was within the last hour */
          if (cfg.deployed_at) {
            var deployTime = new Date(cfg.deployed_at).getTime();
            if (!isNaN(deployTime) && Date.now() - deployTime < 3600 * 1000) {
              var badge = document.createElement("span");
              badge.className = "brand-new-badge";
              badge.title = "Deployed " + cfg.deployed_at;
              var updateBadge = function () {
                var diff = Math.floor((Date.now() - deployTime) / 1000);
                if (diff < 0) diff = 0;
                var txt;
                if (diff < 60) txt = "updated " + diff + " sec ago";
                else if (diff < 3600) txt = "updated " + Math.floor(diff / 60) + " min ago";
                else {
                  /* Past 1h — remove the badge */
                  if (badge.parentNode) badge.parentNode.removeChild(badge);
                  return false;
                }
                badge.textContent = txt;
                return true;
              };
              updateBadge();
              el.parentNode.insertBefore(badge, el.nextSibling);
              var badgeTimer = setInterval(function () {
                if (!updateBadge()) clearInterval(badgeTimer);
              }, 10000);
            }
          }
        }
      }
      if (cfg.dashboard_token) {
        window.__orochiToken = cfg.dashboard_token;
      }
      /* Server metadata panel */
      if (cfg.server) {
        window.__orochiServer = cfg.server;
        var infoEl = document.getElementById("server-info");
        if (infoEl) {
          var s = cfg.server;
          var uptimeStr = (function (secs) {
            var d = Math.floor(secs / 86400);
            var h = Math.floor((secs % 86400) / 3600);
            var m = Math.floor((secs % 3600) / 60);
            if (d > 0) return d + "d " + h + "h";
            if (h > 0) return h + "h " + m + "m";
            return m + "m";
          })(s.uptime || 0);
          var lines = [];
          if (s.orochi_hostname)    lines.push('<span class="server-label">Host:</span><span class="server-value">' + s.orochi_hostname + '</span>');
          if (s.external_ip) lines.push('<span class="server-label">IP:</span><span class="server-value">' + s.external_ip + '</span>');
          if (s.orochi_version)     lines.push('<span class="server-label">Ver:</span><span class="server-value">v' + s.orochi_version + '</span>');
          lines.push('<span class="server-label">Up:</span><span class="server-value">' + uptimeStr + '</span>');
          var msgInput = document.getElementById("msg-input");
          var inputHasFocus = msgInput && document.activeElement === msgInput;
          var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
          var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
          infoEl.innerHTML = lines.join("<br>");
          if (inputHasFocus && document.activeElement !== msgInput) {
            msgInput.focus();
            try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
          }
        }
      }
    }
  } catch (e) {
    /* config endpoint unavailable -- use defaults */
  }
})();

/* Auto-reload on new deploy — polls /api/config every 20s and reloads
 * the page (bypassing the service worker) when the server's build_id
 * changes. This removes the "please hard-refresh" step from every
 * deploy: clients pick up new JS/CSS within ~20s of a docker restart. */
(function () {
  var bootstrapBuild = null;
  var poll = function () {
    try {
      var req = new XMLHttpRequest();
      req.open("GET", "/api/config?_=" + Date.now(), true);
      req.onload = function () {
        if (req.status !== 200) return;
        try {
          var cfg = JSON.parse(req.responseText);
          var bid = cfg.build_id || cfg.orochi_version || "";
          if (!bid) return;
          if (bootstrapBuild === null) {
            bootstrapBuild = bid;
            return;
          }
          if (bid !== bootstrapBuild) {
            console.log("[orochi] build changed: " + bootstrapBuild + " → " + bid + " — reloading");
            /* Skip the SW cache on reload */
            if ("serviceWorker" in navigator) {
              navigator.serviceWorker.getRegistrations().then(function (regs) {
                regs.forEach(function (r) { r.update(); });
                location.reload();
              });
            } else {
              location.reload();
            }
          }
        } catch (_) {}
      };
      req.send();
    } catch (_) {}
  };
  /* first run: capture the current build, then poll every 20s */
  setTimeout(poll, 2000);
  setInterval(poll, 20000);
})();
