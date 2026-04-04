/* Dashboard config loader -- fetches /api/config to override WebSocket URL.
 * When SCITEX_OROCHI_DASHBOARD_WS_UPSTREAM is set on the server,
 * the dashboard connects to that upstream for real-time messages
 * (e.g. dev dashboard observes stable's WebSocket feed).
 *
 * This script sets window.__orochiWsUpstream before app.js runs.
 */
(function () {
  var xhr = new XMLHttpRequest();
  xhr.open("GET", "/api/config", false); /* synchronous -- runs before app.js */
  try {
    xhr.send();
    if (xhr.status === 200) {
      var cfg = JSON.parse(xhr.responseText);
      if (cfg.ws_upstream) {
        window.__orochiWsUpstream = cfg.ws_upstream;
      }
    }
  } catch (e) {
    /* config endpoint unavailable -- use default */
  }
})();
