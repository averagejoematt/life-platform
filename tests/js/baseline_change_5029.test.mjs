// #5029 — every public heart-rate-derived chart breaks (or footnotes) at the served baseline-change date,
// labelled "baseline change", and never gives a reason. The date is an argument here, exactly as a payload's
// `baseline_change` is at runtime: the front-end never hard-codes it.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const charts = await import("../../site/assets/js/charts.js");
const vitals = await import("../../site/assets/js/evidence_vitals.js");
const ck = await import("../../site/assets/js/ck_depth.js");
const { lineChart, arcTrend, autonomicHero, sparkline, barChart, baselineChangeIndex } = charts;

const BC = "2026-10-10";
const days = (from, n) => Array.from({ length: n }, (_, i) => new Date(Date.parse(`${from}T12:00:00Z`) + i * 86400000).toISOString().slice(0, 10));
const SPAN = days("2026-10-05", 10); // 10-05 .. 10-14 spans the change
const series = SPAN.map((d, i) => ({ date: d, value: 60 - i, rhr_bpm: 60 - i, hrv_ms: 40 + i }));
const FORBIDDEN = /\b(AF|AFib|atrial|fibrillation|metoprolol|medication|diagnos|clinical|cardiac|arrhythm|regime|re-baselin)/i;

const breaks = (svgPathD) => (svgPathD.match(/M/g) || []).length;
const lineD = (html, cls) => new RegExp(`class="${cls}" d="([^"]+)"`).exec(html)[1];

test("baselineChangeIndex: only a series with points on both sides breaks", () => {
  assert.equal(baselineChangeIndex(SPAN, BC), 5);
  assert.equal(baselineChangeIndex(days("2026-10-10", 5), BC), -1); // all on/after
  assert.equal(baselineChangeIndex(days("2026-09-01", 5), BC), -1); // all before
  assert.equal(baselineChangeIndex(SPAN, null), -1);
  assert.equal(baselineChangeIndex(SPAN, "garbage"), -1);
});

test("lineChart breaks its line and footnotes 'baseline change' at the date", () => {
  const html = lineChart(series, { unit: " bpm", label: "Resting heart rate", baselineChange: BC });
  assert.equal(breaks(lineD(html, "chart-line")), 2, "the stroke lifts the pen once");
  assert.match(html, /class="chart-bc"/);
  assert.match(html, /<span class="chart-bc-note">baseline change<\/span> Oct 10/);
  assert.doesNotMatch(html, FORBIDDEN);
});

test("lineChart with no baselineChange (or a series on one side) is unchanged", () => {
  const plain = lineChart(series, { unit: " bpm", label: "x" });
  assert.equal(breaks(lineD(plain, "chart-line")), 1);
  assert.doesNotMatch(plain, /chart-bc|baseline change/);
  const after = lineChart(series.slice(5), { unit: " bpm", label: "x", baselineChange: BC });
  assert.doesNotMatch(after, /chart-bc|baseline change/);
});

test("autonomicHero breaks BOTH lines and footnotes once", () => {
  const html = autonomicHero(series, { baselineChange: BC });
  assert.equal(breaks(lineD(html, "ah-hrv")), 2);
  assert.equal(breaks(lineD(html, "ah-rhr")), 2);
  assert.equal((html.match(/class="chart-bc-note"/g) || []).length, 1);
  assert.match(html, /baseline change/);
  assert.doesNotMatch(html, FORBIDDEN);
  assert.doesNotMatch(autonomicHero(series), /baseline change/);
});

test("arcTrend (walking HR / VO2max) breaks the arc and never smooths across the date", () => {
  const html = arcTrend(series.map((s, i) => ({ ...s, value: i < 5 ? 100 : 200 })), { unit: " bpm", label: "Walking HR", baselineChange: BC });
  const d = lineD(html, "wt-trend");
  assert.equal(breaks(d), 2);
  // each side is flat: smoothing stayed on its own side of the date (a bridged window would give 100 < y < 200)
  const ys = [...d.matchAll(/[ML][\d.]+ ([\d.]+)/g)].map((m) => m[1]);
  assert.equal(new Set(ys.slice(0, 5)).size, 1);
  assert.equal(new Set(ys.slice(5)).size, 1);
  assert.match(html, /baseline change/);
  assert.doesNotMatch(html, FORBIDDEN);
});

