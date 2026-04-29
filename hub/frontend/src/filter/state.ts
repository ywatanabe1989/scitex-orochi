// @ts-nocheck
import { _channelPrefs } from "../app/members";
import { channelUnread, escapeHtml, fuzzyMatch } from "../app/utils";
import { runFilter } from "./runner";
import { resourceData } from "../resources-tab/panel";

/* Tag-based unified filter with fuzzy matching — state, parser, tags,
 * suggestions, and input event wiring. Paired with filter/runner.js. */
/* globals: fuzzyMatch, escapeHtml, (globalThis as any).cachedAgentNames, resourceData,
   currentChannel, activeTags */

/* mention.js redefines fuzzyMatch() to return a numeric score where
 * -1 means no match. In JS -1 is truthy, so all boolean filter checks
 * would pass regardless of match. _fm() wraps with >= 0 check. */
export var _fm = function (query, text) {
  return fuzzyMatch(query, text) >= 0;
};

/* The filter UI (#filter-input + #filter-tags + #filter-suggest) was
 * removed from dashboard.html when the global Ctrl+K fuzzy filter was
 * dropped. The support functions (addTag/removeTag/runFilter/etc.) are
 * still imported from many call-sites (right-click "filter by host",
 * etc.) and the data side (activeTags) still drives row dimming via
 * syncFilterVisuals(). So: keep the data, no-op the UI. Each function
 * that touched a filter-UI element now early-returns if the element is
 * absent. NOT a patch — recognising that the filter UI is conditional
 * is the rigorous design once the visible chips were removed. */
export var filterInput = document.getElementById("filter-input");
export var filterTagsEl = document.getElementById("filter-tags");
export var filterSuggestEl = document.getElementById("filter-suggest");
export var activeTags = [];
export var suggestIndex = -1;

export function parseFilterInput(raw) {
  var parts = raw.split(/\s+/);
  var tags = [];
  var textParts = [];
  parts.forEach(function (p) {
    var m = p.match(/^(agent|host|channel|label|project|is):(.+)$/i);
    if (m) {
      tags.push({ type: m[1].toLowerCase(), value: m[2].toLowerCase() });
    } else if (p) {
      textParts.push(p);
    }
  });
  return { tags: tags, text: textParts.join(" ") };
}

/* Known "is:<flag>" state filters for channels/DMs. Evaluated against
 * _channelPrefs + channelUnread (todo#72). */
export var IS_FLAGS = ["starred", "pinned", "muted", "unread", "hidden", "dm"];

export function _channelMatchesIsFlag(el, flag) {
  /* Resolve the channel key for this sidebar row. */
  var ch =
    el.getAttribute("data-channel") ||
    (el.textContent ? el.textContent.trim() : "");
  if (!ch) return false;
  var norm = ch.charAt(0) === "#" || ch.indexOf("dm:") === 0 ? ch : "#" + ch;
  var prefs =
    (typeof _channelPrefs !== "undefined" &&
      (_channelPrefs[norm] || _channelPrefs[ch])) ||
    {};
  if (flag === "starred" || flag === "pinned") return !!prefs.is_starred;
  if (flag === "muted") return !!prefs.is_muted;
  if (flag === "hidden") return !!prefs.is_hidden;
  if (flag === "unread") {
    if (typeof channelUnread === "undefined") return false;
    var n = channelUnread[ch] || channelUnread[norm] || 0;
    return n > 0;
  }
  if (flag === "dm") return ch.indexOf("dm:") === 0;
  return false;
}

export function addTag(type, value) {
  var idx = -1;
  activeTags.forEach(function (t, i) {
    if (t.type === type && t.value === value) idx = i;
  });
  if (idx >= 0) {
    activeTags.splice(idx, 1);
  } else {
    activeTags.push({ type: type, value: value });
  }
  renderTags();
  runFilter();
  syncFilterVisuals();
}

export function removeTag(index) {
  activeTags.splice(index, 1);
  renderTags();
  runFilter();
  syncFilterVisuals();
}

export function syncFilterVisuals() {
  var agentValues = {};
  var channelValues = {};
  var hostValues = {};
  activeTags.forEach(function (t) {
    if (t.type === "agent") agentValues[t.value.toLowerCase()] = true;
    if (t.type === "channel") channelValues[t.value.toLowerCase()] = true;
    if (t.type === "host") hostValues[t.value.toLowerCase()] = true;
  });
  document.querySelectorAll(".agent-card").forEach(function (el) {
    var name = (
      el.getAttribute("data-agent") || el.textContent.trim().split("\n")[0]
    ).toLowerCase();
    el.classList.toggle("filter-active", !!agentValues[name]);
  });
  document.querySelectorAll(".channel-item").forEach(function (el) {
    var ch = (
      el.getAttribute("data-channel") || el.textContent.trim()
    ).toLowerCase();
    el.classList.toggle("filter-active", !!channelValues[ch]);
  });
  document.querySelectorAll(".res-card").forEach(function (el) {
    var host = (
      el.getAttribute("data-host") || el.textContent.trim().split("\n")[0]
    ).toLowerCase();
    el.classList.toggle("filter-active", !!hostValues[host]);
  });
}

/* Format a filter-tag chip label. DM channels have long raw keys like
 * "dm:agent:X|human:Y" \u2014 show "DM: X" instead. */
