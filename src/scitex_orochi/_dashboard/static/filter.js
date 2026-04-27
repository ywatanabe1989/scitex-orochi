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
  var exists = activeTags.some(function (t) {
    return t.type === type && t.value === value;
  });
  if (exists) return;
  activeTags.push({ type: type, value: value });
  renderTags();
  runFilter();
}

function removeTag(index) {
  activeTags.splice(index, 1);
  renderTags();
  runFilter();
}

function renderTags() {
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
}

function hideSuggestions() {
  filterSuggestEl.classList.remove("visible");
  filterSuggestEl.innerHTML = "";
  suggestIndex = -1;
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
    var show = fuzzyMatch(q, text);
    if (show && allTags.length > 0) {
      show = allTags.every(function (tag) {
        var val = tag.value.toLowerCase();
        if (tag.type === "agent") {
          return fuzzyMatch(
            val,
            (sender ? sender.textContent : "").toLowerCase(),
          );
        }
        if (tag.type === "channel") {
          return fuzzyMatch(
            val,
            (el.getAttribute("data-channel") || "").toLowerCase(),
          );
        }
        return fuzzyMatch(val, text.toLowerCase());
      });
    }
    if (show && currentChannel) {
      show = el.getAttribute("data-channel") === currentChannel;
    }
    el.style.display = show ? "" : "none";
  });
  document.querySelectorAll(".todo-item").forEach(function (el) {
    var text = el.textContent;
    var show = fuzzyMatch(q, text);
    if (show && allTags.length > 0) {
      show = allTags.every(function (tag) {
        var val = tag.value.toLowerCase();
        if (tag.type === "label") {
          var labels = el.querySelectorAll(".todo-label");
          if (labels.length === 0) return false;
          var found = false;
          labels.forEach(function (l) {
            if (fuzzyMatch(val, l.textContent.toLowerCase())) found = true;
          });
          return found;
        }
        return fuzzyMatch(val, text.toLowerCase());
      });
    }
    el.style.display = show ? "" : "none";
  });
  document.querySelectorAll("#agents .agent-card").forEach(function (el) {
    var text = el.textContent;
    el.style.display =
      fuzzyMatch(q, text) && matchesAllTags(allTags, text) ? "" : "none";
  });
  document.querySelectorAll("#channels .channel-item").forEach(function (el) {
    var text = el.textContent;
    el.style.display =
      fuzzyMatch(q, text) && matchesAllTags(allTags, text) ? "" : "none";
  });
  document.querySelectorAll("#resources .res-card").forEach(function (el) {
    var text = el.textContent;
    el.style.display =
      fuzzyMatch(q, text) && matchesAllTags(allTags, text) ? "" : "none";
  });
  document.querySelectorAll("#agents-grid .agent-card").forEach(function (el) {
    var text = el.textContent;
    el.style.display =
      fuzzyMatch(q, text) && matchesAllTags(allTags, text) ? "" : "none";
  });
  document.querySelectorAll("#resources-grid .res-card").forEach(function (el) {
    var text = el.textContent;
    el.style.display =
      fuzzyMatch(q, text) && matchesAllTags(allTags, text) ? "" : "none";
  });
}
