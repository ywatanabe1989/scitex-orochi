// @ts-nocheck
// Migrated classic-script file. Types intentionally loose during
// the big-bang JS-to-TS bundle migration. Narrow later, per-file.
async function loadHistory() {
  /* If a channel is currently selected, delegate to loadChannelHistory so we
   * only fetch that channel's messages.  This prevents a race/flash where the
   * full all-channels response could briefly render before the client-side
   * filter hides non-matching messages (todo#247). */
  if (currentChannel) {
    return loadChannelHistory(currentChannel);
  }
  try {
    var res = await fetch(apiUrl("/api/messages/?limit=100"), {
      credentials: "same-origin",
    });
    if (!res.ok) {
      console.error("loadHistory: API returned", res.status, res.statusText);
      return;
    }
    var messages = await res.json();
    /* API returns newest-first (-ts); reverse for chronological display */
    messages.reverse();
    var container = document.getElementById("messages");

    /* Preserve the textarea value and pending attachments across history
     * rebuilds.  On mobile Safari, large DOM mutations (innerHTML="")
     * while the keyboard is up can cause the browser to reset or blur
     * the focused textarea, losing the user's in-progress message. */
    var msgInput = document.getElementById("msg-input");
    var savedValue = msgInput ? msgInput.value : "";
    var hadFocus = msgInput && document.activeElement === msgInput;
    var savedStart = msgInput ? msgInput.selectionStart : 0;
    var savedEnd = msgInput ? msgInput.selectionEnd : 0;
    /* Save pending attachments (uploaded files waiting to be sent) */
    var savedAttachments =
      typeof pendingAttachments !== "undefined"
        ? pendingAttachments.slice()
        : [];

    container.innerHTML = "";
    knownMessageKeys = {};
    /* Suppress arrival animations / sidebar pulses for this bulk backlog. */
    _isLoadingHistory = true;
    try {
      messages.forEach(function (row) {
        var key = messageKey(row.sender, row.ts, row.content);
        knownMessageKeys[key] = true;
        appendMessage({
          id: row.id,
          type: "message",
          sender: row.sender,
          sender_type: row.sender_type,
          ts: row.ts,
          edited: row.edited || false,
          edited_at: row.edited_at || null,
          thread_count: row.thread_count || 0,
          metadata: row.metadata || {},
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
    } finally {
      _isLoadingHistory = false;
      _initialLoadComplete = true;
    }
    container.scrollTop = container.scrollHeight;

    /* Restore textarea state if the DOM rebuild clobbered it */
    if (msgInput && savedValue && !msgInput.value) {
      msgInput.value = savedValue;
      if (hadFocus) {
        msgInput.focus();
        try {
          msgInput.setSelectionRange(savedStart, savedEnd);
        } catch (_) {}
      }
    }
    /* Restore pending attachments if they were lost */
    if (
      savedAttachments.length &&
      typeof pendingAttachments !== "undefined" &&
      !pendingAttachments.length
    ) {
      pendingAttachments = savedAttachments;
      if (typeof _renderAttachmentTray === "function") _renderAttachmentTray();
    }

    historyLoaded = true;
    /* If the page was loaded with ?thread=<id>, auto-open that thread now
     * that the parent message DOM exists (todo#237). */
    if (typeof applyThreadUrlOnLoad === "function") {
      try {
        applyThreadUrlOnLoad();
      } catch (_) {}
    }
    /* Fetch reactions for all loaded messages */
    if (typeof fetchReactionsForMessages === "function") {
      var ids = messages
        .map(function (r) {
          return r.id;
        })
        .filter(Boolean);
      fetchReactionsForMessages(ids);
    }
  } catch (e) {
    console.error("loadHistory failed:", e);
  }
}

/* Lightweight alternative to loadHistory for WebSocket reconnects.
 * Fetches recent messages and appends only those we haven't seen,
 * avoiding the full innerHTML="" rebuild that disrupts the textarea
 * on mobile Safari. */
async function fetchNewMessages() {
  try {
    var endpoint = currentChannel
      ? "/api/history/" + encodeURIComponent(currentChannel) + "?limit=50"
      : "/api/messages/?limit=50";
    var res = await fetch(apiUrl(endpoint), { credentials: "same-origin" });
    if (!res.ok) return;
    var messages = await res.json();
    messages.reverse();
    _isLoadingHistory = true;
    try {
      messages.forEach(function (row) {
        var key = messageKey(row.sender, row.ts, row.content);
        if (knownMessageKeys[key]) return;
        knownMessageKeys[key] = true;
        appendMessage({
          id: row.id,
          type: "message",
          sender: row.sender,
          sender_type: row.sender_type,
          ts: row.ts,
          edited: row.edited || false,
          edited_at: row.edited_at || null,
          thread_count: row.thread_count || 0,
          metadata: row.metadata || {},
          payload: {
            channel: row.channel || currentChannel || "",
            content: row.content,
            attachments:
              (row.metadata && row.metadata.attachments) ||
              row.attachments ||
              [],
          },
        });
      });
    } finally {
      _isLoadingHistory = false;
    }
  } catch (e) {
    console.warn("fetchNewMessages failed:", e);
  }
}

async function loadChannelHistory(channel) {
  try {
    var encodedChannel = encodeURIComponent(channel);
    var res = await fetch(
      apiUrl("/api/history/" + encodedChannel + "?limit=100"),
      { credentials: "same-origin" },
    );
    if (!res.ok) {
      console.error(
        "loadChannelHistory: API returned",
        res.status,
        res.statusText,
      );
      return;
    }
    var messages = await res.json();
    /* API returns newest-first (-ts); reverse for chronological display */
    messages.reverse();
    var container = document.getElementById("messages");

    /* Preserve textarea value + attachments -- see loadHistory */
    var msgInput = document.getElementById("msg-input");
    var savedValue = msgInput ? msgInput.value : "";
    var hadFocus = msgInput && document.activeElement === msgInput;
    var savedStart = msgInput ? msgInput.selectionStart : 0;
    var savedEnd = msgInput ? msgInput.selectionEnd : 0;
    var savedAttachments =
      typeof pendingAttachments !== "undefined"
        ? pendingAttachments.slice()
        : [];

    container.innerHTML = "";
    knownMessageKeys = {};
    /* Suppress arrival animations / sidebar pulses for this bulk backlog. */
    _isLoadingHistory = true;
    try {
      messages.forEach(function (row) {
        var key = messageKey(row.sender, row.ts, row.content);
        knownMessageKeys[key] = true;
        appendMessage({
          id: row.id,
          type: "message",
          sender: row.sender,
          sender_type: row.sender_type,
          ts: row.ts,
          edited: row.edited || false,
          edited_at: row.edited_at || null,
          thread_count: row.thread_count || 0,
          metadata: row.metadata || {},
          payload: {
            channel: channel,
            content: row.content,
            attachments:
              (row.metadata && row.metadata.attachments) ||
              row.attachments ||
              [],
          },
        });
      });
    } finally {
      _isLoadingHistory = false;
      _initialLoadComplete = true;
    }
    container.scrollTop = container.scrollHeight;

    /* Restore textarea state if the DOM rebuild clobbered it */
    if (msgInput && savedValue && !msgInput.value) {
      msgInput.value = savedValue;
      if (hadFocus) {
        msgInput.focus();
        try {
          msgInput.setSelectionRange(savedStart, savedEnd);
        } catch (_) {}
      }
    }
    /* Restore pending attachments */
    if (
      savedAttachments.length &&
      typeof pendingAttachments !== "undefined" &&
      !pendingAttachments.length
    ) {
      pendingAttachments = savedAttachments;
      if (typeof _renderAttachmentTray === "function") _renderAttachmentTray();
    }

    historyLoaded = true;
    /* If the page was loaded with ?thread=<id>, auto-open that thread now */
    if (typeof applyThreadUrlOnLoad === "function") {
      try {
        applyThreadUrlOnLoad();
      } catch (_) {}
    }
    if (typeof fetchReactionsForMessages === "function") {
      var ids = messages
        .map(function (r) {
          return r.id;
        })
        .filter(Boolean);
      fetchReactionsForMessages(ids);
    }
  } catch (e) {
    console.error("Failed to load channel history:", e);
  }
}
