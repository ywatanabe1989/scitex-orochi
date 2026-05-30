// @ts-nocheck
import { getResolvedAgentColor, getSenderIcon } from "../agent-icons";
import { cleanAgentName, escapeHtml, hostedAgentName, timeAgo, apiUrl } from "../app/utils";
import { _processMessageMarkdown } from "../chat/chat-markdown";
import { buildAttachmentsHtml } from "../chat/chat-attachments";

/* activity-tab/graph-feed.ts — persistent message feed panel docked
 * on the right side of the graph (topology) canvas.
 *
 * Background (lead msg#15701, ywatanabe msg#15699): the Agents-tab
 * graph was one-way — posts worked but inbound replies only surfaced
 * as a 1.3s landing bubble on the destination node (see
 * topology-packets.ts _topoLandingBubble + _TOPO_LANDING_DUR_MS), then
 * disappeared. Users had to switch to the Chat tab to read responses,
 * making graph-tab conversations impossible.
 *
 * Design:
 *   - A right-docked collapsible panel hosts a scrollable feed.
 *   - Feed is wired to a "graph focus channel": defaults to the global
 *     currentChannel (same channel the Chat tab is focused on), or can
 *     be picked via the panel's channel selector, or gets auto-set
 *     when the user double-clicks a channel node to compose (see
 *     compose.ts _topoOpenChannelCompose → _graphFeedSetChannel).
 *   - Inbound WS messages: handleMessage() in websocket.ts mirrors
 *     each `msg` to _graphFeedAppendMessage so the feed lives in
 *     parallel with the Chat #messages feed. No flash/auto-dismiss.
 *   - Scroll-top loads older history (reuses /api/history/<ch> —
 *     same endpoint the Chat tab uses).
 *
 * Complements — does NOT replace — the hover-preview planned on PR
 * #311 item 11 (a popover over a channel NODE that shows the last 7
 * msgs for THAT channel). This panel is always-on for the compose
 * box's currently-wired channel.
 */

/* Feed rendering state */
var _graphFeedChannel = null; /* current wired channel */
var _graphFeedMountedForChannel = null; /* channel whose history is loaded */
var _graphFeedCollapsed = false;
var _graphFeedOldestTs = null; /* scroll-back cursor */
var _graphFeedLoadingOlder = false;
var _graphFeedKnownIds = Object.create(null); /* dedupe map */
var _graphFeedInitialLoadDone = false;

try {
  _graphFeedCollapsed =
    localStorage.getItem("orochi.graphFeedCollapsed") === "1";
} catch (_) {}

function _saveCollapsed() {
  try {
    localStorage.setItem(
      "orochi.graphFeedCollapsed",
      _graphFeedCollapsed ? "1" : "0",
    );
  } catch (_) {}
}

/* Stable feed root query — scoped to the topology view so we never
 * accidentally render into the Chat tab's #messages. */
function _graphFeedRoot() {
  return document.querySelector(
    ".activity-view-topology .graph-feed-messages",
  );
}

function _graphFeedPanel() {
  return document.querySelector(".activity-view-topology .graph-feed-panel");
}

/* HTML scaffold — injected by topology.ts into .topo-wrap on every
 * render. Guarded by a signature: if the panel already exists and the
 * channel is unchanged, we leave its message DOM intact so live-
 * appended messages aren't wiped by heartbeat re-renders. */
