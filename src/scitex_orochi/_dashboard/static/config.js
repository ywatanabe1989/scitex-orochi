/* Dashboard config loader -- fetches /api/config before app.js runs.
 *
 * Sets:
 *   window.__orochiWsUpstream  -- WS URL override (dev -> stable sync)
 *   window.__orochiApiUpstream -- REST URL override (dev -> stable sends)
 *   window.__orochiVersion     -- package version for display
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
        var el = document.getElementById("orochi-version");
        if (el) el.textContent = "v" + cfg.version;
      }
    }
  } catch (e) {
    /* config endpoint unavailable -- use defaults */
  }
})();
