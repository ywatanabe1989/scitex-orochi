/* Orochi Dashboard — WebSocket chat client */
(function () {
  var workspace = window.__orochiWorkspace;
  var wsUrl = window.__orochiWsUrl;
  var csrfToken = window.__orochiCsrfToken;

  var messagesEl = document.getElementById("messages");
  var inputEl = document.getElementById("message-input");
  var formEl = document.getElementById("message-form");
  var channelListEl = document.getElementById("channel-list");
  var currentChannelEl = document.getElementById("current-channel");

  var currentChannel = "#general";
  var ws = null;

  function connectWs() {
    ws = new WebSocket(wsUrl);
    ws.onopen = function () {
      console.log("Dashboard WS connected");
    };
    ws.onmessage = function (evt) {
      var data = JSON.parse(evt.data);
      if (data.type === "message" && data.channel === currentChannel) {
        appendMessage(data.sender, data.text, data.ts);
      }
    };
    ws.onclose = function () {
      console.log("Dashboard WS closed, reconnecting in 3s...");
      setTimeout(connectWs, 3000);
    };
  }

  function appendMessage(sender, text, ts) {
    var div = document.createElement("div");
    div.className = "message";

    var senderSpan = document.createElement("span");
    senderSpan.className = "sender";
    senderSpan.textContent = sender;

    var tsSpan = document.createElement("span");
    tsSpan.className = "ts";
    if (ts) {
      var d = new Date(ts);
      tsSpan.textContent = d.toLocaleTimeString();
    }

    var textDiv = document.createElement("div");
    textDiv.className = "text";
    textDiv.textContent = text;

    div.appendChild(senderSpan);
    div.appendChild(tsSpan);
    div.appendChild(textDiv);
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function sendMessage(text) {
    /* Send via REST API (reliable through Cloudflare) */
    var url = "/api/workspace/" + workspace + "/messages/";
    var xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.setRequestHeader("X-CSRFToken", csrfToken);
    xhr.send(JSON.stringify({ channel: currentChannel, text: text }));
  }

  function switchChannel(name) {
    currentChannel = name;
    currentChannelEl.textContent = name;
    messagesEl.innerHTML = "";
    /* Mark active in sidebar */
    var items = channelListEl.querySelectorAll("li");
    for (var i = 0; i < items.length; i++) {
      items[i].classList.toggle("active", items[i].dataset.channel === name);
    }
    loadHistory(name);
  }

  function loadHistory(channelName) {
    var ch = channelName.replace(/^#/, "");
    var url = "/api/workspace/" + workspace + "/history/" + ch + "/?limit=50";
    var xhr = new XMLHttpRequest();
    xhr.open("GET", url);
    xhr.onload = function () {
      if (xhr.status === 200) {
        var msgs = JSON.parse(xhr.responseText);
        msgs.reverse();
        for (var i = 0; i < msgs.length; i++) {
          appendMessage(msgs[i].sender, msgs[i].content, msgs[i].ts);
        }
      }
    };
    xhr.send();
  }

  /* Event listeners */
  formEl.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = inputEl.value.trim();
    if (!text) return;
    sendMessage(text);
    inputEl.value = "";
  });

  channelListEl.addEventListener("click", function (e) {
    var li = e.target.closest("li");
    if (li && li.dataset.channel) {
      switchChannel(li.dataset.channel);
    }
  });

  /* Init */
  if (wsUrl) {
    connectWs();
  }
  switchChannel("#general");
})();
