/* activity-tab/edge-menu.js — edge-click / right-click unsubscribe
 * popover for topology edges. */


/* Edge-click unsubscribe: clicking (or right-clicking) a topology edge
 * offers to remove that agent's subscription to the channel.
 * ywatanabe 2026-04-19: "edges (lines) must be selectable to
 * unsubscribe".
 *
 * Optimistic: drop the channel from window.__lastAgents[i].channels and
 * from _topoStickyEdges so the edge disappears immediately. The DELETE
 * request to /api/channel-members/ then confirms with the backend.
 * _agentSubscribe's throttled fetchAgents will reconcile any drift. */
var _topoEdgeMenuEl = null;
function _topoCloseEdgeMenu() {
  if (_topoEdgeMenuEl && _topoEdgeMenuEl.parentNode) {
    _topoEdgeMenuEl.parentNode.removeChild(_topoEdgeMenuEl);
  }
  _topoEdgeMenuEl = null;
  document.removeEventListener("click", _topoEdgeMenuOutsideClick, true);
  document.removeEventListener("mousedown", _topoEdgeMenuOutsideClick, true);
  document.removeEventListener("keydown", _topoEdgeMenuKeyHandler, true);
}
/* Viewport clamp — mirror of app.js::_repositionMenuInViewport. Copied
 * (not imported) because this file's popovers should work even if app.js
 * hasn't exposed its helper on window. ywatanabe 2026-04-19. */
