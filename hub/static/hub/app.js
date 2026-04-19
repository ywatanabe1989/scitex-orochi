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
  /* Per-channel chat filter: reset whenever the user switches channels so
   * a stale filter from the previous channel doesn't hide messages here. */
  if (typeof chatFilterReset === "function") {
    try {
      chatFilterReset();
    } catch (_) {}
  }
  /* Update textarea placeholder to show active channel — msg#9368.
   * In multi-select mode (ch=null), keep showing the last active channel
   * so the user knows where their message will be posted (#9694).
   * DMs use a friendly "@<other>" label instead of the raw
   * "dm:agent:X|human:Y" channel string. */
  try {
    var inp = document.getElementById("msg-input");
    if (inp) {
      var targetCh = ch || lastActiveChannel;
      if (targetCh && targetCh.indexOf("dm:") === 0) {
        inp.placeholder = "Message " + _dmFriendlyLabel(targetCh) + "\u2026";
      } else {
        inp.placeholder = targetCh
          ? "Message #" + targetCh.replace(/^#/, "") + "\u2026"
          : "Type a message\u2026";
      }
    }
  } catch (_) {}
  /* Update composer target indicator (todo#364) */
  _updateComposerTarget(ch || lastActiveChannel, false);
  /* Update channel topic banner (todo#402) — show for active channel,
   * or last active when in all-channels mode */
  _updateChannelTopicBanner(ch || lastActiveChannel);
}

/* Friendly-label for a dm:<principal>|<principal> channel. Strips the
 * "dm:" prefix, splits on "|", drops the self principal when known, and
 * strips "agent:"/"human:" type prefixes so the result is "@name" (or
 * "@a, @b" when the self principal can't be determined). */
function _dmFriendlyLabel(ch) {
  if (!ch || ch.indexOf("dm:") !== 0) return ch || "";
  var parts = ch.substring(3).split("|");
  var self = window.__orochiUserName ? "human:" + window.__orochiUserName : "";
  var others = parts.filter(function (p) {
    return p && p !== self;
  });
  if (others.length === 0) others = parts;
  return others
    .map(function (p) {
      return "@" + p.replace(/^(agent:|human:)/, "");
    })
    .join(", ");
}
window._dmFriendlyLabel = _dmFriendlyLabel;

