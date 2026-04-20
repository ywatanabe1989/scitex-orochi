// @ts-nocheck
// Migrated classic-script file. Types intentionally loose during
// the big-bang JS-to-TS bundle migration. Narrow later, per-file.
/* Tag-based unified filter with fuzzy matching — state, parser, tags,
 * suggestions, and input event wiring. Paired with filter/runner.js. */
/* globals: fuzzyMatch, escapeHtml, cachedAgentNames, resourceData,
   currentChannel, activeTags */

/* mention.js redefines fuzzyMatch() to return a numeric score where
 * -1 means no match. In JS -1 is truthy, so all boolean filter checks
 * would pass regardless of match. _fm() wraps with >= 0 check. */
var _fm = function (query, text) {
  return fuzzyMatch(query, text) >= 0;
};

var filterInput = document.getElementById("filter-input");
var filterTagsEl = document.getElementById("filter-tags");
var filterSuggestEl = document.getElementById("filter-suggest");
var activeTags = [];
var suggestIndex = -1;

function parseFilterInput(raw) {
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
var IS_FLAGS = ["starred", "pinned", "muted", "unread", "hidden", "dm"];

function _channelMatchesIsFlag(el, flag) {
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

function addTag(type, value) {
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

function removeTag(index) {
  activeTags.splice(index, 1);
  renderTags();
  runFilter();
  syncFilterVisuals();
}

function syncFilterVisuals() {
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

function renderTags() {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  filterTagsEl.innerHTML = activeTags
    .map(function (t, i) {
      return (
        '<span class="filter-tag" data-type="' +
        t.type +
        '" onclick="removeTag(' +
        i +
        ')">' +
        t.type +
        ":" +
        escapeHtml(t.value) +
        ' <span class="tag-remove">\u00D7</span></span>'
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

function getTagSuggestions(prefix) {
  var results = [];
  var pLower = prefix.toLowerCase();
  cachedAgentNames.forEach(function (n) {
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

function showSuggestions(items) {
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

function hideSuggestions() {
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
