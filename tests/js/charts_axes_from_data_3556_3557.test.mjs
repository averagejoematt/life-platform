// tests/js/charts_axes_from_data_3556_3557.test.mjs — the two halves of ONE rule
// for site/assets/js/charts.js:
//
//   A chart's DOMAIN comes from the data it plots; an annotation is drawn onto
//   that domain, never folded into it. A point's X comes from its own VALUE
//   (its date), never from its index in an array.
//
// #3556: lineChart put `goal` into min/max, so the results door's weight chart
// (goal 185 under a ~324 lb series) rescaled the real weigh-ins against a number
// they never touched — 114px of slope collapsed to 1.8px — AND moved the `dir`
// verdict's flat threshold with it, so the results door printed "holding flat"
// for the same 2.25 lb loss the story page (which passes no goal) called
// "trending down". weightTrendChart has forbidden this since P0.1 ("HARD RULE 4:
// the goal NEVER anchors the y-axis"); this generalises the rule to every
// lineChart caller.
//
// #3557: dualLineChart index-positioned each series over its OWN length
// (x = i/(arr.length − 1)), so two series of different lengths were stretched
// across the same span: the same calendar day landed at two different x, and
// both lines ran to the right edge however early one of them stopped. The
// nutrition reconciliation (projected vs actual loss) and the strain-vs-recovery
// overlay are structurally unequal in length — the API emits a projected value
// every logged day but an actual only on weigh-in days — so the comparison those
// charts exist to draw was not comparing like with like.
//
// Every positive assertion below is paired with a NEGATIVE CONTROL: the same
// assertion is re-run against a mutant module built by patching the exact
// pre-fix line back into charts.js, and MUST fail there. A guard that cannot
// fail is not a guard (the standing rule after #3200/#2116).
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const CHARTS_URL = new URL("../../site/assets/js/charts.js", import.meta.url);
const SRC = fs.readFileSync(CHARTS_URL, "utf8");

const { lineChart, dualLineChart } = await import("../../site/assets/js/charts.js");

// Build a mutant of charts.js with `from` replaced by `to`, and import it. The
// replacement is asserted to have applied, so a refactor that renames the line
// breaks the negative control loudly instead of silently making it vacuous.
// The svgtype side-effect import is stripped (the mutant is loaded from a temp
// dir by file URL, outside the root-relative loader hook's reach).
let _mutantN = 0;
async function mutant(...pairs) {
  let src = SRC;
  for (const [from, to] of pairs) {
    assert.ok(src.includes(from), `negative-control anchor not found in charts.js:\n${from}`);
    src = src.replace(from, to);
  }
  src = src.replace(/^import "\/assets\/js\/svgtype\.js";$/m, "");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "charts-mutant-"));
  const f = path.join(dir, `charts_mutant_${_mutantN++}.mjs`);
  fs.writeFileSync(f, src);
  return await import(`file://${f}`);
}

const dOf = (svg, cls) => {
  const m = new RegExp(`class="${cls}[^"]*"[^>]*d="([^"]+)"`).exec(svg);
  assert.ok(m, `no path with class ${cls} in output`);
  return m[1];
};
const xsOf = (d) => (d.match(/[ML](-?[\d.]+) /g) || []).map((s) => Number(s.slice(1)));
const ysOf = (d) => (d.match(/[ML]-?[\d.]+ (-?[\d.]+)/g) || []).map((s) => Number(s.split(" ")[1]));
const ariaOf = (svg) => (/aria-label="([^"]+)"/.exec(svg) || [])[1];
const capOf = (svg) => (/<figcaption[^>]*>([\s\S]*?)<\/figcaption>/.exec(svg) || [])[1];

// The issue's own fixture: 10 weigh-ins, 324.6 → 322.35 (a real 2.25 lb loss).
const WEIGH_INS = [...Array(10)].map((_, i) => ({
  date: `2026-09-${String(5 + i).padStart(2, "0")}`,
  weight_lbs: 324.6 - 0.25 * i,
}));
// The two live call sites, verbatim in shape: evidence_intelligence.js (results
// door, passes the goal) and story.js (the story page, passes none).
const RESULTS_DOOR = { valueKey: "weight_lbs", goal: 185, unit: " lb", label: "Weight · recent readings" };
const STORY_PAGE = { valueKey: "weight_lbs", unit: " lb", label: "Weight · recent readings" };

