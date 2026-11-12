// Findings over time (src/lib/laboratory.js findingsOverTime, stabilitySummary, stabilityFigure; page
// src/lab/lab-findings.astro). Honesty: "held in N of N weeks" only when the pair was listed every week and every
// interval sat on one side of zero; otherwise the line says what happened. Privacy: a finding naming the day grade or
// habit completion renders only with its public method's stamp — a week computed under the private-by-inference method
// is never drawn, listed or counted (owner rulings 2026-11-03/05/06). The privacy test carries a must-fail control.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { findingIsPublic, findingsOverTime, latestFindings, stabilityFigure, stabilitySummary, weekWords } from "../src/lib/laboratory.js";

const WWW = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const LAB = JSON.parse(readFileSync(join(WWW, "content", "fixtures", "lab.json"), "utf8"));
const DG = { day_grade: "day-grade-public-v1" };
const HP = { habit_pct: "habit-pct-public-v1" };

const f = (week, a, b, r, lo, hi, methods = {}) => ({ id: `${week}-${a}-${b}`, week, metric_a: a, metric_b: b, r, ci95_low: lo, ci95_high: hi, n: 90, n_eff: 50, methods });
const pairOf = (rows) => findingsOverTime(rows).pairs[0];

test("held is claimed only when every week was listed and every interval cleared zero", () => {
  const rows = ["2026-W42", "2026-W43", "2026-W44", "2026-W45"].map((w, i) => f(w, "HRV", "Recovery", 0.7 - i * 0.01, 0.5, 0.8));
  const p = pairOf(rows);
  assert.equal(p.summary.key, "held");
  assert.equal(p.summary.text, "Held in 4 of 4 weeks: r from +0.67 to +0.70, every week's 95% interval clear of zero.");
  // one interval reaching zero: no "held"
  const crossed = rows.map((x, i) => (i === 2 ? { ...x, ci95_low: -0.02 } : x));
  const q = pairOf(crossed);
  assert.equal(q.summary.key, "reached");
  assert.match(q.summary.text, /^Listed in 4 of 4 weeks; its interval reached zero in the week of 26 Oct\.$/);
  // a missing interval is not "clear of zero" either
  assert.equal(pairOf(rows.map((x, i) => (i === 0 ? { ...x, ci95_low: null } : x))).summary.key, "reached");
  // a week not listed: said, with the weeks named
  // (the week exists — another pair was listed in it — but this pair was not)
  const gap = findingsOverTime([...rows.filter((x) => x.week !== "2026-W43"), f("2026-W43", "Steps", "HRV", 0.3, 0.1, 0.5)]).pairs.find((p) => p.metric_a === "HRV");
  assert.equal(gap.summary.key, "partial");
  assert.equal(gap.summary.text, "Listed in 3 of 4 weeks; not listed in the week of 19 Oct; clear of zero each week it was listed (r from +0.67 to +0.70).");
  // a change of direction is never "held", even with every interval clear of zero
  const flip = pairOf(rows.map((x, i) => (i === 3 ? { ...x, r: -0.4, ci95_low: -0.6, ci95_high: -0.1 } : x)));
  assert.equal(flip.summary.key, "flipped");
  assert.match(flip.summary.text, /^Changed direction/);
});

test("a pair listed once is not a recurring pair; the fixture's recurring pairs are worded", () => {
  const o = findingsOverTime([f("2026-W44", "HRV", "Recovery", 0.7, 0.5, 0.8), f("2026-W45", "Steps", "HRV", 0.3, 0.1, 0.5)]);
  assert.equal(o.pairs.length, 0);
  const fx = findingsOverTime(LAB.lab_findings);
  assert.ok(fx.weeks.length >= 2 && fx.pairs.length >= 2);
  for (const p of fx.pairs) {
    assert.ok(p.listed >= 2 && p.listed <= p.weeks.length);
    const listed = p.weeks.filter((w) => w.finding).map((w) => w.finding);
    if (p.summary.key === "held") {
      assert.equal(listed.length, p.weeks.length);
      assert.ok(listed.every((x) => x.ci95_low > 0 || x.ci95_high < 0));
    }
  }
  const hrv = fx.pairs.find((p) => p.metric_a === "HRV" && p.metric_b === "Recovery");
  assert.equal(hrv.summary.key, "held");
  assert.equal(stabilitySummary(hrv).text, hrv.summary.text);
});

test("the small multiple: one fixed −1..+1 axis, a point per week, the viewBox at the width it was given", () => {
  const p = findingsOverTime(LAB.lab_findings).pairs[0];
  for (const width of [340, 358, 1000]) {
    const svg = stabilityFigure(p, { width });
    assert.match(svg, new RegExp(`viewBox="0 0 ${width} 168"`));
    const pts = JSON.parse(svg.match(/data-points="([^"]+)"/)[1].replace(/&quot;/g, '"').replace(/&amp;/g, "&"));
    assert.equal(pts.length, p.weeks.length);
    assert.ok(pts.every((q) => q.x >= 0 && q.x <= width && /^Week of /.test(q.label)));
    assert.match(svg, />\+1</);
    assert.match(svg, />−1</);
    assert.doesNotMatch(svg, /\d{4}-\d{2}-\d{2}/, "an ISO date on a page is a defect");
  }
  assert.equal(weekWords("2026-W45", { short: true }), "week of 2 Nov");
});

