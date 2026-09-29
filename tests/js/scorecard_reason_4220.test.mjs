// tests/js/scorecard_reason_4220.test.mjs — the reason line under a scorecard call is
// reader words, never the grader's serialized dict (#4220). The fixtures are the WIRE:
// `outcome_notes` strings exactly as /api/predictions served them 2026-09-29 16:24Z.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { callReasonText } = await import("../../site/assets/js/scorecard_reason.js");

const NO_SIGNAL_WIRE =
  '{"actual_value": null, "reason": "Insufficient data to determine trend for \'blood_glucose_avg\'", "beats_null": false, "bayesian_update": null, "algo_version": "1.0", "grading_open": true}';
const GRADED_WIRE =
  '{"actual_value": 0.23412323897684148, "reason": "hrv_7day_avg trend=up (slope=0.2341), predicted=up", "beats_null": true, "bayesian_update": null, "algo_version": "1.0"}';

test("#4220: a no-signal call reads 'not gradable yet — <reason>', never the raw dict", () => {
  const out = callReasonText("inconclusive", NO_SIGNAL_WIRE);
  assert.equal(out, "not gradable yet — insufficient data to determine trend for 'blood_glucose_avg'");
  for (const leak of ["{", "actual_value", "algo_version", "grading_open", "null"]) assert.ok(!out.includes(leak), `${leak} leaked: ${out}`);
  assert.equal(callReasonText("expired", NO_SIGNAL_WIRE).startsWith("not gradable yet — "), true);
});

test("#4220: a graded call's reason is the grader's own sentence, unwrapped", () => {
  assert.equal(callReasonText("confirmed", GRADED_WIRE), "hrv_7day_avg trend=up (slope=0.2341), predicted=up");
  assert.equal(callReasonText("refuted", JSON.parse(GRADED_WIRE)), "hrv_7day_avg trend=up (slope=0.2341), predicted=up");
});

test("#4220: plain notes pass through; nothing to say renders nothing", () => {
  assert.equal(callReasonText("refuted", "recovery_score trend=up, predicted=down"), "recovery_score trend=up, predicted=down");
  assert.equal(callReasonText("confirmed", "{not json"), "{not json");
  assert.equal(callReasonText("pending", ""), "");
  assert.equal(callReasonText("inconclusive", null), "");
  assert.equal(callReasonText("inconclusive", '{"actual_value": null, "grading_open": true}'), "");
});