// ── #3556 · the domain comes from the series ──────────────────────────────────

test("#3556 lineChart — the y-domain is IDENTICAL with and without a goal", () => {
  const withGoal = lineChart(WEIGH_INS, RESULTS_DOOR);
  const without = lineChart(WEIGH_INS, STORY_PAGE);
  // Same domain ⇒ byte-identical data path. (Not merely "similar": the series is
  // plotted from the same numbers, so any difference at all is the goal leaking in.)
  assert.equal(dOf(withGoal, "chart-line"), dOf(without, "chart-line"));
  // And the slope is the real one: the full drawable height, not 1.8px of it.
  const ys = ysOf(dOf(withGoal, "chart-line"));
  assert.ok(Math.max(...ys) - Math.min(...ys) > 100, `y-span ${Math.max(...ys) - Math.min(...ys)}px — the goal is still flattening the series`);
});

test("#3556 lineChart — a goal ABOVE the data cannot widen the domain either (the live spend curve)", () => {
  // /api/receipts, 2026-09-05: 5 days of month-to-date spend under a $252 ceiling.
  const spend = [["2026-09-01", 0.69], ["2026-09-02", 4.31], ["2026-09-03", 8.65], ["2026-09-04", 11.77], ["2026-09-05", 13.8]]
    .map(([date, mtd_usd]) => ({ date, mtd_usd }));
  const opts = { valueKey: "mtd_usd", dateKey: "date", label: "month-to-date spend" };
  assert.equal(dOf(lineChart(spend, { ...opts, goal: 252 }), "chart-line"), dOf(lineChart(spend, opts), "chart-line"));
});

test("#3556 lineChart — the dir verdict is read off the DATA's range, so both doors agree", () => {
  const results = lineChart(WEIGH_INS, RESULTS_DOOR);
  const story = lineChart(WEIGH_INS, STORY_PAGE);
  assert.match(ariaOf(results), /trending down/);
  assert.match(ariaOf(story), /trending down/);
  assert.doesNotMatch(ariaOf(results), /holding flat/);
});

test("#3556 lineChart — a PLOTTED projection still widens the domain (it is data, not an annotation)", () => {
  const pts = [1, 2, 3, 4, 5].map((v, i) => ({ date: `2026-07-0${i + 1}`, value: v }));
  const proj = lineChart(pts, { projection: { value: 40, date: "2026-07-31" } });
  const plain = lineChart(pts, {});
  assert.match(proj, /class="chart-proj"/);
  // The dashed segment is drawn out to 40, so 40 must be in frame — the projected
  // dot's cy has to sit inside the viewBox, and the actual line compresses.
  const cy = Number(/class="chart-proj-dot"[^>]*cy="([\d.]+)"/.exec(proj)[1]);
  assert.ok(cy >= 0 && cy <= 130, `projected dot cy ${cy} is out of frame`);
  assert.notEqual(dOf(proj, "chart-line"), dOf(plain, "chart-line"));
});

test("#3556 lineChart — an off-domain goal stays VISIBLE, pinned outside the plot area and named as off-scale", () => {
  const out = lineChart(WEIGH_INS, RESULTS_DOOR);
  // Still drawn — the annotation's job is to be seen; it is just not the axis.
  assert.match(out, /class="chart-goal chart-goal--off"/);
  const gy = Number(/class="chart-goal chart-goal--off"[^>]*y1="([\d.]+)"/.exec(out)[1]);
  // Pinned to the margin band BELOW the padded plot area (P = 8, H = 130), so it
  // cannot be misread as a value sitting on the scale.
  assert.ok(gy > 122, `off-scale goal at y=${gy} is inside the plot area`);
  // ...and both the caption and the screen-reader summary say so, with the real distance.
  assert.match(capOf(out), /goal 185 lb — off scale, 137\.4 lb below the plotted range \(annotation, not the axis\)/);
  assert.match(ariaOf(out), /goal 185 lb — off scale, 137\.4 lb below the plotted range/);
  // The axis is never truncated to make room: the first and last weigh-ins still
  // sit at the top and bottom of the drawable band.
  const ys = ysOf(dOf(out, "chart-line"));
  assert.equal(Math.min(...ys), 8);
  assert.equal(Math.max(...ys), 122);
});

