// @ts-nocheck
/* Machines tab — orochi-cron status panel.
 *
 * Phase 2 of the Orochi unified cron (lead msg#16406 / msg#16408). The
 * hub aggregates per-host cron_jobs out of heartbeat payloads and
 * serves them at GET /api/cron/. This module fetches that data, keeps
 * a module-level {host -> {jobs, stale, last_heartbeat_at, agent}}
 * map, and renders a collapsible cron-jobs subsection under each
 * Machines-tab host card.
 *
 * No auto-refresh — the Machines-tab refresh cycle (30s polling via
 * init.ts + the /api/resources path already piggybacks on the same
 * heartbeat) picks up fresh cron data. Keeping the panel read-only
 * and poll-less means it stays cheap to render and doesn't compete
 * with the chat WS for bandwidth.
 *
 * Render rules (match ywatanabe's spec in the task brief):
 *   - Status glyph:
 *       ok       last_exit === 0
 *       warn     last_exit !== 0 (and !== null)
 *       pending  no last_run yet (job just registered, never run)
 *   - Row: <icon> <name> <last-run-relative> → next <next-run-relative>
 *   - Header shows job count and collapse/expand chevron.
 *   - Whole panel is collapsed by default; localStorage per-host.
 *   - Tooltip (title=) on each row carries the full stdout/stderr
 *     tail (when present in the jobs dict) so operators can spot a
 *     failing cron without leaving the tab.
 */

import { apiUrl, escapeHtml } from "../app/utils";

export interface CronJob {
  name: string;
  interval?: number;
  last_run?: number | null;
  last_exit?: number | null;
  last_skipped?: string | null;
  last_duration_seconds?: number | null;
  next_run?: number | null;
  running?: boolean;
  disabled?: boolean;
  command?: string;
  timeout?: number;
  // Optional NDJSON tails — emitted by future cron daemon upgrades.
  stdout_tail?: string;
  stderr_tail?: string;
}

export interface CronHost {
  agent: string;
  last_heartbeat_at: string | null;
  stale: boolean;
  jobs: CronJob[];
}

/* Module-level cache: host label -> payload. Populated by fetchCronJobs
 * and read by renderCronJobsHtml during renderResourcesTab. */
export var cronByHost: Record<string, CronHost> = {};

/* Per-host collapsed-state, persisted so operators who always keep
 * the mba panel open don't have to re-click on every tab refresh. */
