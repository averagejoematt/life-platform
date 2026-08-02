// tests/js/calibration_void.test.mjs — #1893: the void ledger, visible.
//
// A reset voids (never grades) every still-open pre-registered bet. The career
// card's n is a SUBSET of the record — 273 of 323 lifetime bets were voided
// across five resets and no surface said so. This holds the shipped renderer
// (executed, not just parsed) to the honest line: voided.n > 0 must render the
// disclosure beside the career figures, and its absence must not invent one.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const ei = await import("../../site/assets/js/evidence_intelligence.js");

const BASE = {
  platform: { n: 2, brier: 0.2, lifetime: { n: 50, confirmed: 23, refuted: 27, brier: 0.21 } },
  coaches: [],
  hypotheses: {},
  cycle: 11,
};

test("voided bets render the honest-denominator line on the career card", () => {
  const html = ei.renderCalibration({ ...BASE, voided: { n: 273, hypotheses: 6, predictions: 267, by_reset: {} } });
  assert.match(html, /273 pre-registered bets voided at resets/);
  assert.match(html, /denominator is honest/);
});

test("zero voided bets renders no void line (nothing invented)", () => {
  const html = ei.renderCalibration({ ...BASE, voided: { n: 0, by_reset: {} } });
  assert.doesNotMatch(html, /voided at resets/);
});

test("a payload without the voided field (older cache) still renders", () => {
  const html = ei.renderCalibration(BASE);
  assert.match(html, /Career · every cycle/);
  assert.doesNotMatch(html, /voided at resets/);
});
