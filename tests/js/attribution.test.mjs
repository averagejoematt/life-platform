// tests/js/attribution.test.mjs — unit tests for the site-wide UTM capture module
// (#1621). This module is loaded from the canonical footer on every chrome-bearing
// page, so a regression here is a silent, site-wide loss of the acquisition signal
// the epic's 60-day growth gate is graded on — and it fails invisibly (the page still
// renders, the form still submits, the attribution is just gone).
//
// Dynamic `await import()` rather than a static import: a static import specifier is
// resolved BEFORE the loader registered by support/loader.mjs takes effect.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const mod = await import("../../site/assets/js/attribution.js");
const { normalize, parseUtm, captureFromLocation, readAttribution, attributionPayload, withUtm, STORAGE_KEY } = mod;

/** Minimal sessionStorage stand-in. */
function fakeStorage(initial) {
  const map = new Map(initial ? Object.entries(initial) : []);
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
    _map: map,
  };
}

const loc = (search, pathname = "/") => ({ search, pathname });

// ── normalize ────────────────────────────────────────────────────────────────

test("normalize — lowercases, trims, and collapses disallowed chars", () => {
  assert.equal(normalize("  Reddit  "), "reddit");
  assert.equal(normalize("Quantified Self"), "quantified-self");
  assert.equal(normalize("news.ycombinator.com"), "news.ycombinator.com");
});

test("normalize — strips markup rather than escaping it", () => {
  assert.equal(normalize("<script>alert(1)</script>"), "script-alert-1-script");
});

test("normalize — caps length and handles non-strings", () => {
  assert.equal(normalize("x".repeat(500)).length, 64);
  assert.equal(normalize(null), "");
  assert.equal(normalize(undefined), "");
  assert.equal(normalize(42), "");
});

// ── parseUtm ─────────────────────────────────────────────────────────────────

test("parseUtm — extracts and normalizes the utm keys present", () => {
  const out = parseUtm("?utm_source=Reddit&utm_campaign=quantifiedself");
  assert.deepEqual(out, { utm_source: "reddit", utm_campaign: "quantifiedself" });
});

test("parseUtm — ignores non-utm params entirely", () => {
  assert.deepEqual(parseUtm("?ref=x&fbclid=abc&tab=sleep"), {});
});

test("parseUtm — empty/absent/garbage search yields an empty object", () => {
  assert.deepEqual(parseUtm(""), {});
  assert.deepEqual(parseUtm(undefined), {});
  assert.deepEqual(parseUtm("?utm_source="), {});
});

// ── capture + persistence (the load-bearing behaviour) ───────────────────────

test("captureFromLocation — persists to storage so it survives navigation", () => {
  const storage = fakeStorage();
  captureFromLocation(loc("?utm_source=reddit"), storage);
  const stored = readAttribution(storage);
  assert.equal(stored.utm_source, "reddit");
  assert.ok(storage.getItem(STORAGE_KEY), "must write under the shared storage key");
});

test("captureFromLocation — a LATER clean-URL page still reads the landing attribution", () => {
  // This is the whole reason the module is site-wide: land with the UTM on /, then
  // navigate to /subscribe/ where location.search is empty.
  const storage = fakeStorage();
  captureFromLocation(loc("?utm_source=reddit", "/"), storage);
  captureFromLocation(loc("", "/subscribe/"), storage);
  assert.equal(readAttribution(storage).utm_source, "reddit");
});

test("captureFromLocation — first write wins; a later campaign does not overwrite", () => {
  const storage = fakeStorage();
  captureFromLocation(loc("?utm_source=reddit"), storage);
  captureFromLocation(loc("?utm_source=twitter"), storage);
  assert.equal(readAttribution(storage).utm_source, "reddit");
});

test("captureFromLocation — no utm params means nothing is stored at all", () => {
  const storage = fakeStorage();
  assert.equal(captureFromLocation(loc("?tab=sleep"), storage), null);
  assert.equal(readAttribution(storage), null);
});

test("captureFromLocation — stores the landing PATH only, never the query string", () => {
  const storage = fakeStorage();
  captureFromLocation(loc("?utm_source=reddit&token=SECRET", "/cockpit/"), storage);
  const raw = storage.getItem(STORAGE_KEY);
  assert.equal(readAttribution(storage).landing_path, "/cockpit/");
  assert.ok(!raw.includes("SECRET"), "querystring content must never be persisted");
});

test("captureFromLocation — a throwing storage never propagates", () => {
  const hostile = {
    getItem: () => null,
    setItem: () => {
      throw new Error("QuotaExceeded");
    },
  };
  assert.doesNotThrow(() => captureFromLocation(loc("?utm_source=reddit"), hostile));
});

test("readAttribution — corrupt stored JSON degrades to null, not a throw", () => {
  const storage = fakeStorage({ [STORAGE_KEY]: "{not json" });
  assert.equal(readAttribution(storage), null);
});

// ── the POST payload ─────────────────────────────────────────────────────────

test("attributionPayload — only utm_* fields, never the internal bookkeeping", () => {
  const storage = fakeStorage();
  captureFromLocation(loc("?utm_source=reddit&utm_medium=social", "/cockpit/"), storage);
  const payload = attributionPayload(storage);
  assert.deepEqual(payload, { utm_source: "reddit", utm_medium: "social" });
  assert.ok(!("landing_path" in payload));
  assert.ok(!("captured_at" in payload));
});

test("attributionPayload — empty object when nothing captured (safe to spread)", () => {
  assert.deepEqual(attributionPayload(fakeStorage()), {});
  assert.deepEqual(attributionPayload(null), {});
});

// ── the outbound helper ──────────────────────────────────────────────────────

test("withUtm — tags a URL and preserves existing query params", () => {
  const out = withUtm("https://averagejoematt.com/data/?tab=sleep", { source: "rss", medium: "feed" });
  assert.ok(out.includes("tab=sleep"));
  assert.ok(out.includes("utm_source=rss"));
  assert.ok(out.includes("utm_medium=feed"));
});

test("withUtm — is idempotent; an already-tagged link keeps its tags", () => {
  const once = withUtm("https://averagejoematt.com/story/", { source: "rss", medium: "feed" });
  assert.equal(withUtm(once, { source: "other", medium: "other" }), once);
});

test("withUtm — root-relative URLs stay root-relative", () => {
  const out = withUtm("/subscribe/", { source: "footer", medium: "site" });
  assert.ok(out.startsWith("/subscribe/?"), `expected root-relative, got ${out}`);
});

test("withUtm — normalizes tag values through the same rule as capture", () => {
  assert.ok(withUtm("/x", { source: "Reddit Ads" }).includes("utm_source=reddit-ads"));
});

test("withUtm — junk input is returned unchanged rather than throwing", () => {
  assert.equal(withUtm("", { source: "x" }), "");
  assert.equal(withUtm(null, { source: "x" }), null);
});