export function _graphFeedPanelHtml() {
  var ch = _graphFeedChannel || "";
  var collapsedCls = _graphFeedCollapsed ? " graph-feed-collapsed" : "";
  var label = ch ? "#" + ch : "(pick a channel)";
  return (
    '<div class="graph-feed-panel' +
    collapsedCls +
    '" data-graph-feed>' +
    '<div class="graph-feed-header">' +
    '<button type="button" class="graph-feed-toggle" ' +
    'data-graph-feed-action="toggle" ' +
    'title="Collapse / expand the graph message feed">' +
    (_graphFeedCollapsed ? "\u25C0" : "\u25B6") +
    "</button>" +
    '<span class="graph-feed-title">Feed</span>' +
    '<span class="graph-feed-channel" title="' +
    escapeHtml(ch ? "Channel: " + ch : "No channel wired") +
    '">' +
    escapeHtml(label) +
    "</span>" +
    "</div>" +
    '<div class="graph-feed-messages" ' +
    'data-graph-feed-messages ' +
    'aria-live="polite" aria-atomic="false">' +
    '<div class="graph-feed-older-hint" style="display:none">' +
    "Loading older…</div>" +
    '<div class="graph-feed-empty" ' +
    'data-graph-feed-empty>' +
    (ch
      ? "Loading recent messages…"
      : "Double-click a channel node or pick one above to start a conversation here.") +
    "</div>" +
    "</div>" +
    "</div>"
  );
}

/* Delegated click + scroll wiring. Called once per grid via the
 * delegation guard (same pattern as _wireTopoSeekbar). */
var _graphFeedWired = false;
export function _wireGraphFeed(grid) {
  if (_graphFeedWired || !grid) return;
  _graphFeedWired = true;
  grid.addEventListener("click", function (ev) {
    var btn = ev.target.closest
      ? ev.target.closest("[data-graph-feed-action]")
      : null;
    if (!btn) return;
    var action = btn.getAttribute("data-graph-feed-action");
    if (action === "toggle") {
      _graphFeedCollapsed = !_graphFeedCollapsed;
      _saveCollapsed();
      var panel = _graphFeedPanel();
      if (panel) {
        panel.classList.toggle("graph-feed-collapsed", _graphFeedCollapsed);
        btn.textContent = _graphFeedCollapsed ? "\u25C0" : "\u25B6";
      }
    }
  });
  /* Scroll-top → load older. Attach directly to the messages element
   * when it mounts (event bubbling for scroll doesn't cross shadow
   * boundaries; `scroll` doesn't bubble at all). We re-attach after
   * every render by checking a data flag. */
  grid.addEventListener(
    "scroll",
    function (ev) {
      var el = ev.target;
      if (!el || !el.classList || !el.classList.contains("graph-feed-messages"))
        return;
      if (el.scrollTop < 30 && !_graphFeedLoadingOlder) {
        _loadOlderMessages();
      }
    },
    true,
  );
}

/* Post-render hook — called by topology.ts after grid.innerHTML is set.
 * Responsibilities:
 *   1) Ensure feed history matches _graphFeedChannel.
 *   2) If the channel is unchanged, restore previously-rendered
 *      message DOM (we stashed it aside before innerHTML rewrite).
 * We stash in a module-level DocumentFragment so heartbeat re-renders
 * don't flicker the feed. */
var _graphFeedCachedDom = null;

export function _graphFeedPreRender() {
  /* Save the current feed DOM (messages, not header) so we can
   * restore after the re-render wipes innerHTML. Only meaningful when
   * the channel is unchanged. */
  var root = _graphFeedRoot();
  if (!root) {
    _graphFeedCachedDom = null;
    return;
  }
  _graphFeedCachedDom = {
    channel: _graphFeedChannel,
    html: root.innerHTML,
    scrollTop: root.scrollTop,
    scrollHeight: root.scrollHeight,
  };
}

export function _graphFeedPostRender() {
  var root = _graphFeedRoot();
  if (!root) return;
  /* If channel unchanged and we have cached DOM, restore it wholesale
   * so the heartbeat re-render doesn't flash the feed. */
  if (
    _graphFeedCachedDom &&
    _graphFeedCachedDom.channel === _graphFeedChannel &&
    _graphFeedMountedForChannel === _graphFeedChannel
  ) {
    root.innerHTML = _graphFeedCachedDom.html;
    /* Preserve scroll — if user was near bottom, pin to bottom;
     * otherwise keep their scrollTop. */
    var wasAtBottom =
      _graphFeedCachedDom.scrollHeight -
        _graphFeedCachedDom.scrollTop -
        100 <
      100;
    if (wasAtBottom) {
      root.scrollTop = root.scrollHeight;
    } else {
      root.scrollTop = _graphFeedCachedDom.scrollTop;
    }
    _graphFeedCachedDom = null;
    return;
  }
  _graphFeedCachedDom = null;

  /* New (or first) channel wiring — fetch history. */
  if (_graphFeedChannel && _graphFeedMountedForChannel !== _graphFeedChannel) {
    _loadInitialHistory(_graphFeedChannel);
  }
}