var _CRON_COLLAPSE_KEY = "orochi.cronCollapse";
var _cronCollapse: Record<string, boolean> = (function _loadCollapse() {
  try {
    var raw = localStorage.getItem(_CRON_COLLAPSE_KEY);
    if (!raw) return {};
    var parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (_e) {
    return {};
  }
})();

function _persistCollapse() {
  try {
    localStorage.setItem(_CRON_COLLAPSE_KEY, JSON.stringify(_cronCollapse));
  } catch (_e) {
    /* ignore quota / private-mode errors */
  }
}

export function isCronPanelCollapsed(host: string): boolean {
  /* Default = collapsed (true) per spec. Stored value overrides default. */
  var stored = _cronCollapse[host];
  if (stored === undefined) return true;
  return !!stored;
}

export function toggleCronPanel(host: string): void {
  _cronCollapse[host] = !isCronPanelCollapsed(host);
  _persistCollapse();
}

/* Relative time formatting — "2m ago", "1h ago", "now". Compact so
 * the row renders on one line under the donut grid. */
export function formatRelative(epochSeconds: number | null | undefined, now?: number): string {
  if (!epochSeconds) return "—";
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

export function statusGlyph(job: CronJob): { glyph: string; cls: string; label: string } {
  if (job.disabled) return { glyph: "⏸", cls: "cron-row-disabled", label: "disabled" };
  if (job.last_run === null || job.last_run === undefined || job.last_run === 0) {
    return { glyph: "⏸", cls: "cron-row-pending", label: "not yet run" };
  }
  var exit = job.last_exit;
  if (exit === null || exit === undefined) {
    /* Running right now (not finished), or state file wrote orochi_started_at
     * before ended_at — treat as pending. */
    return { glyph: "⏸", cls: "cron-row-pending", label: "pending" };
  }
  if (exit === 0) return { glyph: "✅", cls: "cron-row-ok", label: "ok" };
  return { glyph: "⚠️", cls: "cron-row-warn", label: "exit=" + exit };
}

/* One-row renderer — kept pure so the frontend unit test (if the repo
 * grows a harness) can exercise it without a DOM. */
export function renderCronJobRow(job: CronJob, now?: number): string {
  var st = statusGlyph(job);
  var nameHtml = escapeHtml(job.name || "");
  var lastText = formatRelative(job.last_run ?? null, now);
  var nextText = formatRelative(job.next_run ?? null, now);
  /* Tooltip — carry the tail outputs if the daemon state file included
   * them. Daemons that don't emit these keep the tooltip minimal. */
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
    '<span class="cron-arrow" aria-hidden="true">→</span>' +
    '<span class="cron-next">next ' + escapeHtml(nextText) + "</span>" +
    "</div>"
  );
}

/* Whole-panel renderer. Emits the collapsible header + row list,
 * with a data-host attribute so the click handler (wired by the
 * Machines tab after the card grid paints) can flip collapse state
 * without a full refetch.
 *
 * Emits an empty string when the host has no cron row in the
 * aggregator — callers inline this, so "no data" degrades gracefully
 * to no panel at all (the Machines card doesn't get a dangling
 * "Cron jobs (0)" header). */
export function renderCronJobsHtml(host: string, now?: number): string {
  var payload = cronByHost[host];
  if (!payload) return "";
  var jobs = payload.jobs || [];
  if (jobs.length === 0 && !payload.stale) return "";
  var collapsed = isCronPanelCollapsed(host);
  var chevron = collapsed ? "▶" : "▼";
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
        jobs.map(function (j) { return renderCronJobRow(j, now); }).join("") +
        "</div>";
    }
  }
  return (
    '<div class="cron-panel" data-cron-host="' + escapeHtml(host) + '">' +
    '<div class="cron-header" data-cron-toggle="' + escapeHtml(host) + '" role="button" tabindex="0">' +
    '<span class="cron-chevron">' + chevron + "</span>" +
    '<span class="cron-title">Cron jobs (' + jobs.length + ")</span>" +
    staleBadge +
    "</div>" +
    bodyHtml +
    "</div>"
  );
}

/* Click handler attached to a card grid after render — delegates so we
 * don't spawn per-row listeners. */
export function wireCronToggles(root: Element | null, onChange: () => void): void {
  if (!root) return;
  root.querySelectorAll(".cron-header[data-cron-toggle]").forEach(function (el) {
    (el as HTMLElement).addEventListener("click", function (ev) {
      ev.stopPropagation(); /* don't trigger the card-wide addTag click */
      var host = (el as HTMLElement).getAttribute("data-cron-toggle") || "";
      if (!host) return;
      toggleCronPanel(host);
      onChange();
    });
    /* Keyboard parity — space / enter toggles, same as a <button>. */
    (el as HTMLElement).addEventListener("keydown", function (ev) {
      var key = (ev as KeyboardEvent).key;
      if (key !== "Enter" && key !== " ") return;
      ev.preventDefault();
      ev.stopPropagation();
      var host = (el as HTMLElement).getAttribute("data-cron-toggle") || "";
      if (!host) return;
      toggleCronPanel(host);
      onChange();
    });
  });
}

/* Fetch /api/cron/ and refresh the module cache. Silent on transport
 * failure — the existing Machines tab already shows a stale indicator
 * via the resource card's LED, so a missing cron panel is redundant
 * noise. */
export async function fetchCronJobs(): Promise<void> {
  try {
    var res = await fetch(apiUrl("/api/cron/"));
    if (!res.ok) return;
    var data = await res.json();
    var hosts = (data && data.hosts) || {};
    /* Replace wholesale — the aggregator already collapses duplicates. */
    cronByHost = hosts;
  } catch (e) {
    console.warn("fetchCronJobs failed:", e);
  }
}