function _topoClampMenuInViewport(el) {
  if (!el) return;
  var pad = 8;
  var rect = el.getBoundingClientRect();
  if (rect.right > window.innerWidth - pad) {
    el.style.left = Math.max(pad, window.innerWidth - rect.width - pad) + "px";
  }
  if (rect.bottom > window.innerHeight - pad) {
    el.style.top = Math.max(pad, window.innerHeight - rect.height - pad) + "px";
  }
  /* Also clamp left/top edges in case the click was near 0,0. */
  if (rect.left < pad) el.style.left = pad + "px";
  if (rect.top < pad) el.style.top = pad + "px";
}
function _topoEdgeMenuOutsideClick(ev) {
  if (!_topoEdgeMenuEl) return;
  if (_topoEdgeMenuEl.contains(ev.target)) return;
  _topoCloseEdgeMenu();
}
function _topoEdgeMenuKeyHandler(ev) {
  if (ev.key === "Escape") {
    ev.stopPropagation();
    _topoCloseEdgeMenu();
  }
}
function _topoDoEdgeUnsubscribe(agent, channel) {
  /* Optimistic removal: drop from __lastAgents + sticky set before
   * firing the DELETE so the edge vanishes on the next render. */
  var live = window.__lastAgents || [];
  for (var i = 0; i < live.length; i++) {
    if (live[i].name === agent) {
      var chs = Array.isArray(live[i].channels) ? live[i].channels : [];
      live[i].channels = chs.filter(function (c) {
        return c !== channel;
      });
      break;
    }
  }
  if (typeof _topoStickyKey === "function") {
    delete _topoStickyEdges[_topoStickyKey(agent, channel)];
  }
  _topoLastSig = "";
  if (typeof renderActivityTab === "function") renderActivityTab();
  if (typeof _invalidateTopoPerms === "function") _invalidateTopoPerms();

  /* Fire DELETE /api/channel-members/ directly so we control the toast
   * wording exactly (app.js::_toggleAgentChannelSubscription emits its
   * own "Unsubscribed ← channel" toast; we want "from" here). */
  if (typeof _showMiniToast === "function") {
    _showMiniToast("Unsubscribed " + agent + " from " + channel, "ok");
  }
  if (typeof _agentDjangoUsername !== "function") return;
  var username = _agentDjangoUsername(agent);
  if (!username) return;
  var url =
    typeof apiUrl === "function"
      ? apiUrl("/api/channel-members/")
      : "/api/channel-members/";
  fetch(url, {
    method: "DELETE",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": typeof getCsrfToken === "function" ? getCsrfToken() : "",
    },
    body: JSON.stringify({ channel: channel, username: username }),
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
            if (typeof _showMiniToast === "function") {
              _showMiniToast("Unsubscribe failed: " + msg, "err");
            }
          });
      }
      /* Reconcile with server state so a subsequent subscribe sees the
       * authoritative channel list, not our optimistic mutation. */
      if (typeof fetchAgentsThrottled === "function") fetchAgentsThrottled();
      else if (typeof fetchAgents === "function") fetchAgents();
    })
    .catch(function (_) {});
}
function _topoShowEdgeMenu(agent, channel, clientX, clientY) {
  _topoCloseEdgeMenu();
  if (!agent || !channel) return;
  var menu = document.createElement("div");
  menu.className = "topo-edge-menu";
  menu.setAttribute("role", "menu");
  /* Confirm-dialog flow: title + subtle preview row + danger button +
   * Cancel. The preview line mirrors what will happen ("<#channel>  <-
   * <agent>") in monospace with the agent's own color so users can
   * double-check before destroying their subscription. */
  var agentColor =
    typeof getAgentColor === "function" ? getAgentColor(agent) : "#cbd5e1";
  menu.style.position = "fixed";
  menu.style.left = clientX + "px";
  menu.style.top = clientY + "px";
  /* Start transparent; rAF flips opacity:1 after insertion for a 120ms
   * fade-in. No fade on close — that path just removes the node. */
  menu.style.opacity = "0";
  menu.innerHTML =
    '<div class="topo-edge-menu-title">' +
    escapeHtml(agent) +
    " &rarr; " +
    escapeHtml(channel) +
    "</div>" +
    '<div class="topo-edge-menu-preview">' +
    '<span class="topo-edge-menu-preview-ch">' +
    escapeHtml(channel) +
    "</span>" +
    '<span class="topo-edge-menu-preview-arr">&larr;</span>' +
    '<span class="topo-edge-menu-preview-ag" style="color:' +
    escapeHtml(agentColor) +
    '">' +
    escapeHtml(agent) +
    "</span>" +
    "</div>" +
    '<button type="button" class="topo-edge-menu-btn topo-edge-menu-btn-danger" data-topo-edge-action="unsubscribe">Unsubscribe ' +
    escapeHtml(agent) +
    " from " +
    escapeHtml(channel) +
    "</button>" +
    '<button type="button" class="topo-edge-menu-btn" data-topo-edge-action="cancel">Cancel</button>';
  document.body.appendChild(menu);
  /* Viewport-aware clamp — keeps the popover 8px inside every edge so
   * the outline never kisses the screen border, even when a user clicks
   * an edge pixel near the bottom-right corner. */
  _topoClampMenuInViewport(menu);
  _topoEdgeMenuEl = menu;
  /* Fade in: next frame flip opacity so the browser has a chance to
   * commit the initial opacity:0 → transition kicks in. */
  requestAnimationFrame(function () {
    if (_topoEdgeMenuEl === menu) menu.style.opacity = "1";
  });
  /* Bind the action handler directly to each button (not via click
   * delegation on the parent menu). Delegated click on the menu was
   * unreliable in the wild: right-click-to-open puts the DOM into a
   * state where the subsequent left-click on Unsubscribe sometimes
   * never reached our bubble-phase listener — users reported
   * "unsubscribe not working from right click edge -> unsubscribe".
   * Per-button listeners fire deterministically on `click` AND
   * `pointerdown` (fallback for flaky pointer stacks), so the action
   * runs even if one of the two phases is intercepted upstream.
   * ywatanabe 2026-04-19. */
  function _topoEdgeMenuHandleAction(ev) {
    var btn = ev.currentTarget;
    if (!btn) return;
    var action = btn.getAttribute("data-topo-edge-action");
    ev.preventDefault();
    ev.stopPropagation();
    /* Guard against double-fire (pointerdown + click on same button). */
    if (btn.__topoActionFired) return;
    btn.__topoActionFired = true;
    if (action === "unsubscribe") {
      _topoDoEdgeUnsubscribe(agent, channel);
    }
    _topoCloseEdgeMenu();
  }
  var actionBtns = menu.querySelectorAll("[data-topo-edge-action]");
  for (var ai = 0; ai < actionBtns.length; ai++) {
    actionBtns[ai].addEventListener("click", _topoEdgeMenuHandleAction);
    /* Also fire on pointerdown — triggers before mouseup/click so
     * nothing that runs on click-bubble can cancel the action. */
    actionBtns[ai].addEventListener("pointerdown", _topoEdgeMenuHandleAction);
  }
  /* Dismiss on outside click (mousedown catches it earlier than click,
   * so the menu can't flicker on drag-select) / Escape. Defer to next
   * tick so the current click that opened the menu doesn't immediately
   * close it. */
  setTimeout(function () {
    document.addEventListener("mousedown", _topoEdgeMenuOutsideClick, true);
    document.addEventListener("click", _topoEdgeMenuOutsideClick, true);
    document.addEventListener("keydown", _topoEdgeMenuKeyHandler, true);
  }, 0);
}

