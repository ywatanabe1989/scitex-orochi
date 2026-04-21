// @ts-nocheck
import { apiUrl, escapeHtml } from "../app/utils";

/* activity-tab/channel-hover-preview.ts — Item 11 (lead msg#15646).
 *
 * Lightweight hover-preview popover for channel nodes on the Agents
 * topology canvas. On settled hover (300 ms delay) of a .topo-channel
 * group, fetch the last 7 messages via GET /api/history/<channel>/
 * and render them in a floating popover anchored near the node.
 *
 * Design rules (from lead spec):
 *   - 300 ms hover delay so a quick cursor sweep doesn't flash the
 *     popover. Debounce resets on re-entry.
 *   - Snapshot on hover: no auto-refresh. For deeper exploration the
 *     user double-clicks to jump to the Chat tab (existing behaviour).
 *   - Pointer entering the popover does NOT dismiss it — the user
 *     needs to read without having the popover vanish under the
 *     cursor. Dismiss on pointerleave of BOTH the node and the
 *     popover, or on outer click.
 *   - Scrollable if content overflows; reuse the chat feed's
 *     message-cell typography via the shared .chp-* styles in
 *     style-menus.css.
 *   - Vanilla TS / DOM only — no framer-motion, no react. Matches the
 *     style of channel-controls.ts / context-menus.ts.
 *
 * Caching: we keep a tiny Map<channel, {data, at}> of the last
 * fetched snapshot with a 5 s TTL so rapid re-hover doesn't
 * re-fetch on every pass. This is explicitly NOT live data — hovering
 * twice within 5 s returns the same snapshot, which is fine because
 * the spec calls this "snapshot on hover".
 */

var HOVER_DELAY_MS = 300;
var CACHE_TTL_MS = 5000;
var FETCH_LIMIT = 7;

var _hoverTimer: any = null;
var _currentNode: any = null;
var _currentPopover: any = null;
var _cache: any = {};
/* Incrementing request epoch so a late-arriving fetch for a channel
 * the user has already moved away from doesn't silently paint over a
 * newer hover target. */
var _epoch = 0;

function _clearHoverTimer() {
  if (_hoverTimer) {
    clearTimeout(_hoverTimer);
    _hoverTimer = null;
  }
}

function _destroyPopover() {
  if (_currentPopover && _currentPopover.parentNode) {
    _currentPopover.parentNode.removeChild(_currentPopover);
  }
  _currentPopover = null;
  _currentNode = null;
}

function _fmtTime(iso) {
  if (!iso) return "";
  try {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    var hh = String(d.getHours()).padStart(2, "0");
    var mm = String(d.getMinutes()).padStart(2, "0");
    return hh + ":" + mm;
  } catch (_e) {
    return "";
  }
}

function _truncate(s, n) {
  if (!s) return "";
  s = String(s);
  if (s.length <= n) return s;
  return s.slice(0, n - 1) + "\u2026";
}

function _renderRows(messages) {
  if (!messages || !messages.length) {
    return '<div class="chp-empty">(no recent messages)</div>';
  }
  /* API returns newest-first; flip so the popover reads chronologically
   * like the chat feed does. */
  var rows = messages.slice().reverse();
  return rows
    .map(function (m) {
      var sender = m.sender || "?";
      var ts = _fmtTime(m.ts);
      var content = _truncate(m.content || "", 140);
      return (
        '<div class="chp-row">' +
        '<div class="chp-meta">' +
        '<span class="chp-sender">' +
        escapeHtml(sender) +
        "</span>" +
        (ts
          ? '<span class="chp-ts">' + escapeHtml(ts) + "</span>"
          : "") +
        "</div>" +
        '<div class="chp-body">' +
        escapeHtml(content) +
        "</div>" +
        "</div>"
      );
    })
    .join("");
}

function _positionPopover(pop, node) {
  /* Anchor near the node but stay inside the viewport with 8 px pad.
   * Prefer right-of-node; flip to left if right would overflow. If
   * bottom would overflow, align to top of viewport. */
  var pad = 8;
  var rect = node.getBoundingClientRect();
  var pr = pop.getBoundingClientRect();
  var left = rect.right + 8;
  var top = rect.top;
  if (left + pr.width > window.innerWidth - pad) {
    left = Math.max(pad, rect.left - pr.width - 8);
  }
  if (top + pr.height > window.innerHeight - pad) {
    top = Math.max(pad, window.innerHeight - pr.height - pad);
  }
  pop.style.left = left + "px";
  pop.style.top = top + "px";
}

