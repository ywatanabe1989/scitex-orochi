// @ts-nocheck
import { apiUrl, escapeHtml } from "../app/utils";
import { closeThreadPanel, openThreadPanel } from "./panel";

/* Threading — state, attachment tray, content linkify, permalink, URL sync */
/* globals: apiUrl, escapeHtml */

var threadPanel = null;
var threadPanelParentId = null;

/* Thread-local pending attachments (separate from main composer
 * pendingAttachments). This is the single source of truth — paste,
 * drop, and file-picker all push here via _stageThreadFiles; the send
 * path (threads/panel.ts::sendThreadReply) reads via
 * getThreadPendingAttachments(); panel open/close + send clear via
 * resetThreadPendingAttachments(). Previously panel.ts reassigned
 * `(globalThis as any).threadPendingAttachments = []`, which broke the
 * reference shared with this module under ES modules — pasted images
 * were staged here but never picked up by the send path, so the Reply
 * composer "lost" pasted attachments (msg#16527). */
var threadPendingAttachments = [];
var _threadSketchActive = false;

/* Accessor + resetter so cross-module consumers never need to reassign
 * the array reference (which would break this module's writers). */
export function getThreadPendingAttachments() {
  return threadPendingAttachments;
}

export function resetThreadPendingAttachments() {
  /* Mutate in place so any existing reference (including the legacy
   * globalThis mirror at the bottom of this file) stays pointing at
   * the live array. */
  threadPendingAttachments.length = 0;
}

export function _renderThreadAttachmentTray() {
  var tray = document.getElementById("thread-pending-attachments");
  if (!tray) return;
  if (!threadPendingAttachments.length) {
    tray.style.display = "none";
    tray.innerHTML = "";
    return;
  }
  tray.style.display = "flex";
  tray.innerHTML = "";
  threadPendingAttachments.forEach(function (p, idx) {
    var item = document.createElement("div");
    item.className = "pending-attachment";
    var isImage =
      p.uploaded &&
      p.uploaded.mime_type &&
      p.uploaded.mime_type.indexOf("image/") === 0;
    var thumb;
    if (isImage) {
      thumb = document.createElement("img");
      thumb.src = p.uploaded.url;
      thumb.className = "pending-attachment-thumb";
      thumb.alt = p.uploaded.filename || "image";
    } else {
      thumb = document.createElement("span");
      thumb.className = "pending-attachment-icon";
      thumb.textContent = "📎";
    }
    var label = document.createElement("span");
    label.className = "pending-attachment-label";
    label.textContent =
      (p.uploaded && p.uploaded.filename) || (p.file && p.file.name) || "file";
    var remove = document.createElement("button");
    remove.type = "button";
    remove.className = "pending-attachment-remove";
    remove.textContent = "×";
    remove.addEventListener("click", function () {
      threadPendingAttachments.splice(idx, 1);
      _renderThreadAttachmentTray();
    });
    item.appendChild(thumb);
    item.appendChild(label);
    item.appendChild(remove);
    tray.appendChild(item);
  });
}

export async function _stageThreadFiles(files) {
  for (var i = 0; i < files.length; i++) {
    var file = files[i];
    try {
      var formData = new FormData();
      formData.append("file", file);
      var res = await fetch(apiUrl("/api/upload/"), {
        method: "POST",
        credentials: "same-origin",
        body: formData,
      });
      if (res.ok) {
        var u = await res.json();
        threadPendingAttachments.push({ file: file, uploaded: u });
        _renderThreadAttachmentTray();
      }
    } catch (e) {
      console.error("Thread file upload error:", e);
    }
  }
}

/* Format thread reply content: markdown-like rendering matching chat.js (todo#385).
 * Input is already-escaped HTML (escapeHtml applied before calling this).
 * Handles: fenced code blocks, inline code, bold, blockquotes, URLs, msg refs. */
