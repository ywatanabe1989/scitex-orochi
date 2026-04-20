// @ts-nocheck
/* Chat module -- markdown / mention / link / code-block content rendering.
 * Extracted from appendMessage() so chat-render.js stays under the JS
 * line limit. Pure helper: takes raw content text, returns the
 * highlighted/escaped HTML string ready to drop into a .content div. */

function _processMessageMarkdown(content) {
  var escaped = escapeHtml(content);

  /* Fenced code blocks: ```lang\n...\n``` — extract BEFORE inline processing
   * so the inline-code regex and \n→<br> don't corrupt their content. (#375)
   * Placeholder: NUL-delimited tokens replaced after all inline processing. */
  var _codeBlocks = [];
  escaped = escaped.replace(
    /```([\w.+-]*)[ \t]*\n([\s\S]*?)```/g,
    function (_, lang, code) {
      var trimmed = code.replace(/\n$/, "");
      var html;
      if (lang && lang.toLowerCase() === "mermaid") {
        /* Mermaid diagrams: render as SVG inline with a raw-script toggle */
        html =
          '<div class="mermaid-container">' +
          '<div class="mermaid-rendered">' +
          trimmed +
          "</div>" +
          '<pre class="mermaid-raw" style="display:none"><code>' +
          trimmed +
          "</code></pre>" +
          '<button class="mermaid-toggle">Show raw</button>' +
          "</div>";
      } else {
        var hljsCls = lang ? ' class="language-' + lang + '"' : "";
        var langBadge = lang
          ? '<span class="code-lang-badge">' + escapeHtml(lang) + "</span>"
          : "";
        html =
          '<div class="code-block-wrap">' +
          langBadge +
          '<pre class="code-block"><code' +
          hljsCls +
          ">" +
          trimmed +
          "</code></pre></div>";
      }
      _codeBlocks.push(html);
      return "\x00" + (_codeBlocks.length - 1) + "\x00";
    },
  );

  /* Blockquote: lines beginning with `> ` (rendered as &gt; after escaping).
   * Process before inline markup so block structure is resolved first. (#9721) */
  escaped = (function _blockquote(s) {
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
            block.join("\n") +
            "</blockquote>",
        );
      } else {
        out.push(lines[i]);
        i++;
      }
    }
    return out.join("\n");
  })(escaped);

  /* Bare-name mentions: highlight the known agent/member names even when
   * they appear without a leading @. Kept conservative by requiring the
   * name to be sourced from cachedAgentNames/cachedMemberNames and by
   * using word boundaries so substrings inside other words don't match. */
  function _highlightBareNames(s) {
    var names = [];
    if (
      typeof cachedAgentNames !== "undefined" &&
      Array.isArray(cachedAgentNames)
    ) {
      names = names.concat(cachedAgentNames);
    }
    if (
      typeof cachedMemberNames !== "undefined" &&
      Array.isArray(cachedMemberNames)
    ) {
      names = names.concat(cachedMemberNames);
    }
    /* Dedup + longest-first so "head@mba" wins over "head" */
    names = Array.from(new Set(names)).filter(Boolean);
    names.sort(function (a, b) {
      return b.length - a.length;
    });
    names.forEach(function (n) {
      if (!n || n.length < 2) return;
      var escName = n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      /* Skip if already inside a mention-highlight span */
      var re = new RegExp("(^|[^\\w@>])" + escName + "(?![\\w@.-])", "g");
      s = s.replace(re, function (match, lead, offset, full) {
        /* Don't double-wrap if the match is already within an existing
         * <span class="mention-highlight">…</span>. Cheap scan backwards. */
        var before = full.slice(0, offset + lead.length);
        var lastOpen = before.lastIndexOf("<span");
        var lastClose = before.lastIndexOf("</span>");
        if (lastOpen > lastClose) return match;
        return lead + '<span class="mention-highlight">' + n + "</span>";
      });
    });
    return s;
  }

  /* Group mention tokens (@heads, @healers, @mambas, @all, @agents) get a
   * distinct chip class with a tooltip describing who the group expands to.
   * Kept in sync with hub/consumers.py GROUP_PATTERNS (todo#421). */
  var MENTION_GROUP_TOKENS = {
    heads: "all head-* agents",
    healers: "all mamba-healer-* agents",
    mambas: "all mamba-* agents",
    all: "everyone in the workspace",
    agents: "all agents in the workspace",
  };

  /* Return true if the character at index `idx` of `src` sits inside a
   * single-line `...` inline-code span. Counts backticks from the start
   * of the current line; odd count == inside. Used to suppress mention
   * highlighting for @tokens that live inside backticks (todo#421). */
  function _isInsideInlineCode(src, idx) {
    var lineStart = src.lastIndexOf("\n", idx - 1) + 1;
    var ticks = 0;
    for (var i = lineStart; i < idx; i++) {
      if (src.charCodeAt(i) === 96 /* ` */) ticks++;
    }
    return ticks % 2 === 1;
  }

  /* Match @ after any non-word char so CJK text like「こんにちは@mamba」highlights (#9958) */
  var highlightedContent = escaped.replace(
    /(^|[^\w])@([\w@.\-]+)/g,
    function (match, prefix, name, offset, full) {
      /* Suppress chip/highlight if we are inside an inline `code` span.
       * Fenced ```blocks``` are already replaced with NUL placeholders
       * above, so this guard only needs to worry about backticks. */
      if (_isInsideInlineCode(full, offset + prefix.length)) {
        return match;
      }
      var desc = MENTION_GROUP_TOKENS[name];
      if (desc) {
        return (
          prefix +
          '<span class="mention-group-chip" data-mention-group="' +
          name +
          '" title="@' +
          name +
          " - " +
          desc +
          '">@' +
          name +
          "</span>"
        );
      }
      return prefix + '<span class="mention-highlight">@' + name + "</span>";
    },
  );
  highlightedContent = _highlightBareNames(highlightedContent)
    /* Inline markdown: **bold**, *italic*, `code` */
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, "<em>$1</em>")
    .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
    .replace(/\n/g, "<br>")
    .replace(
      /(#(?:general|todo|research|deploy|telegram|orchestrator))\b/g,
      '<span class="channel-highlight">$1</span>',
    )
    /* Cross-repo references: `owner/repo#N` → GitHub issue link.
     * Must run before the bare `#N` rule so the slash-prefixed form wins
     * (the bare rule has a `(?<![\/\w])` guard that lets this pass). */
    .replace(
      /(^|[^\w\/])([\w.-]+\/[\w.-]+)#(\d+)\b/g,
      function (_m, lead, repo, num) {
        var label = repo + "#" + num;
        return (
          lead +
          '<a class="issue-link" data-issue-repo="' +
          repo +
          '" data-issue-num="' +
          num +
          '" data-issue-label="' +
          label +
          '" href="https://github.com/' +
          repo +
          "/issues/" +
          num +
          '" target="_blank" rel="noopener">' +
          label +
          "</a>"
        );
      },
    )
    .replace(
      /(?<![\/\w])#(\d+)\b/g,
      '<a class="issue-link" data-issue-num="$1" data-issue-label="#$1" href="https://github.com/ywatanabe1989/todo/issues/$1" target="_blank">#$1</a>',
    )
    /* Auto-link plain URLs. The lookbehind only blocks URLs that are
     * already inside an HTML attribute value (`="...` or `'...`); the
     * previous version also blocked `>`, which mis-fired on URLs sitting
     * right after a `<br>` tag (the prior `\n → <br>` substitution leaves
     * `>` as the char immediately before any line-leading URL), so URLs
     * at the start of a wrapped line never became clickable.
     * todo#239 / msg 5961 / ywatanabe report msg 6058. */
    /* Auto-link msg#NNN references — click opens thread panel (msg#9644 spec) */
    .replace(
      /\bmsg#(\d+)\b/g,
      '<a class="msg-ref-link" href="#" data-msg-ref="$1" onclick="event.preventDefault();jumpToMsg(\'$1\')">msg#$1</a>',
    )
    .replace(
      /(?<!["'=])(https?:\/\/[^\s<>"')\]]+)/g,
      '<a class="chat-link" href="$1" target="_blank" rel="noopener">$1</a>',
    )
    /* Auto-link bare www. URLs (no scheme) — prepend https:// for href.
     * Must run after the https?:// replacement so we don't double-link.
     * Skip if already inside an <a> tag (lookbehind for `href="`). */
    .replace(
      /(?<!["'=\/])\b(www\.[a-zA-Z0-9\-]+\.[a-zA-Z]{2,}[^\s<>"')\]]*)/g,
      '<a class="chat-link" href="https://$1" target="_blank" rel="noopener">$1</a>',
    );

  /* Restore fenced code blocks (placeholders → <pre><code>) (#375) */
  if (_codeBlocks.length > 0) {
    highlightedContent = highlightedContent.replace(
      /\x00(\d+)\x00/g,
      function (_, idx) {
        return _codeBlocks[parseInt(idx, 10)];
      },
    );
  }
  return highlightedContent;
}
