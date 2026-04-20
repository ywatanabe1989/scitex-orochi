(function() {
  "use strict";
  (function() {
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/api/config", false);
    try {
      xhr.send();
      if (xhr.status === 200) {
        var cfg = JSON.parse(xhr.responseText);
        if (cfg.ws_upstream) {
          window.__orochiWsUpstream = cfg.ws_upstream;
          window.__orochiApiUpstream = cfg.ws_upstream.replace(/\/$/, "");
        }
        (function _initBrandClock() {
          var clockEl = document.getElementById("brand-clock");
          if (!clockEl) return;
          function _tick() {
            var now = /* @__PURE__ */ new Date();
            var pad = function(n) {
              return n < 10 ? "0" + n : "" + n;
            };
            clockEl.textContent = now.getFullYear() + "-" + pad(now.getMonth() + 1) + "-" + pad(now.getDate()) + " " + pad(now.getHours()) + ":" + pad(now.getMinutes()) + ":" + pad(now.getSeconds());
          }
          _tick();
          setInterval(_tick, 1e3);
        })();
        if (cfg.version) {
          window.__orochiVersion = cfg.version;
          window.__orochiDeployedAt = cfg.deployed_at || "";
          var el = document.getElementById("orochi-version");
          if (el) {
            el.textContent = "v" + cfg.version;
            if (cfg.build_id) {
              el.title = "build " + cfg.build_id + (cfg.deployed_at ? " (" + cfg.deployed_at + ")" : "");
            }
            if (cfg.deployed_at) {
              var deployTime = new Date(cfg.deployed_at).getTime();
              if (!isNaN(deployTime) && Date.now() - deployTime < 3600 * 1e3) {
                var badge = document.createElement("span");
                badge.className = "brand-new-badge";
                badge.title = "Deployed " + cfg.deployed_at;
                var updateBadge = function() {
                  var diff = Math.floor((Date.now() - deployTime) / 1e3);
                  if (diff < 0) diff = 0;
                  var txt;
                  if (diff < 60) txt = "updated " + diff + " sec ago";
                  else if (diff < 3600) txt = "updated " + Math.floor(diff / 60) + " min ago";
                  else {
                    if (badge.parentNode) badge.parentNode.removeChild(badge);
                    return false;
                  }
                  badge.textContent = txt;
                  return true;
                };
                updateBadge();
                el.parentNode.insertBefore(badge, el.nextSibling);
                var badgeTimer = setInterval(function() {
                  if (!updateBadge()) clearInterval(badgeTimer);
                }, 1e4);
              }
            }
          }
        }
        if (cfg.dashboard_token) {
          window.__orochiToken = cfg.dashboard_token;
        }
        if (cfg.server) {
          window.__orochiServer = cfg.server;
          var infoEl = document.getElementById("server-info");
          if (infoEl) {
            var s = cfg.server;
            var uptimeStr = function(secs) {
              var d = Math.floor(secs / 86400);
              var h = Math.floor(secs % 86400 / 3600);
              var m = Math.floor(secs % 3600 / 60);
              if (d > 0) return d + "d " + h + "h";
              if (h > 0) return h + "h " + m + "m";
              return m + "m";
            }(s.uptime || 0);
            var lines = [];
            if (s.hostname) lines.push('<span class="server-label">Host:</span><span class="server-value">' + s.hostname + "</span>");
            if (s.external_ip) lines.push('<span class="server-label">IP:</span><span class="server-value">' + s.external_ip + "</span>");
            if (s.version) lines.push('<span class="server-label">Ver:</span><span class="server-value">v' + s.version + "</span>");
            lines.push('<span class="server-label">Up:</span><span class="server-value">' + uptimeStr + "</span>");
            var msgInput2 = document.getElementById("msg-input");
            var inputHasFocus = msgInput2 && document.activeElement === msgInput2;
            var savedStart = inputHasFocus ? msgInput2.selectionStart : 0;
            var savedEnd = inputHasFocus ? msgInput2.selectionEnd : 0;
            infoEl.innerHTML = lines.join("<br>");
            if (inputHasFocus && document.activeElement !== msgInput2) {
              msgInput2.focus();
              try {
                msgInput2.setSelectionRange(savedStart, savedEnd);
              } catch (_) {
              }
            }
          }
        }
      }
    } catch (e) {
    }
  })();
  (function() {
    var bootstrapBuild = null;
    var poll = function() {
      try {
        var req = new XMLHttpRequest();
        req.open("GET", "/api/config?_=" + Date.now(), true);
        req.onload = function() {
          if (req.status !== 200) return;
          try {
            var cfg = JSON.parse(req.responseText);
            var bid = cfg.build_id || cfg.version || "";
            if (!bid) return;
            if (bootstrapBuild === null) {
              bootstrapBuild = bid;
              return;
            }
            if (bid !== bootstrapBuild) {
              console.log("[orochi] build changed: " + bootstrapBuild + " → " + bid + " — reloading");
              if ("serviceWorker" in navigator) {
                navigator.serviceWorker.getRegistrations().then(function(regs) {
                  regs.forEach(function(r) {
                    r.update();
                  });
                  location.reload();
                });
              } else {
                location.reload();
              }
            }
          } catch (_) {
          }
        };
        req.send();
      } catch (_) {
      }
    };
    setTimeout(poll, 2e3);
    setInterval(poll, 2e4);
  })();
  (function() {
    function _escape(s) {
      if (typeof escapeHtml === "function") return escapeHtml(s);
      return String(s == null ? "" : s).replace(/[&<>"']/g, function(c) {
        return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] || c;
      });
    }
    function _connected(a) {
      if (typeof connected === "function") return connected(a);
      return (a.status || "online") !== "offline";
    }
    function renderAgentIcon(a, size) {
      var px = size || 14;
      var name = a.name || "";
      if (typeof agentIdentity === "function") {
        var ident = agentIdentity(a);
        if (ident && typeof ident.iconHtml === "function") {
          return '<span class="agent-badge-icon avatar-clickable" data-avatar-agent="' + _escape(name) + '" title="Click to change avatar">' + ident.iconHtml(px) + "</span>";
        }
      }
      var initial = (name[0] || "?").toUpperCase();
      var color = typeof getAgentColor === "function" ? getAgentColor(name) : "#888";
      return '<span class="agent-badge-icon avatar-clickable" data-avatar-agent="' + _escape(name) + '" title="Click to change avatar" style="display:inline-flex;align-items:center;justify-content:center;width:' + px + "px;height:" + px + "px;border-radius:50%;background:" + color + ";color:#111;font-size:" + Math.round(px * 0.7) + 'px;font-weight:600">' + _escape(initial) + "</span>";
    }
    function renderAgentStar(a) {
      var pinned = !!a.pinned;
      return '<button type="button" class="agent-badge-star pin-btn activity-pin-btn' + (pinned ? " pinned activity-pin-on" : "") + '" data-pin-name="' + _escape(a.name || "") + '" data-pin-next="' + (pinned ? "false" : "true") + '" title="' + _escape(pinned ? "Unstar" : "Star (keeps as ghost when offline)") + '">' + (pinned ? "★" : "☆") + "</button>";
    }
    function renderAgentLeds(a, opts) {
      var extra = opts && opts.extraClass ? " " + opts.extraClass : "";
      var liveness = a.liveness || a.status || "online";
      var paneState = a.pane_state || "unknown";
      var wsOn = _connected(a);
      var ledWs = '<span class="activity-led activity-led-ws activity-led-ws-' + (wsOn ? "on" : "off") + extra + '" title="' + _escape(
        "1. WebSocket — " + (wsOn ? "connected" : "disconnected") + "\n  TCP+WS handshake; green = sidecar holds an open WS."
      ) + '"></span>';
      var pong = a.last_pong_ts;
      var pongAge = pong != null ? (Date.now() - new Date(pong).getTime()) / 1e3 : null;
      var pingState = "off";
      var pingLabel = "no pong yet";
      if (pongAge != null) {
        if (pongAge < 60) {
          pingState = "on";
          pingLabel = "pong " + Math.round(pongAge) + "s ago";
          if (a.last_rtt_ms != null)
            pingLabel += " (" + Math.round(a.last_rtt_ms) + "ms round-trip)";
        } else if (pongAge < 180) {
          pingState = "warn";
          pingLabel = "stale pong " + Math.round(pongAge) + "s ago";
        } else {
          pingState = "off";
          pingLabel = "no recent pong (" + Math.round(pongAge) + "s)";
        }
      }
      var ledPing = '<span class="activity-led activity-led-ping activity-led-ping-' + pingState + extra + '" title="' + _escape(
        "2. Ping — " + pingLabel + "\n  Hub sends ping every 25s; sidecar echoes pong.\n  Green = fresh, yellow = stale, grey = none."
      ) + '"></span>';
      var ledFn = '<span class="activity-led activity-led-fn activity-led-fn-' + liveness + extra + '" title="' + _escape(
        "3. Local functional state — " + liveness.toUpperCase() + " (pane: " + paneState + ")\n  Heuristic from local pane text; not fully reliable.\n  green = running, yellow = idle, blue = waiting,\n  red = auth_error, orange = stale."
      ) + '"></span>';
      var echo = a.last_nonce_echo_at;
      var echoAge = echo != null ? (Date.now() - new Date(echo).getTime()) / 1e3 : null;
      var echoState = "pending";
      var echoLabel = "not yet probed by any peer";
      if (echoAge != null) {
        if (echoAge < 90) {
          echoState = "on";
          echoLabel = "echoed " + Math.round(echoAge) + "s ago";
        } else if (echoAge < 300) {
          echoState = "warn";
          echoLabel = "stale echo " + Math.round(echoAge) + "s ago";
        } else {
          echoState = "fail";
          echoLabel = "no echo (" + Math.round(echoAge) + "s)";
        }
      }
      var ledEcho = '<span class="activity-led activity-led-echo activity-led-echo-' + echoState + extra + '" title="' + _escape(
        "4. Remote functional state — " + echoLabel + "\n  Active probe: peer host posts random nonce; agent must\n  echo it back through Claude. Strongest proof-of-life.\n  green = recent, yellow = stale, red = no echo, grey = pending."
      ) + '"></span>';
      return ledWs + ledPing + ledFn + ledEcho;
    }
    function renderAgentName(a, opts) {
      var hideHost = opts && opts.hideHost;
      var displayName = a.name || "";
      if (typeof hostedAgentName === "function") {
        displayName = hostedAgentName(a);
      } else if (!hideHost && a.machine && displayName.indexOf("@") === -1) {
        displayName = displayName + "@" + a.machine;
      }
      if (typeof cleanAgentName === "function") {
        displayName = cleanAgentName(displayName);
      }
      var color = typeof getAgentColor === "function" ? getAgentColor(a.name || "") : "";
      return '<span class="agent-badge-name"' + (color ? ' style="color:' + color + '"' : "") + ">" + _escape(displayName) + "</span>";
    }
    function renderAgentBadge(a, opts) {
      opts = opts || {};
      var icon = renderAgentIcon(a, opts.iconSize);
      var leds = renderAgentLeds(a, { extraClass: opts.extraClass });
      var name = opts.hideName ? "" : renderAgentName(a, opts);
      var star = renderAgentStar(a);
      return icon + leds + name + star;
    }
    function isAgentAllGreen(a) {
      if (!_connected(a)) return false;
      var pongAge = a.last_pong_ts != null ? (Date.now() - new Date(a.last_pong_ts).getTime()) / 1e3 : null;
      if (!(pongAge != null && pongAge < 60)) return false;
      if ((a.liveness || a.status || "") !== "online") return false;
      var echoAge = a.last_nonce_echo_at != null ? (Date.now() - new Date(a.last_nonce_echo_at).getTime()) / 1e3 : null;
      if (!(echoAge != null && echoAge < 90)) return false;
      return true;
    }
    function isAgentVisible(a) {
      if (a.pinned) return true;
      if (_connected(a)) return true;
      var pongAge = a.last_pong_ts != null ? (Date.now() - new Date(a.last_pong_ts).getTime()) / 1e3 : null;
      if (pongAge != null && pongAge < 60) return true;
      if ((a.liveness || a.status || "") === "online") return true;
      var echoAge = a.last_nonce_echo_at != null ? (Date.now() - new Date(a.last_nonce_echo_at).getTime()) / 1e3 : null;
      if (echoAge != null && echoAge < 90) return true;
      return false;
    }
    window.renderAgentIcon = renderAgentIcon;
    window.renderAgentStar = renderAgentStar;
    window.renderAgentLeds = renderAgentLeds;
    window.renderAgentName = renderAgentName;
    window.renderAgentBadge = renderAgentBadge;
    window.isAgentAllGreen = isAgentAllGreen;
    window.isAgentVisible = isAgentVisible;
  })();
  (function() {
    function _escape(s) {
      if (typeof escapeHtml === "function") return escapeHtml(s);
      return String(s == null ? "" : s).replace(/[&<>"']/g, function(c) {
        return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] || c;
      });
    }
    function _connected(a) {
      if (typeof connected === "function") return connected(a);
      return (a.status || "online") !== "offline";
    }
    function _renderAgentGlyphSvg(a, gx, gy, size, ident, opts) {
      opts = opts || {};
      var cacheMap;
      if (opts.isHuman) {
        cacheMap = typeof cachedHumanIcons !== "undefined" ? cachedHumanIcons : {};
      } else {
        cacheMap = typeof cachedAgentIcons !== "undefined" ? cachedAgentIcons : {};
      }
      var cached = cacheMap && cacheMap[a.name] || "";
      var isUrl = cached && (cached.indexOf("http") === 0 || cached.indexOf("/") === 0);
      if (isUrl) {
        return '<image class="topo-agent-glyph-img' + (opts.isHuman ? " topo-human-glyph topo-human-glyph-img" : "") + '" href="' + _escape(cached) + '" x="' + (gx - size / 2).toFixed(1) + '" y="' + (gy - size / 2).toFixed(1) + '" width="' + size + '" height="' + size + '" preserveAspectRatio="xMidYMid slice"/>';
      }
      if (cached) {
        return '<text class="' + (opts.isHuman ? "topo-human-glyph" : "topo-agent-glyph") + '" x="' + gx.toFixed(1) + '" y="' + (opts.isHuman ? (gy + 4).toFixed(1) : gy.toFixed(1)) + '" font-size="' + (opts.isHuman ? 13 : 12) + '"' + (opts.isHuman ? "" : ' dominant-baseline="central" text-anchor="middle"') + ">" + cached + "</text>";
      }
      if (opts.isHuman) {
        return '<text class="topo-human-glyph" x="' + gx.toFixed(1) + '" y="' + (gy + 4).toFixed(1) + '" font-size="13">👤</text>';
      }
      var color = ident && ident.color || (typeof getAgentColor === "function" ? getAgentColor(a.name || "") : "#4ecdc4");
      var markup = typeof getSnakeIcon === "function" ? getSnakeIcon(size, color) : "";
      return markup.replace(
        /<svg /,
        '<svg x="' + (gx - size / 2).toFixed(1) + '" y="' + (gy - size / 2).toFixed(1) + '" '
      );
    }
    function renderAgentBadgeSvg(a, pos, opts) {
      opts = opts || {};
      var x = pos.x;
      var y = pos.y;
      var showName = opts.showName !== false;
      var showStar = opts.showStar !== false;
      var showLeds = opts.showLeds !== false && !opts.isHuman;
      var iconSize = opts.iconSize || 14;
      var LED_R = 4;
      var GAP = 5;
      var ident = typeof agentIdentity === "function" ? agentIdentity(a) : {
        color: typeof getAgentColor === "function" ? getAgentColor(a.name || "") : "#4ecdc4",
        displayName: a.name || "",
        tooltip: a.name || ""
      };
      var nameText = opts.labelOverride || ident.displayName || a.name || "";
      var color = opts.isHuman ? "#fbbf24" : ident.color;
      var glyphX = opts.isHuman ? x - 10 : x - LED_R - GAP / 2 - 28;
      var glyph = _renderAgentGlyphSvg(a, glyphX, y, iconSize, ident, opts);
      var wsLed = "";
      var fnLed = "";
      if (showLeds) {
        var connectedFlag = _connected(a);
        var liveness = a.liveness || a.status || (connectedFlag ? "online" : "offline");
        var FN_COLORS = {
          online: "#4ecdc4",
          idle: "#ffd93d",
          stale: "#ff8c42",
          offline: "#555"
        };
        var wsColor = connectedFlag ? "#4ecdc4" : "#555";
        var fnColor = FN_COLORS[liveness] || "#555";
        if (opts.isDead) fnColor = "#ef4444";
        var wsCx = x - (LED_R + GAP / 2);
        var fnCx = x + (LED_R + GAP / 2);
        wsLed = '<circle cx="' + wsCx.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="' + LED_R + '" fill="' + wsColor + '" stroke="#0a0a0a" stroke-width="0.5"><title>WebSocket: ' + (connectedFlag ? "connected" : "disconnected") + "</title></circle>";
        fnLed = '<circle cx="' + fnCx.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="' + LED_R + '" fill="' + fnColor + '" stroke="#0a0a0a" stroke-width="0.5"><title>Liveness: ' + _escape(liveness) + "</title></circle>";
      }
      var pinMark = "";
      if (showStar && a.pinned) {
        pinMark = '<text class="topo-label-pin" x="' + (x + LED_R + GAP / 2 + 8).toFixed(1) + '" y="' + (y + 4).toFixed(1) + '" fill="#fbbf24" font-size="13">★</text>';
      }
      var nameX = opts.isHuman ? x + 6 : x + LED_R + GAP / 2 + 22;
      var textW = Math.max(40, nameText.length * 6.5);
      var badgeLeft = opts.isHuman ? x - 18 : glyphX - 14;
      var badgeRight = nameX + textW + 6;
      var badgeWidth = badgeRight - badgeLeft;
      var badgeY = y - 11;
      var bgClass = opts.isHuman ? "topo-agent-bg topo-human-bg" : "topo-agent-bg";
      var bg = '<rect class="' + bgClass + '" x="' + badgeLeft.toFixed(1) + '" y="' + badgeY.toFixed(1) + '" width="' + badgeWidth.toFixed(1) + '" height="22" rx="11" ry="11"/>';
      var nameSvg = "";
      if (showName) {
        nameSvg = '<text class="topo-label topo-label-agent" x="' + nameX.toFixed(1) + '" y="' + (y + 4).toFixed(1) + '" fill="' + color + '">' + _escape(nameText) + "</text>";
      }
      var cls = "topo-node topo-agent";
      if (opts.isHuman) cls += " topo-human";
      if (opts.isSelected) cls += " topo-agent-selected";
      if (opts.isDead) cls += " topo-agent-dead";
      if (opts.extraClass) cls += " " + opts.extraClass;
      return '<g class="' + cls + '" data-agent="' + _escape(a.name || "") + '"><title>' + _escape(ident.tooltip || a.name || "") + "</title>" + bg + glyph + wsLed + fnLed + pinMark + nameSvg + "</g>";
    }
    window.renderAgentBadgeSvg = renderAgentBadgeSvg;
  })();
  (function() {
    function _escape(s) {
      if (typeof escapeHtml === "function") return escapeHtml(s);
      return String(s == null ? "" : s).replace(/[&<>"']/g, function(c) {
        return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] || c;
      });
    }
    function _norm(ch) {
      if (!ch) return "";
      return ch.charAt(0) === "#" ? ch : "#" + ch;
    }
    function channelBadgeModel(name) {
      var raw = name || "";
      var norm = _norm(raw);
      var prefs = typeof window !== "undefined" && window._channelPrefs && (window._channelPrefs[norm] || window._channelPrefs[raw]) || {};
      var unreadMap = typeof window !== "undefined" && window.channelUnread || {};
      var ident = typeof channelIdentity === "function" ? channelIdentity(norm) : { displayName: norm, tooltip: norm, color: "", iconHtml: null };
      var cachedIcon = typeof cachedChannelIcons !== "undefined" && (cachedChannelIcons[norm] || cachedChannelIcons[raw]) || "";
      var iconIsUrl = !!cachedIcon && (cachedIcon.indexOf("http") === 0 || cachedIcon.indexOf("/") === 0);
      return {
        name: raw,
        norm,
        displayName: ident.displayName || norm,
        color: ident.color || "",
        tooltip: ident.tooltip || norm,
        isStarred: !!prefs.is_starred,
        isMuted: !!prefs.is_muted,
        isHidden: !!prefs.is_hidden,
        unread: unreadMap[raw] || unreadMap[norm] || 0,
        iconGlyph: cachedIcon,
        iconIsUrl,
        // Same iconHtml(size) contract as channelIdentity.iconHtml so
        // call sites can reuse it unchanged.
        iconHtml: ident.iconHtml
      };
    }
    function renderChannelBadgeHtml(name, opts) {
      opts = opts || {};
      var m = channelBadgeModel(name);
      var ctx = opts.context || "sidebar";
      var showEye = !!opts.showEye;
      var showUnread = !!opts.showUnread;
      var draggable = !!opts.draggable;
      var displayLabel = opts.label || m.displayName;
      var dragHtml = draggable ? '<span class="ch-drag-handle" title="Drag to reorder">&#8942;</span>' : "";
      var iconPx = opts.iconSize || 14;
      var iconInner = typeof m.iconHtml === "function" ? m.iconHtml(iconPx) : _escape(m.norm);
      var iconHtml = '<span class="ch-icon ch-identity-icon" data-channel="' + _escape(m.norm) + '" title="Click to change icon">' + iconInner + "</span>";
      var starHtml = '<span class="ch-star ch-pin ' + (m.isStarred ? "ch-pin-on ch-star-on" : "ch-pin-off ch-star-off") + '" data-channel="' + _escape(m.norm) + '" data-ch="' + _escape(m.norm) + '" title="' + (m.isStarred ? "Unstar" : "Star (float to top)") + '">' + (m.isStarred ? "★" : "☆") + "</span>";
      var eyeHtml = "";
      if (showEye) {
        eyeHtml = '<span class="ch-eye ' + (m.isHidden ? "ch-eye-off" : "ch-eye-on") + '" data-channel="' + _escape(m.norm) + '" data-ch="' + _escape(m.norm) + '" title="' + (m.isHidden ? "Show channel (un-hide)" : "Hide channel (dim in list)") + '">' + (m.isHidden ? "🚫" : "👁") + "</span>";
      }
      var muteHtml = '<span class="ch-mute ' + (m.isMuted ? "ch-mute-on" : "ch-mute-off") + '" data-channel="' + _escape(m.norm) + '" data-ch="' + _escape(m.norm) + '" title="' + (m.isMuted ? "Unmute notifications" : "Mute notifications") + '">' + (m.isMuted ? "🔕" : "🔔") + "</span>";
      var nameCls = ctx === "pool" ? "ch-name topo-pool-chip-name" : "ch-name";
      var nameHtml = '<span class="' + nameCls + '">' + _escape(displayLabel) + "</span>";
      var unreadHtml = "";
      if (showUnread) {
        unreadHtml = '<span class="ch-badge-slot">' + (m.unread > 0 ? '<span class="unread-badge">' + (m.unread > 99 ? "99+" : m.unread) + "</span>" : "") + "</span>";
      }
      return dragHtml + iconHtml + starHtml + eyeHtml + muteHtml + nameHtml + unreadHtml;
    }
    function renderChannelBadgeSvg(name, pos, opts) {
      opts = opts || {};
      var m = channelBadgeModel(name);
      var showEye = !!opts.showEye;
      var showUnread = !!opts.showUnread;
      var x = pos.x;
      var y = pos.y;
      var r = pos.r || 12;
      var count = opts.count != null ? opts.count : null;
      var labelText = count != null ? m.norm + " (" + count + ")" : m.norm;
      var extraClass = opts.extraClass || "";
      var pts = x + "," + (y - r) + " " + (x + r) + "," + y + " " + x + "," + (y + r) + " " + (x - r) + "," + y;
      var chCls = "topo-node topo-channel";
      if (m.isStarred) chCls += " topo-channel-starred";
      if (m.isMuted) chCls += " topo-channel-muted";
      if (m.isHidden) chCls += " topo-channel-hidden";
      if (extraClass) chCls += " " + extraClass;
      var iconGlyph = "";
      if (m.iconIsUrl) {
        var imgSize = Math.max(14, Math.round(r * 1.6));
        iconGlyph = '<image class="topo-ch-icon-img ch-icon" data-channel="' + _escape(m.norm) + '" href="' + _escape(m.iconGlyph) + '" x="' + (x - imgSize / 2).toFixed(1) + '" y="' + (y - imgSize / 2).toFixed(1) + '" width="' + imgSize + '" height="' + imgSize + '" preserveAspectRatio="xMidYMid slice"/>';
      } else if (m.iconGlyph) {
        iconGlyph = '<text class="topo-ch-emoji ch-icon" data-channel="' + _escape(m.norm) + '" x="' + x.toFixed(1) + '" y="' + (y + 4).toFixed(1) + '" font-size="' + Math.max(11, Math.round(r * 1.2)) + '" text-anchor="middle" dominant-baseline="middle">' + _escape(m.iconGlyph) + "</text>";
      }
      var starFill = m.isStarred ? "#fbbf24" : "#3a3a3a";
      var starGlyph = '<text class="topo-ch-star ch-star" data-channel="' + _escape(m.norm) + '" x="' + (x + r + 2).toFixed(1) + '" y="' + (y - r + 4).toFixed(1) + '" font-size="11" fill="' + starFill + '" style="cursor:pointer" title="' + (m.isStarred ? "Unstar" : "Star") + '">' + (m.isStarred ? "★" : "☆") + "</text>";
      var eyeGlyph = "";
      if (showEye) {
        eyeGlyph = '<text class="topo-ch-eye ch-eye" data-channel="' + _escape(m.norm) + '" x="' + (x - r - 12).toFixed(1) + '" y="' + (y + r + 8).toFixed(1) + '" font-size="9" fill="#94a3b8" style="cursor:pointer">' + (m.isHidden ? "🚫" : "👁") + "</text>";
      }
      var muteGlyph = '<text class="topo-ch-mute ch-mute" data-channel="' + _escape(m.norm) + '" x="' + (x - r - 12).toFixed(1) + '" y="' + (y - r + 4).toFixed(1) + '" font-size="9" fill="' + (m.isMuted ? "#94a3b8" : "#3a3a3a") + '" style="cursor:pointer">' + (m.isMuted ? "🔕" : "🔔") + "</text>";
      var labelW = Math.max(40, labelText.length * 6.5);
      var labelX = x - labelW / 2 - 6;
      var labelY = y - r - 18;
      var labelRect = '<rect class="topo-channel-bg" x="' + labelX.toFixed(1) + '" y="' + labelY.toFixed(1) + '" width="' + (labelW + 12).toFixed(1) + '" height="20" rx="10" ry="10"/>';
      var labelTextSvg = '<text class="topo-label topo-label-ch" x="' + x + '" y="' + (y - r - 4).toFixed(1) + '" text-anchor="middle">' + _escape(labelText) + "</text>";
      var unreadSvg = "";
      if (showUnread && m.unread > 0) {
        unreadSvg = '<circle class="topo-ch-unread" cx="' + (x + r + 6).toFixed(1) + '" cy="' + (y + r).toFixed(1) + '" r="7" fill="#ef4444"/><text class="topo-ch-unread-text" x="' + (x + r + 6).toFixed(1) + '" y="' + (y + r + 3).toFixed(1) + '" font-size="9" fill="#fff" text-anchor="middle">' + (m.unread > 9 ? "9+" : m.unread) + "</text>";
      }
      var attrs = opts.extraAttrs || "";
      return '<g class="' + chCls + '" data-channel="' + _escape(m.norm) + '"' + (count != null ? ' data-agent-count="' + count + '"' : "") + (attrs ? " " + attrs : "") + '><polygon points="' + pts + '" fill="#1a1a1a" stroke="#444" stroke-width="1"/>' + iconGlyph + starGlyph + eyeGlyph + muteGlyph + labelRect + labelTextSvg + unreadSvg + "</g>";
    }
    var _attached = false;
    function attachChannelBadgeHandlers() {
      if (_attached) return;
      _attached = true;
      if (typeof document === "undefined") return;
      document.body.addEventListener(
        "click",
        function(ev) {
          var star = ev.target.closest(
            ".ch-star[data-channel], .ch-pin[data-channel], .ch-pin[data-ch]"
          );
          if (star) {
            var chS = star.getAttribute("data-channel") || star.getAttribute("data-ch");
            if (chS && typeof _setChannelPref === "function") {
              ev.stopPropagation();
              ev.preventDefault();
              var cur = window._channelPrefs && window._channelPrefs[_norm(chS)] || {};
              _setChannelPref(chS, { is_starred: !cur.is_starred });
              return;
            }
          }
          var eye = ev.target.closest(".ch-eye[data-channel], .ch-eye[data-ch]");
          if (eye) {
            var chE = eye.getAttribute("data-channel") || eye.getAttribute("data-ch");
            if (chE && typeof _setChannelPref === "function") {
              ev.stopPropagation();
              ev.preventDefault();
              var curE = window._channelPrefs && window._channelPrefs[_norm(chE)] || {};
              _setChannelPref(chE, { is_hidden: !curE.is_hidden });
              return;
            }
          }
          var mute = ev.target.closest(
            ".ch-mute[data-channel], .ch-mute[data-ch]"
          );
          if (mute) {
            var chM = mute.getAttribute("data-channel") || mute.getAttribute("data-ch");
            if (chM && typeof _setChannelPref === "function") {
              ev.stopPropagation();
              ev.preventDefault();
              var curM = window._channelPrefs && window._channelPrefs[_norm(chM)] || {};
              _setChannelPref(chM, { is_muted: !curM.is_muted });
              return;
            }
          }
          var icon = ev.target.closest(".ch-icon[data-channel]");
          if (icon) {
            var chI = icon.getAttribute("data-channel");
            if (chI && typeof window.openEmojiPicker === "function" && typeof _setChannelIcon === "function") {
              ev.stopPropagation();
              ev.preventDefault();
              window.openEmojiPicker(function(emoji) {
                _setChannelIcon(chI, { icon_emoji: emoji });
              });
              return;
            }
          }
        },
        true
        // capture — beat site-local click handlers that stopPropagation
      );
    }
    if (typeof document !== "undefined") {
      if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", attachChannelBadgeHandlers);
      } else {
        attachChannelBadgeHandlers();
      }
    }
    window.channelBadgeModel = channelBadgeModel;
    window.renderChannelBadgeHtml = renderChannelBadgeHtml;
    window.renderChannelBadgeSvg = renderChannelBadgeSvg;
    window.attachChannelBadgeHandlers = attachChannelBadgeHandlers;
  })();
  var currentChannel$1 = null;
  var lastActiveChannel$1 = null;
  try {
    var _persistedCh = localStorage.getItem("orochi_active_channel");
    if (_persistedCh && _persistedCh !== "__all__") {
      currentChannel$1 = _persistedCh;
      lastActiveChannel$1 = _persistedCh;
    }
  } catch (_) {
  }
  function setCurrentChannel$1(ch) {
    currentChannel$1 = ch;
    if (ch) lastActiveChannel$1 = ch;
    try {
      localStorage.setItem("orochi_active_channel", ch == null ? "__all__" : ch);
    } catch (_) {
    }
    if (typeof chatFilterReset === "function") {
      try {
        chatFilterReset();
      } catch (_) {
      }
    }
    try {
      var inp = document.getElementById("msg-input");
      if (inp) {
        var targetCh = ch || lastActiveChannel$1;
        if (targetCh && targetCh.indexOf("dm:") === 0) {
          inp.placeholder = "Message " + _dmFriendlyLabel(targetCh) + "…";
        } else {
          inp.placeholder = targetCh ? "Message #" + targetCh.replace(/^#/, "") + "…" : "Type a message…";
        }
      }
    } catch (_) {
    }
    _updateComposerTarget$1(ch || lastActiveChannel$1, false);
    _updateChannelTopicBanner(ch || lastActiveChannel$1);
  }
  function _dmFriendlyLabel(ch) {
    if (!ch || ch.indexOf("dm:") !== 0) return ch || "";
    var parts = ch.substring(3).split("|");
    var self = window.__orochiUserName ? "human:" + window.__orochiUserName : "";
    var others = parts.filter(function(p) {
      return p && p !== self;
    });
    if (others.length === 0) others = parts;
    return others.map(function(p) {
      return "@" + p.replace(/^(agent:|human:)/, "");
    }).join(", ");
  }
  window._dmFriendlyLabel = _dmFriendlyLabel;
  function _updateComposerTarget$1(ch, isReply, replyMsgId) {
    try {
      var el = document.getElementById("composer-target");
      var nameEl = document.getElementById("composer-target-name");
      if (!el || !nameEl) return;
      el.classList.remove("is-dm", "is-reply");
      if (isReply && replyMsgId) {
        el.classList.add("is-reply");
        nameEl.textContent = "↳ reply in " + (ch || "#?") + " · msg#" + replyMsgId;
        el.firstChild.nodeValue = "";
      } else if (ch && ch.startsWith("dm:")) {
        el.classList.add("is-dm");
        nameEl.textContent = "→ " + _dmFriendlyLabel(ch) + " (DM)";
        el.firstChild.nodeValue = "";
      } else {
        nameEl.textContent = ch || "#general";
        el.firstChild.nodeValue = "→ ";
      }
    } catch (_) {
    }
  }
  window._updateComposerTarget = _updateComposerTarget$1;
  window.setCurrentChannel = setCurrentChannel$1;
  var _channelDescriptions$1 = {};
  var _agentChannelMap = {};
  function _updateChannelTopicBanner$1(ch) {
    var banner = document.getElementById("channel-topic-banner");
    var textEl = document.getElementById("channel-topic-text");
    var membersEl = document.getElementById("channel-members");
    if (!banner || !textEl) return;
    var desc = _channelDescriptions$1[ch] || "";
    if (desc) {
      textEl.textContent = desc;
    } else {
      textEl.textContent = "";
    }
    if (membersEl) {
      var members = _agentChannelMap[ch] || [];
      if (members.length > 0) {
        membersEl.innerHTML = members.map(function(m) {
          var dot = m.online ? '<span class="ch-mem-dot ch-mem-online"></span>' : '<span class="ch-mem-dot"></span>';
          return '<span class="ch-mem-pill" title="' + escapeHtml(m.name) + '">' + dot + escapeHtml(cleanAgentName ? cleanAgentName(m.name) : m.name) + "</span>";
        }).join("");
        membersEl.style.display = "";
      } else {
        membersEl.style.display = "none";
      }
    }
    var membersBtn = document.getElementById("channel-members-btn");
    var membersCountEl = document.getElementById("channel-members-count");
    if (membersBtn && ch && !ch.startsWith("dm:")) {
      var liveCount = membersEl ? membersEl.children.length : 0;
      if (membersCountEl)
        membersCountEl.textContent = liveCount > 0 ? liveCount : "";
      membersBtn.style.display = "";
    } else if (membersBtn) {
      membersBtn.style.display = "none";
    }
    var _onChatTab = typeof activeTab !== "undefined" ? activeTab === "chat" : true;
    banner.style.display = _onChatTab && (desc || ch) ? "" : "none";
  }
  var _membersCache = {};
  function toggleMembersPanel() {
    var panel = document.getElementById("channel-members-panel");
    if (!panel) return;
    if (panel.style.display === "none") {
      openMembersPanel(currentChannel || lastActiveChannel);
    } else {
      closeMembersPanel();
    }
  }
  function openMembersPanel(ch) {
    var panel = document.getElementById("channel-members-panel");
    var list = document.getElementById("ch-members-list");
    var title = document.getElementById("ch-members-panel-title");
    if (!panel || !list) return;
    if (title) title.textContent = (ch || "Channel") + " — Members";
    list.innerHTML = '<div class="ch-members-loading">Loading...</div>';
    panel.style.display = "";
    if (_membersCache[ch]) {
      _renderMembersPanel(_membersCache[ch]);
      return;
    }
    fetch(apiUrl("/api/channel-members/?channel=" + encodeURIComponent(ch)), {
      credentials: "same-origin"
    }).then(function(r) {
      return r.json();
    }).then(function(data) {
      _membersCache[ch] = data;
      _renderMembersPanel(data);
    }).catch(function() {
      if (list)
        list.innerHTML = '<div class="ch-members-loading">Failed to load members.</div>';
    });
  }
  function _renderMembersPanel(members) {
    var list = document.getElementById("ch-members-list");
    if (!list) return;
    var rw = members.filter(function(m) {
      return m.permission === "read-write";
    });
    var ro = members.filter(function(m) {
      return m.permission === "read-only";
    });
    var html = "";
    if (rw.length > 0) {
      html += '<div class="ch-members-section-label">Read & Write (' + rw.length + ")</div>";
      html += rw.map(function(m) {
        var icon = m.kind === "agent" ? "&#129302;" : "&#128100;";
        return '<div class="ch-members-row">' + icon + " " + escapeHtml(m.username) + "</div>";
      }).join("");
    }
    if (ro.length > 0) {
      html += '<div class="ch-members-section-label ch-members-ro-label">Read Only (' + ro.length + ")</div>";
      html += ro.map(function(m) {
        var icon = m.kind === "agent" ? "&#129302;" : "&#128100;";
        return '<div class="ch-members-row ch-members-ro">' + icon + " " + escapeHtml(m.username) + ' <span class="ch-members-ro-badge">ro</span></div>';
      }).join("");
    }
    if (!html) html = '<div class="ch-members-loading">No members found.</div>';
    list.innerHTML = html;
  }
  function closeMembersPanel() {
    var panel = document.getElementById("channel-members-panel");
    if (panel) panel.style.display = "none";
  }
  window.toggleMembersPanel = toggleMembersPanel;
  window.openMembersPanel = openMembersPanel;
  window.closeMembersPanel = closeMembersPanel;
  function openChannelTopicEdit() {
    var modal = document.getElementById("channel-topic-modal");
    var inp = document.getElementById("channel-topic-input");
    if (!modal || !inp) return;
    inp.value = _channelDescriptions$1[currentChannel] || "";
    modal.style.display = "flex";
    setTimeout(function() {
      inp.focus();
    }, 50);
  }
  window.openChannelTopicEdit = openChannelTopicEdit;
  function closeChannelTopicEdit() {
    var modal = document.getElementById("channel-topic-modal");
    if (modal) modal.style.display = "none";
  }
  window.closeChannelTopicEdit = closeChannelTopicEdit;
  function saveChannelTopic() {
    var inp = document.getElementById("channel-topic-input");
    if (!inp || !currentChannel) return;
    var desc = inp.value.trim();
    fetch(apiUrl("/api/channels/"), {
      method: "PATCH",
      headers: Object.assign(
        { "Content-Type": "application/json" },
        orochiHeaders()
      ),
      body: JSON.stringify({ name: currentChannel, description: desc }),
      credentials: "same-origin"
    }).then(function(r) {
      return r.json();
    }).then(function() {
      _channelDescriptions$1[currentChannel] = desc;
      _updateChannelTopicBanner$1(currentChannel);
      closeChannelTopicEdit();
    }).catch(function(e) {
      console.warn("saveChannelTopic error:", e);
    });
  }
  window.saveChannelTopic = saveChannelTopic;
  if (currentChannel) {
    try {
      var _inp = document.getElementById("msg-input");
      if (_inp)
        _inp.placeholder = "Message " + currentChannel.replace(/^#/, "#") + "…";
    } catch (_) {
    }
    document.addEventListener("DOMContentLoaded", function() {
      _updateComposerTarget(currentChannel, false);
    });
  }
  document.addEventListener("DOMContentLoaded", function() {
    fetch(apiUrl("/api/channels/"), { credentials: "same-origin" }).then(function(r) {
      return r.json();
    }).then(function(list) {
      list.forEach(function(ch) {
        if (ch.name) {
          if (ch.description) _channelDescriptions[ch.name] = ch.description;
          _channelPrefs[ch.name] = {
            is_starred: ch.is_starred || false,
            is_muted: ch.is_muted || false,
            is_hidden: ch.is_hidden || false,
            notification_level: ch.notification_level || "all"
          };
          if (typeof cacheChannelIdentity === "function") {
            cacheChannelIdentity(ch);
          }
        }
      });
      if (currentChannel) _updateChannelTopicBanner(currentChannel);
      var chContainer = document.getElementById("channels");
      if (chContainer) chContainer._lastStatsJson = null;
      if (typeof fetchStats === "function") fetchStats();
    }).catch(function(_) {
    });
  });
  function _openAgentDmSimple(agentA, agentB) {
    if (!agentA || !agentB || agentA === agentB) return;
    var pair = [agentA, agentB].sort();
    var channel = "dm:agent:" + pair[0] + "|agent:" + pair[1];
    if (typeof setCurrentChannel === "function") setCurrentChannel(channel);
    if (typeof loadChannelHistory === "function") loadChannelHistory(channel);
    if (typeof _activateTab === "function") _activateTab("chat");
  }
  window._openAgentDmSimple = _openAgentDmSimple;
  var userName$1 = window.__orochiUserName || localStorage.getItem("orochi_username");
  if (!userName$1) {
    userName$1 = prompt("Enter your display name for Orochi:", "");
    if (userName$1) {
      localStorage.setItem("orochi_username", userName$1);
    } else {
      userName$1 = "human";
    }
  }
  window.__orochiToken || window.__orochiDashboardToken || new URLSearchParams(location.search).get("token") || "";
  document.addEventListener("visibilitychange", function() {
    if (!document.hidden) {
      unreadCount = 0;
      document.title = baseTitle;
    }
  });
  function updateChannelUnreadBadges() {
    document.querySelectorAll("#channels .channel-item").forEach(function(el) {
      var ch = el.getAttribute("data-channel");
      var count = channelUnread[ch] || 0;
      var slot = el.querySelector(".ch-badge-slot");
      if (slot) {
        var badge = slot.querySelector(".unread-badge");
        if (count > 0) {
          if (!badge) {
            badge = document.createElement("span");
            badge.className = "unread-badge";
            slot.appendChild(badge);
          }
          badge.textContent = count > 99 ? "99+" : count;
        } else if (badge) {
          badge.remove();
        }
      } else {
        var badge2 = el.querySelector(".unread-badge");
        if (count > 0) {
          if (!badge2) {
            badge2 = document.createElement("span");
            badge2.className = "unread-badge";
            el.appendChild(badge2);
          }
          badge2.textContent = count > 99 ? "99+" : count;
        } else if (badge2) {
          badge2.remove();
        }
      }
    });
  }
  window.updateChannelUnreadBadges = updateChannelUnreadBadges;
  document.addEventListener("keydown", function(e) {
    if (e.key !== "Escape") return;
    if (typeof closeEmojiPicker === "function") {
      var emojiOverlay = document.querySelector(".emoji-picker-overlay.visible");
      if (emojiOverlay) {
        closeEmojiPicker();
        e.preventDefault();
        return;
      }
    }
    if (typeof closeThreadPanel === "function") {
      var threadPanel2 = document.querySelector(".thread-panel.open");
      if (threadPanel2) {
        closeThreadPanel();
        e.preventDefault();
        return;
      }
    }
    if (typeof closeSketchPanel === "function") {
      var sketchPanel = document.querySelector(".sketch-panel.open");
      if (sketchPanel) {
        closeSketchPanel();
        e.preventDefault();
        return;
      }
    }
    var generic = document.querySelector(
      ".emoji-picker-overlay.visible, .modal.open, .popup.visible, .long-press-menu"
    );
    if (generic) {
      generic.classList.remove("visible", "open");
      if (generic.classList.contains("long-press-menu")) generic.remove();
      e.preventDefault();
      return;
    }
    var styleModals = document.querySelectorAll(
      '[role="dialog"], .ch-topic-modal, .ch-export-modal, .ch-members-panel, #channel-topic-modal, #channel-export-modal, #channel-members-panel, #new-dm-modal, .dm-modal'
    );
    for (var i = 0; i < styleModals.length; i++) {
      var m = styleModals[i];
      var isVisible = m.hidden !== true && getComputedStyle(m).display !== "none" && getComputedStyle(m).visibility !== "hidden";
      if (!isVisible) continue;
      m.style.display = "none";
      m.hidden = true;
      e.preventDefault();
      return;
    }
  });
  (function() {
    var lastDmJson = "";
    var memberCache = null;
    var agentCache = null;
    function selfPrincipalKey() {
      var u = window.__orochiUserName || "";
      return u ? "human:" + u : "";
    }
    function dmDisplayName(row) {
      var others = row && row.other_participants || [];
      if (others.length === 0) return row && row.name ? row.name : "(empty DM)";
      return others.map(function(p) {
        return p.identity_name || "?";
      }).join(", ");
    }
    function dmBadgeHtml(row) {
      var others = row && row.other_participants || [];
      if (others.length === 0) return "";
      var t = others[0].type === "agent" ? "agent" : "human";
      var label = t === "agent" ? "AI" : "U";
      return '<span class="dm-principal-badge ' + t + '">' + label + "</span>";
    }
    function renderDms(rows) {
      var container = document.getElementById("dms");
      if (!container) return;
      if (!rows || rows.length === 0) {
        container.innerHTML = '<div class="dm-empty">No direct messages</div>';
      } else {
        container.innerHTML = rows.map(function(row) {
          var ch = row.name;
          var active = typeof currentChannel !== "undefined" && currentChannel === ch ? " active" : "";
          var prefs = typeof _channelPrefs !== "undefined" && _channelPrefs[ch] || {};
          var pinned = !!prefs.is_starred;
          var muted = !!prefs.is_muted;
          return '<div class="dm-item' + active + (muted ? " ch-muted" : "") + '" data-channel="' + escapeHtml(ch) + '" title="' + escapeHtml(ch) + '"><span class="ch-pin ' + (pinned ? "ch-pin-on" : "ch-pin-off") + '" data-ch="' + escapeHtml(ch) + '" title="' + (pinned ? "Unstar" : "Star (float to top)") + '">' + (pinned ? "★" : "☆") + '</span><span class="ch-watch ' + (muted ? "ch-watch-off" : "ch-watch-on") + '" data-ch="' + escapeHtml(ch) + '" title="' + (muted ? "Unmute (watch this DM)" : "Mute (stop DM notifications)") + '">👁</span>' + dmBadgeHtml(row) + escapeHtml(dmDisplayName(row)) + "</div>";
        }).join("");
        container.querySelectorAll(".dm-item").forEach(function(el) {
          var pinEl = el.querySelector(".ch-pin");
          if (pinEl && typeof _setChannelPref === "function") {
            pinEl.addEventListener("click", function(ev) {
              ev.stopPropagation();
              var chName = pinEl.getAttribute("data-ch");
              var pref = typeof _channelPrefs !== "undefined" && _channelPrefs[chName] || {};
              _setChannelPref(chName, { is_starred: !pref.is_starred });
            });
          }
          var watchEl = el.querySelector(".ch-watch");
          if (watchEl && typeof _setChannelPref === "function") {
            watchEl.addEventListener("click", function(ev) {
              ev.stopPropagation();
              var chName = watchEl.getAttribute("data-ch");
              var pref = typeof _channelPrefs !== "undefined" && _channelPrefs[chName] || {};
              _setChannelPref(chName, { is_muted: !pref.is_muted });
            });
          }
          el.addEventListener("click", function(ev) {
            if (ev.target.classList.contains("ch-pin") || ev.target.classList.contains("ch-watch"))
              return;
            var ch = el.getAttribute("data-channel");
            if (!ch) return;
            if (typeof currentChannel !== "undefined" && currentChannel === ch) {
              if (typeof setCurrentChannel === "function")
                setCurrentChannel(null);
              if (typeof loadHistory === "function") loadHistory();
            } else {
              if (typeof setCurrentChannel === "function") setCurrentChannel(ch);
              if (typeof loadChannelHistory === "function")
                loadChannelHistory(ch);
            }
            fetchDms();
            if (typeof fetchStats === "function") fetchStats();
          });
        });
      }
      var countEl = document.getElementById("sidebar-count-dms");
      if (countEl) countEl.textContent = "(" + (rows ? rows.length : 0) + ")";
    }
    async function fetchDms() {
      try {
        var res = await fetch(apiUrl("/api/dms/"), {
          credentials: "same-origin"
        });
        if (!res.ok) {
          if (res.status === 404 || res.status === 401 || res.status === 403) {
            renderDms([]);
          }
          return;
        }
        var data = await res.json();
        var rows = data && data.dms || [];
        var json = JSON.stringify(rows);
        if (json === lastDmJson) return;
        lastDmJson = json;
        renderDms(rows);
      } catch (e) {
      }
    }
    window.fetchDms = fetchDms;
    async function loadCandidates() {
      var candidates = [];
      var selfKey = selfPrincipalKey();
      var seen = {};
      try {
        if (memberCache === null) {
          var r1 = await fetch(apiUrl("/api/members/"), {
            credentials: "same-origin"
          });
          memberCache = r1.ok ? await r1.json() : [];
        }
        (memberCache || []).forEach(function(m) {
          var name = m && m.username;
          if (!name) return;
          var key, label, type;
          if (name.indexOf("agent-") === 0) {
            type = "agent";
            label = name.slice("agent-".length);
            key = "agent:" + label;
          } else {
            type = "human";
            label = name;
            key = "human:" + name;
          }
          if (key === selfKey) return;
          if (seen[key]) return;
          seen[key] = true;
          candidates.push({ key, label, type });
        });
      } catch (_) {
      }
      try {
        if (agentCache === null) {
          var r2 = await fetch(apiUrl("/api/agents"), {
            credentials: "same-origin"
          });
          agentCache = r2.ok ? await r2.json() : [];
        }
        (agentCache || []).forEach(function(a) {
          var n = a && a.name ? String(a.name).split("@")[0] : "";
          if (!n) return;
          var key = "agent:" + n;
          if (seen[key]) return;
          seen[key] = true;
          candidates.push({ key, label: n, type: "agent" });
        });
      } catch (_) {
      }
      candidates.sort(function(a, b) {
        return a.label.localeCompare(b.label);
      });
      return candidates;
    }
    function renderPickerResults(candidates, query) {
      var container = document.getElementById("new-dm-results");
      if (!container) return;
      var q = (query || "").toLowerCase();
      var filtered = candidates.filter(function(c) {
        if (!q) return true;
        return c.label.toLowerCase().indexOf(q) !== -1;
      });
      if (filtered.length === 0) {
        container.innerHTML = '<div class="dm-modal-empty">No matches</div>';
        return;
      }
      container.innerHTML = filtered.map(function(c) {
        var badge = '<span class="dm-principal-badge ' + c.type + '">' + (c.type === "agent" ? "AI" : "U") + "</span>";
        return '<div class="dm-modal-result" data-key="' + escapeHtml(c.key) + '">' + badge + escapeHtml(c.label) + "</div>";
      }).join("");
      container.querySelectorAll(".dm-modal-result").forEach(function(el) {
        el.addEventListener("click", function() {
          var key = el.getAttribute("data-key");
          if (key) openDmWith(key);
        });
      });
    }
    async function openDmWith(principalKey) {
      try {
        var headers = { "Content-Type": "application/json" };
        var token = window.__orochiCsrfToken || "";
        if (token) headers["X-CSRFToken"] = token;
        var res = await fetch(apiUrl("/api/dms/"), {
          method: "POST",
          headers,
          credentials: "same-origin",
          body: JSON.stringify({ recipient: principalKey })
        });
        if (!res.ok) {
          var t = await res.text();
          console.error("Create DM failed:", res.status, t);
          return;
        }
        var row = await res.json();
        closeModal();
        lastDmJson = "";
        await fetchDms();
        var ch = row && row.name;
        if (ch) {
          if (typeof setCurrentChannel === "function") setCurrentChannel(ch);
          if (typeof loadChannelHistory === "function") loadChannelHistory(ch);
          if (typeof fetchStats === "function") fetchStats();
        }
      } catch (e) {
        console.error("openDmWith error:", e);
      }
    }
    function openModal() {
      var modal = document.getElementById("new-dm-modal");
      if (!modal) return;
      modal.hidden = false;
      var search = document.getElementById("new-dm-search");
      if (search) {
        search.value = "";
        search.focus();
      }
      memberCache = null;
      agentCache = null;
      loadCandidates().then(function(cands) {
        renderPickerResults(cands, "");
        if (search) {
          search.oninput = function() {
            renderPickerResults(cands, search.value);
          };
        }
      });
    }
    function closeModal() {
      var modal = document.getElementById("new-dm-modal");
      if (modal) modal.hidden = true;
    }
    function wireModal() {
      var btn = document.getElementById("new-dm-btn");
      if (btn) {
        btn.addEventListener("click", function(e) {
          e.preventDefault();
          e.stopPropagation();
          openModal();
        });
      }
      var close = document.getElementById("new-dm-close");
      if (close) close.addEventListener("click", closeModal);
      var modal = document.getElementById("new-dm-modal");
      if (modal) {
        var bd = modal.querySelector(".dm-modal-backdrop");
        if (bd) bd.addEventListener("click", closeModal);
      }
      document.addEventListener("keydown", function(e) {
        if (e.key === "Escape") closeModal();
        if (e.key === "Tab" && modal && !modal.hidden) {
          var focusable = modal.querySelectorAll(
            'input, button, [tabindex]:not([tabindex="-1"])'
          );
          if (focusable.length === 0) return;
          var first = focusable[0];
          var last = focusable[focusable.length - 1];
          if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last.focus();
          } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      });
    }
    function init() {
      wireModal();
      fetchDms();
      setInterval(fetchDms, 1e4);
    }
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", init);
    } else {
      init();
    }
  })();
  (function() {
    var selector = document.getElementById("workspace-selector");
    if (!selector) return;
    var dropdown = null;
    var isOpen = false;
    function close() {
      if (dropdown && dropdown.parentNode) {
        dropdown.parentNode.removeChild(dropdown);
      }
      dropdown = null;
      isOpen = false;
    }
    function open() {
      if (isOpen) {
        close();
        return;
      }
      isOpen = true;
      dropdown = document.createElement("div");
      dropdown.className = "ws-dropdown";
      dropdown.innerHTML = '<div class="ws-dropdown-loading">Loading...</div>';
      selector.parentNode.appendChild(dropdown);
      fetch(apiUrl("/api/workspaces"), { credentials: "same-origin" }).then(function(res) {
        if (!res.ok) throw new Error("fetch failed");
        return res.json();
      }).then(function(workspaces) {
        if (!dropdown) return;
        var currentName = window.__orochiWorkspace || "";
        var html = workspaces.map(function(ws2) {
          var isActive = ws2.name === currentName;
          var icon = typeof getWorkspaceIcon === "function" ? getWorkspaceIcon(ws2.name, 18) : "";
          return '<a class="ws-dropdown-item' + (isActive ? " active" : "") + '" href="' + escapeHtml(ws2.url || "#") + '"><span class="ws-dropdown-icon">' + icon + '</span><span class="ws-dropdown-name">' + escapeHtml(ws2.name) + "</span></a>";
        }).join("");
        html += '<a class="ws-dropdown-item ws-dropdown-create" href="/workspace/new/"><span class="ws-dropdown-icon">+</span><span class="ws-dropdown-name">Create New</span></a>';
        dropdown.innerHTML = html;
      }).catch(function() {
        if (dropdown) {
          dropdown.innerHTML = '<div class="ws-dropdown-loading">Failed to load</div>';
        }
      });
    }
    selector.addEventListener("click", function(e) {
      e.stopPropagation();
      open();
    });
    document.addEventListener("click", function(e) {
      if (isOpen && dropdown && !dropdown.contains(e.target)) {
        close();
      }
    });
    document.addEventListener("keydown", function(e) {
      if (isOpen && e.key === "Escape") {
        close();
      }
    });
  })();
  var resourceData$1 = {};
  var _MACHINE_ICON_KEY = "orochi.machineIcons";
  var _machineIcons = function _loadMachineIcons() {
    try {
      var raw = localStorage.getItem(_MACHINE_ICON_KEY);
      if (!raw) return {};
      var parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (_e) {
      return {};
    }
  }();
  function _persistMachineIcons() {
    try {
      localStorage.setItem(_MACHINE_ICON_KEY, JSON.stringify(_machineIcons));
    } catch (_e) {
    }
  }
  function setMachineIcon(name, emoji) {
    if (emoji) _machineIcons[name] = emoji;
    else delete _machineIcons[name];
    _persistMachineIcons();
    if (typeof renderResources === "function") renderResources();
  }
  window.setMachineIcon = setMachineIcon;
  var _machineTooltipEl = null;
  function _machineTooltip() {
    if (_machineTooltipEl) return _machineTooltipEl;
    var el = document.createElement("div");
    el.className = "machine-hover-tooltip";
    el.setAttribute("role", "tooltip");
    el.style.display = "none";
    document.body.appendChild(el);
    _machineTooltipEl = el;
    return el;
  }
  function _fmtMetricPct(p) {
    if (!p || p <= 0) return { text: "—", cls: "mh-tip-unknown" };
    var rounded = Math.round(p);
    var cls = rounded > 80 ? "mh-tip-crit" : rounded > 60 ? "mh-tip-warn" : "mh-tip-ok";
    return { text: rounded + "%", cls };
  }
  function _machineMetricsHtml(host) {
    var d = resourceData$1[host];
    if (!d) return "";
    var cpu = d.cpu && d.cpu.percent || 0;
    var ram = d.memory && d.memory.percent || 0;
    var gpu = 0;
    var vram = 0;
    if (d.gpu && d.gpu.length > 0) {
      var g0 = d.gpu[0];
      gpu = g0.utilization_percent || 0;
      if (g0.memory_percent) {
        vram = g0.memory_percent;
      } else if (g0.memory_total_mb) {
        vram = (g0.memory_used_mb || 0) / g0.memory_total_mb * 100;
      }
    }
    var disk = 0;
    if (d.disk) {
      var dk = Object.keys(d.disk)[0];
      if (dk) disk = d.disk[dk].percent || 0;
    }
    function row(label, value) {
      var m = _fmtMetricPct(value);
      return '<div class="mh-tip-row"><span class="mh-tip-label">' + label + '</span><span class="mh-tip-val ' + m.cls + '">' + m.text + "</span></div>";
    }
    return '<div class="mh-tip-host">' + escapeHtml(host) + "</div>" + row("CPU", cpu) + row("RAM", ram) + row("GPU", gpu) + row("VRAM", vram) + row("Disk", disk);
  }
  function _positionMachineTooltip(el, evt) {
    var pad = 12;
    var rect = el.getBoundingClientRect();
    var vw = window.innerWidth;
    var vh = window.innerHeight;
    var x = evt.clientX + pad;
    var y = evt.clientY + pad;
    if (x + rect.width + pad > vw) x = evt.clientX - rect.width - pad;
    if (y + rect.height + pad > vh) y = evt.clientY - rect.height - pad;
    if (x < pad) x = pad;
    if (y < pad) y = pad;
    el.style.left = x + "px";
    el.style.top = y + "px";
  }
  function showMachineTooltip$1(host, evt) {
    if (!host) return;
    var html = _machineMetricsHtml(host);
    if (!html) return;
    var el = _machineTooltip();
    el.innerHTML = html;
    el.style.display = "block";
    _positionMachineTooltip(el, evt);
  }
  function moveMachineTooltip$1(evt) {
    if (!_machineTooltipEl || _machineTooltipEl.style.display === "none") return;
    _positionMachineTooltip(_machineTooltipEl, evt);
  }
  function hideMachineTooltip$1() {
    if (_machineTooltipEl) _machineTooltipEl.style.display = "none";
  }
  window.showMachineTooltip = showMachineTooltip$1;
  window.moveMachineTooltip = moveMachineTooltip$1;
  window.hideMachineTooltip = hideMachineTooltip$1;
  var _machinesView = "cards";
  try {
    var _persistedMV = localStorage.getItem("orochi.machinesView");
    if (_persistedMV === "viz" || _persistedMV === "cards")
      _machinesView = _persistedMV;
  } catch (_e) {
  }
  var todoActiveGroups = /* @__PURE__ */ new Set(["all"]);
  function _syncTodoBtnState() {
    document.querySelectorAll(".todo-state-btn").forEach(function(b) {
      var g = b.getAttribute("data-group");
      b.classList.toggle("active", todoActiveGroups.has(g));
    });
  }
  function _updateTodoBtnCounts(issues) {
    var counts = {
      all: 0,
      "high-priority": 0,
      "medium-priority": 0,
      "low-priority": 0,
      future: 0,
      blocker: 0,
      closed: 0
    };
    (issues || []).forEach(function(issue) {
      counts.all += 1;
      if (issue.state === "closed") {
        counts.closed += 1;
        if (_hasBlockerLabel(issue)) counts.blocker += 1;
        return;
      }
      if (_hasBlockerLabel(issue)) counts.blocker += 1;
      var key = classifyIssue(issue);
      if (counts[key] != null) counts[key] += 1;
      else if (key === "_uncategorized") counts.future += 1;
    });
    var LABELS = {
      all: "All",
      "high-priority": "High",
      "medium-priority": "Medium",
      "low-priority": "Low",
      future: "Future",
      blocker: "Blocker",
      closed: "Closed"
    };
    document.querySelectorAll(".todo-state-btn").forEach(function(b) {
      var g = b.getAttribute("data-group");
      var label = LABELS[g] || g;
      var n = counts[g];
      b.innerHTML = escapeHtml(label) + (n != null ? ' <span class="todo-state-count">' + n + "</span>" : "");
    });
  }
  var _TODO_VIEW_KEY = "orochi.todoViewMode";
  function _todoViewMode() {
    try {
      var v = localStorage.getItem(_TODO_VIEW_KEY);
      return v === "viz" ? "viz" : "list";
    } catch (_) {
      return "list";
    }
  }
  function _applyTodoViewMode(mode) {
    var isViz = mode === "viz";
    var viz = document.getElementById("viz-content");
    var stats = document.getElementById("todo-stats");
    var grid = document.getElementById("todo-grid");
    var pills = document.querySelector("#todo-view .todo-state-filter");
    if (viz) viz.style.display = isViz ? "" : "none";
    if (stats) stats.style.display = isViz ? "none" : "";
    if (grid) grid.style.display = isViz ? "none" : "";
    if (pills) pills.style.display = isViz ? "none" : "";
    document.querySelectorAll("#todo-view [data-todo-view]").forEach(function(btn) {
      btn.classList.toggle(
        "active",
        btn.getAttribute("data-todo-view") === mode
      );
    });
    if (isViz && typeof renderVizTab === "function") renderVizTab();
  }
  function _wireTodoViewSwitch() {
    document.querySelectorAll("#todo-view [data-todo-view]").forEach(function(btn) {
      btn.addEventListener("click", function() {
        var mode = btn.getAttribute("data-todo-view") || "list";
        try {
          localStorage.setItem(_TODO_VIEW_KEY, mode);
        } catch (_) {
        }
        _applyTodoViewMode(mode);
      });
    });
    _applyTodoViewMode(_todoViewMode());
  }
  document.addEventListener("DOMContentLoaded", function() {
    _wireTodoViewSwitch();
    if (typeof renderVizTab === "function") renderVizTab();
    document.querySelectorAll(".todo-state-btn").forEach(function(btn) {
      btn.addEventListener("click", function(e) {
        var g = btn.getAttribute("data-group");
        var multi = e.ctrlKey || e.metaKey;
        if (multi) {
          if (g === "all") {
            todoActiveGroups = /* @__PURE__ */ new Set(["all"]);
          } else {
            todoActiveGroups.delete("all");
            if (todoActiveGroups.has(g)) {
              todoActiveGroups.delete(g);
              if (todoActiveGroups.size === 0) todoActiveGroups.add("all");
            } else {
              todoActiveGroups.add(g);
            }
          }
        } else {
          todoActiveGroups = /* @__PURE__ */ new Set([g]);
        }
        _syncTodoBtnState();
        fetchTodoList$1();
      });
    });
  });
  function _todoBackendState() {
    if (todoActiveGroups.has("all") || todoActiveGroups.has("closed") || todoActiveGroups.has("blocker")) {
      return "all";
    }
    return "open";
  }
  var _todoCache = { all: null, open: null };
  var _todoCacheTs = { all: 0, open: 0 };
  var _TODO_CACHE_TTL_MS = 60 * 1e3;
  function _hasBlockerLabel(issue) {
    return (issue.labels || []).some(function(l) {
      return (l.name || "").toLowerCase() === "blocker";
    });
  }
  function _passesGroupFilter(issue) {
    if (todoActiveGroups.has("all")) return true;
    if (todoActiveGroups.has("blocker") && _hasBlockerLabel(issue)) return true;
    if (issue.state === "closed") {
      return todoActiveGroups.has("closed");
    }
    var key = classifyIssue(issue);
    if (todoActiveGroups.has(key)) return true;
    if (key === "_uncategorized" && todoActiveGroups.has("future")) return true;
    return false;
  }
  function _populateIssueMap(issues) {
    _todoIssuesByNumber = {};
    (issues || []).forEach(function(i) {
      _todoIssuesByNumber[i.number] = i;
    });
  }
  function _updateLastFetchedLabel(ts) {
    var el = document.getElementById("todo-last-updated");
    if (!el) return;
    if (!ts) {
      el.textContent = "";
      return;
    }
    var d = new Date(ts);
    var hh = String(d.getHours()).padStart(2, "0");
    var mm = String(d.getMinutes()).padStart(2, "0");
    var ss = String(d.getSeconds()).padStart(2, "0");
    el.textContent = "Last updated: " + hh + ":" + mm + ":" + ss;
    el.setAttribute("data-ts", String(ts));
  }
  function _renderTodoFromCache(issues) {
    _populateIssueMap(issues);
    _updateTodoBtnCounts(issues || []);
    var msgInput2 = document.getElementById("msg-input");
    var inputHasFocus = msgInput2 && document.activeElement === msgInput2;
    var savedStart = inputHasFocus ? msgInput2.selectionStart : 0;
    var savedEnd = inputHasFocus ? msgInput2.selectionEnd : 0;
    var container = document.getElementById("todo-grid");
    if (!issues || issues.length === 0) {
      container.innerHTML = '<p class="empty-notice">No issues</p>';
      if (inputHasFocus && document.activeElement !== msgInput2) {
        msgInput2.focus();
        try {
          msgInput2.setSelectionRange(savedStart, savedEnd);
        } catch (_) {
        }
      }
      return;
    }
    issues = issues.filter(_passesGroupFilter);
    if (issues.length === 0) {
      container.innerHTML = '<p class="empty-notice">No issues match the current filter</p>';
      if (inputHasFocus && document.activeElement !== msgInput2) {
        msgInput2.focus();
        try {
          msgInput2.setSelectionRange(savedStart, savedEnd);
        } catch (_) {
        }
      }
      return;
    }
    var grouped = {};
    PRIORITY_GROUPS.forEach(function(g) {
      grouped[g.key] = [];
    });
    var closedGroup = [];
    issues.forEach(function(issue) {
      if (issue.state === "closed") {
        closedGroup.push(issue);
      } else {
        var key = classifyIssue(issue);
        grouped[key].push(issue);
      }
    });
    PRIORITY_GROUPS.forEach(function(g) {
      grouped[g.key].sort(sortByUpdated);
    });
    closedGroup.sort(sortByUpdated);
    var html = PRIORITY_GROUPS.map(function(g) {
      return buildGroupHtml(g, grouped[g.key]);
    }).join("");
    if (closedGroup.length > 0) {
      html += buildGroupHtml(
        { key: "closed", label: "Closed", color: "#555" },
        closedGroup
      );
    }
    container.innerHTML = html;
    attachTodoEvents(container);
    _backgroundFillDetails(container);
    _updateLastFetchedLabel(_todoCacheTs.all || _todoCacheTs.open || Date.now());
    if (typeof runFilter === "function") runFilter();
    if (inputHasFocus && document.activeElement !== msgInput2) {
      msgInput2.focus();
      try {
        msgInput2.setSelectionRange(savedStart, savedEnd);
      } catch (_) {
      }
    }
  }
  async function fetchTodoList$1(forceRefresh) {
    var msgInput2 = document.getElementById("msg-input");
    var inputHasFocus = msgInput2 && document.activeElement === msgInput2;
    var savedStart = inputHasFocus ? msgInput2.selectionStart : 0;
    var savedEnd = inputHasFocus ? msgInput2.selectionEnd : 0;
    var _restoreFocus = function() {
      if (inputHasFocus && document.activeElement !== msgInput2) {
        msgInput2.focus();
        try {
          msgInput2.setSelectionRange(savedStart, savedEnd);
        } catch (_) {
        }
      }
    };
    var state = _todoBackendState();
    var now = Date.now();
    {
      if (_todoCache.all && now - _todoCacheTs.all < _TODO_CACHE_TTL_MS) {
        _renderTodoFromCache(_todoCache.all);
        return;
      }
      if (state === "open" && _todoCache.open && now - _todoCacheTs.open < _TODO_CACHE_TTL_MS) {
        _renderTodoFromCache(_todoCache.open);
        return;
      }
    }
    try {
      var res = await fetch(
        "/api/github/issues?state=" + encodeURIComponent(state)
      );
      if (!res.ok) {
        console.error("Failed to fetch TODO list:", res.status);
        var errBody = {};
        try {
          errBody = await res.json();
        } catch (_) {
        }
        var msg = "Failed to load issues (HTTP " + res.status + ")";
        if (errBody.code === "missing_token") {
          msg = "Configure GITHUB_TOKEN in Docker environment to enable TODO list";
        } else if (errBody.error) {
          msg = errBody.error;
        }
        document.getElementById("todo-grid").innerHTML = '<p class="empty-notice">' + msg + "</p>";
        _restoreFocus();
        return;
      }
      var issues = await res.json();
      _todoCache[state] = issues;
      _todoCacheTs[state] = Date.now();
      _populateIssueMap(issues);
      _updateLastFetchedLabel(_todoCacheTs[state]);
      var container = document.getElementById("todo-grid");
      if (!issues || issues.length === 0) {
        container.innerHTML = '<p class="empty-notice">No issues</p>';
        _restoreFocus();
        return;
      }
      issues = issues.filter(_passesGroupFilter);
      if (issues.length === 0) {
        container.innerHTML = '<p class="empty-notice">No issues match the current filter</p>';
        _restoreFocus();
        return;
      }
      var grouped = {};
      PRIORITY_GROUPS.forEach(function(g) {
        grouped[g.key] = [];
      });
      var closedGroup = [];
      issues.forEach(function(issue) {
        if (issue.state === "closed") {
          closedGroup.push(issue);
        } else {
          var key = classifyIssue(issue);
          grouped[key].push(issue);
        }
      });
      PRIORITY_GROUPS.forEach(function(g) {
        grouped[g.key].sort(sortByUpdated);
      });
      closedGroup.sort(sortByUpdated);
      var html = PRIORITY_GROUPS.map(function(g) {
        return buildGroupHtml(g, grouped[g.key]);
      }).join("");
      if (closedGroup.length > 0) {
        html += buildGroupHtml(
          { key: "closed", label: "Closed", color: "#555" },
          closedGroup
        );
      }
      container.innerHTML = html;
      attachTodoEvents(container);
      _updateTodoBtnCounts(_todoCache[state] || []);
      _backgroundFillDetails(container);
      _restoreFocus();
    } catch (e) {
      console.error("TODO list fetch error:", e);
    }
  }
  var _todoStatsRefreshTimer = null;
  var _TODO_STATS_REFRESH_MS = 60 * 1e3;
  function _shortRepo(repo) {
    if (!repo) return "";
    var slash = repo.lastIndexOf("/");
    return slash >= 0 ? repo.substring(slash + 1) : repo;
  }
  function _renderTodoStatsTotals(totals) {
    var openN = totals && totals.open || 0;
    var closedN = totals && totals.closed || 0;
    var total = openN + closedN;
    return '<div class="todo-stats-cards"><div class="todo-stats-card"><div class="todo-stats-val">' + openN + '</div><div class="todo-stats-lbl">Open</div></div><div class="todo-stats-card"><div class="todo-stats-val">' + closedN + '</div><div class="todo-stats-lbl">Closed</div></div><div class="todo-stats-card"><div class="todo-stats-val">' + total + '</div><div class="todo-stats-lbl">Total</div></div></div>';
  }
  function _renderTodoStatsBurndown(daily) {
    if (!daily || daily.length === 0) {
      return '<p class="empty-notice">No velocity data</p>';
    }
    var W = 720, H = 180;
    var padL = 32, padR = 12, padT = 12, padB = 24;
    var innerW = W - padL - padR;
    var innerH = H - padT - padB;
    var n = daily.length;
    var maxY = 1;
    for (var i = 0; i < n; i++) {
      if (daily[i].opened > maxY) maxY = daily[i].opened;
      if (daily[i].closed > maxY) maxY = daily[i].closed;
    }
    var step = n > 1 ? innerW / (n - 1) : innerW;
    function pt(i2, v) {
      var x = padL + i2 * step;
      var y = padT + innerH - v / maxY * innerH;
      return x.toFixed(1) + "," + y.toFixed(1);
    }
    var openedPath = daily.map(function(d, i2) {
      return pt(i2, d.opened);
    }).join(" ");
    var closedPath = daily.map(function(d, i2) {
      return pt(i2, d.closed);
    }).join(" ");
    function yLabel(v) {
      var y = padT + innerH - v / maxY * innerH;
      return '<text class="todo-chart-axis" x="' + (padL - 4) + '" y="' + (y + 3) + '" text-anchor="end">' + v + '</text><line class="todo-chart-grid" x1="' + padL + '" x2="' + (W - padR) + '" y1="' + y + '" y2="' + y + '"/>';
    }
    var yLabels = yLabel(0) + yLabel(Math.round(maxY / 2)) + yLabel(maxY);
    function xLabel(i2) {
      if (i2 < 0 || i2 >= n) return "";
      var x = padL + i2 * step;
      var label = (daily[i2].date || "").substring(5);
      return '<text class="todo-chart-axis" x="' + x + '" y="' + (H - 6) + '" text-anchor="middle">' + label + "</text>";
    }
    var xLabels = xLabel(0) + xLabel(Math.floor(n / 2)) + xLabel(n - 1);
    return '<div class="todo-stats-section"><div class="todo-stats-h">Daily velocity (14d)</div><div class="todo-chart-legend"><span class="todo-chart-swatch todo-chart-opened"></span>Opened <span class="todo-chart-swatch todo-chart-closed"></span>Closed</div><svg class="todo-chart" viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none" role="img" aria-label="Daily open/close velocity">' + yLabels + xLabels + '<polyline class="todo-chart-line todo-chart-opened-line" points="' + openedPath + '"/><polyline class="todo-chart-line todo-chart-closed-line" points="' + closedPath + '"/></svg></div>';
  }
  function _renderTodoStatsLabels(labels) {
    if (!labels || labels.length === 0) {
      return '<div class="todo-stats-section"><div class="todo-stats-h">Labels</div><p class="empty-notice">No labels</p></div>';
    }
    var maxCount = labels[0].open_count || 1;
    var rows = labels.map(function(l) {
      var pct = Math.max(2, Math.round(l.open_count / maxCount * 100));
      return '<li class="todo-label-row"><span class="todo-label-name">' + escapeHtml(l.label) + '</span><span class="todo-label-bar"><span class="todo-label-fill" style="width:' + pct + '%"></span></span><span class="todo-label-count">' + l.open_count + "</span></li>";
    }).join("");
    return '<div class="todo-stats-section"><div class="todo-stats-h">Labels (open, top ' + labels.length + ')</div><ul class="todo-label-list">' + rows + "</ul></div>";
  }
  function _renderTodoStatsByRepo(rows) {
    if (!rows || rows.length === 0) {
      return "";
    }
    var body = rows.map(function(r) {
      return "<tr><td>" + escapeHtml(_shortRepo(r.repo)) + '</td><td class="todo-repo-num">' + (r.open || 0) + '</td><td class="todo-repo-num">' + (r.closed || 0) + "</td></tr>";
    }).join("");
    return '<div class="todo-stats-section"><div class="todo-stats-h">By repo</div><table class="todo-repo-table"><thead><tr><th>Repo</th><th>Open</th><th>Closed</th></tr></thead><tbody>' + body + "</tbody></table></div>";
  }
  function _renderTodoStatsStarvation(rows, threshold) {
    if (!rows || rows.length === 0) {
      return '<div class="todo-stats-section"><div class="todo-stats-h">Starvation</div><p class="empty-notice">Nothing stale — good job</p></div>';
    }
    var body = rows.map(function(r) {
      var labels = (r.labels || []).map(function(n) {
        return '<span class="todo-label">' + escapeHtml(n) + "</span>";
      }).join("");
      return "<tr><td>" + escapeHtml(_shortRepo(r.repo)) + '</td><td class="todo-repo-num">#' + escapeHtml(String(r.number)) + '</td><td><a href="' + escapeHtml(r.url || "#") + '" target="_blank" rel="noopener">' + escapeHtml(r.title || "") + '</a></td><td class="todo-repo-num">' + (r.age_days || 0) + 'd</td><td><div class="todo-labels">' + labels + "</div></td></tr>";
    }).join("");
    return '<div class="todo-stats-section"><div class="todo-stats-h">Starvation (open &gt; ' + (threshold || 7) + "d, top " + rows.length + ')</div><table class="todo-starve-table"><thead><tr><th>Repo</th><th>#</th><th>Title</th><th>Age</th><th>Labels</th></tr></thead><tbody>' + body + "</tbody></table></div>";
  }
  function _renderTodoStats(data) {
    var container = document.getElementById("todo-stats");
    if (!container) return;
    if (!data) {
      container.innerHTML = '<p class="empty-notice">No TODO stats available</p>';
      return;
    }
    var html = _renderTodoStatsTotals(data.totals) + _renderTodoStatsBurndown(data.daily_velocity) + _renderTodoStatsLabels(data.label_breakdown) + _renderTodoStatsByRepo(data.by_repo) + _renderTodoStatsStarvation(data.starvation, data.starvation_threshold_days);
    container.innerHTML = html;
  }
  async function fetchTodoStats(force) {
    var container = document.getElementById("todo-stats");
    if (!container) return;
    if (!container.innerHTML) {
      container.innerHTML = '<p class="empty-notice">Loading TODO stats...</p>';
    }
    try {
      var url = "/api/todo/stats/" + (force ? "?refresh=1" : "");
      var res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) {
        container.innerHTML = '<p class="empty-notice">Failed to load TODO stats (HTTP ' + res.status + ")</p>";
        return;
      }
      var data = await res.json();
      _renderTodoStats(data);
    } catch (e) {
      console.error("TODO stats fetch error:", e);
      container.innerHTML = '<p class="empty-notice">Failed to load TODO stats</p>';
    }
  }
  function startTodoStatsAutoRefresh() {
    if (_todoStatsRefreshTimer) return;
    _todoStatsRefreshTimer = setInterval(fetchTodoStats, _TODO_STATS_REFRESH_MS);
  }
  document.addEventListener("DOMContentLoaded", function() {
    var btn = document.querySelector('[data-tab="todo"]');
    if (btn) {
      btn.addEventListener("click", function() {
        fetchTodoStats();
        startTodoStatsAutoRefresh();
      });
    }
    try {
      var last = localStorage.getItem("orochi_active_tab");
      if (last === "todo") {
        fetchTodoStats();
        startTodoStatsAutoRefresh();
      }
    } catch (_) {
    }
  });
  (function(global) {
    var PDFJS_VERSION = "3.11.174";
    var CDN_BASE = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/" + PDFJS_VERSION;
    var LIB_URL = CDN_BASE + "/pdf.min.js";
    var WORKER_URL = CDN_BASE + "/pdf.worker.min.js";
    var loadPromise = null;
    var cache = /* @__PURE__ */ new Map();
    function loadLib() {
      if (loadPromise) return loadPromise;
      if (global.pdfjsLib) {
        try {
          global.pdfjsLib.GlobalWorkerOptions.workerSrc = WORKER_URL;
        } catch (_) {
        }
        loadPromise = Promise.resolve(global.pdfjsLib);
        return loadPromise;
      }
      loadPromise = new Promise(function(resolve, reject) {
        var s = document.createElement("script");
        s.src = LIB_URL;
        s.async = true;
        s.onload = function() {
          if (!global.pdfjsLib) {
            reject(new Error("pdfjsLib missing after load"));
            return;
          }
          try {
            global.pdfjsLib.GlobalWorkerOptions.workerSrc = WORKER_URL;
          } catch (_) {
          }
          resolve(global.pdfjsLib);
        };
        s.onerror = function() {
          reject(new Error("failed to load pdf.js from " + LIB_URL));
        };
        document.head.appendChild(s);
      });
      return loadPromise;
    }
    function render(pdfUrl, opts) {
      opts = opts || {};
      var maxSide = opts.maxSide || 160;
      if (cache.has(pdfUrl)) return cache.get(pdfUrl);
      var p = loadLib().then(function(pdfjsLib) {
        return pdfjsLib.getDocument({ url: pdfUrl, disableRange: false }).promise;
      }).then(function(pdf) {
        return pdf.getPage(1);
      }).then(function(page) {
        var baseViewport = page.getViewport({ scale: 1 });
        var scale = maxSide / Math.max(baseViewport.width, baseViewport.height);
        var viewport = page.getViewport({ scale });
        var canvas = document.createElement("canvas");
        canvas.width = Math.ceil(viewport.width);
        canvas.height = Math.ceil(viewport.height);
        var ctx = canvas.getContext("2d");
        return page.render({ canvasContext: ctx, viewport }).promise.then(function() {
          return canvas.toDataURL("image/png");
        });
      }).catch(function(err) {
        cache.delete(pdfUrl);
        throw err;
      });
      cache.set(pdfUrl, p);
      return p;
    }
    function hydrate(el, pdfUrl, opts) {
      if (!el || !pdfUrl) return;
      if (el.getAttribute("data-pdf-thumb") === "done") return;
      if (el.getAttribute("data-pdf-thumb") === "pending") return;
      el.setAttribute("data-pdf-thumb", "pending");
      render(pdfUrl, opts).then(function(dataUrl) {
        if (!el.isConnected) return;
        el.setAttribute("data-pdf-thumb", "done");
        el.innerHTML = "";
        var img = document.createElement("img");
        img.src = dataUrl;
        img.alt = "PDF preview";
        img.className = "pdf-thumb-img";
        img.style.maxWidth = "100%";
        img.style.maxHeight = "100%";
        img.style.objectFit = "contain";
        img.style.display = "block";
        el.appendChild(img);
      }).catch(function(err) {
        if (!el.isConnected) return;
        el.setAttribute("data-pdf-thumb", "error");
        if (global.console && console.warn) {
          console.warn("pdf-thumb failed for", pdfUrl, err);
        }
      });
    }
    function hydrateAll(root) {
      root = root || document;
      var nodes = root.querySelectorAll(
        "[data-pdf-thumb-url]:not([data-pdf-thumb='done']):not([data-pdf-thumb='pending'])"
      );
      nodes.forEach(function(n) {
        var url = n.getAttribute("data-pdf-thumb-url");
        if (url) hydrate(n, url);
      });
    }
    global.pdfThumb = {
      render,
      hydrate,
      hydrateAll
    };
  })(window);
  function _pulseSidebarRow(channel, variant) {
    if (!channel) return;
    var safe = channel.replace(/"/g, '\\"');
    var rows = document.querySelectorAll(
      '.dm-item[data-channel="' + safe + '"], .channel-item[data-channel="' + safe + '"]'
    );
    var cls = variant === "mention" ? "ch-pulse-mention" : "dm-pulse";
    rows.forEach(function(row) {
      row.classList.remove(cls);
      void row.offsetWidth;
      row.classList.add(cls);
      var done = function() {
        row.classList.remove(cls);
        row.removeEventListener("animationend", done);
      };
      row.addEventListener("animationend", done);
      if (variant === "mention") {
        var badge = row.querySelector(".unread-badge");
        if (badge) {
          badge.classList.remove("badge-shake");
          void badge.offsetWidth;
          badge.classList.add("badge-shake");
          var badgeDone = function() {
            badge.classList.remove("badge-shake");
            badge.removeEventListener("animationend", badgeDone);
          };
          badge.addEventListener("animationend", badgeDone);
        }
      }
    });
  }
  window._pulseSidebarRow = _pulseSidebarRow;
  var _chatFilterQuery = "";
  var _chatFilterDebounce = null;
  function _chatFilterApplyNow(q) {
    _chatFilterQuery = (q || "").trim().toLowerCase();
    var container = document.getElementById("messages");
    if (!container) return;
    var rows = container.querySelectorAll(".message");
    if (!_chatFilterQuery) {
      rows.forEach(function(el2) {
        el2.classList.remove("chat-filter-miss");
        el2.classList.remove("chat-filter-hit");
      });
      return;
    }
    for (var i = 0; i < rows.length; i++) {
      var el = rows[i];
      var txt = (el.textContent || "").toLowerCase();
      if (txt.indexOf(_chatFilterQuery) !== -1) {
        el.classList.add("chat-filter-hit");
        el.classList.remove("chat-filter-miss");
      } else {
        el.classList.add("chat-filter-miss");
        el.classList.remove("chat-filter-hit");
      }
    }
  }
  function chatFilterApply(q) {
    if (_chatFilterDebounce) clearTimeout(_chatFilterDebounce);
    _chatFilterDebounce = setTimeout(function() {
      _chatFilterDebounce = null;
      _chatFilterApplyNow(q);
    }, 100);
  }
  function chatFilterReset$1() {
    if (_chatFilterDebounce) {
      clearTimeout(_chatFilterDebounce);
      _chatFilterDebounce = null;
    }
    _chatFilterQuery = "";
    var inp = document.getElementById("chat-filter-input");
    if (inp) inp.value = "";
    _chatFilterApplyNow("");
  }
  window.chatFilterApply = chatFilterApply;
  window.chatFilterReset = chatFilterReset$1;
  var _voiceDeferQueue = [];
  window._flushVoiceQueue = function() {
    var queued = _voiceDeferQueue.splice(0);
    queued.forEach(function(msg) {
      appendMessage(msg);
    });
  };
  var issueTitleCache = {};
  var issueTitleInflight = {};
  function _hydrateIssueLink(a, title) {
    if (!title || a.dataset.hinted) return;
    var msgInput2 = document.getElementById("msg-input");
    var inputHasFocus = msgInput2 && document.activeElement === msgInput2;
    var savedStart = inputHasFocus ? msgInput2.selectionStart : 0;
    var savedEnd = inputHasFocus ? msgInput2.selectionEnd : 0;
    var label = a.getAttribute("data-issue-label") || a.textContent;
    a.title = label + " " + title;
    a.innerHTML = escapeHtml(label) + ' <span class="issue-link-title">(' + escapeHtml(title) + ")</span>";
    a.dataset.hinted = "1";
    if (inputHasFocus && document.activeElement !== msgInput2) {
      msgInput2.focus();
      try {
        msgInput2.setSelectionRange(savedStart, savedEnd);
      } catch (_) {
      }
    }
  }
  function _fetchCrossRepoTitle(repo, num, cb) {
    var key = repo + "#" + num;
    if (issueTitleCache[key] !== void 0) {
      cb(issueTitleCache[key] || null);
      return;
    }
    if (issueTitleInflight[key]) return;
    issueTitleInflight[key] = true;
    var url = apiUrl(
      "/api/github/issue-title?repo=" + encodeURIComponent(repo) + "&number=" + encodeURIComponent(num)
    );
    fetch(url, { credentials: "same-origin" }).then(function(r) {
      return r.ok ? r.json() : null;
    }).then(function(data) {
      delete issueTitleInflight[key];
      var title = data && data.title || "";
      issueTitleCache[key] = title;
      if (title) cb(title);
    }).catch(function() {
      delete issueTitleInflight[key];
    });
  }
  function applyIssueTitleHints(scope) {
    var root = document;
    root.querySelectorAll(".issue-link").forEach(function(a) {
      if (a.dataset.hinted) return;
      var repo = a.getAttribute("data-issue-repo");
      var num = a.getAttribute("data-issue-num");
      if (!num) {
        var m = a.textContent.match(/#(\d+)/);
        if (!m) return;
        num = m[1];
        a.setAttribute("data-issue-num", num);
      }
      if (repo) {
        var key = repo + "#" + num;
        var cached = issueTitleCache[key];
        if (cached) {
          _hydrateIssueLink(a, cached);
        } else if (cached === void 0) {
          _fetchCrossRepoTitle(repo, num, function(title2) {
            _hydrateIssueLink(a, title2);
          });
        }
      } else {
        var title = issueTitleCache[num];
        if (title) _hydrateIssueLink(a, title);
      }
    });
  }
  async function refreshIssueTitleCache() {
    try {
      var res = await fetch(apiUrl("/api/github/issues"), {
        credentials: "same-origin"
      });
      if (!res.ok) return;
      var issues = await res.json();
      if (Array.isArray(issues)) {
        issues.forEach(function(i) {
          if (i && i.number && i.title)
            issueTitleCache[String(i.number)] = i.title;
        });
        applyIssueTitleHints();
      }
    } catch (e) {
    }
  }
  refreshIssueTitleCache();
  setInterval(refreshIssueTitleCache, 12e4);
  function sendMessage() {
    var input = document.getElementById("msg-input");
    var channel = currentChannel || typeof lastActiveChannel !== "undefined" && lastActiveChannel || "#general";
    var text = input.value.trim();
    var attachments = typeof getPendingAttachments === "function" ? getPendingAttachments() : [];
    if (!text && attachments.length === 0) return;
    var payload = { channel, content: text };
    if (attachments.length > 0) payload.attachments = attachments;
    if (wsConnected && ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "message", payload }));
    } else {
      sendOrochiMessage({
        type: "message",
        sender: userName,
        payload
      });
    }
    input.value = "";
    input.style.height = "auto";
    var msgContainer = document.getElementById("messages");
    if (msgContainer) {
      msgContainer.scrollTop = msgContainer.scrollHeight;
    }
    if (typeof clearPendingAttachments === "function") {
      clearPendingAttachments();
    }
    try {
      sessionStorage.removeItem(
        "orochi-draft-" + (currentChannel || "__default__")
      );
    } catch (_) {
    }
    if (typeof window.voiceInputResetAfterSend === "function") {
      try {
        window.voiceInputResetAfterSend();
      } catch (_) {
      }
    }
  }
  function _draftKey() {
    try {
      return "orochi-draft-" + (currentChannel || "__default__");
    } catch (_) {
      return "orochi-draft-__default__";
    }
  }
  function _saveDraft(value) {
    try {
      if (value && value.length > 0) {
        sessionStorage.setItem(_draftKey(), value);
      } else {
        sessionStorage.removeItem(_draftKey());
      }
    } catch (_) {
    }
  }
  function restoreDraftForCurrentChannel$1() {
    try {
      var input = document.getElementById("msg-input");
      if (!input) return;
      var saved = sessionStorage.getItem(_draftKey());
      if (saved && !input.value) {
        input.value = saved;
        input.style.height = "auto";
        input.style.height = Math.min(input.scrollHeight, 200) + "px";
      }
    } catch (_) {
    }
  }
  window.restoreDraftForCurrentChannel = restoreDraftForCurrentChannel$1;
  document.getElementById("msg-input").addEventListener("input", function() {
    this.style.height = "auto";
    this.style.height = Math.min(this.scrollHeight, 200) + "px";
    _saveDraft(this.value);
  });
  restoreDraftForCurrentChannel$1();
  (function() {
    var input = document.getElementById("msg-input");
    if (!input) return;
    function _logBlur(label, e) {
      try {
        var arr = JSON.parse(sessionStorage.getItem("orochi-blurlog") || "[]");
        var rt = e && e.relatedTarget;
        arr.push({
          t: (/* @__PURE__ */ new Date()).toISOString(),
          label,
          relatedTarget: rt ? (rt.tagName || "?") + "#" + (rt.id || "") + "." + (rt.className || "") : null,
          activeAfter: document.activeElement ? document.activeElement.tagName + "#" + (document.activeElement.id || "") : null,
          stack: new Error().stack ? new Error().stack.split("\n").slice(2, 8).join(" | ") : null
        });
        while (arr.length > 50) arr.shift();
        sessionStorage.setItem("orochi-blurlog", JSON.stringify(arr));
      } catch (_) {
      }
    }
    input.addEventListener("blur", function(e) {
      _logBlur("sync-blur", e);
      requestAnimationFrame(function() {
        if (document.activeElement !== input) {
          _logBlur("post-rAF-still-blurred", e);
        }
      });
    });
    window.getBlurLog = function() {
      try {
        return JSON.parse(sessionStorage.getItem("orochi-blurlog") || "[]");
      } catch (_) {
        return [];
      }
    };
  })();
  document.addEventListener("click", function(e) {
    var btn = e.target.closest(".msg-fold-btn");
    if (!btn) return;
    e.preventDefault();
    var parent = btn.parentElement;
    if (!parent) return;
    var previewEl = parent.querySelector(".msg-preview");
    var fullEl = parent.querySelector(".msg-full");
    if (!previewEl || !fullEl) return;
    var extra = btn.getAttribute("data-extra") || "?";
    if (fullEl.style.display === "none") {
      fullEl.style.display = "block";
      previewEl.style.display = "none";
      btn.textContent = "Show less";
      _renderMermaidIn(fullEl);
    } else {
      fullEl.style.display = "none";
      previewEl.style.display = "block";
      btn.textContent = "Show more (" + extra + " more lines)";
    }
  });
  document.addEventListener("click", function(e) {
    var btn = e.target.closest(".mermaid-toggle");
    if (!btn) return;
    e.preventDefault();
    var container = btn.closest(".mermaid-container");
    if (!container) return;
    var rawEl = container.querySelector(".mermaid-raw");
    if (!rawEl) return;
    var isHidden = rawEl.style.display === "none" || rawEl.style.display === "";
    rawEl.style.display = isHidden ? "block" : "none";
    btn.textContent = isHidden ? "Hide raw" : "Show raw";
  });
  (function() {
    var msgInput2 = document.getElementById("msg-input");
    if (!msgInput2) return;
    msgInput2.addEventListener("blur", function(e) {
      if (window.__voiceInputAllowBlur) return;
      var savedStart = msgInput2.selectionStart || 0;
      var savedEnd = msgInput2.selectionEnd || 0;
      var rt = e && e.relatedTarget;
      if (rt && rt.tagName) {
        var tn = rt.tagName.toUpperCase();
        if (tn === "TEXTAREA" || tn === "INPUT" || tn === "SELECT") return;
        if (rt.isContentEditable) return;
      }
      requestAnimationFrame(function() {
        var still = document.activeElement;
        if (still === msgInput2) return;
        if (still && still.tagName) {
          var stn = still.tagName.toUpperCase();
          if (stn === "TEXTAREA" || stn === "INPUT" || stn === "SELECT") return;
          if (still.isContentEditable) return;
        }
        try {
          var sel = window.getSelection && window.getSelection();
          if (sel && sel.toString().length > 0) {
            var anchor = sel.anchorNode;
            if (anchor && anchor.nodeType === 3) anchor = anchor.parentElement;
            if (anchor && anchor.closest && anchor.closest("#messages, .msg, .thread-panel")) {
              return;
            }
          }
        } catch (_) {
        }
        try {
          msgInput2.focus();
          msgInput2.setSelectionRange(savedStart, savedEnd);
        } catch (_) {
        }
      });
    });
  })();
  document.getElementById("msg-send").addEventListener("click", function(e) {
    e.preventDefault();
    sendMessage();
    document.getElementById("msg-input").focus();
  });
  document.getElementById("msg-input").addEventListener("keydown", function(e) {
    var isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
    if ((isMac ? e.metaKey : e.ctrlKey) && e.key === "u") {
      e.preventDefault();
      var fi = document.getElementById("file-input");
      if (fi) fi.click();
      return;
    }
    if (e.key === "Enter") {
      var dd = document.getElementById("mention-dropdown");
      if (dd && dd.classList.contains("visible")) return;
      if (e.shiftKey) return;
      if (e.altKey) {
        e.preventDefault();
        return;
      }
      e.preventDefault();
      sendMessage();
    }
  });
  function startEditMessage(msgId) {
    var el = document.querySelector('.msg[data-msg-id="' + msgId + '"]');
    if (!el) return;
    var contentEl = el.querySelector(".content");
    if (!contentEl) return;
    if (el.querySelector(".msg-edit-input")) return;
    var currentText = contentEl.innerText || contentEl.textContent || "";
    var msgInput2 = document.getElementById("msg-input");
    var inputHasFocus = msgInput2 && document.activeElement === msgInput2;
    var savedStart = inputHasFocus ? msgInput2.selectionStart : 0;
    var savedEnd = inputHasFocus ? msgInput2.selectionEnd : 0;
    contentEl.style.display = "none";
    var editContainer = document.createElement("div");
    editContainer.className = "msg-edit-container";
    editContainer.innerHTML = '<textarea class="msg-edit-input" rows="2">' + escapeHtml(currentText) + '</textarea><div class="msg-edit-actions"><button class="msg-edit-save" type="button">Save</button><button class="msg-edit-cancel" type="button">Cancel</button></div>';
    contentEl.parentNode.insertBefore(editContainer, contentEl.nextSibling);
    if (inputHasFocus && document.activeElement !== msgInput2) {
      msgInput2.focus();
      try {
        msgInput2.setSelectionRange(savedStart, savedEnd);
      } catch (_) {
      }
    }
    var textarea = editContainer.querySelector(".msg-edit-input");
    textarea.focus();
    textarea.setSelectionRange(textarea.value.length, textarea.value.length);
    textarea.style.height = "auto";
    textarea.style.height = Math.min(textarea.scrollHeight, 200) + "px";
    editContainer.querySelector(".msg-edit-save").addEventListener("click", function() {
      saveEditMessage(msgId, textarea.value);
    });
    editContainer.querySelector(".msg-edit-cancel").addEventListener("click", function() {
      cancelEditMessage(msgId);
    });
    textarea.addEventListener("keydown", function(e) {
      if (e.key === "Enter" && !e.shiftKey && !e.altKey) {
        e.preventDefault();
        saveEditMessage(msgId, textarea.value);
      }
      if (e.key === "Escape") {
        cancelEditMessage(msgId);
      }
    });
  }
  function saveEditMessage(msgId, newText) {
    newText = (newText || "").trim();
    if (!newText) return;
    fetch(apiUrl("/api/messages/" + msgId + "/"), {
      method: "PATCH",
      headers: orochiHeaders(),
      credentials: "same-origin",
      body: JSON.stringify({ text: newText })
    }).then(function(res) {
      if (!res.ok) {
        res.json().then(function(d) {
          console.error("Edit failed:", d.error || res.status);
        });
      }
    }).catch(function(e) {
      console.error("Edit error:", e);
    });
    cancelEditMessage(msgId);
  }
  function cancelEditMessage(msgId) {
    var el = document.querySelector('.msg[data-msg-id="' + msgId + '"]');
    if (!el) return;
    var editContainer = el.querySelector(".msg-edit-container");
    if (editContainer) editContainer.remove();
    var contentEl = el.querySelector(".content");
    if (contentEl) contentEl.style.display = "";
  }
  function deleteMessage(msgId) {
    fetch(apiUrl("/api/messages/" + msgId + "/"), {
      method: "DELETE",
      headers: orochiHeaders(),
      credentials: "same-origin"
    }).then(function(res) {
      if (!res.ok) {
        res.json().then(function(d) {
          console.error("Delete failed:", d.error || res.status);
        });
      }
    }).catch(function(e) {
      console.error("Delete error:", e);
    });
  }
  (function() {
    var LONG_PRESS_MS = 500;
    var MOVE_TOLERANCE = 10;
    var pressTimer = null;
    var startX = 0;
    var startY = 0;
    var didLongPress = false;
    var openMenu = null;
    function isTouchDevice() {
      return "ontouchstart" in window || navigator.maxTouchPoints && navigator.maxTouchPoints > 0;
    }
    function isInteractiveTarget(node) {
      while (node && node !== document.body) {
        var tag = node.tagName;
        if (tag === "TEXTAREA" || tag === "BUTTON" || tag === "INPUT" || tag === "A" || tag === "SELECT") {
          return true;
        }
        if (node.classList && node.classList.contains("msg-edit-container")) {
          return true;
        }
        node = node.parentNode;
      }
      return false;
    }
    function closeLongPressMenu() {
      if (openMenu && openMenu.parentNode) {
        openMenu.parentNode.removeChild(openMenu);
      }
      openMenu = null;
      document.removeEventListener("touchstart", _outsideHandler, true);
      document.removeEventListener("mousedown", _outsideHandler, true);
    }
    function _outsideHandler(e) {
      if (openMenu && !openMenu.contains(e.target)) {
        closeLongPressMenu();
      }
    }
    function getMessageMeta(msgEl) {
      var idStr = msgEl.getAttribute("data-msg-id");
      var msgId = idStr ? parseInt(idStr, 10) : null;
      var senderEl = msgEl.querySelector(".sender");
      var sender = senderEl ? senderEl.textContent.trim() : "";
      var contentEl = msgEl.querySelector(".content");
      var text = contentEl ? contentEl.innerText || contentEl.textContent || "" : "";
      var isOwn = typeof userName !== "undefined" && sender && (sender === userName || sender === cleanAgentName(userName));
      return { msgId, sender, text, isOwn };
    }
    function copyText(text) {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).catch(function() {
        });
        return;
      }
      try {
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      } catch (_) {
      }
    }
    function showLongPressMenu(msgEl, x, y) {
      closeLongPressMenu();
      var meta = getMessageMeta(msgEl);
      if (!meta.msgId) return;
      var menu = document.createElement("div");
      menu.className = "long-press-menu";
      var actions = [
        {
          label: "Reply",
          icon: "💬",
          run: function() {
            if (typeof openThreadForMessage === "function") {
              openThreadForMessage(meta.msgId);
            }
          }
        },
        {
          label: "React",
          icon: "☺",
          run: function() {
            var btn = msgEl.querySelector(".msg-react-btn");
            if (typeof openReactionPicker === "function") {
              openReactionPicker(btn || msgEl, meta.msgId);
            }
          }
        }
      ];
      if (meta.isOwn) {
        actions.push({
          label: "Edit",
          icon: "✏️",
          run: function() {
            if (typeof startEditMessage === "function") {
              startEditMessage(meta.msgId);
            }
          }
        });
        actions.push({
          label: "Delete",
          icon: "🗑️",
          cls: "danger",
          run: function() {
            if (typeof deleteMessage === "function") {
              deleteMessage(meta.msgId);
            }
          }
        });
      }
      actions.push({
        label: "Copy text",
        icon: "📋",
        run: function() {
          copyText(meta.text);
        }
      });
      actions.forEach(function(a) {
        var item = document.createElement("button");
        item.type = "button";
        item.className = "long-press-item" + (a.cls ? " " + a.cls : "");
        item.innerHTML = '<span class="long-press-icon">' + a.icon + '</span><span class="long-press-label">' + a.label + "</span>";
        item.addEventListener("click", function(ev) {
          ev.preventDefault();
          ev.stopPropagation();
          closeLongPressMenu();
          try {
            a.run();
          } catch (err) {
            console.error("long-press action failed:", err);
          }
        });
        menu.appendChild(item);
      });
      document.body.appendChild(menu);
      var rect = menu.getBoundingClientRect();
      var vw = window.innerWidth;
      var vh = window.innerHeight;
      var left = Math.min(Math.max(8, x - rect.width / 2), vw - rect.width - 8);
      var top = y + 12;
      if (top + rect.height > vh - 8) {
        top = Math.max(8, y - rect.height - 12);
      }
      menu.style.left = left + "px";
      menu.style.top = top + "px";
      openMenu = menu;
      setTimeout(function() {
        document.addEventListener("touchstart", _outsideHandler, true);
        document.addEventListener("mousedown", _outsideHandler, true);
      }, 0);
      if (navigator.vibrate) {
        try {
          navigator.vibrate(15);
        } catch (_) {
        }
      }
    }
    function clearPressTimer() {
      if (pressTimer) {
        clearTimeout(pressTimer);
        pressTimer = null;
      }
    }
    function onTouchStart(e) {
      if (e.touches.length !== 1) return;
      var t = e.target;
      if (isInteractiveTarget(t)) return;
      var msgEl = t.closest && t.closest(".msg");
      if (!msgEl || msgEl.classList.contains("msg-system")) return;
      if (!msgEl.getAttribute("data-msg-id")) return;
      didLongPress = false;
      var touch = e.touches[0];
      startX = touch.clientX;
      startY = touch.clientY;
      pressTimer = setTimeout(function() {
        didLongPress = true;
        showLongPressMenu(msgEl, startX, startY);
      }, LONG_PRESS_MS);
    }
    function onTouchMove(e) {
      if (!pressTimer) return;
      var touch = e.touches[0];
      if (!touch) return;
      var dx = Math.abs(touch.clientX - startX);
      var dy = Math.abs(touch.clientY - startY);
      if (dx > MOVE_TOLERANCE || dy > MOVE_TOLERANCE) {
        clearPressTimer();
      }
    }
    function onTouchEnd() {
      clearPressTimer();
    }
    function onTouchCancel() {
      clearPressTimer();
    }
    function onClickCapture(e) {
      if (didLongPress) {
        didLongPress = false;
        e.preventDefault();
        e.stopPropagation();
      }
    }
    function init() {
      if (!isTouchDevice()) return;
      var container = document.getElementById("messages");
      if (!container) return;
      container.addEventListener("touchstart", onTouchStart, { passive: true });
      container.addEventListener("touchmove", onTouchMove, { passive: true });
      container.addEventListener("touchend", onTouchEnd, { passive: true });
      container.addEventListener("touchcancel", onTouchCancel, { passive: true });
      container.addEventListener("click", onClickCapture, true);
    }
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", init);
    } else {
      init();
    }
  })();
  document.addEventListener("click", function(e) {
    var link = e.target.closest(".channel-link");
    if (!link) return;
    e.preventDefault();
    var ch = link.getAttribute("data-channel");
    if (!ch) return;
    if (typeof currentChannel !== "undefined") {
      if (currentChannel === ch) {
        if (typeof setCurrentChannel === "function") setCurrentChannel(null);
        else currentChannel = null;
        if (typeof loadHistory === "function") loadHistory();
      } else {
        if (typeof setCurrentChannel === "function") setCurrentChannel(ch);
        else currentChannel = ch;
        if (typeof loadChannelHistory === "function") loadChannelHistory(ch);
      }
      if (typeof addTag === "function") addTag("channel", ch);
      if (typeof fetchStats === "function") fetchStats();
    }
  });
  var mentionDropdown = document.getElementById("mention-dropdown");
  var mentionSelectedIndex = -1;
  var cachedAgentObjects = [];
  var cachedMemberNames = [];
  var mentionActiveInput = null;
  var SPECIAL_MENTIONS = [
    { name: "all", desc: "notify everyone" },
    { name: "channel", desc: "notify this channel" },
    { name: "agents", desc: "notify all agents" },
    { name: "heads", desc: "notify all head-* agents" },
    { name: "healers", desc: "notify all mamba-healer-* agents" },
    { name: "mambas", desc: "notify all mamba-* agents" }
  ];
  function fuzzyMatch$1(query, text) {
    var q = query.toLowerCase();
    var t = text.toLowerCase();
    if (t.indexOf(q) === 0) return 0;
    if (t.indexOf(q) !== -1) return 1;
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
  function cleanDisplayName(name) {
    return name.replace(/^orochi-/, "");
  }
  async function refreshAgentNames$1() {
    try {
      var res = await fetch(apiUrl("/api/agents"));
      var agents = await res.json();
      cachedAgentNames = agents.map(function(a) {
        return a.name;
      });
      cachedAgentObjects = agents;
    } catch (e) {
    }
    try {
      var res2 = await fetch(apiUrl("/api/members/"), { credentials: "same-origin" });
      var members = await res2.json();
      cachedMemberNames = members.map(function(m) {
        return m.username;
      });
    } catch (e) {
    }
  }
  function getMentionQuery(input) {
    var val = input.value;
    var pos = input.selectionStart;
    var before = val.substring(0, pos);
    var match = before.match(/(^|[^\w])@([\w@.\-]*)$/);
    if (match)
      return {
        query: match[2].toLowerCase(),
        start: match.index + match[1].length
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
  function positionMentionDropdown(inputEl) {
    if (inputEl && inputEl.id !== "msg-input") {
      var rect = inputEl.getBoundingClientRect();
      mentionDropdown.style.position = "fixed";
      mentionDropdown.style.bottom = window.innerHeight - rect.top + 4 + "px";
      mentionDropdown.style.left = rect.left + "px";
      mentionDropdown.style.width = rect.width + "px";
    } else {
      mentionDropdown.style.position = "";
      mentionDropdown.style.bottom = "";
      mentionDropdown.style.left = "";
      mentionDropdown.style.width = "";
    }
  }
  function showMentionDropdown(specialItems, agentItems) {
    var msgInput2 = document.getElementById("msg-input");
    var inputHasFocus = msgInput2 && document.activeElement === msgInput2;
    var savedStart = inputHasFocus ? msgInput2.selectionStart : 0;
    var savedEnd = inputHasFocus ? msgInput2.selectionEnd : 0;
    mentionSelectedIndex = 0;
    var html = "";
    specialItems.forEach(function(item, i) {
      html += '<div class="mention-item mention-special' + (i === 0 ? " selected" : "") + '" data-name="' + escapeHtml(item.name) + '"><span class="mention-dot mention-dot-special"></span><strong>@' + escapeHtml(item.name) + '</strong><span class="mention-desc">' + escapeHtml(item.desc) + "</span></div>";
    });
    if (specialItems.length > 0 && agentItems.length > 0) {
      html += '<div class="mention-divider"></div>';
    }
    var offset = specialItems.length;
    agentItems.forEach(function(name, i) {
      var online = isAgentOnline(name);
      var dotClass = online ? "mention-dot-online" : "mention-dot-offline";
      var display = cleanDisplayName(name);
      var showFull = display !== name;
      html += '<div class="mention-item' + (offset + i === 0 ? " selected" : "") + '" data-name="' + escapeHtml(name) + '"><span class="mention-dot ' + dotClass + '"></span>' + escapeHtml(display) + (showFull ? '<span class="mention-desc">' + escapeHtml(name) + "</span>" : "") + "</div>";
    });
    mentionDropdown.innerHTML = html;
    mentionDropdown.classList.add("visible");
    positionMentionDropdown(mentionActiveInput);
    if (inputHasFocus && document.activeElement !== msgInput2) {
      msgInput2.focus();
      try {
        msgInput2.setSelectionRange(savedStart, savedEnd);
      } catch (_) {
      }
    }
  }
  function hideMentionDropdown$1() {
    var msgInput2 = document.getElementById("msg-input");
    var inputHasFocus = msgInput2 && document.activeElement === msgInput2;
    var savedStart = inputHasFocus ? msgInput2.selectionStart : 0;
    var savedEnd = inputHasFocus ? msgInput2.selectionEnd : 0;
    mentionDropdown.classList.remove("visible");
    mentionDropdown.innerHTML = "";
    mentionSelectedIndex = -1;
    mentionActiveInput = null;
    mentionDropdown.style.position = "";
    mentionDropdown.style.bottom = "";
    mentionDropdown.style.left = "";
    mentionDropdown.style.width = "";
    if (inputHasFocus && document.activeElement !== msgInput2) {
      msgInput2.focus();
      try {
        msgInput2.setSelectionRange(savedStart, savedEnd);
      } catch (_) {
      }
    }
  }
  function insertMention(name) {
    var input = mentionActiveInput || document.getElementById("msg-input");
    var info = getMentionQuery(input);
    if (!info) return;
    var before = input.value.substring(0, info.start);
    var after = input.value.substring(input.selectionStart);
    input.value = before + "@" + name + " " + after;
    var newPos = info.start + name.length + 2;
    input.setSelectionRange(newPos, newPos);
    input.focus();
    hideMentionDropdown$1();
  }
  function handleMentionInput(e) {
    if (e && e.isComposing) return;
    mentionActiveInput = this;
    var info = getMentionQuery(this);
    if (!info) {
      hideMentionDropdown$1();
      return;
    }
    var matchedSpecial = SPECIAL_MENTIONS.filter(function(s) {
      return s.name.indexOf(info.query) === 0;
    });
    var allNames = cachedAgentNames.slice();
    cachedMemberNames.forEach(function(m) {
      if (allNames.indexOf(m) === -1) allNames.push(m);
    });
    var matchedAgents = allNames.map(function(n) {
      var score = fuzzyMatch$1(info.query, n);
      var cleanScore = fuzzyMatch$1(info.query, cleanDisplayName(n));
      var best = score === -1 ? cleanScore : cleanScore === -1 ? score : Math.min(score, cleanScore);
      return { name: n, score: best };
    }).filter(function(item) {
      return item.score !== -1;
    }).sort(function(a, b) {
      return a.score - b.score;
    }).map(function(item) {
      return item.name;
    });
    if (matchedSpecial.length === 0 && matchedAgents.length === 0) {
      hideMentionDropdown$1();
      return;
    }
    showMentionDropdown(matchedSpecial, matchedAgents);
  }
  function handleMentionKeydown(e) {
    if (!mentionDropdown || !mentionDropdown.classList.contains("visible")) {
      return;
    }
    var items = mentionDropdown.querySelectorAll(".mention-item");
    if (items.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      mentionSelectedIndex = Math.min(mentionSelectedIndex + 1, items.length - 1);
      items.forEach(function(el, i) {
        el.classList.toggle("selected", i === mentionSelectedIndex);
      });
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      mentionSelectedIndex = Math.max(mentionSelectedIndex - 1, 0);
      items.forEach(function(el, i) {
        el.classList.toggle("selected", i === mentionSelectedIndex);
      });
    } else if ((e.key === "Tab" || e.key === "Enter") && mentionSelectedIndex >= 0) {
      e.preventDefault();
      insertMention(items[mentionSelectedIndex].getAttribute("data-name"));
    } else if (e.key === "Escape") {
      e.preventDefault();
      hideMentionDropdown$1();
    }
  }
  function handleMentionBlur() {
    setTimeout(hideMentionDropdown$1, 150);
  }
  function initMentionAutocomplete(inputEl) {
    inputEl.addEventListener("input", handleMentionInput);
    inputEl.addEventListener("compositionend", handleMentionInput);
    inputEl.addEventListener("keydown", handleMentionKeydown);
    inputEl.addEventListener("blur", handleMentionBlur);
  }
  initMentionAutocomplete(document.getElementById("msg-input"));
  mentionDropdown.addEventListener("click", function(e) {
    var item = e.target.closest(".mention-item");
    if (item) insertMention(item.getAttribute("data-name"));
  });
  setInterval(refreshAgentNames$1, 15e3);
  refreshAgentNames$1();
  var settingsLoaded = false;
  function fetchSettings$1() {
    if (settingsLoaded) return;
    var container = document.getElementById("settings-content");
    if (!container) return;
    fetch(apiUrl("/settings/"), { credentials: "same-origin" }).then(function(res) {
      return res.text();
    }).then(function(html) {
      var msgInput2 = document.getElementById("msg-input");
      var inputHasFocus = msgInput2 && document.activeElement === msgInput2;
      var savedStart = inputHasFocus ? msgInput2.selectionStart : 0;
      var savedEnd = inputHasFocus ? msgInput2.selectionEnd : 0;
      var parser = new DOMParser();
      var doc = parser.parseFromString(html, "text/html");
      var main = doc.querySelector(".settings-page") || doc.querySelector("main") || doc.querySelector(".container");
      if (main) {
        container.innerHTML = main.innerHTML;
      } else {
        container.innerHTML = doc.body.innerHTML;
      }
      settingsLoaded = true;
      wireSettingsForms(container);
      if (inputHasFocus && document.activeElement !== msgInput2) {
        msgInput2.focus();
        try {
          msgInput2.setSelectionRange(savedStart, savedEnd);
        } catch (_) {
        }
      }
    }).catch(function() {
      var msgInput2 = document.getElementById("msg-input");
      var inputHasFocus = msgInput2 && document.activeElement === msgInput2;
      var savedStart = inputHasFocus ? msgInput2.selectionStart : 0;
      var savedEnd = inputHasFocus ? msgInput2.selectionEnd : 0;
      container.innerHTML = '<p class="empty-notice">Failed to load settings.</p>';
      if (inputHasFocus && document.activeElement !== msgInput2) {
        msgInput2.focus();
        try {
          msgInput2.setSelectionRange(savedStart, savedEnd);
        } catch (_) {
        }
      }
    });
  }
  function wireSettingsModeTabs(container) {
    var btns = container.querySelectorAll(".settings-mode-btn");
    var panes = container.querySelectorAll(".settings-mode-pane");
    if (!btns.length || !panes.length) return;
    btns.forEach(function(btn) {
      btn.addEventListener("click", function() {
        var mode = btn.getAttribute("data-mode");
        btns.forEach(function(b) {
          b.classList.toggle("active", b === btn);
        });
        panes.forEach(function(p) {
          p.style.display = p.getAttribute("data-mode") === mode ? "" : "none";
        });
      });
    });
  }
  function _wireSettingsIconPicker(container) {
    var preview = container.querySelector(".ws-icon-clickable, #ws-icon-preview");
    var iconInput = container.querySelector("#icon-input");
    var form = container.querySelector(".settings-form-icon");
    if (!preview || !iconInput || !form) return;
    preview.addEventListener("click", function() {
      var emoji = window.prompt(
        "Enter a single emoji (or leave blank to clear):",
        ""
      );
      if (emoji === null) return;
      iconInput.value = emoji.trim();
      form.submit();
    });
  }
  function wireSettingsForms(container) {
    wireSettingsModeTabs(container);
    _wireSettingsIconPicker(container);
    if (typeof initPushUI === "function") initPushUI();
    container.querySelectorAll("form").forEach(function(form) {
      form.addEventListener("submit", function(e) {
        e.preventDefault();
        var formData = new FormData(form);
        fetch(form.action || apiUrl("/settings/"), {
          method: "POST",
          credentials: "same-origin",
          body: formData
        }).then(function(res) {
          if (res.redirected) {
            window.location.href = res.url;
            return;
          }
          settingsLoaded = false;
          fetchSettings$1();
        }).catch(function() {
          alert("Action failed. Please try again.");
        });
      });
    });
    var deleteInput = container.querySelector('input[name="confirm_name"]');
    var deleteBtn = container.querySelector("#delete-ws-btn, .delete-ws-btn");
    if (deleteInput && deleteBtn) {
      var wsName = window.__orochiWorkspaceName || "";
      deleteBtn.disabled = true;
      deleteInput.addEventListener("input", function() {
        deleteBtn.disabled = this.value !== wsName;
      });
    }
  }
  document.addEventListener("DOMContentLoaded", function() {
    var settingsBtn = document.querySelector('[data-tab="settings"]');
    if (settingsBtn) {
      settingsBtn.addEventListener("click", function() {
        fetchSettings$1();
      });
    }
  });
  (function() {
    var EMOJI_LIST = [
      /* animals */
      "🐍",
      "🐉",
      "🦉",
      "🐺",
      "🦊",
      "🐻",
      "🐱",
      "🐶",
      "🐝",
      "🦋",
      "🐢",
      "🐙",
      /* objects & tools */
      "🚀",
      "⚙️",
      "🔬",
      "💻",
      "📚",
      "🔭",
      "⚡",
      "🔥",
      "🌟",
      "🌊",
      "🌍",
      "🌙",
      /* symbols & shapes */
      "❤️",
      "💎",
      "🔶",
      "🔵",
      "🟢",
      "🟣",
      "🟠",
      "🔴",
      /* activities */
      "🎯",
      "🎵",
      "🎨",
      "🏆",
      "🧩",
      "🎮",
      "♟️",
      "💡",
      /* plants & nature */
      "🌱",
      "🌿",
      "🌵",
      "🌸",
      "🌻",
      "🌺",
      "🌲",
      "🍃"
    ];
    var overlay = null;
    function createPicker(onSelect) {
      if (overlay) close();
      overlay = document.createElement("div");
      overlay.className = "emoji-picker-overlay";
      var picker = document.createElement("div");
      picker.className = "emoji-picker";
      var header = document.createElement("div");
      header.className = "emoji-picker-header";
      header.textContent = "Choose workspace icon";
      picker.appendChild(header);
      var actions = document.createElement("div");
      actions.className = "emoji-picker-actions";
      var uploadBtn = document.createElement("button");
      uploadBtn.type = "button";
      uploadBtn.className = "emoji-picker-btn emoji-picker-upload";
      uploadBtn.textContent = "📂 Upload image";
      uploadBtn.title = "Upload an image file (max 2 MB)";
      var fileInput = document.createElement("input");
      fileInput.type = "file";
      fileInput.accept = "image/*";
      fileInput.className = "emoji-picker-file";
      fileInput.addEventListener("change", function() {
        var f = fileInput.files && fileInput.files[0];
        if (f) {
          uploadIconImage(f);
        }
      });
      uploadBtn.addEventListener("click", function() {
        fileInput.click();
      });
      actions.appendChild(uploadBtn);
      actions.appendChild(fileInput);
      if (window.__orochiWorkspaceIconImage) {
        var removeBtn = document.createElement("button");
        removeBtn.type = "button";
        removeBtn.className = "emoji-picker-btn emoji-picker-remove-image";
        removeBtn.textContent = "✕ Remove image";
        removeBtn.title = "Delete the uploaded image (keeps emoji)";
        removeBtn.addEventListener("click", function() {
          clearIconImage();
        });
        actions.appendChild(removeBtn);
      }
      picker.appendChild(actions);
      var grid = document.createElement("div");
      grid.className = "emoji-picker-grid";
      var clearBtn = document.createElement("button");
      clearBtn.className = "emoji-picker-btn emoji-picker-clear";
      clearBtn.textContent = "✕";
      clearBtn.title = "Remove custom icon";
      clearBtn.addEventListener("click", function() {
        onSelect("");
        close();
      });
      grid.appendChild(clearBtn);
      EMOJI_LIST.forEach(function(emoji) {
        var btn = document.createElement("button");
        btn.className = "emoji-picker-btn";
        btn.textContent = emoji;
        btn.addEventListener("click", function() {
          onSelect(emoji);
          close();
        });
        grid.appendChild(btn);
      });
      picker.appendChild(grid);
      overlay.appendChild(picker);
      overlay.addEventListener("click", function(e) {
        if (e.target === overlay) close();
      });
      document.body.appendChild(overlay);
      requestAnimationFrame(function() {
        overlay.classList.add("visible");
      });
    }
    function close() {
      if (!overlay) return;
      overlay.classList.remove("visible");
      setTimeout(function() {
        if (overlay && overlay.parentNode) {
          overlay.parentNode.removeChild(overlay);
        }
        overlay = null;
      }, 150);
    }
    function postIcon(emoji) {
      var formData = new FormData();
      formData.append("action", "set_icon");
      formData.append("icon", emoji);
      fetch(apiUrl("/settings/"), {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrfToken },
        body: formData
      }).then(function(res) {
        if (!res.ok) {
          console.error("set_icon failed:", res.status);
          return;
        }
        window.__orochiWorkspaceIcon = emoji;
        updateVisibleIcons(emoji);
      }).catch(function(e) {
        console.error("set_icon error:", e);
      });
    }
    function renderImageIcon(url, size) {
      var radius = Math.round(size * 0.22);
      var s = escapeHtmlSafe(url);
      return '<img class="ws-icon-img" src="' + s + '" alt="" width="' + size + '" height="' + size + '" style="width:' + size + "px;height:" + size + "px;border-radius:" + radius + 'px;object-fit:cover;display:block" />';
    }
    function escapeHtmlSafe(s) {
      var d = document.createElement("div");
      d.textContent = s || "";
      return d.innerHTML;
    }
    function updateVisibleIcons(emoji) {
      var wsName = window.__orochiWorkspaceName || "workspace";
      var imgUrl = window.__orochiWorkspaceIconImage || "";
      var wsIconSlot = document.getElementById("ws-icon-slot");
      if (wsIconSlot) {
        if (imgUrl) {
          wsIconSlot.innerHTML = renderImageIcon(imgUrl, 16);
        } else if (emoji) {
          wsIconSlot.innerHTML = '<span class="ws-emoji-icon">' + emoji + "</span>";
        } else {
          wsIconSlot.innerHTML = getWorkspaceIcon(wsName, 16);
        }
      }
      var preview = document.getElementById("ws-icon-preview");
      if (preview) {
        if (imgUrl) {
          preview.innerHTML = renderImageIcon(imgUrl, 64);
        } else if (emoji) {
          preview.innerHTML = '<span class="ws-emoji-icon ws-emoji-icon-lg">' + emoji + "</span>";
        } else {
          preview.innerHTML = getWorkspaceIcon(wsName, 64);
        }
      }
    }
    function uploadIconImage(file) {
      if (!file) return;
      if (!/^image\//.test(file.type || "")) {
        alert("Only image files are allowed.");
        return;
      }
      if (file.size > 2 * 1024 * 1024) {
        alert("Image too large (max 2 MB).");
        return;
      }
      var formData = new FormData();
      formData.append("file", file);
      fetch("/api/workspace/icon/", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrfToken },
        body: formData
      }).then(function(res) {
        if (!res.ok) {
          console.error("workspace icon upload failed:", res.status);
          return res.json().then(function(e) {
            alert(e && e.error || "Upload failed");
          }).catch(function() {
            alert("Upload failed");
          });
        }
        return res.json().then(function(body) {
          window.__orochiWorkspaceIconImage = body.url || "";
          updateVisibleIcons(window.__orochiWorkspaceIcon || "");
          close();
        });
      }).catch(function(e) {
        console.error("workspace icon upload error:", e);
      });
    }
    function clearIconImage() {
      fetch("/api/workspace/icon/?clear=1", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrfToken }
      }).then(function(res) {
        if (!res.ok) {
          console.error("workspace icon clear failed:", res.status);
          return;
        }
        window.__orochiWorkspaceIconImage = "";
        updateVisibleIcons(window.__orochiWorkspaceIcon || "");
        close();
      }).catch(function(e) {
        console.error("workspace icon clear error:", e);
      });
    }
    function wireIconClick() {
      var wsIconSlot = document.getElementById("ws-icon-slot");
      if (wsIconSlot) {
        wsIconSlot.style.cursor = "pointer";
        wsIconSlot.title = "Click to change workspace icon";
        wsIconSlot.addEventListener("click", function(e) {
          e.stopPropagation();
          createPicker(function(emoji) {
            postIcon(emoji);
          });
        });
      }
    }
    function wireSettingsIconClick() {
      var observer = new MutationObserver(function() {
        var preview = document.getElementById("ws-icon-preview");
        if (preview && !preview.dataset.emojiWired) {
          preview.dataset.emojiWired = "1";
          preview.style.cursor = "pointer";
          preview.title = "Click to change workspace icon";
          preview.addEventListener("click", function(e) {
            e.stopPropagation();
            createPicker(function(emoji) {
              postIcon(emoji);
            });
          });
        }
      });
      var settingsContent = document.getElementById("settings-content");
      if (settingsContent) {
        observer.observe(settingsContent, { childList: true, subtree: true });
      }
    }
    document.addEventListener("DOMContentLoaded", function() {
      wireIconClick();
      wireSettingsIconClick();
    });
    if (document.readyState !== "loading") {
      wireIconClick();
      wireSettingsIconClick();
    }
    window.openEmojiPicker = createPicker;
    window.closeEmojiPicker = close;
  })();
  var _fm$1 = function(query, text) {
    return fuzzyMatch(query, text) >= 0;
  };
  var filterInput$1 = document.getElementById("filter-input");
  var filterTagsEl = document.getElementById("filter-tags");
  var filterSuggestEl = document.getElementById("filter-suggest");
  var activeTags$1 = [];
  var suggestIndex = -1;
  function addTag$1(type, value) {
    var idx = -1;
    activeTags$1.forEach(function(t, i) {
      if (t.type === type && t.value === value) idx = i;
    });
    if (idx >= 0) {
      activeTags$1.splice(idx, 1);
    } else {
      activeTags$1.push({ type, value });
    }
    renderTags();
    runFilter();
    syncFilterVisuals();
  }
  function removeTag(index) {
    activeTags$1.splice(index, 1);
    renderTags();
    runFilter();
    syncFilterVisuals();
  }
  function syncFilterVisuals() {
    var agentValues = {};
    var channelValues = {};
    var hostValues = {};
    activeTags$1.forEach(function(t) {
      if (t.type === "agent") agentValues[t.value.toLowerCase()] = true;
      if (t.type === "channel") channelValues[t.value.toLowerCase()] = true;
      if (t.type === "host") hostValues[t.value.toLowerCase()] = true;
    });
    document.querySelectorAll(".agent-card").forEach(function(el) {
      var name = (el.getAttribute("data-agent") || el.textContent.trim().split("\n")[0]).toLowerCase();
      el.classList.toggle("filter-active", !!agentValues[name]);
    });
    document.querySelectorAll(".channel-item").forEach(function(el) {
      var ch = (el.getAttribute("data-channel") || el.textContent.trim()).toLowerCase();
      el.classList.toggle("filter-active", !!channelValues[ch]);
    });
    document.querySelectorAll(".res-card").forEach(function(el) {
      var host = (el.getAttribute("data-host") || el.textContent.trim().split("\n")[0]).toLowerCase();
      el.classList.toggle("filter-active", !!hostValues[host]);
    });
  }
  function renderTags() {
    var msgInput2 = document.getElementById("msg-input");
    var inputHasFocus = msgInput2 && document.activeElement === msgInput2;
    var savedStart = inputHasFocus ? msgInput2.selectionStart : 0;
    var savedEnd = inputHasFocus ? msgInput2.selectionEnd : 0;
    filterTagsEl.innerHTML = activeTags$1.map(function(t, i) {
      return '<span class="filter-tag" data-type="' + t.type + '" onclick="removeTag(' + i + ')">' + t.type + ":" + escapeHtml(t.value) + ' <span class="tag-remove">×</span></span>';
    }).join("");
    if (inputHasFocus && document.activeElement !== msgInput2) {
      msgInput2.focus();
      try {
        msgInput2.setSelectionRange(savedStart, savedEnd);
      } catch (_) {
      }
    }
  }
  function getTagSuggestions(prefix) {
    var results = [];
    var pLower = prefix.toLowerCase();
    cachedAgentNames.forEach(function(n) {
      if (_fm$1(pLower, n.toLowerCase())) {
        results.push({ type: "agent", value: n });
      }
    });
    Object.keys(resourceData).forEach(function(h) {
      if (_fm$1(pLower, h.toLowerCase())) {
        results.push({ type: "host", value: h });
      }
    });
    document.querySelectorAll("#channels .channel-item").forEach(function(el) {
      var ch = el.getAttribute("data-channel") || el.textContent.trim();
      if (_fm$1(pLower, ch.toLowerCase())) {
        results.push({ type: "channel", value: ch });
      }
    });
    document.querySelectorAll(".todo-label[data-label-name]").forEach(function(el) {
      var name = el.getAttribute("data-label-name");
      if (name && _fm$1(pLower, name.toLowerCase())) {
        results.push({ type: "label", value: name });
      }
    });
    var seen = {};
    return results.filter(function(r) {
      var key = r.type + ":" + r.value;
      if (seen[key]) return false;
      seen[key] = true;
      return true;
    }).slice(0, 8);
  }
  function showSuggestions(items) {
    if (items.length === 0) {
      hideSuggestions();
      return;
    }
    var msgInput2 = document.getElementById("msg-input");
    var inputHasFocus = msgInput2 && document.activeElement === msgInput2;
    var savedStart = inputHasFocus ? msgInput2.selectionStart : 0;
    var savedEnd = inputHasFocus ? msgInput2.selectionEnd : 0;
    suggestIndex = 0;
    filterSuggestEl.innerHTML = items.map(function(item, i) {
      return '<div class="filter-suggest-item' + (i === 0 ? " selected" : "") + '" data-type="' + item.type + '" data-value="' + escapeHtml(item.value) + '"><span class="suggest-type">' + item.type + ":</span>" + escapeHtml(item.value) + "</div>";
    }).join("");
    filterSuggestEl.classList.add("visible");
    if (inputHasFocus && document.activeElement !== msgInput2) {
      msgInput2.focus();
      try {
        msgInput2.setSelectionRange(savedStart, savedEnd);
      } catch (_) {
      }
    }
  }
  function hideSuggestions() {
    var msgInput2 = document.getElementById("msg-input");
    var inputHasFocus = msgInput2 && document.activeElement === msgInput2;
    var savedStart = inputHasFocus ? msgInput2.selectionStart : 0;
    var savedEnd = inputHasFocus ? msgInput2.selectionEnd : 0;
    filterSuggestEl.classList.remove("visible");
    filterSuggestEl.innerHTML = "";
    suggestIndex = -1;
    if (inputHasFocus && document.activeElement !== msgInput2) {
      msgInput2.focus();
      try {
        msgInput2.setSelectionRange(savedStart, savedEnd);
      } catch (_) {
      }
    }
  }
  filterSuggestEl.addEventListener("click", function(e) {
    var item = e.target.closest(".filter-suggest-item");
    if (item) {
      addTag$1(item.getAttribute("data-type"), item.getAttribute("data-value"));
      filterInput$1.value = "";
      hideSuggestions();
    }
  });
  filterInput$1.addEventListener("input", function() {
    var raw = this.value.trim();
    if (raw.length >= 1) {
      showSuggestions(getTagSuggestions(raw));
    } else {
      hideSuggestions();
    }
    runFilter();
  });
  filterInput$1.addEventListener("keydown", function(e) {
    var items = filterSuggestEl.querySelectorAll(".filter-suggest-item");
    if (items.length > 0 && filterSuggestEl.classList.contains("visible")) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        suggestIndex = Math.min(suggestIndex + 1, items.length - 1);
        items.forEach(function(el, i) {
          el.classList.toggle("selected", i === suggestIndex);
        });
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        suggestIndex = Math.max(suggestIndex - 1, 0);
        items.forEach(function(el, i) {
          el.classList.toggle("selected", i === suggestIndex);
        });
      } else if ((e.key === "Tab" || e.key === "Enter") && suggestIndex >= 0) {
        e.preventDefault();
        var sel = items[suggestIndex];
        addTag$1(sel.getAttribute("data-type"), sel.getAttribute("data-value"));
        filterInput$1.value = "";
        hideSuggestions();
      } else if (e.key === "Escape") {
        hideSuggestions();
      }
    } else if (e.key === "Backspace" && !this.value && activeTags$1.length > 0) {
      removeTag(activeTags$1.length - 1);
    }
  });
  filterInput$1.addEventListener("blur", function() {
    setTimeout(hideSuggestions, 150);
  });
  function _currentInputTokens() {
    var raw = filterInput && filterInput.value || "";
    var parsed = parseFilterInput(raw.trim());
    var set = {};
    parsed.tags.forEach(function(t) {
      if (t.type === "is") set[t.value.toLowerCase()] = true;
    });
    return set;
  }
  function _syncFilterChips() {
    var bar = document.getElementById("sidebar-filter-chips");
    if (!bar) return;
    var inInput = _currentInputTokens();
    var inTags = {};
    activeTags.forEach(function(t) {
      if (t.type === "is") inTags[t.value.toLowerCase()] = true;
    });
    bar.querySelectorAll(".sidebar-filter-chip").forEach(function(chip) {
      var f = chip.getAttribute("data-is");
      var on = !!(inInput[f] || inTags[f]);
      chip.classList.toggle("active", on);
      chip.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }
  function _toggleIsToken(flag) {
    if (!filterInput) return;
    var raw = filterInput.value || "";
    var token = "is:" + flag;
    var re = new RegExp("(?:^|\\s)" + token + "(?=\\s|$)", "i");
    if (re.test(raw)) {
      raw = raw.replace(re, " ").replace(/\s+/g, " ").trim();
    } else {
      raw = (raw ? raw + " " : "") + token;
    }
    filterInput.value = raw;
    filterInput.dispatchEvent(new Event("input", { bubbles: true }));
  }
  function _initFilterChips() {
    var bar = document.getElementById("sidebar-filter-chips");
    if (!bar) return;
    bar.addEventListener("click", function(e) {
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
  var _selectedAgentTab$1 = "overview";
  var _agentDetailCache = {};
  var _agentDetailInflight = {};
  async function _fetchAgentDetail(name) {
    if (!name || name === "overview") return;
    if (_agentDetailInflight[name]) return;
    _agentDetailInflight[name] = true;
    try {
      var res = await fetch(
        apiUrl("/api/agents/" + encodeURIComponent(name) + "/detail/")
      );
      if (!res.ok) {
        console.warn("agent detail fetch failed:", name, res.status);
        return;
      }
      var data = await res.json();
      _agentDetailCache[name] = data;
      if (_selectedAgentTab$1 === name) {
        var grid = document.getElementById("agents-grid");
        if (grid) _renderAgentContent(grid);
      }
    } catch (e) {
      console.warn("agent detail fetch error:", name, e);
    } finally {
      _agentDetailInflight[name] = false;
    }
  }
  function _invalidateAgentDetail(name) {
    delete _agentDetailCache[name];
    _fetchAgentDetail(name);
  }
  function onAgentInfoEvent(name) {
    if (!name) return;
    if (_selectedAgentTab$1 !== name) return;
    _invalidateAgentDetail(name);
  }
  window.onAgentInfoEvent = onAgentInfoEvent;
  async function renderAgentsTab$1() {
    var msgInput2 = document.getElementById("msg-input");
    var inputHasFocus = msgInput2 && document.activeElement === msgInput2;
    var savedStart = inputHasFocus ? msgInput2.selectionStart : 0;
    var savedEnd = inputHasFocus ? msgInput2.selectionEnd : 0;
    var grid = document.getElementById("agents-grid");
    try {
      var res = await fetch(apiUrl("/api/agents/registry"));
      var agents = await res.json();
      if (agents.length === 0) {
        grid.innerHTML = '<p class="empty-notice">No agents connected</p>';
        _lastAgentsData = [];
        return;
      }
      agents.sort(function(a, b) {
        var aOff = isAgentInactive(a) ? 1 : 0;
        var bOff = isAgentInactive(b) ? 1 : 0;
        return aOff - bOff || a.name.localeCompare(b.name);
      });
      _lastAgentsData = agents;
      if (_selectedAgentTab !== "overview" && !agents.find(function(a) {
        return a.name === _selectedAgentTab;
      })) {
        _selectedAgentTab = "overview";
      }
      var existingBar = grid.querySelector("#agent-subtab-bar");
      if (!existingBar) {
        grid.innerHTML = _renderSubTabBar(agents) + '<div id="agent-tab-content" class="agent-tab-content"></div>';
        _bindSubTabBar(grid);
      } else {
        var newBar = document.createElement("div");
        newBar.innerHTML = _renderSubTabBar(agents);
        var updatedBar = newBar.firstChild;
        existingBar.parentNode.replaceChild(updatedBar, existingBar);
        _bindSubTabBar(grid);
      }
      _renderAgentContent(grid);
    } catch (e) {
      console.error("Agents tab error:", e);
    }
    if (inputHasFocus && document.activeElement !== msgInput2) {
      msgInput2.focus();
      try {
        msgInput2.setSelectionRange(savedStart, savedEnd);
      } catch (_) {
      }
    }
  }
  function startAgentsTabRefresh() {
    stopAgentsTabRefresh();
    _agentsTabInterval = setInterval(function() {
      if (activeTab === "agents-tab") renderAgentsTab$1();
    }, 3e3);
  }
  function stopAgentsTabRefresh() {
    if (_agentsTabInterval) {
      clearInterval(_agentsTabInterval);
      _agentsTabInterval = null;
    }
  }
  startAgentsTabRefresh();
  var connectivityCache = null;
  function syncHostHover(host, on) {
    if (!host) return;
    var selectors = [
      '.conn-node[data-host-name="' + host + '"]',
      '.res-card[data-host-name="' + host + '"]',
      '.activity-card[data-machine="' + host + '"]'
    ];
    selectors.forEach(function(sel) {
      var els;
      try {
        els = document.querySelectorAll(sel);
      } catch (e) {
        return;
      }
      els.forEach(function(el) {
        if (on) el.classList.add("mesh-hl");
        else el.classList.remove("mesh-hl");
      });
    });
  }
  window.syncHostHover = syncHostHover;
  async function fetchConnectivity() {
    try {
      var res = await fetch(apiUrl("/api/connectivity/"), {
        credentials: "same-origin"
      });
      if (!res.ok) return;
      connectivityCache = await res.json();
      renderConnectivityMap();
    } catch (e) {
      console.warn("fetchConnectivity error:", e);
    }
  }
  function _layoutNodes(nodes, cx, cy, innerRadius, outerRadius) {
    var positions = {};
    if (nodes.length === 0) return positions;
    var machines = nodes.filter(function(n) {
      return n.type !== "bastion";
    });
    var bastions = nodes.filter(function(n) {
      return n.type === "bastion";
    });
    var mCount = machines.length;
    for (var i = 0; i < mCount; i++) {
      var theta = -Math.PI / 2 + 2 * Math.PI * i / mCount;
      positions[machines[i].id] = {
        x: cx + innerRadius * Math.cos(theta),
        y: cy + innerRadius * Math.sin(theta)
      };
    }
    bastions.forEach(function(b) {
      var hostPos = positions[b.host];
      if (hostPos) {
        var dx = hostPos.x - cx;
        var dy = hostPos.y - cy;
        var len = Math.sqrt(dx * dx + dy * dy) || 1;
        positions[b.id] = {
          x: cx + outerRadius * dx / len,
          y: cy + outerRadius * dy / len
        };
      } else {
        positions[b.id] = { x: cx, y: cy + outerRadius };
      }
    });
    return positions;
  }
  function _edgePath(p1, p2, offsetSign) {
    var dx = p2.x - p1.x;
    var dy = p2.y - p1.y;
    var len = Math.sqrt(dx * dx + dy * dy);
    if (len === 0) return "M " + p1.x + " " + p1.y + " L " + p2.x + " " + p2.y;
    var nx = -dy / len;
    var ny = dx / len;
    var off = 6 * (offsetSign || 0);
    var midx = (p1.x + p2.x) / 2 + nx * off * 4;
    var midy = (p1.y + p2.y) / 2 + ny * off * 4;
    return "M " + (p1.x + nx * off) + " " + (p1.y + ny * off) + " Q " + midx + " " + midy + " " + (p2.x + nx * off) + " " + (p2.y + ny * off);
  }
  function renderConnectivityMap() {
    var msgInput2 = document.getElementById("msg-input");
    var inputHasFocus = msgInput2 && document.activeElement === msgInput2;
    var savedStart = inputHasFocus ? msgInput2.selectionStart : 0;
    var savedEnd = inputHasFocus ? msgInput2.selectionEnd : 0;
    var container = document.getElementById("connectivity-map");
    if (!container) return;
    if (!connectivityCache || !connectivityCache.nodes || connectivityCache.nodes.length === 0) {
      container.innerHTML = '<p class="empty-notice">No connectivity data.</p>';
      if (inputHasFocus && document.activeElement !== msgInput2) {
        msgInput2.focus();
        try {
          msgInput2.setSelectionRange(savedStart, savedEnd);
        } catch (_) {
        }
      }
      return;
    }
    var nodes = connectivityCache.nodes;
    var edges = connectivityCache.edges || [];
    var W = 520;
    var H = 420;
    var cx = W / 2;
    var cy = H / 2;
    var innerRadius = 100;
    var outerRadius = 190;
    var nodeR = 26;
    var bastionR = 20;
    var positions = _layoutNodes(nodes, cx, cy, innerRadius, outerRadius);
    var edgeKey = function(e) {
      return e.source + "→" + e.target;
    };
    var seen = {};
    var svgParts = [];
    svgParts.push(
      '<svg class="connectivity-svg" viewBox="0 0 ' + W + " " + H + '" width="100%" height="' + H + '">'
    );
    svgParts.push(
      '<defs><marker id="arrow-ok" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="#4ecdc4"/></marker><marker id="arrow-fail" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="#ef4444"/></marker><marker id="arrow-pending" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="#f59e0b"/></marker></defs>'
    );
    var machineNodes = nodes.filter(function(n) {
      return n.type !== "bastion";
    });
    var bastionNodes = nodes.filter(function(n) {
      return n.type === "bastion";
    });
    var bastionAnchorEdges = edges.filter(function(e) {
      return e.source.indexOf("bastion") === 0 || e.target.indexOf("bastion") === 0;
    });
    var machineEdges = edges.filter(function(e) {
      return e.source.indexOf("bastion") !== 0 && e.target.indexOf("bastion") !== 0;
    });
    bastionAnchorEdges.forEach(function(e) {
      var p1 = positions[e.source];
      var p2 = positions[e.target];
      if (!p1 || !p2) return;
      var color = e.status === "ok" ? "#4ecdc4" : e.status === "pending" ? "#f59e0b" : "#ef4444";
      var d = "M " + p1.x + " " + p1.y + " L " + p2.x + " " + p2.y;
      svgParts.push(
        '<path d="' + d + '" stroke="' + color + '" stroke-width="1" fill="none" stroke-dasharray="3 3" opacity="0.5"><title>' + escapeHtml(e.source) + " ↔ " + escapeHtml(e.target) + " (CF tunnel)</title></path>"
      );
    });
    machineEdges.forEach(function(e) {
      var p1 = positions[e.source];
      var p2 = positions[e.target];
      if (!p1 || !p2) return;
      var pair = edgeKey(e);
      var reverse = e.target + "→" + e.source;
      var sign = 0;
      if (seen[reverse]) sign = -1;
      seen[pair] = true;
      var d = _edgePath(p1, p2, sign);
      var color = e.status === "ok" ? "#4ecdc4" : "#ef4444";
      var dash = e.status === "ok" ? "" : 'stroke-dasharray="4 4"';
      var marker = e.status === "ok" ? "url(#arrow-ok)" : "url(#arrow-fail)";
      svgParts.push(
        '<path d="' + d + '" stroke="' + color + '" stroke-width="1.5" fill="none" ' + dash + ' marker-end="' + marker + '" opacity="0.75"><title>' + escapeHtml(e.source) + " → " + escapeHtml(e.target) + " (" + escapeHtml(e.status) + ", " + escapeHtml(e.method) + ")</title></path>"
      );
    });
    bastionNodes.forEach(function(n) {
      var p = positions[n.id];
      if (!p) return;
      var isPending = n.status === "pending";
      var stroke = isPending ? "#f59e0b" : "#4ecdc4";
      var fill = isPending ? "rgba(245,158,11,0.12)" : "rgba(78,205,196,0.10)";
      svgParts.push(
        '<g class="conn-node conn-node-bastion"><rect x="' + (p.x - bastionR) + '" y="' + (p.y - bastionR * 0.7) + '" width="' + bastionR * 2 + '" height="' + bastionR * 1.4 + '" rx="8" ry="8" fill="' + fill + '" stroke="' + stroke + '" stroke-width="1.5" ' + (isPending ? 'stroke-dasharray="4 2"' : "") + '/><text x="' + p.x + '" y="' + (p.y + 3) + '" text-anchor="middle" class="conn-node-label conn-bastion-label">☁ ' + escapeHtml(n.label.replace("bastion-", "")) + "</text><title>" + escapeHtml(n.label) + " — " + escapeHtml(n.role || "") + "</title></g>"
      );
    });
    machineNodes.forEach(function(n) {
      var p = positions[n.id];
      if (!p) return;
      svgParts.push(
        '<g class="conn-node" data-host-name="' + escapeHtml(n.id) + '"><circle cx="' + p.x + '" cy="' + p.y + '" r="' + nodeR + '" fill="#141414" stroke="#4ecdc4" stroke-width="2"/><text x="' + p.x + '" y="' + (p.y + 4) + '" text-anchor="middle" class="conn-node-label">' + escapeHtml(n.label) + "</text><title>" + escapeHtml(n.label) + " — " + escapeHtml(n.role || "") + "</title></g>"
      );
    });
    svgParts.push("</svg>");
    var okCount = edges.filter(function(e) {
      return e.status === "ok";
    }).length;
    var failCount = edges.filter(function(e) {
      return e.status === "fail";
    }).length;
    var pendingCount = edges.filter(function(e) {
      return e.status === "pending";
    }).length;
    var bastionLive = nodes.filter(function(n) {
      return n.type === "bastion" && n.status !== "pending";
    }).length;
    var bastionTotal = nodes.filter(function(n) {
      return n.type === "bastion";
    }).length;
    var srcLabel = connectivityCache.source === "live" ? "live" : "static";
    var pendingPill = pendingCount > 0 ? '<span class="conn-pill conn-pill-pending">☁ ' + bastionLive + "/" + bastionTotal + " CF tunnels</span>" : '<span class="conn-pill conn-pill-ok">☁ ' + bastionLive + "/" + bastionTotal + " CF tunnels</span>";
    var html = '<div class="connectivity-header"><span class="connectivity-title">SSH mesh</span><span class="connectivity-summary">' + pendingPill + '<span class="conn-pill conn-pill-ok">' + okCount + " links ok</span>" + (failCount ? '<span class="conn-pill conn-pill-fail">' + failCount + " blocked</span>" : "") + '<span class="conn-source">(' + escapeHtml(srcLabel) + ")</span></span></div>" + svgParts.join("");
    container.innerHTML = html;
    Array.prototype.forEach.call(
      container.querySelectorAll(".conn-node[data-host-name]"),
      function(g) {
        var host = g.getAttribute("data-host-name");
        g.addEventListener("mouseenter", function(ev) {
          syncHostHover(host, true);
          if (typeof showMachineTooltip === "function")
            showMachineTooltip(host, ev);
        });
        g.addEventListener("mousemove", function(ev) {
          if (typeof moveMachineTooltip === "function") moveMachineTooltip(ev);
        });
        g.addEventListener("mouseleave", function() {
          syncHostHover(host, false);
          if (typeof hideMachineTooltip === "function") hideMachineTooltip();
        });
      }
    );
    if (inputHasFocus && document.activeElement !== msgInput2) {
      msgInput2.focus();
      try {
        msgInput2.setSelectionRange(savedStart, savedEnd);
      } catch (_) {
      }
    }
  }
  document.addEventListener("DOMContentLoaded", function() {
    var btn = document.querySelector('[data-tab="resources"]');
    if (btn) {
      btn.addEventListener("click", fetchConnectivity);
    }
    setInterval(function() {
      if (connectivityCache) fetchConnectivity();
    }, 6e4);
  });
  var _overviewSort = "name";
  var _overviewView = "list";
  var _overviewColor = "name";
  var _topoSizeBy = "subscribers";
  try {
    var _savedSort = localStorage.getItem("orochi.overviewSort");
    if (_savedSort === "name" || _savedSort === "machine")
      _overviewSort = _savedSort;
    var _savedView = localStorage.getItem("orochi.overviewView");
    if (_savedView === "list" || _savedView === "tiled" || _savedView === "topology")
      _overviewView = _savedView;
    var _savedColor = localStorage.getItem("orochi.overviewColor");
    if (_savedColor === "name" || _savedColor === "host" || _savedColor === "account")
      _overviewColor = _savedColor;
    var _savedSize = localStorage.getItem("orochi.topoSizeBy");
    if (_savedSize === "equal" || _savedSize === "subscribers" || _savedSize === "posts")
      _topoSizeBy = _savedSize;
  } catch (_e) {
  }
  var _topoHidden = { agents: {}, channels: {} };
  try {
    var _topoHiddenRaw = localStorage.getItem("orochi.topoHidden");
    if (_topoHiddenRaw) {
      var _topoHiddenParsed = JSON.parse(_topoHiddenRaw);
      if (_topoHiddenParsed && typeof _topoHiddenParsed === "object") {
        _topoHidden.agents = _topoHiddenParsed.agents || {};
        _topoHidden.channels = _topoHiddenParsed.channels || {};
      }
    }
  } catch (_e) {
  }
  function _topoSaveHidden() {
    try {
      localStorage.setItem(
        "orochi.topoHidden",
        JSON.stringify({
          agents: _topoHidden.agents,
          channels: _topoHidden.channels
        })
      );
    } catch (_e) {
    }
    if (typeof _topoAutoSaveActiveSlot === "function") {
      _topoAutoSaveActiveSlot();
    }
  }
  function _topoHide(kind, name) {
    if (!kind || !name) return;
    var hn = typeof userName !== "undefined" && userName || window.__orochiUserName || "";
    if (kind === "agent" && hn && name === hn) return;
    if (kind === "agent") _topoHidden.agents[name] = true;
    else if (kind === "channel") _topoHidden.channels[name] = true;
    else return;
    _topoSaveHidden();
    if (typeof renderActivityTab === "function") renderActivityTab();
  }
  function _topoUnhide(kind, name) {
    if (kind === "agent") delete _topoHidden.agents[name];
    else if (kind === "channel") delete _topoHidden.channels[name];
    _topoSaveHidden();
    if (typeof renderActivityTab === "function") renderActivityTab();
  }
  function _topoUnhideAll() {
    _topoHidden = { agents: {}, channels: {} };
    _topoSaveHidden();
    if (typeof renderActivityTab === "function") renderActivityTab();
  }
  window._topoHide = _topoHide;
  window._topoUnhide = _topoUnhide;
  window._topoUnhideAll = _topoUnhideAll;
  var _topoManualPositions = {};
  try {
    var _topoPosRaw = localStorage.getItem("orochi.topoPositions");
    if (_topoPosRaw) {
      var _topoPosParsed = JSON.parse(_topoPosRaw);
      if (_topoPosParsed && typeof _topoPosParsed === "object") {
        _topoManualPositions = _topoPosParsed;
      }
    }
  } catch (_e) {
  }
  function _topoManualKey(kind, name) {
    return String(kind || "") + ":" + String(name || "");
  }
  function _topoSaveManualPositions() {
    try {
      localStorage.setItem(
        "orochi.topoPositions",
        JSON.stringify(_topoManualPositions)
      );
    } catch (_e) {
    }
  }
  function _topoSetManualPosition(kind, name, x, y) {
    if (!kind || !name) return;
    if (typeof x !== "number" || typeof y !== "number") return;
    _topoManualPositions[_topoManualKey(kind, name)] = { x, y };
    _topoSaveManualPositions();
  }
  function _topoClearManualPosition(kind, name) {
    delete _topoManualPositions[_topoManualKey(kind, name)];
    _topoSaveManualPositions();
  }
  window._topoSetManualPosition = _topoSetManualPosition;
  window._topoClearManualPosition = _topoClearManualPosition;
  var _TOPO_POOL_SEL_KEY = "orochi.topoPoolSelection";
  var _TOPO_POOL_MEM_KEY_LEGACY = "orochi.topoPoolMemories";
  function _topoMemWorkspaceKey() {
    var ws2 = typeof window !== "undefined" && (window.__orochiWorkspace || window.__orochiWorkspaceName) || "default";
    return "orochi.memoryslots." + String(ws2);
  }
  (function _loadPoolSel() {
    var empty = {
      agents: /* @__PURE__ */ Object.create(null),
      channels: /* @__PURE__ */ Object.create(null)
    };
    try {
      var raw = localStorage.getItem(_TOPO_POOL_SEL_KEY);
      if (!raw) return empty;
      var parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return empty;
      (parsed.agents || []).forEach(function(n) {
        if (typeof n === "string") empty.agents[n] = true;
      });
      (parsed.channels || []).forEach(function(n) {
        if (typeof n === "string") empty.channels[n] = true;
      });
    } catch (_e) {
    }
    return empty;
  })();
  (function _loadPoolMem() {
    try {
      var raw = localStorage.getItem(_topoMemWorkspaceKey());
      if (!raw) {
        raw = localStorage.getItem(_TOPO_POOL_MEM_KEY_LEGACY);
      }
      if (!raw) return {};
      var parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (_e) {
      return {};
    }
  })();
  var _TOPO_ACTIVE_MEM_KEY = "orochi.topoActiveMemSlot";
  (function() {
    try {
      var v = parseInt(localStorage.getItem(_TOPO_ACTIVE_MEM_KEY) || "", 10);
      return isFinite(v) && v >= 1 && v <= 5 ? v : null;
    } catch (_) {
      return null;
    }
  })();
  function _secondsSinceIso(iso) {
    if (!iso) return null;
    var t = Date.parse(iso);
    if (isNaN(t)) return null;
    return Math.max(0, Math.floor((Date.now() - t) / 1e3));
  }
  function _isDeadAgent(a) {
    if (!a) return false;
    var connected2 = (a.status || "online") !== "offline";
    if (!connected2) return false;
    var toolSec = typeof _secondsSinceIso === "function" ? _secondsSinceIso(a.last_tool_at) : null;
    var actSec = typeof _secondsSinceIso === "function" ? _secondsSinceIso(a.last_action) : null;
    var noTool = toolSec == null || toolSec > 180;
    var noAct = actSec == null || actSec > 180;
    return noTool && noAct;
  }
  window._isDeadAgent = _isDeadAgent;
  function _invalidateTopoPerms() {
    _topoChannelPerms = /* @__PURE__ */ Object.create(null);
    _topoChannelPermsFetchedAt = 0;
  }
  window._invalidateTopoPerms = _invalidateTopoPerms;
  function _topoPoolMemoryIsDirty$1(slot) {
    var mem = _topoPoolMemories[String(slot)];
    if (!mem) return false;
    var savedA = {};
    (mem.agents || []).forEach(function(n) {
      savedA[n] = true;
    });
    var savedC = {};
    (mem.channels || []).forEach(function(n) {
      savedC[n] = true;
    });
    var liveA = _topoPoolSelection.agents || {};
    var liveC = _topoPoolSelection.channels || {};
    var liveAKeys = Object.keys(liveA);
    var liveCKeys = Object.keys(liveC);
    if (liveAKeys.length !== Object.keys(savedA).length) return true;
    if (liveCKeys.length !== Object.keys(savedC).length) return true;
    for (var i = 0; i < liveAKeys.length; i++) {
      if (!savedA[liveAKeys[i]]) return true;
    }
    for (var j = 0; j < liveCKeys.length; j++) {
      if (!savedC[liveCKeys[j]]) return true;
    }
    return false;
  }
  function _syncMemoryDirtyIndicators$1() {
    var all = document.querySelectorAll(
      ".topo-pool-mem-btn[data-mem-slot], .sidebar-mem-btn[data-mem-slot]"
    );
    for (var i = 0; i < all.length; i++) {
      var btn = all[i];
      var slot = btn.getAttribute("data-mem-slot");
      var slotN = parseInt(slot, 10);
      btn.classList.toggle("topo-pool-mem-btn-filled", !!_topoPoolMemories[slot]);
      btn.classList.toggle("sidebar-mem-btn-filled", !!_topoPoolMemories[slot]);
      btn.classList.toggle(
        "topo-pool-mem-btn-active",
        _topoActiveMemSlot === slotN
      );
      btn.classList.toggle(
        "sidebar-mem-btn-active",
        _topoActiveMemSlot === slotN
      );
      var dirty = _topoActiveMemSlot === slotN && _topoPoolMemoryIsDirty$1(slotN);
      btn.classList.toggle("topo-pool-mem-btn-dirty", dirty);
      btn.classList.toggle("sidebar-mem-btn-dirty", dirty);
      if (dirty) {
        btn.setAttribute(
          "data-dirty-title",
          "Unsaved changes — click Save to persist"
        );
      } else {
        btn.removeAttribute("data-dirty-title");
      }
    }
  }
  window._topoPoolMemoryIsDirty = _topoPoolMemoryIsDirty$1;
  window._syncMemoryDirtyIndicators = _syncMemoryDirtyIndicators$1;
  function _topoPulseEdge(sender, channel, opts) {
    var _dbg = window.__topoPulseDebug !== false;
    if (!channel) {
      if (_dbg)
        console.warn("[topo-pulse] bail: no channel", { sender, channel });
      return;
    }
    if (!_topoSeekReplayInProgress) {
      var _now = Date.now();
      _topoSeekEvents.push({
        ts: _now,
        sender: sender || "",
        channel,
        opts: opts ? { isArtifact: !!opts.isArtifact, text: opts.text || "" } : {}
      });
      var _cutoff = _now - TOPO_SEEK_WINDOW_MS;
      while (_topoSeekEvents.length && _topoSeekEvents[0].ts < _cutoff) {
        _topoSeekEvents.shift();
      }
      if (_topoSeekMode === "live") {
        _topoSeekUpdateUI();
      }
    }
    if (_topoSeekMode === "playback" && !_topoSeekReplayInProgress) {
      return;
    }
    var svg = document.querySelector(".activity-view-topology .topo-svg");
    if (!svg) {
      if (_dbg)
        console.warn("[topo-pulse] bail: topology svg not in DOM (tab hidden?)", {
          sender,
          channel
        });
      return;
    }
    var edges = svg.querySelector(".topo-edges");
    if (!edges) {
      if (_dbg)
        console.warn("[topo-pulse] bail: .topo-edges not found", {
          sender,
          channel
        });
      return;
    }
    var klass = opts && opts.isArtifact ? "topo-packet-artifact" : "topo-packet-message";
    var babble = "";
    if (opts) {
      babble = opts.text || opts.babble || "";
    }
    var packetOpts = { text: babble };
    var LEG = 500;
    if (channel.indexOf("dm:") === 0) {
      var dmRecipients = [];
      if (channel.indexOf("dm:group:") === 0) {
        dmRecipients = channel.slice("dm:group:".length).split(",");
      } else {
        channel.slice("dm:".length).split("|").forEach(function(part) {
          if (!part) return;
          if (part.indexOf("agent:") === 0) dmRecipients.push(part.slice(6));
          else if (part.indexOf("human:") === 0)
            dmRecipients.push(part.slice(6));
          else dmRecipients.push(part);
        });
      }
      var dmFrom = sender ? _topoLastPositions.agents[sender] : null;
      if (_dbg) {
        var _sCoord = dmFrom ? "x:" + dmFrom.x.toFixed(1) + " y:" + dmFrom.y.toFixed(1) : "(not on graph)";
        console.log("coordinate sender: " + _sCoord);
      }
      if (!dmRecipients.length) {
        if (_dbg)
          console.warn("[topo-pulse] DM bail: parsed zero recipients", {
            channel
          });
        return;
      }
      if (!dmFrom) {
        if (_dbg)
          console.warn(
            "[topo-pulse] DM bail: sender not on graph. available keys:",
            Object.keys(_topoLastPositions.agents)
          );
        return;
      }
      dmRecipients.forEach(function(rn) {
        if (!rn || rn === sender) return;
        var rp = _topoLastPositions.agents[rn];
        if (_dbg) {
          console.log("DM sent from " + sender + " to " + rn);
          var _rCoord = rp ? "x:" + rp.x.toFixed(1) + " y:" + rp.y.toFixed(1) : "(not on graph)";
          console.log("coordinate receiver " + _rCoord);
        }
        if (!rp) {
          if (_dbg)
            console.warn("[topo-pulse] DM bail: recipient not on graph", {
              recipient: rn,
              channel,
              availableKeys: Object.keys(_topoLastPositions.agents)
            });
          return;
        }
        _topoSpawnPacket(edges, dmFrom, rp, LEG, 0, klass, { text: babble });
      });
      return;
    }
    var cp = _topoLastPositions.channels[channel];
    if (!cp) return;
    var ap = sender ? _topoLastPositions.agents[sender] : null;
    var leg2Delay = 0;
    if (ap) {
      _topoSpawnPacket(edges, ap, cp, LEG, 0, klass, packetOpts);
      leg2Delay = LEG;
    } else {
      _topoSpawnPacket(edges, cp, cp, 180, 0, klass, packetOpts);
    }
    var humanKey = typeof userName !== "undefined" && userName || window.__orochiUserName || "";
    var subscribers = Object.keys(_topoLastPositions.agents).filter(function(n) {
      if (n === sender) return false;
      if (humanKey && n === humanKey) return true;
      var ag = (window.__lastAgents || []).find(function(x) {
        return x.name === n;
      });
      return ag && Array.isArray(ag.channels) && ag.channels.indexOf(channel) !== -1;
    });
    subscribers.forEach(function(n) {
      var target = _topoLastPositions.agents[n];
      if (!target) return;
      _topoSpawnPacket(edges, cp, target, LEG, leg2Delay, klass, packetOpts);
    });
  }
  window._topoPulseEdge = _topoPulseEdge;
  document.addEventListener("DOMContentLoaded", function() {
    var btn = document.querySelector('[data-tab="activity"]');
    if (btn) {
      btn.addEventListener("click", function() {
        refreshActivityFromApi();
        startActivityAutoRefresh();
      });
    }
  });
  function _buildSidebarMemoryDropdownOptions() {
    var max = typeof _TOPO_POOL_MEM_MAX !== "undefined" ? _TOPO_POOL_MEM_MAX : 5;
    var active = _topoActiveMemSlot;
    var parts = [];
    var noneSel = active == null ? ' selected="selected"' : "";
    parts.push('<option value=""' + noneSel + ">No memory</option>");
    var firstFree = 0;
    for (var slot = 1; slot <= max; slot++) {
      var mem = _topoPoolMemories ? _topoPoolMemories[String(slot)] : null;
      if (!mem && firstFree === 0) firstFree = slot;
      var label = mem && mem.label ? String(mem.label) : "";
      var count = mem ? (mem.agents || []).length + (mem.channels || []).length : 0;
      var isActive = active === slot;
      var dirty = isActive && typeof _topoPoolMemoryIsDirty === "function" && _topoPoolMemoryIsDirty(slot);
      var face;
      if (mem) {
        face = "M" + slot;
        if (label) face += " · " + label;
        if (count > 0) face += " (" + count + ")";
      } else {
        face = "M" + slot + " (empty)";
      }
      if (dirty) face += " ●";
      var sel = isActive ? ' selected="selected"' : "";
      parts.push(
        '<option value="' + slot + '"' + sel + ">" + escapeHtml(face) + "</option>"
      );
    }
    if (firstFree > 0) {
      parts.push('<option value="__new__">+ Create new</option>');
    } else {
      parts.push('<option value="__full__" disabled>(all slots full)</option>');
    }
    return parts.join("");
  }
  function _buildSidebarMemoryChipsHtml() {
    var html = "";
    var max = typeof _TOPO_POOL_MEM_MAX !== "undefined" ? _TOPO_POOL_MEM_MAX : 5;
    for (var slot = 1; slot <= max; slot++) {
      var mem = _topoPoolMemories ? _topoPoolMemories[String(slot)] : null;
      var count = mem ? (mem.agents || []).length + (mem.channels || []).length : 0;
      var hiddenCount = mem && mem.hidden ? (mem.hidden.agents || []).length + (mem.hidden.channels || []).length : 0;
      var filterActive = !!(mem && mem.filter && (mem.filter.input && mem.filter.input.length || Array.isArray(mem.filter.tags) && mem.filter.tags.length));
      var label = mem && mem.label ? String(mem.label) : "";
      var active = _topoActiveMemSlot === slot;
      var dirty = active && typeof _topoPoolMemoryIsDirty === "function" && _topoPoolMemoryIsDirty(slot);
      var face;
      if (label) {
        face = label.length > 6 ? label.slice(0, 5) + "…" : label;
      } else if (mem && count > 0) {
        face = "M" + slot + "·" + count;
      } else {
        face = "M" + slot;
      }
      var dirtyDot = dirty ? " ●" : "";
      var title;
      if (mem) {
        var parts = [];
        parts.push(count + " selected");
        if (hiddenCount) parts.push(hiddenCount + " hidden");
        if (filterActive) parts.push("filter");
        title = "Recall M" + slot + (label ? " — " + label : "") + " (" + parts.join(", ") + "). Shift+click to overwrite, right-click to rename or clear.";
      } else {
        title = "M" + slot + " (empty). Click Save below, or shift-click this chip, to snapshot the current selection.";
      }
      if (dirty) title += "\n\nUnsaved changes — click Save to persist";
      var cls = "sidebar-mem-btn sidebar-mem-chip";
      if (mem) cls += " sidebar-mem-btn-filled sidebar-mem-chip-filled";
      if (label) cls += " sidebar-mem-chip-labeled";
      if (active) cls += " sidebar-mem-btn-active sidebar-mem-chip-active";
      if (dirty) cls += " sidebar-mem-btn-dirty sidebar-mem-chip-dirty";
      html += '<button type="button" class="' + cls + '" data-mem-slot="' + slot + '" title="' + escapeHtml(title) + '">' + escapeHtml(face) + dirtyDot + "</button>";
    }
    return html;
  }
  function renderSidebarMemory() {
    var host = document.getElementById("sidebar-memory");
    if (!host) return;
    var selectEl = host.querySelector("#sidebar-mem-select");
    if (selectEl) {
      selectEl.innerHTML = _buildSidebarMemoryDropdownOptions();
    }
    var slotsEl = host.querySelector(".sidebar-memory-slots");
    if (slotsEl && !selectEl) {
      slotsEl.innerHTML = _buildSidebarMemoryChipsHtml();
    }
    var saveBtn = host.querySelector(
      '.sidebar-memory-actions button[data-action="save"]'
    );
    if (saveBtn) {
      var hasSel = typeof _topoPoolSelectionSize === "function" && _topoPoolSelectionSize() > 0;
      saveBtn.classList.toggle(
        "sidebar-mem-btn-armed",
        hasSel || _topoActiveMemSlot != null
      );
      saveBtn.textContent = _topoActiveMemSlot != null ? "Save to M" + _topoActiveMemSlot : "Save";
    }
  }
  window.renderSidebarMemory = renderSidebarMemory;
  function _sidebarMemoryShowHint(anchor, text) {
    if (!anchor) return;
    var old = document.querySelector(".sidebar-mem-hint");
    if (old && old.parentNode) old.parentNode.removeChild(old);
    var bubble = document.createElement("div");
    bubble.className = "sidebar-mem-hint";
    bubble.textContent = text;
    document.body.appendChild(bubble);
    var r = anchor.getBoundingClientRect();
    bubble.style.position = "fixed";
    bubble.style.left = Math.round(r.left) + "px";
    bubble.style.top = Math.round(r.bottom + 4) + "px";
    setTimeout(function() {
      if (bubble && bubble.parentNode) bubble.parentNode.removeChild(bubble);
    }, 1800);
  }
  function _sidebarMemoryRefreshBothSurfaces() {
    renderSidebarMemory();
    if (typeof _topoLastSig !== "undefined") _topoLastSig = "";
    if (typeof renderActivityTab === "function") {
      renderActivityTab();
    }
    if (typeof _topoPoolSelectionPaint === "function") {
      _topoPoolSelectionPaint(document);
    }
    if (typeof _syncMemoryDirtyIndicators === "function") {
      _syncMemoryDirtyIndicators();
    }
  }
  function _wireSidebarMemory() {
    var host = document.getElementById("sidebar-memory");
    if (!host) return;
    if (host._mwWired) return;
    host._mwWired = true;
    var selectEl = host.querySelector("#sidebar-mem-select");
    if (selectEl) {
      selectEl.addEventListener("change", function(ev) {
        var val = selectEl.value;
        var prevSlot = _topoActiveMemSlot;
        var prevDirty = prevSlot != null && typeof _topoPoolMemoryIsDirty === "function" && _topoPoolMemoryIsDirty(prevSlot);
        if (prevDirty) {
          var ok = false;
          try {
            ok = window.confirm(
              "M" + prevSlot + " has unsaved changes. Discard them and switch?"
            );
          } catch (_e) {
            ok = false;
          }
          if (!ok) {
            _sidebarMemoryRefreshBothSurfaces();
            return;
          }
        }
        if (val === "") {
          _topoActiveMemSlot = null;
          if (typeof _topoPoolSelectClear === "function") {
            _topoPoolSelectClear();
          }
        } else if (val === "__new__") {
          var max = typeof _TOPO_POOL_MEM_MAX !== "undefined" ? _TOPO_POOL_MEM_MAX : 5;
          var free = 0;
          for (var i = 1; i <= max; i++) {
            if (!(_topoPoolMemories && _topoPoolMemories[String(i)])) {
              free = i;
              break;
            }
          }
          if (free === 0) {
            _sidebarMemoryShowHint(selectEl, "All slots full");
            _sidebarMemoryRefreshBothSurfaces();
            return;
          }
          var label = null;
          try {
            label = window.prompt(
              "Name for M" + free + " (blank = unnamed):",
              ""
            );
          } catch (_e) {
            label = null;
          }
          if (label === null) {
            _sidebarMemoryRefreshBothSurfaces();
            return;
          }
          _topoActiveMemSlot = free;
          if (typeof _topoPoolSelectClear === "function") {
            _topoPoolSelectClear();
          }
          if (String(label).trim() !== "" && typeof _topoPoolMemoryRename === "function") {
            if (typeof _topoPoolMemorySave === "function") {
              _topoPoolMemorySave(free);
            }
            _topoPoolMemoryRename(free, String(label).trim());
          }
        } else {
          var slotN = parseInt(val, 10);
          if (slotN >= 1) {
            _topoActiveMemSlot = slotN;
            if (_topoPoolMemories && _topoPoolMemories[String(slotN)] && typeof _topoPoolMemoryRecall === "function") {
              _topoPoolMemoryRecall(slotN);
            }
          }
        }
        if (typeof _topoPersistActiveMemSlot === "function") {
          _topoPersistActiveMemSlot();
        }
        _sidebarMemoryRefreshBothSurfaces();
        ev.stopPropagation();
      });
    }
    host.addEventListener("click", function(ev) {
      var chip = ev.target.closest(".sidebar-mem-btn[data-mem-slot]");
      if (chip && host.contains(chip)) {
        var slotN = parseInt(chip.getAttribute("data-mem-slot"), 10);
        var max = typeof _TOPO_POOL_MEM_MAX !== "undefined" ? _TOPO_POOL_MEM_MAX : 5;
        if (!(slotN >= 1 && slotN <= max)) return;
        if (ev.shiftKey) {
          if (typeof _topoPoolMemorySave === "function") {
            _topoPoolMemorySave(slotN);
          }
        } else {
          if (_topoActiveMemSlot === slotN) {
            _topoActiveMemSlot = null;
          } else {
            _topoActiveMemSlot = slotN;
            if (_topoPoolMemories && _topoPoolMemories[String(slotN)] && typeof _topoPoolMemoryRecall === "function") {
              _topoPoolMemoryRecall(slotN);
            }
          }
          if (typeof _topoPersistActiveMemSlot === "function") {
            _topoPersistActiveMemSlot();
          }
        }
        ev.stopPropagation();
        _sidebarMemoryRefreshBothSurfaces();
        return;
      }
      var actBtn = ev.target.closest(
        ".sidebar-memory-actions button[data-action]"
      );
      if (actBtn && host.contains(actBtn)) {
        var action = actBtn.getAttribute("data-action");
        if (action === "none") {
          _topoActiveMemSlot = null;
          if (typeof _topoPersistActiveMemSlot === "function") {
            _topoPersistActiveMemSlot();
          }
          if (typeof _topoPoolSelectClear === "function") {
            _topoPoolSelectClear();
          }
        } else if (action === "select-all") {
          if (typeof _topoPoolSelectAll === "function") {
            var grid = document.getElementById("activity-grid");
            _topoPoolSelectAll(grid || document);
          }
        } else if (action === "deselect-all") {
          if (typeof _topoPoolSelectClear === "function") {
            _topoPoolSelectClear();
          }
        } else if (action === "save") {
          if (_topoActiveMemSlot == null) {
            _sidebarMemoryShowHint(actBtn, "Pick an M-slot first");
            ev.stopPropagation();
            return;
          }
          if (typeof _topoPoolMemorySave === "function") {
            _topoPoolMemorySave(_topoActiveMemSlot);
          }
        }
        ev.stopPropagation();
        _sidebarMemoryRefreshBothSurfaces();
        return;
      }
    });
    host.addEventListener("contextmenu", function(ev) {
      if (ev.shiftKey) return;
      var chip = ev.target.closest(".sidebar-mem-btn[data-mem-slot]");
      if (!chip || !host.contains(chip)) return;
      var slotN = parseInt(chip.getAttribute("data-mem-slot"), 10);
      var max = typeof _TOPO_POOL_MEM_MAX !== "undefined" ? _TOPO_POOL_MEM_MAX : 5;
      if (!(slotN >= 1 && slotN <= max)) return;
      var mem = _topoPoolMemories && _topoPoolMemories[String(slotN)];
      if (!mem) return;
      ev.preventDefault();
      ev.stopPropagation();
      var curLabel = mem.label && typeof mem.label === "string" ? mem.label : "";
      var answer = null;
      try {
        answer = window.prompt(
          "Rename M" + slotN + " (leave empty to clear the slot):",
          curLabel
        );
      } catch (_e) {
        answer = null;
      }
      if (answer === null) return;
      var trimmed = String(answer).trim();
      if (trimmed === "") {
        if (typeof _topoPoolMemoryDelete === "function") {
          _topoPoolMemoryDelete(slotN);
        }
      } else {
        if (typeof _topoPoolMemoryRename === "function") {
          _topoPoolMemoryRename(slotN, trimmed);
        }
      }
      _sidebarMemoryRefreshBothSurfaces();
    });
  }
  document.addEventListener("DOMContentLoaded", function() {
    _wireSidebarMemory();
    renderSidebarMemory();
  });
  var _vizPollTimer = null;
  var _vizCachedData = null;
  var _vizCachedAt = 0;
  var _VIZ_FRESH_MS = 6e4;
  var _vizRenderedSig = "";
  function _vizSig(data) {
    try {
      var daily = data && data.daily_velocity || [];
      var totals = data && data.totals || {};
      return String(totals.open || 0) + ":" + String(totals.closed || 0) + ":" + daily.length + ":" + (daily.length ? daily[daily.length - 1].date + "/" + daily[daily.length - 1].opened + "/" + daily[daily.length - 1].closed : "");
    } catch (_) {
      return String(Date.now());
    }
  }
  function renderVizTab$1() {
    var container = document.getElementById("viz-content");
    if (!container) return;
    if (_vizCachedData) {
      _vizRenderedSig = "";
      _renderVizPayload(_vizCachedData, container);
    } else if (!container.innerHTML) {
      container.innerHTML = _buildVizSkeleton();
    }
    if (Date.now() - _vizCachedAt > _VIZ_FRESH_MS) {
      fetchVizPayload();
    }
    if (_vizPollTimer) clearInterval(_vizPollTimer);
    _vizPollTimer = setInterval(fetchVizPayload, _VIZ_FRESH_MS);
  }
  function _buildVizSkeleton() {
    return '<div class="viz-card viz-skeleton" aria-busy="true"><h3>TODO progress</h3><div class="viz-skel-chart"></div><div class="viz-skel-legend"><span class="viz-skel-pill"></span><span class="viz-skel-pill"></span><span class="viz-skel-pill"></span></div><div class="viz-skel-kpis"><span class="viz-skel-kpi"></span><span class="viz-skel-kpi"></span><span class="viz-skel-kpi"></span><span class="viz-skel-kpi"></span></div><p class="empty-notice viz-skel-note">Loading visualization&hellip;</p></div>';
  }
  function stopVizTab$1() {
    if (_vizPollTimer) {
      clearInterval(_vizPollTimer);
      _vizPollTimer = null;
    }
  }
  async function fetchVizPayload() {
    var container = document.getElementById("viz-content");
    if (!container) return;
    try {
      var res = await fetch(apiUrl("/api/todo/stats/"), {
        credentials: "same-origin"
      });
      if (!res.ok) {
        if (!_vizCachedData) {
          container.innerHTML = '<p class="empty-notice">Failed to load stats (HTTP ' + res.status + ").</p>";
        }
        return;
      }
      var data = await res.json();
      _vizCachedData = data;
      _vizCachedAt = Date.now();
      _renderVizPayload(data, container);
    } catch (e) {
      if (!_vizCachedData) {
        container.innerHTML = '<p class="empty-notice">Error: ' + escapeHtml(String(e)) + "</p>";
      }
    }
  }
  function _renderVizPayload(data, container) {
    var sig = _vizSig(data);
    if (sig && sig === _vizRenderedSig) return;
    _vizRenderedSig = sig;
    var daily = data && data.daily_velocity || [];
    var totals = data && data.totals || { open: 0, closed: 0 };
    if (!daily.length) {
      container.innerHTML = '<p class="empty-notice">No velocity data in window.</p>';
      return;
    }
    var pts = daily.map(function(d) {
      return {
        date: d.date,
        opened: Number(d.opened) || 0,
        closed: Number(d.closed) || 0
      };
    });
    var cumOpened = 0;
    var cumClosed = 0;
    var series = pts.map(function(p) {
      cumOpened += p.opened;
      cumClosed += p.closed;
      return {
        date: p.date,
        n_opened: cumOpened,
        n_closed: cumClosed,
        backlog: cumOpened - cumClosed
      };
    });
    var sumOpened = cumOpened;
    var sumClosed = cumClosed;
    var days = series.length;
    var avgOpen = days ? (sumOpened / days).toFixed(1) : "0";
    var avgClose = days ? (sumClosed / days).toFixed(1) : "0";
    var kpiHtml = '<div class="viz-kpis"><span>Total open<br><span class="viz-kpi-value">' + totals.open + '</span></span><span>Total closed<br><span class="viz-kpi-value">' + totals.closed + "</span></span><span>" + days + '-day opened<br><span class="viz-kpi-value">' + sumOpened + "</span></span><span>" + days + '-day closed<br><span class="viz-kpi-value">' + sumClosed + '</span></span><span>Avg opened/day<br><span class="viz-kpi-value">' + avgOpen + '</span></span><span>Avg closed/day<br><span class="viz-kpi-value">' + avgClose + "</span></span></div>";
    var svg = _buildLineChartSVG(series);
    var legend = '<div class="viz-legend"><span><span class="viz-legend-dot" style="background:#4ea0ff"></span>n_opened (cumulative)</span><span><span class="viz-legend-dot" style="background:#4ecdc4"></span>n_closed (cumulative)</span><span><span class="viz-legend-dot" style="background:#f5a623"></span>backlog (opened − closed)</span></div>';
    container.innerHTML = '<div class="viz-card"><h3>TODO progress (' + days + "-day window)</h3>" + svg + legend + kpiHtml + '<p class="empty-notice" style="margin-top:8px;font-size:11px"><!-- hook-bypass: inline-style -->Data refreshed ' + escapeHtml(_fmtTs(data.ts)) + " · auto-refresh every 60s.</p></div>";
  }
  if (typeof document !== "undefined") {
    document.addEventListener("DOMContentLoaded", function() {
      setTimeout(function() {
        if (typeof fetchVizPayload === "function") fetchVizPayload();
      }, 1e3);
    });
  }
  function _fmtTs(iso) {
    if (!iso) return "(unknown)";
    try {
      var d = new Date(iso);
      return d.toLocaleString();
    } catch (_) {
      return iso;
    }
  }
  function _buildLineChartSVG(series) {
    var W = 1200;
    var H = 360;
    var padL = 54;
    var padR = 20;
    var padT = 16;
    var padB = 40;
    var innerW = W - padL - padR;
    var innerH = H - padT - padB;
    var n = series.length;
    var yMin = 0;
    var yMax = 0;
    series.forEach(function(s) {
      if (s.n_opened > yMax) yMax = s.n_opened;
      if (s.n_closed > yMax) yMax = s.n_closed;
      if (s.backlog > yMax) yMax = s.backlog;
      if (s.backlog < yMin) yMin = s.backlog;
    });
    if (yMax === yMin) yMax = yMin + 1;
    var span = yMax - yMin;
    yMax += span * 0.1;
    function x(i) {
      return padL + (n <= 1 ? innerW / 2 : i / (n - 1) * innerW);
    }
    function y(v) {
      return padT + innerH - (v - yMin) / (yMax - yMin) * innerH;
    }
    function path(key, color) {
      var d = series.map(function(s, i) {
        return (i === 0 ? "M" : "L") + x(i).toFixed(1) + "," + y(s[key]).toFixed(1);
      }).join(" ");
      return '<path d="' + d + '" fill="none" stroke="' + color + '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>';
    }
    var grid = "";
    for (var gi = 0; gi <= 4; gi++) {
      var gy = padT + innerH * gi / 4;
      var yVal = yMax - (yMax - yMin) * gi / 4;
      grid += '<line class="viz-gridline" x1="' + padL + '" x2="' + (padL + innerW) + '" y1="' + gy + '" y2="' + gy + '"/><text x="' + (padL - 6) + '" y="' + (gy + 3) + '" text-anchor="end" fill="#888" font-size="10">' + Math.round(yVal) + "</text>";
    }
    var step = Math.max(1, Math.ceil(n / 7));
    var xAxis = "";
    for (var xi = 0; xi < n; xi += step) {
      var label = series[xi].date.slice(5);
      xAxis += '<text x="' + x(xi).toFixed(1) + '" y="' + (padT + innerH + 16) + '" text-anchor="middle" fill="#888" font-size="10">' + label + "</text>";
    }
    var axisBox = '<line x1="' + padL + '" y1="' + (padT + innerH) + '" x2="' + (padL + innerW) + '" y2="' + (padT + innerH) + '" stroke="#333"/>';
    return '<svg class="viz-svg" viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="xMidYMid meet">' + grid + axisBox + xAxis + path("n_opened", "#4ea0ff") + path("n_closed", "#4ecdc4") + path("backlog", "#f5a623") + "</svg>";
  }
  window.renderVizTab = renderVizTab$1;
  window.stopVizTab = stopVizTab$1;
  (function() {
    var fileInput = document.getElementById("file-input");
    if (fileInput && !fileInput.hasAttribute("multiple")) {
      fileInput.setAttribute("multiple", "multiple");
    }
  })();
  var pendingAttachments = [];
  var _attachmentTray = null;
  function _ensureAttachmentTray() {
    if (_attachmentTray) return _attachmentTray;
    var inputBar = document.querySelector(".input-bar");
    if (!inputBar) return null;
    _attachmentTray = document.createElement("div");
    _attachmentTray.id = "pending-attachments";
    _attachmentTray.className = "pending-attachments";
    if (inputBar.firstChild) {
      inputBar.insertBefore(_attachmentTray, inputBar.firstChild);
    } else {
      inputBar.appendChild(_attachmentTray);
    }
    return _attachmentTray;
  }
  function _renderAttachmentTray() {
    var msgInput2 = document.getElementById("msg-input");
    var inputHasFocus = msgInput2 && document.activeElement === msgInput2;
    var savedStart = inputHasFocus ? msgInput2.selectionStart : 0;
    var savedEnd = inputHasFocus ? msgInput2.selectionEnd : 0;
    var tray = _ensureAttachmentTray();
    if (!tray) return;
    if (!pendingAttachments.length) {
      tray.style.display = "none";
      tray.innerHTML = "";
      if (inputHasFocus && document.activeElement !== msgInput2) {
        msgInput2.focus();
        try {
          msgInput2.setSelectionRange(savedStart, savedEnd);
        } catch (_) {
        }
      }
      return;
    }
    tray.style.display = "flex";
    tray.innerHTML = "";
    pendingAttachments.forEach(function(p, idx) {
      var item = document.createElement("div");
      item.className = "pending-attachment";
      var isImage = p.uploaded && p.uploaded.mime_type && p.uploaded.mime_type.indexOf("image/") === 0;
      var thumb;
      if (isImage) {
        thumb = document.createElement("img");
        thumb.src = p.uploaded.url;
        thumb.className = "pending-attachment-thumb";
        thumb.alt = p.uploaded.filename || "image";
      } else {
        thumb = document.createElement("span");
        thumb.className = "pending-attachment-icon";
        thumb.textContent = "📎";
      }
      var label = document.createElement("span");
      label.className = "pending-attachment-label";
      label.textContent = p.uploaded && p.uploaded.filename || p.file.name;
      var remove = document.createElement("button");
      remove.type = "button";
      remove.className = "pending-attachment-remove";
      remove.title = "Remove";
      remove.textContent = "✕";
      remove.addEventListener("click", function() {
        pendingAttachments.splice(idx, 1);
        _renderAttachmentTray();
      });
      item.appendChild(thumb);
      item.appendChild(label);
      item.appendChild(remove);
      tray.appendChild(item);
    });
    if (inputHasFocus && document.activeElement !== msgInput2) {
      msgInput2.focus();
      try {
        msgInput2.setSelectionRange(savedStart, savedEnd);
      } catch (_) {
      }
    }
  }
  document.getElementById("msg-attach").addEventListener("click", function() {
    document.getElementById("file-input").click();
  });
  document.addEventListener("keydown", function(e) {
    var isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
    if (!((isMac ? e.metaKey : e.ctrlKey) && e.key === "u")) return;
    var tag = document.activeElement && document.activeElement.tagName;
    var onComposer = document.activeElement && document.activeElement.id === "msg-input";
    var onOtherInput = (tag === "INPUT" || tag === "TEXTAREA") && !onComposer;
    if (onOtherInput) return;
    e.preventDefault();
    document.getElementById("file-input").click();
  });
  document.getElementById("file-input").addEventListener("change", async function() {
    if (!this.files || this.files.length === 0) return;
    var arr = Array.prototype.slice.call(this.files);
    await stageFiles$1(arr);
    this.value = "";
  });
  async function stageFiles$1(files) {
    if (!files || files.length === 0) return;
    console.log("[orochi-upload] stageFiles:", files.length);
    var formData = new FormData();
    files.forEach(function(f) {
      formData.append("file", f);
    });
    try {
      var headers = {};
      if (typeof csrfToken !== "undefined" && csrfToken) {
        headers["X-CSRFToken"] = csrfToken;
      }
      var res = await fetch(apiUrl("/api/upload"), {
        method: "POST",
        headers,
        credentials: "same-origin",
        body: formData
      });
      if (!res.ok) {
        console.error("[orochi-upload] upload failed:", res.status);
        return;
      }
      var result = await res.json();
      var uploaded = result && result.files || (result && result.url ? [result] : []);
      uploaded.forEach(function(u, i) {
        pendingAttachments.push({ file: files[i] || files[0], uploaded: u });
      });
      _renderAttachmentTray();
    } catch (e) {
      console.error("[orochi-upload] stage error:", e);
    }
  }
  var msgInput = document.getElementById("msg-input");
  msgInput.addEventListener("dragover", function(e) {
    e.preventDefault();
    this.classList.add("drag-over");
  });
  msgInput.addEventListener("dragleave", function() {
    this.classList.remove("drag-over");
  });
  msgInput.addEventListener("drop", function(e) {
    e.preventDefault();
    this.classList.remove("drag-over");
    var files = e.dataTransfer.files;
    if (files && files.length) {
      stageFiles$1(Array.prototype.slice.call(files));
    }
  });
  var PASTE_TEXT_ATTACH_MIN_CHARS = 1500;
  var PASTE_TEXT_ATTACH_MIN_LINES = 25;
  function _pastedTextShouldAttach(text) {
    if (!text) return false;
    if (text.length >= PASTE_TEXT_ATTACH_MIN_CHARS) return true;
    var newlines = 0;
    for (var i = 0; i < text.length && newlines < PASTE_TEXT_ATTACH_MIN_LINES; i++) {
      if (text.charCodeAt(i) === 10) newlines++;
    }
    return newlines >= PASTE_TEXT_ATTACH_MIN_LINES;
  }
  function _buildPastedTextFile(text) {
    var ext = ".txt";
    var mime = "text/plain";
    var trimmed = text.trim();
    if (/^\s*[\{\[]/.test(trimmed) && /[\}\]]\s*$/.test(trimmed)) {
      try {
        JSON.parse(trimmed);
        ext = ".json";
        mime = "application/json";
      } catch (_) {
      }
    } else if (/^(diff --git|---\s|\+\+\+\s|@@\s)/m.test(trimmed)) {
      ext = ".patch";
      mime = "text/x-diff";
    } else if (/^(def |class |import |from \S+ import )/m.test(trimmed)) {
      ext = ".py";
      mime = "text/x-python";
    } else if (/^(Traceback \(most recent call last\)|\s+at .+\(.+:\d+:\d+\))/m.test(
      trimmed
    )) {
      ext = ".log";
      mime = "text/plain";
    }
    var ts = (/* @__PURE__ */ new Date()).toISOString().replace(/[:.]/g, "-").replace("T", "_").slice(0, 19);
    var name = "pasted-" + ts + ext;
    try {
      return new File([text], name, { type: mime });
    } catch (_) {
      var blob = new Blob([text], { type: mime });
      blob.name = name;
      return blob;
    }
  }
  function handleClipboardPaste(e) {
    var cd = e.clipboardData || e.originalEvent && e.originalEvent.clipboardData;
    if (!cd) return;
    var collected = [];
    var seen = /* @__PURE__ */ new Set();
    function pushUnique(f) {
      if (!f || !f.type || f.type.indexOf("image/") !== 0) return;
      var key = f.name + "|" + f.size + "|" + f.type + "|" + (f.lastModified || 0);
      if (seen.has(key)) return;
      seen.add(key);
      collected.push(f);
    }
    var fileList = cd.files;
    if (fileList && fileList.length) {
      for (var i = 0; i < fileList.length; i++) pushUnique(fileList[i]);
    } else if (cd.items) {
      for (var j = 0; j < cd.items.length; j++) {
        var it = cd.items[j];
        if (it && it.type && it.type.indexOf("image/") === 0) {
          pushUnique(it.getAsFile());
        }
      }
    }
    var text = "";
    try {
      text = cd.getData("text/plain") || "";
    } catch (_) {
      text = "";
    }
    var attachText = _pastedTextShouldAttach(text);
    if (collected.length > 0 || attachText) {
      e.preventDefault();
      if (attachText) {
        collected.push(_buildPastedTextFile(text));
        console.log(
          "[orochi-upload] staging pasted text as attachment:",
          text.length,
          "chars"
        );
      }
      if (collected.length > 0) {
        console.log(
          "[orochi-upload] staging",
          collected.length,
          "pasted item(s)"
        );
        stageFiles$1(collected);
      }
    }
  }
  msgInput.addEventListener("paste", handleClipboardPaste);
  function renderFilesGrid() {
    var msgInput2 = document.getElementById("msg-input");
    var inputHasFocus = msgInput2 && document.activeElement === msgInput2;
    var savedStart = inputHasFocus ? msgInput2.selectionStart : 0;
    var savedEnd = inputHasFocus ? msgInput2.selectionEnd : 0;
    var grid = document.getElementById("files-grid");
    if (!grid) return;
    var items = filesCache.filter(function(i) {
      return matchesFilter(i) && filesMatchQuery(i);
    });
    imgViewerImages = items.filter(function(i) {
      return mimeCategory(i.mime_type) === "image";
    }).map(function(i) {
      return { url: i.url, filename: i.filename };
    });
    if (items.length === 0) {
      grid.innerHTML = '<p class="empty-notice">No files yet. Upload via the chat input (attach, drag, or paste).</p>';
      if (inputHasFocus && document.activeElement !== msgInput2) {
        msgInput2.focus();
        try {
          msgInput2.setSelectionRange(savedStart, savedEnd);
        } catch (_) {
        }
      }
      return;
    }
    var selectedHtml = filesSelected.size > 0 ? '<div class="files-selection-bar"><span>' + filesSelected.size + " file" + (filesSelected.size !== 1 ? "s" : "") + ' selected</span><button type="button" class="files-dl-btn" onclick="filesDownloadSelected()">Download selected</button><button type="button" class="files-clear-btn" onclick="filesClearSelection()">Clear</button></div>' : "";
    function _catIcon(cat) {
      return cat === "image" ? "🖼" : cat === "application/pdf" ? "📄" : cat === "video" ? "🎬" : cat === "audio" ? "🎵" : "📁";
    }
    if (filesViewMode === "tiles") {
      grid.className = "files-tiles";
      grid.innerHTML = selectedHtml + items.map(function(item) {
        var cacheIdx = filesCache.indexOf(item);
        var isSelected = filesSelected.has(cacheIdx);
        var cat = mimeCategory(item.mime_type);
        var senderColor = getAgentColor(item.sender);
        var thumb = cat === "image" ? '<img class="files-tile-thumb" src="' + escapeHtml(item.url) + '" alt="" loading="lazy">' : cat === "application/pdf" ? '<div class="files-tile-icon" data-pdf-thumb-url="' + escapeHtml(item.url) + '">' + _catIcon(cat) + "</div>" : '<div class="files-tile-icon">' + _catIcon(cat) + "</div>";
        return '<div class="files-tile' + (isSelected ? " file-card-selected" : "") + '" onclick="filesHandleClick(event,' + cacheIdx + ')">' + thumb + '<div class="files-tile-body"><div class="files-tile-name">' + escapeHtml(item.filename || "file") + '</div><div class="files-tile-meta">' + escapeHtml(item.mime_type || "") + (item.size ? " &middot; " + escapeHtml(formatFileSize(item.size)) : "") + '</div><div class="files-tile-sub" style="color:' + senderColor + '">' + escapeHtml(cleanAgentName(item.sender)) + " &middot; " + escapeHtml(timeAgo(item.ts) || "") + "</div></div></div>";
      }).join("");
      if (window.pdfThumb) window.pdfThumb.hydrateAll(grid);
      return;
    }
    if (filesViewMode === "list" || filesViewMode === "details") {
      var isDetails = filesViewMode === "details";
      grid.className = "files-list" + (isDetails ? " files-list-details" : "");
      grid.innerHTML = selectedHtml + '<table class="files-list-table"><thead><tr><th></th><th>Name</th><th>Type</th><th>Size</th><th>Sender</th>' + (isDetails ? "<th>Channel</th>" : "") + "<th>When</th></tr></thead><tbody>" + items.map(function(item) {
        var cacheIdx = filesCache.indexOf(item);
        var isSelected = filesSelected.has(cacheIdx);
        var cat = mimeCategory(item.mime_type);
        var icon = cat === "image" ? "🖼" : cat === "application/pdf" ? "📄" : cat === "video" ? "🎬" : cat === "audio" ? "🎵" : "📁";
        var senderColor = getAgentColor(item.sender);
        return '<tr class="files-list-row' + (isSelected ? " file-card-selected" : "") + '" onclick="filesHandleClick(event,' + cacheIdx + ')"><td class="flt-icon">' + icon + '</td><td class="flt-name"><a href="' + escapeHtml(item.url) + '" download onclick="event.stopPropagation()" target="_blank">' + escapeHtml(item.filename || "file") + '</a></td><td class="flt-mime">' + escapeHtml(
          (item.mime_type || "").split("/")[1] || item.mime_type || ""
        ) + '</td><td class="flt-size">' + escapeHtml(formatFileSize(item.size)) + '</td><td class="flt-sender" style="color:' + senderColor + '">' + escapeHtml(cleanAgentName(item.sender)) + "</td>" + (isDetails ? '<td class="flt-channel">' + escapeHtml(item.channel || "") + "</td>" : "") + '<td class="flt-when">' + escapeHtml(timeAgo(item.ts) || "") + "</td></tr>";
      }).join("") + "</tbody></table>";
      return;
    }
    grid.className = "files-grid";
    grid.innerHTML = selectedHtml + items.map(function(item, _idx) {
      var cacheIdx = filesCache.indexOf(item);
      var isSelected = filesSelected.has(cacheIdx);
      var senderColor = getAgentColor(item.sender);
      var when = timeAgo(item.ts) || "";
      var sizeStr = formatFileSize(item.size);
      var meta = [];
      if (item.channel) meta.push(escapeHtml(item.channel));
      if (sizeStr) meta.push(escapeHtml(sizeStr));
      if (item.mime_type) meta.push(escapeHtml(item.mime_type));
      var isImg = mimeCategory(item.mime_type) === "image";
      var imgClickAttr = isImg ? 'onclick="event.preventDefault();event.stopPropagation();openImgViewer(' + JSON.stringify(item.url) + "," + JSON.stringify(item.filename || "") + ',imgViewerImages)"' : "";
      var previewHtml = isImg ? '<a href="' + escapeHtml(item.url) + '" class="file-preview-link" ' + imgClickAttr + '><img class="file-preview-img" src="' + escapeHtml(item.url) + '" alt="' + escapeHtml(item.filename || "") + '" loading="lazy"></a>' : renderFilePreview(item);
      return '<div class="file-card' + (isSelected ? " file-card-selected" : "") + '" data-cache-idx="' + cacheIdx + '" onclick="filesHandleClick(event, ' + cacheIdx + ')">' + (isSelected ? '<div class="file-check-badge">✓</div>' : "") + '<div class="file-preview">' + previewHtml + '</div><div class="file-info"><div class="file-name"><a href="' + escapeHtml(item.url) + '" target="_blank" download onclick="event.stopPropagation()">' + escapeHtml(item.filename || "file") + '</a></div><div class="file-meta"><span class="file-sender" style="color:' + senderColor + '">' + escapeHtml(cleanAgentName(item.sender)) + "</span> &middot; " + escapeHtml(when) + '</div><div class="file-meta-small">' + meta.join(" &middot; ") + "</div></div></div>";
    }).join("");
    grid.addEventListener(
      "click",
      function handler(e) {
        grid.removeEventListener("click", handler);
      },
      { once: true }
    );
    if (typeof runFilter === "function") runFilter();
    if (window.pdfThumb) window.pdfThumb.hydrateAll(grid);
    if (inputHasFocus && document.activeElement !== msgInput2) {
      msgInput2.focus();
      try {
        msgInput2.setSelectionRange(savedStart, savedEnd);
      } catch (_) {
      }
    }
  }
  async function fetchFiles$1() {
    try {
      var res = await fetch(apiUrl("/api/media/"), {
        credentials: "same-origin"
      });
      if (!res.ok) {
        console.error("fetchFiles failed:", res.status);
        return;
      }
      filesCache = await res.json();
      renderFilesGrid();
    } catch (e) {
      console.warn("fetchFiles error:", e);
    }
  }
  document.addEventListener("DOMContentLoaded", function() {
    var buttons = document.querySelectorAll(".files-filter-btn");
    buttons.forEach(function(btn) {
      btn.addEventListener("click", function() {
        buttons.forEach(function(b) {
          b.classList.remove("active");
        });
        btn.classList.add("active");
        filesFilterMime = btn.getAttribute("data-mime");
        renderFilesGrid();
      });
    });
    var tabBtn = document.querySelector('[data-tab="files"]');
    if (tabBtn) {
      tabBtn.addEventListener("click", fetchFiles$1);
    }
    try {
      var saved = localStorage.getItem("files.viewMode");
      if (saved && ["grid", "tiles", "list", "details"].indexOf(saved) !== -1) {
        filesSetView(saved);
      }
    } catch (_) {
    }
    document.addEventListener("keydown", function(e) {
      var filesView = document.getElementById("files-view");
      if (!filesView || filesView.style.display === "none") return;
      if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) {
        var input = document.getElementById("files-search");
        if (input) {
          e.preventDefault();
          input.focus();
          input.select();
        }
      }
    });
  });
  function openPdfViewer(url, filename) {
    if (!url) return;
    closePdfViewer();
    var overlay = document.createElement("div");
    overlay.id = "pdf-modal-overlay";
    overlay.className = "pdf-modal-overlay";
    overlay.innerHTML = '<div class="pdf-modal-frame"><div class="pdf-modal-header"><span class="pdf-modal-title">' + (typeof escapeHtml === "function" ? escapeHtml(filename || "PDF") : filename || "PDF") + '</span><a class="pdf-modal-download" href="' + url + '" download target="_blank" rel="noopener" title="Open in new tab / download">↗</a><button type="button" class="pdf-modal-close" aria-label="Close PDF" onclick="closePdfViewer()">×</button></div><iframe class="pdf-modal-iframe" src="' + url + '#toolbar=1&navpanes=0" allow="fullscreen"></iframe></div>';
    overlay.addEventListener("click", function(e) {
      if (e.target === overlay) closePdfViewer();
    });
    document.body.appendChild(overlay);
    document.addEventListener("keydown", _pdfModalEscHandler);
    try {
      history.pushState({ pdfModal: true }, "", window.location.href);
    } catch (_) {
    }
    window.addEventListener("popstate", _pdfModalPopstateHandler);
  }
  function closePdfViewer() {
    var overlay = document.getElementById("pdf-modal-overlay");
    if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
    document.removeEventListener("keydown", _pdfModalEscHandler);
    window.removeEventListener("popstate", _pdfModalPopstateHandler);
  }
  function _pdfModalEscHandler(e) {
    if (e.key === "Escape") closePdfViewer();
  }
  function _pdfModalPopstateHandler(_e) {
    closePdfViewer();
  }
  window.openPdfViewer = openPdfViewer;
  window.closePdfViewer = closePdfViewer;
  function renderSubtabs() {
    var msgInput2 = document.getElementById("msg-input");
    var inputHasFocus = msgInput2 && document.activeElement === msgInput2;
    var savedStart = inputHasFocus ? msgInput2.selectionStart : 0;
    var savedEnd = inputHasFocus ? msgInput2.selectionEnd : 0;
    var bar = document.getElementById("releases-subtabs");
    if (!bar) return;
    var tabsHtml = REPOS.map(function(r) {
      var key = r.owner + "/" + r.repo;
      var cls = "settings-mode-btn releases-subtab-btn" + (key === activeRepoKey ? " active" : "");
      return '<span class="releases-subtab-wrap" draggable="true" data-repo-id="' + r.id + '" data-repo-key="' + escapeHtml(key) + '"><button type="button" class="' + cls + '" data-repo-key="' + escapeHtml(key) + '">' + escapeHtml(r.label || r.repo) + '</button><button type="button" class="releases-subtab-del" data-repo-id="' + r.id + '" data-repo-key="' + escapeHtml(key) + '" title="Remove ' + escapeHtml(key) + '" aria-label="Remove ' + escapeHtml(key) + '">×</button></span>';
    }).join("");
    tabsHtml += '<button type="button" class="releases-add-btn" id="releases-add-btn" title="Track a new GitHub repo">+ Add Repo</button>';
    bar.innerHTML = tabsHtml;
    bar.querySelectorAll(".releases-subtab-btn").forEach(function(btn) {
      btn.addEventListener("click", function() {
        var key = btn.getAttribute("data-repo-key");
        selectRepo(key);
      });
    });
    bar.querySelectorAll(".releases-subtab-del").forEach(function(btn) {
      btn.addEventListener("mousedown", function(ev) {
        ev.stopPropagation();
      });
      btn.addEventListener("click", function(ev) {
        ev.stopPropagation();
        var id = btn.getAttribute("data-repo-id");
        var key = btn.getAttribute("data-repo-key");
        deleteRepo(id, key);
      });
    });
    bar.querySelectorAll(".releases-subtab-wrap").forEach(function(wrap) {
      attachDragHandlers(wrap);
    });
    var addBtn = bar.querySelector("#releases-add-btn");
    if (addBtn) {
      addBtn.addEventListener("click", openAddRepoDialog);
    }
    if (inputHasFocus && document.activeElement !== msgInput2) {
      msgInput2.focus();
      try {
        msgInput2.setSelectionRange(savedStart, savedEnd);
      } catch (_) {
      }
    }
  }
  var _dragSrcId = null;
  function _clearDragIndicators() {
    var bar = document.getElementById("releases-subtabs");
    if (!bar) return;
    bar.querySelectorAll(".releases-subtab-wrap").forEach(function(w) {
      w.classList.remove("drag-over-before", "drag-over-after", "dragging");
    });
  }
  function attachDragHandlers(wrap) {
    wrap.addEventListener("dragstart", function(ev) {
      var id = wrap.getAttribute("data-repo-id");
      _dragSrcId = id;
      try {
        ev.dataTransfer.effectAllowed = "move";
        ev.dataTransfer.setData("text/plain", id);
      } catch (_) {
      }
      wrap.classList.add("dragging");
    });
    wrap.addEventListener("dragover", function(ev) {
      if (_dragSrcId == null) return;
      var myId = wrap.getAttribute("data-repo-id");
      if (myId === _dragSrcId) return;
      ev.preventDefault();
      try {
        ev.dataTransfer.dropEffect = "move";
      } catch (_) {
      }
      var rect = wrap.getBoundingClientRect();
      var before = ev.clientX < rect.left + rect.width / 2;
      wrap.classList.toggle("drag-over-before", before);
      wrap.classList.toggle("drag-over-after", !before);
    });
    wrap.addEventListener("dragleave", function() {
      wrap.classList.remove("drag-over-before", "drag-over-after");
    });
    wrap.addEventListener("drop", function(ev) {
      ev.preventDefault();
      var srcId = _dragSrcId;
      _clearDragIndicators();
      if (!srcId || srcId === wrap.getAttribute("data-repo-id")) return;
      var bar = document.getElementById("releases-subtabs");
      if (!bar) return;
      var srcWrap = bar.querySelector(
        '.releases-subtab-wrap[data-repo-id="' + srcId + '"]'
      );
      if (!srcWrap) return;
      var rect = wrap.getBoundingClientRect();
      var insertBefore = ev.clientX < rect.left + rect.width / 2;
      if (insertBefore) {
        wrap.parentNode.insertBefore(srcWrap, wrap);
      } else if (wrap.nextSibling) {
        wrap.parentNode.insertBefore(srcWrap, wrap.nextSibling);
      } else {
        wrap.parentNode.appendChild(srcWrap);
      }
      var ids = [];
      bar.querySelectorAll(".releases-subtab-wrap").forEach(function(w) {
        var id = parseInt(w.getAttribute("data-repo-id"), 10);
        if (!isNaN(id)) ids.push(id);
      });
      persistOrder(ids);
    });
    wrap.addEventListener("dragend", function() {
      _dragSrcId = null;
      _clearDragIndicators();
    });
  }
  function openAddRepoDialog() {
    var url = window.prompt(
      "Add a GitHub repo to the Releases tab.\n\nEnter a GitHub URL or 'owner/repo':",
      "https://github.com/"
    );
    if (!url) return;
    url = url.trim();
    if (!url || url === "https://github.com/") return;
    fetch(apiUrl("/api/tracked-repos/"), {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": _getCsrf()
      },
      body: JSON.stringify({ url })
    }).then(function(res) {
      return res.json().then(function(data) {
        return { ok: res.ok, status: res.status, data };
      });
    }).then(function(r) {
      if (!r.ok) {
        window.alert(
          "Failed to add repo: " + (r.data && r.data.error || "HTTP " + r.status)
        );
        return;
      }
      return fetchTrackedRepos().then(function() {
        if (r.data && r.data.repo) {
          activeRepoKey = r.data.repo.key;
        }
        renderSubtabs();
        if (activeRepoKey) loadChangelog(activeRepoKey);
      });
    }).catch(function(e) {
      window.alert("Network error: " + e);
    });
  }
  function deleteRepo(id, key) {
    if (!id) return;
    if (!window.confirm("Remove " + key + " from the Releases tab?")) return;
    fetch(apiUrl("/api/tracked-repos/" + id + "/"), {
      method: "DELETE",
      credentials: "same-origin",
      headers: {
        "X-CSRFToken": _getCsrf()
      }
    }).then(function(res) {
      return res.json().then(function(data) {
        return { ok: res.ok, status: res.status, data };
      });
    }).then(function(r) {
      if (!r.ok) {
        window.alert(
          "Failed to remove repo: " + (r.data && r.data.error || "HTTP " + r.status)
        );
        return;
      }
      delete changelogCache[key];
      if (activeRepoKey === key) activeRepoKey = null;
      return fetchTrackedRepos().then(function() {
        if (!activeRepoKey && REPOS.length) {
          activeRepoKey = REPOS[0].owner + "/" + REPOS[0].repo;
        }
        renderSubtabs();
        var content = document.getElementById("releases-content");
        if (activeRepoKey) {
          loadChangelog(activeRepoKey);
        } else if (content) {
          content.innerHTML = '<p class="empty-notice">No tracked repos. Click "+ Add Repo" to track a GitHub repository.</p>';
        }
      });
    }).catch(function(e) {
      window.alert("Network error: " + e);
    });
  }
  function selectRepo(key) {
    activeRepoKey = key;
    var bar = document.getElementById("releases-subtabs");
    if (bar) {
      bar.querySelectorAll(".releases-subtab-btn").forEach(function(btn) {
        btn.classList.toggle("active", btn.getAttribute("data-repo-key") === key);
      });
    }
    loadChangelog(key);
  }
  function loadChangelog(key) {
    var msgInput2 = document.getElementById("msg-input");
    var inputHasFocus = msgInput2 && document.activeElement === msgInput2;
    var savedStart = inputHasFocus ? msgInput2.selectionStart : 0;
    var savedEnd = inputHasFocus ? msgInput2.selectionEnd : 0;
    var _restoreFocus = function() {
      if (inputHasFocus && document.activeElement !== msgInput2) {
        msgInput2.focus();
        try {
          msgInput2.setSelectionRange(savedStart, savedEnd);
        } catch (_) {
        }
      }
    };
    var content = document.getElementById("releases-content");
    if (!content) return;
    if (changelogCache[key]) {
      content.innerHTML = changelogCache[key];
      _restoreFocus();
      return;
    }
    content.innerHTML = '<div class="changelog-loading">Loading CHANGELOG.md…</div>';
    _restoreFocus();
    var parts = key.split("/");
    var owner = parts[0];
    var repo = parts[1];
    fetch(apiUrl("/api/repo/" + owner + "/" + repo + "/changelog/"), {
      credentials: "same-origin"
    }).then(function(res) {
      return res.json().then(function(data) {
        return { ok: res.ok, status: res.status, data };
      });
    }).then(function(r) {
      if (key !== activeRepoKey) return;
      var _mi = document.getElementById("msg-input");
      var _ihf = _mi && document.activeElement === _mi;
      var _ss = _ihf ? _mi.selectionStart : 0;
      var _se = _ihf ? _mi.selectionEnd : 0;
      var html;
      if (r.ok && r.data && typeof r.data.content === "string") {
        var url = r.data.html_url || "";
        var header = url ? '<div class="changelog-source"><a href="' + escapeHtml(url) + '" target="_blank" rel="noopener noreferrer">View on GitHub</a></div>' : "";
        html = header + '<div class="changelog-rendered">' + renderMarkdown(r.data.content) + "</div>";
        changelogCache[key] = html;
      } else if (r.status === 404 || r.data && r.data.error && /404/.test(r.data.error)) {
        html = '<div class="empty-notice"><p>📋 No <code>CHANGELOG.md</code> in this repository yet.</p><p style="opacity:0.7;font-size:13px;">Add a <code>CHANGELOG.md</code> file to the repo root to populate this view. Format: <a href="https://keepachangelog.com/" target="_blank" rel="noopener">Keep a Changelog</a>.</p></div>';
      } else {
        var msg = r.data && r.data.error || "Failed to load CHANGELOG.md (status " + r.status + ")";
        html = '<p class="empty-notice">' + escapeHtml(msg) + "</p>";
      }
      content.innerHTML = html;
      if (_ihf && document.activeElement !== _mi) {
        _mi.focus();
        try {
          _mi.setSelectionRange(_ss, _se);
        } catch (_) {
        }
      }
    }).catch(function(e) {
      if (key !== activeRepoKey) return;
      var _mi = document.getElementById("msg-input");
      var _ihf = _mi && document.activeElement === _mi;
      var _ss = _ihf ? _mi.selectionStart : 0;
      var _se = _ihf ? _mi.selectionEnd : 0;
      content.innerHTML = '<p class="empty-notice">Network error: ' + escapeHtml(String(e)) + "</p>";
      if (_ihf && document.activeElement !== _mi) {
        _mi.focus();
        try {
          _mi.setSelectionRange(_ss, _se);
        } catch (_) {
        }
      }
    });
  }
  function initReleasesTab() {
    if (releasesInitialized) return;
    releasesInitialized = true;
    fetchTrackedRepos().then(function() {
      if (REPOS.length) {
        activeRepoKey = REPOS[0].owner + "/" + REPOS[0].repo;
      }
      renderSubtabs();
      var content = document.getElementById("releases-content");
      if (activeRepoKey) {
        loadChangelog(activeRepoKey);
      } else if (content) {
        content.innerHTML = '<p class="empty-notice">No tracked repos. Click "+ Add Repo" to track a GitHub repository.</p>';
      }
    });
  }
  document.addEventListener("DOMContentLoaded", function() {
    var tabBtn = document.querySelector('[data-tab="releases"]');
    if (tabBtn) {
      tabBtn.addEventListener("click", initReleasesTab);
    }
  });
  var threadPanelParentId = null;
  function _readThreadIdFromUrl() {
    try {
      var sp = new URLSearchParams(window.location.search);
      var v = sp.get("thread");
      if (v == null || v === "") return null;
      var n = Number(v);
      return isFinite(n) && n > 0 ? n : null;
    } catch (_) {
      return null;
    }
  }
  window.addEventListener("popstate", function() {
    var id = _readThreadIdFromUrl();
    if (id == null) ;
    else if (threadPanelParentId !== id) {
      openThreadPanel(id, { skipPushState: true });
    }
  });
  var sketchOverlay$1 = null;
  var sketchCanvas = null;
  var sketchCtx = null;
  var sketchDrawing = false;
  var sketchTool = "pen";
  var sketchColor = "#ffffff";
  var sketchLineWidth = 5;
  var SKETCH_COLORS = [
    "#ffffff",
    "#ef4444",
    "#f59e0b",
    "#22c55e",
    "#3b82f6",
    "#8b5cf6",
    "#ec4899",
    "#6b7280"
  ];
  var SKETCH_WIDTHS = [2, 5, 10];
  var SKETCH_WIDTH_LABELS = ["Thin", "Med", "Thick"];
  function openSketch() {
    if (sketchOverlay$1) return;
    sketchOverlay$1 = document.createElement("div");
    sketchOverlay$1.className = "sketch-overlay";
    var panel = document.createElement("div");
    panel.className = "sketch-panel";
    sketchOverlay$1.appendChild(panel);
    var toolbar = document.createElement("div");
    toolbar.className = "sketch-toolbar";
    panel.appendChild(toolbar);
    var penBtn = document.createElement("button");
    penBtn.className = "sketch-tool-btn active";
    penBtn.textContent = "Pen";
    penBtn.addEventListener("click", function() {
      sketchTool = "pen";
      toolbar.querySelectorAll(".sketch-tool-btn").forEach(function(b) {
        b.classList.remove("active");
      });
      penBtn.classList.add("active");
    });
    toolbar.appendChild(penBtn);
    var eraserBtn = document.createElement("button");
    eraserBtn.className = "sketch-tool-btn";
    eraserBtn.textContent = "Eraser";
    eraserBtn.addEventListener("click", function() {
      sketchTool = "eraser";
      toolbar.querySelectorAll(".sketch-tool-btn").forEach(function(b) {
        b.classList.remove("active");
      });
      eraserBtn.classList.add("active");
    });
    toolbar.appendChild(eraserBtn);
    var sep1 = document.createElement("span");
    sep1.className = "sketch-sep";
    toolbar.appendChild(sep1);
    SKETCH_COLORS.forEach(function(c) {
      var swatch = document.createElement("button");
      swatch.className = "sketch-color" + (c === sketchColor ? " active" : "");
      swatch.style.background = c;
      swatch.addEventListener("click", function() {
        toolbar.querySelectorAll(".sketch-color").forEach(function(s) {
          s.classList.remove("active");
        });
        swatch.classList.add("active");
        sketchColor = c;
        sketchTool = "pen";
        toolbar.querySelectorAll(".sketch-tool-btn").forEach(function(b) {
          b.classList.toggle("active", b.textContent === "Pen");
        });
      });
      toolbar.appendChild(swatch);
    });
    var sep2 = document.createElement("span");
    sep2.className = "sketch-sep";
    toolbar.appendChild(sep2);
    SKETCH_WIDTHS.forEach(function(w, i) {
      var btn = document.createElement("button");
      btn.className = "sketch-width-btn" + (w === sketchLineWidth ? " active" : "");
      btn.textContent = SKETCH_WIDTH_LABELS[i];
      btn.addEventListener("click", function() {
        toolbar.querySelectorAll(".sketch-width-btn").forEach(function(b) {
          b.classList.remove("active");
        });
        btn.classList.add("active");
        sketchLineWidth = w;
      });
      toolbar.appendChild(btn);
    });
    sketchCanvas = document.createElement("canvas");
    sketchCanvas.className = "sketch-canvas";
    sketchCanvas.width = 1200;
    sketchCanvas.height = 800;
    panel.appendChild(sketchCanvas);
    sketchCtx = sketchCanvas.getContext("2d");
    sketchCtx.fillStyle = "#1a1a2e";
    sketchCtx.fillRect(0, 0, 1200, 800);
    sketchCanvas.style.touchAction = "none";
    setupSketchEvents();
    var actions = document.createElement("div");
    actions.className = "sketch-actions";
    var clearBtn = document.createElement("button");
    clearBtn.className = "sketch-btn";
    clearBtn.textContent = "Clear";
    clearBtn.addEventListener("click", function() {
      sketchCtx.globalCompositeOperation = "source-over";
      sketchCtx.fillStyle = "#1a1a2e";
      sketchCtx.fillRect(0, 0, 1200, 800);
    });
    var cancelBtn = document.createElement("button");
    cancelBtn.className = "sketch-btn";
    cancelBtn.textContent = "Cancel";
    cancelBtn.addEventListener("click", closeSketch$1);
    var sendBtn = document.createElement("button");
    sendBtn.className = "sketch-btn sketch-btn-primary";
    sendBtn.textContent = "Send";
    sendBtn.addEventListener("click", sendSketch);
    actions.append(clearBtn, cancelBtn, sendBtn);
    panel.appendChild(actions);
    sketchOverlay$1.addEventListener("click", function(e) {
      if (e.target === sketchOverlay$1) closeSketch$1();
    });
    var onKey = function(e) {
      if (e.key === "Escape") {
        closeSketch$1();
        document.removeEventListener("keydown", onKey);
      }
    };
    document.addEventListener("keydown", onKey);
    document.body.appendChild(sketchOverlay$1);
  }
  function setupSketchEvents() {
    sketchCanvas.addEventListener("pointerdown", function(e) {
      sketchDrawing = true;
      sketchCtx.beginPath();
      var r = sketchCanvas.getBoundingClientRect();
      sketchCtx.moveTo(
        (e.clientX - r.left) / r.width * 1200,
        (e.clientY - r.top) / r.height * 800
      );
    });
    sketchCanvas.addEventListener("pointermove", function(e) {
      if (!sketchDrawing) return;
      var r = sketchCanvas.getBoundingClientRect();
      var x = (e.clientX - r.left) / r.width * 1200;
      var y = (e.clientY - r.top) / r.height * 800;
      sketchCtx.lineWidth = sketchLineWidth;
      sketchCtx.lineCap = "round";
      sketchCtx.lineJoin = "round";
      if (sketchTool === "eraser") {
        sketchCtx.globalCompositeOperation = "destination-out";
        sketchCtx.strokeStyle = "rgba(0,0,0,1)";
      } else {
        sketchCtx.globalCompositeOperation = "source-over";
        sketchCtx.strokeStyle = sketchColor;
      }
      sketchCtx.lineTo(x, y);
      sketchCtx.stroke();
      sketchCtx.beginPath();
      sketchCtx.moveTo(x, y);
    });
    sketchCanvas.addEventListener("pointerup", function() {
      sketchDrawing = false;
    });
    sketchCanvas.addEventListener("pointerleave", function() {
      sketchDrawing = false;
    });
  }
  function closeSketch$1() {
    if (sketchOverlay$1) {
      sketchOverlay$1.remove();
      sketchOverlay$1 = null;
      sketchCanvas = null;
      sketchCtx = null;
    }
  }
  async function sendSketch() {
    if (!sketchCanvas) return;
    var dataUrl = sketchCanvas.toDataURL("image/png");
    var b64 = dataUrl.split(",")[1];
    closeSketch$1();
    try {
      var res = await fetch(apiUrl("/api/upload-base64"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          data: b64,
          filename: "sketch.png",
          mime_type: "image/png"
        })
      });
      if (!res.ok) {
        console.error("Sketch upload failed:", res.status);
        return;
      }
      var result = await res.json();
      var channel = currentChannel || "#general";
      sendOrochiMessage({
        type: "message",
        sender: userName,
        payload: {
          channel,
          content: "sketch",
          attachments: [result]
        }
      });
    } catch (e) {
      console.error("Sketch upload error:", e);
    }
  }
  document.getElementById("msg-sketch").addEventListener("click", openSketch);
  var webcamOverlay = null;
  var webcamVideo = null;
  var webcamStream = null;
  var webcamFacing = "environment";
  var webcamCaptureInput = null;
  var webcamOnKey = null;
  function _webcamEnsureFallbackInput() {
    if (webcamCaptureInput) return webcamCaptureInput;
    webcamCaptureInput = document.getElementById("webcam-capture-input");
    if (webcamCaptureInput) return webcamCaptureInput;
    webcamCaptureInput = document.createElement("input");
    webcamCaptureInput.type = "file";
    webcamCaptureInput.accept = "image/*";
    webcamCaptureInput.setAttribute("capture", "environment");
    webcamCaptureInput.id = "webcam-capture-input";
    webcamCaptureInput.style.display = "none";
    document.body.appendChild(webcamCaptureInput);
    return webcamCaptureInput;
  }
  function _webcamWireFallbackInput() {
    var input = _webcamEnsureFallbackInput();
    if (input._webcamWired) return;
    input._webcamWired = true;
    input.addEventListener("change", function() {
      if (!this.files || this.files.length === 0) return;
      var arr = Array.prototype.slice.call(this.files);
      if (typeof stageFiles === "function") {
        stageFiles(arr);
      } else {
        console.error("[orochi-webcam] stageFiles unavailable");
      }
      this.value = "";
    });
  }
  function _webcamOpenFallback() {
    var input = _webcamEnsureFallbackInput();
    _webcamWireFallbackInput();
    input.click();
  }
  async function _webcamRequestStream(facing) {
    return navigator.mediaDevices.getUserMedia({
      video: { facingMode: facing, width: { ideal: 1280 } },
      audio: false
    });
  }
  async function openWebcam() {
    if (webcamOverlay) return;
    _webcamWireFallbackInput();
    if (!navigator.mediaDevices || typeof navigator.mediaDevices.getUserMedia !== "function") {
      _webcamOpenFallback();
      return;
    }
    try {
      webcamStream = await _webcamRequestStream(webcamFacing);
    } catch (e) {
      console.warn("[orochi-webcam] getUserMedia failed, falling back:", e);
      _webcamOpenFallback();
      return;
    }
    webcamOverlay = _buildWebcamUI();
    document.body.appendChild(webcamOverlay);
    if (webcamVideo) {
      webcamVideo.srcObject = webcamStream;
    }
  }
  function _buildWebcamUI() {
    var overlay = document.createElement("div");
    overlay.className = "webcam-overlay";
    var panel = document.createElement("div");
    panel.className = "webcam-panel";
    overlay.appendChild(panel);
    webcamVideo = document.createElement("video");
    webcamVideo.className = "webcam-video";
    webcamVideo.autoplay = true;
    webcamVideo.playsInline = true;
    webcamVideo.muted = true;
    panel.appendChild(webcamVideo);
    var hint = document.createElement("div");
    hint.className = "webcam-hint";
    hint.textContent = "Capture adds photo to attachment tray. Done closes the camera.";
    panel.appendChild(hint);
    var actions = document.createElement("div");
    actions.className = "webcam-actions";
    var cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "webcam-btn";
    cancelBtn.textContent = "Cancel";
    cancelBtn.addEventListener("click", closeWebcam);
    var flipBtn = document.createElement("button");
    flipBtn.type = "button";
    flipBtn.className = "webcam-btn";
    flipBtn.textContent = "Flip";
    flipBtn.title = "Switch camera";
    flipBtn.addEventListener("click", flipWebcam);
    var captureBtn = document.createElement("button");
    captureBtn.type = "button";
    captureBtn.className = "webcam-btn webcam-btn-capture";
    captureBtn.textContent = "Capture";
    captureBtn.title = "Take photo";
    captureBtn.addEventListener("click", captureWebcamFrame);
    var doneBtn = document.createElement("button");
    doneBtn.type = "button";
    doneBtn.className = "webcam-btn webcam-btn-primary";
    doneBtn.textContent = "Done";
    doneBtn.title = "Close camera (photos stay in attachment tray)";
    doneBtn.addEventListener("click", closeWebcam);
    actions.append(cancelBtn, flipBtn, captureBtn, doneBtn);
    panel.appendChild(actions);
    overlay.addEventListener("click", function(e) {
      if (e.target === overlay) closeWebcam();
    });
    webcamOnKey = function(e) {
      if (e.key === "Escape") closeWebcam();
    };
    document.addEventListener("keydown", webcamOnKey);
    return overlay;
  }
  function captureWebcamFrame() {
    if (!webcamVideo || !webcamVideo.videoWidth) return;
    var canvas = document.createElement("canvas");
    canvas.width = webcamVideo.videoWidth;
    canvas.height = webcamVideo.videoHeight;
    var ctx = canvas.getContext("2d");
    ctx.drawImage(webcamVideo, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(
      function(blob) {
        if (!blob) return;
        var ts = (/* @__PURE__ */ new Date()).toISOString().replace(/[-:]/g, "").replace(/\..+/, "");
        var filename = "webcam-" + ts + ".jpg";
        var file;
        try {
          file = new File([blob], filename, { type: "image/jpeg" });
        } catch (_) {
          blob.name = filename;
          file = blob;
        }
        if (typeof stageFiles === "function") {
          stageFiles([file]);
        } else {
          console.error("[orochi-webcam] stageFiles unavailable");
        }
      },
      "image/jpeg",
      0.9
    );
  }
  async function flipWebcam() {
    if (!webcamStream || !webcamVideo) return;
    webcamFacing = webcamFacing === "environment" ? "user" : "environment";
    _webcamStopStream();
    try {
      webcamStream = await _webcamRequestStream(webcamFacing);
      webcamVideo.srcObject = webcamStream;
    } catch (e) {
      console.warn("[orochi-webcam] flip failed, reacquiring:", e);
      webcamFacing = webcamFacing === "environment" ? "user" : "environment";
      try {
        webcamStream = await _webcamRequestStream(webcamFacing);
        webcamVideo.srcObject = webcamStream;
      } catch (e2) {
        console.error("[orochi-webcam] could not reacquire stream:", e2);
        closeWebcam();
      }
    }
  }
  function _webcamStopStream() {
    if (webcamStream) {
      var tracks = webcamStream.getTracks();
      for (var i = 0; i < tracks.length; i++) {
        try {
          tracks[i].stop();
        } catch (_) {
        }
      }
      webcamStream = null;
    }
  }
  function closeWebcam() {
    _webcamStopStream();
    if (webcamOverlay) {
      webcamOverlay.remove();
      webcamOverlay = null;
    }
    webcamVideo = null;
    if (webcamOnKey) {
      document.removeEventListener("keydown", webcamOnKey);
      webcamOnKey = null;
    }
  }
  var _webcamBtn = document.getElementById("msg-webcam");
  if (_webcamBtn) {
    _webcamBtn.addEventListener("click", openWebcam);
  }
  _webcamWireFallbackInput();
  (function() {
    var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition)
      return;
    var isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1;
    if (isIOS) return;
    var btn = document.getElementById("msg-voice");
    if (!btn) return;
    btn.classList.remove("voice-btn-hidden");
    var VOICE_LANGS = [
      { code: "en-US", label: "EN" },
      { code: "ja-JP", label: "JA" }
    ];
    var LANG_KEY = "orochi-voice-lang";
    function _resolveInitialLangIdx() {
      try {
        var saved = localStorage.getItem(LANG_KEY);
        for (var i = 0; i < VOICE_LANGS.length; i++) {
          if (VOICE_LANGS[i].code === saved) return i;
        }
      } catch (_) {
      }
      return (navigator.language || "").startsWith("ja") ? 1 : 0;
    }
    var langIdx = _resolveInitialLangIdx();
    var langBtn = document.getElementById("msg-voice-lang");
    if (langBtn) {
      langBtn.classList.remove("voice-btn-hidden");
      langBtn.textContent = VOICE_LANGS[langIdx].label;
      langBtn.addEventListener("click", function() {
        _cycleLang();
        try {
          document.getElementById("msg-input").focus();
        } catch (_) {
        }
      });
    }
    var recognition = null;
    var isListening = false;
    var _userStopped = false;
    var baseText = "";
    var _restartAfterStop = false;
    var _suppressResults = false;
    var _voiceTarget = null;
    var _generation = 0;
    window.isVoiceRecording = false;
    function _setStoppedUI() {
      isListening = false;
      window.isVoiceRecording = false;
      if (typeof window._flushVoiceQueue === "function") {
        try {
          window._flushVoiceQueue();
        } catch (_) {
        }
      }
      btn.classList.remove("voice-active");
      var threadBtn = document.getElementById("thread-voice-btn");
      if (threadBtn) threadBtn.classList.remove("voice-active");
      btn.title = "Voice input · " + VOICE_LANGS[langIdx].label + " · right-click to change language · Alt+Enter / Ctrl+Enter / Ctrl+M to toggle";
      var input = document.getElementById("msg-input");
      if (input) input.classList.remove("voice-recording");
      if (_voiceTarget && _voiceTarget !== input)
        _voiceTarget.classList.remove("voice-recording");
    }
    function _createRecognition() {
      var myGen = ++_generation;
      var r = new SpeechRecognition();
      r.continuous = true;
      r.interimResults = true;
      r.lang = VOICE_LANGS[langIdx].code;
      r.addEventListener("start", function() {
        if (myGen !== _generation) return;
        isListening = true;
        window.isVoiceRecording = true;
        _userStopped = false;
        var inThread = _voiceTarget && _voiceTarget.id === "thread-input";
        var threadBtn = document.getElementById("thread-voice-btn");
        if (inThread && threadBtn) {
          threadBtn.classList.add("voice-active");
          btn.classList.remove("voice-active");
        } else {
          btn.classList.add("voice-active");
          if (threadBtn) threadBtn.classList.remove("voice-active");
        }
        btn.title = "Stop voice input";
        var target = _voiceTarget || document.getElementById("msg-input");
        if (target) target.classList.add("voice-recording");
      });
      r.addEventListener("end", function() {
        if (myGen !== _generation) return;
        if (_restartAfterStop) {
          _restartAfterStop = false;
          _suppressResults = false;
          recognition = _createRecognition();
          try {
            recognition.start();
          } catch (_) {
          }
          return;
        }
        if (isListening && !_userStopped) {
          setTimeout(function() {
            if (myGen !== _generation) return;
            if (!_userStopped) {
              recognition = _createRecognition();
              try {
                recognition.start();
              } catch (_) {
                _setStoppedUI();
              }
            }
          }, 150);
          return;
        }
        _setStoppedUI();
      });
      r.addEventListener("result", function(e) {
        if (myGen !== _generation) return;
        if (_suppressResults) return;
        var input = _voiceTarget || document.getElementById("msg-input");
        var transcript = "";
        for (var i = 0; i < e.results.length; i++) {
          transcript += e.results[i][0].transcript;
        }
        var sep = baseText && !baseText.endsWith(" ") && transcript ? " " : "";
        if (input) {
          input.value = baseText + sep + transcript;
          input.dispatchEvent(new Event("input", { bubbles: true }));
        }
      });
      r.addEventListener("error", function(e) {
        if (myGen !== _generation) return;
        if (e.error !== "no-speech" && e.error !== "aborted") {
          console.warn("Voice input error:", e.error);
        }
        _setStoppedUI();
      });
      return r;
    }
    function _toggleVoice() {
      var focused = document.activeElement;
      var input = null;
      if (focused && focused.tagName === "TEXTAREA") {
        if (focused.hasAttribute("data-voice-input") || focused.closest && (focused.closest(".thread-panel") || focused.closest("#topo-channel-compose") || focused.closest(".topo-compose-modal"))) {
          input = focused;
        }
      }
      if (!input) {
        var canvasCompose = document.getElementById("topo-channel-compose");
        if (canvasCompose) {
          var composeTa = canvasCompose.querySelector(
            "textarea.tcc-input, textarea[data-voice-input]"
          );
          if (composeTa) {
            input = composeTa;
            try {
              composeTa.focus();
            } catch (_ignored) {
            }
          }
        }
      }
      if (!input) {
        var chatActive = true;
        try {
          if (typeof window.activeTab === "string") {
            chatActive = window.activeTab === "chat";
          }
        } catch (_) {
          chatActive = true;
        }
        if (chatActive) {
          input = document.getElementById("msg-input");
        }
      }
      if (!input) {
        return;
      }
      if (isListening) {
        _userStopped = true;
        _generation++;
        _setStoppedUI();
        if (recognition) {
          try {
            recognition.abort();
          } catch (_) {
          }
        }
        recognition = null;
        _voiceTarget = null;
      } else {
        if (recognition) {
          try {
            recognition.abort();
          } catch (_) {
          }
          recognition = null;
        }
        _voiceTarget = input;
        recognition = _createRecognition();
        _userStopped = false;
        baseText = input ? input.value : "";
        try {
          recognition.start();
        } catch (_) {
          _generation++;
          _setStoppedUI();
        }
      }
      if (input) {
        try {
          input.focus();
        } catch (_) {
        }
      }
    }
    function _cycleLang() {
      langIdx = (langIdx + 1) % VOICE_LANGS.length;
      if (recognition) recognition.lang = VOICE_LANGS[langIdx].code;
      if (langBtn) langBtn.textContent = VOICE_LANGS[langIdx].label;
      btn.title = (isListening ? "Stop voice input" : "Voice input") + " · " + VOICE_LANGS[langIdx].label + " · right-click to change language · Ctrl+M to toggle";
      try {
        localStorage.setItem(LANG_KEY, VOICE_LANGS[langIdx].code);
      } catch (_) {
      }
    }
    window.toggleVoiceInput = _toggleVoice;
    window.cycleVoiceLang = _cycleLang;
    btn.addEventListener("click", _toggleVoice);
    btn.addEventListener("contextmenu", function(e) {
      e.preventDefault();
      _cycleLang();
    });
    document.addEventListener(
      "keydown",
      function(e) {
        if (e.key === "Escape" && isListening) {
          _toggleVoice();
          return;
        }
        if (e.ctrlKey && (e.key === "m" || e.key === "M") || e.altKey && (e.key === "v" || e.key === "V")) {
          e.preventDefault();
          _toggleVoice();
          return;
        }
        if (e.key === "Enter" && (e.ctrlKey || e.altKey)) {
          var focused = document.activeElement;
          var inThread = focused && focused.closest && focused.closest(".thread-panel");
          if (inThread) return;
          var inCanvasCompose = focused && focused.closest && focused.closest("#topo-channel-compose");
          if (inCanvasCompose) return;
          var inTopoGroupCompose = focused && focused.closest && focused.closest(".topo-compose-modal");
          if (inTopoGroupCompose) return;
          if (typeof activeTab !== "undefined" && activeTab === "chat") {
            e.preventDefault();
            _toggleVoice();
          }
        }
      },
      true
    );
    btn.title = "Voice input · " + VOICE_LANGS[langIdx].label + " · right-click to change language · Alt+Enter / Ctrl+Enter / Ctrl+M to toggle";
    window.voiceInputResetAfterSend = function() {
      baseText = "";
      _suppressResults = true;
      if (isListening) {
        _restartAfterStop = true;
        if (recognition) {
          try {
            recognition.stop();
          } catch (_) {
          }
        }
      }
    };
  })();
  var _termState = {
    loaded: false,
    loadingPromise: null
  };
  function _termLoadAssets() {
    if (_termState.loaded) return Promise.resolve();
    if (_termState.loadingPromise) return _termState.loadingPromise;
    _termState.loadingPromise = new Promise(function(resolve, reject) {
      var css = document.createElement("link");
      css.rel = "stylesheet";
      css.href = "https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.min.css";
      document.head.appendChild(css);
      var script = document.createElement("script");
      script.src = "https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.min.js";
      script.onload = function() {
        var fit = document.createElement("script");
        fit.src = "https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.min.js";
        fit.onload = function() {
          _termState.loaded = true;
          resolve();
        };
        fit.onerror = function() {
          reject(new Error("failed to load xterm-addon-fit"));
        };
        document.head.appendChild(fit);
      };
      script.onerror = function() {
        reject(new Error("failed to load xterm.js"));
      };
      document.head.appendChild(script);
    });
    return _termState.loadingPromise;
  }
  function _termStatus(msg, cls) {
    var el = document.getElementById("terminal-status");
    if (!el) return;
    el.textContent = msg;
    el.className = "terminal-status" + (" " + cls);
  }
  function _termCloseExisting() {
    var container = document.getElementById("terminal-xterm-container");
    if (container) container.innerHTML = "";
  }
  document.addEventListener("DOMContentLoaded", function() {
    var closeBtn = document.getElementById("terminal-close-btn");
    if (closeBtn) {
      closeBtn.addEventListener("click", function() {
        _termCloseExisting();
        _termStatus("closed", "closed");
      });
    }
  });
  window._termLoadAssets = _termLoadAssets;
  var activeTab$1 = "chat";
  function _activateTab$1(tab) {
    activeTab$1 = tab;
    document.querySelectorAll(".tab-btn").forEach(function(b) {
      b.classList.toggle("active", b.getAttribute("data-tab") === tab);
    });
    var messagesEl = document.getElementById("messages");
    var chatFilterEl = document.getElementById("chat-filter-input");
    var inputBar = document.querySelector(".input-bar");
    var todoView = document.getElementById("todo-view");
    var resourcesView = document.getElementById("resources-view");
    var agentsTabView = document.getElementById("agents-tab-view");
    var workspacesView = document.getElementById("workspaces-view");
    var activityView = document.getElementById("activity-view");
    var filesView = document.getElementById("files-view");
    var releasesView = document.getElementById("releases-view");
    var terminalView = document.getElementById("terminal-view");
    var settingsView = document.getElementById("settings-view");
    messagesEl.style.display = "none";
    if (chatFilterEl) chatFilterEl.style.display = "none";
    inputBar.style.display = "none";
    var topicBanner = document.getElementById("channel-topic-banner");
    if (topicBanner) topicBanner.style.display = "none";
    var membersPanel = document.getElementById("channel-members-panel");
    if (membersPanel) membersPanel.style.display = "none";
    todoView.style.display = "none";
    resourcesView.style.display = "none";
    agentsTabView.style.display = "none";
    workspacesView.style.display = "none";
    if (activityView) activityView.style.display = "none";
    if (filesView) filesView.style.display = "none";
    if (releasesView) releasesView.style.display = "none";
    if (terminalView) terminalView.style.display = "none";
    if (settingsView) settingsView.style.display = "none";
    if (tab !== "todo" && typeof stopVizTab === "function") stopVizTab();
    if (tab === "chat") {
      messagesEl.style.display = "";
      if (chatFilterEl) chatFilterEl.style.display = "";
      inputBar.style.display = "";
      if (topicBanner) topicBanner.style.display = "";
      requestAnimationFrame(function() {
        messagesEl.scrollTop = messagesEl.scrollHeight;
        var input = document.getElementById("msg-input");
        if (input) {
          input.focus();
          if (typeof restoreDraftForCurrentChannel === "function") {
            restoreDraftForCurrentChannel();
          }
        }
      });
    } else if (tab === "todo") {
      todoView.style.display = "block";
      todoView.style.flex = "1";
      fetchTodoList();
      if (typeof renderVizTab === "function") renderVizTab();
    } else if (tab === "agents-tab") {
      agentsTabView.style.display = "block";
      agentsTabView.style.flex = "1";
      renderAgentsTab();
    } else if (tab === "resources") {
      resourcesView.style.display = "block";
      resourcesView.style.flex = "1";
      renderResourcesTab();
    } else if (tab === "workspaces") {
      workspacesView.style.display = "block";
      workspacesView.style.flex = "1";
      fetchWorkspaces();
    } else if (tab === "activity") {
      if (activityView) {
        activityView.style.display = "";
        activityView.style.flex = "1";
      }
      if (typeof refreshActivityFromApi === "function") refreshActivityFromApi();
      if (typeof startActivityAutoRefresh === "function")
        startActivityAutoRefresh();
    } else if (tab === "files") {
      if (filesView) {
        filesView.style.display = "block";
        filesView.style.flex = "1";
      }
      if (typeof fetchFiles === "function") fetchFiles();
    } else if (tab === "releases") {
      if (releasesView) {
        releasesView.style.display = "block";
        releasesView.style.flex = "1";
      }
      if (typeof fetchReleases === "function") fetchReleases();
    } else if (tab === "terminal") {
      if (terminalView) {
        terminalView.style.display = "flex";
        terminalView.style.flex = "1";
      }
      if (typeof renderTerminalTab === "function") renderTerminalTab();
    } else if (tab === "settings" && settingsView) {
      settingsView.style.display = "block";
      settingsView.style.flex = "1";
      fetchSettings();
    }
    try {
      localStorage.setItem("orochi_active_tab", tab);
    } catch (_) {
    }
  }
  document.querySelectorAll(".tab-btn").forEach(function(btn) {
    btn.addEventListener("click", function() {
      var tab = btn.getAttribute("data-tab");
      if (tab === activeTab$1) return;
      _activateTab$1(tab);
    });
  });
  (function() {
    try {
      var last = localStorage.getItem("orochi_active_tab");
      if (last && last !== "chat") {
        var btn = document.querySelector('.tab-btn[data-tab="' + last + '"]');
        if (btn) _activateTab$1(last);
      }
    } catch (_) {
    }
  })();
  (function() {
    function sectionKey(h2) {
      return h2.getAttribute("data-section") || h2.textContent.trim();
    }
    function applySavedState() {
      var saved = {};
      try {
        saved = JSON.parse(localStorage.getItem("orochi_collapsed") || "{}");
      } catch (e) {
      }
      document.querySelectorAll(".collapsible-heading").forEach(function(h2) {
        var key = sectionKey(h2);
        var section = h2.nextElementSibling;
        if (saved[key]) {
          h2.classList.add("collapsed");
          if (section) section.classList.add("collapsed");
        }
      });
    }
    applySavedState();
    document.addEventListener("click", function(e) {
      var h2 = e.target.closest(".collapsible-heading");
      if (!h2) return;
      if (e.target.closest("button")) return;
      var key = sectionKey(h2);
      var section = h2.nextElementSibling;
      var isCollapsed = h2.classList.toggle("collapsed");
      if (section) section.classList.toggle("collapsed", isCollapsed);
      try {
        var state = JSON.parse(localStorage.getItem("orochi_collapsed") || "{}");
        if (isCollapsed) {
          state[key] = true;
        } else {
          delete state[key];
        }
        localStorage.setItem("orochi_collapsed", JSON.stringify(state));
      } catch (err) {
      }
    });
  })();
  (function() {
    var toggle = document.getElementById("sidebar-toggle");
    var sidebar = document.getElementById("sidebar");
    if (!toggle || !sidebar) return;
    var backdrop = document.createElement("div");
    backdrop.className = "sidebar-backdrop";
    document.body.appendChild(backdrop);
    function openSidebar() {
      sidebar.classList.add("open");
      toggle.classList.add("open");
      toggle.innerHTML = "&#10005;";
      backdrop.classList.add("visible");
    }
    function closeSidebar() {
      sidebar.classList.remove("open");
      toggle.classList.remove("open");
      toggle.innerHTML = "&#9776;";
      backdrop.classList.remove("visible");
    }
    toggle.addEventListener("click", function() {
      if (sidebar.classList.contains("open")) {
        closeSidebar();
      } else {
        openSidebar();
      }
    });
    backdrop.addEventListener("click", closeSidebar);
    var chEl = document.getElementById("channels");
    if (chEl) {
      chEl.addEventListener("click", function(e) {
        if (e.target.closest(".channel-item") && window.innerWidth <= 600) {
          closeSidebar();
        }
      });
    }
    var _swipeStartX = null;
    var _swipeStartY = null;
    document.addEventListener(
      "touchstart",
      function(e) {
        _swipeStartX = e.touches[0].clientX;
        _swipeStartY = e.touches[0].clientY;
      },
      { passive: true }
    );
    document.addEventListener(
      "touchend",
      function(e) {
        if (_swipeStartX === null) return;
        var dx = e.changedTouches[0].clientX - _swipeStartX;
        var dy = e.changedTouches[0].clientY - _swipeStartY;
        var absDx = Math.abs(dx);
        var absDy = Math.abs(dy);
        if (absDx < 40 || absDy > absDx) {
          _swipeStartX = null;
          return;
        }
        if (dx > 0 && _swipeStartX < 40) {
          openSidebar();
        } else if (dx < 0 && sidebar.classList.contains("open")) {
          closeSidebar();
        }
        _swipeStartX = null;
      },
      { passive: true }
    );
  })();
  (function() {
    var brandLogo = document.getElementById("brand-logo");
    if (brandLogo) {
      brandLogo.innerHTML = '<img class="header-icon" src="/static/hub/orochi-icon.png" alt="Orochi">';
    }
  })();
  (function() {
    var wsIconSlot = document.getElementById("ws-icon-slot");
    var wsName = window.__orochiWorkspaceName || "workspace";
    var wsIconImage = window.__orochiWorkspaceIconImage || "";
    var wsIcon = window.__orochiWorkspaceIcon || "";
    if (wsIconSlot) {
      if (wsIconImage) {
        wsIconSlot.innerHTML = getWorkspaceIcon(wsName, 16);
      } else if (wsIcon) {
        wsIconSlot.innerHTML = '<span class="ws-emoji-icon">' + wsIcon + "</span>";
      } else {
        wsIconSlot.innerHTML = getWorkspaceIcon(wsName, 16);
      }
    }
  })();
  (function() {
    var el = document.getElementById("wall-clock");
    if (!el) return;
    function tick() {
      el.textContent = (/* @__PURE__ */ new Date()).toLocaleString(void 0, {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false
      });
    }
    tick();
    setInterval(tick, 1e3);
  })();
  refreshAgentNames().then(function() {
    loadHistory();
  });
  fetchAgents();
  if (typeof fetchHumanProfiles === "function") {
    fetchHumanProfiles();
    setInterval(fetchHumanProfiles, 6e4);
  }
  fetchStats();
  connect();
  setInterval(fetchStats, 1e4);
  setInterval(fetchAgents, 1e4);
  fetchTodoList();
  setInterval(fetchTodoList, 6e4);
  fetchResources();
  setInterval(fetchResources, 3e4);
  fetchWorkspaces();
  setInterval(fetchWorkspaces, 3e4);
  setTimeout(function() {
    if (!wsConnected) {
      console.warn("WebSocket not connected after 3s, starting REST poll");
      startRestPolling();
    }
  }, 3e3);
  document.addEventListener("keydown", function(e) {
    if (e.key !== "Escape") return;
    var editInput = document.querySelector(".msg-edit-input");
    if (editInput && document.activeElement === editInput) return;
    if (window.elementInspector && window.elementInspector._isActive) return;
    var emojiOverlay = document.querySelector(".emoji-picker-overlay.visible");
    if (emojiOverlay) {
      if (typeof window.closeEmojiPicker === "function")
        window.closeEmojiPicker();
      e.preventDefault();
      return;
    }
    if (typeof reactionPicker !== "undefined" && reactionPicker) {
      closeReactionPicker();
      e.preventDefault();
      return;
    }
    if (typeof sketchOverlay !== "undefined" && sketchOverlay) {
      closeSketch();
      e.preventDefault();
      return;
    }
    if (typeof threadPanel !== "undefined" && threadPanel) {
      closeThreadPanel();
      e.preventDefault();
      return;
    }
    var mentionDD = document.getElementById("mention-dropdown");
    if (mentionDD && mentionDD.classList.contains("visible")) {
      if (typeof hideMentionDropdown === "function") hideMentionDropdown();
      e.preventDefault();
      return;
    }
    var filterDD = document.getElementById("filter-suggest");
    if (filterDD && filterDD.classList.contains("visible")) {
      filterDD.classList.remove("visible");
      filterDD.innerHTML = "";
      e.preventDefault();
      return;
    }
    var openDetail = document.querySelector(".agent-detail-popup.open");
    if (openDetail) {
      openDetail.classList.remove("open");
      e.preventDefault();
      return;
    }
    var wsDropdown = document.querySelector(".ws-dropdown");
    if (wsDropdown) {
      return;
    }
    var sidebar = document.getElementById("sidebar");
    if (sidebar && sidebar.classList.contains("open")) {
      sidebar.classList.remove("open");
      var toggle = document.getElementById("sidebar-toggle");
      if (toggle) {
        toggle.classList.remove("open");
        toggle.innerHTML = "&#9776;";
      }
      var backdrop = document.querySelector(".sidebar-backdrop");
      if (backdrop) backdrop.classList.remove("visible");
      e.preventDefault();
      return;
    }
  });
  (function() {
    var LS_KEY = "orochi.sidebarFolded";
    var container = document.querySelector(".container");
    var btn = document.getElementById("sidebar-fold");
    if (!container || !btn) return;
    function applyState(folded) {
      container.classList.toggle("sidebar-folded", !!folded);
      btn.innerHTML = folded ? "›" : "‹";
      btn.title = folded ? "Expand sidebar (Ctrl+B)" : "Collapse sidebar (Ctrl+B)";
      btn.setAttribute(
        "aria-label",
        folded ? "Expand sidebar" : "Collapse sidebar"
      );
    }
    var initial = false;
    try {
      initial = localStorage.getItem(LS_KEY) === "1";
    } catch (_e) {
    }
    applyState(initial);
    btn.addEventListener("click", function() {
      var folded = !container.classList.contains("sidebar-folded");
      applyState(folded);
      try {
        localStorage.setItem(LS_KEY, folded ? "1" : "0");
      } catch (_e) {
      }
    });
    document.addEventListener("keydown", function(ev) {
      if (!(ev.ctrlKey || ev.metaKey)) return;
      if (ev.key !== "b" && ev.key !== "B") return;
      var t = ev.target;
      var isInput = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable);
      if (isInput) return;
      ev.preventDefault();
      btn.click();
    });
  })();
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(function(err) {
      console.error("SW registration failed:", err);
    });
  }
  localStorage.getItem("orochi_push_enabled") === "true";
  (function() {
    var EI = window.__EI = window.__EI || {};
    var DEPTH_COLORS = [
      "#3B82F6",
      // Blue (depth 0-2)
      "#10B981",
      // Green (depth 3-5)
      "#F59E0B",
      // Yellow (depth 6-8)
      "#EF4444",
      // Red (depth 9-11)
      "#EC4899"
      // Pink (depth 12+)
    ];
    function getDepth(element) {
      var depth = 0;
      var current = element;
      while (current && current !== document.body) {
        depth++;
        current = current.parentElement;
      }
      return depth;
    }
    function getColorForDepth(depth) {
      var index = Math.min(Math.floor(depth / 3), DEPTH_COLORS.length - 1);
      return DEPTH_COLORS[index];
    }
    function hexToRgba(hex, alpha) {
      var result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
      if (!result) return "rgba(59, 130, 246, " + alpha + ")";
      var r = parseInt(result[1], 16);
      var g = parseInt(result[2], 16);
      var b = parseInt(result[3], 16);
      return "rgba(" + r + ", " + g + ", " + b + ", " + alpha + ")";
    }
    EI.getDepth = getDepth;
    EI.getColorForDepth = getColorForDepth;
    EI.hexToRgba = hexToRgba;
    function NotificationManager() {
      this._onCopyCallback = null;
    }
    NotificationManager.prototype.setOnCopyCallback = function(cb) {
      this._onCopyCallback = cb;
    };
    NotificationManager.prototype.triggerCopyCallback = function() {
      var self = this;
      if (self._onCopyCallback) {
        setTimeout(function() {
          if (self._onCopyCallback) self._onCopyCallback();
        }, 400);
      }
    };
    NotificationManager.prototype.showNotification = function(message, type, duration) {
      duration = duration || 1e3;
      var el = document.createElement("div");
      el.textContent = message;
      el.style.cssText = "position:fixed;top:16px;right:16px;padding:10px 20px;background:" + (type === "success" ? "rgba(16,185,129,0.95)" : "rgba(239,68,68,0.95)") + ";color:#fff;border-radius:6px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:13px;font-weight:600;z-index:10000000;box-shadow:0 4px 12px rgba(0,0,0,0.25);opacity:0;transform:translateY(-10px) scale(0.95);transition:opacity 0.2s ease,transform 0.2s ease;";
      document.body.appendChild(el);
      requestAnimationFrame(function() {
        el.style.opacity = "1";
        el.style.transform = "translateY(0) scale(1)";
      });
      setTimeout(function() {
        el.style.opacity = "0";
        el.style.transform = "translateY(-10px) scale(0.95)";
        setTimeout(function() {
          el.remove();
        }, 200);
      }, duration);
    };
    NotificationManager.prototype.showCameraFlash = function() {
      var flash = document.createElement("div");
      flash.style.cssText = "position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(255,255,255,0.4);z-index:9999999;pointer-events:none;opacity:1;transition:opacity 0.1s ease;";
      document.body.appendChild(flash);
      setTimeout(function() {
        flash.style.opacity = "0";
      }, 30);
      setTimeout(function() {
        flash.remove();
      }, 130);
    };
    EI.NotificationManager = NotificationManager;
    function DebugInfoCollector() {
    }
    DebugInfoCollector.prototype.buildCSSSelector = function(element) {
      var tag = element.tagName.toLowerCase();
      var id = element.id;
      var classes = element.className;
      var selector = tag;
      if (id) selector += "#" + id;
      if (classes && typeof classes === "string") {
        var classList = classes.split(/\s+/).filter(function(c) {
          return c;
        });
        if (classList.length > 0) selector += "." + classList.join(".");
      }
      return selector;
    };
    DebugInfoCollector.prototype.getXPath = function(element) {
      if (element.id) return '//*[@id="' + element.id + '"]';
      var parts = [];
      var current = element;
      while (current && current.nodeType === Node.ELEMENT_NODE) {
        var index = 0;
        var sibling = current.previousSibling;
        while (sibling) {
          if (sibling.nodeType === Node.ELEMENT_NODE && sibling.nodeName === current.nodeName)
            index++;
          sibling = sibling.previousSibling;
        }
        var tagName = current.nodeName.toLowerCase();
        var pathIndex = index > 0 ? "[" + (index + 1) + "]" : "";
        parts.unshift(tagName + pathIndex);
        current = current.parentElement;
      }
      return "/" + parts.join("/");
    };
    DebugInfoCollector.prototype._getEventListeners = function(element) {
      var listeners = [];
      var eventAttrs = [
        "onclick",
        "onload",
        "onchange",
        "onsubmit",
        "onmouseover",
        "onmouseout"
      ];
      eventAttrs.forEach(function(attr) {
        if (element.hasAttribute(attr)) listeners.push(attr);
      });
      return listeners;
    };
    DebugInfoCollector.prototype._getParentChain = function(element) {
      var chain = [];
      var current = element.parentElement;
      var depth = 0;
      var self = this;
      while (current && depth < 5) {
        chain.push(self.buildCSSSelector(current));
        current = current.parentElement;
        depth++;
      }
      return chain;
    };
    DebugInfoCollector.prototype._getAppliedStylesheets = function() {
      var sheets = [];
      for (var i = 0; i < document.styleSheets.length; i++) {
        try {
          var sheet = document.styleSheets[i];
          if (sheet.href) sheets.push(sheet.href);
          else if (sheet.ownerNode) sheets.push("<inline style>");
        } catch (e) {
          sheets.push("<cross-origin stylesheet>");
        }
      }
      return sheets;
    };
    DebugInfoCollector.prototype._getMatchingCSSRules = function(element) {
      var matchingRules = [];
      for (var i = 0; i < document.styleSheets.length; i++) {
        try {
          var sheet = document.styleSheets[i];
          if (!sheet.cssRules) continue;
          for (var j = 0; j < sheet.cssRules.length; j++) {
            var rule = sheet.cssRules[j];
            if (rule instanceof CSSStyleRule) {
              try {
                if (element.matches(rule.selectorText)) {
                  matchingRules.push({
                    selector: rule.selectorText,
                    cssText: rule.cssText.substring(0, 200) + (rule.cssText.length > 200 ? "..." : ""),
                    source: sheet.href || "<inline style>",
                    ruleIndex: j
                  });
                }
              } catch (e) {
              }
            }
          }
        } catch (e) {
        }
      }
      return matchingRules;
    };
    DebugInfoCollector.prototype.gatherElementDebugInfo = function(element) {
      var info = {};
      info.url = window.location.href;
      info.timestamp = (/* @__PURE__ */ new Date()).toISOString();
      var className = typeof element.className === "string" ? element.className : "";
      info.element = {
        tag: element.tagName.toLowerCase(),
        id: element.id || null,
        classes: className ? className.split(/\s+/).filter(function(c) {
          return c;
        }) : [],
        selector: this.buildCSSSelector(element),
        xpath: this.getXPath(element)
      };
      info.attributes = {};
      for (var i = 0; i < element.attributes.length; i++) {
        var attr = element.attributes[i];
        info.attributes[attr.name] = attr.value;
      }
      if (element instanceof HTMLElement) {
        var computed = window.getComputedStyle(element);
        info.styles = {
          display: computed.display,
          position: computed.position,
          width: computed.width,
          height: computed.height,
          margin: computed.margin,
          padding: computed.padding,
          backgroundColor: computed.backgroundColor,
          color: computed.color,
          fontSize: computed.fontSize,
          fontFamily: computed.fontFamily,
          zIndex: computed.zIndex,
          opacity: computed.opacity,
          visibility: computed.visibility,
          overflow: computed.overflow
        };
        if (element.style.cssText) info.inlineStyles = element.style.cssText;
        var rect = element.getBoundingClientRect();
        info.dimensions = {
          width: rect.width,
          height: rect.height,
          top: rect.top,
          left: rect.left,
          bottom: rect.bottom,
          right: rect.right
        };
        info.scroll = {
          scrollTop: element.scrollTop,
          scrollLeft: element.scrollLeft,
          scrollHeight: element.scrollHeight,
          scrollWidth: element.scrollWidth
        };
        info.content = {
          innerHTML: element.innerHTML.substring(0, 200) + (element.innerHTML.length > 200 ? "..." : ""),
          textContent: (element.textContent || "").substring(0, 200) + ((element.textContent || "").length > 200 ? "..." : "")
        };
      }
      info.eventListeners = this._getEventListeners(element);
      info.parentChain = this._getParentChain(element);
      info.appliedStylesheets = this._getAppliedStylesheets();
      info.matchingCSSRules = this._getMatchingCSSRules(element);
      return this._formatDebugInfoForAI(info);
    };
    DebugInfoCollector.prototype._formatDebugInfoForAI = function(info) {
      var attrs = Object.entries(info.attributes || {}).map(function(kv) {
        return "- " + kv[0] + ": " + kv[1];
      }).join("\n");
      var styles = Object.entries(info.styles || {}).map(function(kv) {
        return "- " + kv[0] + ": " + kv[1];
      }).join("\n");
      var listeners = info.eventListeners && info.eventListeners.length > 0 ? info.eventListeners.join(", ") : "none detected";
      var parents = (info.parentChain || []).map(function(p, i) {
        return i + 1 + ". " + p;
      }).join("\n");
      var sheets = (info.appliedStylesheets || []).slice(0, 10).map(function(s, i) {
        return i + 1 + ". " + s;
      }).join("\n");
      var rulesCount = (info.matchingCSSRules || []).length;
      var rulesText = rulesCount > 0 ? info.matchingCSSRules.slice(0, 10).map(function(rule, i) {
        return "\n### " + (i + 1) + ". " + rule.selector + "\n- Source: " + rule.source + "\n- Rule Index: " + rule.ruleIndex + "\n- CSS: " + rule.cssText + "\n";
      }).join("\n") : "No matching rules found (may be due to CORS restrictions)";
      return "# Element Debug Information\n\n## Page Context\n- URL: " + info.url + "\n- Timestamp: " + info.timestamp + "\n\n## Element Identification\n- Tag: <" + info.element.tag + ">\n- ID: " + (info.element.id || "none") + "\n- Classes: " + (info.element.classes.join(", ") || "none") + "\n- CSS Selector: " + info.element.selector + "\n- XPath: " + info.element.xpath + "\n\n## Attributes\n" + (attrs || "none") + "\n\n## Computed Styles\n" + (styles || "none") + "\n\n" + (info.inlineStyles ? "## Inline Styles\n" + info.inlineStyles + "\n\n" : "") + "## Dimensions & Position\n- Width: " + (info.dimensions ? info.dimensions.width : "?") + "px\n- Height: " + (info.dimensions ? info.dimensions.height : "?") + "px\n- Top: " + (info.dimensions ? info.dimensions.top : "?") + "px\n- Left: " + (info.dimensions ? info.dimensions.left : "?") + "px\n\n## Scroll State\n- scrollTop: " + (info.scroll ? info.scroll.scrollTop : "?") + "\n- scrollLeft: " + (info.scroll ? info.scroll.scrollLeft : "?") + "\n\n## Content (truncated)\n" + (info.content ? info.content.textContent : "none") + "\n\n## Event Listeners\n" + listeners + "\n\n## Parent Chain\n" + parents + "\n\n## Applied Stylesheets\n" + sheets + "\n\n## Matching CSS Rules (" + rulesCount + " rules)\n" + rulesText + "\n\n---\nThis debug information was captured by Element Inspector.\n";
    };
    EI.DebugInfoCollector = DebugInfoCollector;
  })();
  (function() {
    var EI = window.__EI = window.__EI || {};
    function OverlayManager() {
      this._container = null;
    }
    OverlayManager.prototype.isActive = function() {
      return this._container !== null;
    };
    OverlayManager.prototype.getContainer = function() {
      return this._container;
    };
    OverlayManager.prototype.createOverlay = function() {
      this._container = document.createElement("div");
      this._container.id = "element-inspector-overlay";
      var docHeight = Math.max(
        document.body.scrollHeight,
        document.documentElement.scrollHeight,
        document.body.offsetHeight,
        document.documentElement.offsetHeight,
        document.body.clientHeight,
        document.documentElement.clientHeight
      );
      this._container.style.cssText = "position:absolute;top:0;left:0;width:100%;height:" + docHeight + "px;pointer-events:none;z-index:999999;";
      document.body.appendChild(this._container);
      return this._container;
    };
    OverlayManager.prototype.removeOverlay = function() {
      if (this._container) {
        this._container.remove();
        this._container = null;
      }
    };
    EI.OverlayManager = OverlayManager;
    function LabelRenderer(debugCollector, notificationManager) {
      this._debug = debugCollector;
      this._notify = notificationManager;
    }
    LabelRenderer.prototype.shouldShowLabel = function(element, rect, depth) {
      if (element.id) return rect.width > 20 && rect.height > 20;
      if (rect.width > 100 || rect.height > 100) return true;
      var importantTags = [
        "header",
        "nav",
        "main",
        "section",
        "article",
        "aside",
        "footer",
        "form",
        "table"
      ];
      if (importantTags.indexOf(element.tagName.toLowerCase()) !== -1 && (rect.width > 50 || rect.height > 50))
        return true;
      var interactiveTags = ["button", "a", "input", "select", "textarea"];
      if (interactiveTags.indexOf(element.tagName.toLowerCase()) !== -1 && (rect.width > 30 || rect.height > 30))
        return true;
      if (depth > 8 && rect.width < 100 && rect.height < 100) return false;
      return false;
    };
    LabelRenderer.prototype.findLabelPosition = function(rect, occupiedPositions) {
      var scrollY = window.scrollY;
      var scrollX = window.scrollX;
      var positions = [
        { top: rect.top + scrollY - 24, left: rect.left + scrollX },
        { top: rect.top + scrollY - 24, left: rect.right + scrollX - 200 },
        { top: rect.top + scrollY + 4, left: rect.left + scrollX + 4 },
        { top: rect.top + scrollY + 4, left: rect.right + scrollX - 204 },
        { top: rect.bottom + scrollY + 4, left: rect.left + scrollX },
        { top: rect.bottom + scrollY + 4, left: rect.right + scrollX - 200 },
        {
          top: rect.top + scrollY + rect.height / 2 - 10,
          left: rect.left + scrollX - 210
        },
        {
          top: rect.top + scrollY + rect.height / 2 - 10,
          left: rect.right + scrollX + 10
        },
        { top: rect.top + scrollY - 48, left: rect.left + scrollX },
        { top: rect.bottom + scrollY + 28, left: rect.left + scrollX }
      ];
      for (var i = 0; i < positions.length; i++) {
        if (!this._isOccupied(positions[i], occupiedPositions)) {
          return {
            top: positions[i].top,
            left: positions[i].left,
            isValid: true
          };
        }
      }
      return { top: 0, left: 0, isValid: false };
    };
    LabelRenderer.prototype._isOccupied = function(pos, occupied) {
      var w = 250, h = 20;
      for (var i = 0; i < occupied.length; i++) {
        var o = occupied[i];
        if (!(pos.left + w < o.left || pos.left > o.right || pos.top + h < o.top || pos.top > o.bottom))
          return true;
      }
      return false;
    };
    LabelRenderer.prototype.createLabel = function(element, depth) {
      var tag = element.tagName.toLowerCase();
      var id = element.id;
      var classes = element.className;
      var labelText = '<span class="element-inspector-label-tag">' + tag + "</span>";
      if (id)
        labelText += ' <span class="element-inspector-label-id">#' + id + "</span>";
      if (classes && typeof classes === "string") {
        var classList = classes.split(/\s+/).filter(function(c) {
          return c.length > 0;
        });
        if (classList.length > 0) {
          var preview = classList.slice(0, 2).join(".");
          labelText += ' <span class="element-inspector-label-class">.' + preview + "</span>";
          if (classList.length > 2)
            labelText += '<span class="element-inspector-label-class">+' + (classList.length - 2) + "</span>";
        }
      }
      if (depth > 5)
        labelText += ' <span style="color:#999;font-size:9px;">d' + depth + "</span>";
      var label = document.createElement("div");
      label.className = "element-inspector-label";
      label.innerHTML = labelText;
      label.title = "Right-click to copy comprehensive debug info for AI";
      return label;
    };
    LabelRenderer.prototype.addCopyToClipboard = function(label, element) {
      var self = this;
      label.addEventListener("contextmenu", function(e) {
        e.stopPropagation();
        e.preventDefault();
        var debugInfo = self._debug.gatherElementDebugInfo(element);
        navigator.clipboard.writeText(debugInfo).then(function() {
          self._notify.showNotification("Copied!", "success");
          console.log("[ElementInspector] Copied debug info to clipboard");
          self._notify.triggerCopyCallback();
        }).catch(function(err) {
          console.error("[ElementInspector] Failed to copy:", err);
          self._notify.showNotification("Copy Failed", "error");
        });
      });
    };
    LabelRenderer.prototype.addHoverHighlight = function(label, box, element, onHover) {
      label.addEventListener("mouseenter", function() {
        onHover(box, element);
        box.classList.add("highlighted");
        if (element instanceof HTMLElement) {
          element.style.outline = "3px solid rgba(59,130,246,0.8)";
          element.style.outlineOffset = "2px";
        }
      });
      label.addEventListener("mouseleave", function() {
        onHover(null, null);
        box.classList.remove("highlighted");
        if (element instanceof HTMLElement) {
          element.style.outline = "";
          element.style.outlineOffset = "";
        }
      });
    };
    EI.LabelRenderer = LabelRenderer;
  })();
  (function() {
    var EI = window.__EI = window.__EI || {};
    var getDepth = EI.getDepth;
    var getColorForDepth = EI.getColorForDepth;
    EI.LabelRenderer;
    function LayerPickerPanel(debugCollector, notificationManager) {
      this._panel = null;
      this._elements = [];
      this._index = 0;
      this._debug = debugCollector;
      this._notify = notificationManager;
      this._highlightCb = null;
    }
    LayerPickerPanel.prototype.setHighlightCallback = function(cb) {
      this._highlightCb = cb;
    };
    LayerPickerPanel.prototype.getCurrentDepthIndex = function() {
      return this._index;
    };
    LayerPickerPanel.prototype.getElementsAtCursor = function() {
      return this._elements;
    };
    LayerPickerPanel.prototype.getSelectedElement = function() {
      if (this._elements.length > 0 && this._index < this._elements.length)
        return this._elements[this._index];
      return null;
    };
    LayerPickerPanel.prototype.show = function(x, y, elements) {
      this.remove();
      this._elements = elements;
      this._index = 0;
      if (elements.length <= 1) return;
      var panel = document.createElement("div");
      panel.className = "element-inspector-layer-picker";
      panel.tabIndex = 0;
      panel.style.cssText = "position:fixed;top:" + Math.min(y + 10, window.innerHeight - 300) + "px;left:" + Math.min(x + 15, window.innerWidth - 220) + "px;background:rgba(30,30,30,0.95);border:1px solid rgba(100,100,100,0.5);border-radius:6px;padding:6px 0;min-width:200px;max-height:280px;overflow-y:auto;z-index:10000001;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',monospace;font-size:11px;box-shadow:0 4px 16px rgba(0,0,0,0.4);outline:none;";
      var header = document.createElement("div");
      header.style.cssText = "padding:4px 10px 6px;color:#888;border-bottom:1px solid rgba(100,100,100,0.3);margin-bottom:4px;font-size:10px;";
      header.textContent = elements.length + " layers (scroll / arrow keys)";
      panel.appendChild(header);
      this._setupKeyboard(panel);
      this._renderList(panel, elements);
      document.body.appendChild(panel);
      this._panel = panel;
      this.updateSelection();
      setTimeout(function() {
        panel.focus();
      }, 10);
    };
    LayerPickerPanel.prototype._renderList = function(panel, elements) {
      var self = this;
      elements.forEach(function(el, index) {
        var item = document.createElement("div");
        item.dataset.index = String(index);
        item.style.cssText = "padding:5px 10px;cursor:pointer;display:flex;align-items:center;gap:6px;transition:background 0.1s;";
        var depthBar = document.createElement("span");
        var depth = getDepth(el);
        depthBar.style.cssText = "width:" + Math.min(depth * 3, 30) + "px;height:3px;background:" + getColorForDepth(depth) + ";border-radius:2px;flex-shrink:0;";
        var indexNum = document.createElement("span");
        indexNum.style.cssText = "color:#666;width:18px;text-align:right;";
        indexNum.textContent = String(index + 1);
        var info = document.createElement("span");
        var tag = el.tagName.toLowerCase();
        var id = el.id ? "#" + el.id : "";
        var cls = el.className && typeof el.className === "string" ? "." + el.className.split(" ")[0].substring(0, 15) : "";
        info.innerHTML = '<span style="color:#61afef">' + tag + '</span><span style="color:#e5c07b">' + id + '</span><span style="color:#98c379">' + cls + "</span>";
        info.style.cssText = "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
        item.appendChild(depthBar);
        item.appendChild(indexNum);
        item.appendChild(info);
        item.addEventListener("mouseenter", function() {
          item.style.background = "rgba(100,100,100,0.3)";
        });
        item.addEventListener("mouseleave", function() {
          if (self._index !== index) item.style.background = "";
        });
        item.addEventListener("click", function() {
          self._index = index;
          if (self._highlightCb) self._highlightCb(el);
          self.updateSelection();
        });
        panel.appendChild(item);
      });
    };
    LayerPickerPanel.prototype._setupKeyboard = function(panel) {
      var self = this;
      panel.addEventListener("keydown", function(e) {
        var maxIndex = self._elements.length - 1;
        switch (e.key) {
          case "ArrowDown":
          case "Tab":
            if (!e.shiftKey) {
              e.preventDefault();
              e.stopPropagation();
              self._index = Math.min(self._index + 1, maxIndex);
            } else if (e.key === "Tab") {
              e.preventDefault();
              e.stopPropagation();
              self._index = Math.max(self._index - 1, 0);
            }
            if (self._highlightCb) self._highlightCb(self._elements[self._index]);
            self.updateSelection();
            break;
          case "ArrowUp":
            e.preventDefault();
            e.stopPropagation();
            self._index = Math.max(self._index - 1, 0);
            if (self._highlightCb) self._highlightCb(self._elements[self._index]);
            self.updateSelection();
            break;
          case "Enter":
            e.preventDefault();
            e.stopPropagation();
            self._confirmSelection();
            break;
          case "Escape":
            e.preventDefault();
            e.stopPropagation();
            self.remove();
            break;
        }
      });
    };
    LayerPickerPanel.prototype._confirmSelection = function() {
      if (this._elements.length === 0) return;
      var el = this._elements[this._index];
      if (!el) return;
      var debugInfo = this._debug.gatherElementDebugInfo(el);
      var self = this;
      navigator.clipboard.writeText(debugInfo).then(function() {
        self._notify.showNotification("Copied!", "success");
        self._notify.triggerCopyCallback();
      }).catch(function(err) {
        console.error("[ElementInspector] Failed to copy:", err);
        self._notify.showNotification("Copy Failed", "error");
      });
    };
    LayerPickerPanel.prototype.updateSelection = function() {
      if (!this._panel) return;
      var self = this;
      var items = this._panel.querySelectorAll("[data-index]");
      items.forEach(function(item, index) {
        if (index === self._index) {
          item.style.background = "rgba(59,130,246,0.4)";
          item.style.borderLeft = "2px solid #3b82f6";
          item.scrollIntoView({ block: "nearest" });
        } else {
          item.style.background = "";
          item.style.borderLeft = "";
        }
      });
    };
    LayerPickerPanel.prototype.navigate = function(direction) {
      if (this._elements.length <= 1) return;
      if (direction === "down")
        this._index = Math.min(this._index + 1, this._elements.length - 1);
      else this._index = Math.max(this._index - 1, 0);
      if (this._highlightCb) this._highlightCb(this._elements[this._index]);
      this.updateSelection();
    };
    LayerPickerPanel.prototype.remove = function() {
      if (this._panel) {
        this._panel.remove();
        this._panel = null;
      }
    };
    LayerPickerPanel.prototype.reset = function() {
      this.remove();
      this._elements = [];
      this._index = 0;
    };
    EI.LayerPickerPanel = LayerPickerPanel;
  })();
  (function() {
    var EI = window.__EI = window.__EI || {};
    var getDepth = EI.getDepth;
    var getColorForDepth = EI.getColorForDepth;
    var LabelRenderer = EI.LabelRenderer;
    var LayerPickerPanel = EI.LayerPickerPanel;
    var BATCH_SIZE = 512;
    var MIN_SIZE = 10;
    function ElementScanner(debugCollector, notificationManager) {
      this._debug = debugCollector;
      this._notify = notificationManager;
      this._elementBoxMap = /* @__PURE__ */ new Map();
      this._hoveredBox = null;
      this._hoveredElement = null;
      this._batchStart = 0;
      this._allVisible = [];
      this._overlayRef = null;
      this._lastCursorX = 0;
      this._lastCursorY = 0;
      this._wheelHandler = null;
      this._directHighlight = null;
      this._layerPicker = new LayerPickerPanel(
        debugCollector,
        notificationManager
      );
      this._labelRenderer = new LabelRenderer(
        debugCollector,
        notificationManager
      );
      var self = this;
      this._layerPicker.setHighlightCallback(function(el) {
        if (self._overlayRef) self._highlightElement(el, self._overlayRef);
      });
    }
    ElementScanner.prototype.getElementBoxMap = function() {
      return this._elementBoxMap;
    };
    ElementScanner.prototype.getDepthSelectedElement = function() {
      return this._layerPicker.getSelectedElement() || this._hoveredElement;
    };
    ElementScanner.prototype.clearElementBoxMap = function() {
      this._elementBoxMap.clear();
      this._hoveredBox = null;
      this._hoveredElement = null;
      this._batchStart = 0;
      this._allVisible = [];
      this._overlayRef = null;
      if (this._wheelHandler) {
        document.removeEventListener("wheel", this._wheelHandler);
        this._wheelHandler = null;
      }
      this._layerPicker.reset();
      this._clearDirectHighlight();
    };
    ElementScanner.prototype.scanElements = function(overlayContainer) {
      this._overlayRef = overlayContainer;
      if (this._allVisible.length === 0) this._collectVisible();
      this._renderBatch(overlayContainer);
      this._setupWheel(overlayContainer);
    };
    ElementScanner.prototype._collectVisible = function() {
      var startTime = performance.now();
      var all = document.querySelectorAll("*");
      for (var i = 0; i < all.length; i++) {
        var element = all[i];
        if (!element || !element.tagName) continue;
        if (element.closest("#element-inspector-overlay")) continue;
        var tagName = element.tagName.toLowerCase();
        if (["script", "style", "link", "meta", "head", "noscript", "br"].indexOf(
          tagName
        ) !== -1)
          continue;
        var rect = element.getBoundingClientRect();
        if (rect.width < MIN_SIZE || rect.height < MIN_SIZE) continue;
        if (element instanceof HTMLElement) {
          if (element.offsetParent === null && tagName !== "body" && tagName !== "html") {
            if (element.style.display === "none") continue;
          }
        }
        this._allVisible.push(element);
      }
      var elapsed = (performance.now() - startTime).toFixed(1);
      console.log(
        "[ElementInspector] Found " + this._allVisible.length + " visible elements in " + elapsed + "ms"
      );
    };
    ElementScanner.prototype._renderBatch = function(overlayContainer) {
      var startTime = performance.now();
      var fragment = document.createDocumentFragment();
      var occupiedPositions = [];
      var scrollY = window.scrollY;
      var scrollX = window.scrollX;
      var batchEnd = Math.min(
        this._batchStart + BATCH_SIZE,
        this._allVisible.length
      );
      var count = 0;
      var self = this;
      for (var i = this._batchStart; i < batchEnd; i++) {
        var element = this._allVisible[i];
        var rect = element.getBoundingClientRect();
        var margin = 100;
        if (rect.bottom < -margin || rect.top > window.innerHeight + margin || rect.right < -margin || rect.left > window.innerWidth + margin)
          continue;
        var depth = getDepth(element);
        var color = getColorForDepth(depth);
        var area = rect.width * rect.height;
        var borderWidth = area > 1e5 ? 1 : area > 1e4 ? 1.5 : 2;
        var box = document.createElement("div");
        box.className = "element-inspector-box";
        box.style.cssText = "top:" + (rect.top + scrollY) + "px;left:" + (rect.left + scrollX) + "px;width:" + rect.width + "px;height:" + rect.height + "px;border-color:" + color + ";border-width:" + borderWidth + "px;";
        var id = element.id ? "#" + element.id : "";
        box.title = "Right-click to copy | Scroll to cycle depth: " + element.tagName.toLowerCase() + id;
        this._elementBoxMap.set(box, element);
        (function(b, el) {
          b.addEventListener("mouseenter", function() {
            self._hoveredBox = b;
            self._hoveredElement = el;
          });
          b.addEventListener("mouseleave", function() {
            if (self._hoveredBox === b) {
              self._hoveredBox = null;
              self._hoveredElement = null;
            }
          });
          b.addEventListener("click", function(e) {
            b.style.pointerEvents = "none";
            var under = document.elementFromPoint(e.clientX, e.clientY);
            b.style.pointerEvents = "";
            if (under && under !== b) {
              var clickEvt = new MouseEvent("click", {
                bubbles: true,
                cancelable: true,
                view: window,
                clientX: e.clientX,
                clientY: e.clientY
              });
              under.dispatchEvent(clickEvt);
            }
          });
          b.addEventListener("contextmenu", function(e) {
            e.preventDefault();
            e.stopPropagation();
            var selEl = self._hoveredElement || el;
            var selBox = self._hoveredBox || b;
            selBox.classList.add("highlighted");
            var debugInfo = self._debug.gatherElementDebugInfo(selEl);
            navigator.clipboard.writeText(debugInfo).then(function() {
              self._notify.showNotification("Copied!", "success");
              console.log("[ElementInspector] Copied:", debugInfo);
              self._notify.triggerCopyCallback();
            }).catch(function(err) {
              console.error("[ElementInspector] Copy failed:", err);
              self._notify.showNotification("Copy Failed", "error");
              selBox.classList.remove("highlighted");
            });
          });
        })(box, element);
        if (this._labelRenderer.shouldShowLabel(element, rect, depth)) {
          var label = this._labelRenderer.createLabel(element, depth);
          if (label) {
            var labelPos = this._labelRenderer.findLabelPosition(
              rect,
              occupiedPositions
            );
            if (labelPos.isValid) {
              label.style.top = labelPos.top + "px";
              label.style.left = labelPos.left + "px";
              this._labelRenderer.addCopyToClipboard(label, element);
              this._labelRenderer.addHoverHighlight(
                label,
                box,
                element,
                function(b, e) {
                  self._hoveredBox = b;
                  self._hoveredElement = e;
                }
              );
              occupiedPositions.push({
                top: labelPos.top - 8,
                left: labelPos.left - 8,
                bottom: labelPos.top + 20 + 8,
                right: labelPos.left + 250 + 8
              });
              fragment.appendChild(label);
            }
          }
        }
        fragment.appendChild(box);
        count++;
      }
      overlayContainer.appendChild(fragment);
      var elapsed = (performance.now() - startTime).toFixed(1);
      var total = this._allVisible.length;
      var remaining = total - batchEnd;
      console.log(
        "[ElementInspector] Rendered " + count + " elements (" + (this._batchStart + 1) + "-" + batchEnd + "/" + total + ") in " + elapsed + "ms" + (remaining > 0 ? " | Ctrl+I for next " + Math.min(remaining, BATCH_SIZE) : "")
      );
      if (remaining > 0)
        this._notify.showNotification(
          batchEnd + "/" + total + " elements | Ctrl+I for more",
          "success",
          2e3
        );
    };
    ElementScanner.prototype.loadNextBatch = function() {
      if (!this._overlayRef) return false;
      var total = this._allVisible.length;
      var nextStart = this._batchStart + BATCH_SIZE;
      if (nextStart >= total) {
        this._notify.showNotification("All elements loaded", "success");
        return false;
      }
      this._batchStart = nextStart;
      this._renderBatch(this._overlayRef);
      return true;
    };
    ElementScanner.prototype._setupWheel = function(overlayContainer) {
      var self = this;
      this._wheelHandler = function(e) {
        if (!overlayContainer.contains(e.target)) return;
        var cursorMoved = Math.abs(e.clientX - self._lastCursorX) > 5 || Math.abs(e.clientY - self._lastCursorY) > 5;
        if (cursorMoved) {
          self._lastCursorX = e.clientX;
          self._lastCursorY = e.clientY;
          var elements = self._getElementsAtPoint(e.clientX, e.clientY);
          self._layerPicker.show(e.clientX, e.clientY, elements);
        }
        var elements = self._layerPicker.getElementsAtCursor();
        if (elements.length <= 1) {
          self._layerPicker.remove();
          return;
        }
        e.preventDefault();
        e.stopPropagation();
        self._layerPicker.navigate(e.deltaY > 0 ? "down" : "up");
      };
      document.addEventListener("wheel", this._wheelHandler, { passive: false });
    };
    ElementScanner.prototype._getElementsAtPoint = function(x, y) {
      var elements = [];
      var allAtPoint = document.elementsFromPoint(x, y);
      for (var i = 0; i < allAtPoint.length; i++) {
        var el = allAtPoint[i];
        if (!el || !el.tagName) continue;
        if (el.closest("#element-inspector-overlay")) continue;
        if (el.closest(".element-inspector-layer-picker")) continue;
        var tag = el.tagName.toLowerCase();
        if (["html", "body", "script", "style", "head"].indexOf(tag) !== -1)
          continue;
        elements.push(el);
      }
      return elements;
    };
    ElementScanner.prototype._clearDirectHighlight = function() {
      if (this._directHighlight instanceof HTMLElement) {
        this._directHighlight.style.outline = "";
        this._directHighlight.style.outlineOffset = "";
      }
      this._directHighlight = null;
    };
    ElementScanner.prototype._highlightElement = function(element, overlayContainer) {
      overlayContainer.querySelectorAll(".element-inspector-box.highlighted").forEach(function(box) {
        box.classList.remove("highlighted");
      });
      this._clearDirectHighlight();
      var found = false;
      for (var entry of this._elementBoxMap) {
        if (entry[1] === element) {
          entry[0].classList.add("highlighted");
          this._hoveredBox = entry[0];
          this._hoveredElement = element;
          found = true;
          break;
        }
      }
      if (!found && element instanceof HTMLElement) {
        element.style.outline = "3px solid #3b82f6";
        element.style.outlineOffset = "2px";
        this._directHighlight = element;
        this._hoveredElement = element;
      }
    };
    EI.ElementScanner = ElementScanner;
  })();
  (function() {
    var EI = window.__EI = window.__EI || {};
    var getDepth = EI.getDepth;
    EI.NotificationManager;
    EI.DebugInfoCollector;
    EI.OverlayManager;
    EI.ElementScanner;
    function SelectionManager(elementBoxMap, debugCollector, notificationManager) {
      this._selectionMode = false;
      this._start = null;
      this._rect = null;
      this._overlay = null;
      this._selectedElements = /* @__PURE__ */ new Set();
      this._boxMap = elementBoxMap;
      this._debug = debugCollector;
      this._notify = notificationManager;
      this._scanner = null;
      var self = this;
      this._onMouseDown = function(e) {
        self._handleMouseDown(e);
      };
      this._onMouseMove = function(e) {
        self._handleMouseMove(e);
      };
      this._onMouseUp = function(e) {
        self._handleMouseUp(e);
      };
    }
    SelectionManager.prototype.setElementScanner = function(scanner) {
      this._scanner = scanner;
    };
    SelectionManager.prototype.isActive = function() {
      return this._selectionMode;
    };
    SelectionManager.prototype.startSelectionMode = function() {
      this._selectionMode = true;
      document.body.classList.add("element-inspector-selection-mode");
      this._overlay = document.createElement("div");
      this._overlay.className = "selection-overlay";
      document.body.appendChild(this._overlay);
      this._notify.showNotification("Drag to select area", "success");
      document.addEventListener("mousedown", this._onMouseDown);
      document.addEventListener("mousemove", this._onMouseMove);
      document.addEventListener("mouseup", this._onMouseUp);
    };
    SelectionManager.prototype.cancelSelectionMode = function() {
      this._selectionMode = false;
      document.body.classList.remove("element-inspector-selection-mode");
      this._clearHighlights();
      if (this._overlay) {
        this._overlay.remove();
        this._overlay = null;
      }
      if (this._rect) {
        this._rect.remove();
        this._rect = null;
      }
      document.removeEventListener("mousedown", this._onMouseDown);
      document.removeEventListener("mousemove", this._onMouseMove);
      document.removeEventListener("mouseup", this._onMouseUp);
      this._start = null;
    };
    SelectionManager.prototype._handleMouseDown = function(e) {
      if (!this._selectionMode) return;
      e.preventDefault();
      this._start = { x: e.clientX, y: e.clientY };
      this._rect = document.createElement("div");
      this._rect.className = "selection-rectangle";
      this._rect.style.left = e.clientX + "px";
      this._rect.style.top = e.clientY + "px";
      this._rect.style.width = "0px";
      this._rect.style.height = "0px";
      document.body.appendChild(this._rect);
    };
    SelectionManager.prototype._handleMouseMove = function(e) {
      if (!this._selectionMode || !this._start || !this._rect) return;
      e.preventDefault();
      var left = Math.min(this._start.x, e.clientX);
      var top = Math.min(this._start.y, e.clientY);
      var width = Math.abs(e.clientX - this._start.x);
      var height = Math.abs(e.clientY - this._start.y);
      this._rect.style.left = left + "px";
      this._rect.style.top = top + "px";
      this._rect.style.width = width + "px";
      this._rect.style.height = height + "px";
    };
    SelectionManager.prototype._handleMouseUp = function(e) {
      if (!this._selectionMode || !this._start || !this._rect) return;
      e.preventDefault();
      var left = Math.min(this._start.x, e.clientX);
      var top = Math.min(this._start.y, e.clientY);
      var width = Math.abs(e.clientX - this._start.x);
      var height = Math.abs(e.clientY - this._start.y);
      if (width < 5 || height < 5) {
        this.cancelSelectionMode();
        this._notify.showNotification("Selection too small", "error");
        return;
      }
      var rect = { left, top, width, height };
      var selectedElements = this._findElementsInRect(rect);
      console.log(
        "[ElementInspector] Found " + selectedElements.length + " elements in selection"
      );
      var info = this._gatherSelectionInfo(selectedElements, rect);
      var self = this;
      navigator.clipboard.writeText(info).then(function() {
        self._notify.showNotification(
          selectedElements.length + " elements copied!",
          "success"
        );
        self._notify.triggerCopyCallback();
      }).catch(function(err) {
        console.error("[ElementInspector] Failed to copy:", err);
        self._notify.showNotification("Copy Failed", "error");
      });
      this.cancelSelectionMode();
    };
    SelectionManager.prototype._clearHighlights = function() {
      var self = this;
      this._boxMap.forEach(function(element, box) {
        if (self._selectedElements.has(element)) {
          box.style.borderWidth = "2px";
          box.style.background = "rgba(255,255,255,0.01)";
          box.style.transform = "";
          box.style.zIndex = "";
        }
      });
      this._selectedElements.forEach(function(element) {
        if (element instanceof HTMLElement)
          element.classList.remove("element-inspector-selected");
      });
      this._selectedElements.clear();
    };
    SelectionManager.prototype._findElementsInRect = function(rect) {
      var selected = [];
      var all = document.querySelectorAll("*");
      var selRect = {
        left: rect.left,
        top: rect.top,
        right: rect.left + rect.width,
        bottom: rect.top + rect.height
      };
      var targetDepth = null;
      if (this._scanner) {
        var depthEl = this._scanner.getDepthSelectedElement();
        if (depthEl) targetDepth = getDepth(depthEl);
      }
      for (var i = 0; i < all.length; i++) {
        var element = all[i];
        if (element.closest("#element-inspector-overlay") || element.classList.contains("selection-rectangle") || element.classList.contains("selection-overlay") || element.closest(".element-inspector-layer-picker"))
          continue;
        var tagName = element.tagName.toLowerCase();
        if ([
          "script",
          "style",
          "link",
          "meta",
          "head",
          "noscript",
          "br",
          "html",
          "body"
        ].indexOf(tagName) !== -1)
          continue;
        if (element instanceof HTMLElement) {
          var computed = window.getComputedStyle(element);
          if (computed.display === "none" || computed.visibility === "hidden")
            continue;
        }
        if (targetDepth !== null && Math.abs(getDepth(element) - targetDepth) > 2)
          continue;
        var elRect = element.getBoundingClientRect();
        if (elRect.width < 10 || elRect.height < 10) continue;
        var intersects = !(elRect.right < selRect.left || elRect.left > selRect.right || elRect.bottom < selRect.top || elRect.top > selRect.bottom);
        if (intersects) selected.push(element);
      }
      return selected;
    };
    SelectionManager.prototype._gatherSelectionInfo = function(elements, rect) {
      var info = "# Rectangle Selection Debug Information\n\n## Selection Area\n- Position: (" + Math.round(rect.left) + ", " + Math.round(rect.top) + ")\n- Size: " + Math.round(rect.width) + "x" + Math.round(rect.height) + "px\n- URL: " + window.location.href + "\n- Timestamp: " + (/* @__PURE__ */ new Date()).toISOString() + "\n- Elements Found: " + elements.length + "\n\n---\n\n";
      var types = {};
      elements.forEach(function(el) {
        var tag = el.tagName.toLowerCase();
        types[tag] = (types[tag] || 0) + 1;
      });
      info += "## Element Type Summary\n";
      Object.entries(types).sort(function(a, b) {
        return b[1] - a[1];
      }).forEach(function(kv) {
        info += "- " + kv[0] + ": " + kv[1] + "\n";
      });
      info += "\n---\n\n";
      var maxDetailed = 20;
      var detailedCount = Math.min(elements.length, maxDetailed);
      info += "## Detailed Element Information (" + detailedCount + " of " + elements.length + " elements)\n\n---\n\n";
      var self = this;
      elements.slice(0, maxDetailed).forEach(function(element, index) {
        info += "# Element " + (index + 1) + "/" + elements.length + "\n\n";
        info += self._debug.gatherElementDebugInfo(element);
        info += "\n" + "=".repeat(80) + "\n\n";
      });
      if (elements.length > maxDetailed) {
        info += "## Remaining Elements (" + (elements.length - maxDetailed) + " elements - basic info)\n\n";
        elements.slice(maxDetailed).forEach(function(element, index) {
          var actualIndex = maxDetailed + index + 1;
          var selector = self._debug.buildCSSSelector(element);
          var r = element.getBoundingClientRect();
          var text = (element.textContent || "").trim().substring(0, 50);
          info += "### " + actualIndex + ". " + selector + "\n";
          info += "- Position: (" + Math.round(r.left) + ", " + Math.round(r.top) + ") | Size: " + Math.round(r.width) + "x" + Math.round(r.height) + "px\n";
          if (text)
            info += '- Text: "' + text + (text.length > 50 ? "..." : "") + '"\n';
          info += "\n";
        });
      }
      info += "\n---\nGenerated by Element Inspector - Rectangle Selection Mode\n";
      return info;
    };
    EI.SelectionManager = SelectionManager;
  })();
  (function() {
    var EI = window.__EI = window.__EI || {};
    var NotificationManager = EI.NotificationManager;
    var DebugInfoCollector = EI.DebugInfoCollector;
    var OverlayManager = EI.OverlayManager;
    var ElementScanner = EI.ElementScanner;
    var SelectionManager = EI.SelectionManager;
    function ConsoleCollector(notificationManager) {
      this._notify = notificationManager;
      this._logs = [];
      this._networkErrors = [];
      this._maxLogs = 1e3;
      this._origConsole = {
        log: console.log.bind(console),
        warn: console.warn.bind(console),
        error: console.error.bind(console),
        info: console.info.bind(console),
        debug: console.debug.bind(console)
      };
      this._startCapturing();
      this._captureNetworkErrors();
    }
    ConsoleCollector.prototype._captureNetworkErrors = function() {
      var self = this;
      window.addEventListener(
        "error",
        function(e) {
          if (e.target && e.target.tagName) {
            var src = e.target.src || e.target.href || "";
            if (src) self._networkErrors.push("Failed to load resource: " + src);
          }
        },
        true
      );
    };
    ConsoleCollector.prototype._startCapturing = function() {
      var self = this;
      ["log", "warn", "error", "info", "debug"].forEach(function(type) {
        console[type] = function() {
          var args = Array.prototype.slice.call(arguments);
          self._captureLog(type, args);
          self._origConsole[type].apply(console, args);
        };
      });
    };
    ConsoleCollector.prototype._captureLog = function(type, args) {
      this._logs.push({
        type,
        timestamp: (/* @__PURE__ */ new Date()).toISOString(),
        args: args.map(function(a) {
          if (a === null) return "null";
          if (a === void 0) return "undefined";
          if (typeof a === "string") return a;
          if (typeof a === "number" || typeof a === "boolean") return String(a);
          if (a instanceof Error)
            return a.name + ": " + a.message + "\n" + (a.stack || "");
          try {
            return JSON.stringify(a, null, 2);
          } catch (e) {
            return String(a);
          }
        })
      });
      if (this._logs.length > this._maxLogs) this._logs.shift();
    };
    ConsoleCollector.prototype.getConsoleLogs = function() {
      var total = this._logs.length + this._networkErrors.length;
      if (total === 0) return "No console logs captured.";
      var output = "";
      this._networkErrors.forEach(function(err) {
        output += "ERROR: " + err + "\n";
      });
      this._logs.forEach(function(entry) {
        output += "[" + entry.type.toUpperCase() + "] " + entry.args.join(" ") + "\n";
      });
      return output;
    };
    ConsoleCollector.prototype.captureDebugSnapshot = function() {
      this._notify.showCameraFlash();
      var logsText = this.getConsoleLogs();
      if (!logsText || logsText === "No console logs captured.") {
        this._notify.showNotification("No logs to copy", "error");
        this._notify.triggerCopyCallback();
        return;
      }
      var self = this;
      navigator.clipboard.writeText(logsText).then(function() {
        self._notify.showNotification("Console logs copied!", "success");
        self._notify.triggerCopyCallback();
      }).catch(function(err) {
        self._origConsole.error("[ConsoleCollector] Clipboard failed:", err);
        self._notify.showNotification("Copy Failed", "error");
        self._notify.triggerCopyCallback();
      });
    };
    function PageStructureExporter(notificationManager) {
      this._notify = notificationManager;
    }
    PageStructureExporter.prototype.copyPageStructure = function() {
      console.log("[ElementInspector] Generating full page structure...");
      this._notify.showCameraFlash();
      var structure = this._generate();
      var self = this;
      navigator.clipboard.writeText(structure).then(function() {
        self._notify.showNotification("Page structure copied!", "success");
        self._notify.triggerCopyCallback();
      }).catch(function(err) {
        console.error("[ElementInspector] Failed to copy page structure:", err);
        self._notify.showNotification("Copy Failed", "error");
      });
    };
    PageStructureExporter.prototype._generate = function() {
      var info = {
        url: window.location.href,
        timestamp: (/* @__PURE__ */ new Date()).toISOString(),
        viewport: {
          width: window.innerWidth,
          height: window.innerHeight
        },
        document: { title: document.title },
        structure: this._buildTree(document.body, 0, 10)
      };
      return "# Full Page Structure\n\n## Page Information\n- URL: " + info.url + "\n- Title: " + info.document.title + "\n- Timestamp: " + info.timestamp + "\n- Viewport: " + info.viewport.width + "x" + info.viewport.height + "\n\n## Document Structure\n```json\n" + JSON.stringify(info.structure, null, 2) + "\n```\n";
    };
    PageStructureExporter.prototype._buildTree = function(element, depth, maxDepth) {
      if (depth > maxDepth) return { truncated: true };
      var className = typeof element.className === "string" ? element.className : "";
      var node = { tag: element.tagName.toLowerCase() };
      if (element.id) node.id = element.id;
      if (className)
        node.classes = className.split(/\s+/).filter(function(c) {
          return c;
        });
      var children = [];
      for (var i = 0; i < element.children.length; i++) {
        var child = element.children[i];
        if (child.tagName !== "SCRIPT" && child.tagName !== "STYLE") {
          children.push(this._buildTree(child, depth + 1, maxDepth));
        }
      }
      if (children.length > 0) node.children = children;
      return node;
    };
    function ElementInspector() {
      this._isActive = false;
      this._notifyMgr = new NotificationManager();
      this._debugCollector = new DebugInfoCollector();
      this._overlayMgr = new OverlayManager();
      this._elementScanner = new ElementScanner(
        this._debugCollector,
        this._notifyMgr
      );
      this._selectionMgr = new SelectionManager(
        this._elementScanner.getElementBoxMap(),
        this._debugCollector,
        this._notifyMgr
      );
      this._selectionMgr.setElementScanner(this._elementScanner);
      this._pageExporter = new PageStructureExporter(this._notifyMgr);
      this._consoleCollector = new ConsoleCollector(this._notifyMgr);
      var self = this;
      this._notifyMgr.setOnCopyCallback(function() {
        self.deactivate();
      });
      this._init();
    }
    ElementInspector.prototype._init = function() {
      var self = this;
      document.addEventListener("keydown", function(e) {
        var key = e.key.toLowerCase();
        if ([
          "Tab",
          "Enter",
          "ArrowUp",
          "ArrowDown",
          "ArrowLeft",
          "ArrowRight"
        ].indexOf(e.key) !== -1)
          return;
        if (e.ctrlKey && e.shiftKey && !e.altKey && key === "i") {
          e.preventDefault();
          e.stopPropagation();
          console.log(
            "[ElementInspector] Ctrl+Shift+I pressed - capturing debug snapshot"
          );
          self._consoleCollector.captureDebugSnapshot();
          return;
        }
        if (e.ctrlKey && e.altKey && !e.shiftKey && key === "i") {
          e.preventDefault();
          self._startSelectionMode();
          return;
        }
        if (e.ctrlKey && !e.altKey && !e.shiftKey && key === "i") {
          if (self._isActive) {
            e.preventDefault();
            self._elementScanner.loadNextBatch();
            return;
          }
        }
        if (e.altKey && !e.shiftKey && !e.ctrlKey && key === "i") {
          e.preventDefault();
          self.toggle();
          return;
        }
        if (e.key === "Escape") {
          if (self._selectionMgr.isActive()) {
            e.preventDefault();
            self._selectionMgr.cancelSelectionMode();
            self.deactivate();
          } else if (self._isActive) {
            e.preventDefault();
            self.deactivate();
          }
          return;
        }
      });
      console.log("[ElementInspector] Initialized");
      console.log("  Alt+I: Toggle inspector overlay");
      console.log("  Ctrl+I: Load next 512 elements (when active)");
      console.log("  Ctrl+Alt+I: Rectangle selection mode");
      console.log("  Ctrl+Shift+I: Debug snapshot (console logs)");
      console.log("  Scroll wheel: Cycle through overlapped elements");
      console.log("  Right-click: Copy element debug info");
      console.log("  Left-click: Pass through to underlying element");
      console.log("  Escape: Deactivate inspector / Cancel selection");
    };
    ElementInspector.prototype.toggle = function() {
      if (this._isActive) this.deactivate();
      else this.activate();
    };
    ElementInspector.prototype.activate = function() {
      console.log("[ElementInspector] Activating...");
      this._isActive = true;
      var container = this._overlayMgr.createOverlay();
      this._elementScanner.scanElements(container);
      console.log("[ElementInspector] Active - Press Alt+I to deactivate");
    };
    ElementInspector.prototype.deactivate = function() {
      console.log("[ElementInspector] Deactivating...");
      this._isActive = false;
      this._elementScanner._clearDirectHighlight();
      this._elementScanner.clearElementBoxMap();
      this._overlayMgr.removeOverlay();
    };
    ElementInspector.prototype.refresh = function() {
      if (this._isActive) {
        this.deactivate();
        this.activate();
      }
    };
    ElementInspector.prototype._startSelectionMode = function() {
      if (!this._isActive) this.activate();
      this._selectionMgr.startSelectionMode();
    };
    var elementInspector = new ElementInspector();
    window.elementInspector = elementInspector;
    var resizeTimeout;
    window.addEventListener("resize", function() {
      clearTimeout(resizeTimeout);
      resizeTimeout = window.setTimeout(function() {
        if (window.elementInspector && window.elementInspector._isActive) {
          window.elementInspector.refresh();
        }
      }, 500);
    });
  })();
  (function() {
    var _overlay = null;
    var _input = null;
    var _results = null;
    var _status = null;
    var _cache = [];
    var _cacheTs = 0;
    var _CACHE_TTL = 60 * 1e3;
    var _debounceTimer = null;
    var _selectedIdx = -1;
    var _loading = false;
    function fm(query, text) {
      if (typeof _fm === "function") return _fm(query, text);
      if (typeof fuzzyMatch === "function") return fuzzyMatch(query, text) >= 0;
      return text.toLowerCase().indexOf(query.toLowerCase()) >= 0;
    }
    function buildDOM() {
      if (_overlay) return;
      _overlay = document.createElement("div");
      _overlay.id = "search-palette-overlay";
      _overlay.setAttribute("role", "dialog");
      _overlay.setAttribute("aria-modal", "true");
      _overlay.setAttribute("aria-label", "Global message search");
      _overlay.innerHTML = '<div id="search-palette-modal"><div id="search-palette-input-wrap"><span id="search-palette-icon" aria-hidden="true">&#128269;</span><input id="search-palette-input" type="text" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" placeholder="Search messages across all channels…" /><span id="search-palette-status"></span></div><div id="search-palette-results" role="listbox"></div><div id="search-palette-footer"><span class="sp-hint"><kbd>↑</kbd><kbd>↓</kbd> navigate</span><span class="sp-hint"><kbd>Enter</kbd> open thread</span><span class="sp-hint"><kbd>Esc</kbd> close</span></div></div>';
      document.body.appendChild(_overlay);
      _input = document.getElementById("search-palette-input");
      _results = document.getElementById("search-palette-results");
      _status = document.getElementById("search-palette-status");
      _overlay.addEventListener("mousedown", function(e) {
        if (e.target === _overlay) closePalette();
      });
      _input.addEventListener("input", function() {
        clearTimeout(_debounceTimer);
        _debounceTimer = setTimeout(runSearch, 150);
      });
      _input.addEventListener("keydown", handleInputKey);
    }
    function openPalette() {
      buildDOM();
      _overlay.classList.add("sp-open");
      _input.value = "";
      _results.innerHTML = "";
      _status.textContent = "";
      _selectedIdx = -1;
      _input.focus();
      fetchMessages();
    }
    function closePalette() {
      if (!_overlay) return;
      _overlay.classList.remove("sp-open");
      _selectedIdx = -1;
    }
    function fetchMessages() {
      var now = Date.now();
      if (_loading || now - _cacheTs < _CACHE_TTL && _cache.length > 0) return;
      _loading = true;
      setStatus("Loading…");
      var url;
      if (typeof apiUrl === "function") {
        url = apiUrl("/api/messages/?limit=200");
      } else {
        url = "/api/messages/?limit=200";
      }
      fetch(url, { credentials: "same-origin" }).then(function(res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      }).then(function(data) {
        _cache = data;
        _cacheTs = Date.now();
        _loading = false;
        setStatus("");
        if (_input && _input.value.trim()) runSearch();
      }).catch(function(err) {
        _loading = false;
        setStatus("Failed to load");
        console.warn("[search-palette] fetch error:", err);
      });
    }
    function setStatus(msg) {
      if (_status) _status.textContent = msg;
    }
    function runSearch() {
      var raw = _input ? _input.value.trim() : "";
      if (!raw) {
        _results.innerHTML = "";
        _selectedIdx = -1;
        return;
      }
      var words = raw.split(/\s+/).filter(Boolean).map(function(w) {
        return w.toLowerCase();
      });
      var hits = _cache.filter(function(msg) {
        var haystack = (msg.sender || "") + " " + (msg.channel || "") + " " + (msg.content || "");
        return words.every(function(w) {
          return fm(w, haystack);
        });
      });
      renderResults(hits.slice(0, 50), words);
    }
    function highlight(text, words) {
      var safe = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      words.forEach(function(w) {
        var lower = safe.toLowerCase();
        var wl = w.toLowerCase();
        var out = "";
        var pos = 0;
        var idx;
        while ((idx = lower.indexOf(wl, pos)) !== -1) {
          out += safe.slice(pos, idx) + "<mark>" + safe.slice(idx, idx + w.length) + "</mark>";
          pos = idx + w.length;
        }
        out += safe.slice(pos);
        safe = out;
      });
      return safe;
    }
    function formatTs(isoStr) {
      try {
        var d = new Date(isoStr);
        var now = /* @__PURE__ */ new Date();
        var diff = now - d;
        if (diff < 6e4) return "just now";
        if (diff < 36e5) return Math.floor(diff / 6e4) + "m ago";
        if (diff < 864e5) return Math.floor(diff / 36e5) + "h ago";
        return d.toLocaleDateString(void 0, { month: "short", day: "numeric" });
      } catch (_) {
        return "";
      }
    }
    function renderResults(hits, words) {
      _selectedIdx = -1;
      if (hits.length === 0) {
        _results.innerHTML = '<div class="sp-empty">No messages found</div>';
        return;
      }
      var html = hits.map(function(msg, i) {
        var snippet = (msg.content || "").replace(/\s+/g, " ").trim();
        if (snippet.length > 200) snippet = snippet.slice(0, 200) + "…";
        return '<div class="sp-result" role="option" data-msg-id="' + escapeAttr(String(msg.id)) + '" data-idx="' + i + '"><div class="sp-result-meta"><span class="sp-result-channel">' + escapeHtml2(msg.channel || "") + '</span><span class="sp-result-sender">' + escapeHtml2(msg.sender || "") + '</span><span class="sp-result-ts">' + formatTs(msg.ts) + '</span></div><div class="sp-result-snippet">' + highlight(snippet, words) + "</div></div>";
      }).join("");
      _results.innerHTML = html;
      _results.querySelectorAll(".sp-result").forEach(function(el) {
        el.addEventListener("mousedown", function(e) {
          e.preventDefault();
          activateResult(el);
        });
      });
    }
    function handleInputKey(e) {
      var items = _results.querySelectorAll(".sp-result");
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelected(Math.min(_selectedIdx + 1, items.length - 1), items);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelected(Math.max(_selectedIdx - 1, 0), items);
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (_selectedIdx >= 0 && items[_selectedIdx]) {
          activateResult(items[_selectedIdx]);
        } else if (items.length > 0) {
          activateResult(items[0]);
        }
      } else if (e.key === "Escape") {
        closePalette();
      }
    }
    function setSelected(idx, items) {
      items.forEach(function(el) {
        el.classList.remove("sp-selected");
      });
      _selectedIdx = idx;
      if (idx >= 0 && items[idx]) {
        items[idx].classList.add("sp-selected");
        items[idx].scrollIntoView({ block: "nearest" });
      }
    }
    function activateResult(el) {
      var msgId = el.getAttribute("data-msg-id");
      closePalette();
      if (!msgId) return;
      if (typeof jumpToMsg === "function") {
        jumpToMsg(msgId);
      } else if (typeof openThreadForMessage === "function") {
        openThreadForMessage(msgId);
      }
    }
    function escapeHtml2(s) {
      return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }
    function escapeAttr(s) {
      return String(s).replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    }
    document.addEventListener("keydown", function(e) {
      var isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
      var trigger = isMac ? e.metaKey && e.key === "k" : e.ctrlKey && e.key === "k";
      if (!trigger) return;
      var tag = document.activeElement && document.activeElement.tagName;
      var isEditable = (tag === "INPUT" || tag === "TEXTAREA" || document.activeElement.isContentEditable) && document.activeElement.id !== "search-palette-input";
      if (isEditable) return;
      e.preventDefault();
      if (_overlay && _overlay.classList.contains("sp-open")) {
        closePalette();
      } else {
        openPalette();
      }
    });
    window.openSearchPalette = openPalette;
    window.closeSearchPalette = closePalette;
  })();
  (function() {
    function init() {
      var feed = document.getElementById("messages");
      var btnTop = document.getElementById("feed-scroll-top");
      var btnBottom = document.getElementById("feed-scroll-bottom");
      if (!feed || !btnTop || !btnBottom) return;
      function update() {
        var st = feed.scrollTop;
        var max = feed.scrollHeight - feed.clientHeight;
        btnTop.classList.toggle("visible", st > 80);
        btnBottom.classList.toggle("visible", max - st > 80);
      }
      feed.addEventListener("scroll", update, { passive: true });
      new MutationObserver(update).observe(feed, { childList: true, subtree: false });
      update();
      btnTop.addEventListener("click", function() {
        feed.scrollTo({ top: 0, behavior: "smooth" });
      });
      btnBottom.addEventListener("click", function() {
        feed.scrollTo({ top: feed.scrollHeight, behavior: "smooth" });
      });
    }
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", init);
    } else {
      init();
    }
  })();
  (function() {
    var _focused = null;
    function _getAllMsgs() {
      return Array.from(document.querySelectorAll("#messages .msg"));
    }
    function _focusMsg(el) {
      if (!el) return;
      if (_focused) {
        _focused.classList.remove("msg-nav-focused");
        _focused.removeAttribute("tabindex");
      }
      _focused = el;
      el.classList.add("msg-nav-focused");
      el.setAttribute("tabindex", "-1");
      el.scrollIntoView({ block: "nearest", behavior: "smooth" });
      _showNavHint(el);
    }
    function _clearFocus() {
      if (_focused) {
        _focused.classList.remove("msg-nav-focused");
        _focused.removeAttribute("tabindex");
        _focused = null;
      }
      _hideNavHint();
      var inp = document.getElementById("msg-input");
      if (inp) inp.focus();
    }
    var _hint = null;
    function _showNavHint(el) {
      if (!_hint) {
        _hint = document.createElement("div");
        _hint.id = "feed-nav-hint";
        _hint.className = "feed-nav-hint";
        document.body.appendChild(_hint);
      }
      el.getAttribute("data-msg-id");
      _hint.innerHTML = '<span class="fnh-keys">↑↓</span> navigate &nbsp;·&nbsp;<span class="fnh-keys">Enter</span> reply &nbsp;·&nbsp;<span class="fnh-keys">E</span> react &nbsp;·&nbsp;<span class="fnh-keys">Esc</span> back to input';
      _hint.style.display = "flex";
    }
    function _hideNavHint() {
      if (_hint) _hint.style.display = "none";
    }
    document.addEventListener("DOMContentLoaded", function() {
      var inp = document.getElementById("msg-input");
      if (!inp) return;
      inp.addEventListener("keydown", function(e) {
        if (e.key === "ArrowUp" && inp.value === "") {
          e.preventDefault();
          var msgs = _getAllMsgs();
          if (msgs.length > 0) _focusMsg(msgs[msgs.length - 1]);
        }
      });
    });
    document.addEventListener("click", function(e) {
      var msg = e.target.closest && e.target.closest("#messages .msg");
      if (!msg) return;
      if (e.target.closest(".msg-actions, .msg-thread-btn, .reply-btn, .emoji-btn, .ch-star, .reaction-btn, .msg-footer")) return;
      _focusMsg(msg);
    });
    document.addEventListener("keydown", function(e) {
      if (!_focused) return;
      if (e.isComposing) return;
      if (e.key === "Escape") {
        e.preventDefault();
        _clearFocus();
        return;
      }
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        var msgs = _getAllMsgs();
        var idx = msgs.indexOf(_focused);
        var next = e.key === "ArrowDown" ? msgs[idx + 1] : msgs[idx - 1];
        if (next) {
          _focusMsg(next);
        } else if (e.key === "ArrowDown") {
          _clearFocus();
        }
        return;
      }
      if (e.key === "Enter" || e.key === "r" || e.key === "R") {
        if (e.altKey || e.ctrlKey || e.metaKey) return;
        e.preventDefault();
        var msgId = _focused.getAttribute("data-msg-id");
        if (msgId) {
          if (typeof window.openThreadForMessage === "function") {
            window.openThreadForMessage(parseInt(msgId, 10));
          } else if (typeof window.openReplyPanel === "function") {
            window.openReplyPanel(parseInt(msgId, 10));
          } else {
            var replyBtn = _focused.querySelector('.msg-thread-btn, .reply-btn, .action-reply, [data-action="reply"]');
            if (replyBtn) replyBtn.click();
          }
        }
        _clearFocus();
        return;
      }
      if (e.key === "e" || e.key === "E") {
        e.preventDefault();
        var emojiBtn = _focused.querySelector('.emoji-btn, .action-react, [data-action="react"], .msg-emoji-btn');
        if (emojiBtn) emojiBtn.click();
        return;
      }
    });
    document.addEventListener("mousedown", function(e) {
      if (!_focused) return;
      var feed = document.getElementById("messages");
      if (feed && !feed.contains(e.target)) _clearFocus();
    });
  })();
})();
//# sourceMappingURL=orochi-DeCs6OVi.js.map
