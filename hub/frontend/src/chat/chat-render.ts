// @ts-nocheck
import { getResolvedAgentColor, getSenderIcon } from "../agent-icons";
import { channelsEqual, cleanAgentName, escapeHtml, hostedAgentName, timeAgo, userName } from "../app/utils";
import { _renderMermaidIn, buildAttachmentsHtml } from "./chat-attachments";
import { _processMessageMarkdown } from "./chat-markdown";
import { _chatFilterQuery, _mentionRegex, _pulseSidebarRow, _voiceDeferQueue, applyIssueTitleHints, isKnownAgent } from "./chat-state";
import { updateResourcePanel } from "../resources-tab/panel";

export function appendMessage(msg) {
  /* Filter hub-internal system messages from the feed (msg#10315).
   * Hub sends mention_reply messages (sender="hub") as status responses
   * when agents are @mentioned. These are noisy in regular channels. */
  var _meta = msg.metadata || {};
  if (msg.sender === "hub" && _meta.source === "mention_reply") return;

  /* Voice-recording guard: defer the DOM update to avoid interrupting the
   * Web Speech API SpeechRecognition session. Scroll and layout changes
   * during active recording can cause the browser to abort recognition.
   * The queue is flushed by _flushVoiceQueue() when recording stops.
   *
   * Exception (scitex-orochi#172): render the user's OWN echoed post
   * immediately even during continuous dictation. Deferring own-posts made
   * the feed look frozen after Ctrl+Enter-send-while-dictating — ywatanabe's
   * primary voice workflow (msg#6500/#6504 + msg#13124). Auto-scroll is
   * already suppressed during recording (see the `!window.isVoiceRecording`
   * guard in the appendChild block below) and focus is restored after the
   * DOM write, so the layout shift from rendering one own-post is tolerable
   * for recognition. Other agents' / other users' messages continue to be
   * deferred to keep the feed quiet during dictation. */
  var _ownPostDuringVoice =
    window.isVoiceRecording &&
    typeof userName !== "undefined" &&
    msg.sender === userName;
  if (window.isVoiceRecording && !_ownPostDuringVoice) {
    _voiceDeferQueue.push(msg);
    return;
  }
  var el = document.createElement("div");
  var senderName = msg.sender || "unknown";
  var isAgent = msg.sender_type === "agent" || isKnownAgent(senderName);
  el.className = "msg" + (isAgent ? "" : " msg-human");
  if (msg.id) el.setAttribute("data-msg-id", String(msg.id));
  /* todo#274 Part 2: tag sender for multi-select AND filter */
  el.setAttribute("data-sender", senderName);
  var ts = "";
  var fullTs = "";
  if (msg.ts) {
    var d = new Date(msg.ts);
    if (!isNaN(d.getTime())) {
      ts = timeAgo(msg.ts);
      fullTs = d.toLocaleString();
    }
  }
  var channel = (msg.payload && msg.payload.channel) || "";
  var content = "";
  if (msg.payload) {
    content =
      msg.payload.content || msg.payload.text || msg.payload.message || "";
  }
  /* Fallback to top-level fields (WebSocket flat format) */
  if (!content) {
    content = msg.text || msg.content || "";
  }
  /* Intercept resource reports */
  var meta = (msg.payload && msg.payload.metadata) || {};
  if (meta.type === "resource_report" && meta.data) {
    updateResourcePanel(meta.data);
  }
  /* Allow attachment-only messages (empty text with images/files) */
  var attachments =
    (msg.payload && msg.payload.attachments) ||
    (msg.metadata && msg.metadata.attachments) ||
    msg.attachments ||
    [];
  if (!content && attachments.length === 0) return;
  var senderColor = getResolvedAgentColor(senderName);
  if (channel) {
    el.setAttribute("data-channel", channel);
  }
  /* Mentions must be highlighted BEFORE the newline→<br> conversion,
   * otherwise a mention sitting right after a line break doesn't match
   * the `(^|[\s])` anchor (since <br> is not whitespace). */
  var highlightedContent = _processMessageMarkdown(content);

  /* Fold long posts (>10 lines).
   * Count <br> splits AND lines inside <pre> blocks for an accurate total. */
  var MAX_LINES = 10;
  var _countLines = function (html) {
    var n = html.split("<br>").length;
    /* Each <pre> block contributes (newline count) additional visual lines */
    html.replace(/<pre[\s\S]*?<\/pre>/g, function (pre) {
      n += (pre.match(/\n/g) || []).length;
    });
    return n;
  };
  var lines = highlightedContent.split("<br>");
  var totalLines = _countLines(highlightedContent);
  var isFolded = totalLines > MAX_LINES;
  if (isFolded) {
    var preview = lines.slice(0, MAX_LINES).join("<br>");
    var full = highlightedContent;
    var extraLines = totalLines - MAX_LINES;
    highlightedContent =
      '<div class="msg-preview">' +
      preview +
      "</div>" +
      '<div class="msg-full" style="display:none">' +
      full +
      "</div>" +
      '<button class="msg-fold-btn" tabindex="-1" data-extra="' +
      extraLines +
      '">Show more (' +
      extraLines +
      " more lines)</button>";
  }
  /* Inline reply reference — if this message has metadata.reply_to
   * pointing at another message id, render a small quoted preview of
   * the parent above the content so the relationship is visible in
   * the main feed (not only in the thread side panel). */
  var replyRefHtml = "";
  var metaObj = (msg.payload && msg.payload.metadata) || msg.metadata || {};
  var replyToId = metaObj && metaObj.reply_to;
  if (replyToId) {
    var parentEl = document.querySelector(
      '.msg[data-msg-id="' + String(replyToId) + '"]',
    );
    var parentSender = "";
    var parentSnippet = "";
    if (parentEl) {
      var senderEl = parentEl.querySelector(".sender");
      var bodyEl = parentEl.querySelector(".content");
      parentSender = senderEl ? senderEl.textContent : "";
      parentSnippet = bodyEl ? bodyEl.textContent.slice(0, 120) : "";
    }
    replyRefHtml =
      '<div class="msg-reply-ref" data-parent-id="' +
      String(replyToId) +
      '" title="Click to jump to parent">' +
      '<span class="msg-reply-icon">\u21b3</span> ' +
      (parentSender
        ? '<span class="msg-reply-parent">' +
          escapeHtml(parentSender) +
          "</span>: "
        : '<span class="msg-reply-parent">msg#' + replyToId + "</span>: ") +
      '<span class="msg-reply-snippet">' +
      escapeHtml(parentSnippet || "(scroll up to load)") +
      "</span>" +
      "</div>";
  }

  /* attachments already resolved above (for the empty-content guard) */
  var attachmentsHtml = buildAttachmentsHtml(attachments);
  var roleBadge = "";
  var youTag =
    senderName === userName ? ' <span class="you-tag">(You)</span>' : "";
  var senderIcon = getSenderIcon(senderName, isAgent);
  el.innerHTML =
    '<div class="msg-header">' +
    '<span class="msg-icon">' +
    senderIcon +
    "</span>" +
    '<span class="sender" style="color:' +
    senderColor +
    '">' +
    /* #238: include @hostname in chat-feed sender headers, mirroring
     * the sidebar Agents list. Look up the agent record in the live
     * cache (window.__lastAgents) and pass to hostedAgentName so
     * cleanAgentName collapses redundant role-host suffixes
     * (head-mba@mba → head@mba). Falls back to bare cleanAgentName
     * for humans / unknown senders. */
    escapeHtml(
      isAgent
        ? (function () {
            var rec = (window.__lastAgents || []).find(function (a) {
              return a && a.name === senderName;
            });
            return rec ? hostedAgentName(rec) : cleanAgentName(senderName);
          })()
        : cleanAgentName(senderName),
    ) +
    "</span>" +
    youTag +
    roleBadge +
    '<a href="#" class="channel channel-link" data-channel="' +
    escapeHtml(channel) +
    '" title="Switch to ' +
    escapeHtml(channel) +
    '">' +
    escapeHtml(channel) +
    "</a>" +
    '<span class="ts" title="' +
    escapeHtml(fullTs) +
    '">' +
    ts +
    "</span>" +
    (msg.id
      ? '<span class="msg-id-chip" title="Message ID">#' + msg.id + "</span>"
      : "") +
    (msg.edited
      ? '<span class="msg-edited-tag" title="' +
        escapeHtml(
          msg.edited_at ? "Edited " + timeAgo(msg.edited_at) : "Edited",
        ) +
        '">(edited)</span>'
      : "") +
    "</div>" +
    replyRefHtml +
    '<div class="content">' +
    highlightedContent +
    "</div>" +
    attachmentsHtml +
    (msg.id
      ? '<div class="msg-reactions" data-msg-id="' + msg.id + '"></div>'
      : "") +
    (msg.id
      ? '<button class="msg-react-btn" type="button" title="React" onclick="openReactionPicker(this,' +
        msg.id +
        ')">+</button>'
      : "") +
    (msg.id
      ? '<button class="msg-thread-btn" type="button" title="Reply in thread" onclick="openThreadForMessage(' +
        msg.id +
        ')">\uD83D\uDCAC</button>'
      : "") +
    (msg.id
      ? '<button class="permalink-btn msg-permalink-btn" type="button" tabindex="-1" ' +
        'title="Copy link to this thread" ' +
        'onclick="event.stopPropagation();copyThreadPermalink(' +
        msg.id +
        ',this)">\uD83D\uDD17</button>'
      : "") +
    (msg.id && senderName === userName
      ? '<button class="msg-edit-btn" type="button" title="Edit message" onclick="startEditMessage(' +
        msg.id +
        ')">&#9998;</button>'
      : "") +
    (msg.id && senderName === userName
      ? '<button class="msg-delete-btn" type="button" title="Delete message" onclick="deleteMessage(' +
        msg.id +
        ')">&#10005;</button>'
      : "") +
    (function () {
      var tc = msg.thread_count || 0;
      if (!msg.id || tc === 0) return "";
      return (
        '<div class="msg-thread-count" data-msg-id="' +
        msg.id +
        '" onclick="openThreadForMessage(' +
        msg.id +
        ')">' +
        "\uD83D\uDCAC " +
        tc +
        (tc === 1 ? " reply" : " replies") +
        "</div>"
      );
    })();
  /* Hydrate PDF first-page thumbnails in this message's attachments
   * (todo#89). Safe no-op if pdf-thumbnail.js hasn't loaded yet. */
  if (window.pdfThumb) window.pdfThumb.hydrateAll(el);
  /* Channel guard: hide this row if we're currently filtered to a single
   * channel and the incoming message doesn't belong to it. Use channelsEqual
   * (msg#16691) so ``#ywatanabe`` vs ``ywatanabe`` is treated as the same
   * channel — the mismatch was the root cause of the silent-feed regression
   * where every inbound WS message landed in the DOM with display:none. */
  if (
    (globalThis as any).currentChannel &&
    !channelsEqual(channel, (globalThis as any).currentChannel)
  ) {
    el.style.display = "none";
  }
  var container = document.getElementById("messages");
  /* Only auto-scroll if user is already near the bottom (within 150px).
   * This prevents forced scrolling while the user is typing or reading
   * older messages, which on mobile Safari can disrupt the textarea
   * (dismiss keyboard, lose IME composition, or reset input value). */
  var nearBottom =
    container.scrollHeight - container.scrollTop - container.clientHeight < 150;
  /* Preserve textarea focus/selection across DOM mutation + scroll.
   * todo#225: on the dashboard, inbound WS messages were causing the
   * compose textarea to lose focus mid-typing. The root cause is the
   * appendChild + scrollTop write on #messages: even though the textarea
   * is a sibling, browsers can blur it when the focused element is in a
   * container whose layout shifts under an async scroll write, and the
   * same path is responsible for todo#55's pending-attachment / input
   * state loss. We snapshot focus before the mutation and restore it
   * afterward, and we skip the auto-scroll entirely while the user is
   * actively typing so we don't yank their viewport either.
   *
   * Voice recording: additionally save/restore the full activeElement +
   * selection so that DOM mutations during SpeechRecognition don't steal
   * focus away from the textarea that the speech API is writing into.
   * (Note: appendMessage already returns early when window.isVoiceRecording
   * is true — this path is reached only for non-voice DOM updates.) */
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  /* Also capture any other focused element (e.g. thread textarea) */
  var savedActiveEl = document.activeElement;
  var savedActiveStart = 0;
  var savedActiveEnd = 0;
  if (
    savedActiveEl &&
    savedActiveEl !== msgInput &&
    (savedActiveEl.tagName === "TEXTAREA" || savedActiveEl.tagName === "INPUT")
  ) {
    try {
      savedActiveStart = savedActiveEl.selectionStart;
      savedActiveEnd = savedActiveEl.selectionEnd;
    } catch (_) {}
  }
  container.appendChild(el);
  /* Visual effects: fade-in + mention styling / sidebar pulses.
   * Gated on `(globalThis as any)._initialLoadComplete` so historical backlogs and channel-switch
   * history rebuilds don't animate. Own posts aren't faded (they're echoes
   * of what the user just typed and animating them feels laggy) but mentions
   * of the user still flash via the sidebar pulse below. */
  var _isOwnPost = typeof userName !== "undefined" && senderName === userName;
  if ((globalThis as any)._initialLoadComplete && !(globalThis as any)._isLoadingHistory && !_isOwnPost) {
    el.classList.add("msg-arrived");
    setTimeout(function () {
      el.classList.remove("msg-arrived");
    }, 400);
  }
  /* Mention detection: @<userName> or @me (case-insensitive). Persistent
   * class — left border + bg tint via effects.css. Skip if this is the
   * user's own message (you don't mention yourself). */
  var _hasMention = !_isOwnPost && _mentionRegex().test(content);
  if (_hasMention) {
    el.classList.add("msg-mention");
  }
  /* Sidebar pulses — only for messages arriving AFTER initial load,
   * and only if the message is in a non-focused channel. */
  if ((globalThis as any)._initialLoadComplete && !(globalThis as any)._isLoadingHistory && channel) {
    /* `#`-prefix-agnostic match (msg#16691) — same rationale as the
     * display-guard above. Without this, own-channel arrivals could wrongly
     * pulse the sidebar row as "unread mention" on legacy channel rows. */
    var _isFocused = channelsEqual(channel, (globalThis as any).currentChannel);
    if (!_isFocused) {
      if (_hasMention) {
        _pulseSidebarRow(channel, "mention");
      } else if (channel.indexOf("dm:") === 0 && !_isOwnPost) {
        _pulseSidebarRow(channel, "dm");
      }
    }
  }
  /* Lazy-create DM sidebar refresh (todo#418 follow-up): when a message
   * arrives on a dm:<...> channel that the sidebar hasn't listed yet,
   * the 10s poll in dms.js would leave the row invisible for up to 10s
   * after the backend lazily created the DM on first send. Kick
   * fetchDms() immediately so the new row appears right away. Covers
   * both inbound (someone DMs me) and own-send (I send to a new DM)
   * paths — fetchDms() is idempotent and JSON-diffed internally. */
  if (channel && channel.indexOf("dm:") === 0) {
    var _dmRowPresent =
      document.querySelector(
        '.dm-item[data-channel="' + channel.replace(/"/g, '\\"') + '"]',
      ) !== null;
    if (!_dmRowPresent && typeof window.fetchDms === "function") {
      try {
        window.fetchDms();
      } catch (_) {}
    }
  }
  /* Render any mermaid diagrams inside the newly appended message */
  _renderMermaidIn(el);
  /* todo#274 Part 2: re-apply multi-select feed filter so newly-arrived
   * messages get hidden if they don't match the current selection. */
  if (typeof applyFeedFilter === "function") {
    try {
      applyFeedFilter();
    } catch (_) {}
  }
  /* Re-apply chat filter so newly-arrived messages respect the sticky
   * filter input if the user has one typed. O(1) per incoming message
   * (only tests the one new row). */
  if (_chatFilterQuery) {
    var _txt = (el.textContent || "").toLowerCase();
    if (_txt.indexOf(_chatFilterQuery) !== -1) {
      el.classList.add("chat-filter-hit");
    } else {
      el.classList.add("chat-filter-miss");
    }
  }
  /* Auto-scroll: skip during voice recording to prevent scrollTop writes
   * from interfering with the SpeechRecognition session — EXCEPT when the
   * user just sent a message (window._scrollAfterNextMessage flag set by
   * sendMessage()). Without the exception, the WS echo of the user's own
   * voice-composed post arrives while isVoiceRecording is still true (mic
   * stays on for continuous dictation) and the message scrolls off-screen
   * (#239). The flag is consumed here so at most one message triggers it. */
  var forceScroll = window._scrollAfterNextMessage;
  if (forceScroll) window._scrollAfterNextMessage = false;
  if (nearBottom && (!window.isVoiceRecording || forceScroll)) {
    container.scrollTop = container.scrollHeight;
  }
  /* Restore focus + selection for the main compose textarea */
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try {
      msgInput.setSelectionRange(savedStart, savedEnd);
    } catch (_) {}
  }
  /* Restore focus + selection for any other text input (e.g. thread textarea) */
  if (
    savedActiveEl &&
    savedActiveEl !== msgInput &&
    document.activeElement !== savedActiveEl &&
    (savedActiveEl.tagName === "TEXTAREA" || savedActiveEl.tagName === "INPUT")
  ) {
    try {
      savedActiveEl.focus();
      savedActiveEl.setSelectionRange(savedActiveStart, savedActiveEnd);
    } catch (_) {}
  }
  applyIssueTitleHints(el);
}

