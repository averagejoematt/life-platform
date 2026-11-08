// The Laboratory's words and figures (src/lib/laboratory.js, L1). Honesty first: a verdict, an effect or an interval
// is shown only as served; "insufficient data" and "not checked yet" are said when they are the truth.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  addDays,
  byPillar,
  daysBySide,
  findingText,
  intervalFigure,
  intervalText,
  labCounts,
  latestFindings,
  minEffectText,
  testDates,
  testSentence,
  verdictOf,
  weekWords,
  windowChart,
  windowChartOptions,
} from "../src/lib/laboratory.js";

const WWW = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const LAB = JSON.parse(readFileSync(join(WWW, "content", "fixtures", "lab.json"), "utf8"));
const SPEC = {
  condition_metric: "protein_g",
  condition_op: "<=",
  condition_threshold: 120,
  outcome_metric: "recovery",
  direction: "lower",
  lag_days: 1,
  min_effect: 6.82,
  min_effect_unit: "points",
  min_effect_kind: "personal_derivation",
  baseline_window_days: 30,
  baseline_n: 29,
  baseline_sd: 13.641,
};
const T = { id: "t", status: "pending", pre_registered: "2026-10-04", monitoring_window_days: 21, min_days_per_arm: 5, spec: SPEC };

test("the test sentence carries the frozen spec's words, threshold and lag", () => {
  assert.equal(testSentence(T), "On days with protein at or below 120 g, recovery score a day later is lower than on the other days.");
  assert.match(testSentence({ ...T, spec: { ...SPEC, condition_op: "median_split", condition_metric: "cardio_7d_min" } }), /more cardio over the past seven days than the window's median/);
  assert.match(testSentence({ ...T, spec: null, statement: "x" }), /^x$/);
});

test("the minimum effect says where its number came from", () => {
  assert.match(minEffectText(T), /^6\.82 points — set from his own day-to-day variation in the 30 days before/);
  assert.match(minEffectText({ ...T, spec: { ...SPEC, min_effect_kind: "population_constant" } }), /not derived from his data/);
  assert.equal(minEffectText({ ...T, spec: { ...SPEC, min_effect: null } }), "No minimum effect was served for this test.");
});

test("verdicts: served words only, and the honest reason when there is none", () => {
  assert.equal(verdictOf({ ...T, verdict: null }).word, "Not checked yet");
  const thin = verdictOf({ ...T, verdict: "inconclusive", n_condition: 3, n_comparison: 16 });
  assert.equal(thin.word, "Insufficient data");
  assert.equal(thin.reason, "3 days on the test side and 16 on the other; each needs 5.");
  // the engine serves 0 and 0 until it has two sides' worth of paired days: say that, not "0 days on the test side"
  const early = verdictOf({ ...T, verdict: "inconclusive", n_condition: 0, n_comparison: 0, days_observed: 5 });
  assert.equal(early.reason, "5 paired days so far; the check splits them only once there are 10 (5 a side).");
  assert.equal(verdictOf({ ...T, verdict: "inconclusive", n_condition: 14, n_comparison: 13, ci95_low: -10.7, ci95_high: 5.3 }).word, "Inconclusive");
  assert.equal(verdictOf({ ...T, verdict: "supported" }).word, "Supported");
  assert.equal(verdictOf({ ...T, verdict: "contradicted" }).word, "Contradicted");
  const retired = verdictOf({ ...T, status: "archived", verdict: "inconclusive", n_condition: 14, n_comparison: 13, ci95_low: -10.7, ci95_high: 5.3 });
  assert.equal(retired.word, "Retired");
  assert.match(retired.reason, /Last check: inconclusive/);
});

test("an interval is shown only when served — never invented", () => {
  assert.equal(intervalText(T), null);
  assert.equal(intervalFigure(T), null);
  const t = { ...T, effect_size: -1.396, ci95_low: -10.731, ci95_high: 5.291 };
  assert.equal(intervalText(t), "−1.4 points (95% interval −10.7 to +5.3)");
  const svg = intervalFigure(t, { width: 350 });
  assert.match(svg, /^<svg viewBox="0 0 350 84"/);
  assert.match(svg, /−6\.8 needed/);
});

test("the test's dates: baseline from the derivation window, window from the monitoring length", () => {
  assert.equal(addDays("2026-10-04", -30), "2026-09-04");
  assert.deepEqual(testDates(T), { baselineFrom: "2026-09-04", preRegistered: "2026-10-04", windowEnd: "2026-10-25" });
  assert.equal(testDates({ ...T, pre_registered: null }), null);
});

const SERIES = {
  unit: "g",
  decimals: 0,
  days: [
    { date: "2026-10-02", value: 150, present: true, gap: false },
    { date: "2026-10-04", value: 110, present: true, gap: false },
    { date: "2026-10-05", value: 130, present: true, gap: false },
    { date: "2026-10-06", value: null, present: false, gap: false },
  ],
};

test("days by side: the served reading against the PRE-REGISTERED line, from the day the test was written", () => {
  assert.deepEqual(
    daysBySide(T, SERIES).map((d) => [d.date, d.side]),
    [
      ["2026-10-04", "test"],
      ["2026-10-05", "other"],
      ["2026-10-06", null],
    ],
  );
  assert.ok(daysBySide({ ...T, spec: { ...SPEC, condition_op: "median_split" } }, SERIES).every((d) => d.side === null), "no served median → no side");
});

test("the window chart: inspectable points, the test's day marked, a phone viewBox that follows the container (11 px floor)", () => {
  const o = windowChartOptions(T, SERIES, "condition");
  assert.equal(o.dashed, 120);
  assert.deepEqual(
    o.markers.map((m) => m.label),
    ["test written"],
  );
  const desk = windowChart(o);
  assert.match(desk, /data-points="/);
  assert.match(desk, /viewBox="0 0 1000 220"/);
  const phone = windowChart(o, { mobile: true, width: 342 });
  assert.match(phone, /viewBox="0 0 342 220"/);
  // every SVG text at the phone width is at least 11 px when the viewBox equals the container width
  const sizes = [...phone.matchAll(/font-size="([\d.]+)"/g)].map((m) => Number(m[1]));
  assert.ok(sizes.length && sizes.every((s) => s >= 11), `sizes ${sizes}`);
  // ISO dates never reach the visible labels
  const visible = phone.replace(/data-points="[^"]*"/, "").replace(/<[^>]+>/g, " ");
  assert.doesNotMatch(visible, /\d{4}-\d{2}-\d{2}/);
  assert.equal(windowChartOptions(T, null), null);
  assert.equal(windowChartOptions(T, { days: [{ date: "2026-10-04", value: null, present: false, gap: false }] }), null, "no reading → the page says so");
});

test("findings: the newest week, in words, with how many weeks listed the pair", () => {
  const { week, items, weeks } = latestFindings(LAB.lab_findings);
  assert.ok(week && items.length && weeks >= 1);
  assert.ok(items.every((f) => f.week === week && f.seen >= 1 && f.seen <= weeks));
  const s = findingText({ metric_a: "HRV", metric_b: "Recovery", r: 0.65, ci95_low: 0.458, ci95_high: 0.78, n: 90, n_eff: 53.7 });
  assert.equal(s, "HRV and Recovery moved together: r = +0.65 (95% interval +0.46 to +0.78), about 54 independent days of 90.");
  assert.match(findingText({ metric_a: "Resting HR", metric_b: "Recovery", r: -0.67, n: 90 }), /moved in opposite directions/);
  assert.equal(weekWords("2026-W45"), "the week of 2 November 2026");
});

test("counts and groups are counts of the served rows", () => {
  const c = labCounts(LAB);
  assert.equal(c.running + c.ready + c.backlog + c.done, LAB.lab_experiments.length);
  assert.equal(c.testsOpen + c.testsRetired, LAB.lab_tests.length);
  const g = byPillar(LAB.lab_experiments);
  assert.equal(
    g.reduce((s, x) => s + x.items.length, 0),
    LAB.lab_experiments.length,
  );
});

test("the fixture carries no private read and no reader-write field", () => {
  const text = JSON.stringify(LAB);
  assert.doesNotMatch(text, /"votes"|"matthew_note"|"reflection"/);
  const subjects = JSON.stringify([
    LAB.lab_experiments.map((x) => [x.name, x.hypothesis, x.tags]),
    LAB.lab_findings.map((f) => [f.metric_a, f.metric_b]),
    LAB.lab_protocols.groups.map((g) => g.items.map((i) => [i.name, i.why])),
  ]);
  assert.doesNotMatch(subjects, /\b(mood|journal(?:ing)?|state of mind|diary|gratitude)\b/i);
});
