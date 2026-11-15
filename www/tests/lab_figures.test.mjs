// The Laboratory's index figures (2026-11-14, sprint II): placement of served numbers only.
import assert from "node:assert/strict";
import { test } from "node:test";

import { armsFigure, findingCaption, forestFigure, pairTitle } from "../src/lib/laboratory.js";

const f = { metric_a: "Resting HR", metric_b: "Recovery", r: -0.67, ci95_low: -0.81, ci95_high: -0.44, n: 90, n_eff: 39.2 };

test("a finding as a forest row: the dot and band at the served r and interval, cobalt only when the band clears zero", () => {
  const svg = forestFigure(f, { width: 212 }); // pad 6: the axis is 200 units wide, so −1 → 6, 0 → 106, +1 → 206
  assert.match(svg, /<circle cx="39\.0"/, "r = −0.67 sits at 6 + 0.165 × 200");
  assert.match(svg, /x1="25\.0" y1="15" x2="62\.0"/, "the band runs from −0.81 to −0.44");
  assert.match(svg, /#1B3FD6/);
  const crosses = forestFigure({ ...f, r: 0.1, ci95_low: -0.1, ci95_high: 0.3 });
  assert.doesNotMatch(crosses, /#1B3FD6/, "an interval that includes zero is never cobalt");
  assert.equal(forestFigure({ ...f, r: null }), null);
  assert.equal(pairTitle(f), "Resting HR × Recovery");
  assert.equal(findingCaption(f), "r −0.67 · 95% interval −0.81 to −0.44 · about 39 independent days of 90");
});

test("a test's paired days against what a verdict needs: two sides once split, one bar before, nothing when unchecked", () => {
  const split = armsFigure({ min_days_per_arm: 5, days_observed: 10, n_condition: 4, n_comparison: 6 });
  assert.match(split, /test side: 4 of the 5 days needed; other side: 6 of the 5 days needed/);
  const before = armsFigure({ min_days_per_arm: 5, days_observed: 5, n_condition: 0, n_comparison: 0 });
  assert.match(before, /paired days: 5 of the 10 days needed/);
  assert.equal(armsFigure({ min_days_per_arm: 5, days_observed: null }), null, "no count served, nothing drawn");
});
