// The one weekly spark (review 2026-11-14 dataviz-1/-2): bars from zero with no floor, a labelled trend line when
// the change is small against the level, and the same picture for the same series on every page.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { SPARK_H, TREND_BELOW, scaleWords, sparkPlan, weeklySpark } from "../src/lib/spark.js";

const weight = [327.3, 322.1, 318.9, 314.0, 308.3, 302.2, 298.8, 291.4]; // a 11% fall: the series the review read two ways
const hrv = [34, 43, 50, 49, 70, 57, 59, 58]; // moves by half its level
const heights = (svg) => [...svg.matchAll(/<rect x="\d+" y="[\d.]+" width="10" height="([\d.]+)"/g)].map((m) => Number(m[1]));

test("a small change against the level is a trend line on its own labelled range, never bars", () => {
  const { svg, plan } = weeklySpark(weight);
  assert.equal(plan.kind, "trend");
  assert.equal(heights(svg).length, 0, "no bars: a bar from zero would hide the fall, a bar from the minimum would invent a collapse");
  assert.match(svg, /<polyline/);
  assert.equal(scaleWords(plan, { decimals: 1, unit: "lb" }), "weekly means 291.4 to 327.3 lb · line on that range");
});

test("bars start at zero and their heights are the values in proportion — no floor, no offset", () => {
  const { svg, plan } = weeklySpark(hrv);
  assert.equal(plan.kind, "bars");
  assert.equal(scaleWords(plan), "weekly means · bars from zero");
  const h = heights(svg);
  assert.equal(h.length, 8);
  const top = Math.max(...hrv);
  hrv.forEach((v, i) => assert.ok(Math.abs(h[i] - (v / top) * (SPARK_H - 1)) < 0.06, `week ${i}: ${h[i]} for ${v}`));
  assert.ok(Math.abs(h[0] / h[4] - 34 / 70) < 0.01, "the lowest week is not a stub: it keeps its ratio to the highest");
});

test("a week of zero draws no bar and a missing week is a hollow tick, in both forms", () => {
  const counts = weeklySpark([0, 2, 5, null, 3, 0, 4, 6]);
  assert.equal(counts.plan.kind, "bars");
  assert.equal(heights(counts.svg).length, 5, "two zero weeks and one missing week draw no bar");
  assert.equal((counts.svg.match(/stroke-dasharray="2 2"/g) || []).length, 1);
  const gap = weeklySpark([327, 322, null, 314, 308, 302, 298, 291]);
  assert.equal((gap.svg.match(/<polyline/g) || []).length, 2, "the line breaks at the missing week: nothing is interpolated");
  assert.equal(weeklySpark([null, null]).plan.kind, "empty");
});

test("the form is decided by the values alone, at a stated threshold", () => {
  assert.equal(sparkPlan([100, 76]).kind, "trend"); // 24% of the level
  assert.equal(sparkPlan([100, 74]).kind, "bars"); // 26%
  assert.ok(TREND_BELOW === 0.25);
  assert.equal(weeklySpark(weight).svg, weeklySpark([...weight]).svg, "same values, same picture");
});

test("both doors draw through the contract and neither keeps a scale of its own", () => {
  for (const page of ["../src/pages/index.astro", "../src/pages/data/index.astro"]) {
    const src = readFileSync(new URL(page, import.meta.url), "utf8");
    assert.match(src, /weeklySpark\(/, page);
    assert.doesNotMatch(src, /Math\.min\(\.\.\.vals|\(v - lo\) \/ \(hi - lo\)/, `${page} still scales its own bars`);
  }
});
