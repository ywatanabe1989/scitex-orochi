/* Mention autocomplete module */
/* globals: escapeHtml, getAgentColor, cachedAgentNames, apiUrl, isAgentInactive */

var mentionDropdown = document.getElementById("mention-dropdown");
var mentionSelectedIndex = -1;
var cachedAgentObjects = [];

var SPECIAL_MENTIONS = [
  { name: "all", desc: "notify everyone" },
  { name: "channel", desc: "notify this channel" },
  { name: "agents", desc: "notify all agents" },
];

async function refreshAgentNames() {
  try {
    var res = await fetch(apiUrl("/api/agents"));
    var agents = await res.json();
    cachedAgentNames = agents.map(function (a) {
      return a.name;
    });
    cachedAgentObjects = agents;
  } catch (e) {
    /* ignore */
  }
}

function getMentionQuery(input) {
  var val = input.value;
  var pos = input.selectionStart;
  var before = val.substring(0, pos);
  var match = before.match(/(^|[\s])@([\w-]*)$/);
  if (match)
    return {
      query: match[2].toLowerCase(),
      start: match.index + match[1].length,
    };
  return null;
}

function isAgentOnline(name) {
  for (var i = 0; i < cachedAgentObjects.length; i++) {
    if (cachedAgentObjects[i].name === name) {
      return !isAgentInactive(cachedAgentObjects[i]);
    }
  }
  return false;
}

function showMentionDropdown(specialItems, agentItems) {
  mentionSelectedIndex = 0;
  var html = "";

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

  if (specialItems.length > 0 && agentItems.length > 0) {
    html += '<div class="mention-divider"></div>';
  }

  var offset = specialItems.length;
  agentItems.forEach(function (name, i) {
    var online = isAgentOnline(name);
    var dotClass = online ? "mention-dot-online" : "mention-dot-offline";
    html +=
      '<div class="mention-item' +
      (offset + i === 0 ? " selected" : "") +
      '" data-name="' +
      escapeHtml(name) +
      '">' +
      '<span class="mention-dot ' +
      dotClass +
      '"></span>' +
      escapeHtml(name) +
      "</div>";
  });

  mentionDropdown.innerHTML = html;
  mentionDropdown.classList.add("visible");
}

function hideMentionDropdown() {
  mentionDropdown.classList.remove("visible");
  mentionDropdown.innerHTML = "";
  mentionSelectedIndex = -1;
}

function insertMention(name) {
  var input = document.getElementById("msg-input");
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

document.getElementById("msg-input").addEventListener("input", function () {
  var info = getMentionQuery(this);
  if (!info) {
    hideMentionDropdown();
    return;
  }

  var matchedSpecial = SPECIAL_MENTIONS.filter(function (s) {
    return s.name.indexOf(info.query) === 0;
  });
  var matchedAgents = cachedAgentNames.filter(function (n) {
    return n.toLowerCase().indexOf(info.query) === 0;
  });

  if (matchedSpecial.length === 0 && matchedAgents.length === 0) {
    hideMentionDropdown();
    return;
  }
  showMentionDropdown(matchedSpecial, matchedAgents);
});

document.getElementById("msg-input").addEventListener("keydown", function (e) {
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
});

mentionDropdown.addEventListener("click", function (e) {
  var item = e.target.closest(".mention-item");
  if (item) insertMention(item.getAttribute("data-name"));
});

document.getElementById("msg-input").addEventListener("blur", function () {
  setTimeout(hideMentionDropdown, 150);
});

setInterval(refreshAgentNames, 15000);
refreshAgentNames();
