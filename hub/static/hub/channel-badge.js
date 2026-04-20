/**
 * channel-badge.js — single source of truth for the channel badge UI.
 *
 * Parallel to agent-badge.js. Every site that shows a channel
 * (sidebar row, topology pool chip, topology SVG canvas node) MUST
 * call into this module so the UI stays in lockstep across surfaces.
 * ywatanabe directive 2026-04-20: "ALL channel badge MUST have exactly
 * the SAME UI and functionalities (change icon, star/unstar,
 * notification toggle)".
 *
 * Canonical slot order (mirrors sidebar convention):
 *   [drag?] [icon] [star ★/☆] [eye 👁/🚫] [mute 🔔/🔕] [#name] [unread?]
 *
 * Exports (window-scoped — classic script):
 *   channelBadgeModel(name)               — state/model record
 *   renderChannelBadgeHtml(name, opts)    — HTML renderer (sidebar + pool)
 *   renderChannelBadgeSvg(name, pos, opts)— SVG renderer (topology canvas)
 *   attachChannelBadgeHandlers()          — document.body delegation
 *
 * All clicks on .ch-star / .ch-eye / .ch-mute / .ch-icon inside a
 * node carrying [data-channel] are caught by the delegated handler
 * wired from attachChannelBadgeHandlers(). Existing per-row wiring
 * elsewhere can stay — delegation is idempotent — but new sites
 * don't need to reimplement star/eye/mute logic.
 *
 * Hard rule: if you need a new variant, add an opt — never inline a
 * different markup or click handler.
 */

