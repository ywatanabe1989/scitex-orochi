// @ts-nocheck
import { apiUrl, escapeHtml, isAgentInactive } from "./app/utils";
import { _channelPrefs } from "./app/members";

/* Mention autocomplete module */
/* globals: escapeHtml, getAgentColor, (globalThis as any).cachedAgentNames, apiUrl, isAgentInactive */

export var mentionDropdown = document.getElementById("mention-dropdown");
export var mentionSelectedIndex = -1;
export var cachedAgentObjects = [];
export var cachedMemberNames = [];
export var mentionActiveInput = null;

export var SPECIAL_MENTIONS = [
  { name: "all", desc: "notify everyone" },
  { name: "channel", desc: "notify this channel" },
  { name: "agents", desc: "notify all agents" },
  { name: "heads", desc: "notify all head-* agents" },
  { name: "healers", desc: "notify all mamba-healer-* agents" },
  { name: "mambas", desc: "notify all mamba-* agents" },
];

/* Channel names for @channel autocomplete. Populated by channel-prefs.ts
 * when channels are fetched. Strip leading # so "@general" completes. */
export var cachedChannelNames: string[] = [];

/* Fuzzy match: check if all query characters appear in order within text.
   Returns a score (lower = better) or -1 if no match. */
export function _mention__fuzzyMatch(query, text) {
  var q = query.toLowerCase();
  var t = text.toLowerCase();
  /* Exact prefix match gets best score */
  if (t.indexOf(q) === 0) return 0;
  /* Substring match gets second-best score */
  if (t.indexOf(q) !== -1) return 1;
  /* Fuzzy: all query chars must appear in order */
  var qi = 0;
  var gaps = 0;
  for (var ti = 0; ti < t.length && qi < q.length; ti++) {
    if (t[ti] === q[qi]) {
      qi++;
    } else if (qi > 0) {
      gaps++;
    }
  }
  if (qi === q.length) return 2 + gaps;
  return -1;
}

export function cleanDisplayName(name) {
  return name.replace(/^orochi-/, "");
}

export async function refreshAgentNames() {
  try {
    var res = await fetch(apiUrl("/api/agents"));
    var agents = await res.json();
    (globalThis as any).cachedAgentNames = agents.map(function (a) {
      return a.name;
    });
    cachedAgentObjects = agents;
  } catch (e) {
    /* ignore */
  }
  try {
    var res2 = await fetch(apiUrl("/api/members/"), { credentials: "same-origin" });
    var members = await res2.json();
    cachedMemberNames = members.map(function (m) {
      return m.username;
    });
  } catch (e) {
    /* ignore */
  }
}

export function getMentionQuery(input) {
  var val = input.value;
  var pos = input.selectionStart;
  var before = val.substring(0, pos);
  /* Allow @ after any non-word char (space, CJK chars, punctuation, etc.)
   * so Japanese text like「こんにちは@mamba」triggers the dropdown. (#9958) */
  var match = before.match(/(^|[^\w])@([\w@.\-]*)$/);
  if (match)
    return {
      query: match[2].toLowerCase(),
      start: match.index + match[1].length,
    };
  return null;
}

export function isAgentOnline(name) {
  for (var i = 0; i < cachedAgentObjects.length; i++) {
    if (cachedAgentObjects[i].name === name) {
      return !isAgentInactive(cachedAgentObjects[i]);
    }
  }
  return false;
}

export function positionMentionDropdown(inputEl) {
  /* Move the dropdown near the active input if it is not the main msg-input */
  if (inputEl && inputEl.id !== "msg-input") {
    var rect = inputEl.getBoundingClientRect();
    mentionDropdown.style.position = "fixed";
    mentionDropdown.style.bottom = (window.innerHeight - rect.top + 4) + "px";
    mentionDropdown.style.left = rect.left + "px";
    mentionDropdown.style.width = rect.width + "px";
  } else {
    /* Reset to default positioning inside .input-bar */
    mentionDropdown.style.position = "";
    mentionDropdown.style.bottom = "";
    mentionDropdown.style.left = "";
    mentionDropdown.style.width = "";
  }
}