function _updateComposerTarget(ch, isReply, replyMsgId) {
  try {
    var el = document.getElementById("composer-target");
    var nameEl = document.getElementById("composer-target-name");
    if (!el || !nameEl) return;
    el.classList.remove("is-dm", "is-reply");
    if (isReply && replyMsgId) {
      el.classList.add("is-reply");
      nameEl.textContent =
        "\u21b3 reply in " + (ch || "#?") + " \u00b7 msg#" + replyMsgId;
      el.firstChild.nodeValue = "";
    } else if (ch && ch.startsWith("dm:")) {
      el.classList.add("is-dm");
      nameEl.textContent = "\u2192 " + _dmFriendlyLabel(ch) + " (DM)";
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

/* Fetch channel descriptions + prefs once on load */
document.addEventListener("DOMContentLoaded", function () {
  fetch(apiUrl("/api/channels/"), { credentials: "same-origin" })
    .then(function (r) {
      return r.json();
    })
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
  Object.assign((_channelPrefs[normCh] = _channelPrefs[normCh] || {}), patch);
  if (normCh !== ch) {
    /* mirror for legacy lookups */
    Object.assign((_channelPrefs[ch] = _channelPrefs[ch] || {}), patch);
  }
  fetch(apiUrl("/api/channel-prefs/"), {
    method: "PATCH",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": getCsrfToken(),
    },
    body: JSON.stringify(Object.assign({ channel: normCh }, patch)),
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
      var pinEl = el.querySelector(".ch-pin");
      if (pinEl) {
        pinEl.classList.toggle("ch-pin-on", !!pref.is_starred);
        pinEl.classList.toggle("ch-pin-off", !pref.is_starred);
        pinEl.setAttribute(
          "title",
          pref.is_starred ? "Unpin" : "Pin (float to top)",
        );
      }
      var watchEl = el.querySelector(".ch-watch");
      if (watchEl) {
        watchEl.classList.toggle("ch-watch-on", !pref.is_muted);
        watchEl.classList.toggle("ch-watch-off", !!pref.is_muted);
        watchEl.setAttribute(
          "title",
          pref.is_muted
            ? "Unmute (watch this channel)"
            : "Mute (stop notifications)",
        );
      }
      /* Keep the per-row eye icon (todo#418) in sync immediately after a
       * hide/unhide click so the user gets instant visual feedback before
       * fetchStats() re-renders the list. */
      var eyeEl = el.querySelector(".ch-eye");
      if (eyeEl) {
        eyeEl.classList.toggle("ch-eye-on", !pref.is_hidden);
        eyeEl.classList.toggle("ch-eye-off", !!pref.is_hidden);
        eyeEl.textContent = pref.is_hidden ? "\uD83D\uDEAB" : "\uD83D\uDC41";
        eyeEl.setAttribute(
          "title",
          pref.is_hidden
            ? "Show channel (un-hide)"
            : "Hide channel (dim in list)",
        );
      }
      el.classList.toggle("ch-starred", !!pref.is_starred);
      el.classList.toggle("ch-muted", !!pref.is_muted);
      el.classList.toggle("ch-hidden", !!pref.is_hidden);
      if (pref.is_hidden) el.setAttribute("data-hidden", "1");
      else el.removeAttribute("data-hidden");
    });
  }
  fetchStats();
}

/* Render the Starred section in the sidebar */
/* Sort starred list by sort_order (then alpha as tiebreaker) */
function _sortedStarred() {
  return Object.keys(_channelPrefs)
    .filter(function (ch) {
      return _channelPrefs[ch] && _channelPrefs[ch].is_starred;
    })
    .sort(function (a, b) {
      var oa = _channelPrefs[a] ? _channelPrefs[a].sort_order || 0 : 0;
      var ob = _channelPrefs[b] ? _channelPrefs[b].sort_order || 0 : 0;
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
  container.innerHTML = starred
    .map(function (ch) {
      var active = currentChannel === ch ? " active" : "";
      var muted =
        _channelPrefs[ch] && _channelPrefs[ch].is_muted ? " ch-muted" : "";
      var unread = channelUnread[ch] || 0;
      var badgeHtml =
        '<span class="ch-badge-slot">' +
        (unread > 0
          ? '<span class="unread-badge">' +
            (unread > 99 ? "99+" : unread) +
            "</span>"
          : "") +
        "</span>";
      return (
        '<div class="channel-item starred-item' +
        active +
        muted +
        '" data-channel="' +
        escapeHtml(ch) +
        '" draggable="true">' +
        '<span class="ch-drag-handle" title="Drag to reorder">&#8942;</span>' +
        '<span class="ch-pin ch-pin-on" data-ch="' +
        escapeHtml(ch) +
        '" title="Unpin (will drop from top)">\uD83D\uDCCC</span>' +
        '<span class="ch-name">' +
        escapeHtml(ch) +
        "</span>" +
        badgeHtml +
        "</div>"
      );
    })
    .join("");
  container.querySelectorAll(".channel-item").forEach(function (el) {
    el.addEventListener("click", function (ev) {
      if (
        ev.target.classList.contains("ch-pin") ||
        ev.target.classList.contains("ch-watch") ||
        ev.target.classList.contains("ch-drag-handle")
      )
        return;
      var ch = el.getAttribute("data-channel");
      setCurrentChannel(ch);
      loadChannelHistory(ch);
      if (typeof applyFeedFilter === "function") applyFeedFilter();
    });
    var star = el.querySelector(".ch-pin");
    if (star)
      star.addEventListener("click", function (ev) {
        ev.stopPropagation();
        var ch = star.getAttribute("data-ch");
        _setChannelPref(ch, { is_starred: false });
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

/* Nudge a just-appended fixed-position menu back inside the viewport.
 * Assumes `el` is already attached to the DOM with a {left,top} pair.
 * Keeps an 8px safety padding from all viewport edges so the outline
 * doesn't kiss the screen border. Called once right after appendChild.
 * ywatanabe 2026-04-19. */
function _repositionMenuInViewport(el) {
  if (!el) return;
  var pad = 8;
  var rect = el.getBoundingClientRect();
  if (rect.right > window.innerWidth - pad) {
    el.style.left = Math.max(pad, window.innerWidth - rect.width - pad) + "px";
  }
  if (rect.bottom > window.innerHeight - pad) {
    el.style.top = Math.max(pad, window.innerHeight - rect.height - pad) + "px";
  }
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
  menu.style.cssText =
    "position:fixed;z-index:9999;left:" + x + "px;top:" + y + "px;";
  /* Reserve a fixed-width glyph slot at the start of every row so the
   * channel-name / label column lines up whether a row has a prefix
   * (☆/★/🔇/🔔/⤓) or not. Without the empty placeholder, rows without a
   * glyph start flush-left and names jitter into misaligned columns.
   * todo#99. ywatanabe 2026-04-19. */
  var G_STAR_OFF = "\u2606"; /* ☆ */
  var G_STAR_ON = "\u2605"; /* ★ */
  var G_MUTE_OFF = "\uD83D\uDD14"; /* 🔔 bell — mute OFF (will mute on click) */
  var G_MUTE_ON = "\uD83D\uDD07"; /* 🔇 — currently muted */
  var G_EXPORT = "\u2935"; /* ⤵ export */
  var G_EMPTY = "";
  function _glyph(g) {
    return '<span class="ch-ctx-glyph">' + g + "</span>";
  }
  menu.innerHTML = [
    '<div class="ch-ctx-item" data-action="star">' +
      _glyph(starred ? G_STAR_ON : G_STAR_OFF) +
      (starred ? "Unstar" : "Star channel") +
      "</div>",
    '<div class="ch-ctx-item" data-action="mute">' +
      _glyph(muted ? G_MUTE_ON : G_MUTE_OFF) +
      (muted ? "Unmute" : "Mute channel") +
      "</div>",
    '<div class="ch-ctx-sep"></div>',
    '<div class="ch-ctx-label">Notifications</div>',
    '<div class="ch-ctx-item ch-ctx-notif' +
      (notif === "all" ? " ch-ctx-active" : "") +
      '" data-action="notif-all">' +
      _glyph(G_EMPTY) +
      "All messages</div>",
    '<div class="ch-ctx-item ch-ctx-notif' +
      (notif === "mentions" ? " ch-ctx-active" : "") +
      '" data-action="notif-mentions">' +
      _glyph(G_EMPTY) +
      "@ Mentions only</div>",
    '<div class="ch-ctx-item ch-ctx-notif' +
      (notif === "nothing" ? " ch-ctx-active" : "") +
      '" data-action="notif-nothing">' +
      _glyph(G_EMPTY) +
      "Nothing</div>",
    '<div class="ch-ctx-sep"></div>',
    '<div class="ch-ctx-item ch-ctx-export" data-action="export">' +
      _glyph(G_EXPORT) +
      "Export channel\u2026</div>",
    '<div class="ch-ctx-sep"></div>',
    '<div class="ch-ctx-item ch-ctx-hide" data-action="hide">' +
      _glyph(G_EMPTY) +
      (hidden ? "Show channel" : "Hide channel") +
      "</div>",
    '<div class="ch-ctx-sep"></div>',
    '<div class="ch-ctx-item ch-ctx-hide" data-action="topo-hide">' +
      _glyph(G_EMPTY) +
      "Hide node (Viz topology)" +
      "</div>",
  ].join("");
  document.body.appendChild(menu);
  _ctxMenu = menu;
  _repositionMenuInViewport(menu);

  menu.querySelectorAll(".ch-ctx-item").forEach(function (item) {
    item.addEventListener("click", function () {
      var action = item.getAttribute("data-action");
      if (action === "star") _setChannelPref(ch, { is_starred: !starred });
      else if (action === "mute") _setChannelPref(ch, { is_muted: !muted });
      else if (action === "notif-all")
        _setChannelPref(ch, { notification_level: "all" });
      else if (action === "notif-mentions")
        _setChannelPref(ch, { notification_level: "mentions" });
      else if (action === "notif-nothing")
        _setChannelPref(ch, { notification_level: "nothing" });
      else if (action === "export") {
        _hideChannelCtxMenu();
        openChannelExport(ch);
        return;
      } else if (action === "hide") _setChannelPref(ch, { is_hidden: !hidden });
      else if (action === "topo-hide") {
        if (typeof window._topoHide === "function") {
          try {
            window._topoHide("channel", ch);
          } catch (_) {}
        }
      }
      _hideChannelCtxMenu();
    });
  });

  /* Close on click outside — use 'click' (not 'mousedown') so the item's
   * own click handler fires before the menu is removed from the DOM.
   * Using mousedown removed the menu before click fired, silently eating
   * all item actions (star, hide, mute, etc.). */
  setTimeout(function () {
    document.addEventListener("click", _hideChannelCtxMenu, { once: true });
  }, 10);
}

function _hideChannelCtxMenu() {
  if (_ctxMenu) {
    _ctxMenu.remove();
    _ctxMenu = null;
  }
}

/* ── Agent-row context menu (right-click on sidebar or Agents overview) ──
 * Offers: subscribe to channel (read-only / read-write), open/create DM
 * with another agent (unidirectional readonly or bidirectional read-write),
 * and unsubscribe from a currently-joined channel. Mirrors the channel
 * ctx-menu pattern above, but adds hover submenus.
 */
var _agentCtxMenu = null;
function _hideAgentCtxMenu() {
  if (_agentCtxMenu) {
    _agentCtxMenu.remove();
    _agentCtxMenu = null;
  }
  /* The hover submenu (Add/DM/Remove/etc.) is a separate DOM node
   * outside _agentCtxMenu. Without this, picking a submenu item
   * closes the parent menu but leaves the submenu floating on
   * screen. ywatanabe 2026-04-19: "subscribed #general but why the
   * menu keeps shown?". */
  if (window._agentCtxSubMenu) {
    try {
      window._agentCtxSubMenu.remove();
    } catch (_e) {}
    window._agentCtxSubMenu = null;
  }
  document.removeEventListener("keydown", _agentCtxKeyHandler, true);
}
function _agentCtxKeyHandler(ev) {
  if (ev.key === "Escape") _hideAgentCtxMenu();
}

function _addAgentContextMenu(el) {
  el.addEventListener("contextmenu", function (ev) {
    /* Only intercept plain right-click — let devtools through on Shift+RMB */
    if (ev.shiftKey) return;
    ev.preventDefault();
    ev.stopPropagation();
    var name =
      el.getAttribute("data-agent-name") || el.getAttribute("data-agent");
    if (!name) return;
    _showAgentContextMenu(name, ev.clientX, ev.clientY);
  });
}

function _showAgentContextMenu(agent, x, y) {
  _hideAgentCtxMenu();
  _hideChannelCtxMenu();
  var agents = Array.isArray(window.__lastAgents) ? window.__lastAgents : [];
  var self = agents.find(function (a) {
    return a && a.name === agent;
  }) || { name: agent, channels: [] };
  var curChannels = Array.isArray(self.channels) ? self.channels : [];
  var curSet = {};
  curChannels.forEach(function (c) {
    curSet[c] = true;
    curSet[c.charAt(0) === "#" ? c : "#" + c] = true;
  });

  var menu = document.createElement("div");
  menu.className = "ch-ctx-menu agent-ctx-menu";
  menu.style.cssText =
    "position:fixed;z-index:10000;left:" + x + "px;top:" + y + "px;";
  /* Human users (the signed-in ywatanabe) can't be hidden from the
   * topology — the canvas needs them as a node origin for post
   * animations. Suppress the "Hide node" row for them so we don't
   * advertise a no-op. */
  var humanName =
    (typeof userName !== "undefined" && userName) ||
    window.__orochiUserName ||
    "";
  var canHide = !humanName || agent !== humanName;
  var hideRow = canHide
    ? '<div class="ch-ctx-sep"></div>' +
      '<div class="ch-ctx-item ch-ctx-hide" data-topo-hide="1">' +
      "Hide node (Viz topology)</div>"
    : "";
  menu.innerHTML = [
    '<div class="ch-ctx-label">Agent: ' + escapeHtml(agent) + "</div>",
    '<div class="ch-ctx-item ch-ctx-sub" data-sub="add">Add to channel&nbsp;&hellip; &#9656;</div>',
    '<div class="ch-ctx-item ch-ctx-sub" data-sub="dm">DM with agent&nbsp;&hellip; &#9656;</div>',
    '<div class="ch-ctx-sep"></div>',
    '<div class="ch-ctx-item ch-ctx-sub ch-ctx-hide" data-sub="remove">Remove from channel&nbsp;&hellip; &#9656;</div>',
    hideRow,
  ].join("");
  document.body.appendChild(menu);
  _agentCtxMenu = menu;
  _repositionMenuInViewport(menu);
  /* Wire the flat "Hide node" row (not a submenu). */
  var hideItem = menu.querySelector('.ch-ctx-item[data-topo-hide="1"]');
  if (hideItem) {
    hideItem.addEventListener("click", function (ev) {
      ev.stopPropagation();
      if (typeof window._topoHide === "function")
        window._topoHide("agent", agent);
      _hideAgentCtxMenu();
    });
  }

  var subEl = null;
  function openSub(anchor, html, onPick) {
    if (subEl) subEl.remove();
    subEl = document.createElement("div");
    subEl.className = "ch-ctx-menu agent-ctx-submenu";
    var r = anchor.getBoundingClientRect();
    subEl.style.cssText =
      "position:fixed;z-index:10001;left:" +
      (r.right + 2) +
      "px;top:" +
      r.top +
      "px;max-height:60vh;overflow-y:auto;";
    subEl.innerHTML = html;
    document.body.appendChild(subEl);
    window._agentCtxSubMenu = subEl;
    /* Viewport-aware flip: if the submenu would overflow the right
     * edge, flip it to the left of the anchor instead of the right.
     * If it would overflow the bottom, nudge it up. Keep 8px padding
     * from all viewport edges. ywatanabe 2026-04-19. */
    var pad = 8;
    var sr = subEl.getBoundingClientRect();
    if (sr.right > window.innerWidth - pad) {
      var flipped = r.left - sr.width - 2;
      subEl.style.left =
        Math.max(
          pad,
          flipped >= pad ? flipped : window.innerWidth - sr.width - pad,
        ) + "px";
    }
    sr = subEl.getBoundingClientRect();
    if (sr.bottom > window.innerHeight - pad) {
      subEl.style.top =
        Math.max(pad, window.innerHeight - sr.height - pad) + "px";
    }
    subEl.querySelectorAll("[data-pick]").forEach(function (it) {
      it.addEventListener("click", function (ev) {
        ev.stopPropagation();
        onPick(it);
        _hideAgentCtxMenu();
      });
    });
  }
  function permRow(label, attrs) {
    /* attrs: {ro: {...}, rw: {...}} — each merged into the span as data-*.
     * Produces a <div> with label + RO/RW picker spans. */
    function dataAttrs(o) {
      var out = ' data-pick="1"';
      for (var k in o) out += " data-" + k + '="' + o[k] + '"';
      return out;
    }
    return (
      '<div class="ch-ctx-item ch-ctx-row">' +
      '<span class="ch-ctx-rowname">' +
      label +
      "</span>" +
      '<span class="ch-ctx-perm"' +
      dataAttrs(attrs.ro) +
      ' title="read-only">RO</span>' +
      '<span class="ch-ctx-perm ch-ctx-perm-rw"' +
      dataAttrs(attrs.rw) +
      ' title="read-write">RW</span>' +
      "</div>"
    );
  }

  menu.querySelectorAll(".ch-ctx-sub").forEach(function (item) {
    item.addEventListener("mouseenter", function () {
      var kind = item.getAttribute("data-sub");
      var empty = '<div class="ch-ctx-label">(none)</div>';
      if (kind === "add") {
        /* Only show #-prefixed entries; _channelPrefs may also carry
         * legacy bare-name mirrors that would duplicate the row. */
        var chs = Object.keys(_channelPrefs || {})
          .filter(function (c) {
            return c && c.charAt(0) === "#" && !curSet[c];
          })
          .sort();
        if (!chs.length) return openSub(item, empty, function () {});
        var html = chs
          .map(function (c) {
            var e = escapeHtml(c);
            return permRow(e, {
              ro: { ch: e, perm: "read-only" },
              rw: { ch: e, perm: "read-write" },
            });
          })
          .join("");
        openSub(item, html, function (p) {
          _agentSubscribe(
            agent,
            p.getAttribute("data-ch"),
            p.getAttribute("data-perm"),
          );
        });
      } else if (kind === "dm") {
        /* One-click DM: the backend lazy-creates the channel on first
         * send (commit 3dac12f), so we skip the RO/RW permission picker
         * and just navigate to the Chat tab with the canonical channel
         * selected. ywatanabe 2026-04-19: DM submenu was overkill. */
        var others = agents
          .filter(function (a) {
            return a && a.name && a.name !== agent;
          })
          .sort(function (a, b) {
            return (a.name || "").localeCompare(b.name || "");
          });
        if (!others.length) return openSub(item, empty, function () {});
        var html2 = others
          .map(function (a) {
            var nm = escapeHtml(a.name);
            return (
              '<div class="ch-ctx-item" data-pick="1" data-other="' +
              nm +
              '">@' +
              nm +
              "</div>"
            );
          })
          .join("");
        openSub(item, html2, function (p) {
          _openAgentDmSimple(agent, p.getAttribute("data-other"));
        });
      } else if (kind === "remove") {
        var rm = curChannels
          .filter(function (c) {
            return c && c.indexOf("dm:") !== 0;
          })
          .sort();
        if (!rm.length) return openSub(item, empty, function () {});
        var html3 = rm
          .map(function (c) {
            var e = escapeHtml(c);
            return (
              '<div class="ch-ctx-item ch-ctx-hide" data-pick="1" data-ch="' +
              e +
              '">' +
              e +
              "</div>"
            );
          })
          .join("");
        openSub(item, html3, function (p) {
          _toggleAgentChannelSubscription(
            agent,
            p.getAttribute("data-ch"),
            false,
          );
        });
      }
    });
  });

  /* Close on outside click / Escape. Mousedown on menu/submenu swallowed
   * so item clicks still dispatch before dismissal. */
  setTimeout(function () {
    document.addEventListener(
      "click",
      function onDocClick(ev) {
        if (
          _agentCtxMenu &&
          !_agentCtxMenu.contains(ev.target) &&
          !(subEl && subEl.contains(ev.target))
        ) {
          document.removeEventListener("click", onDocClick, true);
          _hideAgentCtxMenu();
        }
      },
      true,
    );
    document.addEventListener("keydown", _agentCtxKeyHandler, true);
  }, 10);
}

/* POST /api/channel-members/ with a chosen permission. Reuses the same
 * endpoint as _toggleAgentChannelSubscription but passes the permission
 * body field (see hub/views/api.py api_channel_members). */
function _agentSubscribe(agentName, channel, permission) {
  var username = _agentDjangoUsername(agentName);
  if (!username || !channel) return Promise.resolve();
  var body = JSON.stringify({
    channel: channel,
    username: username,
    permission: permission || "read-write",
  });
  return fetch(apiUrl("/api/channel-members/"), {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": getCsrfToken(),
    },
    body: body,
  })
    .then(function (res) {
      if (!res.ok) {
        return res.text().then(function (t) {
          throw new Error(res.status + ": " + (t || "").slice(0, 200));
        });
      }
      return res.json();
    })
    .then(function () {
      _showMiniToast(
        "Subscribed " + agentName + " → " + channel + " (" + permission + ")",
        "ok",
      );
      if (typeof fetchAgentsThrottled === "function") fetchAgentsThrottled();
      else if (typeof fetchAgents === "function") fetchAgents();
    })
    .catch(function (e) {
      _showMiniToast("Subscribe failed: " + e.message, "err");
    });
}

/* Open the canonical agent↔agent DM channel in the Chat tab without
 * calling /api/dms/. The backend lazy-creates the channel on first
 * message send (commit 3dac12f), so this is a pure navigation op:
 *   - canonical channel name: dm:agent:<A>|agent:<B> with names sorted
 *   - select it as current channel, load history (empty until first send)
 *   - switch to Chat tab
 * ywatanabe 2026-04-19: DM submenu RO/RW picker was overkill — clicking
 * "@other-agent" should just open the conversation. */
function _openAgentDmSimple(agentA, agentB) {
  if (!agentA || !agentB || agentA === agentB) return;
  var pair = [agentA, agentB].sort();
  var channel = "dm:agent:" + pair[0] + "|agent:" + pair[1];
  if (typeof setCurrentChannel === "function") setCurrentChannel(channel);
  if (typeof loadChannelHistory === "function") loadChannelHistory(channel);
  if (typeof _activateTab === "function") _activateTab("chat");
}
window._openAgentDmSimple = _openAgentDmSimple;

/* Create a DM channel between two agents with a direction policy.
 * dir = "rw": both agents subscribed read-write (bidirectional)
 * dir = "ro": self=read-only, other=read-write (self can only read) */
function _agentDmCreate(selfAgent, otherAgent, dir) {
  if (!selfAgent || !otherAgent || selfAgent === otherAgent) return;
  /* Canonical channel name: dm:agent:<A>|agent:<B> with names sorted so
   * A↔B and B↔A collapse to a single channel. */
  var pair = [selfAgent, otherAgent].sort();
  var channel = "dm:agent:" + pair[0] + "|agent:" + pair[1];
  var selfPerm = dir === "ro" ? "read-only" : "read-write";
  var otherPerm = "read-write";
  _agentSubscribe(selfAgent, channel, selfPerm).then(function () {
    _agentSubscribe(otherAgent, channel, otherPerm);
  });
}

/* ── Channel export modal ── */
function openChannelExport(ch) {
  var modal = document.getElementById("channel-export-modal");
  if (!modal) return;
  var now = new Date();
  var todayStart = now.toISOString().slice(0, 10) + "T00:00";
  var todayNow = now.toISOString().slice(0, 16);
  document.getElementById("ch-export-from").value = todayStart;
  document.getElementById("ch-export-to").value = todayNow;
  document.getElementById("ch-export-format").value = "json";
  modal.setAttribute("data-channel", ch || currentChannel || "");
  document.getElementById("ch-export-title").textContent =
    "Export " + (ch || currentChannel || "channel");
  modal.style.display = "flex";
}

function closeChannelExport() {
  var modal = document.getElementById("channel-export-modal");
  if (modal) modal.style.display = "none";
}

function doChannelExport() {
  var modal = document.getElementById("channel-export-modal");
  if (!modal) return;
  var ch = modal.getAttribute("data-channel");
  var from = document.getElementById("ch-export-from").value;
  var to = document.getElementById("ch-export-to").value;
  var fmt = document.getElementById("ch-export-format").value;
  if (!ch) {
    alert("No channel selected.");
    return;
  }
  /* Build URL: /api/channels/<chat_id>/export/?format=...&from=...&to=...&token=... */
  var chatId = ch.replace(/^#/, "");
  var url =
    "/api/channels/" +
    encodeURIComponent(chatId) +
    "/export/?format=" +
    encodeURIComponent(fmt);
  if (from) url += "&from=" + encodeURIComponent(from);
  if (to) url += "&to=" + encodeURIComponent(to);
  if (token) url += "&token=" + encodeURIComponent(token);
  var a = document.createElement("a");
  a.href = url;
  a.download = chatId + "-export." + fmt;
  document.body.appendChild(a);
  a.click();
  a.remove();
  closeChannelExport();
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
      _dndState = { el: el, section: section };
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
      if (!_dndState || _dndState.section !== section || el === _dndState.el)
        return;
      /* Insert dragged item before drop target */
      var items = Array.from(
        container.querySelectorAll(".channel-item[draggable]"),
      );
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
      var reordered = Array.from(
        container.querySelectorAll(".channel-item[draggable]"),
      );
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
            headers: {
              "Content-Type": "application/json",
              "X-CSRFToken": getCsrfToken(),
            },
            body: JSON.stringify({ channel: ch, sort_order: idx * 10 }),
          }).catch(function (_) {});
        }
      });
      el.classList.remove("ch-drop-target");
    });
  });
}

