// tests/js/calibration_v2_core.test.mjs — the browser port of calibration-v2 reproduces the Python method EXACTLY.
//
// site/assets/js/calibration-v2-core.js is what /method/grade-your-coach/ grades a pasted ledger with (owner ruling
// 2026-11-09: calibration-v2 everywhere). tests/fixtures/calibration_v2_vectors.json is generated from
// experiment.calibration_v2.assess and pinned to it by tests/test_calibration_v2_js_parity.py; this test holds the JS
// to the same fixture with deep equality — no tolerance. Mutation control at the bottom: a changed answer fails.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const core = await import("../../site/assets/js/calibration-v2-core.js");
const FIX = JSON.parse(readFileSync(new URL("../fixtures/calibration_v2_vectors.json", import.meta.url), "utf8"));

test("the constants are the Python module's", () => {
  const c = FIX.constants;
  assert.equal(core.METHOD_VERSION, c.method_version);
  assert.equal(core.ALPHA, c.significance);
  assert.equal(core.LEVEL_BINS, c.level_bins);
  assert.equal(core.USABLE_CI_WIDTH, c.usable_ci_width);
  assert.equal(core.MIN_LEVELS, c.min_levels);
  assert.equal(core.EVENTS_PER_PARAMETER * core.RECALIBRATION_PARAMETERS, c.min_minority_outcome_n);
  assert.equal(core.minLevelN(), c.min_level_n);
});

for (const v of FIX.vectors) {
  test(`vector ${v.name}: assess() deep-equals the Python output`, () => {
    assert.deepStrictEqual(core.assess(v.pairs), v.expected);
  });
}

test("pyRound is Python's round (half-even on the exact binary value)", () => {
  assert.equal(core.pyRound(0.125, 2), 0.12);
  assert.equal(core.pyRound(0.375, 2), 0.38);
  assert.equal(core.pyRound(2.5, 0), 2);
  assert.equal(core.pyRound(0.1 + 0.2, 3), 0.3);
  assert.equal(core.pyFloat(1), "1.0");
  assert.equal(core.pyFloat(0.0108), "0.0108");
});

test("mutation control: a changed answer is caught", () => {
  const v = FIX.vectors.find((x) => x.name === "nutrition_shaped_over_at_50");
  const got = core.assess(v.pairs);
  assert.match(got.confidence_direction.wording, /^Over-confident at its 50% calls \(12 of 43 came true/);
  const tampered = structuredClone(v.expected);
  tampered.confidence_direction.result = "consistent_not_established";
  assert.throws(() => assert.deepStrictEqual(got, tampered));
});
