// The open questions, drawn (sprint III item 7): served numbers only; the unmeasured dimensions stay empty frames; no
// figure for numbers that are not served; the rate flag's private line is never drawn.
import assert from "node:assert/strict";
import { test } from "node:test";

import { dimsFigure, paceFigure, testProgress, testsFigure } from "../src/lib/openq.js";

test("the pace figure draws the served rate and interval, and no flag line", () => {
  const svg = paceFigure({ rate: 2.97, lo: 2.62, hi: 3.15, level: 80 });
  assert.match(svg, /About 3\.0 pounds lost a week; 80% interval 2\.6 to 3\.2/);
  assert.doesNotMatch(svg, /flag|cap|stroke-dasharray/);
  assert.equal(paceFigure({ rate: null }), null);
});

test("an unmeasured dimension is an empty dashed frame, named as having no public measure", () => {
  const svg = dimsFigure([
    { label: "Body", measured: true },
    { label: "Mind", measured: false },
  ]);
  assert.match(svg, /Measured in public: Body\. No public measure: Mind\./);
  assert.equal((svg.match(/stroke-dasharray/g) || []).length, 1);
  assert.equal(dimsFigure([]), null);
});

test("a test's progress is its weaker side over the days each side needs; unchecked and archived tests are not drawn", () => {
  assert.equal(testProgress({ min_days_per_arm: 5, days_observed: 10, n_condition: 4, n_comparison: 6 }), 0.8);
  assert.equal(testProgress({ min_days_per_arm: 5, days_observed: 5, n_condition: 0, n_comparison: 0 }), 0.5);
  assert.equal(testProgress({ min_days_per_arm: 5, days_observed: null }), null);
  assert.equal(testProgress({ min_days_per_arm: 5, days_observed: 27, n_condition: 14, n_comparison: 13, status: "archived" }), null);
  const svg = testsFigure([{ min_days_per_arm: 5, days_observed: 10, n_condition: 4, n_comparison: 6 }, { min_days_per_arm: 5, days_observed: null }]);
  assert.match(svg, /1 checked test; 0 with enough paired days/);
  assert.equal(testsFigure([{ min_days_per_arm: 5, days_observed: null }]), null);
});
