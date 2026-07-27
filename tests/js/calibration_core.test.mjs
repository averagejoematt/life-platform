// tests/js/calibration_core.test.mjs — #1396: the browser half of the calibration
// parity contract.
//
// /method/grade-your-coach/ computes its scorecard entirely in the reader's
// browser, from site/assets/js/calibration-core.js. That file is a vendored copy
// of oss/calibration-core/js/calibration-core.js, and the page's whole promise is
// "the SAME scorecard the platform's own coaches get". This test holds the
// VENDORED file — the one actually shipped to readers — to the same fixture the
// deployed Python grader generated, with exact equality.
//
// tests/test_calibration_core_parity.py covers the other two legs (platform
// Python <-> extracted package, and the byte-identity of this vendored copy).
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const VECTORS = JSON.parse(readFileSync(join(HERE, "..", "..", "oss", "calibration-core", "vectors", "calibration_vectors.json"), "utf8"));

// Dynamic await import(): the shipped module is loaded and EXECUTED, so a port
// that parses but computes the wrong number cannot slip through.
const cc = await import("../../site/assets/js/calibration-core.js");

test("the shipped module scores every core vector exactly as the platform grader does", () => {
  for (const c of VECTORS.core_cases) {
    assert.deepStrictEqual(cc.scorePairs(c.pairs, c.n_bins), c.expected, `core case: ${c.id} — ${c.description}`);
  }
});

test("confidence normalisation matches the platform grader on every vector", () => {
  for (const c of VECTORS.confidence_cases) {
    assert.deepStrictEqual(cc.normalizeConfidence(c.input), c.expected, `confidence: ${JSON.stringify(c.input)}`);
  }
});

test("outcome resolution matches the platform grader on every vector", () => {
  for (const c of VECTORS.outcome_cases) {
    assert.deepStrictEqual(cc.outcomeToBinary(c.input), c.expected, `outcome: ${JSON.stringify(c.input)}`);
  }
});

test("record extractors match the platform grader on every vector", () => {
  const fns = {
    prediction_records: cc.pairsFromPredictionRecords,
    calibration_rows: cc.pairsFromCalibrationRows,
    forecast_resolution_rows: cc.pairsFromForecastResolutionRows,
  };
  for (const c of VECTORS.record_cases) {
    assert.deepStrictEqual(fns[c.kind](c.records), c.expected_pairs, `records: ${c.id}`);
  }
});

test("the paste-box parser matches the Python package on every adapter vector", () => {
  for (const c of VECTORS.adapter_cases.ledger_text_cases) {
    assert.deepStrictEqual(cc.parseLedgerText(c.text), c.expected, `ledger text: ${c.id}`);
  }
});

test("rounding is CPython's half-to-even on the exact binary value, not Math.round", () => {
  // Without this the page would publish 0.13 where the platform publishes 0.12.
  for (const c of VECTORS.adapter_cases.round_cases) {
    assert.deepStrictEqual(cc.pyRound(c.x, c.nd), c.expected, `round(${c.x}, ${c.nd})`);
  }
});

test("the shipped demo ledgers score to their committed scorecards", () => {
  const demoDir = join(HERE, "..", "..", "oss", "calibration-core", "demo");
  const worked = JSON.parse(readFileSync(join(demoDir, "worked_example.json"), "utf8"));
  const pairs = cc.pairsFromPredictionRecords(worked.rows.map((r) => ({ confidence: r.confidence, status: r.outcome })));
  assert.deepStrictEqual(cc.scorePairs(pairs), worked.expected_scorecard, "worked example scorecard drifted");

  // Matthew's real public ledger: every call in the snapshot is still pending,
  // so the honest answer is n=0 / insufficient_data — not a fabricated score.
  const real = JSON.parse(readFileSync(join(demoDir, "matthew_public_ledger.json"), "utf8"));
  assert.equal(real.provenance.synthetic, false);
  const realPairs = cc.pairsFromPredictionRecords(real.rows.map((r) => ({ confidence: r.confidence, status: r.outcome })));
  const realScore = cc.scorePairs(realPairs);
  assert.equal(realScore.n, realPairs.length);
  assert.equal(realScore.brier, realPairs.length ? realScore.brier : null);
});
