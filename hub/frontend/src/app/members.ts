// @ts-nocheck
/* ── Channel topic banner + subscriber list (todo#402) ── */
var _channelDescriptions = {}; /* cache: channel → description */
var _agentChannelMap = {}; /* cache: channel → [{name, online}] */
var _channelPrefs =
  {}; /* cache: channel → {is_starred, is_muted, is_hidden, notification_level} */

function _updateChannelTopicBanner(ch) {
  var banner = document.getElementById("channel-topic-banner");
  var textEl = document.getElementById("channel-topic-text");
  var membersEl = document.getElementById("channel-members");
  if (!banner || !textEl) return;
  var desc = _channelDescriptions[ch] || "";
  if (desc) {
    textEl.textContent = desc;
  } else {
    textEl.textContent = "";
  }
  /* Build member pill list */
  if (membersEl) {
    var members = _agentChannelMap[ch] || [];
    if (members.length > 0) {
      membersEl.innerHTML = members
        .map(function (m) {
          var dot = m.online
            ? '<span class="ch-mem-dot ch-mem-online"></span>'
            : '<span class="ch-mem-dot"></span>';
          return (
            '<span class="ch-mem-pill" title="' +
            escapeHtml(m.name) +
            '">' +
            dot +
            escapeHtml(cleanAgentName ? cleanAgentName(m.name) : m.name) +
            "</span>"
          );
        })
        .join("");
      membersEl.style.display = "";
    } else {
      membersEl.style.display = "none";
    }
  }
  /* Members count button — always show for group channels (click to see full list) */
  var membersBtn = document.getElementById("channel-members-btn");
  var membersCountEl = document.getElementById("channel-members-count");
  if (membersBtn && ch && !ch.startsWith("dm:")) {
    /* Show agent pill count if available, otherwise show generic icon */
    var liveCount = membersEl ? membersEl.children.length : 0;
    if (membersCountEl)
      membersCountEl.textContent = liveCount > 0 ? liveCount : "";
    membersBtn.style.display = "";
  } else if (membersBtn) {
    membersBtn.style.display = "none";
  }
  /* Banner visibility: only ever show on the Chat tab, even if a channel
   * is selected. Other tabs (TODO, Agents, Machines, Files, Releases,
   * Settings) share the same #channel-topic-banner element but must not
   * render it — the banner is conceptually a chat-space header, not a
   * global workspace header. See ywatanabe directive 2026-04-18 18:31. */
  var _onChatTab =
    typeof activeTab !== "undefined" ? activeTab === "chat" : true;
  banner.style.display = _onChatTab && (desc || ch) ? "" : "none";
}

/* Channel members panel (todo#407) */
var _membersCache = {}; /* channel → [{username, permission, kind}] */

function toggleMembersPanel() {
  var panel = document.getElementById("channel-members-panel");
  if (!panel) return;
  if (panel.style.display === "none") {
    openMembersPanel(currentChannel || lastActiveChannel);
  } else {
    closeMembersPanel();
  }
}

function openMembersPanel(ch) {
  var panel = document.getElementById("channel-members-panel");
  var list = document.getElementById("ch-members-list");
  var title = document.getElementById("ch-members-panel-title");
  if (!panel || !list) return;
  if (title) title.textContent = (ch || "Channel") + " — Members";
  list.innerHTML = '<div class="ch-members-loading">Loading...</div>';
  panel.style.display = "";

  /* Check cache first */
  if (_membersCache[ch]) {
    _renderMembersPanel(_membersCache[ch]);
    return;
  }

  fetch(apiUrl("/api/channel-members/?channel=" + encodeURIComponent(ch)), {
    credentials: "same-origin",
  })
    .then(function (r) {
      return r.json();
    })
    .then(function (data) {
      _membersCache[ch] = data;
      _renderMembersPanel(data);
    })
    .catch(function () {
      if (list)
        list.innerHTML =
          '<div class="ch-members-loading">Failed to load members.</div>';
    });
}

