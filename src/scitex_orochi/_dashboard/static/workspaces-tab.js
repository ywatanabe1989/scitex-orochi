/* Workspaces Tab -- workspace cards */
/* globals: escapeHtml, getAgentColor, activeTab */

var workspacesData = [];

async function fetchWorkspaces() {
  try {
    var res = await fetch("/api/workspaces");
    if (!res.ok) return;
    workspacesData = await res.json();
    if (activeTab === "workspaces") renderWorkspacesTab();
  } catch (e) {
    console.warn("fetchWorkspaces failed:", e);
  }
}

function renderWorkspacesTab() {
  var grid = document.getElementById("workspaces-grid");
  if (!workspacesData || workspacesData.length === 0) {
    grid.innerHTML =
      '<p style="color:#555;font-size:13px;">No workspaces configured</p>';
    return;
  }
  grid.innerHTML = workspacesData.map(buildWorkspaceCard).join("");
  workspacesData.forEach(fetchWorkspaceInvites);
}

function buildWorkspaceCard(ws) {
  var color = getAgentColor(ws.name);
  var channelsHtml = "";
  if (ws.channels && ws.channels.length > 0) {
    channelsHtml =
      '<div style="margin-top:6px">' +
      '<div style="color:#8a8aaa;font-size:11px;margin-bottom:3px">Channels</div>' +
      '<div style="display:flex;flex-wrap:wrap;gap:4px">' +
      ws.channels
        .map(function (ch) {
          var chColor = getAgentColor(ch);
          return (
            '<span style="background:' +
            chColor +
            "22;color:" +
            chColor +
            ";padding:2px 8px;border-radius:10px;font-size:11px;" +
            "border:1px solid " +
            chColor +
            '44">' +
            escapeHtml(ch) +
            "</span>"
          );
        })
        .join("") +
      "</div></div>";
  }
  var membersHtml = "";
  var memberNames = ws.members ? Object.keys(ws.members) : [];
  if (memberNames.length > 0) {
    membersHtml =
      '<div style="margin-top:6px">' +
      '<div style="color:#8a8aaa;font-size:11px;margin-bottom:3px">Members (' +
      memberNames.length +
      ")</div>" +
      '<div style="display:flex;flex-wrap:wrap;gap:4px">' +
      memberNames
        .map(function (name) {
          var role = ws.members[name];
          var badgeBg = role === "admin" ? "#ef4444" : "#0f3460";
          return (
            '<span style="font-size:11px;color:#ccc">' +
            escapeHtml(name) +
            ' <span style="background:' +
            badgeBg +
            ";color:#fff;padding:1px 5px;border-radius:8px;" +
            'font-size:9px;font-weight:600">' +
            escapeHtml(role) +
            "</span></span>"
          );
        })
        .join('<span style="color:#2a2a4a;margin:0 2px">&middot;</span>') +
      "</div></div>";
  }
  var inviteHtml =
    '<div id="ws-invite-' +
    escapeHtml(ws.id) +
    '" style="margin-top:6px;color:#666;font-size:11px"></div>';
  return (
    '<div class="res-card" style="border-left:3px solid ' +
    color +
    '">' +
    '<div style="display:flex;align-items:center;gap:6px">' +
    '<span style="color:' +
    color +
    ';font-weight:600;font-size:14px">' +
    escapeHtml(ws.name) +
    "</span></div>" +
    (ws.description
      ? '<div style="color:#888;font-size:12px;margin-top:3px">' +
        escapeHtml(ws.description) +
        "</div>"
      : "") +
    channelsHtml +
    membersHtml +
    inviteHtml +
    "</div>"
  );
}

function fetchWorkspaceInvites(ws) {
  fetch("/api/workspaces/" + encodeURIComponent(ws.id) + "/invites")
    .then(function (res) {
      if (!res.ok) return [];
      return res.json();
    })
    .then(function (invites) {
      var el = document.getElementById("ws-invite-" + ws.id);
      if (el && invites && invites.length > 0) {
        el.textContent = "Invites: " + invites.length + " active";
      } else if (el) {
        el.textContent = "";
      }
    })
    .catch(function () {});
}
