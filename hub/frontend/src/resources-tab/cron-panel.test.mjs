/* resources-tab/cron-panel.test.mjs — standalone Node smoke-test for
 * the Machines-tab cron panel renderer. No vitest/jest in this repo;
 * run with:
 *     node hub/frontend/src/resources-tab/cron-panel.test.mjs
 * Exits non-zero on failure.
 *
 * Covers the pure (DOM-less) render helpers exported by the classic-
 * script mirror at hub/static/hub/resources-tab/cron-panel.js. Any
 * divergence between the TS source and the JS mirror shows up here.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

const __dirname = dirname(fileURLToPath(import.meta.url));
const MIRROR = resolve(
  __dirname,
  "../../../static/hub/resources-tab/cron-panel.js",
);

let failed = 0;
let passed = 0;
function assert(cond, label) {
  if (cond) {
    passed += 1;
    console.log("PASS " + label);
  } else {
    failed += 1;
    console.error("FAIL " + label);
  }
}

function makeLocalStorage() {
  const store = new Map();
  return {
    getItem(k) {
      return store.has(k) ? store.get(k) : null;
    },
    setItem(k, v) {
      store.set(String(k), String(v));
    },
    removeItem(k) {
      store.delete(k);
    },
    clear() {
      store.clear();
    },
    _raw: store,
  };
}

function loadModule() {
  const code = readFileSync(MIRROR, "utf8");
  const ctx = {
    /* Stub globals the mirror expects. ``escapeHtml`` is a classic
     * util; we supply a minimal identity wrapper that does the basic
     * char replacements the production helper does. */
    apiUrl: (p) => p,
    escapeHtml: (s) =>
      String(s || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;"),
    localStorage: makeLocalStorage(),
    Date,
    JSON,
    Object,
    String,
    Number,
    Array,
    Math,
    console,
    fetch: async () => ({ ok: false }),
  };
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  return ctx;
}

/* ──── Test 1: statusGlyph distinguishes ok / warn / pending / disabled ──── */
{
  const m = loadModule();
  const { cronStatusGlyph } = m;
  const ok = cronStatusGlyph({ last_run: 100, last_exit: 0 });
  assert(ok.cls === "cron-row-ok", "last_exit=0 → cron-row-ok");
  const warn = cronStatusGlyph({ last_run: 100, last_exit: 1 });
  assert(warn.cls === "cron-row-warn", "last_exit=1 → cron-row-warn");
  assert(warn.label === "exit=1", "warn label carries exit code");
  const pending = cronStatusGlyph({ last_run: 0, last_exit: null });
  assert(pending.cls === "cron-row-pending", "no last_run → pending");
  const disabled = cronStatusGlyph({ disabled: true, last_exit: 0 });
  assert(disabled.cls === "cron-row-disabled", "disabled flag → row-disabled");
}

/* ──── Test 2: formatRelative renders seconds / minutes / hours ──── */
{
  const m = loadModule();
  const { formatCronRelative } = m;
  const now = 1_000_000;
  assert(formatCronRelative(now, now) === "now", "delta<5s → now");
  assert(formatCronRelative(now - 30, now) === "30s ago", "seconds-ago");
  assert(formatCronRelative(now - 120, now) === "2m ago", "minutes-ago");
  assert(formatCronRelative(now - 3600, now) === "1h ago", "hours-ago");
  assert(
    formatCronRelative(now + 60, now) === "in 1m",
    "future delta → in-N prefix",
  );
  assert(formatCronRelative(null, now) === "\u2014", "null → em-dash");
}

/* ──── Test 3: renderCronJobRow emits expected markup ──── */
{
  const m = loadModule();
  const { renderCronJobRow } = m;
  const now = 1_000_000;
  const job = {
    name: "machine-heartbeat",
    last_run: now - 120,
    last_exit: 0,
    next_run: now + 60,
    interval: 180,
    command: "echo hi",
  };
  const html = renderCronJobRow(job, now);
  assert(html.includes('class="cron-row cron-row-ok'), "row carries ok class");
  assert(html.includes("machine-heartbeat"), "row includes job name");
  assert(html.includes("2m ago"), "row renders last_run relative time");
  assert(html.includes("next in 1m"), "row renders next_run relative time");
  assert(
    html.includes("every 180s"),
    "tooltip includes interval summary",
  );
  assert(
    html.includes("$ echo hi"),
    "tooltip includes command line",
  );
}

/* ──── Test 4: renderCronJobsHtml gates on collapse state ──── */
{
  const m = loadModule();
  const host = "mba";
  m.cronByHost[host] = {
    agent: "head-mba",
    last_heartbeat_at: null,
    stale: false,
    jobs: [{ name: "a", last_run: 100, last_exit: 0, next_run: 200 }],
  };
  const collapsed = m.renderCronJobsHtml(host, 100);
  assert(
    collapsed.includes("Cron jobs (1)"),
    "collapsed panel shows header + count",
  );
  assert(
    !collapsed.includes("cron-rows"),
    "collapsed panel omits the rows body",
  );
  /* Flip collapse via the exported toggle helper and re-render. */
  m.toggleCronPanel(host);
  const open = m.renderCronJobsHtml(host, 100);
  assert(
    open.includes('class="cron-rows"'),
    "open panel emits the rows body",
  );
  assert(open.includes('class="cron-row cron-row-ok'), "open panel renders each row");
}

/* ──── Test 5: stale host keeps the panel rendering ──── */
{
  const m = loadModule();
  const host = "nas";
  m.cronByHost[host] = {
    agent: "head-nas",
    last_heartbeat_at: null,
    stale: true,
    jobs: [],
  };
  const html = m.renderCronJobsHtml(host, 100);
  assert(html.includes('class="cron-panel"'), "stale empty host still renders panel");
  assert(html.includes("cron-stale"), "stale badge is present");
}

/* ──── Test 6: host without an entry gets empty string ──── */
{
  const m = loadModule();
  const html = m.renderCronJobsHtml("unknown-host", 100);
  assert(html === "", "unknown host → empty string (card stays unchanged)");
}

/* ──── Test 7: empty jobs + not stale → no panel at all ──── */
{
  const m = loadModule();
  m.cronByHost["bare"] = {
    agent: "bare",
    last_heartbeat_at: null,
    stale: false,
    jobs: [],
  };
  const html = m.renderCronJobsHtml("bare", 100);
  assert(
    html === "",
    "fresh host with 0 jobs → no panel (avoids dangling 'Cron jobs (0)')",
  );
}

/* ──── Test 8: collapse state persists via localStorage mirror ──── */
{
  const m = loadModule();
  const host = "spartan";
  /* Default = collapsed. */
  assert(m.isCronPanelCollapsed(host) === true, "collapse default = true");
  m.toggleCronPanel(host);
  assert(m.isCronPanelCollapsed(host) === false, "toggle flips collapse state");
  m.toggleCronPanel(host);
  assert(m.isCronPanelCollapsed(host) === true, "toggle flips back");
}

if (failed) {
  console.error(`\n${failed} test(s) failed (${passed} passed).`);
  process.exit(1);
}
console.log(`\nAll ${passed} test(s) passed.`);
