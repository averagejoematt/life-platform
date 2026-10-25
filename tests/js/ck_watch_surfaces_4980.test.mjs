// tests/js/ck_watch_surfaces_4980.test.mjs — #4980: the watch on the public pages.
//
// A trend: VO2 max (every estimate on record, each labelled with its device, the line broken
// where the device changes and at the served baseline change), honest steps (each day says
// whose count it is) and the watch's active energy (from its first day only). The verify page:
// "two instruments" from the served registry words, and no agreement before the study rules.
// Synthetic bodies only; no builder reads the wall clock.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const D = await import("../../site/assets/js/ck_depth.js");
const { renderVerify, verifyInstruments } = await import("../../site/assets/js/evidence_meta.js");
const BASE = "/next/v8/";

const VITALS = {
  baseline_change: "2026-10-10",
  vo2max: {
    available: true,
    series: [
      { date: "2021-06-01", value: 41.0, source: "apple_health", device: "Apple Health" },
      { date: "2021-07-18", value: 43.3, source: "apple_health", device: "Apple Health" },
      { date: "2024-03-01", value: 38.0, source: "garmin", device: "Garmin watch" },
      { date: "2026-05-19", value: 33.3, source: "garmin", device: "Garmin watch" },
    ],
  },
};

test("VO2 max reads the served arc and keeps each point's device", () => {
  const pts = D.seriesOf("vo2max", { vitals: VITALS });
  assert.deepEqual(pts.map((p) => [p.date, p.device]), [["2021-06-01", "Apple Health"], ["2021-07-18", "Apple Health"], ["2024-03-01", "Garmin watch"], ["2026-05-19", "Garmin watch"]]);
  assert.deepEqual(D.seriesOf("vo2max", { vitals: { vo2max: { available: false } } }), []);
  assert.deepEqual(D.seriesOf("vo2max", {}), []);
});

test("the VO2 max line breaks where the device changes, and says which device when", () => {
  const pts = D.seriesOf("vo2max", { vitals: VITALS });
  const html = D.trendChartHTML(pts, D.MEASURES.vo2max.write, "VO2 max", { day: D.yearDay });
  assert.equal((html.match(/<polyline class="ck-chart__line"/g) || []).length, 2, "one line per device run");
  assert.match(html, /The line breaks where the device changes: Apple Health, June 1, 2021 to July 18, 2021; Garmin watch, March 1, 2024 to May 19, 2026\./);
  assert.match(html, /June 1, 2021 · 41 ml\/kg\/min/);
  assert.doesNotMatch(html, /ck-chart__bc/, "no baseline-change rule when no point crosses it");
});

test("a VO2 max point after the baseline change breaks the line there too", () => {
  const series = [...VITALS.vo2max.series, { date: "2026-10-20", value: 34.0, source: "apple_health", device: "Apple Watch" }, { date: "2026-10-24", value: 34.5, source: "apple_health", device: "Apple Watch" }];
  const pts = D.seriesOf("vo2max", { vitals: { ...VITALS, vo2max: { available: true, series } } });
  const html = D.trendChartHTML(pts, D.MEASURES.vo2max.write, "VO2 max", { day: D.yearDay, baselineChange: "2026-10-10" });
  assert.equal((html.match(/<polyline class="ck-chart__line"/g) || []).length, 3);
  assert.match(html, /ck-chart__bc/);
  assert.match(html, /baseline change · October 10, 2026/);
  assert.match(html, /Apple Watch, October 20, 2026 to October 24, 2026/);
});

test("a one-device series is unchanged: one line, no device sentence", () => {
  const pts = [{ date: "2026-10-01", value: 300 }, { date: "2026-10-02", value: 299 }];
  const html = D.trendChartHTML(pts, D.MEASURES.weight.write, "Weight");
  assert.equal((html.match(/<polyline/g) || []).length, 1);
  assert.doesNotMatch(html, /device changes/);
  assert.equal(D.deviceRunsText(pts), "");
});

test("VO2 max readings are listed with their year and device, and without day doors", () => {
  const pts = D.seriesOf("vo2max", { vitals: VITALS });
  const html = D.recentRowsHTML(pts, D.MEASURES.vo2max.write, BASE, 7, { link: false });
  assert.match(html, /May 19, 2026 · Tuesday · 33\.3 ml\/kg\/min · Garmin watch/);
  assert.match(html, /Jun 1, 2021 · Tuesday · 41 ml\/kg\/min · Apple Health/);
  assert.doesNotMatch(html, /href=/, "no door to a day page that does not exist");
});

