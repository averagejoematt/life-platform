import assert from "node:assert/strict";
import { test } from "node:test";

import { correctionRows, instantInWords, ruleText } from "../src/lib/corrections.js";

const ISO = /\b20\d\d-\d\d-\d\d\b/;
const base = {
  source: "corrections",
  kind: "regrade",
  rules: [{ id: "#5533:e", version: "1.1" }],
  explanation: "Heart-rate measures changed baseline on 10 October 2026.",
  said_on: "2026-10-08",
  original_status: "confirmed",
  original_outcome_date: "2026-10-22",
  corrected_status: "refuted",
  corrected_outcome_date: "2026-11-01",
  target_before: null,
  target_after: null,
  corrected_at: "2026-11-01T18:11:57Z",
  published_on: null,
  reason: "#5533 (e): an HR-metric window spanning 10 October 2026",
  aggregate_impact: null,
};
const rowsOf = (c) => Object.fromEntries(correctionRows(c));

test("a #5533 correction: original and corrected verdicts with their own days, the explanation, the recorded instant", () => {
  const r = rowsOf(base);
  assert.equal(r["Call made"], "8 October 2026");
  assert.equal(r["Original verdict"], "right — graded 22 October 2026", "the field the page read before (original_timestamp) was null on the wire");
  assert.equal(r["Corrected verdict"], "wrong — graded 1 November 2026");
  assert.equal(r["What changed"], base.explanation);
  assert.equal(r["Correction recorded"], "1 November 2026, 18:11 UTC");
  assert.equal(r["Correction published"], "not recorded", "no publication day is recorded — never the build day, never corrected_at");
  for (const [, v] of correctionRows(base)) assert.doesNotMatch(String(v), ISO);
});

test("an older writer's correction: nothing it did not record is filled in", () => {
  const r = rowsOf({ ...base, source: "verdict_correction", rules: [{ id: "#4541:count", version: null }], original_outcome_date: null, corrected_outcome_date: null, corrected_at: "2026-10-10T05:20:36.403217+00:00" });
  assert.equal(r["Original verdict"], "right — graded day not recorded");
  assert.equal(r["Corrected verdict"], "wrong — graded day not recorded");
  assert.equal(r["Correction recorded"], "10 October 2026, 05:20 UTC");
  const none = rowsOf({ ...base, corrected_status: null, corrected_at: null, said_on: null });
  assert.equal(none["Corrected verdict"], "not recorded");
  assert.equal(none["Correction recorded"], "not recorded");
  assert.equal(none["Call made"], "not recorded");
});

test("a moved target shows both days; an open call was not yet graded", () => {
  const r = rowsOf({ ...base, kind: "respecify", original_status: "pending", original_outcome_date: null, target_before: "2026-11-01", target_after: "2026-10-03" });
  assert.equal(r["Original verdict"], "open — not yet graded");
  assert.equal(r["Day the call was about"], "1 November 2026, corrected to 3 October 2026");
  assert.equal(ruleText(base), "#5533:e, evaluator 1.1");
  assert.equal(ruleText({ rules: [{ id: "#4618:respecify", version: null }] }), "#4618:respecify, version not recorded");
  assert.equal(instantInWords(null), null);
});
