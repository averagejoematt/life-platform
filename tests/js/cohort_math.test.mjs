// tests/js/cohort_math.test.mjs — #1820: the cohort-strip percentile direction flip.
//
// /api/cohort_strip's matthew_percentile is "% of the cohort strictly below Matthew's
// raw value" — correct to render as "ahead of X%" for a higher-is-better metric, but
// backwards for a lower-is-better one (resting heart rate is the module's own example):
// being below him there means being BETTER, so he's ahead of the people ABOVE him.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { cohortAheadPercent } = await import("../../site/assets/js/cohort_math.js");

test("higher-is-better: ahead-percent equals the raw percentile (no flip)", () => {
  assert.equal(cohortAheadPercent(80, false), 80);
  assert.equal(cohortAheadPercent(0, false), 0);
  assert.equal(cohortAheadPercent(100, false), 100);
});

test("lower-is-better: ahead-percent flips to 100 minus the raw percentile", () => {
  // The issue's reproduced case: matthew=70 (resting HR) vs cohort [50,52,54,56,58],
  // all lower (better). Raw percentile (share below him) = 100 — he is the WORST
  // performer and must be "ahead of" nobody, i.e. 0%, not the un-flipped 100%.
  assert.equal(cohortAheadPercent(100, true), 0);
  assert.equal(cohortAheadPercent(0, true), 100);
  assert.equal(cohortAheadPercent(80, true), 20);
});

test("null percentile (no matthew_value configured) stays null — no sentence rendered", () => {
  assert.equal(cohortAheadPercent(null, false), null);
  assert.equal(cohortAheadPercent(null, true), null);
});