const PULSE = {
  watch_first_day: "2026-10-17",
  pulse_history: [
    { date: "2026-10-15", steps: 9000, steps_source: "whoop", active_kcal: null },
    { date: "2026-10-16", steps: 6000, steps_source: "apple_health", active_kcal: null },
    { date: "2026-10-18", steps: 12000, steps_source: "apple_health", active_kcal: 813 },
    { date: "2026-10-19", steps: 8000, steps_source: "garmin", active_kcal: 640 },
  ],
};

test("each day's steps say whose count they are", () => {
  const pts = D.seriesOf("steps", { pulse: PULSE });
  assert.deepEqual(pts.map((p) => p.device), ["wrist strap", "phone", "phone and watch", "Garmin watch"]);
  const html = D.recentRowsHTML(pts, D.MEASURES.steps.write, BASE);
  assert.match(html, /12,000 · phone and watch/);
  assert.match(html, /9,000 · wrist strap/);
  assert.match(html, /href="\/next\/v8\/day\/\?d=2026-10-18"/, "steps rows keep their day doors");
  assert.equal(D.stepsBy("apple_health", "2026-10-16", "2026-10-17"), "phone");
  assert.equal(D.stepsBy("apple_health", "2026-10-16", ""), "phone", "no served watch day: never claimed for the watch");
  assert.equal(D.stepsBy(undefined, "2026-10-16", "2026-10-17"), "");
});

test("active energy starts with the watch: no reading before it is drawn or counted", () => {
  const pts = D.seriesOf("energy", { pulse: PULSE });
  assert.deepEqual(pts.map((p) => [p.date, p.value]), [["2026-10-18", 813], ["2026-10-19", 640]]);
  assert.equal(D.MEASURES.energy.write(812.6), "813 kcal");
  assert.match(D.trendSentence(pts, D.MEASURES.energy.write), /2 readings from October 18 to October 19\. Lowest 640 kcal, highest 813 kcal, average 727 kcal\./);
});

test("the trend index lists the watch's measures under Training", () => {
  const html = D.trendIndexHTML(BASE, { pulse: PULSE, vitals: VITALS });
  assert.match(html, /\?m=energy">Active energy \(watch\) · 640 kcal/);
  assert.match(html, /\?m=vo2max">VO2 max · 33\.3 ml\/kg\/min/);
  assert.match(html, /Steps \(wrist strap, else phone and watch\)/);
});

const INSTRUMENTS = [
  { measure: "Steps", answers: "Whoop first; when it has none, the phone and Apple Watch.", other: "", combined: "pending" },
  { measure: "Resting heart rate", answers: "Whoop.", other: "The Apple Watch records its own reading beside it, kept private.", combined: "pending" },
];

test("the verify page explains the two instruments from the served words", () => {
  const html = verifyInstruments({ instruments: INSTRUMENTS });
  assert.match(html, /Two instruments/);
  assert.match(html, /<strong>Steps<\/strong> — Whoop first; when it has none, the phone and Apple Watch\./);
  assert.match(html, /Nothing is averaged across the two until their comparison has been read and ruled on\./);
  assert.equal(verifyInstruments({}), "");
});

test("at 30 nights with no ruling the page states no agreement", () => {
  const html = renderVerify({
    status: "awaiting_ruling",
    n_nights: 31,
    min_nights: 30,
    watch_era: { start: "2026-10-17" },
    study: { state: "awaiting_ruling", n_nights: 31, min_nights: 30, verdict_published: false },
    study_reason: "31 nights recorded on both devices since 2026-10-17. The comparison has enough nights; its result is published once it has been read and ruled on.",
    instruments: INSTRUMENTS,
    rhr_agreement: null,
    combined_agreement_rate_pct: null,
    daily: [],
  });
  assert.match(html, /its result is published once it has been read and ruled on/);
  assert.match(html, /Two instruments/);
  assert.doesNotMatch(html, /agreement rate|Across every overlapping night|night by night/);
  assert.doesNotMatch(html, /bpm<\/td>|\d+ bpm/, "no heart-rate value");
});
