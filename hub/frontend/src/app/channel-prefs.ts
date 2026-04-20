
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
          if (typeof cacheChannelIdentity === "function") {
            cacheChannelIdentity(ch);
          }
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
      /* Keep the bell/mute placeholder in sync on the same tick as
       * star/eye so the whole row feels responsive. User request
       * 2026-04-20: "from anywhere, buttons must be responsive
       * (icon change, star/unstar, notification on/off)". */
      var muteEl = el.querySelector(".ch-mute");
      if (muteEl) {
        muteEl.classList.toggle("ch-mute-on", !!pref.is_muted);
        muteEl.classList.toggle("ch-mute-off", !pref.is_muted);
        muteEl.textContent = pref.is_muted ? "\uD83D\uDD15" : "\uD83D\uDD14";
        muteEl.setAttribute(
          "title",
          pref.is_muted ? "Unmute notifications" : "Mute notifications",
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
  /* Canvas repaint — star/mute/hide flip the channel-node polygon
   * class (topo-channel-starred/-muted) and the activity pool chip
   * star/mute glyphs. Clear the topo sticky signature so the next
   * render actually rebuilds the SVG instead of short-circuiting
   * on the unchanged agent-data sig. */
  if (typeof renderActivityTab === "function") {
    if (typeof window._topoLastSig !== "undefined") window._topoLastSig = "";
    renderActivityTab();
  }
}

/* Update an agent's display profile (icon_emoji etc) via
 * POST /api/agent-profiles/. Parallel to _setChannelIcon — keeps the
 * configuration story uniform across entity types. The registry
 * reads AgentProfile on next join so the icon survives container
 * restarts (todo#101 Entity Consistency). */
function _setAgentIcon(name, patch) {
  if (
    typeof cachedAgentIcons !== "undefined" &&
    patch &&
    "icon_emoji" in patch
  ) {
    if (patch.icon_emoji) cachedAgentIcons[name] = patch.icon_emoji;
    else delete cachedAgentIcons[name];
  }
  fetch(apiUrl("/api/agent-profiles/"), {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": getCsrfToken(),
    },
    body: JSON.stringify(Object.assign({ name: name }, patch)),
  }).catch(function (_) {});
  if (typeof fetchAgents === "function") fetchAgents();
  if (typeof renderActivityTab === "function") {
    if (typeof window._topoLastSig !== "undefined") window._topoLastSig = "";
    renderActivityTab();
  }
}

/* Update a channel's custom icon/color via PATCH /api/channels/
 * (todo#101). Accepts any subset of {icon_emoji, icon_image, icon_text,
 * color}. The server broadcasts channel_identity so every connected
 * client refreshes the three render surfaces in lockstep. */
function _setChannelIcon(ch, patch) {
  var normCh = ch.charAt(0) === "#" ? ch : "#" + ch;
  if (typeof cacheChannelIdentity === "function") {
    cacheChannelIdentity(
      Object.assign(
        {
          name: normCh,
          icon_emoji: cachedChannelIcons[normCh] || "",
          icon_image: "",
          icon_text: "",
          color: cachedChannelColors[normCh] || "",
        },
        patch,
      ),
    );
  }
  fetch(apiUrl("/api/channels/"), {
    method: "PATCH",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": getCsrfToken(),
    },
    body: JSON.stringify(Object.assign({ name: normCh }, patch)),
  }).catch(function (_) {});
  if (typeof fetchStats === "function") fetchStats();
  if (typeof renderActivityTab === "function") {
    /* Bust the topology sticky-signature so the canvas repaints with
     * the fresh icon/color instead of skipping the rebuild — signature
     * doesn't capture icon/color changes. */
    if (typeof window._topoLastSig !== "undefined") window._topoLastSig = "";
    renderActivityTab();
  }
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
      var sPref = _channelPrefs[ch] || {};
      var sMuteHtml =
        '<span class="ch-mute ' +
        (sPref.is_muted ? "ch-mute-on" : "ch-mute-off") +
        '" data-ch="' +
        escapeHtml(ch) +
        '" title="' +
        (sPref.is_muted ? "Unmute notifications" : "Mute notifications") +
        '">' +
        (sPref.is_muted ? "\uD83D\uDD15" : "\uD83D\uDD14") +
        "</span>";
      var sIconHtml =
        typeof channelIdentity === "function"
          ? '<span class="ch-identity-icon">' +
            channelIdentity(ch).iconHtml(14) +
            "</span>"
          : "";
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
        '" title="Unstar (will drop from top)">\u2605</span>' +
        sMuteHtml +
        sIconHtml +
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

