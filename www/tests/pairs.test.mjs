import assert from "node:assert/strict";
import { test } from "node:test";

import { findPair, lagInWords, pairSentence, partnersOf, strengthInWords } from "../src/lib/pairs.js";

const pairs = {
  pairs: [
    { a: "weight_lbs", b: "hrv", lag: -2, n: 46, n_eff: 37.3, r: -0.35, rho: -0.552, ci95: [-0.604, -0.031], p_eff: 0.0263, fdr_q: 0.1495, family_size: 30 },
    { a: "weight_lbs", b: "hrv", lag: 0, n: 48, n_eff: 39.1, r: -0.12, rho: -0.1, ci95: [-0.4, 0.17], p_eff: 0.46, fdr_q: 0.8, family_size: 30 },
  ],
};

test("a pairing is found in either direction with the lag mirrored", () => {
  assert.equal(findPair(pairs, "weight_lbs", "hrv", -2).n, 46);
  assert.equal(findPair(pairs, "hrv", "weight_lbs", 2).n, 46);
  assert.equal(findPair(pairs, "hrv", "weight_lbs", -2), null);
  assert.deepEqual(partnersOf(pairs, "hrv"), ["weight_lbs"]);
});

test("the sentence carries the platform's numbers and never the word significant", () => {
  const s = pairSentence(findPair(pairs, "weight_lbs", "hrv", -2), { weight_lbs: "weight", hrv: "HRV" });
  assert.ok(s.startsWith("HRV read 2 days before weight: 46 paired days, Pearson r -0.35 (95% interval -0.60 to -0.03)"));
  assert.ok(s.includes("Spearman ρ -0.55") && s.includes("p 0.026 on 37.3 effective days") && s.includes("q 0.15 across the 30 pairings"));
  assert.ok(!/significan/i.test(s));
  assert.equal(pairSentence(null), null);
});

test("lag and strength are words, not verdicts", () => {
  assert.equal(lagInWords(0), "the same day");
  assert.equal(lagInWords(1), "read one day after");
  assert.equal(lagInWords(-2), "read 2 days before");
  assert.equal(strengthInWords(-0.35), "a moderate negative association");
  assert.equal(strengthInWords(0.05), "no measurable association");
  assert.equal(strengthInWords(null), "not computed");
});
