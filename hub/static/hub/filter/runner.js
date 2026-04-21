/* Tag-based unified filter — matching, runFilter, sidebar/grid filters,
 * and is:<flag> chip toggles. Paired with filter/state.js. */
/* globals: _fm, filterInput, activeTags, currentChannel, parseFilterInput,
   _channelMatchesIsFlag */

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
    /* #284: channels are single-select — at most one .channel-item.selected
     * ever exists. The legacy multi-channel bypass was removed; currentChannel
     * alone is the filter gate. */
    if (show && currentChannel) {
      /* channelsEqual (msg#16691) so legacy ``#`` vs bare channel names
       * don't wrongly hide rows in the active channel. */
      show = channelsEqual(el.getAttribute("data-channel"), currentChannel);
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