/* ── todo#49: agent ↔ channel subscription DnD helpers ── */
function _agentHasChannel(channelsCsv, channel) {
  if (!channel) return false;
  var norm = channel.charAt(0) === "#" ? channel : "#" + channel;
  var bare = channel.charAt(0) === "#" ? channel.slice(1) : channel;
  var list = String(channelsCsv || "")
    .split(",")
    .map(function (s) {
      return s.trim();
    })
    .filter(Boolean);
  for (var i = 0; i < list.length; i++) {
    var v = list[i];
    if (v === channel || v === norm || v === bare || v === "#" + bare)
      return true;
  }
  return false;
}

function _setChannelDropHint(el, text) {
  var hint = el.querySelector(".ch-hint");
  if (!hint) {
    hint = document.createElement("span");
    hint.className = "ch-hint";
    el.appendChild(hint);
  }
  hint.textContent = text;
}

function _agentDjangoUsername(name) {
  /* Mirrors hub/views/api.py: re.sub(r"[^a-zA-Z0-9_.\-]", "-", name) */
  if (!name) return "";
  var safe = String(name).replace(/[^a-zA-Z0-9_.\-]/g, "-");
  return "agent-" + safe;
}

function _showMiniToast(text, kind) {
  var el = document.getElementById("orochi-mini-toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "orochi-mini-toast";
    document.body.appendChild(el);
  }
  el.className = "";
  if (kind) el.classList.add(kind);
  el.textContent = text;
  /* force reflow so transition re-fires when toast shown twice in a row */
  void el.offsetWidth;
  el.classList.add("visible");
  if (el._hideTimer) clearTimeout(el._hideTimer);
  el._hideTimer = setTimeout(function () {
    el.classList.remove("visible");
  }, 2200);
}