(function () {
  "use strict";

  // ── Helper: HTML escape ─────────────────────────────────────────────
  function _escape(s) {
    if (typeof escapeHtml === "function") return escapeHtml(s);
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return (
        { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[
          c
        ] || c
      );
    });
  }

  function _norm(ch) {
    if (!ch) return "";
    return ch.charAt(0) === "#" ? ch : "#" + ch;
  }

  // ── State model — single source of truth for badge data ────────────
  function channelBadgeModel(name) {
    var raw = name || "";
    var norm = _norm(raw);
    var prefs =
      (typeof window !== "undefined" &&
        window._channelPrefs &&
        (window._channelPrefs[norm] || window._channelPrefs[raw])) ||
      {};
    var unreadMap =
      (typeof window !== "undefined" && window.channelUnread) || {};
    var ident =
      typeof channelIdentity === "function"
        ? channelIdentity(norm)
        : { displayName: norm, tooltip: norm, color: "", iconHtml: null };
    var cachedIcon =
      (typeof cachedChannelIcons !== "undefined" &&
        (cachedChannelIcons[norm] || cachedChannelIcons[raw])) ||
      "";
    var iconIsUrl =
      !!cachedIcon &&
      (cachedIcon.indexOf("http") === 0 || cachedIcon.indexOf("/") === 0);
    return {
      name: raw,
      norm: norm,
      displayName: ident.displayName || norm,
      color: ident.color || "",
      tooltip: ident.tooltip || norm,
      isStarred: !!prefs.is_starred,
      isMuted: !!prefs.is_muted,
      isHidden: !!prefs.is_hidden,
      unread: unreadMap[raw] || unreadMap[norm] || 0,
      iconGlyph: cachedIcon,
      iconIsUrl: iconIsUrl,
      // Same iconHtml(size) contract as channelIdentity.iconHtml so
      // call sites can reuse it unchanged.
      iconHtml: ident.iconHtml,
    };
  }

  // ── HTML renderer: sidebar row + pool chip ─────────────────────────
  function renderChannelBadgeHtml(name, opts) {
    opts = opts || {};
    var m = channelBadgeModel(name);
    var ctx = opts.context || "sidebar"; // "sidebar" | "pool" | "starred"
    var showEye = !!opts.showEye;
    var showUnread = !!opts.showUnread;
    var draggable = !!opts.draggable;
    var displayLabel = opts.label || m.displayName;

    // Drag handle — sidebar only; pool chips aren't drag-reorderable.
    var dragHtml = draggable
      ? '<span class="ch-drag-handle" title="Drag to reorder">&#8942;</span>'
      : "";

    // Icon — call through channelIdentity.iconHtml (cascade image > emoji
    // > text > "#"). Size bumped for sidebar; 14 default.
    var iconPx = opts.iconSize || 14;
    var iconInner =
      typeof m.iconHtml === "function" ? m.iconHtml(iconPx) : _escape(m.norm);
    var iconHtml =
      '<span class="ch-icon ch-identity-icon" data-channel="' +
      _escape(m.norm) +
      '" title="Click to change icon">' +
      iconInner +
      "</span>";

    // Star — always visible (placeholder even when unstarred so columns
    // line up across chips).
    var starHtml =
      '<span class="ch-star ch-pin ' +
      (m.isStarred ? "ch-pin-on ch-star-on" : "ch-pin-off ch-star-off") +
      '" data-channel="' +
      _escape(m.norm) +
      '" data-ch="' +
      _escape(m.norm) +
      '" title="' +
      (m.isStarred ? "Unstar" : "Star (float to top)") +
      '">' +
      (m.isStarred ? "\u2605" : "\u2606") +
      "</span>";

    // Eye — optional (showEye opt). Renders 👁 when visible, 🚫 when hidden.
    var eyeHtml = "";
    if (showEye) {
      eyeHtml =
        '<span class="ch-eye ' +
        (m.isHidden ? "ch-eye-off" : "ch-eye-on") +
        '" data-channel="' +
        _escape(m.norm) +
        '" data-ch="' +
        _escape(m.norm) +
        '" title="' +
        (m.isHidden ? "Show channel (un-hide)" : "Hide channel (dim in list)") +
        '">' +
        (m.isHidden ? "\uD83D\uDEAB" : "\uD83D\uDC41") +
        "</span>";
    }

    // Mute — always visible placeholder so the column geometry is stable.
    var muteHtml =
      '<span class="ch-mute ' +
      (m.isMuted ? "ch-mute-on" : "ch-mute-off") +
      '" data-channel="' +
      _escape(m.norm) +
      '" data-ch="' +
      _escape(m.norm) +
      '" title="' +
      (m.isMuted ? "Unmute notifications" : "Mute notifications") +
      '">' +
      (m.isMuted ? "\uD83D\uDD15" : "\uD83D\uDD14") +
      "</span>";

    // Name label.
    var nameCls = ctx === "pool" ? "ch-name topo-pool-chip-name" : "ch-name";
    var nameHtml =
      '<span class="' + nameCls + '">' + _escape(displayLabel) + "</span>";

    // Unread bubble — sidebar shows N, pool chips skip by default.
    var unreadHtml = "";
    if (showUnread) {
      unreadHtml =
        '<span class="ch-badge-slot">' +
        (m.unread > 0
          ? '<span class="unread-badge">' +
            (m.unread > 99 ? "99+" : m.unread) +
            "</span>"
          : "") +
        "</span>";
    }

    return (
      dragHtml +
      iconHtml +
      starHtml +
      eyeHtml +
      muteHtml +
      nameHtml +
      unreadHtml
    );
  }

  // ── SVG renderer: topology canvas ──────────────────────────────────
  // Emits a <g class="topo-channel" data-channel="..."> group with:
  //   diamond polygon + icon + star + eye + mute + label rect + label.
  // Canonical element order: icon + star + eye + mute + name — IDENTICAL
  // to renderChannelBadgeHtml above, so sidebar / pool / canvas all read
  // left-to-right the same way. ywatanabe 2026-04-20: "ALL channel badge
  // MUST have the SAME UI and functionalities".
  // pos = {x, y, r}; r optional (default 12).
  function renderChannelBadgeSvg(name, pos, opts) {
    opts = opts || {};
    var m = channelBadgeModel(name);
    var showEye = !!opts.showEye;
    var showUnread = !!opts.showUnread;
    var x = pos.x;
    var y = pos.y;
    var r = pos.r || 12;
    var count = opts.count != null ? opts.count : null;
    var labelText = count != null ? m.norm + " (" + count + ")" : m.norm;
    var extraClass = opts.extraClass || "";

    var pts =
      x +
      "," +
      (y - r) +
      " " +
      (x + r) +
      "," +
      y +
      " " +
      x +
      "," +
      (y + r) +
      " " +
      (x - r) +
      "," +
      y;

    var chCls = "topo-node topo-channel";
    if (m.isStarred) chCls += " topo-channel-starred";
    if (m.isMuted) chCls += " topo-channel-muted";
    if (m.isHidden) chCls += " topo-channel-hidden";
    if (extraClass) chCls += " " + extraClass;

    // Icon: URL → <image>, emoji → <text>, else no glyph.
    var iconGlyph = "";
    if (m.iconIsUrl) {
      var imgSize = Math.max(14, Math.round(r * 1.6));
      iconGlyph =
        '<image class="topo-ch-icon-img ch-icon" data-channel="' +
        _escape(m.norm) +
        '" href="' +
        _escape(m.iconGlyph) +
        '" x="' +
        (x - imgSize / 2).toFixed(1) +
        '" y="' +
        (y - imgSize / 2).toFixed(1) +
        '" width="' +
        imgSize +
        '" height="' +
        imgSize +
        '" preserveAspectRatio="xMidYMid slice"/>';
    } else if (m.iconGlyph) {
      iconGlyph =
        '<text class="topo-ch-emoji ch-icon" data-channel="' +
        _escape(m.norm) +
        '" x="' +
        x.toFixed(1) +
        '" y="' +
        (y + 4).toFixed(1) +
        '" font-size="' +
        Math.max(11, Math.round(r * 1.2)) +
        '" text-anchor="middle" dominant-baseline="middle">' +
        _escape(m.iconGlyph) +
        "</text>";
    }

    // Star — always rendered; filled gold when starred, dim outline when not.
    var starFill = m.isStarred ? "#fbbf24" : "#3a3a3a";
    var starGlyph =
      '<text class="topo-ch-star ch-star" data-channel="' +
      _escape(m.norm) +
      '" x="' +
      (x + r + 2).toFixed(1) +
      '" y="' +
      (y - r + 4).toFixed(1) +
      '" font-size="11" fill="' +
      starFill +
      '" style="cursor:pointer" title="' +
      (m.isStarred ? "Unstar" : "Star") +
      '">' +
      (m.isStarred ? "\u2605" : "\u2606") +
      "</text>";

    // Eye — optional.
    var eyeGlyph = "";
    if (showEye) {
      eyeGlyph =
        '<text class="topo-ch-eye ch-eye" data-channel="' +
        _escape(m.norm) +
        '" x="' +
        (x - r - 12).toFixed(1) +
        '" y="' +
        (y + r + 8).toFixed(1) +
        '" font-size="9" fill="#94a3b8" style="cursor:pointer">' +
        (m.isHidden ? "\uD83D\uDEAB" : "\uD83D\uDC41") +
        "</text>";
    }

    // Mute — only rendered when muted (keeps diamond uncluttered).
    var muteGlyph =
      '<text class="topo-ch-mute ch-mute" data-channel="' +
      _escape(m.norm) +
      '" x="' +
      (x - r - 12).toFixed(1) +
      '" y="' +
      (y - r + 4).toFixed(1) +
      '" font-size="9" fill="' +
      (m.isMuted ? "#94a3b8" : "#3a3a3a") +
      '" style="cursor:pointer">' +
      (m.isMuted ? "\uD83D\uDD15" : "\uD83D\uDD14") +
      "</text>";

    // Label rect + text (channel label above diamond).
    var labelW = Math.max(40, labelText.length * 6.5);
    var labelX = x - labelW / 2 - 6;
    var labelY = y - r - 18;
    var labelRect =
      '<rect class="topo-channel-bg" x="' +
      labelX.toFixed(1) +
      '" y="' +
      labelY.toFixed(1) +
      '" width="' +
      (labelW + 12).toFixed(1) +
      '" height="20" rx="10" ry="10"/>';
    var labelTextSvg =
      '<text class="topo-label topo-label-ch" x="' +
      x +
      '" y="' +
      (y - r - 4).toFixed(1) +
      '" text-anchor="middle">' +
      _escape(labelText) +
      "</text>";

    // Optional unread bubble (not used on canvas today, but available).
    var unreadSvg = "";
    if (showUnread && m.unread > 0) {
      unreadSvg =
        '<circle class="topo-ch-unread" cx="' +
        (x + r + 6).toFixed(1) +
        '" cy="' +
        (y + r).toFixed(1) +
        '" r="7" fill="#ef4444"/>' +
        '<text class="topo-ch-unread-text" x="' +
        (x + r + 6).toFixed(1) +
        '" y="' +
        (y + r + 3).toFixed(1) +
        '" font-size="9" fill="#fff" text-anchor="middle">' +
        (m.unread > 9 ? "9+" : m.unread) +
        "</text>";
    }

    var attrs = opts.extraAttrs || "";
    return (
      '<g class="' +
      chCls +
      '" data-channel="' +
      _escape(m.norm) +
      '"' +
      (count != null ? ' data-agent-count="' + count + '"' : "") +
      (attrs ? " " + attrs : "") +
      ">" +
      '<polygon points="' +
      pts +
      '" fill="#1a1a1a" stroke="#444" stroke-width="1"/>' +
      iconGlyph +
      starGlyph +
      eyeGlyph +
      muteGlyph +
      labelRect +
      labelTextSvg +
      unreadSvg +
      "</g>"
    );
  }

  // ── Delegated click handlers — body-level so every ch-* element
  // anywhere in the DOM gets the same behavior. Idempotent: only binds
  // once per page load.
  var _attached = false;
  function attachChannelBadgeHandlers() {
    if (_attached) return;
    _attached = true;
    if (typeof document === "undefined") return;

    document.body.addEventListener(
      "click",
      function (ev) {
        // Star toggle — match .ch-star OR the legacy .ch-pin alias.
        var star = ev.target.closest(
          ".ch-star[data-channel], .ch-pin[data-channel], .ch-pin[data-ch]",
        );
        if (star) {
          var chS =
            star.getAttribute("data-channel") || star.getAttribute("data-ch");
          if (chS && typeof _setChannelPref === "function") {
            ev.stopPropagation();
            ev.preventDefault();
            var cur =
              (window._channelPrefs && window._channelPrefs[_norm(chS)]) || {};
            _setChannelPref(chS, { is_starred: !cur.is_starred });
            return;
          }
        }
        // Eye (hide) toggle.
        var eye = ev.target.closest(".ch-eye[data-channel], .ch-eye[data-ch]");
        if (eye) {
          var chE =
            eye.getAttribute("data-channel") || eye.getAttribute("data-ch");
          if (chE && typeof _setChannelPref === "function") {
            ev.stopPropagation();
            ev.preventDefault();
            var curE =
              (window._channelPrefs && window._channelPrefs[_norm(chE)]) || {};
            _setChannelPref(chE, { is_hidden: !curE.is_hidden });
            return;
          }
        }
        // Mute toggle.
        var mute = ev.target.closest(
          ".ch-mute[data-channel], .ch-mute[data-ch]",
        );
        if (mute) {
          var chM =
            mute.getAttribute("data-channel") || mute.getAttribute("data-ch");
          if (chM && typeof _setChannelPref === "function") {
            ev.stopPropagation();
            ev.preventDefault();
            var curM =
              (window._channelPrefs && window._channelPrefs[_norm(chM)]) || {};
            _setChannelPref(chM, { is_muted: !curM.is_muted });
            return;
          }
        }
        // Icon change — open emoji picker and set icon_emoji.
        var icon = ev.target.closest(".ch-icon[data-channel]");
        if (icon) {
          var chI = icon.getAttribute("data-channel");
          if (
            chI &&
            typeof window.openEmojiPicker === "function" &&
            typeof _setChannelIcon === "function"
          ) {
            ev.stopPropagation();
            ev.preventDefault();
            window.openEmojiPicker(function (emoji) {
              _setChannelIcon(chI, { icon_emoji: emoji });
            });
            return;
          }
        }
      },
      true, // capture — beat site-local click handlers that stopPropagation
    );
  }

  // Auto-attach on DOMContentLoaded so every subsequent render picks up
  // delegation without callers needing to remember.
  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", attachChannelBadgeHandlers);
    } else {
      attachChannelBadgeHandlers();
    }
  }

  // Expose globals — script is loaded as a plain <script> tag.
  window.channelBadgeModel = channelBadgeModel;
  window.renderChannelBadgeHtml = renderChannelBadgeHtml;
  window.renderChannelBadgeSvg = renderChannelBadgeSvg;
  window.attachChannelBadgeHandlers = attachChannelBadgeHandlers;
})();
