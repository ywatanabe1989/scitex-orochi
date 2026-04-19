/* Tag-based unified filter with fuzzy matching */
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

function matchesAllTags(tags, text) {
  if (tags.length === 0) return true;
  var lower = text.toLowerCase();
  return tags.every(function (tag) {
    /* "is:" state tags are evaluated per-row in channel/dm filters,
     * not via free-text match. Accept here so non-channel rows still
     * pass through when the only active tag is is:<flag>. */
    if (tag.type === "is") return true;
    return _fm(tag.value.toLowerCase(), lower);
  });
}

function _isTagsFrom(allTags) {
  var out = [];
  allTags.forEach(function (t) {
    if (t.type === "is") out.push(t.value.toLowerCase());
  });
  return out;
}

function runFilter() {
  var parsed = parseFilterInput(filterInput.value.trim());
  var allTags = activeTags.concat(parsed.tags);
  var q = parsed.text;
  /* Split free text into space-separated keywords for AND matching (#347) */
  var qWords = q ? q.split(/\s+/).filter(Boolean) : [];
  document.querySelectorAll(".msg").forEach(function (el) {
    var sender = el.querySelector(".sender");
    var channel = el.querySelector(".channel");
    var content = el.querySelector(".content");
    var text =
      (sender ? sender.textContent : "") +
      " " +
      (channel ? channel.textContent : "") +
      " " +
      (content ? content.textContent : "");
    /* Each keyword must match independently (AND logic) */
    var show =
      qWords.length === 0 ||
      qWords.every(function (w) {
        return _fm(w, text);
      });
    if (show && allTags.length > 0) {
      /* Group agent tags for OR (union) logic; other tags stay AND */
      var agentTags = allTags.filter(function (t) {
        return t.type === "agent";
      });
      var otherTags = allTags.filter(function (t) {
        return t.type !== "agent";
      });
      if (agentTags.length > 0) {
        var senderText = (sender ? sender.textContent : "").toLowerCase();
        show = agentTags.some(function (tag) {
          return _fm(tag.value.toLowerCase(), senderText);
        });
      }
      if (show && otherTags.length > 0) {
        show = otherTags.every(function (tag) {
          var val = tag.value.toLowerCase();
          if (tag.type === "channel") {
            return _fm(
              val,
              (el.getAttribute("data-channel") || "").toLowerCase(),
            );
          }
          return _fm(val, text.toLowerCase());
        });
      }
    }
    /* Skip single-channel filter when multi-select is active (#366):
     * applyFeedFilter() handles multi-channel visibility in that case. */
    var _multiActive =
      document.querySelectorAll("#channels .channel-item.selected").length >= 2;
    if (show && currentChannel && !_multiActive) {
      show = el.getAttribute("data-channel") === currentChannel;
    }
    el.style.display = show ? "" : "none";
  });
  document.querySelectorAll(".todo-item").forEach(function (el) {
    var text = el.textContent;
    var show =
      qWords.length === 0 ||
      qWords.every(function (w) {
        return _fm(w, text);
      });
    if (show && allTags.length > 0) {
      show = allTags.every(function (tag) {
        var val = tag.value.toLowerCase();
        if (tag.type === "label") {
          var labels = el.querySelectorAll(".todo-label");
          if (labels.length === 0) return false;
          var found = false;
          labels.forEach(function (l) {
            if (_fm(val, l.textContent.toLowerCase())) found = true;
          });
          return found;
        }
        return _fm(val, text.toLowerCase());
      });
    }
    el.style.display = show ? "" : "none";
  });
  filterSidebarElements(qWords, allTags);
}

function _matchAllWords(words, text) {
  return (
    words.length === 0 ||
    words.every(function (w) {
      return _fm(w, text);
    })
  );
}