export function _prettyTagLabel(type: string, value: string): string {
  if (type === "channel" && value.indexOf("dm:") === 0) {
    var after = value.slice(3); // "agent:X|human:Y"
    var firstPart = after.split("|")[0] || "";
    var colonIdx = firstPart.indexOf(":");
    var name = colonIdx >= 0 ? firstPart.slice(colonIdx + 1) : firstPart;
    return "DM: " + name;
  }
  return type + ":" + value;
}

function _prettyChannelName(chatId: string): string {
  return _prettyTagLabel("channel", chatId);
}

export function renderTags() {
  if (!filterTagsEl) return;
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  filterTagsEl.innerHTML = activeTags
    .map(function (t, i) {
      return (
        '<span class="filter-tag" data-type="' +
        t.type +
        '" data-chat-id="' +
        escapeHtml(t.value) +
        '" onclick="removeTag(' +
        i +
        ')">' +
        escapeHtml(_prettyTagLabel(t.type, t.value)) +
        ' <span class="tag-remove">×</span></span>'
      );
    })
    .join("");
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try {
      msgInput.setSelectionRange(savedStart, savedEnd);
    } catch (_) {}
  }
}

export function getTagSuggestions(prefix) {
  var results = [];
  var pLower = prefix.toLowerCase();
  (globalThis as any).cachedAgentNames.forEach(function (n) {
    if (_fm(pLower, n.toLowerCase())) {
      results.push({ type: "agent", value: n });
    }
  });
  Object.keys(resourceData).forEach(function (h) {
    if (_fm(pLower, h.toLowerCase())) {
      results.push({ type: "host", value: h });
    }
  });
  document.querySelectorAll("#channels .channel-item").forEach(function (el) {
    var ch = el.getAttribute("data-channel") || el.textContent.trim();
    if (_fm(pLower, ch.toLowerCase())) {
      results.push({ type: "channel", value: ch });
    }
  });
  document
    .querySelectorAll(".todo-label[data-label-name]")
    .forEach(function (el) {
      var name = el.getAttribute("data-label-name");
      if (name && _fm(pLower, name.toLowerCase())) {
        results.push({ type: "label", value: name });
      }
    });
  var seen = {};
  return results
    .filter(function (r) {
      var key = r.type + ":" + r.value;
      if (seen[key]) return false;
      seen[key] = true;
      return true;
    })
    .slice(0, 8);
}

export function showSuggestions(items) {
  if (!filterSuggestEl) return;
  if (items.length === 0) {
    hideSuggestions();
    return;
  }
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  suggestIndex = 0;
  filterSuggestEl.innerHTML = items
    .map(function (item, i) {
      return (
        '<div class="filter-suggest-item' +
        (i === 0 ? " selected" : "") +
        '" data-type="' +
        item.type +
        '" data-value="' +
        escapeHtml(item.value) +
        '">' +
        '<span class="suggest-type">' +
        item.type +
        ":</span>" +
        escapeHtml(item.value) +
        "</div>"
      );
    })
    .join("");
  filterSuggestEl.classList.add("visible");
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try {
      msgInput.setSelectionRange(savedStart, savedEnd);
    } catch (_) {}
  }
}

export function hideSuggestions() {
  if (!filterSuggestEl) return;
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  filterSuggestEl.classList.remove("visible");
  filterSuggestEl.innerHTML = "";
  suggestIndex = -1;
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try {
      msgInput.setSelectionRange(savedStart, savedEnd);
    } catch (_) {}
  }
}

/* Wire the fuzzy-suggest UI only when its elements are in the DOM.
 * The visible filter-input / filter-tags / filter-suggest trio was
 * removed from dashboard.html when the Ctrl+K fuzzy search was
 * dropped. The handlers below are kept so we can re-enable the UI by
 * just re-adding the three elements — no JS re-wiring required. */
if (filterSuggestEl && filterInput) {
  filterSuggestEl.addEventListener("click", function (e) {
    var item = e.target.closest(".filter-suggest-item");
    if (item) {
      addTag(item.getAttribute("data-type"), item.getAttribute("data-value"));
      filterInput.value = "";
      hideSuggestions();
    }
  });

  filterInput.addEventListener("input", function () {
    var raw = this.value.trim();
    if (raw.length >= 1) {
      showSuggestions(getTagSuggestions(raw));
    } else {
      hideSuggestions();
    }
    runFilter();
  });

  filterInput.addEventListener("keydown", function (e) {
    var items = filterSuggestEl.querySelectorAll(".filter-suggest-item");
    if (items.length > 0 && filterSuggestEl.classList.contains("visible")) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        suggestIndex = Math.min(suggestIndex + 1, items.length - 1);
        items.forEach(function (el, i) {
          el.classList.toggle("selected", i === suggestIndex);
        });
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        suggestIndex = Math.max(suggestIndex - 1, 0);
        items.forEach(function (el, i) {
          el.classList.toggle("selected", i === suggestIndex);
        });
      } else if ((e.key === "Tab" || e.key === "Enter") && suggestIndex >= 0) {
        e.preventDefault();
        var sel = items[suggestIndex];
        addTag(sel.getAttribute("data-type"), sel.getAttribute("data-value"));
        filterInput.value = "";
        hideSuggestions();
      } else if (e.key === "Escape") {
        hideSuggestions();
      }
    } else if (e.key === "Backspace" && !this.value && activeTags.length > 0) {
      removeTag(activeTags.length - 1);
    }
  });

  filterInput.addEventListener("blur", function () {
    setTimeout(hideSuggestions, 150);
  });
}
