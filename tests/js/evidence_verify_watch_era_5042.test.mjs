// tests/js/evidence_verify_watch_era_5042.test.mjs — /method/verify/ (#5042, Refs #4976 #4974).
//
// The live finding: the cross-device table claimed 83 nights of Whoop-vs-Apple-Watch overlap
// from 2025-12-07, but the watch's first resting-heart-rate reading is 2026-10-17. The producer
// now floors the window at the watch era and returns `too_few_nights` below the agreement
// study's 30-night minimum; the page must render that as "too few nights to compare yet" with
// the era start, and never an agreement rate or a HIGH/LOW verdict.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { renderVerify } = await import("../../site/assets/js/evidence_meta.js");

const ERA = { start: "2026-10-17", determined_by: "the earliest Apple Watch-sourced RHR reading" };
const night = (date, w, a) => ({ date, whoop_rhr_bpm: w, apple_rhr_bpm: a, rhr_abs_diff_bpm: Math.abs(w - a), rhr_agreement: Math.abs(w - a) <= 3 ? "agree" : "flag" });

test("below the study minimum the page shows the honest-empty state, n and the era start, no verdict", () => {
  const html = renderVerify({
    status: "too_few_nights",
    period: { start: "2026-10-18", end: "2026-10-18", overlapping_days: 1 },
    n_nights: 1,
    min_nights: 30,
    watch_era: ERA,
    rhr_agreement: null,
    combined_agreement_rate_pct: null,
    device_confidence: null,
    daily: [night("2026-10-18", 51, 48)],
    hrv_note: "HRV is not compared.",
  });
  assert.match(html, /Too few nights to compare yet — 1 of the 30/);
  assert.match(html, /Apple Watch \(from 2026-10-17\)/);
  assert.doesNotMatch(html, /agreement rate/);
  assert.doesNotMatch(html, /Across every overlapping night/);
  assert.doesNotMatch(html, /HIGH|LOW|MODERATE/);
  // the raw night is still shown — it is a reading, not a finding
  assert.match(html, /2026-10-18/);
});

test("at the study minimum the verdict renders, captioned with the watch era", () => {
  const daily = Array.from({ length: 30 }, (_, i) => night(`2026-11-${String(i + 1).padStart(2, "0")}`, 55, 54));
  const html = renderVerify({
    status: "ok",
    period: { start: "2026-11-01", end: "2026-11-30", overlapping_days: 30 },
    n_nights: 30,
    min_nights: 30,
    watch_era: ERA,
    rhr_agreement: { agree_days: 30, minor_days: 0, flagged_days: 0, agreement_rate_pct: 100 },
    combined_agreement_rate_pct: 100,
    daily,
  });
  assert.match(html, /agreement rate/);
  assert.match(html, /Whoop vs Apple Watch \(from 2026-10-17\), night by night/);
  assert.match(html, /since the watch arrived \(2026-10-17\)/);
  assert.doesNotMatch(html, /Too few nights/);
});