test("#3556 lineChart — an IN-domain goal is unchanged: drawn at its true y, not flagged off-scale", () => {
  const pts = [10, 12, 14, 16].map((v, i) => ({ date: `2026-01-0${i + 1}`, value: v }));
  const out = lineChart(pts, { goal: 13, unit: "kg" });
  assert.match(out, /class="chart-goal"/);
  assert.doesNotMatch(out, /chart-goal--off/);
  const gy = Number(/class="chart-goal"[^>]*y1="([\d.]+)"/.exec(out)[1]);
  assert.ok(gy > 8 && gy < 122, `in-domain goal should sit inside the plot area, got y=${gy}`);
  assert.doesNotMatch(capOf(out), /off scale/);
});

test("#3556 lineChart — the goal never touches the hover readout's coordinates", () => {
  const cp = (svg) => /data-cpts="([^"]+)"/.exec(svg)[1];
  assert.equal(cp(lineChart(WEIGH_INS, RESULTS_DOOR)), cp(lineChart(WEIGH_INS, STORY_PAGE)));
});

test("#3556 NEGATIVE CONTROL — re-folding the goal into the domain reds the domain assertion", async () => {
  const m = await mutant([
    "  const vals = dvals.concat(projActive ? [projVal] : []);",
    "  const vals = dvals.concat(goal != null ? [Number(goal)] : []).concat(projActive ? [projVal] : []);",
  ]);
  // Same two call sites, same fixture — the mutant must diverge, and must revive
  // the exact symptom the issue reported.
  assert.notEqual(dOf(m.lineChart(WEIGH_INS, RESULTS_DOOR), "chart-line"), dOf(m.lineChart(WEIGH_INS, STORY_PAGE), "chart-line"));
  assert.throws(() => {
    assert.equal(dOf(m.lineChart(WEIGH_INS, RESULTS_DOOR), "chart-line"), dOf(m.lineChart(WEIGH_INS, STORY_PAGE), "chart-line"));
  }, /Expected values to be strictly equal/);
  const ys = ysOf(dOf(m.lineChart(WEIGH_INS, RESULTS_DOOR), "chart-line"));
  assert.ok(Math.max(...ys) - Math.min(...ys) < 10, "the mutant should flatten the series against the goal");
});

test("#3556 NEGATIVE CONTROL — a dir threshold read off the goal-widened domain reds the verdict assertion", async () => {
  const DOMAIN = [
    "  const vals = dvals.concat(projActive ? [projVal] : []);",
    "  const vals = dvals.concat(goal != null ? [Number(goal)] : []).concat(projActive ? [projVal] : []);",
  ];
  const THRESHOLD = [
    "  const dir = Math.abs(delta) <= (dataMax - dataMin) * 0.02 ? \"holding flat\"",
    "  const dir = Math.abs(delta) < (max - min) * 0.02 ? \"holding flat\"",
  ];
  // The threshold mutation alone is harmless while the domain is clean (max−min is
  // then the data's own range) — it only lies once the goal is back in the domain.
  // Both together are the pre-fix code, and they reproduce the reported symptom
  // exactly: the results door prints "holding flat" over a real 2.25 lb loss.
  assert.match(ariaOf((await mutant(THRESHOLD)).lineChart(WEIGH_INS, RESULTS_DOOR)), /trending down/);
  const pre = await mutant(DOMAIN, THRESHOLD);
  assert.match(ariaOf(pre.lineChart(WEIGH_INS, RESULTS_DOOR)), /holding flat/);
  assert.match(ariaOf(pre.lineChart(WEIGH_INS, STORY_PAGE)), /trending down/); // the two doors disagree
  assert.throws(() => assert.match(ariaOf(pre.lineChart(WEIGH_INS, RESULTS_DOOR)), /trending down/));
});

// ── #3557 · the x comes from the point's own date ────────────────────────────

// 20 daily projected points vs 10 every-other-day actuals — the issue's fixture,
// and the real shape of /api/nutrition's reconciliation days.
const PROJECTED = [...Array(20)].map((_, i) => ({ date: `2026-09-${String(5 + i).padStart(2, "0")}`, value: 0.3 * (i + 1) }));
const ACTUAL = [...Array(10)].map((_, i) => ({ date: `2026-09-${String(5 + 2 * i).padStart(2, "0")}`, value: 0.25 * (2 * i + 1) }));
const DUAL_OPTS = { aLabel: "projected (energy balance)", bLabel: "actual (scale)", unit: " lb", label: "cumulative loss" };

