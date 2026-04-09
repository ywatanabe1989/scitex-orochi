/* Dashboard config loader -- fetches /api/config before app.js runs.
 *
 * Sets:
 *   window.__orochiWsUpstream  -- WS URL override (dev -> stable sync)
 *   window.__orochiApiUpstream -- REST URL override (dev -> stable sends)
 *   window.__orochiVersion     -- package version for display
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
      if (cfg.version) {
        window.__orochiVersion = cfg.version;
        window.__orochiDeployedAt = cfg.deployed_at || "";
        var el = document.getElementById("orochi-version");
        if (el) {
          /* Compact: just version, full build ID in tooltip */
          el.textContent = "v" + cfg.version;
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
                if (diff < 60) txt = "Updated " + diff + "s ago";
                else if (diff < 3600) txt = "Updated " + Math.floor(diff / 60) + "m ago";
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
    }
  } catch (e) {
    /* config endpoint unavailable -- use defaults */
  }
})();