function _toggleAgentChannelSubscription(agentName, channel, subscribe) {
  var username = _agentDjangoUsername(agentName);
  if (!username || !channel) return;
  var method = subscribe ? "POST" : "DELETE";
  var body = JSON.stringify({ channel: channel, username: username });
  var url = apiUrl("/api/channel-members/");
  fetch(url, {
    method: method,
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": getCsrfToken(),
    },
    body: body,
  })
    .then(function (res) {
      if (!res.ok) {
        return res
          .json()
          .catch(function () {
            return { error: res.status };
          })
          .then(function (j) {
            var msg =
              (j && j.error) || "HTTP " + res.status + " — check permissions";
            _showMiniToast(
              (subscribe ? "Subscribe failed: " : "Unsubscribe failed: ") + msg,
              "err",
            );
            throw new Error(msg);
          });
      }
      return res.json();
    })
    .then(function () {
      _showMiniToast(
        (subscribe ? "Subscribed " : "Unsubscribed ") +
          agentName +
          (subscribe ? " → " : " ← ") +
          channel,
        "ok",
      );
      /* Registry heartbeat takes up to ~2s to re-propagate agent.channels;
       * force an immediate refresh so the UI reflects the change and a
       * subsequent drag sees the latest subscription state. */
      if (typeof fetchAgentsThrottled === "function") {
        fetchAgentsThrottled();
      } else if (typeof fetchAgents === "function") {
        fetchAgents();
      }
    })
    .catch(function (_) {});
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
function getCsrfToken() {
  return window.__orochiCsrfToken || csrfToken || "";
}
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