/* Public: change the wired channel. Called from compose.ts when the
 * inline channel-compose popup opens (so replies land in the feed
 * under the focused channel), and from the panel's own channel picker
 * (future), and from topology.ts's initial wire to currentChannel. */
export function _graphFeedSetChannel(channel) {
  channel = channel || "";
  if (channel === _graphFeedChannel) return;
  _graphFeedChannel = channel;
  _graphFeedMountedForChannel = null;
  _graphFeedOldestTs = null;
  _graphFeedKnownIds = Object.create(null);
  _graphFeedInitialLoadDone = false;
  var panel = _graphFeedPanel();
  if (panel) {
    var ch = panel.querySelector(".graph-feed-channel");
    if (ch) {
      ch.textContent = channel ? "#" + channel : "(pick a channel)";
      ch.setAttribute(
        "title",
        channel ? "Channel: " + channel : "No channel wired",
      );
    }
  }
  var root = _graphFeedRoot();
  if (root) {
    root.innerHTML =
      '<div class="graph-feed-older-hint" style="display:none">' +
      "Loading older…</div>" +
      '<div class="graph-feed-empty" data-graph-feed-empty>' +
      (channel
        ? "Loading recent messages…"
        : "Double-click a channel node or pick one above to start a conversation here.") +
      "</div>";
  }
  if (channel) _loadInitialHistory(channel);
}

/* Default initial wiring — called by topology.ts on first render. If
 * no channel is already set, adopt the global currentChannel so the
 * feed "just works" for users coming from Chat. */
export function _graphFeedEnsureDefaultChannel() {
  if (_graphFeedChannel) return;
  var ch = (globalThis as any).currentChannel || "";
  if (ch) _graphFeedSetChannel(ch);
}

/* Expose the module-local current channel for compose.ts etc. */
export function _graphFeedGetChannel() {
  return _graphFeedChannel || "";
}

async function _loadInitialHistory(channel) {
  if (!channel) return;
  _graphFeedMountedForChannel = channel;
  try {
    var encoded = encodeURIComponent(channel);
    var res = await fetch(apiUrl("/api/history/" + encoded + "?limit=50"), {
      credentials: "same-origin",
    });
    if (!res.ok) return;
    var rows = await res.json();
    /* API returns newest-first; reverse for chronological rendering. */
    rows.reverse();
    var root = _graphFeedRoot();
    if (!root) return;
    /* Guard: if the user switched channels while we were fetching,
     * abort — otherwise we'd paint stale rows. */
    if (_graphFeedChannel !== channel) return;
    root.innerHTML =
      '<div class="graph-feed-older-hint" style="display:none">' +
      "Loading older…</div>";
    _graphFeedKnownIds = Object.create(null);
    if (!rows.length) {
      root.innerHTML +=
        '<div class="graph-feed-empty" data-graph-feed-empty>' +
        "No messages in this channel yet. Send one to get started.</div>";
      _graphFeedInitialLoadDone = true;
      return;
    }
    rows.forEach(function (row) {
      if (row.id) _graphFeedKnownIds[row.id] = true;
      _appendRow(row, /*append=*/ true);
      if (!_graphFeedOldestTs || row.ts < _graphFeedOldestTs) {
        _graphFeedOldestTs = row.ts;
      }
    });
    _graphFeedInitialLoadDone = true;
    /* Snap to bottom on initial load. */
    root.scrollTop = root.scrollHeight;
  } catch (e) {
    console.warn("[graph-feed] initial history failed:", e);
  }
}

