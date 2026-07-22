// tests/js/charts.test.mjs — unit tests for site/assets/js/charts.js's pure
// functions (#1431, the first front-end unit-test tranche). charts.js is
// shared across ~40 pages (weight/vitals/nutrition/training/etc.) with, until
// this harness, zero test coverage — only `node --check` / the #1432 import-
// graph gate, neither of which verifies BEHAVIOR (a chart can parse clean and
// still draw a lying or malformed trend). These exercise the actual SVG/HTML
// output for representative inputs, with particular attention to the >=4-
// points-to-draw-a-real-trend rule that's a deliberate honesty guarantee
// (see charts.js's own comment on lineChart/arcTrend/weightTrendChart/
// dualLineChart — 2-3 points draw a misleading straight diagonal, so those
// charts refuse and show an honest count instead).
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

// charts.js statically imports "/assets/js/svgtype.js" for a side effect
// (the SVG legibility-floor scaler). That's a root-relative specifier the
// site_js_loader.mjs hook rewrites — but Node resolves an entire STATIC
// import graph before evaluating any of it, so a top-level `import … from
// "…/charts.js"` in this file would try to resolve svgtype.js before the
// hook registered by "./support/loader.mjs" (above) has taken effect. A
// dynamic `import()`, evaluated at runtime after that registration has
// already run, resolves correctly — the same reason
// scripts/import_site_js_graph.mjs uses `await import()` in a loop rather
// than static imports.
const {
  dualWeight,
  lineChart,
  arcTrend,
  weightTrendChart,
  confLevel,
  nDots,
  ciWhisker,
  dualLineChart,
  sparkline,
  stackedBar,
} = await import("../../site/assets/js/charts.js");

test("dualWeight — always lb-first, converts from the native unit", () => {
  assert.equal(dualWeight(100, "kg"), "220.5 lb · 100 kg");
  assert.equal(dualWeight(100, "lb"), "100 lb · 45.4 kg");
});

test("dualWeight — non-finite input renders the honest em-dash, never NaN", () => {
  assert.equal(dualWeight("not-a-number"), "—");
  assert.equal(dualWeight(undefined), "—");
});

test("lineChart — fewer than 4 points refuses the trend line, shows an honest count", () => {
  const zero = lineChart([], { unit: "kg" });
  assert.match(zero, /chart--empty/);
  assert.match(zero, /Fills as readings accrue/);

  const two = lineChart([1, 2], { unit: "kg" });
  assert.match(two, /chart--empty/);
  assert.match(two, /2 readings so far — the trend line draws in at 4\+/);
  // no <svg> at all below the 4-point floor — this must never draw a fake line.
  assert.doesNotMatch(two, /<svg/);
});

test("lineChart — exactly 3 points is still refused (the floor is >=4, not >3)", () => {
  const three = lineChart([1, 2, 3], { unit: "kg" });
  assert.match(three, /chart--empty/);
  assert.match(three, /3 readings so far/);
});

test("lineChart — 4+ points draws a real SVG trend with the right point count", () => {
  const pts = [
    { date: "2026-01-01", value: 1 },
    { date: "2026-01-02", value: 2 },
    { date: "2026-01-03", value: 3 },
    { date: "2026-01-04", value: 4 },
  ];
  const out = lineChart(pts, { unit: "kg", label: "Weight" });
  assert.match(out, /<svg/);
  assert.match(out, /class="chart-line"/);
  assert.match(out, /4 pts<\/figcaption>/);
  assert.match(out, /trending up/);
  assert.match(out, /Jan 1–Jan 4/);
});

test("lineChart — a flat series reads as 'holding flat', not up or down", () => {
  const pts = [1, 1, 1, 1].map((v, i) => ({ date: `2026-01-0${i + 1}`, value: v }));
  const out = lineChart(pts, { unit: "kg" });
  assert.match(out, /holding flat/);
});