/* Collapse agent-name redundancy:
 *
 *  - "head@mba@Host"             → "head@mba"     (strip extra @host)
 *  - "head-mba@mba"              → "head@mba"     (role-host@host)
 *  - "healer-ywata-note-win@ywata-note-win"
 *                                → "healer@ywata-note-win"
 *  - "mamba-todo-manager-mba@mba"→ "mamba-todo-manager@mba"
 *  - "expert-scitex@ywata-note-win" → unchanged (no duplicated host)
 *
 * Rationale: agent IDs are registered as "<role>-<host>" because the
 * agent-container config generates them that way (head.yaml on mba ⇒
 * "head-mba"), but the dashboard already shows "@<host>" separately,
 * so the duplication just adds noise. This renderer-level fix keeps
 * the registered IDs intact and only affects display. */
function cleanAgentName(name) {
  if (!name) return name;
  var parts = name.split("@");
  if (parts.length >= 3) {
    /* Legacy double-@ form: "head@mba@Host" → "head@mba". Re-enter so
     * the role-host dedupe below also runs on the survivor. */
    name = parts[0] + "@" + parts[1];
    parts = name.split("@");
  }
  if (parts.length === 2) {
    var lead = parts[0];
    var host = parts[1];
    var suffix = "-" + host;
    if (host && lead.length > suffix.length && lead.endsWith(suffix)) {
      return lead.slice(0, -suffix.length) + "@" + host;
    }
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
  /* Always pipe the constructed "<name>@<host>" string through
   * cleanAgentName so the role-host suffix gets collapsed
   * (head-mba@mba → head@mba). The earlier form returned the raw
   * concatenation and the dedupe never fired. */
  return host ? cleanAgentName(name + "@" + host) : name;
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
    if (
      (msg.sender === "hub" || msg.sender === "system") &&
      msg.metadata &&
      msg.metadata.type === "status_probe"
    )
      return;
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
    /* Topology view — pulse a glowing packet along the edge from the
     * sender to the channel so the map animates as traffic flows.
     * Silently no-ops when topology isn't visible. */
    if (typeof _topoPulseEdge === "function") {
      var _topoCh = msg.channel || (msg.payload && msg.payload.channel) || "";
      var _topoAttach =
        (msg.metadata && msg.metadata.attachments) ||
        (msg.payload && msg.payload.attachments) ||
        [];
      var _topoIsArtifact =
        Array.isArray(_topoAttach) && _topoAttach.length > 0;
      /* Babble text — first ~60 chars of the message ride the packet as
       * a small speech-bubble. For attachment-only posts we show a
       * paperclip glyph so the packet is never silent. _topoSpawnPacket
       * does the final truncation and ellipsis. */
      var _topoText = msg.text || (msg.payload && msg.payload.content) || "";
      if (!_topoText && _topoIsArtifact) {
        _topoText = "\uD83D\uDCCE attachment";
      }
      if (window.__topoPulseDebug !== false && _topoCh.indexOf("dm:") === 0) {
        var _dmNow = new Date();
        console.info(
          "%c[topo-pulse] DM received",
          "color:#fbbf24;font-weight:700",
          _dmNow.toISOString().slice(11, 23) + " (" + _dmNow.getTime() + "ms)",
          "sender=" + msg.sender,
          "channel=" + _topoCh,
        );
      }
      _topoPulseEdge(msg.sender, _topoCh, {
        isArtifact: _topoIsArtifact,
        text: _topoText,
      });
    }
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
    msg.type === "agent_info" ||
    msg.type === "agent_pong"
  ) {
    fetchAgentsThrottled();
    fetchStatsThrottled();
    fetchResources();
    /* todo#47 — if the Agents tab currently has a detail view open
     * for the agent that just sent an info/pong, invalidate that
     * view's cache so pane_tail / RTT / last_action refresh live. */
    if (
      (msg.type === "agent_info" ||
        msg.type === "agent_pong" ||
        msg.type === "agent_presence") &&
      typeof window.onAgentInfoEvent === "function"
    ) {
      window.onAgentInfoEvent(msg.agent);
    }
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
        try {
          msgInput.setSelectionRange(savedStart, savedEnd);
        } catch (e) {}
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
    /* Sidebar agent rows mirror the Agents-tab overview one-liner so the
     * two stay visually in sync (ywatanabe 2026-04-19). Same columns:
     *   [pin][ws-led][fn-led][state-badge-compact][name@host]
     * Compact widths so it fits in the ~260px sidebar. Visibility rule
     * matches the overview: offline agents are hidden unless pinned. */
    var connected = function (x) {
      return (x.status || "online") !== "offline";
    };
    var _computeStateLocal = function (a) {
      var pane = a.pane_state || "";
      if (pane === "compacting" || pane === "auto_compact") return "compacting";
      if (
        pane === "y_n_prompt" ||
        pane === "compose_pending_unsent" ||
        pane === "auth_error" ||
        pane === "mcp_broken" ||
        pane === "stuck"
      )
        return "selecting";
      if (!connected(a)) return "offline";
      var lastToolName = String(a.last_tool_name || "").toLowerCase();
      if (lastToolName.indexOf("compact") !== -1) return "compacting";
      var lastToolSec =
        a.last_tool_at || a.last_action
          ? (Date.now() - new Date(a.last_tool_at || a.last_action).getTime()) /
            1000
          : null;
      if (lastToolSec != null && lastToolSec < 30) return "running";
      return "idle";
    };
    var sidebarVisible = agents.filter(function (a) {
      return connected(a) || !!a.pinned;
    });
    container.innerHTML = sidebarVisible
      .map(function (a) {
        var liveness = a.liveness || (connected(a) ? "online" : "offline");
        var state = _computeStateLocal(a);
        var ghostClass =
          !connected(a) && a.pinned ? " sidebar-agent-ghost" : "";
        var rawName = a.name || "";
        /* todo#96: route identity (icon, color, display-name, tooltip)
         * through the shared agentIdentity helper so the sidebar row,
         * Activity pool chip and canvas node all agree. Falls back to
         * the legacy inline derivation when the helper hasn't loaded
         * yet (e.g. during very early bootstrap). */
        var ident =
          typeof agentIdentity === "function"
            ? agentIdentity(a)
            : {
                displayName: hostedAgentName(a),
                color:
                  typeof _colorKeyFor === "function"
                    ? getAgentColor(_colorKeyFor(a))
                    : getAgentColor(a.name),
                tooltip:
                  (a.agent_id || rawName) +
                  " (" +
                  (a.machine || "unknown") +
                  ")",
                iconHtml: function () {
                  return "";
                },
              };
        var chList = Array.isArray(a.channels) ? a.channels.join(",") : "";
        var pinOn = a.pinned ? " activity-pin-on" : "";
        var pinTitle = a.pinned
          ? "Unpin"
          : "Pin (keeps as ghost when offline, floats to top)";
        return (
          '<div class="agent-card sidebar-agent-row' +
          ghostClass +
          '" data-agent-name="' +
          escapeHtml(rawName) +
          '" data-agent-channels="' +
          escapeHtml(chList) +
          '" draggable="true" title="' +
          escapeHtml(ident.tooltip) +
          '">' +
          '<button type="button" class="activity-pin-btn pin-btn' +
          pinOn +
          (a.pinned ? " pinned" : "") +
          '" data-pin-name="' +
          escapeHtml(rawName) +
          '" data-pin-next="' +
          (a.pinned ? "false" : "true") +
          '" title="' +
          escapeHtml(pinTitle) +
          '">\uD83D\uDCCC</button>' +
          '<span class="sidebar-agent-icon">' +
          ident.iconHtml(14) +
          "</span>" +
          '<span class="activity-led activity-led-ws activity-led-ws-' +
          (connected(a) ? "on" : "off") +
          '"></span>' +
          '<span class="activity-led activity-led-fn activity-led-fn-' +
          liveness +
          '"></span>' +
          '<span class="activity-state activity-state-compact activity-state-' +
          state +
          '">' +
          escapeHtml(state.toUpperCase()) +
          "</span>" +
          '<span class="agent-name" style="color:' +
          ident.color +
          '">' +
          escapeHtml(ident.displayName) +
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
        /* todo#49: drag agent card onto a channel to subscribe / unsubscribe. */
        el.addEventListener("dragstart", function (ev) {
          var n = el.getAttribute("data-agent-name") || "";
          var chs = el.getAttribute("data-agent-channels") || "";
          el.classList.add("agent-dragging");
          try {
            ev.dataTransfer.effectAllowed = "link";
            ev.dataTransfer.setData("application/x-orochi-agent", n);
            ev.dataTransfer.setData("text/plain", n);
            /* Carry current subscriptions so the drop handler can render
             * add/remove affordance without an extra fetch. */
            ev.dataTransfer.setData("application/x-orochi-agent-channels", chs);
          } catch (e) {}
          window.__orochiDragAgent = { name: n, channels: chs };
        });
        el.addEventListener("dragend", function () {
          el.classList.remove("agent-dragging");
          window.__orochiDragAgent = null;
          document
            .querySelectorAll(
              ".channel-item.drop-target-agent-add,.channel-item.drop-target-agent-remove",
            )
            .forEach(function (t) {
              t.classList.remove("drop-target-agent-add");
              t.classList.remove("drop-target-agent-remove");
              var hint = t.querySelector(".ch-hint");
              if (hint) hint.remove();
            });
        });
        el.addEventListener("click", function (ev) {
          if (ev.target.closest(".pin-btn")) return; /* handled separately */
          if (ev.target.closest(".kill-btn")) return; /* handled separately */
          if (ev.target.closest(".restart-btn"))
            return; /* handled separately */
          if (ev.target.closest(".avatar-clickable"))
            return; /* handled below */
          var multi = ev.ctrlKey || ev.metaKey;
          /* todo#274 Part 2: Ctrl/Cmd+Click toggles multi-select. */
          if (multi) {
            el.classList.toggle("selected");
          } else {
            /* todo#274 Part 1: single-select highlight (toggle on 2nd click). */
            var cards = container.querySelectorAll(
              ".agent-card[data-agent-name]",
            );
            var wasSelected = el.classList.contains("selected");
            cards.forEach(function (c) {
              c.classList.remove("selected");
            });
            if (!wasSelected) el.classList.add("selected");
          }
          if (typeof applyFeedFilter === "function") applyFeedFilter();
        });
        /* Right-click: open agent context menu (channel subscribe / DM). */
        _addAgentContextMenu(el);
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
      try {
        msgInput.setSelectionRange(savedStart, savedEnd);
      } catch (e) {}
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
  if (
    !confirm(
      "Kill agent " +
        name +
        "?\nThis will terminate screen, bun sidecar, and disconnect.",
    )
  )
    return;
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
    var newStatsJson = JSON.stringify(stats.channels);
    if (chContainer._lastStatsJson === newStatsJson) return;
    chContainer._lastStatsJson = newStatsJson;
    var msgInput = document.getElementById("msg-input");
    var inputHasFocus = msgInput && document.activeElement === msgInput;
    var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
    var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
    /* Preserve Ctrl+Click multi-select state across re-renders (#274 Part 2) */
    var prevSelected = {};
    chContainer
      .querySelectorAll(".channel-item.selected")
      .forEach(function (el) {
        var ch = el.getAttribute("data-channel");
        if (ch) prevSelected[ch] = true;
      });
    /* todo#325: hide dm:* channels from the public Channels list
     * (they still render in the DM tab via its own path).
     * todo#326: normalize "general" -> "#general" and dedupe by
     * normalized name so legacy rows collapse into a single entry. */
    var seenNames = {};
    var displayChannels = [];
    /* todo#418: hidden channels always render, but dimmed at the bottom of
     * the Channels section. Clicking a dimmed row un-hides it. No separate
     * toggle UI or per-row eye button — just a subtle visual sort-to-bottom
     * so the list stays scannable. */
    stats.channels.forEach(function (c) {
      if (typeof c !== "string") return;
      if (c.indexOf("dm:") === 0) return;
      var norm = c.charAt(0) === "#" ? c : "#" + c;
      if (seenNames[norm]) return;
      seenNames[norm] = true;
      var pref = _channelPrefs[norm] || _channelPrefs[c] || {};
      displayChannels.push({
        raw: c,
        norm: norm,
        hidden: !!pref.is_hidden,
      });
    });
    /* Also include channels that only exist in _channelPrefs with is_hidden
     * (e.g. deleted from server list but kept for un-hiding). */
    Object.keys(_channelPrefs).forEach(function (ch) {
      if (typeof ch !== "string") return;
      if (ch.indexOf("dm:") === 0) return;
      var pref = _channelPrefs[ch];
      if (!pref || !pref.is_hidden) return;
      var norm = ch.charAt(0) === "#" ? ch : "#" + ch;
      if (seenNames[norm]) return;
      seenNames[norm] = true;
      displayChannels.push({ raw: ch, norm: norm, hidden: true });
    });
    /* Sort: starred first, then visible, then hidden rows at bottom. */
    displayChannels.sort(function (a, b) {
      if (!!a.hidden !== !!b.hidden) return a.hidden ? 1 : -1;
      var pa = _channelPrefs[a.norm] || _channelPrefs[a.raw] || {};
      var pb = _channelPrefs[b.norm] || _channelPrefs[b.raw] || {};
      var aStarred = pa.is_starred ? 0 : 1;
      var bStarred = pb.is_starred ? 0 : 1;
      if (aStarred !== bStarred) return aStarred - bStarred;
      var oa = pa.sort_order != null ? pa.sort_order : 9999;
      var ob = pb.sort_order != null ? pb.sort_order : 9999;
      return oa !== ob ? oa - ob : a.norm.localeCompare(b.norm);
    });
    /* Track first-hidden index so we can drop a subtle divider before
     * the hidden block (todo#418). */
    var firstHiddenIdx = -1;
    for (var _i = 0; _i < displayChannels.length; _i++) {
      if (displayChannels[_i].hidden) {
        firstHiddenIdx = _i;
        break;
      }
    }
    /* todo#71: tree-structured channel hierarchy via "/" path segments.
     * Channels named like "proj/ripple-wm" are grouped under a collapsible
     * "proj" folder header. Starred (pinned) channels remain flat at the
     * top — pinning means "always visible". Hidden channels also stay flat
     * at the bottom (already visually separated by the divider).
     *
     * No backend change. `mkdir` is a no-op (folder appears when first
     * child is added). `mv` is just a channel rename (deferred until a
     * rename API exists). Collapse state persists in localStorage so
     * refreshes keep the user's folders closed/open as they left them. */
    var _treeCollapsed = {};
    try {
      var _raw = localStorage.getItem("orochi.channelTreeCollapsed");
      if (_raw) _treeCollapsed = JSON.parse(_raw) || {};
    } catch (_) {
      _treeCollapsed = {};
    }
    /* Parse "#proj/ripple-wm" -> { folder: "proj", leaf: "#ripple-wm" }.
     * Returns null if the channel has no folder (top-level). Only splits
     * on the FIRST "/" to keep it simple — deeply nested trees can be
     * added later if needed. */
    function _splitChannelPath(norm) {
      if (typeof norm !== "string" || norm.length === 0) return null;
      /* Strip leading "#" then look for "/" */
      var bare = norm.charAt(0) === "#" ? norm.slice(1) : norm;
      var slash = bare.indexOf("/");
      if (slash <= 0 || slash === bare.length - 1) return null;
      return {
        folder: bare.slice(0, slash),
        leaf: "#" + bare.slice(slash + 1),
      };
    }
    /* Walk displayChannels in sorted order and emit an interleaved list of
     * folder-header rows + channel rows. Only non-starred, non-hidden
     * channels are tree-ified; starred stays pinned flat at the top, and
     * hidden stays dimmed flat at the bottom. */
    var _currentFolder = null;
    var _renderRows = [];
    for (var _ri = 0; _ri < displayChannels.length; _ri++) {
      var _e = displayChannels[_ri];
      var _epref = _channelPrefs[_e.norm] || _channelPrefs[_e.raw] || {};
      var _isStarred = !!_epref.is_starred;
      var _isHidden = !!_e.hidden;
      var _split =
        !_isStarred && !_isHidden ? _splitChannelPath(_e.norm) : null;
      if (_split) {
        if (_currentFolder !== _split.folder) {
          _currentFolder = _split.folder;
          _renderRows.push({
            type: "folder",
            prefix: _split.folder,
            collapsed: !!_treeCollapsed[_split.folder],
          });
        }
        if (_treeCollapsed[_split.folder]) {
          /* Child hidden by collapsed folder — skip rendering the row. */
          continue;
        }
        _renderRows.push({
          type: "channel",
          entry: _e,
          origIdx: _ri,
          inFolder: _split.folder,
          leafLabel: _split.leaf,
        });
      } else {
        _currentFolder = null;
        _renderRows.push({
          type: "channel",
          entry: _e,
          origIdx: _ri,
          inFolder: null,
          leafLabel: _e.norm,
        });
      }
    }
    chContainer.innerHTML = _renderRows
      .map(function (row) {
        if (row.type === "folder") {
          var chev = row.collapsed ? "\u25B8" : "\u25BE"; /* ▸ ▾ */
          var ficon = row.collapsed
            ? "\uD83D\uDCC1"
            : "\uD83D\uDCC2"; /* 📁 📂 */
          return (
            '<div class="channel-folder' +
            (row.collapsed ? " collapsed" : "") +
            '" data-folder="' +
            escapeHtml(row.prefix) +
            '" title="Click to ' +
            (row.collapsed ? "expand" : "collapse") +
            ' folder">' +
            '<span class="ch-folder-chev">' +
            chev +
            "</span>" +
            '<span class="ch-folder-icon">' +
            ficon +
            "</span>" +
            '<span class="ch-folder-name">' +
            escapeHtml(row.prefix) +
            "/</span>" +
            "</div>"
          );
        }
        var entry = row.entry;
        var i = row.origIdx;
        var c = entry.raw;
        var norm = entry.norm;
        var active = currentChannel === c ? " active" : "";
        var pref = _channelPrefs[norm] || _channelPrefs[c] || {};
        var muted = pref.is_muted ? " ch-muted" : "";
        /* Star = float-to-top (pinned). ★ filled for starred, ☆ outline
         * for unstarred. Replaces the earlier 📌 pin emoji so both canvas
         * pool chips and this list use a single standardized icon. */
        var starHtml =
          '<span class="ch-pin ' +
          (pref.is_starred ? "ch-pin-on" : "ch-pin-off") +
          '" data-ch="' +
          escapeHtml(norm) +
          '" title="' +
          (pref.is_starred ? "Unstar" : "Star (float to top)") +
          '">' +
          (pref.is_starred ? "\u2605" : "\u2606") +
          "</span>" +
          /* Per-row hide/unhide toggle (todo#418) — 👁 visible / 🚫 hidden.
           * Click stops propagation so the row's own click handler does
           * not also fire. Single eye (the earlier ch-watch mute duplicate
           * was removed — mute still reachable via right-click menu). */
          '<span class="ch-eye ' +
          (pref.is_hidden ? "ch-eye-off" : "ch-eye-on") +
          '" data-ch="' +
          escapeHtml(norm) +
          '" title="' +
          (pref.is_hidden
            ? "Show channel (un-hide)"
            : "Hide channel (dim in list)") +
          '">' +
          (pref.is_hidden ? "\uD83D\uDEAB" : "\uD83D\uDC41") +
          "</span>";
        var unread = channelUnread[c] || channelUnread[norm] || 0;
        var badgeHtml =
          '<span class="ch-badge-slot">' +
          (unread > 0
            ? '<span class="unread-badge">' +
              (unread > 99 ? "99+" : unread) +
              "</span>"
            : "") +
          "</span>";
        var starred = pref.is_starred ? " ch-starred" : "";
        var hiddenCls = entry.hidden ? " ch-hidden" : "";
        var inFolderCls = row.inFolder ? " ch-in-folder" : "";
        var divider =
          i === firstHiddenIdx
            ? '<div class="ch-hidden-divider" aria-hidden="true"></div>'
            : "";
        var rowTitle = entry.hidden
          ? ' title="Hidden \u2014 click to un-hide"'
          : row.inFolder
            ? ' title="' + escapeHtml(entry.norm) + '"'
            : "";
        /* Label: full "#proj/ripple-wm" at top level; short "#ripple-wm"
         * when rendered as a child of the proj/ folder header (todo#71). */
        var nameLabel = row.inFolder ? row.leafLabel : entry.norm;
        return (
          divider +
          '<div class="channel-item' +
          active +
          muted +
          starred +
          hiddenCls +
          inFolderCls +
          '" data-channel="' +
          escapeHtml(c) +
          '"' +
          (entry.hidden ? ' data-hidden="1"' : "") +
          (row.inFolder
            ? ' data-folder="' + escapeHtml(row.inFolder) + '"'
            : "") +
          rowTitle +
          ' draggable="true">' +
          '<span class="ch-drag-handle" title="Drag to reorder">&#8942;</span>' +
          starHtml +
          '<span class="ch-name">' +
          escapeHtml(nameLabel) +
          "</span>" +
          badgeHtml +
          "</div>"
        );
      })
      .join("");
    /* todo#71: wire folder-header click -> toggle collapse + persist.
     * Handler is attached BEFORE the .channel-item forEach so the folder
     * rows live in the same DOM snapshot. Clicking a folder re-runs
     * fetchStats() via the localStorage round-trip so the next render
     * reflects the new collapse state immediately. */
    chContainer.querySelectorAll(".channel-folder").forEach(function (fEl) {
      fEl.addEventListener("click", function (ev) {
        ev.stopPropagation();
        var prefix = fEl.getAttribute("data-folder") || "";
        if (!prefix) return;
        var store = {};
        try {
          var raw = localStorage.getItem("orochi.channelTreeCollapsed");
          if (raw) store = JSON.parse(raw) || {};
        } catch (_) {
          store = {};
        }
        if (store[prefix]) {
          delete store[prefix];
        } else {
          store[prefix] = true;
        }
        try {
          localStorage.setItem(
            "orochi.channelTreeCollapsed",
            JSON.stringify(store),
          );
        } catch (_) {}
        /* Bust the throttle so the next fetchStats actually re-renders. */
        chContainer._lastStatsJson = null;
        fetchStats();
      });
    });
    chContainer.querySelectorAll(".channel-item").forEach(function (el) {
      /* Restore selected state from before re-render */
      var elCh = el.getAttribute("data-channel");
      if (elCh && prevSelected[elCh]) el.classList.add("selected");
      /* Pin icon click — toggle is_starred (pinned-to-top) */
      var pinEl = el.querySelector(".ch-pin");
      if (pinEl) {
        pinEl.addEventListener("click", function (ev) {
          ev.stopPropagation();
          var norm = pinEl.getAttribute("data-ch");
          var curPref = _channelPrefs[norm] || {};
          _setChannelPref(norm, { is_starred: !curPref.is_starred });
        });
      }
      /* Eye icon click — toggle is_muted (watching vs muted) */
      var watchEl = el.querySelector(".ch-watch");
      if (watchEl) {
        watchEl.addEventListener("click", function (ev) {
          ev.stopPropagation();
          var norm = watchEl.getAttribute("data-ch");
          var curPref = _channelPrefs[norm] || {};
          _setChannelPref(norm, { is_muted: !curPref.is_muted });
        });
      }
      /* Hide/unhide icon click — toggle is_hidden (todo#418). */
      var eyeEl = el.querySelector(".ch-eye");
      if (eyeEl) {
        eyeEl.addEventListener("click", function (ev) {
          ev.stopPropagation();
          ev.preventDefault();
          var norm = eyeEl.getAttribute("data-ch");
          var curPref = _channelPrefs[norm] || {};
          _setChannelPref(norm, { is_hidden: !curPref.is_hidden });
        });
      }
      /* Context menu */
      _addChannelContextMenu(el);
      /* todo#49: accept agent-card drops to toggle subscription. */
      el.addEventListener("dragover", function (ev) {
        var drag = window.__orochiDragAgent;
        if (!drag || !drag.name) return;
        ev.preventDefault();
        ev.dataTransfer.dropEffect = "link";
        var ch = el.getAttribute("data-channel") || "";
        var subscribed = _agentHasChannel(drag.channels, ch);
        if (subscribed) {
          el.classList.add("drop-target-agent-remove");
          el.classList.remove("drop-target-agent-add");
          _setChannelDropHint(el, "drop to unsubscribe");
        } else {
          el.classList.add("drop-target-agent-add");
          el.classList.remove("drop-target-agent-remove");
          _setChannelDropHint(el, "drop to subscribe");
        }
      });
      el.addEventListener("dragleave", function () {
        el.classList.remove("drop-target-agent-add");
        el.classList.remove("drop-target-agent-remove");
        var hint = el.querySelector(".ch-hint");
        if (hint) hint.remove();
      });
      el.addEventListener("drop", function (ev) {
        var agentName =
          (ev.dataTransfer &&
            ev.dataTransfer.getData("application/x-orochi-agent")) ||
          (window.__orochiDragAgent && window.__orochiDragAgent.name) ||
          "";
        if (!agentName) return;
        ev.preventDefault();
        ev.stopPropagation();
        var ch = el.getAttribute("data-channel") || "";
        var chs =
          (ev.dataTransfer &&
            ev.dataTransfer.getData("application/x-orochi-agent-channels")) ||
          (window.__orochiDragAgent && window.__orochiDragAgent.channels) ||
          "";
        var subscribed = _agentHasChannel(chs, ch);
        el.classList.remove("drop-target-agent-add");
        el.classList.remove("drop-target-agent-remove");
        var hint = el.querySelector(".ch-hint");
        if (hint) hint.remove();
        _toggleAgentChannelSubscription(agentName, ch, !subscribed);
      });
      el.addEventListener("click", function (ev) {
        if (
          ev.target.classList.contains("ch-pin") ||
          ev.target.classList.contains("ch-watch") ||
          ev.target.classList.contains("ch-eye") ||
          ev.target.classList.contains("ch-drag-handle")
        )
          return;
        var ch = el.getAttribute("data-channel");
        /* Hidden row click: un-hide (same call path as ctx-menu "Show channel"). */
        if (el.getAttribute("data-hidden") === "1") {
          ev.stopPropagation();
          _setChannelPref(ch, { is_hidden: false });
          return;
        }
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
        items.forEach(function (it) {
          it.classList.remove("selected");
        });
        if (!wasSelected && currentChannel === ch) {
          el.classList.add("selected");
        }
        if (typeof applyFeedFilter === "function") applyFeedFilter();
        fetchStats();
      });
    });
    var chCountEl = document.getElementById("sidebar-count-channels");
    if (chCountEl) {
      /* Count visible (non-hidden) rows for the heading — the dimmed
       * hidden rows at the bottom are intentionally not in this count. */
      var visibleCount = displayChannels.filter(function (e) {
        return !e.hidden;
      }).length;
      chCountEl.textContent = "(" + visibleCount + ")";
    }
    /* Add drag-and-drop to channels section */
    _addDragAndDrop(chContainer, "channels");
    if (typeof updateChannelUnreadBadges === "function")
      updateChannelUnreadBadges();
    if (inputHasFocus && document.activeElement !== msgInput) {
      msgInput.focus();
      try {
        msgInput.setSelectionRange(savedStart, savedEnd);
      } catch (_) {}
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
    if (emojiOverlay) {
      closeEmojiPicker();
      e.preventDefault();
      return;
    }
  }
  if (typeof closeThreadPanel === "function") {
    var threadPanel = document.querySelector(".thread-panel.open");
    if (threadPanel) {
      closeThreadPanel();
      e.preventDefault();
      return;
    }
  }
  if (typeof closeSketchPanel === "function") {
    var sketchPanel = document.querySelector(".sketch-panel.open");
    if (sketchPanel) {
      closeSketchPanel();
      e.preventDefault();
      return;
    }
  }
  var generic = document.querySelector(
    ".emoji-picker-overlay.visible, .modal.open, .popup.visible, .long-press-menu",
  );
  if (generic) {
    generic.classList.remove("visible", "open");
    if (generic.classList.contains("long-press-menu")) generic.remove();
    e.preventDefault();
    return;
  }
  /* Inline-style-based modals (display:flex toggled via style) —
   * channel-topic-modal, channel-export-modal, channel-members-panel,
   * and any future role="dialog" element that uses this pattern.
   * Close the top-most visible one. */
  var styleModals = document.querySelectorAll(
    '[role="dialog"], .ch-topic-modal, .ch-export-modal, .ch-members-panel, ' +
      "#channel-topic-modal, #channel-export-modal, #channel-members-panel, " +
      "#new-dm-modal, .dm-modal",
  );
  for (var i = 0; i < styleModals.length; i++) {
    var m = styleModals[i];
    var isVisible =
      m.hidden !== true &&
      getComputedStyle(m).display !== "none" &&
      getComputedStyle(m).visibility !== "hidden";
    if (!isVisible) continue;
    m.style.display = "none";
    m.hidden = true;
    e.preventDefault();
    return;
  }
});
