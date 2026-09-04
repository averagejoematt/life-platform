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
const { coachAsOf, regenerationPaused, ensembleFallback, weeklyAsOf, datableTensions } = await import("../../site/assets/js/coach_asof.js");

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

/* ── the DAY NUMBER in the dateline (2026-08-27) ──────────────────────────

   The live failure: /coaching/by-coach/#physical_coach served "I'm ten days into
   this restart with you — Day 10 as of today" on Day 11, under a tier-2
   regeneration pause. The prose dates ITSELF in experiment days, so a calendar
   dateline alone ("as of Aug 26") never reconciles it — a reader would have to
   know Aug 26 was Day 10. The stamp now carries both frames. */

test("REPLAY 2026-08-27: the held read is datelined in the frame its prose uses", () => {
  const s = coachAsOf("2026-08-26T17:02:28Z", true, 10);
  assert.equal(s, "as of Aug 26 · Day 10 — refresh paused (budget guard)");
  assert.match(s, /Day 10/, "the prose says Day 10; the dateline must say so too");
});

test("the day number rides the stale (un-paused) branch too", () => {
  const fourDaysAgo = new Date(Date.now() - 96 * 3600e3).toISOString();
  const s = coachAsOf(fourDaysAgo, false, 7);
  assert.match(s, /· Day 7 — next refresh pending$/);
});

test("an UNKNOWN day renders nothing — never Day 0, never a guess", () => {
  // A wrong day number over frozen prose is strictly worse than no day number:
  // it would make the dateline endorse the error it exists to frame.
  for (const bad of [undefined, null, 0, -3, NaN, "10", 10.5, true]) {
    const s = coachAsOf("2026-08-26T17:02:28Z", true, bad);
    assert.equal(s, "as of Aug 26 — refresh paused (budget guard)", `day ${String(bad)} must render nothing`);
  }
});

test("no date + a day number still renders the day (the dateline degrades, never vanishes)", () => {
  assert.equal(coachAsOf("", true, 10), "Day 10 — refresh paused (budget guard)");
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

/* ── weeklyAsOf + datableTensions: the tensions band (#2383) ─────────────── */

test("weeklyAsOf: a mid-week digest is current — dated, no pending/paused claim", () => {
  const threeDaysAgo = new Date(Date.now() - 72 * 3600e3).toISOString();
  const s = weeklyAsOf(threeDaysAgo);
  assert.match(s, /^as of /);
  assert.ok(!s.includes("pending") && !s.includes("paused"), `mid-cadence stamp must be plain-dated: "${s}"`);
});

test("weeklyAsOf: past the weekly cadence (>8d) — 'next refresh pending'", () => {
  const tenDaysAgo = new Date(Date.now() - 240 * 3600e3).toISOString();
  assert.match(weeklyAsOf(tenDaysAgo), /^as of .+ — next refresh pending$/);
});

test("weeklyAsOf: dates render Pacific (site convention)", () => {
  // Fixed instant; only the date part is asserted — the staleness suffix is
  // wall-clock-relative by design (reference_golden_tests_wallclock).
  assert.match(weeklyAsOf("2026-07-27T14:00:00Z"), /^as of Jul 27/);
});

test("weeklyAsOf: no/invalid date renders nothing — never a fabricated stamp", () => {
  assert.equal(weeklyAsOf(""), "");
  assert.equal(weeklyAsOf(undefined), "");
  assert.equal(weeklyAsOf("not-a-date"), "");
});

/* ── #3252: the integrator's call carries a DAY number too ─────────────────
   Its prose dates itself in experiment days ("he's been eleven days into the
   cycle"), and while regeneration is paused that sentence keeps asserting a
   frozen day as today's. The calendar date alone cannot reconcile it. */

// These two cases need a stamp INSIDE the weekly cadence window (WEEKLY_STALE_HOURS =
// 8 days), so the date must be DERIVED FROM NOW. Both used a hardcoded
// "2026-08-27T14:02:46.793290+00:00", which sat comfortably inside the window when it was
// written and silently aged out of it: on 2026-09-04 — exactly 8 days later — the
// "— next refresh pending" suffix appeared and the strict-equality case redded main on a
// commit that had touched none of this. The regex case survived only because it lacked a
// `$` anchor, which is luck, not coverage. A fixture that measures the wall clock must be
// derived from the wall clock (the golden-tests-wallclock class).
const FRESH_ISO = new Date(Date.now() - 2 * 3600e3).toISOString();
const FRESH_STAMP = `as of ${new Date(FRESH_ISO).toLocaleDateString("en-US", {
  timeZone: "America/Los_Angeles",
  month: "short",
  day: "numeric",
})}`;

test("weeklyAsOf: the day number joins the calendar date (#3252)", () => {
  assert.equal(weeklyAsOf(FRESH_ISO, 11), `${FRESH_STAMP} · Day 11`);
});

test("weeklyAsOf: an unknown day renders the date ALONE, never Day 0 or a guess", () => {
  // The must-fail direction is a fabricated anchor: a wrong day number is strictly
  // worse than none, so every non-positive-integer collapses to no day at all.
  for (const bad of [undefined, null, 0, -3, "11", 11.5, NaN, true]) {
    assert.equal(weeklyAsOf(FRESH_ISO, bad), FRESH_STAMP,
      `day ${JSON.stringify(bad)} must render no day label`);
  }
});

test("weeklyAsOf: an undatable record renders nothing even WITH a day number", () => {
  // A day number cannot resurrect a stamp the date half refused — otherwise the
  // helper would print a bare "Day 11" with nothing anchoring it to a date.
  assert.equal(weeklyAsOf("not-a-date", 11), "");
  assert.equal(weeklyAsOf("", 11), "");
});

test("weeklyAsOf: a stale record keeps its day number AND its pending suffix", () => {
  const tenDaysAgo = new Date(Date.now() - 240 * 3600e3).toISOString();
  assert.match(weeklyAsOf(tenDaysAgo, 4), /^as of .+ · Day 4 — next refresh pending$/);
});

test("datableTensions REFUSES undated argument prose (#2383)", () => {
  const dated = { topic: "zone 2", position_a: "a", position_b: "b", generated_at: "2026-08-05T14:00:00Z" };
  const undated = { topic: "protein", position_a: "x", position_b: "y" }; // absent = unknown (deploy race) → refuse
  const garbled = { topic: "sleep", position_a: "x", generated_at: "not-a-date" };
  assert.deepEqual(datableTensions([dated, undated, garbled]), [dated]);
});

test("datableTensions keeps the substance filter — a dated but position-less tension still drops", () => {
  assert.deepEqual(datableTensions([{ topic: "t", generated_at: "2026-08-05T14:00:00Z" }]), []);
  assert.deepEqual(datableTensions([null, undefined]), []);
  assert.deepEqual(datableTensions(null), []);
  assert.deepEqual(datableTensions(undefined), []);
});

test("tensionsHTML wires the pair: datableTensions filter + the tt-asof stamp (#2383)", () => {
  const src = readFileSync(join(SITE_JS, "coaching.js"), "utf8");
  assert.match(src, /datableTensions\(/, "tensionsHTML must filter argument prose through datableTensions");
  assert.match(src, /tt-asof/, "the tensions band must render the tt-asof as-of stamp");
  assert.match(src, /weeklyAsOf\(/, "the band's stamp must come from weeklyAsOf (writer-cadence staleness)");
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