export function showMentionDropdown(specialItems, agentItems, channelItems?) {
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  mentionSelectedIndex = 0;
  var html = "";
  var chItems = channelItems || [];

  specialItems.forEach(function (item, i) {
    html +=
      '<div class="mention-item mention-special' +
      (i === 0 ? " selected" : "") +
      '" data-name="' +
      escapeHtml(item.name) +
      '">' +
      '<span class="mention-dot mention-dot-special"></span>' +
      "<strong>@" +
      escapeHtml(item.name) +
      "</strong>" +
      '<span class="mention-desc">' +
      escapeHtml(item.desc) +
      "</span>" +
      "</div>";
  });

  if (specialItems.length > 0 && (agentItems.length > 0 || channelItems.length > 0)) {
    html += '<div class="mention-divider"></div>';
  }

  var offset = specialItems.length;
  agentItems.forEach(function (name, i) {
    var online = isAgentOnline(name);
    var dotClass = online ? "mention-dot-online" : "mention-dot-offline";
    var display = cleanDisplayName(name);
    var showFull = display !== name;
    html +=
      '<div class="mention-item' +
      (offset + i === 0 ? " selected" : "") +
      '" data-name="' +
      escapeHtml(name) +
      '">' +
      '<span class="mention-dot ' +
      dotClass +
      '"></span>' +
      escapeHtml(display) +
      (showFull ? '<span class="mention-desc">' + escapeHtml(name) + '</span>' : '') +
      "</div>";
  });

  /* Channel section (#168) */
  if (chItems.length > 0 && (specialItems.length > 0 || agentItems.length > 0)) {
    html += '<div class="mention-divider"></div>';
  }
  var chOffset = offset + agentItems.length;
  chItems.forEach(function (item, i) {
    html +=
      '<div class="mention-item mention-channel' +
      (chOffset + i === 0 ? " selected" : "") +
      '" data-name="' +
      escapeHtml(item.bare) +
      '">' +
      '<span class="mention-dot mention-dot-channel">#</span>' +
      escapeHtml(item.bare) +
      '<span class="mention-desc">channel mention</span>' +
      "</div>";
  });

  mentionDropdown.innerHTML = html;
  mentionDropdown.classList.add("visible");
  positionMentionDropdown(mentionActiveInput);
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
  }
}

export function hideMentionDropdown() {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  mentionDropdown.classList.remove("visible");
  mentionDropdown.innerHTML = "";
  mentionSelectedIndex = -1;
  mentionActiveInput = null;
  /* Reset positioning */
  mentionDropdown.style.position = "";
  mentionDropdown.style.bottom = "";
  mentionDropdown.style.left = "";
  mentionDropdown.style.width = "";
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try { msgInput.setSelectionRange(savedStart, savedEnd); } catch (_) {}
  }
}

export function insertMention(name) {
  var input = mentionActiveInput || document.getElementById("msg-input");
  var info = getMentionQuery(input);
  if (!info) return;
  var before = input.value.substring(0, info.start);
  var after = input.value.substring(input.selectionStart);
  input.value = before + "@" + name + " " + after;
  var newPos = info.start + name.length + 2;
  input.setSelectionRange(newPos, newPos);
  input.focus();
  hideMentionDropdown();
}

