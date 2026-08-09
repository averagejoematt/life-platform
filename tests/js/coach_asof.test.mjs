// tests/js/coach_asof.test.mjs — #1971: the coaching door's FIRST screen must
// disclose the #802 budget-guard pause, and must degrade honestly while the API
// field isn't live yet.
//
// Two properties pinned here:
//
//  1. coachAsOf(generatedAt, paused) — paused=true renders the "refresh paused
//     (budget guard)" disclosure; paused=false renders only the dated kicker
//     (the negative test: the disclosure NEVER appears un-paused).
//
//  2. regenerationPaused(payload) — STRICT `=== true`. An absent field is
//     UNKNOWN, not "not paused": that is the exact state during an API-deploy /
//     site-deploy race (site/ auto-deploys on merge; the site-api half rides the
//     owner's next flush), and unknown must render nothing new — never a
//     fabricated pause banner, never a crash.
//
// Plus a source set-guard (the daily_line.test.mjs idiom): no coachAsOf call
// site in site/assets/js/ may pass a boolean LITERAL as the paused argument —
// `coachAsOf(..., false)` hardcoded on the roster render is precisely the bug
// #1971 fixes, and this guard keeps it from growing back at any call site.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// Dynamic import after loader registration (the
// reference_site_js_test_and_build_pairs gotcha — a static import would resolve
// the graph before the "/assets/…" resolver exists).
const { coachAsOf, regenerationPaused, ensembleFallback } = await import("../../site/assets/js/coach_asof.js");

const SITE_JS = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "site", "assets", "js");

/* ── coachAsOf: the disclosure itself ────────────────────────────────────── */

test("paused with a dated read: as-of date + the budget-guard disclosure", () => {
  const s = coachAsOf("2026-07-27T14:00:00Z", true);
  assert.equal(s, "as of Jul 27 — refresh paused (budget guard)");
});

test("paused with no usable date: the disclosure still renders alone", () => {
  assert.equal(coachAsOf("", true), "refresh paused (budget guard)");
  assert.equal(coachAsOf("not-a-date", true), "refresh paused (budget guard)");
});

test("NOT paused, fresh read: dated kicker only — the disclosure never leaks in (negative test)", () => {
  const oneHourAgo = new Date(Date.now() - 3600e3).toISOString();
  const s = coachAsOf(oneHourAgo, false);
  assert.match(s, /^as of /);
  assert.ok(!s.includes("paused"), `un-paused kicker must not carry the disclosure: "${s}"`);
});

test("NOT paused, stale read (>48h): 'next refresh pending', still no pause claim", () => {
  const fourDaysAgo = new Date(Date.now() - 96 * 3600e3).toISOString();
  const s = coachAsOf(fourDaysAgo, false);
  assert.match(s, /next refresh pending$/);
  assert.ok(!s.includes("paused"));
});

test("NOT paused, no date: empty string — no kicker renders at all", () => {
  assert.equal(coachAsOf("", false), "");
  assert.equal(coachAsOf(undefined, false), "");
});

/* ── regenerationPaused: absent field = unknown, render nothing new ──────── */

test("regeneration_paused === true is the ONLY paused reading", () => {
  assert.equal(regenerationPaused({ regeneration_paused: true }), true);
});

test("explicit false, absent field, and no payload all read not-paused", () => {
  assert.equal(regenerationPaused({ regeneration_paused: false }), false);
  assert.equal(regenerationPaused({}), false); // absent = unknown (deploy race) → nothing new
  assert.equal(regenerationPaused(null), false);
  assert.equal(regenerationPaused(undefined), false);
});

test("shape-drifted truthy values never fabricate a pause banner", () => {
  assert.equal(regenerationPaused({ regeneration_paused: "true" }), false);
  assert.equal(regenerationPaused({ regeneration_paused: 1 }), false);
});

/* ── ensembleFallback: same discipline, for the cross-coach digest (#2333) ── */

test("ensemble_fallback === true is the ONLY fallback reading", () => {
  assert.equal(ensembleFallback({ ensemble_fallback: true }), true);
});

test("explicit false, absent field, and no payload all read not-fallback", () => {
  assert.equal(ensembleFallback({ ensemble_fallback: false }), false);
  assert.equal(ensembleFallback({}), false); // absent = unknown → nothing new
  assert.equal(ensembleFallback(null), false);
  assert.equal(ensembleFallback(undefined), false);
});

test("shape-drifted truthy values never fabricate a fallback banner", () => {
  assert.equal(ensembleFallback({ ensemble_fallback: "true" }), false);
  assert.equal(ensembleFallback({ ensemble_fallback: 1 }), false);
});

/* ── set-guard: no call site may hardcode the paused argument ────────────── */

test("no coachAsOf call site in site/assets/js/ passes a boolean literal for paused", () => {
  const offenders = [];
  for (const f of readdirSync(SITE_JS).filter((f) => f.endsWith(".js"))) {
    const src = readFileSync(join(SITE_JS, f), "utf8");
    // A literal true/false as the final argument to coachAsOf — the exact form
    // of the #1971 bug (`coachAsOf(c.analysis_generated_at, false)`).
    if (/coachAsOf\([^()]*,\s*(true|false)\s*\)/.test(src)) offenders.push(f);
  }
  assert.deepEqual(offenders, [], `hardcoded paused literal at a coachAsOf call site in: ${offenders.join(", ")}`);
});

test("coaching.js consumes the shared module — no drifted local redefinition", () => {
  const src = readFileSync(join(SITE_JS, "coaching.js"), "utf8");
  assert.ok(src.includes('from "/assets/js/coach_asof.js"'), "coaching.js must import coach_asof.js");
  assert.ok(!/function\s+coachAsOf\s*\(/.test(src), "coaching.js must not redefine coachAsOf locally");
  assert.ok(!/function\s+regenerationPaused\s*\(/.test(src), "coaching.js must not redefine regenerationPaused locally");
});
