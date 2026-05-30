// @ts-nocheck
import { apiUrl, escapeHtml, getAgentColor, getWorkspaceIcon } from "./app/utils";
import { activeTab } from "./tabs";

/* Workspaces Tab -- workspace cards */
/* globals: escapeHtml, getAgentColor, activeTab, apiUrl */

export var workspacesData = [];

export async function fetchWorkspaces() {
  try {
    var res = await fetch(apiUrl("/api/workspaces"));
    if (!res.ok) return;
    workspacesData = await res.json();
    if (activeTab === "workspaces") renderWorkspacesTab();
  } catch (e) {
    console.warn("fetchWorkspaces failed:", e);
  }
}

export function renderWorkspacesTab() {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  var grid = document.getElementById("workspaces-grid");
  if (!workspacesData || workspacesData.length === 0) {
    grid.innerHTML = '<p class="empty-notice">No workspaces configured</p>';
    if (inputHasFocus && document.activeElement !== msgInput) {
      msgInput.focus();
      try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
    }
    return;
  }
  grid.innerHTML = workspacesData.map(buildWorkspaceCard).join("");
  workspacesData.forEach(fetchWorkspaceInvites);
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
  }
}

export function buildWorkspaceCard(ws) {
  var color = getAgentColor(ws.name);
  var channelsHtml = "";
  if (ws.channels && ws.channels.length > 0) {
    channelsHtml =
      '<div class="ws-section">' +
      '<div class="ws-section-label">Channels</div>' +
      '<div class="ws-badges">' +
      ws.channels
        .map(function (ch) {
          return '<span class="ws-channel-badge">' + escapeHtml(ch) + "</span>";
        })
        .join("") +
      "</div></div>";
  }
  var membersHtml = "";
  var memberNames = ws.members ? Object.keys(ws.members) : [];
  if (memberNames.length > 0) {
    membersHtml =
      '<div class="ws-section">' +
      '<div class="ws-section-label">Members (' +
      memberNames.length +
      ")</div>" +
      '<div class="ws-badges">' +
      memberNames
        .map(function (name) {
          var role = ws.members[name];
          var badgeClass = role === "admin" ? "badge-admin" : "badge-member";
          return (
            '<span class="ws-member">' +
            escapeHtml(name) +
            ' <span class="role-badge ' +
            badgeClass +
            '">' +
            escapeHtml(role) +
            "</span></span>"
          );
        })
        .join("") +
      "</div></div>";
  }
  var inviteHtml =
    '<div id="ws-invite-' +
    escapeHtml(ws.id) +
    '" class="ws-invite-status"></div>';
  var wsIcon =
    typeof getWorkspaceIcon === "function" ? getWorkspaceIcon(ws.name, 28) : "";
  return (
    '<div class="res-card">' +
    '<div class="ws-card-header">' +
    '<span class="ws-card-icon">' +
    wsIcon +
    "</span>" +
    '<span class="ws-card-name">' +
    escapeHtml(ws.name) +
    "</span></div>" +
    (ws.description
      ? '<div class="ws-card-desc">' + escapeHtml(ws.description) + "</div>"
      : "") +
    channelsHtml +
    membersHtml +
    inviteHtml +
    "</div>"
  );
}

export function fetchWorkspaceInvites(ws) {
  fetch(apiUrl("/api/workspaces/" + encodeURIComponent(ws.id) + "/invites"))
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
