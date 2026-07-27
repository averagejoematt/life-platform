// oss/calibration-core/tests/calibration-core.test.mjs
//
// The JS side of the parity contract. Every expectation comes from
// vectors/calibration_vectors.json — generated from the deployed platform
// grader — and is compared with assert.deepStrictEqual, i.e. EXACTLY. If this
// file ever needs a tolerance, the extraction has failed.
//
//   node --test          (from oss/calibration-core/ — the runner discovers this file)
//
// Dynamic `await import()`, not a static specifier: the module is loaded and
// executed for real, so a syntax-clean-but-broken port cannot pass.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const VECTORS = JSON.parse(readFileSync(join(HERE, "..", "vectors", "calibration_vectors.json"), "utf8"));

const cc = await import("../js/calibration-core.js");

test("score_pairs reproduces every core vector exactly", () => {
  for (const c of VECTORS.core_cases) {
    assert.deepStrictEqual(cc.scorePairs(c.pairs, c.n_bins), c.expected, `core case: ${c.id} — ${c.description}`);
  }
});

test("normalizeConfidence reproduces every confidence vector exactly", () => {
  for (const c of VECTORS.confidence_cases) {
    assert.deepStrictEqual(cc.normalizeConfidence(c.input), c.expected, `confidence: ${JSON.stringify(c.input)}`);
  }
});

test("outcomeToBinary reproduces every outcome vector exactly", () => {
  for (const c of VECTORS.outcome_cases) {
    assert.deepStrictEqual(cc.outcomeToBinary(c.input), c.expected, `outcome: ${JSON.stringify(c.input)}`);
  }
});

test("record extractors reproduce every record vector exactly", () => {
  const fns = {
    prediction_records: cc.pairsFromPredictionRecords,
    calibration_rows: cc.pairsFromCalibrationRows,
    forecast_resolution_rows: cc.pairsFromForecastResolutionRows,
  };
  for (const c of VECTORS.record_cases) {
    assert.deepStrictEqual(fns[c.kind](c.records), c.expected_pairs, `records: ${c.id}`);
  }
});

test("parseLedgerText reproduces every adapter vector exactly", () => {
  for (const c of VECTORS.adapter_cases.ledger_text_cases) {
    assert.deepStrictEqual(cc.parseLedgerText(c.text), c.expected, `ledger text: ${c.id}`);
  }
});

test("pyRound reproduces CPython's half-to-even rounding on the exact binary value", () => {
  // The trap this whole file exists for: Math.round(0.125 * 100) / 100 === 0.13,
  // Python's round(0.125, 2) === 0.12. A naive port silently publishes a
  // different Brier score than the platform does.
  for (const c of VECTORS.adapter_cases.round_cases) {
    assert.deepStrictEqual(cc.pyRound(c.x, c.nd), c.expected, `round(${c.x}, ${c.nd})`);
  }
});

test("the always-say-50% forecaster scores exactly 0.25", () => {
  assert.equal(cc.brierScore([[0.5, 1], [0.5, 0], [0.5, 1], [0.5, 0]]), 0.25);
});

test("skill is null, never 0, when every outcome is identical", () => {
  assert.equal(cc.brierSkillScore([[0.8, 1], [0.9, 1], [0.7, 1]]), null);
  assert.equal(cc.scorePairs([[0.8, 1], [0.9, 1], [0.7, 1]]).skilled, null);
});

test("reliability without skill never reads well-calibrated", () => {
  const pairs = [];
  for (let i = 0; i < 5; i += 1) pairs.push([0.5, 1]);
  for (let i = 0; i < 3; i += 1) pairs.push([0.5, 0]);
  const s = cc.scorePairs(pairs);
  assert.equal(s.skilled, false);
  assert.notEqual(s.calibration, "well-calibrated");
  assert.equal(s.label, "not_yet_skillful");
});

test("an empty ledger reports null everywhere, never a flattering zero", () => {
  const s = cc.scorePairs([]);
  assert.equal(s.n, 0);
  assert.equal(s.brier, null);
  assert.equal(s.brier_skill, null);
  assert.equal(s.accuracy_pct, null);
  assert.equal(s.calibration, "insufficient_data");
});
