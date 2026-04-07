/* Dashboard config — reads data attributes from the HTML body set by Django template */
(function () {
  var body = document.body;
  window.__orochiWorkspace = body.dataset.workspace || "default";
  window.__orochiWsUrl = body.dataset.wsUrl || "";
  window.__orochiCsrfToken = body.dataset.csrfToken || "";
})();