function _renderMembersPanel(members) {
  var list = document.getElementById("ch-members-list");
  if (!list) return;
  var rw = members.filter(function (m) {
    return m.permission === "read-write";
  });
  var ro = members.filter(function (m) {
    return m.permission === "read-only";
  });
  var html = "";
  if (rw.length > 0) {
    html +=
      '<div class="ch-members-section-label">Read & Write (' +
      rw.length +
      ")</div>";
    html += rw
      .map(function (m) {
        var icon = m.kind === "agent" ? "&#129302;" : "&#128100;";
        return (
          '<div class="ch-members-row">' +
          icon +
          " " +
          escapeHtml(m.username) +
          "</div>"
        );
      })
      .join("");
  }
  if (ro.length > 0) {
    html +=
      '<div class="ch-members-section-label ch-members-ro-label">Read Only (' +
      ro.length +
      ")</div>";
    html += ro
      .map(function (m) {
        var icon = m.kind === "agent" ? "&#129302;" : "&#128100;";
        return (
          '<div class="ch-members-row ch-members-ro">' +
          icon +
          " " +
          escapeHtml(m.username) +
          ' <span class="ch-members-ro-badge">ro</span></div>'
        );
      })
      .join("");
  }
  if (!html) html = '<div class="ch-members-loading">No members found.</div>';
  list.innerHTML = html;
}

function closeMembersPanel() {
  var panel = document.getElementById("channel-members-panel");
  if (panel) panel.style.display = "none";
}
window.toggleMembersPanel = toggleMembersPanel;
window.openMembersPanel = openMembersPanel;
window.closeMembersPanel = closeMembersPanel;

function _rebuildAgentChannelMap(agents) {
  var map = {};
  agents.forEach(function (a) {
    var chs = a.channels || [];
    var online = a.status === "online";
    chs.forEach(function (ch) {
      var norm = ch.charAt(0) === "#" ? ch : "#" + ch;
      if (!map[norm]) map[norm] = [];
      map[norm].push({ name: a.name, online: online });
    });
  });
  _agentChannelMap = map;
  if (currentChannel) _updateChannelTopicBanner(currentChannel);
}

function openChannelTopicEdit() {
  var modal = document.getElementById("channel-topic-modal");
  var inp = document.getElementById("channel-topic-input");
  if (!modal || !inp) return;
  inp.value = _channelDescriptions[currentChannel] || "";
  modal.style.display = "flex";
  setTimeout(function () {
    inp.focus();
  }, 50);
}
window.openChannelTopicEdit = openChannelTopicEdit;

function closeChannelTopicEdit() {
  var modal = document.getElementById("channel-topic-modal");
  if (modal) modal.style.display = "none";
}
window.closeChannelTopicEdit = closeChannelTopicEdit;

function saveChannelTopic() {
  var inp = document.getElementById("channel-topic-input");
  if (!inp || !currentChannel) return;
  var desc = inp.value.trim();
  fetch(apiUrl("/api/channels/"), {
    method: "PATCH",
    headers: Object.assign(
      { "Content-Type": "application/json" },
      orochiHeaders(),
    ),
    body: JSON.stringify({ name: currentChannel, description: desc }),
    credentials: "same-origin",
  })
    .then(function (r) {
      return r.json();
    })
    .then(function () {
      _channelDescriptions[currentChannel] = desc;
      _updateChannelTopicBanner(currentChannel);
      closeChannelTopicEdit();
    })
    .catch(function (e) {
      console.warn("saveChannelTopic error:", e);
    });
}
window.saveChannelTopic = saveChannelTopic;
/* Sync textarea placeholder + composer target with restored channel on page load (#364) */
if (currentChannel) {
  try {
    var _inp = document.getElementById("msg-input");
    if (_inp)
      _inp.placeholder =
        "Message " + currentChannel.replace(/^#/, "#") + "\u2026";
  } catch (_) {}
  document.addEventListener("DOMContentLoaded", function () {
    _updateComposerTarget(currentChannel, false);
  });
}
