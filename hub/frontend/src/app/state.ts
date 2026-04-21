// @ts-nocheck
import { _updateChannelTopicBanner } from "./members";
import { chatFilterReset } from "../chat/chat-state";

/* Orochi Dashboard -- core globals, WS connection, sidebar (Django hub) */

/* System error banner — shown at top of page for critical errors */
export function showSystemBanner(message, level) {
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
export var OROCHI_COLORS = [
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
export var lastActiveChannel = null;
try {
  var _persistedCh = localStorage.getItem("orochi_active_channel");
  if (_persistedCh && _persistedCh !== "__all__") {
    currentChannel = _persistedCh;
    lastActiveChannel = _persistedCh;
  }
} catch (_) {}
export function setCurrentChannel(ch) {
  currentChannel = ch;
  if (ch) lastActiveChannel = ch;
  /* #278: other modules read `(globalThis as any).currentChannel` — the
   * module-local `var currentChannel` is a private binding that the rest
   * of the app can't see. Without this write, a sidebar channel switch
   * updates the local var but leaves the global pinned at its page-load
   * value, causing the feed to stay stale, the WS filter to pass the wrong
   * channel, and sendMessage() to post to the original channel instead of
   * the one the sidebar highlights. Mirror every update to the global. */
  (globalThis as any).currentChannel = ch;
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
  /* msg#16324: hydrate the per-channel draft into the composer on
   * channel switch. Each channel keeps its own in-progress text, so
   * switching to a channel the user was previously drafting in brings
   * that text back. Before hydrating, we (a) flush any debounced save
   * pending for the OLD channel so its last keystrokes hit storage,
   * and (b) clear the textarea so the new channel's draft can
   * populate (the restore helper is a no-op when the textarea already
   * has text). */
  try {
    var _flush = (window as any).orochiDraftStore
      ? (window as any).orochiDraftStore.flushPendingSaves
      : null;
    if (typeof _flush === "function") _flush();
    var _inp = document.getElementById("msg-input");
    if (_inp) {
      _inp.value = "";
      _inp.style.height = "auto";
    }
    var _restore = (window as any).restoreDraftForCurrentChannel;
    if (typeof _restore === "function") _restore();
  } catch (_) {}
}

/* Friendly-label for a dm:<principal>|<principal> channel. Strips the
 * "dm:" prefix, splits on "|", drops the self principal when known, and
 * strips "agent:"/"human:" type prefixes so the result is "@name" (or
 * "@a, @b" when the self principal can't be determined). */
export function _dmFriendlyLabel(ch) {
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

export function _updateComposerTarget(ch, isReply, replyMsgId) {
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

// Expose cross-file mutable state via globalThis:
(globalThis as any).currentChannel = (typeof currentChannel !== 'undefined' ? currentChannel : undefined);
