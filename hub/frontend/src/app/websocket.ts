// @ts-nocheck
import { _graphFeedAppendMessage } from "../activity-tab/graph-feed";
import { renderActivityTab } from "../activity-tab/init";
import { _topoPulseEdge } from "../activity-tab/topology-pulse";
import { cacheChannelIdentity } from "../agent-icons";
import { _channelDescriptions, _updateChannelTopicBanner } from "./members";
import { fetchAgents } from "./sidebar-agents";
import { fetchStats } from "./sidebar-stats";
import { showSystemBanner } from "./state";
import { apiUrl, baseTitle, channelUnread, channelsEqual, messageKey, token } from "./utils";
import { handleMessageDelete, handleMessageEdit } from "../chat/chat-actions";
import { appendSystemMessage } from "../chat/chat-attachments";
import { fetchNewMessages, loadHistory } from "../chat/chat-history";
import { appendMessage } from "../chat/chat-render";
import { handleReactionUpdate } from "../reactions";
import { fetchResources } from "../resources-tab/tab";
import { appendToThreadPanelIfOpen, handleThreadReply } from "../threads/panel";

/* WebSocket connection */
export var ws;
export var wsConnected = false;
export var restPollTimer = null;
export var restPollInterval = 5000;

/* fetchAgents throttle — prevents focus theft on rapid WS events (#225) */
export var _fetchAgentsTimer = null;
export var _fetchAgentsPending = false;
export var FETCH_AGENTS_THROTTLE_MS = 2000;

export function fetchAgentsThrottled() {
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

export var _fetchStatsTimer = null;
export var _fetchStatsPending = false;

export function fetchStatsThrottled() {
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

export function startRestPolling() {
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
        if ((globalThis as any).knownMessageKeys[key]) return;
        (globalThis as any).knownMessageKeys[key] = true;
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

export function stopRestPolling() {
  if (restPollTimer) {
    clearInterval(restPollTimer);
    restPollTimer = null;
  }
}

export function handleMessage(msg) {
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
    if ((globalThis as any).knownMessageKeys[key]) return;
    (globalThis as any).knownMessageKeys[key] = true;
    appendMessage(msg);
    /* Graph-tab persistent feed — mirror inbound messages into the
     * right-docked panel so graph-tab conversations are two-way (lead
     * msg#15701 blocker). No-op when the feed's wired channel doesn't
     * match this message's channel, or when the topology view isn't
     * mounted. */
    if (typeof _graphFeedAppendMessage === "function") {
      try {
        _graphFeedAppendMessage(msg);
      } catch (_) {
        /* Never let a feed-render error disrupt message delivery. */
      }
    }
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
      (globalThis as any).unreadCount++;
      document.title = "(" + (globalThis as any).unreadCount + ") " + baseTitle;
    }
    /* Per-channel unread count (#322). Use channelsEqual (msg#16691) so a
     * message arriving on ``#ywatanabe`` while the user has ``ywatanabe``
     * selected (or vice-versa) is NOT double-counted as unread in its
     * own focused channel. */
    var msgCh = msg.channel || msg.chat_id || "";
    if (msgCh && !channelsEqual(msgCh, (globalThis as any).currentChannel)) {
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
      if (chName === (globalThis as any).currentChannel) _updateChannelTopicBanner(chName);
    }
  } else if (msg.type === "channel_identity") {
    /* Live identity update: icon/color changed. Re-populate the
     * channelIdentity caches and refresh the three render surfaces. */
    var chIdName = msg.channel;
    if (chIdName) {
      _channelDescriptions[chIdName] = msg.description || "";
      if (typeof cacheChannelIdentity === "function") {
        cacheChannelIdentity({
          name: chIdName,
          icon_emoji: msg.icon_emoji || "",
          icon_image: msg.icon_image || "",
          icon_text: msg.icon_text || "",
          color: msg.color || "",
        });
      }
      if (chIdName === (globalThis as any).currentChannel) _updateChannelTopicBanner(chIdName);
      /* Re-render sidebar + pool chips + canvas so the new icon shows
       * without a page reload. fetchStats drives the sidebar; the
       * Activity tab's next render cycle picks up the cache change. */
      if (typeof fetchStats === "function") fetchStats();
      if (typeof renderActivityTab === "function") renderActivityTab();
    }
  }
}

/* Reset unread count when tab becomes visible */
document.addEventListener("visibilitychange", function () {
  if (!document.hidden) {
    (globalThis as any).unreadCount = 0;
    document.title = baseTitle;
  }
});

/* Per-channel unread badges (#322) */
export function updateChannelUnreadBadges() {
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

export function connect() {
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
    /* On reconnect ((globalThis as any).historyLoaded=true), fetch only new messages
     * incrementally instead of doing a full DOM rebuild.  A full
     * loadHistory() on mobile Safari causes massive innerHTML churn
     * that can reset the textarea value / dismiss the keyboard while
     * the user is typing. */
    if ((globalThis as any).historyLoaded) {
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
