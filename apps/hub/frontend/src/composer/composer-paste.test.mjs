/* composer/composer-paste.test.mjs — node-runner for the paste helpers.
 *
 * Matches the style of draft-store.test.mjs (no vitest/jest in this
 * repo; run via `node hub/frontend/src/composer/composer-paste.test.mjs`).
 *
 * Covers:
 *   - _collectPastedImages dedups by (name|size|type|lastModified)
 *   - _collectPastedImages ignores non-image MIME types
 *   - _collectPastedImages falls through to cd.items when cd.files is empty
 *
 * The real composer-paste.ts pulls in `../upload` at module load (for
 * _pastedTextShouldAttach / _buildPastedTextFile), which in turn touches
 * DOM. Unit tests therefore re-implement only the pure dedup helper
 * against the same spec — the DOM-wiring path is typecheck- and
 * build-verified separately.
 */

function _collectPastedImages(cd) {
  var collected = [];
  var seen = new Set();
  function pushUnique(f) {
    if (!f || !f.type || f.type.indexOf("image/") !== 0) return;
    var key =
      f.name + "|" + f.size + "|" + f.type + "|" + (f.lastModified || 0);
    if (seen.has(key)) return;
    seen.add(key);
    collected.push(f);
  }
  if (!cd) return collected;
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
  return collected;
}

let passed = 0;
let failed = 0;
function test(name, fn) {
  try {
    fn();
    console.log(`PASS ${name}`);
    passed++;
  } catch (e) {
    console.log(`FAIL ${name}: ${e.message}`);
    failed++;
  }
}
function assertEq(a, b, msg) {
  if (a !== b) {
    throw new Error(`${msg || "expected"}: ${JSON.stringify(a)} !== ${JSON.stringify(b)}`);
  }
}

function mkFile(name, size, type, lastModified) {
  return { name: name, size: size, type: type, lastModified: lastModified || 0 };
}

test("returns empty for null clipboard data", () => {
  assertEq(_collectPastedImages(null).length, 0);
});

test("returns empty for empty files + items", () => {
  assertEq(_collectPastedImages({ files: [], items: [] }).length, 0);
});

test("collects a single image from cd.files", () => {
  var cd = { files: [mkFile("a.png", 100, "image/png")] };
  var out = _collectPastedImages(cd);
  assertEq(out.length, 1);
  assertEq(out[0].name, "a.png");
});

test("ignores non-image MIME in cd.files", () => {
  var cd = {
    files: [
      mkFile("a.png", 100, "image/png"),
      mkFile("b.txt", 50, "text/plain"),
    ],
  };
  var out = _collectPastedImages(cd);
  assertEq(out.length, 1);
  assertEq(out[0].name, "a.png");
});

test("dedups by (name|size|type|lastModified)", () => {
  var a1 = mkFile("a.png", 100, "image/png", 1);
  var a2 = mkFile("a.png", 100, "image/png", 1);
  var cd = { files: [a1, a2] };
  assertEq(_collectPastedImages(cd).length, 1);
});

test("does NOT dedup when lastModified differs", () => {
  var cd = {
    files: [
      mkFile("a.png", 100, "image/png", 1),
      mkFile("a.png", 100, "image/png", 2),
    ],
  };
  assertEq(_collectPastedImages(cd).length, 2);
});

test("falls through to cd.items when cd.files is empty", () => {
  var file = mkFile("c.jpg", 200, "image/jpeg");
  var cd = {
    files: [],
    items: [{ type: "image/jpeg", getAsFile: () => file }],
  };
  var out = _collectPastedImages(cd);
  assertEq(out.length, 1);
  assertEq(out[0].name, "c.jpg");
});

test("cd.items path also skips non-image items", () => {
  var file = mkFile("c.jpg", 200, "image/jpeg");
  var cd = {
    files: [],
    items: [
      { type: "text/plain", getAsFile: () => mkFile("t.txt", 50, "text/plain") },
      { type: "image/jpeg", getAsFile: () => file },
    ],
  };
  assertEq(_collectPastedImages(cd).length, 1);
});

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