test("sparkline breaks only for dated points", () => {
  const dated = series.map((s) => ({ v: s.value, d: s.date }));
  assert.equal(breaks(lineD(sparkline(dated, { baselineChange: BC }), "chart-line")), 2);
  assert.match(sparkline(dated, { baselineChange: BC }), /class="chart-bc"/);
  assert.equal(breaks(lineD(sparkline(series.map((s) => s.value), { baselineChange: BC }), "chart-line")), 1);
});

test("zone-2 style bar chart dashes the flagged week and footnotes it", () => {
  const html = barChart([{ label: "10-05", value: 90 }, { label: "10-12", value: 40, bc: true }, { label: "10-19", value: 30 }], { label: "Zone-2 min / week" });
  assert.equal((html.match(/cbar--bc/g) || []).length, 1);
  assert.match(html, /<span class="chart-bc-note">baseline change<\/span>/);
  assert.doesNotMatch(barChart([{ label: "a", value: 1 }], { label: "x" }), /baseline change/);
});

test("vitals small multiples footnote only the heart-rate-derived signals", () => {
  const hist = SPAN.map((d, i) => ({ date: d, recovery_pct: 50 + i, hrv_ms: 40 + i, rhr_bpm: 60 - i, strain: 8 + i / 10, weight_lbs: 300 - i, steps: 8000 + i }));
  const html = vitals.vitalsSmallMultiples(hist, BC);
  assert.equal((html.match(/class="chart-bc-note label">baseline change</g) || []).length, 4, "recovery, HRV, resting HR, strain");
  assert.doesNotMatch(html, FORBIDDEN);
  assert.doesNotMatch(vitals.vitalsSmallMultiples(hist), /baseline change/);
});

test("the recovery trend page breaks its line and footnotes it", () => {
  const pts = SPAN.map((d, i) => ({ date: d, value: 70 - i }));
  const html = ck.trendChartHTML(pts, (v) => `${v} out of 100`, "Recovery", { baselineChange: BC });
  assert.equal((html.match(/<polyline class="ck-chart__line"/g) || []).length, 2);
  assert.match(html, /class="ck-chart__bc"/);
  assert.match(html, /baseline change · October 10/);
  assert.doesNotMatch(html, FORBIDDEN);
  assert.doesNotMatch(ck.trendChartHTML(pts, (v) => String(v), "Recovery"), /baseline change/);
});

test("no HR-chart renderer hard-codes the date or names a reason", async () => {
  const { readFileSync } = await import("node:fs");
  for (const f of ["charts.js", "evidence_vitals.js", "evidence_autonomic.js", "evidence_body.js", "ck_depth.js"]) {
    const src = readFileSync(new URL(`../../site/assets/js/${f}`, import.meta.url), "utf8");
    assert.doesNotMatch(src, /2026-10-10/, `${f} hard-codes the baseline-change date`);
    assert.doesNotMatch(src, /\b(atrial|fibrillation|metoprolol)\b/i, `${f} names a clinical reason`);
  }
});

test("the training page's resting-HR hero footnotes the baseline change and stops scoring the drop as a win", async () => {
  const { trainingRHRHero } = await import("../../site/assets/js/evidence_body.js");
  const html = trainingRHRHero(series, BC);
  assert.match(html, /<span class="chart-bc-note">baseline change<\/span> Oct 10/, "the footnote renders under the hero chart");
  assert.equal(breaks(lineD(html, "chart-line")), 2, "the hero line lifts the pen at the change");
  assert.match(html, /read within each side of the baseline change/);
  assert.match(html, /the baseline moving, not a fitness gain/);
  assert.match(html, /since the change it&#39;s drifting down|since the change it's drifting down/);
  assert.doesNotMatch(html, /down is the win/, "the softened copy replaces the fitness-win line across the break");
  assert.doesNotMatch(html, /the engine answering/);
  assert.doesNotMatch(html, FORBIDDEN);
  // one side only (no change in the window, or every point after it): the original read is unchanged
  for (const plain of [trainingRHRHero(series), trainingRHRHero(series.slice(5), BC)]) {
    assert.doesNotMatch(plain, /baseline change/);
    assert.match(plain, /the engine answering/);
  }
});

test("renderTraining hands the pulse_history payload's baseline_change to the hero", async () => {
  const { readFileSync } = await import("node:fs");
  const src = readFileSync(new URL("../../site/assets/js/evidence_body.js", import.meta.url), "utf8");
  assert.match(src, /trainingRHRHero\(\(ph && ph\.pulse_history\) \|\| \[\], \(ph && ph\.baseline_change\) \|\| null\)/);
});
