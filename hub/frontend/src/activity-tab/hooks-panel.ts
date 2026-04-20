// @ts-nocheck
// Migrated classic-script file. Types intentionally loose during
// the big-bang JS-to-TS bundle migration. Narrow later, per-file.
/* activity-tab/hooks-panel.js — hook-event panels (recent tools,
 * prompts, Agent calls, background tasks, tool counts). */


/* Render the hook-event panels (recent tools, prompts, Agent calls,
 * background tasks, tool-use counts). All inputs are arrays/objects from
 * the /api/agents/<name>/detail/ endpoint; empty inputs collapse the
 * whole section to an empty string so nothing renders when hooks aren't
 * wired up for this agent. */
function _renderHookPanels(
  recentTools,
  recentPrompts,
  agentCalls,
  backgroundTasks,
  toolCounts,
) {
  var hasAny =
    (recentTools && recentTools.length) ||
    (recentPrompts && recentPrompts.length) ||
    (agentCalls && agentCalls.length) ||
    (backgroundTasks && backgroundTasks.length) ||
    (toolCounts && Object.keys(toolCounts).length);
  if (!hasAny) return "";
  function _hhmmss(ts) {
    if (!ts || ts.length < 19) return "";
    return ts.slice(11, 19);
  }
  function _list(items, keyFn, emptyLabel) {
    if (!items || !items.length)
      return '<li class="hook-empty">' + escapeHtml(emptyLabel) + "</li>";
    return items
      .slice()
      .reverse()
      .map(function (it) {
        var ts = _hhmmss(it.ts || "");
        var txt = keyFn(it);
        return (
          '<li class="hook-row">' +
          '<span class="hook-ts">' +
          escapeHtml(ts) +
          "</span>" +
          '<span class="hook-txt" title="' +
          escapeHtml(txt) +
          '">' +
          escapeHtml(txt) +
          "</span></li>"
        );
      })
      .join("");
  }
  var toolsHtml = _list(
    recentTools,
    function (it) {
      var name = it.tool || it.kind || "?";
      var prev = it.input_preview || "";
      return prev ? name + " — " + prev : name;
    },
    "no tool calls recorded",
  );
  var promptsHtml = _list(
    recentPrompts,
    function (it) {
      return it.prompt_preview || "";
    },
    "no prompts recorded",
  );
  var agentCallsHtml = _list(
    agentCalls,
    function (it) {
      return it.input_preview || "";
    },
    "no Agent tool calls recorded",
  );
  var bgHtml = _list(
    backgroundTasks,
    function (it) {
      return it.input_preview || "";
    },
    "no background tasks recorded",
  );
  var countsHtml = "";
  if (toolCounts && Object.keys(toolCounts).length) {
    var pairs = Object.keys(toolCounts)
      .map(function (k) {
        return [k, Number(toolCounts[k]) || 0];
      })
      .sort(function (a, b) {
        return b[1] - a[1];
      });
    countsHtml = pairs
      .map(function (p) {
        return (
          '<span class="hook-count-chip" title="' +
          escapeHtml(p[0]) +
          " used " +
          p[1] +
          ' times">' +
          escapeHtml(p[0]) +
          " ×" +
          p[1] +
          "</span>"
        );
      })
      .join("");
  }
  function _panel(title, bodyHtml, extraClass) {
    return (
      '<div class="hook-panel ' +
      (extraClass || "") +
      '">' +
      '<div class="hook-panel-title">' +
      escapeHtml(title) +
      "</div>" +
      bodyHtml +
      "</div>"
    );
  }
  var panels =
    _panel("Recent tools", '<ul class="hook-list">' + toolsHtml + "</ul>") +
    _panel("Recent prompts", '<ul class="hook-list">' + promptsHtml + "</ul>") +
    _panel("Agent calls", '<ul class="hook-list">' + agentCallsHtml + "</ul>") +
    _panel(
      "Background tasks (" +
        (backgroundTasks ? backgroundTasks.length : 0) +
        ")",
      '<ul class="hook-list">' + bgHtml + "</ul>",
    ) +
    (countsHtml
      ? _panel(
          "Tool use counts",
          '<div class="hook-counts">' + countsHtml + "</div>",
          "hook-panel-wide",
        )
      : "");
  return '<div class="agent-detail-section hook-panels">' + panels + "</div>";
}


