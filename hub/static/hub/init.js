/* Orochi Dashboard -- bootstrap (loaded last) */
/* globals: loadHistory, fetchStats, fetchAgents, connect, fetchTodoList,
   fetchResources, fetchWorkspaces, wsConnected, startRestPolling */

loadHistory();
fetchStats();
fetchAgents();
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