function xByDate(svg, series, cls) {
  const xs = xsOf(dOf(svg, cls));
  assert.equal(xs.length, series.length, `path point count ${xs.length} != series length ${series.length}`);
  return new Map(series.map((p, i) => [p.date, xs[i]]));
}

test("#3557 dualLineChart — two series sharing a date share an x, within 0.1px", () => {
  const out = dualLineChart(PROJECTED, ACTUAL, DUAL_OPTS);
  const a = xByDate(out, PROJECTED, "chart-line"), b = xByDate(out, ACTUAL, "chart-down");
  const shared = [...a.keys()].filter((d) => b.has(d));
  assert.equal(shared.length, 10);
  for (const d of shared) assert.ok(Math.abs(a.get(d) - b.get(d)) <= 0.1, `${d}: A x=${a.get(d)} vs B x=${b.get(d)}`);
});

test("#3557 dualLineChart — a series that stops earlier ENDS earlier; it is not stretched to the edge", () => {
  const out = dualLineChart(PROJECTED, ACTUAL, DUAL_OPTS);
  const ax = xsOf(dOf(out, "chart-line")), bx = xsOf(dOf(out, "chart-down"));
  assert.equal(ax[ax.length - 1], 592); // Sep 24 — the frame's t1
  assert.ok(bx[bx.length - 1] < 585, `B's last date is Sep 23 but it ends at x=${bx[bx.length - 1]}`);
  assert.equal(ax[0], 8);
  assert.equal(bx[0], 8); // both start Sep 5 — shared t0
});

test("#3557 dualLineChart — gaps render as gaps: spacing is proportional to elapsed days", () => {
  const irregular = [{ date: "2026-09-01", value: 1 }, { date: "2026-09-02", value: 2 }, { date: "2026-09-20", value: 3 }, { date: "2026-09-21", value: 4 }];
  const dense = [...Array(21)].map((_, i) => ({ date: `2026-09-${String(i + 1).padStart(2, "0")}`, value: i }));
  const out = dualLineChart(irregular, dense, { aLabel: "sparse", bLabel: "dense" });
  const x = xsOf(dOf(out, "chart-line"));
  const oneDay = x[1] - x[0], eighteenDays = x[2] - x[1];
  assert.ok(Math.abs(eighteenDays / oneDay - 18) < 0.05, `an 18-day gap drew ${(eighteenDays / oneDay).toFixed(2)} day-widths`);
});

test("#3557 dualLineChart — the hover readout covers BOTH series' dates, not series A alone", () => {
  const out = dualLineChart(PROJECTED, ACTUAL, DUAL_OPTS);
  const cpts = JSON.parse(/data-cpts="([^"]+)"/.exec(out)[1].replace(/&quot;/g, '"').replace(/&lt;/g, "<"));
  assert.equal(cpts.length, 20); // union of the two date sets
  const shared = cpts.find((c) => /Sep 13/.test(c.l));
  assert.match(shared.l, /projected \(energy balance\)/);
  assert.match(shared.l, /actual \(scale\)/); // both legs on a shared day
  const aOnly = cpts.find((c) => /Sep 14/.test(c.l)); // projected-only day
  assert.match(aOnly.l, /projected \(energy balance\)/);
  assert.doesNotMatch(aOnly.l, /actual \(scale\)/); // a one-sided day reads as one-sided
});

test("#3557 dualLineChart — B-only dates are reachable by the readout too", () => {
  const A = [...Array(5)].map((_, i) => ({ date: `2026-09-${String(1 + i).padStart(2, "0")}`, value: i }));
  const B = [...Array(5)].map((_, i) => ({ date: `2026-09-${String(4 + i).padStart(2, "0")}`, value: i }));
  const out = dualLineChart(A, B, { aLabel: "A", bLabel: "B" });
  const cpts = JSON.parse(/data-cpts="([^"]+)"/.exec(out)[1].replace(/&quot;/g, '"'));
  assert.equal(cpts.length, 8); // Sep 1..8
  assert.ok(cpts.some((c) => /Sep 8/.test(c.l) && /B /.test(c.l) && !/A /.test(c.l)));
});

