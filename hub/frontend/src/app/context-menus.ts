// @ts-nocheck
import { _agentSubscribe, _openAgentDmSimple, _toggleAgentChannelSubscription, openChannelExport } from "./agent-actions";
import { _setChannelPref } from "./channel-prefs";
import { _channelPrefs } from "./members";
import { escapeHtml, userName } from "./utils";

/* Context menu for channel items — right-click shows pref options */
export function _addChannelContextMenu(el) {
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
export function _repositionMenuInViewport(el) {
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

export var _ctxMenu = null;
export function _showChannelCtxMenu(ch, x, y) {
  _hideChannelCtxMenu();
  var prefs = _channelPrefs[ch] || {};
  var notif = prefs.notification_level || "all";
  /* Item 13 (msg#15675): star/mute/hidden state is read directly via
   * the channel-badge icons in sidebar/graph — this menu no longer
   * toggles them. Locals removed to reflect the narrower scope. */

  var menu = document.createElement("div");
  menu.className = "ch-ctx-menu";
  menu.style.cssText =
    "position:fixed;z-index:9999;left:" + x + "px;top:" + y + "px;";
  var G_EXPORT = "\u2935"; /* ⤵ export */
  var G_EMPTY = "";
  function _glyph(g) {
    return '<span class="ch-ctx-glyph">' + g + "</span>";
  }
  /* Item 13 (lead msg#15675 / msg#15678) — deduplicate the channel
   * right-click menu against the direct badge icons (★ / 👁 / 🔔 / icon).
   * Lead's canonical delete-list: Star, Mute, Set Icon, Clear Icon,
   * Delete Channel, Show Channel, Hide Channel, Mute Notifications.
   * Kept: Export Channel (no icon equivalent). Also kept: Notifications
   * level chooser (All / @ Mentions only / Nothing) — this is a 3-way
   * selector and is NOT duplicated by the bell icon's boolean toggle,
   * so it survives the dedup. Also kept: "Hide node (Viz topology)" —
   * this is a session-only viz hide, distinct from the persistent
   * eye-icon is_hidden that propagates across surfaces. */
  menu.innerHTML = [
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
      /* Item 13: trimmed action set — star / mute / hide / set-icon /
       * clear-icon are now handled exclusively by the channel-badge
       * icons (delegation in channel-badge.ts attachChannelBadgeHandlers).
       * Remaining: notification-level trio, export, topo-hide. */
      if (action === "notif-all")
        _setChannelPref(ch, { notification_level: "all" });
      else if (action === "notif-mentions")
        _setChannelPref(ch, { notification_level: "mentions" });
      else if (action === "notif-nothing")
        _setChannelPref(ch, { notification_level: "nothing" });
      else if (action === "export") {
        _hideChannelCtxMenu();
        openChannelExport(ch);
        return;
      } else if (action === "topo-hide") {
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

export function _hideChannelCtxMenu() {
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
export var _agentCtxMenu = null;
export function _hideAgentCtxMenu() {
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
export function _agentCtxKeyHandler(ev) {
  if (ev.key === "Escape") _hideAgentCtxMenu();
}

export function _addAgentContextMenu(el) {
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

export function _showAgentContextMenu(agent, x, y) {
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
  /* Item 13 (msg#15675 / msg#15678) — same dedup principle as the
   * channel ctx-menu: drop icon-equivalent rows. The agent avatar is
   * already an .avatar-clickable trigger for the emoji picker (see
   * agent-badge.ts), so "Set icon" / "Clear icon" here duplicate the
   * icon affordance. Kept: Add-to / DM / Remove-from submenus (no
   * icon equivalent), plus the session-only "Hide node (Viz
   * topology)" row which is distinct from the persistent eye-icon
   * is_hidden that propagates across surfaces. */
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
  /* Item 13: "Set icon" / "Clear icon" rows dropped here — the agent
   * avatar carries .avatar-clickable which opens the emoji picker
   * directly (see agent-badge.ts, delegated in sidebar-agents.ts /
   * dms.ts / agents-tab/overview.ts). */

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
