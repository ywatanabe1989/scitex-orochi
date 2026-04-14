/* Orochi Dashboard -- core globals, WS connection, sidebar (Django hub) */

/* System error banner — shown at top of page for critical errors */
function showSystemBanner(message, level) {
  var existing = document.getElementById("system-banner");
  if (existing) existing.remove();
  var banner = document.createElement("div");
  banner.id = "system-banner";
  banner.textContent = message;
  banner.style.cssText =
    "position:fixed;top:0;left:0;right:0;z-index:9999;padding:12px 20px;" +
    "text-align:center;font-weight:bold;font-size:14px;" +
    (level === "error"
      ? "background:#d32f2f;color:#fff;"
      : "background:#f57c00;color:#fff;");
  var close = document.createElement("span");
  close.textContent = " ✕";
  close.style.cssText = "cursor:pointer;margin-left:16px;";
  close.onclick = function () {
    banner.remove();
  };
  banner.appendChild(close);
  document.body.prepend(banner);
}

/* Yamata no Orochi color palette (from mascot icon heads) */
var OROCHI_COLORS = [
  "#C4A6E8",
  "#7EC8E3",
  "#FF9B9B",
  "#A8E6A3",
  "#FFD93D",
  "#FFB374",
  "#B8D4E3",
  "#E8A6C8",
];
/* Restored from localStorage on every page load so that ywatanabe stays
 * in the channel they were viewing across deploys, WS reconnects, and
 * any other re-render cascade. Persisted on every channel switch in
 * setCurrentChannel(). null = unfiltered (show all channels) which is
 * also persisted as the literal string "__all__". todo#246 / msg 6090. */
var currentChannel = null;
/* lastActiveChannel: the most recently single-selected channel.
 * Used as posting target when multi-select is active (currentChannel=null). */
var lastActiveChannel = null;
try {
  var _persistedCh = localStorage.getItem("orochi_active_channel");
  if (_persistedCh && _persistedCh !== "__all__") {
    currentChannel = _persistedCh;
    lastActiveChannel = _persistedCh;
  }
} catch (_) {}
function setCurrentChannel(ch) {
  currentChannel = ch;
  if (ch) lastActiveChannel = ch;
  try {
    localStorage.setItem("orochi_active_channel", ch == null ? "__all__" : ch);
  } catch (_) {}
  /* Update textarea placeholder to show active channel — msg#9368.
   * In multi-select mode (ch=null), keep showing the last active channel
   * so the user knows where their message will be posted (#9694). */
  try {
    var inp = document.getElementById("msg-input");
    if (inp) {
      var targetCh = ch || lastActiveChannel;
      inp.placeholder = targetCh
        ? "Message #" + targetCh.replace(/^#/, "") + "\u2026"
        : "Type a message\u2026";
    }
  } catch (_) {}
  /* Update composer target indicator (todo#364) */
  _updateComposerTarget(ch || lastActiveChannel, false);
  /* Update channel topic banner (todo#402) — show for active channel,
   * or last active when in all-channels mode */
  _updateChannelTopicBanner(ch || lastActiveChannel);
}

function _updateComposerTarget(ch, isReply, replyMsgId) {
  try {
    var el = document.getElementById("composer-target");
    var nameEl = document.getElementById("composer-target-name");
    if (!el || !nameEl) return;
    el.classList.remove("is-dm", "is-reply");
    if (isReply && replyMsgId) {
      el.classList.add("is-reply");
      nameEl.textContent = "\u21b3 reply in " + (ch || "#?") + " \u00b7 msg#" + replyMsgId;
      el.firstChild.nodeValue = "";
    } else if (ch && ch.startsWith("dm:")) {
      el.classList.add("is-dm");
      var parts = ch.replace("dm:", "").split("|");
      nameEl.textContent = "\u2192 @" + (parts[1] || parts[0]) + " (DM)";
      el.firstChild.nodeValue = "";
    } else {
      nameEl.textContent = ch || "#general";
      el.firstChild.nodeValue = "\u2192 ";
    }
  } catch (_) {}
}
window._updateComposerTarget = _updateComposerTarget;
window.setCurrentChannel = setCurrentChannel;

/* ── Channel topic banner + subscriber list (todo#402) ── */
var _channelDescriptions = {}; /* cache: channel → description */
var _agentChannelMap = {};     /* cache: channel → [{name, online}] */
var _channelPrefs = {};        /* cache: channel → {is_starred, is_muted, is_hidden, notification_level} */

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
      membersEl.innerHTML = members.map(function (m) {
        var dot = m.online
          ? '<span class="ch-mem-dot ch-mem-online"></span>'
          : '<span class="ch-mem-dot"></span>';
        return '<span class="ch-mem-pill" title="' + escapeHtml(m.name) + '">' +
          dot + escapeHtml(cleanAgentName ? cleanAgentName(m.name) : m.name) + '</span>';
      }).join("");
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
    if (membersCountEl) membersCountEl.textContent = liveCount > 0 ? liveCount : "";
    membersBtn.style.display = "";
  } else if (membersBtn) {
    membersBtn.style.display = "none";
  }
  banner.style.display = (desc || ch) ? "" : "none";
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

  fetch(apiUrl("/api/channel-members/?channel=" + encodeURIComponent(ch)), { credentials: "same-origin" })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      _membersCache[ch] = data;
      _renderMembersPanel(data);
    })
    .catch(function () {
      if (list) list.innerHTML = '<div class="ch-members-loading">Failed to load members.</div>';
    });
}