export function filterMessages() {
  /* todo#274 Part 2: delegate to applyFeedFilter which supports
   * AND across multiple selected sidebar items. */
  applyFeedFilter();
}

export function applyFeedFilter() {
  var selectedChannels = [];
  var selectedAgents = [];
  document
    .querySelectorAll(".sidebar .channel-item.selected[data-channel]")
    .forEach(function (el) {
      selectedChannels.push(el.getAttribute("data-channel"));
    });
  document
    .querySelectorAll(".sidebar .agent-card.selected[data-agent-name]")
    .forEach(function (el) {
      selectedAgents.push(el.getAttribute("data-agent-name"));
    });
  var hasAnySelection =
    selectedChannels.length > 0 || selectedAgents.length > 0;
  var msgs = document.querySelectorAll(".msg");
  msgs.forEach(function (el) {
    if (!hasAnySelection) {
      if (!(globalThis as any).currentChannel) {
        el.style.display = "";
      } else {
        var ch0 = el.getAttribute("data-channel");
        /* channelsEqual (msg#16691) tolerates ``#``-prefix asymmetry between
         * the stored message ``data-channel`` and the sidebar-driven
         * currentChannel — see chat-render guard above and utils.ts. */
        el.style.display = channelsEqual(ch0, (globalThis as any).currentChannel)
          ? ""
          : "none";
      }
      return;
    }
    var ch = el.getAttribute("data-channel");
    var sender = el.getAttribute("data-sender");
    /* Normalize the incoming channel so a selected sidebar row in either
     * ``#foo`` or ``foo`` form matches an equivalent message. */
    var chOk =
      selectedChannels.length === 0 ||
      selectedChannels.some(function (sc) {
        return channelsEqual(sc, ch);
      });
    var agOk =
      selectedAgents.length === 0 || selectedAgents.indexOf(sender) !== -1;
    el.style.display = chOk && agOk ? "" : "none";
  });
}
