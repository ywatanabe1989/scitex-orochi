/* Orochi Dashboard -- bootstrap (loaded last) */
/* globals: loadHistory, fetchStats, fetchAgents, connect, fetchTodoList,
   fetchResources, fetchWorkspaces, wsConnected, startRestPolling,
   getSnakeLogo, refreshAgentNames */

/* Inject Orochi logo into sidebar brand */
(function () {
  var brandLogo = document.getElementById("brand-logo");
  if (brandLogo) {
    brandLogo.innerHTML =
      '<img src="/static/hub/orochi-icon.png" alt="Orochi" ' +
      'style="width:100px;height:100px;border-radius:8px;">';
  }
})();

/* Inject workspace icon into sidebar selector */
(function () {
  var wsIconSlot = document.getElementById("ws-icon-slot");
  var wsName = window.__orochiWorkspaceName || "workspace";
  if (wsIconSlot) {
    wsIconSlot.innerHTML = getWorkspaceIcon(wsName, 16);
  }
})();

refreshAgentNames().then(function () {
  loadHistory();
});
fetchAgents();
fetchStats();
connect();
setInterval(fetchStats, 10000);
setInterval(fetchAgents, 10000);
fetchTodoList();
setInterval(fetchTodoList, 60000);
fetchResources();
setInterval(fetchResources, 30000);
fetchWorkspaces();
setInterval(fetchWorkspaces, 30000);
setTimeout(function () {
  if (!wsConnected) {
    console.warn("WebSocket not connected after 3s, starting REST poll");
    startRestPolling();
  }
}, 3000);
