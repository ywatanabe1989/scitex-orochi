// @ts-nocheck
import { _channelPrefs } from "./members";
import { fetchAgents } from "./sidebar-agents";
import { fetchStats } from "./sidebar-stats";
import { setCurrentChannel } from "./state";
import { apiUrl, getCsrfToken, token } from "./utils";
import { fetchAgentsThrottled } from "./websocket";
import { loadChannelHistory } from "../chat/chat-history";
import { _activateTab } from "../tabs";


/* POST /api/channel-members/ with a chosen permission. Reuses the same
 * endpoint as _toggleAgentChannelSubscription but passes the permission
 * body field (see hub/views/api.py api_channel_members). */
export function _agentSubscribe(agentName, channel, permission) {
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
export function _openAgentDmSimple(agentA, agentB) {
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
export function _agentDmCreate(selfAgent, otherAgent, dir) {
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
export function openChannelExport(ch) {
  var modal = document.getElementById("channel-export-modal");
  if (!modal) return;
  var now = new Date();
  var todayStart = now.toISOString().slice(0, 10) + "T00:00";
  var todayNow = now.toISOString().slice(0, 16);
  document.getElementById("ch-export-from").value = todayStart;
  document.getElementById("ch-export-to").value = todayNow;
  document.getElementById("ch-export-format").value = "json";
  modal.setAttribute("data-channel", ch || (globalThis as any).currentChannel || "");
  document.getElementById("ch-export-title").textContent =
    "Export " + (ch || (globalThis as any).currentChannel || "channel");
  modal.style.display = "flex";
}

export function closeChannelExport() {
  var modal = document.getElementById("channel-export-modal");
  if (modal) modal.style.display = "none";
}

export function doChannelExport() {
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
export var _dndState = null; /* {el, section, origIndex} */

export function _addDragAndDrop(container, section) {
  container.querySelectorAll(".channel-item[draggable]").forEach(function (el) {
    el.addEventListener("dragstart", function (ev) {
      _dndState = { el: el, section: section };
      el.classList.add("ch-dragging");
      ev.dataTransfer.effectAllowed = "move";
      ev.dataTransfer.setData("text/plain", el.getAttribute("data-channel"));
      /* msg#16988 (a): full-card drag image. See sidebar-agents.ts
       * for the same treatment on agent cards. Without this the
       * browser default ghost is just the text node under the cursor
       * so the drop position is invisible. */
      try {
        var rect = el.getBoundingClientRect();
        var clone = el.cloneNode(true);
        clone.style.position = "absolute";
        clone.style.top = "-10000px";
        clone.style.left = "-10000px";
        clone.style.width = rect.width + "px";
        clone.style.pointerEvents = "none";
        clone.classList.remove("ch-dragging");
        document.body.appendChild(clone);
        var ox = ev.clientX - rect.left;
        var oy = ev.clientY - rect.top;
        ev.dataTransfer.setDragImage(clone, ox, oy);
        setTimeout(function () {
          if (clone.parentNode) clone.parentNode.removeChild(clone);
        }, 0);
      } catch (_) {}
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
      /* msg#16988 (b): synchronously re-render the sidebar from the
       * updated local _channelPrefs — do NOT rely on the next
       * fetchStats() tick / WS round-trip, which can arrive with
       * stale server data (PATCH still in-flight) and revert the
       * visible order until the user reloads. Bust the stats cache
       * so fetchStats rebuilds from our sort_order snapshot, then
       * call it imperatively. */
      try {
        var chContainer = document.getElementById("channels");
        if (chContainer) chContainer._lastStatsJson = null;
      } catch (_) {}
      if (typeof fetchStats === "function") fetchStats();
    });
  });
}

/* ── todo#49: agent ↔ channel subscription DnD helpers ── */
export function _agentHasChannel(channelsCsv, channel) {
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

export function _setChannelDropHint(el, text) {
  var hint = el.querySelector(".ch-hint");
  if (!hint) {
    hint = document.createElement("span");
    hint.className = "ch-hint";
    el.appendChild(hint);
  }
  hint.textContent = text;
}

export function _agentDjangoUsername(name) {
  /* Mirrors hub/views/api.py: re.sub(r"[^a-zA-Z0-9_.\-]", "-", name) */
  if (!name) return "";
  var safe = String(name).replace(/[^a-zA-Z0-9_.\-]/g, "-");
  return "agent-" + safe;
}

export function _showMiniToast(text, kind) {
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

export function _toggleAgentChannelSubscription(agentName, channel, subscribe) {
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