// ── privacy ───────────────────────────────────────────────────────────────────────────────────

// What /api/discoveries served for W42–W44 before the fix: Day Grade and Habit Completion pairs from records with no
// public method stamp (the METHOD-1 day grade, journal component included; habit_pct over the journal habits). Their r
// values are sentinels here so a leak is visible in any rendered string.
const PRIVATE = [
  f("2026-W42", "readiness", "Day Grade", 0.913, 0.871, 0.951),
  f("2026-W43", "readiness", "Day Grade", 0.917, 0.873, 0.953),
  f("2026-W44", "Calories", "Day Grade", 0.919, 0.875, 0.957, { day_grade: "method-1" }),
  f("2026-W43", "Habit Completion", "Recovery", 0.923, 0.877, 0.959),
  f("2026-W44", "Habit Completion", "Recovery", 0.929, 0.879, 0.961),
  f("2026-W44", "Day grade", "Habits completed", 0.931, 0.881, 0.963, {}), // relabelled: still method-versioned
];
const PUBLIC = [
  ...["2026-W42", "2026-W43", "2026-W44", "2026-W45"].map((w) => f(w, "HRV", "Recovery", 0.68, 0.5, 0.8)),
  f("2026-W45", "readiness", "Day Grade", 0.44, 0.12, 0.68, DG),
  f("2026-W46", "readiness", "Day Grade", 0.46, 0.14, 0.7, DG),
  f("2026-W45", "Habit Completion", "Recovery", 0.51, 0.19, 0.73, HP),
  f("2026-W46", "Habit Completion", "Recovery", 0.5, 0.18, 0.72, HP),
];
const SENTINELS = /0\.9[1-3]\d?|\+0\.9[1-3]|0\.8[7-8]\d|0\.9[5-6]\d/;

/** Everything the Lab renders from a set of findings: the index's newest week, the over-time pairs, their figures. */
function rendered(rows) {
  const over = findingsOverTime(rows);
  const latest = latestFindings(rows);
  return JSON.stringify({
    latest: latest.items.map((x) => [x.metric_a, x.metric_b, x.r, x.ci95_low, x.ci95_high, x.seen, x.of]),
    pairs: over.pairs.map((p) => [p.metric_a, p.metric_b, p.summary.text, p.weeks.map((w) => [w.week, w.finding && w.finding.r]), stabilityFigure(p)]),
  });
}

/** The leak detector: a private sentinel reached the page, or a method-versioned pair counted a pre-method week. */
function leaks(rows) {
  const out = [];
  const text = rendered(rows);
  if (SENTINELS.test(text)) out.push("a private-method r or interval rendered");
  for (const p of findingsOverTime(rows).pairs)
    if (/grade|habit/i.test(`${p.metric_a} ${p.metric_b}`) && p.weeks.some((w) => w.week < "2026-W45")) out.push(`${p.key} counted a pre-method week`);
  for (const x of latestFindings(rows).items) if (/grade|habit/i.test(`${x.metric_a} ${x.metric_b}`) && x.of > 2) out.push(`${x.metric_a}|${x.metric_b} listed of ${x.of}`);
  return out;
}

test("no day-grade or habit pair from a pre-method week renders, and nothing counts it", () => {
  const rows = [...PUBLIC, ...PRIVATE];
  assert.deepEqual(leaks(rows), []);
  assert.ok(PRIVATE.every((x) => !findingIsPublic(x)));
  assert.ok(PUBLIC.every((x) => findingIsPublic(x)));
  const over = findingsOverTime(rows);
  const dg = over.pairs.find((p) => p.metric_b === "Day Grade");
  assert.deepEqual(
    dg.weeks.map((w) => w.week),
    ["2026-W45", "2026-W46"],
    "the day grade pair is counted from its first stamped week",
  );
  assert.equal(dg.summary.text, "Held in 2 of 2 weeks: r from +0.44 to +0.46, every week's 95% interval clear of zero.");
  const latest = latestFindings(rows).items.find((x) => x.metric_b === "Day Grade");
  assert.equal(latest.of, 2);
});

test("the control: the detector reds when the private rows carry a forged stamp (the guard bypassed)", () => {
  const forged = PRIVATE.map((x) => ({ ...x, methods: { ...DG, ...HP } }));
  const found = leaks([...PUBLIC, ...forged]);
  assert.ok(found.length >= 2, `the detector must see the bypass: ${JSON.stringify(found)}`);
  assert.ok(found.some((m) => /private-method r/.test(m)));
  assert.ok(found.some((m) => /pre-method week/.test(m)));
});