export function handleMentionInput(e) {
  /* Skip while an IME composition is in progress — `input.value` reflects
   * the pre-commit buffer and `selectionStart` may point at a position that
   * doesn't yet contain the composed `@`. We re-run on `compositionend`
   * (attached in initMentionAutocomplete) so the query is computed against
   * the finalized text. Fixes todo#383 — JP-mode IME users could not trigger
   * `@mention` autocomplete because the input listener consumed stale state
   * during composition. */
  if (e && e.isComposing) return;
  mentionActiveInput = this;
  var info = getMentionQuery(this);
  if (!info) {
    hideMentionDropdown();
    return;
  }

  var matchedSpecial = SPECIAL_MENTIONS.filter(function (s) {
    return s.name.indexOf(info.query) === 0;
  });
  /* Combine agents and members, deduplicate */
  var allNames = (globalThis as any).cachedAgentNames.slice();
  cachedMemberNames.forEach(function (m) {
    if (allNames.indexOf(m) === -1) allNames.push(m);
  });
  var matchedAgents = allNames
    .map(function (n) {
      var score = _mention__fuzzyMatch(info.query, n);
      /* Also match against cleaned display name */
      var cleanScore = _mention__fuzzyMatch(info.query, cleanDisplayName(n));
      var best = score === -1 ? cleanScore : (cleanScore === -1 ? score : Math.min(score, cleanScore));
      return { name: n, score: best };
    })
    .filter(function (item) {
      return item.score !== -1;
    })
    .sort(function (a, b) {
      return a.score - b.score;
    })
    .map(function (item) {
      return item.name;
    });

  /* Channel name mentions (#168): fuzzy-match against known channel names.
   * @general → subscribers of #general get a DM notification (server-side). */
  var matchedChannels = cachedChannelNames
    .map(function (ch) {
      var bare = ch.charAt(0) === "#" ? ch.slice(1) : ch;
      var score = _mention__fuzzyMatch(info.query, bare);
      return { bare: bare, full: ch, score: score };
    })
    .filter(function (item) {
      return item.score !== -1;
    })
    .sort(function (a, b) {
      return a.score - b.score;
    })
    .slice(0, 8); /* cap channel results */
  if (matchedSpecial.length === 0 && matchedAgents.length === 0 && matchedChannels.length === 0) {
    hideMentionDropdown();
    return;
  }
  showMentionDropdown(matchedSpecial, matchedAgents, matchedChannels);
}

export function handleMentionKeydown(e) {
  if (!mentionDropdown || !mentionDropdown.classList.contains("visible")) {
    return;
  }
  var items = mentionDropdown.querySelectorAll(".mention-item");
  if (items.length === 0) return;
  if (e.key === "ArrowDown") {
    e.preventDefault();
    mentionSelectedIndex = Math.min(mentionSelectedIndex + 1, items.length - 1);
    items.forEach(function (el, i) {
      el.classList.toggle("selected", i === mentionSelectedIndex);
    });
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    mentionSelectedIndex = Math.max(mentionSelectedIndex - 1, 0);
    items.forEach(function (el, i) {
      el.classList.toggle("selected", i === mentionSelectedIndex);
    });
  } else if (
    (e.key === "Tab" || e.key === "Enter") &&
    mentionSelectedIndex >= 0
  ) {
    e.preventDefault();
    insertMention(items[mentionSelectedIndex].getAttribute("data-name"));
  } else if (e.key === "Escape") {
    e.preventDefault();
    hideMentionDropdown();
  }
}

export function handleMentionBlur() {
  setTimeout(hideMentionDropdown, 150);
}

/* Attach mention autocomplete to any textarea */
export function initMentionAutocomplete(inputEl) {
  inputEl.addEventListener("input", handleMentionInput);
  /* Re-run the query once the IME commits its composed text. The
   * input-listener skips during composition (isComposing guard), so
   * without this handler the newly-typed `@` would never show the
   * dropdown in JP IME mode. (todo#383) */
  inputEl.addEventListener("compositionend", handleMentionInput);
  inputEl.addEventListener("keydown", handleMentionKeydown);
  inputEl.addEventListener("blur", handleMentionBlur);
}

/* Init for main compose textarea */
initMentionAutocomplete(document.getElementById("msg-input"));

mentionDropdown.addEventListener("click", function (e) {
  var item = e.target.closest(".mention-item");
  if (item) insertMention(item.getAttribute("data-name"));
});

setInterval(refreshAgentNames, 15000);
refreshAgentNames();
