/* Mention autocomplete module */
/* globals: escapeHtml, getAgentColor, cachedAgentNames */

var mentionDropdown = document.getElementById("mention-dropdown");
var mentionSelectedIndex = -1;

async function refreshAgentNames() {
  try {
    var res = await fetch("/api/agents");
    var agents = await res.json();
    cachedAgentNames = agents.map(function (a) {
      return a.name;
    });
  } catch (e) {
    /* ignore */
  }
}

function getMentionQuery(input) {
  var val = input.value;
  var pos = input.selectionStart;
  var before = val.substring(0, pos);
  var match = before.match(/@([\w-]*)$/);
  if (match) return { query: match[1].toLowerCase(), start: match.index };
  return null;
}

function showMentionDropdown(items) {
  mentionSelectedIndex = 0;
  mentionDropdown.innerHTML = items
    .map(function (name, i) {
      var color = getAgentColor(name);
      return (
        '<div class="mention-item' +
        (i === 0 ? " selected" : "") +
        '" data-name="' +
        escapeHtml(name) +
        '">' +
        '<span class="mention-dot" style="background:' +
        color +
        '"></span>' +
        escapeHtml(name) +
        "</div>"
      );
    })
    .join("");
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
  var filtered = cachedAgentNames.filter(function (n) {
    return n.toLowerCase().indexOf(info.query) === 0;
  });
  if (filtered.length === 0) {
    hideMentionDropdown();
    return;
  }
  showMentionDropdown(filtered);
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