test("lineChart — #1618 a projection draws a DASHED segment + labels the estimate in the caption", () => {
  const pts = [1, 2, 3, 4, 5].map((v, i) => ({ date: `2026-07-0${i + 1}`, value: v }));
  const out = lineChart(pts, {
    valueKey: "value", dateKey: "date", label: "month-to-date spend", goal: 8,
    projection: { value: 12, date: "2026-07-31", label: "projected" },
  });
  // Solid actual line AND the dashed projection segment both present.
  assert.match(out, /class="chart-line"/);
  assert.match(out, /class="chart-proj"/);
  assert.match(out, /class="chart-proj-dot"/);
  // The caption names the estimate — legible without a legend, and honest about being a forecast.
  assert.match(out, /dashed = projected \$12 by month-end \(governor estimate\)/);
  // The projected value (12) sits ABOVE the goal (8) and above every actual (max 5), so it must
  // widen the y-domain — otherwise the ceiling crossing would fall out of frame (AC3).
  assert.match(out, /projected 12 by month-end \(estimate\)/); // aria summary carries it too
});

test("lineChart — #1618 no projection (absent value) draws ONLY the solid line, no phantom dash", () => {
  const pts = [1, 2, 3, 4, 5].map((v, i) => ({ date: `2026-07-0${i + 1}`, value: v }));
  const noProj = lineChart(pts, { valueKey: "value", dateKey: "date", label: "spend", goal: 8 });
  assert.match(noProj, /class="chart-line"/);
  assert.doesNotMatch(noProj, /chart-proj/);
  // A null projection object is treated the same as absent — no dashed segment.
  const nullProj = lineChart(pts, { valueKey: "value", dateKey: "date", goal: 8, projection: null });
  assert.doesNotMatch(nullProj, /chart-proj/);
  // A projection whose date is not after the last actual date can't be positioned honestly → skipped.
  const pastProj = lineChart(pts, { valueKey: "value", dateKey: "date", goal: 8, projection: { value: 12, date: "2026-07-05" } });
  assert.doesNotMatch(pastProj, /chart-proj/);
  // A non-finite projection value is ignored, not rendered as NaN.
  const badProj = lineChart(pts, { valueKey: "value", dateKey: "date", goal: 8, projection: { value: "nope", date: "2026-07-31" } });
  assert.doesNotMatch(badProj, /chart-proj/);
});

test("arcTrend — fewer than 4 valid dated points refuses, invalid dates are dropped first", () => {
  const out = arcTrend([{ date: "2026-01-01", value: 1 }, { date: "not-a-date", value: 2 }, { date: "2026-01-02", value: 3 }], { unit: "bpm" });
  assert.match(out, /chart--empty/);
  assert.match(out, /2 readings so far/); // the bad-date row was filtered out
});

test("weightTrendChart — fewer than 4 weigh-ins refuses with a weigh-in count", () => {
  const out = weightTrendChart([{ date: "2026-01-01", weight_lbs: 180 }]);
  assert.match(out, /chart--empty/);
  assert.match(out, /1 weigh-in so far/);
});

test("weightTrendChart — 4+ weigh-ins draws the trend + honors the goal-never-anchors-axis rule", () => {
  const readings = [
    { date: "2026-01-01", weight_lbs: 190 },
    { date: "2026-01-08", weight_lbs: 188 },
    { date: "2026-01-15", weight_lbs: 186 },
    { date: "2026-01-22", weight_lbs: 184 },
  ];
  const out = weightTrendChart(readings, { goal: 150 });
  assert.match(out, /<svg/);
  // goal 150 is far outside the weigh-in range (184-190) — HARD RULE 4 says the
  // goal must never become the axis floor, so data-wt-min must stay near the
  // real data, not collapse toward 150.
  const min = Number(/data-wt-min="([\d.]+)"/.exec(out)[1]);
  assert.ok(min > 170, `axis min ${min} should track the real weigh-ins, not the distant goal`);
  assert.match(out, /goal 150 lb/);
});

test("confLevel — ciWidthFrac dominates when supplied (tighter band = higher confidence)", () => {
  assert.equal(confLevel({ ciWidthFrac: 0.3 }).level, "high");
  assert.equal(confLevel({ ciWidthFrac: 0.8 }).level, "medium");
  assert.equal(confLevel({ ciWidthFrac: 1.5 }).level, "low");
});

