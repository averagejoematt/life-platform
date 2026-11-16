// tests/js/vitals_null_not_zero_5953.test.mjs — #5953 item 2: a missing reading is a gap, never a zero.
//
// The accuracy review (2026-11-14, calibrated) found the Vitals page reading today's not-yet-served Whoop row as
// zeros: `Number(null)` is 0 and finite, so the 7-day rings fell (RHR 7-day 44 against a 49 minimum), the last-night
// grid printed 0% / 0 ms / 0 bpm and the autonomic hero said HRV and RHR were both "down 0". Each assertion below
// fails on the code before the fix (the must-fail control is the old coercion, rebuilt inline at the end).
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { _vitalsComponents, vitalsLadder, vitalsSmallMultiples, finite } = await import("../../site/assets/js/evidence_vitals.js");
const { autonomicHero } = await import("../../site/assets/js/charts.js");

// six real nights, then today's row with nothing served yet
const hist = [
  { date: "2026-11-08", recovery_pct: 77, hrv_ms: 60, rhr_bpm: 52, sleep_hours: 7.3, strain: 9 },
  { date: "2026-11-09", recovery_pct: 63, hrv_ms: 55, rhr_bpm: 53, sleep_hours: 7.1, strain: 11 },
  { date: "2026-11-10", recovery_pct: 37, hrv_ms: 46, rhr_bpm: 55, sleep_hours: 5.4, strain: 10.9 },
  { date: "2026-11-11", recovery_pct: 71, hrv_ms: 58, rhr_bpm: 50, sleep_hours: 9.0, strain: 8 },
  { date: "2026-11-12", recovery_pct: 83, hrv_ms: 62, rhr_bpm: 49, sleep_hours: 8.6, strain: 12 },
  { date: "2026-11-13", recovery_pct: 75, hrv_ms: 61, rhr_bpm: 50, sleep_hours: 8.1, strain: 10 },
  { date: "2026-11-14", recovery_pct: null, hrv_ms: null, rhr_bpm: null, sleep_hours: null, strain: null },
];

test("finite: a number or null — never a zero for a missing reading", () => {
  for (const x of [null, undefined, "", true, false, "n/a"]) assert.equal(finite(x), null, String(x));
  assert.equal(finite(0), 0);
  assert.equal(finite("51.5"), 51.5);
});

test("last night is the latest row that has the reading, not today's empty row", () => {
  const comps = _vitalsComponents({}, hist);
  const by = Object.fromEntries(comps.map((c) => [c.key, c.raw]));
  assert.deepEqual(by, { recovery: 75, hrv: 61, rhr: 50, sleep: 8.1 });
});

test("the 7-day means leave the missing day out (RHR 7-day 51.5 over six nights, not 44 over seven with a zero)", () => {
  const html = vitalsLadder(_vitalsComponents({}, hist), hist);
  const sevens = [...html.matchAll(/7d<\/span><span class="vl-v mono vl-base">([^<]+)</g)].map((m) => m[1]);
  // recovery 67.7 → 68, HRV 57.0 → 57, RHR 51.5 → 52, sleep 7.6
  assert.deepEqual(sevens, ["68", "57", "52", "7.6"]);
});

test("the small multiples end on the latest real reading, never a 0", () => {
  const html = vitalsSmallMultiples(hist);
  assert.doesNotMatch(html, /sm-v mono">0(\.0)?( |%|<)/);
  assert.match(html, /sm-v mono">50 bpm/);
});

test("the autonomic hero's summary reads the real first and last nights, never 'down 0'", () => {
  const html = autonomicHero(hist);
  assert.match(html, /resting HR down \(52→50 bpm\), HRV up \(60→61 ms\)/);
  assert.doesNotMatch(html, /→0 /);
});

test("must-fail control: the old coercion turns the same missing row into zeros", () => {
  const old = (x) => (Number.isFinite(Number(x)) ? Number(x) : null);
  assert.equal(old(null), 0, "Number(null) is 0 — the defect this file pins");
  const sevenOld = hist.map((h) => old(h.rhr_bpm)).filter((v) => v != null);
  assert.equal(sevenOld.length, 7, "the old reader kept today's missing row");
  assert.ok(Math.round(sevenOld.reduce((a, b) => a + b, 0) / 7) === 44, "and its mean was the review's 44");
});
