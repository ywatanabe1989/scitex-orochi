/* Machines tab — orochi-cron status panel (classic-script mirror).
 *
 * Hand-maintained companion to hub/frontend/src/resources-tab/cron-panel.ts.
 * Phase 2 of the Orochi unified cron (lead msg#16406 / msg#16408):
 * fetches /api/cron/ and renders a collapsible cron-jobs subsection
 * under each Machines-tab host card.
 *
 * Keep this in sync with the TS source (same load-order conventions as
 * panel.js / tab.js). See docstring in cron-panel.ts for the render
 * rules and invariants.
 */
/* globals: apiUrl, escapeHtml */

var cronByHost = {};

var _CRON_COLLAPSE_KEY = "orochi.cronCollapse";
var _cronCollapse = (function _loadCollapse() {
  try {
    var raw = localStorage.getItem(_CRON_COLLAPSE_KEY);
    if (!raw) return {};
    var parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (_e) {
    return {};
  }
})();

function _persistCronCollapse() {
  try {
    localStorage.setItem(_CRON_COLLAPSE_KEY, JSON.stringify(_cronCollapse));
  } catch (_e) {
    /* ignore quota / private-mode errors */
  }
}

function isCronPanelCollapsed(host) {
  var stored = _cronCollapse[host];
  if (stored === undefined) return true;
  return !!stored;
}

function toggleCronPanel(host) {
  _cronCollapse[host] = !isCronPanelCollapsed(host);
  _persistCronCollapse();
}

function formatCronRelative(epochSeconds, now) {
  if (!epochSeconds) return "\u2014";
  var nowSec = typeof now === "number" ? now : Date.now() / 1000;
  var delta = Math.round(nowSec - epochSeconds);
  var absDelta = Math.abs(delta);
  var suffix = delta >= 0 ? " ago" : "";
  var prefix = delta < 0 ? "in " : "";
  if (absDelta < 5) return "now";
  if (absDelta < 60) return prefix + absDelta + "s" + suffix;
  if (absDelta < 3600) return prefix + Math.round(absDelta / 60) + "m" + suffix;
  if (absDelta < 86400) return prefix + Math.round(absDelta / 3600) + "h" + suffix;
  return prefix + Math.round(absDelta / 86400) + "d" + suffix;
}

function cronStatusGlyph(job) {
  if (job.disabled) return { glyph: "\u23F8", cls: "cron-row-disabled", label: "disabled" };
  if (job.last_run === null || job.last_run === undefined || job.last_run === 0) {
    return { glyph: "\u23F8", cls: "cron-row-pending", label: "not yet run" };
  }
  var exit = job.last_exit;
  if (exit === null || exit === undefined) {
    return { glyph: "\u23F8", cls: "cron-row-pending", label: "pending" };
  }
  if (exit === 0) return { glyph: "\u2705", cls: "cron-row-ok", label: "ok" };
  return { glyph: "\u26A0\uFE0F", cls: "cron-row-warn", label: "exit=" + exit };
}

function renderCronJobRow(job, now) {
  var st = cronStatusGlyph(job);
  var nameHtml = escapeHtml(job.name || "");
  var lastText = formatCronRelative(job.last_run == null ? null : job.last_run, now);
  var nextText = formatCronRelative(job.next_run == null ? null : job.next_run, now);
  var tipParts = [nameHtml];
  if (job.command) tipParts.push("$ " + job.command);
  if (typeof job.interval === "number" && job.interval > 0) {
    tipParts.push("every " + job.interval + "s");
  }
  if (typeof job.last_duration_seconds === "number" && job.last_duration_seconds > 0) {
    tipParts.push("last took " + job.last_duration_seconds.toFixed(1) + "s");
  }
  if (job.last_skipped) tipParts.push("skipped: " + job.last_skipped);
  if (job.stderr_tail) tipParts.push("stderr: " + job.stderr_tail);
  else if (job.stdout_tail) tipParts.push("stdout: " + job.stdout_tail);
  var tip = tipParts.join("\n");
  return (
    '<div class="cron-row ' + st.cls + '" title="' + escapeHtml(tip) + '">' +
    '<span class="cron-glyph" aria-label="' + escapeHtml(st.label) + '">' +
    st.glyph +
    "</span>" +
    '<span class="cron-name">' + nameHtml + "</span>" +
    '<span class="cron-last">' + escapeHtml(lastText) + "</span>" +
    '<span class="cron-arrow" aria-hidden="true">\u2192</span>' +
    '<span class="cron-next">next ' + escapeHtml(nextText) + "</span>" +
    "</div>"
  );
}

function renderCronJobsHtml(host, now) {
  var payload = cronByHost[host];
  if (!payload) return "";
  var jobs = payload.jobs || [];
  if (jobs.length === 0 && !payload.stale) return "";
  var collapsed = isCronPanelCollapsed(host);
  var chevron = collapsed ? "\u25B6" : "\u25BC";
  var staleBadge = payload.stale
    ? ' <span class="cron-stale" title="Heartbeat is stale (>10 min old)">stale</span>'
    : "";
  var bodyHtml = "";
  if (!collapsed) {
    if (jobs.length === 0) {
      bodyHtml =
        '<div class="cron-rows cron-rows-empty">No cron jobs reported</div>';
    } else {
      bodyHtml =
        '<div class="cron-rows">' +
        jobs
          .map(function (j) {
            return renderCronJobRow(j, now);
          })
          .join("") +
        "</div>";
    }
  }
  return (
    '<div class="cron-panel" data-cron-host="' + escapeHtml(host) + '">' +
    '<div class="cron-header" data-cron-toggle="' +
    escapeHtml(host) +
    '" role="button" tabindex="0">' +
    '<span class="cron-chevron">' + chevron + "</span>" +
    '<span class="cron-title">Cron jobs (' + jobs.length + ")</span>" +
    staleBadge +
    "</div>" +
    bodyHtml +
    "</div>"
  );
}

function wireCronToggles(root, onChange) {
  if (!root) return;
  root.querySelectorAll(".cron-header[data-cron-toggle]").forEach(function (el) {
    el.addEventListener("click", function (ev) {
      ev.stopPropagation();
      var host = el.getAttribute("data-cron-toggle") || "";
      if (!host) return;
      toggleCronPanel(host);
      onChange();
    });
    el.addEventListener("keydown", function (ev) {
      var key = ev.key;
      if (key !== "Enter" && key !== " ") return;
      ev.preventDefault();
      ev.stopPropagation();
      var host = el.getAttribute("data-cron-toggle") || "";
      if (!host) return;
      toggleCronPanel(host);
      onChange();
    });
  });
}

async function fetchCronJobs() {
  try {
    var res = await fetch(apiUrl("/api/cron/"));
    if (!res.ok) return;
    var data = await res.json();
    var hosts = (data && data.hosts) || {};
    cronByHost = hosts;
  } catch (e) {
    console.warn("fetchCronJobs failed:", e);
  }
}