export function _linkifyThreadContent(html) {
  /* 1. Extract fenced code blocks before inline processing (same as chat.js #375) */
  var _codeBlocks = [];
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, function (_, lang, body) {
    var idx = _codeBlocks.length;
    var escapedBody = body
      .replace(/&amp;/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
    var langBadge = lang
      ? '<span class="code-lang-badge">' + escapeHtml(lang) + "</span>"
      : "";
    var hljsCls = lang ? ' class="language-' + escapeHtml(lang) + '"' : "";
    _codeBlocks.push(
      '<div class="code-block-wrap">' +
        langBadge +
        '<pre class="code-block"><code' +
        hljsCls +
        ">" +
        escapedBody +
        "</code></pre></div>",
    );
    return "\x00CODE" + idx + "\x00";
  });

  /* 2. Blockquote: lines beginning with &gt; (escaped >) */
  html = (function _bq(s) {
    var lines = s.split("\n");
    var out = [];
    var i = 0;
    while (i < lines.length) {
      if (/^&gt;\s?/.test(lines[i])) {
        var block = [];
        while (i < lines.length && /^&gt;\s?/.test(lines[i])) {
          block.push(lines[i].replace(/^&gt;\s?/, ""));
          i++;
        }
        out.push(
          '<blockquote class="chat-blockquote">' +
            block.join("<br>") +
            "</blockquote>",
        );
      } else {
        out.push(lines[i]);
        i++;
      }
    }
    return out.join("\n");
  })(html);

  /* 3. Inline formatting */
  html = html
    /* Inline code: `...` */
    .replace(/`([^`\n]+)`/g, '<code class="inline-code">$1</code>')
    /* Bold: **...** */
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    /* Italic: *...* (single, not double) */
    .replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, "<em>$1</em>")
    /* msg#NNN refs */
    .replace(
      /\bmsg#(\d+)\b/g,
      '<a class="msg-ref-link" href="#" data-msg-ref="$1" onclick="event.preventDefault();jumpToMsg(\'$1\')">msg#$1</a>',
    )
    /* https?:// URLs */
    .replace(
      /(?<!["'=])(https?:\/\/[^\s<>"')\]]+)/g,
      '<a class="chat-link" href="$1" target="_blank" rel="noopener">$1</a>',
    )
    /* www. bare URLs */
    .replace(
      /(?<!["'=\/])\b(www\.[a-zA-Z0-9\-]+\.[a-zA-Z]{2,}[^\s<>"')\]]*)/g,
      '<a class="chat-link" href="https://$1" target="_blank" rel="noopener">$1</a>',
    );

  /* 4. Restore fenced code blocks */
  if (_codeBlocks.length > 0) {
    html = html.replace(/\x00CODE(\d+)\x00/g, function (_, idx) {
      return _codeBlocks[parseInt(idx, 10)];
    });
  }

  return html;
}

/* Build a permalink URL for a thread parent message. */
export function threadPermalinkUrl(parentId) {
  return (
    window.location.origin +
    window.location.pathname +
    "?thread=" +
    encodeURIComponent(String(parentId))
  );
}

/* Copy a permalink to the clipboard and flash a "Copied!" tooltip on the
 * triggering button.  Never steals focus from #msg-input (todo#225). */
export function copyThreadPermalink(parentId, btnEl) {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  var url = threadPermalinkUrl(parentId);
  var done = function () {
    if (btnEl) {
      var prev = btnEl.getAttribute("data-prev-title") || btnEl.title || "";
      btnEl.setAttribute("data-prev-title", prev);
      btnEl.classList.add("permalink-copied");
      btnEl.title = "Copied!";
      setTimeout(function () {
        btnEl.classList.remove("permalink-copied");
        btnEl.title = prev;
      }, 1500);
    }
    if (inputHasFocus && document.activeElement !== msgInput) {
      msgInput.focus();
      try {
        msgInput.setSelectionRange(savedStart, savedEnd);
      } catch (_) {}
    }
  };
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(done, done);
    } else {
      var ta = document.createElement("textarea");
      ta.value = url;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
      } catch (_) {}
      document.body.removeChild(ta);
      done();
    }
  } catch (_) {
    done();
  }
}

/* Update window.location to reflect whether a thread is open.  Uses
 * history.pushState so the back button works naturally. */
export function _pushThreadUrlState(parentId) {
  try {
    var url;
    if (parentId == null) {
      url = window.location.pathname + window.location.hash;
    } else {
      url =
        window.location.pathname +
        "?thread=" +
        encodeURIComponent(String(parentId)) +
        window.location.hash;
    }
    window.history.pushState({ thread: parentId }, "", url);
  } catch (_) {}
}

export function _readThreadIdFromUrl() {
  try {
    var sp = new URLSearchParams(window.location.search);
    var v = sp.get("thread");
    if (v == null || v === "") return null;
    var n = Number(v);
    return isFinite(n) && n > 0 ? n : null;
  } catch (_) {
    return null;
  }
}

/* Auto-open the thread panel for ?thread=<id> on initial page load.
 * Called from chat.js#loadHistory() after messages are rendered. */
export function applyThreadUrlOnLoad() {
  var id = _readThreadIdFromUrl();
  if (id == null) return;
  if (threadPanelParentId === id) return;
  openThreadPanel(id, { skipPushState: true });
}

/* popstate — user hit back/forward; sync the panel to whatever the URL
 * now says. */
window.addEventListener("popstate", function () {
  var id = _readThreadIdFromUrl();
  if (id == null) {
    if (threadPanel) closeThreadPanel({ skipPushState: true });
  } else if (threadPanelParentId !== id) {
    openThreadPanel(id, { skipPushState: true });
  }
});

// Expose cross-file mutable state via globalThis:
(globalThis as any)._threadSketchActive = (typeof _threadSketchActive !== 'undefined' ? _threadSketchActive : undefined);
(globalThis as any).threadPanel = (typeof threadPanel !== 'undefined' ? threadPanel : undefined);
(globalThis as any).threadPanelParentId = (typeof threadPanelParentId !== 'undefined' ? threadPanelParentId : undefined);
(globalThis as any).threadPendingAttachments = (typeof threadPendingAttachments !== 'undefined' ? threadPendingAttachments : undefined);
