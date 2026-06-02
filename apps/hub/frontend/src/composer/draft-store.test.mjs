/* composer/draft-store.test.mjs — standalone Node smoke-test for the
 * draft-store module. There is no vitest/jest in this repo; run with:
 *     node hub/frontend/src/composer/draft-store.test.mjs
 * Exits non-zero on failure.
 *
 * Because draft-store.ts is TS with `// @ts-nocheck`, this test
 * re-implements the same contract against the JS mirror at
 * hub/static/hub/composer/draft-store.js — any divergence between the
 * two files is a bug we want the test to catch.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

const __dirname = dirname(fileURLToPath(import.meta.url));
const MIRROR = resolve(
  __dirname,
  "../../../static/hub/composer/draft-store.js",
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
    get length() {
      return store.size;
    },
    key(i) {
      return Array.from(store.keys())[i] ?? null;
    },
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

function makeThrowingLocalStorage() {
  return {
    get length() {
      return 0;
    },
    key() {
      throw new Error("private mode");
    },
    getItem() {
      throw new Error("private mode");
    },
    setItem() {
      throw new Error("quota");
    },
    removeItem() {
      throw new Error("private mode");
    },
  };
}

function loadModule(localStorageImpl) {
  const code = readFileSync(MIRROR, "utf8");
  const ctx = {
    window: {},
    localStorage: localStorageImpl,
    Date,
    JSON,
    Object,
    String,
    Number,
    isFinite,
    setTimeout,
    clearTimeout,
    console,
  };
  // Make window.* properties reflect the context globals.
  ctx.window.localStorage = localStorageImpl;
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  return ctx.window.orochiDraftStore;
}

/* ──── Test 1: save then load round-trip ──── */
{
  const ls = makeLocalStorage();
  const m = loadModule(ls);
  m.saveDraft("chat", "#proj-neurovista", "hello world");
  const got = m.loadDraft("chat", "#proj-neurovista");
  assert(got === "hello world", "round-trip save/load returns stored text");
  assert(
    ls._raw.has("orochi.draft.chat.#proj-neurovista"),
    "key format matches spec: orochi.draft.<surface>.<target>",
  );
}

/* ──── Test 2: load miss returns null ──── */
{
  const ls = makeLocalStorage();
  const m = loadModule(ls);
  assert(m.loadDraft("chat", "nope") === null, "load miss returns null");
}

/* ──── Test 3: clear removes the key ──── */
{
  const ls = makeLocalStorage();
  const m = loadModule(ls);
  m.saveDraft("chat", "#x", "keep");
  m.clearDraft("chat", "#x");
  assert(m.loadDraft("chat", "#x") === null, "clearDraft removes the entry");
}

/* ──── Test 4: stale (>24h) entries are not restored ──── */
{
  const ls = makeLocalStorage();
  const m = loadModule(ls);
  const stale = {
    text: "old news",
    savedAt: new Date(Date.now() - 25 * 60 * 60 * 1000).toISOString(),
  };
  ls.setItem("orochi.draft.chat.#stale", JSON.stringify(stale));
  assert(
    m.loadDraft("chat", "#stale") === null,
    "24h-old drafts are NOT restored",
  );
  assert(
    ls.getItem("orochi.draft.chat.#stale") === null,
    "loadDraft evicts stale entries it finds",
  );
}

/* ──── Test 5: fresh (<24h) draft IS restored ──── */
{
  const ls = makeLocalStorage();
  const m = loadModule(ls);
  const fresh = {
    text: "still typing",
    savedAt: new Date(Date.now() - 60 * 60 * 1000).toISOString(), // 1h ago
  };
  ls.setItem("orochi.draft.chat.#fresh", JSON.stringify(fresh));
  assert(
    m.loadDraft("chat", "#fresh") === "still typing",
    "drafts <24h old ARE restored",
  );
}

/* ──── Test 6: cleanupStaleDrafts sweeps the whole prefix ──── */
{
  const ls = makeLocalStorage();
  const m = loadModule(ls);
  const stale = {
    text: "old",
    savedAt: new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString(),
  };
  const fresh = {
    text: "new",
    savedAt: new Date().toISOString(),
  };
  ls.setItem("orochi.draft.chat.#a", JSON.stringify(stale));
  ls.setItem("orochi.draft.chat.#b", JSON.stringify(fresh));
  ls.setItem("orochi.draft.overview-popup.#c", JSON.stringify(stale));
  ls.setItem("unrelated_key", "leave me alone");
  m.cleanupStaleDrafts();
  assert(!ls._raw.has("orochi.draft.chat.#a"), "stale chat draft removed");
  assert(ls._raw.has("orochi.draft.chat.#b"), "fresh draft preserved");
  assert(
    !ls._raw.has("orochi.draft.overview-popup.#c"),
    "stale popup draft removed",
  );
  assert(ls._raw.has("unrelated_key"), "non-draft keys untouched");
}

/* ──── Test 7: save with empty text removes the key ──── */
{
  const ls = makeLocalStorage();
  const m = loadModule(ls);
  m.saveDraft("chat", "#x", "hi");
  m.saveDraft("chat", "#x", "");
  assert(
    m.loadDraft("chat", "#x") === null,
    "saving empty text clears the entry",
  );
}

/* ──── Test 8: private mode / quota — all ops no-throw ──── */
{
  const ls = makeThrowingLocalStorage();
  const m = loadModule(ls);
  let threw = false;
  try {
    m.saveDraft("chat", "#x", "hi");
    m.loadDraft("chat", "#x");
    m.clearDraft("chat", "#x");
    m.cleanupStaleDrafts();
  } catch (_) {
    threw = true;
  }
  assert(!threw, "storage failures are swallowed (private mode tolerant)");
}

/* ──── Test 9: corrupted JSON is evicted on load ──── */
{
  const ls = makeLocalStorage();
  const m = loadModule(ls);
  ls.setItem("orochi.draft.chat.#bad", "not json{{{");
  assert(m.loadDraft("chat", "#bad") === null, "corrupted JSON yields null");
  assert(
    !ls._raw.has("orochi.draft.chat.#bad"),
    "corrupted entry is evicted",
  );
}

/* ──── Test 10: empty target falls back to __default__ ──── */
{
  const ls = makeLocalStorage();
  const m = loadModule(ls);
  m.saveDraft("chat", "", "default-draft");
  assert(
    ls._raw.has("orochi.draft.chat.__default__"),
    "empty target → __default__ key",
  );
  m.saveDraft("chat", null, "also-default");
  assert(
    m.loadDraft("chat", null) === "also-default",
    "null target round-trips via __default__",
  );
}

/* ──── Test 11: key format is exactly "orochi.draft.<surface>.<target>" ──── */
{
  const ls = makeLocalStorage();
  const m = loadModule(ls);
  assert(
    m._draftKey("thread", "msg12345") === "orochi.draft.thread.msg12345",
    "thread key format matches spec",
  );
  assert(
    m._draftKey("overview-popup", "#heads") ===
      "orochi.draft.overview-popup.#heads",
    "overview-popup key format matches spec",
  );
}

console.log("\n" + passed + " passed, " + failed + " failed");
process.exit(failed === 0 ? 0 : 1);