test("#3557 dualLineChart — the stated gap is measured on the last date BOTH series reach", () => {
  const out = dualLineChart(PROJECTED, ACTUAL, DUAL_OPTS);
  // Sep 23: projected 5.7, actual 4.75 → 1.0 (not 6.0 vs 4.75 read off different days).
  assert.match(capOf(out), /gap 1 lb on Sep 23/);
  assert.match(ariaOf(out), /gap 1 lb on Sep 23/);
});

test("#3557 dualLineChart — dateless numeric series keep an index frame, but a SHARED one", () => {
  const A = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
  const B = [1, 2, 3, 4, 5];
  const out = dualLineChart(A, B, {});
  const ax = xsOf(dOf(out, "chart-line")), bx = xsOf(dOf(out, "chart-down"));
  assert.equal(ax[ax.length - 1], 592);
  assert.ok(bx[bx.length - 1] < 300, `the shorter dateless series was stretched to x=${bx[bx.length - 1]}`);
  assert.ok(Math.abs(ax[4] - bx[4]) < 0.1); // same index ⇒ same x
  assert.doesNotMatch(capOf(out), /x by real date/); // and it does not CLAIM a date axis
});

test("#3557 NEGATIVE CONTROL — index-positioning each series over its own length reds the alignment assertion", async () => {
  const m = await mutant([
    "  const path = (arr) => arr.map((p, i) => `${i ? \"L\" : \"M\"}${xOf(p, i).toFixed(1)} ${y(p.v).toFixed(1)}`).join(\" \");",
    "  const path = (arr) => arr.map((p, i) => `${i ? \"L\" : \"M\"}${(P + (i / (arr.length - 1)) * (W - 2 * P)).toFixed(1)} ${y(p.v).toFixed(1)}`).join(\" \");",
  ]);
  const out = m.dualLineChart(PROJECTED, ACTUAL, DUAL_OPTS);
  const a = xByDate(out, PROJECTED, "chart-line"), b = xByDate(out, ACTUAL, "chart-down");
  // The issue's measured number: 2026-09-13 at x=253.9 on A and x=267.6 on B.
  assert.ok(Math.abs(a.get("2026-09-13") - b.get("2026-09-13")) > 13);
  assert.throws(() => {
    for (const d of [...a.keys()].filter((k) => b.has(k))) assert.ok(Math.abs(a.get(d) - b.get(d)) <= 0.1, `${d} misaligned`);
  }, /misaligned/);
  // ...and the shorter series is stretched to the right edge although it ends earlier.
  const bx = xsOf(dOf(out, "chart-down"));
  assert.equal(bx[bx.length - 1], 592);
});

// ── low-n: Day 0/1 of a fresh cycle ──────────────────────────────────────────

test("#3556/#3557 low-n — n=0,1,2,3 draw NO line on either builder, goal or no goal", () => {
  for (const n of [0, 1, 2, 3]) {
    const out = lineChart(WEIGH_INS.slice(0, n), { ...RESULTS_DOOR, emptyMsg: "Weight trajectory fills as weigh-ins accrue." });
    assert.doesNotMatch(out, /<svg/, `lineChart drew a line at n=${n}`);
    assert.match(out, /chart--empty/);
    // The goal must not sneak in as a phantom annotation on an empty figure either.
    assert.doesNotMatch(out, /chart-goal/);
    if (n === 0) assert.match(out, /Weight trajectory fills as weigh-ins accrue/);
    else assert.match(out, new RegExp(`${n} reading${n === 1 ? "" : "s"} so far`));

    const dual = dualLineChart(PROJECTED.slice(0, n), ACTUAL.slice(0, n), DUAL_OPTS);
    assert.doesNotMatch(dual, /<svg/, `dualLineChart drew lines at n=${n}`);
    assert.match(dual, /chart--empty/);
  }
});

test("#3556/#3557 low-n — a 4-point series draws honestly and still refuses when only ONE side has 4", () => {
  assert.match(lineChart(WEIGH_INS.slice(0, 4), RESULTS_DOOR), /<svg/);
  assert.match(dualLineChart(PROJECTED, ACTUAL.slice(0, 3), DUAL_OPTS), /chart--empty/);
});
