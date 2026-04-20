// @ts-nocheck
// Migrated classic-script file. Types intentionally loose during
// the big-bang JS-to-TS bundle migration. Narrow later, per-file.
/* activity-tab/data.js — data fetch + refresh polling + channel-member
 * permission fetch. */

async function _fetchActivityDetail(name) {
  if (!name || name === "overview") return;
  if (_activityDetailInflight[name]) return;
  _activityDetailInflight[name] = true;
  try {
    var res = await fetch(
      apiUrl("/api/agents/" + encodeURIComponent(name) + "/detail/"),
    );
    if (!res.ok) return;
    _activityDetailCache[name] = await res.json();
    if (_overviewExpanded === name) {
      var inlineBox = document.querySelector(
        '.activity-inline-detail[data-detail-for="' +
          String(name).replace(/"/g, '\\"') +
          '"]',
      );
      var agent = (window.__lastAgents || []).find(function (a) {
        return a.name === name;
      });
      if (inlineBox && agent) _renderActivityAgentDetail(agent, inlineBox);
    }
  } catch (_e) {
    /* ignore; registry fallback still renders */
  } finally {
    _activityDetailInflight[name] = false;
  }
}


async function _activityChannelRequest(method, agent, channel) {
  var body = { channel: channel, username: "agent-" + agent };
  if (method === "POST" || method === "PATCH") body.permission = "read-write";
  var m = document.cookie.match(/csrftoken=([^;]+)/);
  var res = await fetch(apiUrl("/api/channel-members/"), {
    method: method,
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": m ? decodeURIComponent(m[1]) : "",
    },
    credentials: "same-origin",
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    var txt = await res.text().catch(function () {
      return "";
    });
    throw new Error(res.status + ": " + txt.slice(0, 200));
  }
  /* Any membership mutation invalidates the topology arrow cache so
   * next render re-fetches per-channel permissions. */
  if (typeof _invalidateTopoPerms === "function") _invalidateTopoPerms();
  return res.json();
}

function _invalidateTopoPerms() {
  _topoChannelPerms = Object.create(null);
  _topoChannelPermsFetchedAt = 0;
}
window._invalidateTopoPerms = _invalidateTopoPerms;


function _permKey(channel, agentName) {
  return channel + "::" + agentName;
}

/* Fetch membership+permission for one channel and fold the result into
 * _topoChannelPerms. Silent on failure — the caller treats missing
 * entries as read-write. */
async function _fetchTopoPermsForChannel(channel) {
  if (_topoChannelPermsInflight[channel]) return;
  _topoChannelPermsInflight[channel] = true;
  try {
    var res = await fetch(
      apiUrl("/api/channel-members/?channel=" + encodeURIComponent(channel)),
      { credentials: "same-origin" },
    );
    if (!res.ok) return;
    var rows = await res.json();
    if (!Array.isArray(rows)) return;
    rows.forEach(function (row) {
      if (!row || !row.username) return;
      /* Backend usernames for agents are "agent-<name>"; the topology
       * renderer keys on bare agent names. Strip the prefix so the
       * cache lookup matches either form. */
      var uname = String(row.username);
      var bare = uname.indexOf("agent-") === 0 ? uname.slice(6) : uname;
      var perm = row.permission || "read-write";
      _topoChannelPerms[_permKey(channel, bare)] = perm;
      _topoChannelPerms[_permKey(channel, uname)] = perm;
    });
  } catch (_e) {
    /* ignore — fall back to read-write default on missing entries */
  } finally {
    _topoChannelPermsInflight[channel] = false;
    /* Trigger a lightweight repaint so arrows appear once data lands.
     * We don't want to rebuild the whole SVG (would thrash zoom); just
     * re-decorate the existing lines. */
    if (typeof _repaintTopoArrows === "function") _repaintTopoArrows();
  }
}

/* Kick off one fetch per visible channel if the cache is cold or
 * expired. Non-blocking: arrows render with defaults first, then
 * upgrade once each fetch resolves. */
function _refreshTopoPerms(channels) {
  var now = Date.now();
  if (now - _topoChannelPermsFetchedAt < TOPO_PERMS_TTL_MS) return;
  _topoChannelPermsFetchedAt = now;
  channels.forEach(function (c) {
    _fetchTopoPermsForChannel(c);
  });
}


async function refreshActivityFromApi() {
  try {
    var res = await fetch(apiUrl("/api/agents"), {
      credentials: "same-origin",
    });
    if (!res.ok) return;
    window.__lastAgents = await res.json();
    renderActivityTab();
  } catch (e) {
    /* ignore */
  }
}

function startActivityAutoRefresh() {
  if (activityRefreshTimer) return;
  /* 30s instead of 10s — ywatanabe at msg#6575 said the tab was
   * "ちかちかしすぎ". 30 s is still fast enough to feel live but
   * cuts the visual churn down to 1/3. */
  activityRefreshTimer = setInterval(refreshActivityFromApi, 30000);
}

function stopActivityAutoRefresh() {
  if (activityRefreshTimer) {
    clearInterval(activityRefreshTimer);
    activityRefreshTimer = null;
  }
}