test("confLevel — provisional always reads low regardless of n/confidence", () => {
  assert.deepEqual(confLevel({ provisional: true, n: 999, confidence: 0.99 }), { level: "low", cls: "cf-low" });
});

test("confLevel — n thresholds (>=21 high, >=8 medium, else low)", () => {
  assert.equal(confLevel({ n: 25 }).level, "high");
  assert.equal(confLevel({ n: 10 }).level, "medium");
  assert.equal(confLevel({ n: 2 }).level, "low");
});

test("confLevel — a null confidence must not read as 0 (Number(null) === 0 trap)", () => {
  // Regression guard (#421 QA, per the code comment): confidence=null used to
  // fall through Number(null)=0 and render an invisible cf-low band.
  assert.equal(confLevel({ confidence: null }).level, "medium");
});

test("nDots — n=0 renders the honest empty state, never a fake dot", () => {
  const out = nDots(0);
  assert.match(out, /ndots--none/);
  assert.match(out, />n=0</);
});

test("nDots — dot count is capped, overflow becomes a '+N' badge", () => {
  const out = nDots(15, { cap: 12 });
  assert.equal((out.match(/<i class="ndot">/g) || []).length, 12);
  assert.match(out, /\+3</);
  assert.match(out, />n=15</);
});

test("ciWhisker — no finite interval renders the point alone, never an invented band", () => {
  const out = ciWhisker(3, null, null, { unit: "lb" });
  assert.doesNotMatch(out, /ciw-band/);
  assert.match(out, /no interval yet/);
});

test("ciWhisker — a real interval crossing zero is called out honestly", () => {
  const out = ciWhisker(3, -1, 5, { unit: "lb", confidence: 0.8 });
  assert.match(out, /class="ciw-band/);
  assert.match(out, /crosses zero/);
});

test("ciWhisker — a non-finite value falls back to the empty-figure caption", () => {
  const out = ciWhisker("not-a-number", 1, 2, {});
  assert.match(out, /chart--empty/);
});

test("dualLineChart — either series under 4 points refuses (no misleading two-point diagonal)", () => {
  const A = [{ date: "2026-01-01", value: 1 }, { date: "2026-01-02", value: 2 }];
  const B = [1, 2, 3, 4].map((v, i) => ({ date: `2026-01-0${i + 1}`, value: v }));
  const out = dualLineChart(A, B);
  assert.match(out, /chart--empty/);
});

test("dualLineChart — both series 4+ draws both lines and reports the real gap", () => {
  const A = [10, 11, 12, 13].map((v, i) => ({ date: `2026-01-0${i + 1}`, value: v }));
  const B = [8, 8, 8, 8].map((v, i) => ({ date: `2026-01-0${i + 1}`, value: v }));
  const out = dualLineChart(A, B, { aLabel: "Actual", bLabel: "Projected", unit: "kg" });
  assert.match(out, /class="chart-line"/); // series A
  assert.match(out, /class="chart-down"/); // series B
  assert.match(out, /gap 5kg/); // 13 - 8
});

test("sparkline — fewer than 2 points renders the empty span, no <svg>", () => {
  assert.equal(sparkline([]), '<span class="spark spark--empty"></span>');
  assert.equal(sparkline([5]), '<span class="spark spark--empty"></span>');
});

test("sparkline — 2+ points draws a path", () => {
  const out = sparkline([1, 3, 2, 5]);
  assert.match(out, /<svg class="spark"/);
  assert.match(out, /class="chart-line"/);
});

test("stackedBar — an all-zero/empty segment set renders the honest 'no data' state", () => {
  assert.match(stackedBar([]), /No data yet/);
  assert.match(stackedBar([{ label: "P", value: 0 }]), /No data yet/);
});

test("stackedBar — segment widths are computed as a true percentage of the total", () => {
  const out = stackedBar([
    { label: "Protein", value: 100, tone: "ember" },
    { label: "Carbs", value: 100, tone: "ink" },
  ]);
  assert.match(out, /width:50\.0%/);
  assert.match(out, /Protein 100g · 50%/);
  assert.match(out, /Carbs 100g · 50%/);
});
