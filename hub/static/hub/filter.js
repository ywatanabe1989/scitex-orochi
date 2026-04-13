/* Tag-based unified filter with fuzzy matching */
/* globals: fuzzyMatch, escapeHtml, cachedAgentNames, resourceData,
   currentChannel, activeTags */

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
    var m = p.match(/^(agent|host|channel|label|project):(.+)$/i);
    if (m) {
      tags.push({ type: m[1].toLowerCase(), value: m[2] });
    } else if (p) {
      textParts.push(p);
    }
  });
  return { tags: tags, text: textParts.join(" ") };
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
    try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
  }
}

function getTagSuggestions(prefix) {
  var results = [];
  var pLower = prefix.toLowerCase();
  cachedAgentNames.forEach(function (n) {
    if (fuzzyMatch(pLower, n.toLowerCase())) {
      results.push({ type: "agent", value: n });
    }
  });
  Object.keys(resourceData).forEach(function (h) {
    if (fuzzyMatch(pLower, h.toLowerCase())) {
      results.push({ type: "host", value: h });
    }
  });
  document.querySelectorAll("#channels .channel-item").forEach(function (el) {
    var ch = el.getAttribute("data-channel") || el.textContent.trim();
    if (fuzzyMatch(pLower, ch.toLowerCase())) {
      results.push({ type: "channel", value: ch });
    }
  });
  document
    .querySelectorAll(".todo-label[data-label-name]")
    .forEach(function (el) {
      var name = el.getAttribute("data-label-name");
      if (name && fuzzyMatch(pLower, name.toLowerCase())) {
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
    try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
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
    try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
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
    return fuzzyMatch(tag.value.toLowerCase(), lower);
  });
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
    var show = qWords.length === 0 || qWords.every(function (w) {
      return _fm(w, text);
    });
    if (show && allTags.length > 0) {
      /* Group agent tags for OR (union) logic; other tags stay AND */
      var agentTags = allTags.filter(function (t) { return t.type === "agent"; });
      var otherTags = allTags.filter(function (t) { return t.type !== "agent"; });
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
    if (show && currentChannel) {
      show = el.getAttribute("data-channel") === currentChannel;
    }
    el.style.display = show ? "" : "none";
  });
  document.querySelectorAll(".todo-item").forEach(function (el) {
    var text = el.textContent;
    var show = qWords.length === 0 || qWords.every(function (w) { return _fm(w, text); });
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
  return words.length === 0 || words.every(function (w) { return _fm(w, text); });
}

function filterSidebarElements(qWords, allTags) {
  document.querySelectorAll("#agents .agent-card").forEach(function (el) {
    var text = el.textContent;
    el.style.display =
      _matchAllWords(qWords, text) && matchesAllTags(allTags, text) ? "" : "none";
  });
  document.querySelectorAll("#channels .channel-item").forEach(function (el) {
    var text = el.textContent;
    el.style.display =
      _matchAllWords(qWords, text) && matchesAllTags(allTags, text) ? "" : "none";
  });
  document.querySelectorAll("#resources .res-card").forEach(function (el) {
    var text = el.textContent;
    el.style.display =
      _matchAllWords(qWords, text) && matchesAllTags(allTags, text) ? "" : "none";
  });
  document.querySelectorAll("#agents-grid .agent-card").forEach(function (el) {
    var text = el.textContent;
    el.style.display =
      _matchAllWords(qWords, text) && matchesAllTags(allTags, text) ? "" : "none";
  });
  document.querySelectorAll("#resources-grid .res-card").forEach(function (el) {
    var text = el.textContent;
    el.style.display =
      _matchAllWords(qWords, text) && matchesAllTags(allTags, text) ? "" : "none";
  });
}