async function _loadOlderMessages() {
  if (!_graphFeedChannel || !_graphFeedOldestTs) return;
  _graphFeedLoadingOlder = true;
  var root = _graphFeedRoot();
  if (!root) {
    _graphFeedLoadingOlder = false;
    return;
  }
  var hint = root.querySelector(".graph-feed-older-hint");
  if (hint) hint.style.display = "";
  try {
    var encoded = encodeURIComponent(_graphFeedChannel);
    var before = encodeURIComponent(_graphFeedOldestTs);
    /* Same `before` cursor-style paging the Chat tab uses; if the API
     * doesn't honour it, we just get the same 50 rows back and the
     * dedupe map skips them all — harmless worst case. */
    var res = await fetch(
      apiUrl(
        "/api/history/" + encoded + "?limit=50&before=" + before,
      ),
      { credentials: "same-origin" },
    );
    if (!res.ok) return;
    var rows = await res.json();
    rows.reverse();
    var prevScrollHeight = root.scrollHeight;
    var newRowsAdded = 0;
    /* Prepend in reverse so chronological order stays correct: the
     * oldest of the new batch lands at the top. */
    for (var i = rows.length - 1; i >= 0; i--) {
      var row = rows[i];
      if (row.id && _graphFeedKnownIds[row.id]) continue;
      if (row.id) _graphFeedKnownIds[row.id] = true;
      _appendRow(row, /*append=*/ false); /* prepend */
      newRowsAdded++;
      if (!_graphFeedOldestTs || row.ts < _graphFeedOldestTs) {
        _graphFeedOldestTs = row.ts;
      }
    }
    /* Preserve visual scroll position — added rows pushed everything
     * down by (scrollHeight - prevScrollHeight). */
    if (newRowsAdded > 0) {
      root.scrollTop += root.scrollHeight - prevScrollHeight;
    }
  } catch (e) {
    console.warn("[graph-feed] older history failed:", e);
  } finally {
    if (hint) hint.style.display = "none";
    _graphFeedLoadingOlder = false;
  }
}

/* Public: called from websocket.ts on every inbound WS message so
 * the graph feed stays in sync with the Chat tab without its own
 * subscription infrastructure. */
export function _graphFeedAppendMessage(msg) {
  if (!msg || !_graphFeedChannel) return;
  var ch = msg.channel || (msg.payload && msg.payload.channel) || "";
  if (ch !== _graphFeedChannel) return;
  /* Dedupe — the REST poll path and the WS path can both deliver the
   * same message (observed on hub). */
  if (msg.id && _graphFeedKnownIds[msg.id]) return;
  if (msg.id) _graphFeedKnownIds[msg.id] = true;
  /* Map flat WS shape → the row shape _appendRow expects. */
  var row = {
    id: msg.id,
    sender: msg.sender,
    sender_type: msg.sender_type,
    ts: msg.ts,
    channel: ch,
    content:
      msg.text ||
      msg.content ||
      (msg.payload && (msg.payload.content || msg.payload.text)) ||
      "",
    metadata: (msg.payload && msg.payload.metadata) || msg.metadata || {},
    attachments:
      (msg.payload && msg.payload.attachments) ||
      (msg.metadata && msg.metadata.attachments) ||
      msg.attachments ||
      [],
  };
  _appendRow(row, /*append=*/ true);
}

/* Core row renderer — compact variant of chat-render.appendMessage.
 * Drops the heavy toolbar (thread / react / edit / delete) to keep
 * the panel uncluttered. Click on the message opens the thread in
 * the Chat tab (see _wireGraphFeed click delegation). */