function _openPopover(node, channel) {
  _destroyPopover();
  var pop = document.createElement("div");
  pop.className = "channel-hover-popover";
  pop.setAttribute("data-channel", channel);
  pop.style.cssText =
    "position:fixed;z-index:9998;left:0;top:0;pointer-events:auto;";
  pop.innerHTML =
    '<div class="chp-header">' +
    escapeHtml(channel) +
    '<span class="chp-hint">last ' +
    FETCH_LIMIT +
    "</span>" +
    "</div>" +
    '<div class="chp-body-scroll"><div class="chp-loading">Loading\u2026</div></div>';
  document.body.appendChild(pop);
  _currentPopover = pop;
  _currentNode = node;
  _positionPopover(pop, node);

  /* Pointer entering the popover must NOT dismiss it — user wants to
   * read. pointerleave on the popover itself closes (dismiss on outer
   * pointerleave + outer click, per spec). */
  pop.addEventListener("pointerleave", function (ev) {
    /* If the cursor moves back onto the source node, keep the popover
     * open — the node's own pointerleave handler will tear down when
     * the user truly leaves. */
    var rel = ev.relatedTarget;
    if (rel && _currentNode && _currentNode.contains(rel)) return;
    _destroyPopover();
  });

  /* Re-use cached snapshot if fresh (≤5 s). Spec says "snapshot on
   * hover"; TTL here just avoids a trivially-redundant fetch during
   * rapid re-hovers of the same node. */
  var cached = _cache[channel];
  var now = Date.now();
  if (cached && now - cached.at < CACHE_TTL_MS) {
    _paintMessages(pop, cached.data);
    return;
  }

  var myEpoch = ++_epoch;
  var url = apiUrl(
    "/api/history/" + encodeURIComponent(channel) + "/?limit=" + FETCH_LIMIT,
  );
  fetch(url, { credentials: "same-origin" })
    .then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    })
    .then(function (data) {
      _cache[channel] = { data: data, at: Date.now() };
      /* Bail if the user has already moved to a different node — we
       * don't want a stale fetch to paint over the current popover. */
      if (myEpoch !== _epoch) return;
      if (
        !_currentPopover ||
        _currentPopover.getAttribute("data-channel") !== channel
      )
        return;
      _paintMessages(_currentPopover, data);
    })
    .catch(function (err) {
      if (myEpoch !== _epoch) return;
      if (
        !_currentPopover ||
        _currentPopover.getAttribute("data-channel") !== channel
      )
        return;
      var body = _currentPopover.querySelector(".chp-body-scroll");
      if (body) {
        body.innerHTML =
          '<div class="chp-empty">Failed to load (' +
          escapeHtml(String(err && err.message ? err.message : err)) +
          ")</div>";
      }
    });
}

function _paintMessages(pop, data) {
  var body = pop.querySelector(".chp-body-scroll");
  if (!body) return;
  body.innerHTML = _renderRows(data);
  /* Re-anchor: the popover may have grown from loading-size to full
   * content-size, potentially pushing it off-screen. */
  if (_currentNode) _positionPopover(pop, _currentNode);
}

export function _ovgWireChannelHoverPreview(grid) {
  if (!grid) return;
  /* pointerover/pointerleave over the grid. We debounce per-node so a
   * cursor that sweeps across the canvas doesn't fire a preview for
   * each node it happens to cross. */
  grid.addEventListener("pointerover", function (ev) {
    var node = ev.target.closest(".topo-channel[data-channel]");
    if (!node || !grid.contains(node)) return;
    var ch = node.getAttribute("data-channel");
    if (!ch) return;
    /* Same node as we're already showing? nothing to do. */
    if (
      _currentPopover &&
      _currentPopover.getAttribute("data-channel") === ch &&
      _currentNode === node
    ) {
      return;
    }
    _clearHoverTimer();
    _hoverTimer = setTimeout(function () {
      _hoverTimer = null;
      _openPopover(node, ch);
    }, HOVER_DELAY_MS);
  });
  grid.addEventListener(
    "pointerleave",
    function (ev) {
      var node = ev.target.closest(".topo-channel[data-channel]");
      if (!node || !grid.contains(node)) return;
      /* Cancel a pending settle-timer when the cursor leaves before
       * 300 ms — avoids popping up after the cursor is already gone. */
      _clearHoverTimer();
      /* Closing is gated: if the cursor moved into the popover we
       * keep it alive (popover's own pointerleave handles close). */
      var rel = ev.relatedTarget;
      if (rel && _currentPopover && _currentPopover.contains(rel)) return;
      _destroyPopover();
    },
    true,
  );
  /* Outer click dismisses (spec). Capture phase so we run before any
   * site-local click handler eats the event. */
  document.addEventListener(
    "click",
    function (ev) {
      if (!_currentPopover) return;
      if (_currentPopover.contains(ev.target)) return;
      var node = ev.target.closest(".topo-channel[data-channel]");
      if (node && node === _currentNode) return;
      _destroyPopover();
    },
    true,
  );
}