function _renderMembersPanel(members) {
  var list = document.getElementById("ch-members-list");
  if (!list) return;
  var rw = members.filter(function (m) { return m.permission === "read-write"; });
  var ro = members.filter(function (m) { return m.permission === "read-only"; });
  var html = "";
  if (rw.length > 0) {
    html += '<div class="ch-members-section-label">Read & Write (' + rw.length + ')</div>';
    html += rw.map(function (m) {
      var icon = m.kind === "agent" ? "&#129302;" : "&#128100;";
      return '<div class="ch-members-row">' + icon + ' ' + escapeHtml(m.username) + '</div>';
    }).join("");
  }
  if (ro.length > 0) {
    html += '<div class="ch-members-section-label ch-members-ro-label">Read Only (' + ro.length + ')</div>';
    html += ro.map(function (m) {
      var icon = m.kind === "agent" ? "&#129302;" : "&#128100;";
      return '<div class="ch-members-row ch-members-ro">' + icon + ' ' + escapeHtml(m.username) + ' <span class="ch-members-ro-badge">ro</span></div>';
    }).join("");
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
  setTimeout(function () { inp.focus(); }, 50);
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
    headers: Object.assign({ "Content-Type": "application/json" }, orochiHeaders()),
    body: JSON.stringify({ name: currentChannel, description: desc }),
    credentials: "same-origin",
  })
    .then(function (r) { return r.json(); })
    .then(function () {
      _channelDescriptions[currentChannel] = desc;
      _updateChannelTopicBanner(currentChannel);
      closeChannelTopicEdit();
    })
    .catch(function (e) { console.warn("saveChannelTopic error:", e); });
}
window.saveChannelTopic = saveChannelTopic;
/* Sync textarea placeholder + composer target with restored channel on page load (#364) */
if (currentChannel) {
  try {
    var _inp = document.getElementById("msg-input");
    if (_inp) _inp.placeholder = "Message " + currentChannel.replace(/^#/, "#") + "\u2026";
  } catch (_) {}
  document.addEventListener("DOMContentLoaded", function () {
    _updateComposerTarget(currentChannel, false);
  });
}

/* Fetch channel descriptions + prefs once on load */
document.addEventListener("DOMContentLoaded", function () {
  fetch(apiUrl("/api/channels/"), { credentials: "same-origin" })
    .then(function (r) { return r.json(); })
    .then(function (list) {
      list.forEach(function (ch) {
        if (ch.name) {
          if (ch.description) _channelDescriptions[ch.name] = ch.description;
          _channelPrefs[ch.name] = {
            is_starred: ch.is_starred || false,
            is_muted: ch.is_muted || false,
            is_hidden: ch.is_hidden || false,
            notification_level: ch.notification_level || "all",
          };
        }
      });
      if (currentChannel) _updateChannelTopicBanner(currentChannel);
      /* Re-render channel list now that prefs are loaded (starred channels sorted first).
       * Bust the stats cache so fetchStats doesn't skip the re-render. */
      var chContainer = document.getElementById("channels");
      if (chContainer) chContainer._lastStatsJson = null;
      if (typeof fetchStats === "function") fetchStats();
    })
    .catch(function (_) {});
});

/* Update a single channel pref on the server and update local cache */
function _setChannelPref(ch, patch) {
  /* Normalize channel name so starring via icon (norm "#foo") and via
   * context menu (raw "foo") both hit the same cache entry. */
  var normCh = ch.charAt(0) === "#" ? ch : "#" + ch;
  Object.assign(_channelPrefs[normCh] = _channelPrefs[normCh] || {}, patch);
  if (normCh !== ch) {
    /* mirror for legacy lookups */
    Object.assign(_channelPrefs[ch] = _channelPrefs[ch] || {}, patch);
  }
  fetch(apiUrl("/api/channel-prefs/"), {
    method: "PATCH",
    credentials: "same-origin",
    headers: {"Content-Type": "application/json", "X-CSRFToken": getCsrfToken()},
    body: JSON.stringify(Object.assign({channel: normCh}, patch)),
  }).catch(function (_) {});
  /* Optimistic UI: re-render immediately from local cache instead of waiting
   * for a server round-trip (ywatanabe msg#10552/10586 — todo#416 Bug 3).
   * Rationale: fetchStats cache-bust worked in theory but the server
   * /api/stats response (channel name list) is UNCHANGED when only prefs
   * flip, so the early-return in fetchStats still fires via a different
   * throttle path. Render directly from _channelPrefs. */
  var cc = document.getElementById("channels");
  if (cc) cc._lastStatsJson = null;
  if (typeof _renderStarredSection === "function") _renderStarredSection();
  /* Force a re-render by invalidating the stats cache and calling fetchStats
   * — also re-render the channel list in place for immediate feedback if the
   * row DOM exists. */
  if (cc) {
    cc.querySelectorAll(".channel-item").forEach(function (el) {
      var elCh = el.getAttribute("data-channel");
      if (!elCh) return;
      var elNorm = elCh.charAt(0) === "#" ? elCh : "#" + elCh;
      if (elNorm !== normCh) return;
      var pref = _channelPrefs[elNorm] || _channelPrefs[elCh] || {};
      var starEl = el.querySelector(".ch-star");
      if (starEl) {
        starEl.classList.toggle("ch-star-on", !!pref.is_starred);
        starEl.classList.toggle("ch-star-off", !pref.is_starred);
        starEl.setAttribute("title", pref.is_starred ? "Unstar" : "Star");
      }
      el.classList.toggle("ch-starred", !!pref.is_starred);
      el.classList.toggle("ch-muted", !!pref.is_muted);
    });
  }
  fetchStats();
}

/* Render the Starred section in the sidebar */
/* Sort starred list by sort_order (then alpha as tiebreaker) */
function _sortedStarred() {
  return Object.keys(_channelPrefs).filter(function (ch) {
    return _channelPrefs[ch] && _channelPrefs[ch].is_starred;
  }).sort(function (a, b) {
    var oa = _channelPrefs[a] ? (_channelPrefs[a].sort_order || 0) : 0;
    var ob = _channelPrefs[b] ? (_channelPrefs[b].sort_order || 0) : 0;
    return oa !== ob ? oa - ob : a.localeCompare(b);
  });
}

function _renderStarredSection() {
  var heading = document.getElementById("starred-heading");
  var container = document.getElementById("starred-channels");
  if (!heading || !container) return;
  var starred = _sortedStarred();
  if (starred.length === 0) {
    heading.style.display = "none";
    container.style.display = "none";
    return;
  }
  heading.style.display = "";
  container.style.display = "";
  var countEl = document.getElementById("sidebar-count-starred");
  if (countEl) countEl.textContent = starred.length;
  container.innerHTML = starred.map(function (ch) {
    var active = currentChannel === ch ? " active" : "";
    var muted = (_channelPrefs[ch] && _channelPrefs[ch].is_muted) ? " ch-muted" : "";
    var unread = channelUnread[ch] || 0;
    var badgeHtml = '<span class="ch-badge-slot">' +
      (unread > 0 ? '<span class="unread-badge">' + (unread > 99 ? "99+" : unread) + '</span>' : '') +
      '</span>';
    return '<div class="channel-item starred-item' + active + muted + '" data-channel="' + escapeHtml(ch) + '" draggable="true">' +
      '<span class="ch-drag-handle" title="Drag to reorder">&#8942;</span>' +
      '<span class="ch-star ch-star-on" data-ch="' + escapeHtml(ch) + '" title="Unstar">&#9733;</span>' +
      '<span class="ch-name">' + escapeHtml(ch) + '</span>' +
      badgeHtml +
      '</div>';
  }).join("");
  container.querySelectorAll(".channel-item").forEach(function (el) {
    el.addEventListener("click", function (ev) {
      if (ev.target.classList.contains("ch-star") || ev.target.classList.contains("ch-drag-handle")) return;
      var ch = el.getAttribute("data-channel");
      setCurrentChannel(ch);
      loadChannelHistory(ch);
      if (typeof applyFeedFilter === "function") applyFeedFilter();
    });
    var star = el.querySelector(".ch-star");
    if (star) star.addEventListener("click", function (ev) {
      ev.stopPropagation();
      var ch = star.getAttribute("data-ch");
      _setChannelPref(ch, {is_starred: false});
    });
    _addChannelContextMenu(el);
  });
  _addDragAndDrop(container, "starred");
}

/* Context menu for channel items — right-click shows pref options */
function _addChannelContextMenu(el) {
  el.addEventListener("contextmenu", function (ev) {
    ev.preventDefault();
    var ch = el.getAttribute("data-channel");
    _showChannelCtxMenu(ch, ev.clientX, ev.clientY);
  });
}

var _ctxMenu = null;
function _showChannelCtxMenu(ch, x, y) {
  _hideChannelCtxMenu();
  var prefs = _channelPrefs[ch] || {};
  var starred = prefs.is_starred;
  var muted = prefs.is_muted;
  var hidden = prefs.is_hidden;
  var notif = prefs.notification_level || "all";

  var menu = document.createElement("div");
  menu.className = "ch-ctx-menu";
  menu.style.cssText = "position:fixed;z-index:9999;left:" + x + "px;top:" + y + "px;";
  menu.innerHTML = [
    '<div class="ch-ctx-item" data-action="star">' + (starred ? "&#9733; Unstar" : "&#9734; Star channel") + "</div>",
    '<div class="ch-ctx-item" data-action="mute">' + (muted ? "&#128276; Unmute" : "&#128263; Mute channel") + "</div>",
    '<div class="ch-ctx-sep"></div>',
    '<div class="ch-ctx-label">Notifications</div>',
    '<div class="ch-ctx-item ch-ctx-notif' + (notif==="all"?" ch-ctx-active":"") + '" data-action="notif-all">All messages</div>',
    '<div class="ch-ctx-item ch-ctx-notif' + (notif==="mentions"?" ch-ctx-active":"") + '" data-action="notif-mentions">@ Mentions only</div>',
    '<div class="ch-ctx-item ch-ctx-notif' + (notif==="nothing"?" ch-ctx-active":"") + '" data-action="notif-nothing">Nothing</div>',
    '<div class="ch-ctx-sep"></div>',
    '<div class="ch-ctx-item ch-ctx-hide" data-action="hide">' + (hidden ? "Show channel" : "Hide channel") + "</div>",
  ].join("");
  document.body.appendChild(menu);
  _ctxMenu = menu;

  menu.querySelectorAll(".ch-ctx-item").forEach(function (item) {
    item.addEventListener("click", function () {
      var action = item.getAttribute("data-action");
      if (action === "star") _setChannelPref(ch, {is_starred: !starred});
      else if (action === "mute") _setChannelPref(ch, {is_muted: !muted});
      else if (action === "notif-all") _setChannelPref(ch, {notification_level: "all"});
      else if (action === "notif-mentions") _setChannelPref(ch, {notification_level: "mentions"});
      else if (action === "notif-nothing") _setChannelPref(ch, {notification_level: "nothing"});
      else if (action === "hide") _setChannelPref(ch, {is_hidden: !hidden});
      _hideChannelCtxMenu();
    });
  });

  /* Close on click outside */
  setTimeout(function () {
    document.addEventListener("mousedown", _hideChannelCtxMenu, {once: true});
  }, 10);
}

function _hideChannelCtxMenu() {
  if (_ctxMenu) { _ctxMenu.remove(); _ctxMenu = null; }
}

/* ── Drag-and-drop reordering for sidebar channel sections (msg#10370) ──
 * Works within a section (Starred ↔ Starred, Channels ↔ Channels).
 * Cross-section drops are ignored (star toggle is the way to move between sections).
 * Persistence: saves sort_order via _setChannelPref after each drop.
 */
var _dndState = null; /* {el, section, origIndex} */

function _addDragAndDrop(container, section) {
  container.querySelectorAll(".channel-item[draggable]").forEach(function (el) {
    el.addEventListener("dragstart", function (ev) {
      _dndState = {el: el, section: section};
      el.classList.add("ch-dragging");
      ev.dataTransfer.effectAllowed = "move";
      ev.dataTransfer.setData("text/plain", el.getAttribute("data-channel"));
    });

    el.addEventListener("dragend", function () {
      el.classList.remove("ch-dragging");
      container.querySelectorAll(".ch-drop-target").forEach(function (t) {
        t.classList.remove("ch-drop-target");
      });
      _dndState = null;
    });

    el.addEventListener("dragover", function (ev) {
      if (!_dndState || _dndState.section !== section) return;
      ev.preventDefault();
      ev.dataTransfer.dropEffect = "move";
      /* Show drop target indicator */
      container.querySelectorAll(".ch-drop-target").forEach(function (t) {
        t.classList.remove("ch-drop-target");
      });
      if (el !== _dndState.el) el.classList.add("ch-drop-target");
    });

    el.addEventListener("drop", function (ev) {
      ev.preventDefault();
      if (!_dndState || _dndState.section !== section || el === _dndState.el) return;
      /* Insert dragged item before drop target */
      var items = Array.from(container.querySelectorAll(".channel-item[draggable]"));
      var fromIdx = items.indexOf(_dndState.el);
      var toIdx = items.indexOf(el);
      if (fromIdx === -1 || toIdx === -1) return;
      /* Reorder DOM */
      if (fromIdx < toIdx) {
        container.insertBefore(_dndState.el, el.nextSibling);
      } else {
        container.insertBefore(_dndState.el, el);
      }
      /* Persist new order */
      var reordered = Array.from(container.querySelectorAll(".channel-item[draggable]"));
      reordered.forEach(function (item, idx) {
        var ch = item.getAttribute("data-channel");
        if (ch) {
          /* Update local cache immediately (don't call _setChannelPref to avoid re-render loop) */
          if (!_channelPrefs[ch]) _channelPrefs[ch] = {};
          _channelPrefs[ch].sort_order = idx * 10;
          /* Persist to server */
          fetch(apiUrl("/api/channel-prefs/"), {
            method: "PATCH",
            credentials: "same-origin",
            headers: {"Content-Type": "application/json", "X-CSRFToken": getCsrfToken()},
            body: JSON.stringify({channel: ch, sort_order: idx * 10}),
          }).catch(function (_) {});
        }
      });
      el.classList.remove("ch-drop-target");
    });
  });
}

var cachedAgentNames = [];
var historyLoaded = false;
var knownMessageKeys = {};
var unreadCount = 0;
var channelUnread = {}; /* per-channel unread counts (#322) */
var baseTitle = document.title;

/* User display name -- from Django auth or fallback to localStorage */
var userName =
  window.__orochiUserName || localStorage.getItem("orochi_username");
if (!userName) {
  userName = prompt("Enter your display name for Orochi:", "");
  if (userName) {
    localStorage.setItem("orochi_username", userName);
  } else {
    userName = "human";
  }
}
var csrfToken = window.__orochiCsrfToken || "";
function getCsrfToken() { return window.__orochiCsrfToken || csrfToken || ""; }
function getAgentColor(name) {
  var s = name || "unknown";
  var sum = 0;
  for (var i = 0; i < s.length; i++) {
    sum += s.charCodeAt(i);
  }
  return OROCHI_COLORS[sum % OROCHI_COLORS.length];
}

/* Workspace icon — Slack-style colored rounded square with first letter */
var WORKSPACE_ICON_COLORS = [
  "#4A154B",
  "#1264A3",
  "#2BAC76",
  "#E01E5A",
  "#36C5F0",
  "#ECB22E",
  "#611f69",
  "#0b4f6c",
];

function getWorkspaceColor(name) {
  var s = name || "workspace";
  var sum = 0;
  for (var i = 0; i < s.length; i++) {
    sum += s.charCodeAt(i) * (i + 1);
  }
  return WORKSPACE_ICON_COLORS[sum % WORKSPACE_ICON_COLORS.length];
}

function getWorkspaceIcon(name, size) {
  size = size || 20;
  var color = getWorkspaceColor(name);
  var letter = (name || "W").charAt(0).toUpperCase();
  var fontSize = Math.round(size * 0.55);
  var radius = Math.round(size * 0.22);
  return (
    '<svg class="ws-icon-svg" width="' +
    size +
    '" height="' +
    size +
    '" viewBox="0 0 ' +
    size +
    " " +
    size +
    '" xmlns="http://www.w3.org/2000/svg">' +
    '<rect width="' +
    size +
    '" height="' +
    size +
    '" rx="' +
    radius +
    '" fill="' +
    color +
    '"/>' +
    '<text x="50%" y="50%" dominant-baseline="central" text-anchor="middle" ' +
    'fill="#fff" font-family="-apple-system,BlinkMacSystemFont,sans-serif" ' +
    'font-weight="700" font-size="' +
    fontSize +
    '">' +
    letter +
    "</text></svg>"
  );
}
function escapeHtml(s) {
  var d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

/* Strip hostname suffix: "head@mba@Host" → "head@mba" */
function cleanAgentName(name) {
  if (!name) return name;
  var parts = name.split("@");
  if (parts.length >= 3) {
    return parts[0] + "@" + parts[1];
  }
  return name;
}

/**
 * Return the agent name with host suffix. If the registered name already
 * contains @host (e.g. "head@mba"), return as-is. Otherwise append
 * "@<machine>" from the agent record so the sidebar always shows an
 * identity tied to a host (mamba shows as "mamba@ywata-note-win" even if
 * the agent config still registered plain "mamba").
 */
function hostedAgentName(a) {
  var name = a && a.name ? a.name : "";
  if (!name) return name;
  if (name.indexOf("@") !== -1) return cleanAgentName(name);
  var host = a && a.machine ? a.machine : "";
  return host ? name + "@" + host : name;
}

function fuzzyMatch(query, text) {
  if (!query) return true;
  query = query.toLowerCase();
  text = text.toLowerCase();
  var qi = 0;
  for (var ti = 0; ti < text.length && qi < query.length; ti++) {
    if (text[ti] === query[qi]) qi++;
  }
  return qi === query.length;
}

function messageKey(sender, ts, content) {
  return (
    (sender || "") + "|" + (ts || "") + "|" + (content || "").substring(0, 80)
  );
}

function isAgentInactive(agent) {
  if (agent.status === "offline") return true;
  if (!agent.last_heartbeat) return false;
  var hb = new Date(agent.last_heartbeat);
  if (isNaN(hb.getTime())) return false;
  return Date.now() - hb.getTime() > 60000;
}

function relativeAge(isoStr) {
  if (!isoStr) return "";
  var d = new Date(isoStr);
  if (isNaN(d.getTime())) return "";
  var sec = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
  if (sec < 5) return "just now";
  if (sec < 60) return sec + "s ago";
  var min = Math.floor(sec / 60);
  if (min < 60) return min + "m ago";
  var hr = Math.floor(min / 60);
  if (hr < 24) return hr + "h ago";
  var days = Math.floor(hr / 24);
  return days + "d ago";
}

function timeAgo(isoStr) {
  if (!isoStr) return "";
  var d = new Date(isoStr);
  if (isNaN(d.getTime())) return "";
  var pad = function (n) {
    return n < 10 ? "0" + n : "" + n;
  };
  return (
    d.getFullYear() +
    "-" +
    pad(d.getMonth() + 1) +
    "-" +
    pad(d.getDate()) +
    " " +
    pad(d.getHours()) +
    ":" +
    pad(d.getMinutes()) +
    ":" +
    pad(d.getSeconds())
  );
}

function uptime(isoStr) {
  if (!isoStr) return "";
  var then = new Date(isoStr);
  if (isNaN(then.getTime())) return "";
  var diff = Math.floor((Date.now() - then.getTime()) / 1000);
  var h = Math.floor(diff / 3600);
  var m = Math.floor((diff % 3600) / 60);
  return h + "h " + m + "m";
}

/* REST helper -- Django uses CSRF + session auth, no token param */
function orochiHeaders() {
  var h = { "Content-Type": "application/json" };
  if (csrfToken) h["X-CSRFToken"] = csrfToken;
  return h;
}

/* token for API calls (Flask upstream or Django) */
var token =
  window.__orochiToken ||
  window.__orochiDashboardToken ||
  new URLSearchParams(location.search).get("token") ||
  "";

function apiUrl(path) {
  var base = window.__orochiApiUpstream || "";
  var sep = path.indexOf("?") === -1 ? "?" : "&";
  return base + path + (token ? sep + "token=" + token : "");
}

function sendOrochiMessage(msgData) {
  fetch(apiUrl("/api/messages/"), {
    method: "POST",
    headers: orochiHeaders(),
    body: JSON.stringify(msgData),
  })
    .then(function (res) {
      if (!res.ok) console.error("REST send failed:", res.status);
    })
    .catch(function (e) {
      console.error("REST send error:", e);
    });
}

/* WebSocket connection */
var ws;
var wsConnected = false;
var restPollTimer = null;
var restPollInterval = 5000;

/* fetchAgents throttle — prevents focus theft on rapid WS events (#225) */
var _fetchAgentsTimer = null;
var _fetchAgentsPending = false;
var FETCH_AGENTS_THROTTLE_MS = 2000;

function fetchAgentsThrottled() {
  if (_fetchAgentsTimer) {
    _fetchAgentsPending = true;
    return;
  }
  fetchAgents();
  _fetchAgentsTimer = setTimeout(function () {
    _fetchAgentsTimer = null;
    if (_fetchAgentsPending) {
      _fetchAgentsPending = false;
      fetchAgentsThrottled();
    }
  }, FETCH_AGENTS_THROTTLE_MS);
}

var _fetchStatsTimer = null;
var _fetchStatsPending = false;

function fetchStatsThrottled() {
  if (_fetchStatsTimer) {
    _fetchStatsPending = true;
    return;
  }
  fetchStats();
  _fetchStatsTimer = setTimeout(function () {
    _fetchStatsTimer = null;
    if (_fetchStatsPending) {
      _fetchStatsPending = false;
      fetchStatsThrottled();
    }
  }, FETCH_AGENTS_THROTTLE_MS);
}

function startRestPolling() {
  if (restPollTimer) return;
  restPollTimer = setInterval(async function () {
    if (wsConnected) return;
    try {
      var res = await fetch(apiUrl("/api/messages/?limit=50"), {
        credentials: "same-origin",
      });
      if (!res.ok) return;
      var messages = await res.json();
      /* API returns newest-first; reverse so new messages append chronologically */
      messages.reverse();
      messages.forEach(function (row) {
        var key = messageKey(row.sender, row.ts, row.content);
        if (knownMessageKeys[key]) return;
        knownMessageKeys[key] = true;
        appendMessage({
          type: "message",
          sender: row.sender,
          sender_type: row.sender_type,
          ts: row.ts,
          payload: {
            channel: row.channel,
            content: row.content,
            attachments:
              (row.metadata && row.metadata.attachments) ||
              row.attachments ||
              [],
          },
        });
      });
    } catch (e) {
      console.warn("REST poll failed:", e);
    }
    fetchAgentsThrottled();
    fetchStats();
  }, restPollInterval);
}

function stopRestPolling() {
  if (restPollTimer) {
    clearInterval(restPollTimer);
    restPollTimer = null;
  }
}

function handleMessage(msg) {
  if (msg.type === "message") {
    /* Filter hub internal status probe messages from the feed (#10315).
     * These are sent by the hub itself (sender="hub") as presence/status
     * notifications — they are not user messages and should never appear
     * in the chat feed. */
    if ((msg.sender === "hub" || msg.sender === "system") &&
        (msg.metadata && msg.metadata.type === "status_probe")) return;
    var content = "";
    /* Hub sends flat messages: {type, sender, channel, text, ts, metadata} */
    if (msg.text || msg.channel) {
      content = msg.text || "";
      if (!msg.payload) {
        var attachments = (msg.metadata && msg.metadata.attachments) || [];
        msg.payload = {
          channel: msg.channel || "",
          content: content,
          metadata: msg.metadata || {},
          attachments: attachments,
        };
      }
    } else if (msg.payload) {
      content =
        msg.payload.content || msg.payload.text || msg.payload.message || "";
    }
    var key = messageKey(msg.sender, msg.ts, content);
    if (knownMessageKeys[key]) return;
    knownMessageKeys[key] = true;
    appendMessage(msg);
    /* If this message is a reply and the matching thread panel is open,
     * also live-append it there (deduped by reply id). */
    if (typeof appendToThreadPanelIfOpen === "function") {
      appendToThreadPanelIfOpen(msg);
    }
    if (document.hidden) {
      unreadCount++;
      document.title = "(" + unreadCount + ") " + baseTitle;
    }
    /* Per-channel unread count (#322) */
    var msgCh = msg.channel || msg.chat_id || "";
    if (msgCh && msgCh !== currentChannel) {
      channelUnread[msgCh] = (channelUnread[msgCh] || 0) + 1;
      updateChannelUnreadBadges();
    }
  } else if (msg.type === "system_message") {
    if (typeof appendSystemMessage === "function") {
      appendSystemMessage(msg);
    }
  } else if (
    msg.type === "presence_change" ||
    msg.type === "status_update" ||
    msg.type === "agent_presence" ||
    msg.type === "agent_info"
  ) {
    fetchAgentsThrottled();
    fetchStatsThrottled();
    fetchResources();
  } else if (msg.type === "reaction_update") {
    if (typeof handleReactionUpdate === "function") handleReactionUpdate(msg);
  } else if (msg.type === "thread_reply") {
    if (typeof handleThreadReply === "function") handleThreadReply(msg);
  } else if (msg.type === "message_edit") {
    if (typeof handleMessageEdit === "function") handleMessageEdit(msg);
  } else if (msg.type === "message_delete") {
    if (typeof handleMessageDelete === "function") handleMessageDelete(msg);
  } else if (msg.type === "channel_description") {
    /* Live update channel topic banner without page reload */
    var chName = msg.channel;
    if (chName) {
      _channelDescriptions[chName] = msg.description || "";
      if (chName === currentChannel) _updateChannelTopicBanner(chName);
    }
  }
}

/* Reset unread count when tab becomes visible */
document.addEventListener("visibilitychange", function () {
  if (!document.hidden) {
    unreadCount = 0;
    document.title = baseTitle;
  }
});

/* Per-channel unread badges (#322) */
function updateChannelUnreadBadges() {
  /* Update #channels section (starred channels now live here too) */
  document.querySelectorAll("#channels .channel-item").forEach(function (el) {
    var ch = el.getAttribute("data-channel");
    var count = channelUnread[ch] || 0;
    var slot = el.querySelector(".ch-badge-slot");
    if (slot) {
      /* Preferred: update inside the badge slot (stable layout) */
      var badge = slot.querySelector(".unread-badge");
      if (count > 0) {
        if (!badge) {
          badge = document.createElement("span");
          badge.className = "unread-badge";
          slot.appendChild(badge);
        }
        badge.textContent = count > 99 ? "99+" : count;
      } else if (badge) {
        badge.remove();
      }
    } else {
      /* Fallback: legacy DOM structure without slot */
      var badge2 = el.querySelector(".unread-badge");
      if (count > 0) {
        if (!badge2) {
          badge2 = document.createElement("span");
          badge2.className = "unread-badge";
          el.appendChild(badge2);
        }
        badge2.textContent = count > 99 ? "99+" : count;
      } else if (badge2) {
        badge2.remove();
      }
    }
  });
}
window.updateChannelUnreadBadges = updateChannelUnreadBadges;

function connect() {
  var statusEl = document.getElementById("conn-status");
  /* Build WS URL: prefer Django WS, fallback to upstream or auto-detect */
  var wsUrl;
  if (window.__orochiWsUrl) {
    wsUrl = window.__orochiWsUrl;
    /* Append token if not already present (fallback for stripped cookies) */
    if (token && wsUrl.indexOf("token=") === -1) {
      wsUrl += (wsUrl.indexOf("?") === -1 ? "?" : "&") + "token=" + token;
    }
  } else {
    var wsProto = location.protocol === "https:" ? "wss:" : "ws:";
    var wsHost = window.__orochiWsUpstream
      ? window.__orochiWsUpstream.replace(/^https?:\/\//, "")
      : location.host;
    wsUrl = wsProto + "//" + wsHost + "/ws";
    if (token) wsUrl += "?token=" + token;
  }
  try {
    ws = new WebSocket(wsUrl);
  } catch (e) {
    console.warn("WebSocket constructor failed:", e);
    statusEl.textContent = "polling";
    statusEl.className = "status conn-poll";
    statusEl.title = "WebSocket unavailable — falling back to REST polling";
    startRestPolling();
    return;
  }
  ws.onopen = function () {
    wsConnected = true;
    /* Compact, muted when fine; state class drives the styling */
    statusEl.textContent = "";
    statusEl.title = "Connected to Orochi server";
    statusEl.className = "status conn-ok";
    stopRestPolling();
    fetchStats();
    fetchAgents();
    /* On reconnect (historyLoaded=true), fetch only new messages
     * incrementally instead of doing a full DOM rebuild.  A full
     * loadHistory() on mobile Safari causes massive innerHTML churn
     * that can reset the textarea value / dismiss the keyboard while
     * the user is typing. */
    if (historyLoaded) {
      fetchNewMessages();
    } else {
      loadHistory();
    }
  };
  ws.onclose = function (event) {
    wsConnected = false;
    statusEl.textContent = "disconnected";
    statusEl.className = "status conn-down";
    startRestPolling();
    if (event.code === 4001) {
      statusEl.title = "Session expired — please log in again";
      showSystemBanner(
        "Session expired. Please reload and log in again.",
        "error",
      );
    } else if (event.code === 4003) {
      statusEl.title = "No access to this workspace";
      showSystemBanner("Access denied to this workspace.", "error");
    } else if (event.code === 4004) {
      statusEl.title = "Workspace not found";
      showSystemBanner("Workspace not found.", "error");
    } else {
      statusEl.title = "Disconnected — retrying every 3s";
      statusEl.textContent = "reconnecting";
      setTimeout(connect, 3000);
    }
  };
  ws.onerror = function () {
    if (!wsConnected) startRestPolling();
  };
  ws.onmessage = function (event) {
    try {
      handleMessage(JSON.parse(event.data));
    } catch (e) {
      console.error(
        "[orochi-ws] message handling error:",
        e,
        "raw:",
        event.data.substring(0, 200),
      );
    }
  };
}
/* Sidebar agents + stats fetching */
async function fetchAgents() {
  try {
    var res = await fetch(apiUrl("/api/agents"));
    var agents = await res.json();
    /* Cache for the Activity tab and other consumers */
    window.__lastAgents = agents;
    /* Rebuild channel→members map for topic banner subscriber list */
    _rebuildAgentChannelMap(agents);
    if (typeof renderActivityTab === "function") renderActivityTab();
    var container = document.getElementById("agents");
    /* Focus guard — see todo#225. This path fires on every WS
     * presence/status event and on REST poll; mobile Safari can blur
     * the compose textarea on large innerHTML swaps. */
    var msgInput = document.getElementById("msg-input");
    var inputHasFocus = msgInput && document.activeElement === msgInput;
    var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
    var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
    if (agents.length === 0) {
      container.innerHTML = '<p id="no-agents">No agents connected</p>';
      var cEl = document.getElementById("sidebar-count-agents");
      if (cEl) cEl.textContent = "";
      if (inputHasFocus && document.activeElement !== msgInput) {
        msgInput.focus();
        try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (e) {}
      }
      return;
    }
    var cEl = document.getElementById("sidebar-count-agents");
    if (cEl) cEl.textContent = "(" + agents.length + ")";
    agents.forEach(function (a) {
      cacheAgentIcons([a]);
    });
    /* Skip full DOM rebuild if agent data hasn't changed (#225) */
    var newAgentsJson = JSON.stringify(agents);
    if (container._lastAgentsJson === newAgentsJson) return;
    container._lastAgentsJson = newAgentsJson;
    /* Preserve Ctrl+Click multi-select state across re-renders (#274 Part 2).
     * Without this, every fetchAgents() poll/WS presence event clobbers
     * .selected on agent-cards, defeating multi-select. */
    var prevSelectedAgents = {};
    container
      .querySelectorAll(".agent-card.selected[data-agent-name]")
      .forEach(function (el) {
        var n = el.getAttribute("data-agent-name");
        if (n) prevSelectedAgents[n] = true;
      });
    /* todo#320: sidebar agent cards are now compact — name + status
     * dot only. Full detail (badges, kill/pin/restart, task rows,
     * detail popup, health pill, tooltip) lives in the Agents tab. */
    container.innerHTML = agents
      .map(function (a) {
        var inactive = isAgentInactive(a);
        var liveness = a.liveness || (inactive ? "offline" : "online");
        var statusClassCompact = liveness === "online" ? "online" : "offline";
        var tooltip = (a.agent_id || a.name) + " (" + (a.machine || "unknown") + ")";
        return (
          '<div class="agent-card sidebar-compact' +
          (inactive ? " inactive" : "") +
          '" data-agent-name="' +
          escapeHtml(a.name) +
          '" title="' +
          escapeHtml(tooltip) +
          '">' +
          '<span class="agent-status ' +
          statusClassCompact +
          '"></span>' +
          '<span class="agent-name">' +
          escapeHtml(hostedAgentName(a)) +
          "</span>" +
          "</div>"
        );
      })
      .join("");
    container
      .querySelectorAll(".agent-card[data-agent-name]")
      .forEach(function (el) {
        /* Restore .selected from before re-render (#274 Part 2) */
        var elName = el.getAttribute("data-agent-name");
        if (elName && prevSelectedAgents[elName]) el.classList.add("selected");
        el.addEventListener("click", function (ev) {
          if (ev.target.closest(".pin-btn")) return; /* handled separately */
          if (ev.target.closest(".kill-btn")) return; /* handled separately */
          if (ev.target.closest(".restart-btn")) return; /* handled separately */
          if (ev.target.closest(".avatar-clickable"))
            return; /* handled below */
          var multi = ev.ctrlKey || ev.metaKey;
          /* todo#274 Part 2: Ctrl/Cmd+Click toggles multi-select. */
          if (multi) {
            el.classList.toggle("selected");
          } else {
            /* todo#274 Part 1: single-select highlight (toggle on 2nd click). */
            var cards = container.querySelectorAll(".agent-card[data-agent-name]");
            var wasSelected = el.classList.contains("selected");
            cards.forEach(function (c) { c.classList.remove("selected"); });
            if (!wasSelected) el.classList.add("selected");
          }
          if (typeof applyFeedFilter === "function") applyFeedFilter();
        });
      });
    container
      .querySelectorAll(".pin-btn[data-pin-name]")
      .forEach(function (btn) {
        btn.addEventListener("click", function (ev) {
          ev.stopPropagation();
          togglePinAgent(
            btn.getAttribute("data-pin-name"),
            !btn.classList.contains("pinned"),
          );
        });
      });
    container
      .querySelectorAll(".avatar-clickable[data-avatar-agent]")
      .forEach(function (el) {
        el.addEventListener("click", function (ev) {
          ev.stopPropagation();
          openAvatarPicker(el.getAttribute("data-avatar-agent"));
        });
      });
    container
      .querySelectorAll(".kill-btn[data-kill-name]")
      .forEach(function (btn) {
        btn.addEventListener("click", function (ev) {
          ev.stopPropagation();
          killAgent(btn.getAttribute("data-kill-name"), btn);
        });
      });
    container
      .querySelectorAll(".restart-btn[data-restart-name]")
      .forEach(function (btn) {
        btn.addEventListener("click", function (ev) {
          ev.stopPropagation();
          restartAgent(btn.getAttribute("data-restart-name"), btn);
        });
      });
    if (inputHasFocus && document.activeElement !== msgInput) {
      msgInput.focus();
      try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (e) {}
    }
    /* Re-apply sidebar filter after DOM rebuild so display:none isn't lost */
    if (typeof runFilter === "function") runFilter();
  } catch (e) {
    /* fetch error */
  }
}

async function restartAgent(name, btn) {
  if (!confirm("Restart agent " + name + "?")) return;
  var origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "\u23F3";
  btn.classList.add("restarting");
  try {
    var headers = orochiHeaders();
    var res = await fetch(apiUrl("/api/agents/restart/"), {
      method: "POST",
      headers: headers,
      credentials: "same-origin",
      body: JSON.stringify({ name: name }),
    });
    var data = await res.json();
    if (res.ok) {
      btn.textContent = "\u2713";
      setTimeout(function () {
        btn.textContent = origText;
        btn.disabled = false;
        btn.classList.remove("restarting");
        fetchAgents();
      }, 3000);
    } else {
      btn.textContent = "\u2717";
      console.error("Restart failed:", data.error || res.status);
      setTimeout(function () {
        btn.textContent = origText;
        btn.disabled = false;
        btn.classList.remove("restarting");
      }, 3000);
    }
  } catch (e) {
    console.error("Restart error:", e);
    btn.textContent = origText;
    btn.disabled = false;
    btn.classList.remove("restarting");
  }
}

async function killAgent(name, btn) {
  if (!confirm("Kill agent " + name + "?\nThis will terminate screen, bun sidecar, and disconnect.")) return;
  var origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "\u23F3";
  btn.classList.add("killing");
  try {
    var headers = orochiHeaders();
    var res = await fetch(apiUrl("/api/agents/kill/"), {
      method: "POST",
      headers: headers,
      credentials: "same-origin",
      body: JSON.stringify({ name: name }),
    });
    var data = await res.json();
    if (res.ok) {
      btn.textContent = "\u2713";
      setTimeout(function () {
        btn.textContent = origText;
        btn.disabled = false;
        btn.classList.remove("killing");
        fetchAgents();
      }, 2000);
    } else {
      btn.textContent = "\u2717";
      console.error("Kill failed:", data.error || res.status);
      setTimeout(function () {
        btn.textContent = origText;
        btn.disabled = false;
        btn.classList.remove("killing");
      }, 3000);
    }
  } catch (e) {
    console.error("Kill error:", e);
    btn.textContent = origText;
    btn.disabled = false;
    btn.classList.remove("killing");
  }
}

async function togglePinAgent(name, shouldPin) {
  try {
    var token = window.__orochiCsrfToken || "";
    var headers = { "Content-Type": "application/json" };
    if (token) headers["X-CSRFToken"] = token;
    var method = shouldPin ? "POST" : "DELETE";
    var res = await fetch(apiUrl("/api/agents/pin/"), {
      method: method,
      headers: headers,
      credentials: "same-origin",
      body: JSON.stringify({ name: name }),
    });
    if (res.ok) {
      fetchAgents();
    } else {
      console.error("Pin/unpin failed:", res.status);
    }
  } catch (e) {
    console.error("Pin/unpin error:", e);
  }
}

async function fetchStats() {
  try {
    var res = await fetch(apiUrl("/api/stats"));
    var stats = await res.json();
    var chContainer = document.getElementById("channels");
    /* Guard key must include currentChannel: otherwise a channel click that
     * leaves the stats payload unchanged (same channel list, same counts)
     * skips the rerender and the .active highlight fails to update — making
     * it look like the active channel "jumped" or disappeared on the next
     * unrelated stats refresh (todo#246 reopened). */
    var newStatsJson =
      JSON.stringify(stats.channels) + "|" + (currentChannel || "__all__");
    if (chContainer._lastStatsJson === newStatsJson) return;
    chContainer._lastStatsJson = newStatsJson;
    var msgInput = document.getElementById("msg-input");
    var inputHasFocus = msgInput && document.activeElement === msgInput;
    var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
    var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
    /* Preserve Ctrl+Click multi-select state across re-renders (#274 Part 2) */
    var prevSelected = {};
    chContainer.querySelectorAll(".channel-item.selected").forEach(function (el) {
      var ch = el.getAttribute("data-channel");
      if (ch) prevSelected[ch] = true;
    });
    /* todo#325: hide dm:* channels from the public Channels list
     * (they still render in the DM tab via its own path).
     * todo#326: normalize "general" -> "#general" and dedupe by
     * normalized name so legacy rows collapse into a single entry. */
    var seenNames = {};
    var displayChannels = [];
    stats.channels.forEach(function (c) {
      if (typeof c !== "string") return;
      if (c.indexOf("dm:") === 0) return;
      var norm = c.charAt(0) === "#" ? c : "#" + c;
      if (seenNames[norm]) return;
      seenNames[norm] = true;
      /* Skip hidden channels; starred channels stay in the list (sorted first) */
      var pref = _channelPrefs[norm] || _channelPrefs[c] || {};
      if (pref.is_hidden) return;
      displayChannels.push({ raw: c, norm: norm });
    });
    /* Sort: starred first (sorted by sort_order/alpha), then non-starred alpha */
    displayChannels.sort(function (a, b) {
      var pa = _channelPrefs[a.norm] || _channelPrefs[a.raw] || {};
      var pb = _channelPrefs[b.norm] || _channelPrefs[b.raw] || {};
      var aStarred = pa.is_starred ? 0 : 1;
      var bStarred = pb.is_starred ? 0 : 1;
      if (aStarred !== bStarred) return aStarred - bStarred;
      var oa = pa.sort_order != null ? pa.sort_order : 9999;
      var ob = pb.sort_order != null ? pb.sort_order : 9999;
      return oa !== ob ? oa - ob : a.norm.localeCompare(b.norm);
    });
    chContainer.innerHTML = displayChannels
      .map(function (entry, i) {
        var c = entry.raw;
        var norm = entry.norm;
        var active = currentChannel === c ? " active" : "";
        var pref = _channelPrefs[norm] || _channelPrefs[c] || {};
        var muted = pref.is_muted ? " ch-muted" : "";
        var starHtml = '<span class="ch-star ' + (pref.is_starred ? "ch-star-on" : "ch-star-off") +
          '" data-ch="' + escapeHtml(norm) + '" title="' + (pref.is_starred ? "Unstar" : "Star") + '">&#9733;</span>';
        var unread = channelUnread[c] || channelUnread[norm] || 0;
        var badgeHtml = '<span class="ch-badge-slot">' +
          (unread > 0 ? '<span class="unread-badge">' + (unread > 99 ? "99+" : unread) + '</span>' : '') +
          '</span>';
        var starred = pref.is_starred ? " ch-starred" : "";
        return (
          '<div class="channel-item' + active + muted + starred +
          '" data-channel="' + escapeHtml(c) + '" draggable="true">' +
          '<span class="ch-drag-handle" title="Drag to reorder">&#8942;</span>' +
          starHtml +
          '<span class="ch-name">' + escapeHtml(entry.norm) + '</span>' +
          badgeHtml +
          "</div>"
        );
      })
      .join("");
    chContainer.querySelectorAll(".channel-item").forEach(function (el) {
      /* Restore selected state from before re-render */
      var elCh = el.getAttribute("data-channel");
      if (elCh && prevSelected[elCh]) el.classList.add("selected");
      /* Star icon click — toggle star without navigating */
      var starEl = el.querySelector(".ch-star");
      if (starEl) {
        starEl.addEventListener("click", function (ev) {
          ev.stopPropagation();
          var norm = starEl.getAttribute("data-ch");
          var curPref = _channelPrefs[norm] || {};
          _setChannelPref(norm, {is_starred: !curPref.is_starred});
        });
      }
      /* Context menu */
      _addChannelContextMenu(el);
      el.addEventListener("click", function (ev) {
        if (ev.target.classList.contains("ch-star") || ev.target.classList.contains("ch-drag-handle")) return;
        var ch = el.getAttribute("data-channel");
        var multi = ev.ctrlKey || ev.metaKey;
        /* todo#274 Part 2: Ctrl/Cmd+Click toggles multi-select without
         * disturbing siblings; plain click keeps legacy single-select. */
        if (multi) {
          el.classList.toggle("selected");
          /* When multi-select is active, the DOM may only have messages from
           * currentChannel. Switch to all-channel history so messages from
           * every selected channel are present, then let applyFeedFilter
           * show the merged subset. (#366) */
          var _selCount = chContainer.querySelectorAll(
            ".channel-item.selected[data-channel]",
          ).length;
          if (_selCount >= 2) {
            /* Load all messages; applyFeedFilter handles visible subset */
            setCurrentChannel(null);
            var _applyAfter = function () {
              if (typeof applyFeedFilter === "function") applyFeedFilter();
            };
            loadHistory().then
              ? loadHistory().then(_applyAfter)
              : (loadHistory(), _applyAfter());
          } else if (_selCount === 1) {
            var _onlyCh = chContainer.querySelector(
              ".channel-item.selected[data-channel]",
            );
            if (_onlyCh) {
              setCurrentChannel(_onlyCh.getAttribute("data-channel"));
              loadChannelHistory(_onlyCh.getAttribute("data-channel"));
            }
          } else {
            /* All deselected */
            if (typeof applyFeedFilter === "function") applyFeedFilter();
          }
          return;
        }
        if (currentChannel === ch) {
          setCurrentChannel(null);
          loadHistory();
        } else {
          setCurrentChannel(ch);
          loadChannelHistory(ch);
        }
        /* Auto-switch to Chat tab when channel is clicked (#335) */
        if (typeof _activateTab === "function" && activeTab !== "chat") {
          _activateTab("chat");
        }
        /* Clear unread for this channel (#322) */
        channelUnread[ch] = 0;
        updateChannelUnreadBadges();
        /* todo#274 Part 1: pure visual highlight, toggle on second click. */
        var items = chContainer.querySelectorAll(".channel-item");
        var wasSelected = el.classList.contains("selected");
        items.forEach(function (it) { it.classList.remove("selected"); });
        if (!wasSelected && currentChannel === ch) {
          el.classList.add("selected");
        }
        if (typeof applyFeedFilter === "function") applyFeedFilter();
        fetchStats();
      });
    });
    var chCountEl = document.getElementById("sidebar-count-channels");
    if (chCountEl) chCountEl.textContent = "(" + displayChannels.length + ")";
    /* Add drag-and-drop to channels section */
    _addDragAndDrop(chContainer, "channels");
    if (typeof updateChannelUnreadBadges === "function") updateChannelUnreadBadges();
    if (inputHasFocus && document.activeElement !== msgInput) {
      msgInput.focus();
      try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
    }
  } catch (e) {
    /* fetch error */
  }
}
/* Init is deferred to init.js (loaded after all modules) */

/* Global ESC handler — close any visible popups/modals (#207) */
document.addEventListener("keydown", function (e) {
  if (e.key !== "Escape") return;
  if (typeof closeEmojiPicker === "function") {
    var emojiOverlay = document.querySelector(".emoji-picker-overlay.visible");
    if (emojiOverlay) { closeEmojiPicker(); e.preventDefault(); return; }
  }
  if (typeof closeThreadPanel === "function") {
    var threadPanel = document.querySelector(".thread-panel.open");
    if (threadPanel) { closeThreadPanel(); e.preventDefault(); return; }
  }
  if (typeof closeSketchPanel === "function") {
    var sketchPanel = document.querySelector(".sketch-panel.open");
    if (sketchPanel) { closeSketchPanel(); e.preventDefault(); return; }
  }
  var generic = document.querySelector(".emoji-picker-overlay.visible, .modal.open, .popup.visible, .long-press-menu");
  if (generic) {
    generic.classList.remove("visible", "open");
    if (generic.classList.contains("long-press-menu")) generic.remove();
    e.preventDefault();
  }
});