function _appendRow(row, append) {
  var root = _graphFeedRoot();
  if (!root) return;
  /* Remove empty-state placeholder on first real row. */
  var empty = root.querySelector("[data-graph-feed-empty]");
  if (empty) empty.remove();
  var senderName = row.sender || "unknown";
  var isAgent = row.sender_type === "agent";
  var senderColor = getResolvedAgentColor(senderName);
  var ts = "";
  var fullTs = "";
  if (row.ts) {
    var d = new Date(row.ts);
    if (!isNaN(d.getTime())) {
      ts = timeAgo(row.ts);
      fullTs = d.toLocaleString();
    }
  }
  var content = row.content || "";
  var attachments = row.attachments || [];
  if (!content && (!attachments || !attachments.length)) return;
  var highlightedContent = _processMessageMarkdown(content);
  var senderIcon = getSenderIcon(senderName, isAgent);
  var el = document.createElement("div");
  el.className = "graph-feed-msg" + (isAgent ? "" : " graph-feed-msg-human");
  if (row.id) el.setAttribute("data-msg-id", String(row.id));
  el.setAttribute("data-sender", senderName);
  el.setAttribute("data-channel", row.channel || _graphFeedChannel || "");
  /* Clickable — jumps to the corresponding thread on the Chat tab. */
  if (row.id) {
    el.setAttribute("role", "button");
    el.setAttribute("tabindex", "0");
    el.setAttribute("title", "Click to open in Chat / thread view");
    el.addEventListener("click", function () {
      /* Route to the Chat tab's thread for this message. openThread
       * logic already exists on window from threads/panel.ts. */
      if (typeof (window as any).openThreadForMessage === "function") {
        try {
          (window as any).openThreadForMessage(row.id);
          return;
        } catch (_) {}
      }
      /* Fallback: switch to Chat tab and let the user find it. */
      var tabBtn = document.querySelector('[data-tab="chat"]');
      if (tabBtn) (tabBtn as HTMLElement).click();
    });
  }
  var senderDisplay = isAgent
    ? (function () {
        var rec = (window.__lastAgents || []).find(function (a) {
          return a && a.name === senderName;
        });
        return rec ? hostedAgentName(rec) : cleanAgentName(senderName);
      })()
    : cleanAgentName(senderName);
  var attachmentsHtml =
    typeof buildAttachmentsHtml === "function"
      ? buildAttachmentsHtml(attachments)
      : "";
  el.innerHTML =
    '<div class="graph-feed-msg-header">' +
    '<span class="graph-feed-msg-icon">' +
    senderIcon +
    "</span>" +
    '<span class="graph-feed-msg-sender" style="color:' +
    senderColor +
    '">' +
    escapeHtml(senderDisplay) +
    "</span>" +
    '<span class="graph-feed-msg-ts" title="' +
    escapeHtml(fullTs) +
    '">' +
    ts +
    "</span>" +
    (row.id
      ? '<span class="graph-feed-msg-id">#' + row.id + "</span>"
      : "") +
    "</div>" +
    '<div class="graph-feed-msg-content">' +
    highlightedContent +
    "</div>" +
    attachmentsHtml;
  /* Older-hint placeholder must stay at the top when we prepend. */
  var hint = root.querySelector(".graph-feed-older-hint");
  if (append) {
    var atBottom =
      root.scrollHeight - root.scrollTop - root.clientHeight < 80;
    root.appendChild(el);
    if (atBottom) {
      root.scrollTop = root.scrollHeight;
    }
  } else {
    /* Prepend: land just after the hint so older batches stay above
     * the current top-visible message. */
    if (hint && hint.nextSibling) {
      root.insertBefore(el, hint.nextSibling);
    } else {
      root.insertBefore(el, root.firstChild);
    }
  }
}

/* Expose for cross-file callers via window, mirroring the pattern the
 * rest of activity-tab/ uses for module-local state. */
(window as any)._graphFeedAppendMessage = _graphFeedAppendMessage;
(window as any)._graphFeedSetChannel = _graphFeedSetChannel;
(window as any)._graphFeedGetChannel = _graphFeedGetChannel;