function filterSidebarElements(qWords, allTags) {
  document.querySelectorAll("#agents .agent-card").forEach(function (el) {
    var text = el.textContent;
    el.style.display =
      _matchAllWords(qWords, text) && matchesAllTags(allTags, text)
        ? ""
        : "none";
  });
  var isFlags = _isTagsFrom(allTags);
  document.querySelectorAll("#channels .channel-item").forEach(function (el) {
    var text = el.textContent;
    var show = _matchAllWords(qWords, text) && matchesAllTags(allTags, text);
    if (show && isFlags.length > 0) {
      show = isFlags.every(function (f) {
        return _channelMatchesIsFlag(el, f);
      });
    }
    el.style.display = show ? "" : "none";
  });
  document.querySelectorAll("#dms .dm-item").forEach(function (el) {
    var text = el.textContent;
    var show = _matchAllWords(qWords, text) && matchesAllTags(allTags, text);
    if (show && isFlags.length > 0) {
      show = isFlags.every(function (f) {
        /* DMs honor starred/pinned/muted/unread/dm; treat "hidden" as no-op. */
        if (f === "hidden") return false;
        return _channelMatchesIsFlag(el, f);
      });
    }
    el.style.display = show ? "" : "none";
  });
  document.querySelectorAll("#resources .res-card").forEach(function (el) {
    var text = el.textContent;
    el.style.display =
      _matchAllWords(qWords, text) && matchesAllTags(allTags, text)
        ? ""
        : "none";
  });
  document.querySelectorAll("#agents-grid .agent-card").forEach(function (el) {
    var text = el.textContent;
    el.style.display =
      _matchAllWords(qWords, text) && matchesAllTags(allTags, text)
        ? ""
        : "none";
  });
  document.querySelectorAll("#resources-grid .res-card").forEach(function (el) {
    var text = el.textContent;
    el.style.display =
      _matchAllWords(qWords, text) && matchesAllTags(allTags, text)
        ? ""
        : "none";
  });
  /* Agents tab: per-agent table rows in the overview sub-tab. The paired
   * .agent-pane-row / .claude-md-detail siblings must follow the parent
   * agent-row's visibility so we don't leave orphaned pane previews
   * behind after a filter. */
  document
    .querySelectorAll("#agent-tab-content tr.agent-row")
    .forEach(function (el) {
      var text = el.textContent;
      var show = _matchAllWords(qWords, text) && matchesAllTags(allTags, text);
      el.style.display = show ? "" : "none";
      var sib = el.nextElementSibling;
      while (
        sib &&
        (sib.classList.contains("agent-pane-row") ||
          sib.classList.contains("claude-md-detail"))
      ) {
        if (!show) {
          sib.style.display = "none";
        } else if (sib.classList.contains("agent-pane-row")) {
          sib.style.display = "";
        }
        /* claude-md-detail keeps whatever the toggle button set (display:none
         * when collapsed, table-row when expanded) — don't clobber it. */
        sib = sib.nextElementSibling;
      }
    });
  /* Files tab rows. */
  document
    .querySelectorAll("#files-view tr.files-list-row")
    .forEach(function (el) {
      var text = el.textContent;
      el.style.display =
        _matchAllWords(qWords, text) && matchesAllTags(allTags, text)
          ? ""
          : "none";
    });
  /* Agents tab activity-card grid (what "Agents" actually renders —
   * the data-tab="activity" view). Previously Ctrl+K only filtered
   * table rows in the legacy agents-tab overview, not these cards. */
  document
    .querySelectorAll("#activity-grid .activity-card")
    .forEach(function (el) {
      var text = el.textContent;
      el.style.display =
        _matchAllWords(qWords, text) && matchesAllTags(allTags, text)
          ? ""
          : "none";
    });
  _syncFilterChips();
}

/* ---------------- Sidebar filter chips (todo#72) ----------------
 * Small toggle buttons immediately under #filter-input that write
 * "is:<flag>" tokens into the search field (and remove them on second
 * click). Two-way binding: typing is:<flag> by hand lights up the chip.
 * The chips remain user-visible proof of what is being filtered. */

function _currentInputTokens() {
  /* Return {is: Set<flag>} present in the raw search input (not the
   * chip-tag list, which is rendered separately). */
  var raw = (filterInput && filterInput.value) || "";
  var parsed = parseFilterInput(raw.trim());
  var set = {};
  parsed.tags.forEach(function (t) {
    if (t.type === "is") set[t.value.toLowerCase()] = true;
  });
  return set;
}

function _syncFilterChips() {
  var bar = document.getElementById("sidebar-filter-chips");
  if (!bar) return;
  var inInput = _currentInputTokens();
  var inTags = {};
  activeTags.forEach(function (t) {
    if (t.type === "is") inTags[t.value.toLowerCase()] = true;
  });
  bar.querySelectorAll(".sidebar-filter-chip").forEach(function (chip) {
    var f = chip.getAttribute("data-is");
    var on = !!(inInput[f] || inTags[f]);
    chip.classList.toggle("active", on);
    chip.setAttribute("aria-pressed", on ? "true" : "false");
  });
}

function _toggleIsToken(flag) {
  /* Flip is:<flag> membership directly in the raw #filter-input value
   * (not in activeTags) so users see the token literally — matches the
   * "filters auto-fill the search field" requirement of todo#72. */
  if (!filterInput) return;
  var raw = filterInput.value || "";
  var token = "is:" + flag;
  /* Word-boundary replace to avoid nuking is:<other>. */
  var re = new RegExp("(?:^|\\s)" + token + "(?=\\s|$)", "i");
  if (re.test(raw)) {
    raw = raw.replace(re, " ").replace(/\s+/g, " ").trim();
  } else {
    raw = (raw ? raw + " " : "") + token;
  }
  filterInput.value = raw;
  /* Fire input event so existing listener reruns filter + suggestions. */
  filterInput.dispatchEvent(new Event("input", { bubbles: true }));
}

function _initFilterChips() {
  var bar = document.getElementById("sidebar-filter-chips");
  if (!bar) return;
  bar.addEventListener("click", function (e) {
    var chip = e.target.closest(".sidebar-filter-chip");
    if (!chip) return;
    var f = chip.getAttribute("data-is");
    if (!f) return;
    _toggleIsToken(f);
  });
  _syncFilterChips();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", _initFilterChips);
} else {
  _initFilterChips();
}
