// tests/js/numbers_that_lie_3549_3550.test.mjs — the two reader-facing cards that
// served numbers their own logs could not reproduce (2026-09-05 /review full):
//
//   #3549 /method/survival + /story/attempts: "47% odds of day 30" over a record no
//         cycle had reached. The API now serves null odds until a prior cycle has
//         been observed at the horizon; the renderer must show the counts that
//         explain the dash — never "—%".
//   #3550 /method/calibration: "Well Calibrated / skilled" on a pooled card while
//         both strata were unskilled. The API now serves per-stratum numbers; the
//         card must render them and must not read Well Calibrated when the pooled
//         verdict is over-confident.
//
// Pure string assertions over the exported renderers — offline, no DOM.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { renderSurvival, renderCalibration } = await import("../../site/assets/js/evidence_intelligence.js");

const CYCLE = { cycle: 1, genesis: "2026-06-01", is_current: false, window_days: 6, engaged_days: 6, strip: "██████", collapse_day: null, censored: true };

test("survival: null odds render the counts, not a percent (#3549)", () => {
  const html = renderSurvival({
    horizon_days: 30,
    p_reach_30_pct: null,
    p_reach_30_ci95_pct: null,
    p_reach_30_ceiling_pct: 6,
    n_prior_cycles: 15,
    reached_horizon_n: 0,
    current_silent_days: 0,
    method: "No odds served: 0 of 15 prior cycles has been observed at day 30.",
    confidence: "n=15 prior cycles · 0 reached day 30 · a mirror, not a forecast",
    cycles: [CYCLE],
  });
  assert.ok(!html.includes("—%"), "a dash must never be rendered as a percentage");
  assert.ok(!/\d+%<\/span><span class="fig-k label">odds/.test(html), "no percentage under the odds label");
  assert.ok(html.includes("none of 15 prior cycles reached it"), html);
  assert.ok(html.includes("n=15 prior cycles"), "the confidence line carries n");
});

test("survival: served odds carry the reached/n and the interval (#3549)", () => {
  const html = renderSurvival({
    horizon_days: 30,
    p_reach_30_pct: 40,
    p_reach_30_ci95_pct: [6, 79],
    n_prior_cycles: 3,
    reached_horizon_n: 1,
    current_silent_days: 0,
    method: "m",
    confidence: "n=3 prior cycles · 1 reached day 30",
    cycles: [CYCLE],
  });
  assert.ok(html.includes(">40%<"), html);
  assert.ok(html.includes("1 of 3 prior cycles reached it"), html);
  assert.ok(html.includes("95% CI 6–79%"), html);
});

function stratum(n, confirmed, skill, calibration, gap) {
  return { n, confirmed, brier: 0.2, brier_skill: skill, skilled: skill === null ? null : skill > 0, calibration, reliability_gap: gap, base_rate: n ? confirmed / n : null };
}

const POOLED = {
  n: 174,
  confirmed: 116,
  refuted: 58,
  accuracy_pct: 66.7,
  accuracy_ci95: [59.4, 73.2],
  brier: 0.1847,
  brier_skill: -0.1029,
  skilled: false,
  skill_reference: "stratified",
  reliability_gap: 0.07,
  worst_stratum_gap: { stratum: "coaches", gap: 0.284 },
  calibration: "over-confident",
  label: "not_yet_skillful",
  score: 45,
  reliability_bins: [],
  strata: {
    coaches: stratum(37, 8, -0.4752, "over-confident", 0.284),
    hypotheses: stratum(0, 0, null, "insufficient_data", null),
    interval_forecasts: stratum(137, 108, -0.0008, "not_yet_skillful", 0.012),
  },
};

test("calibration: the pooled card shows every stratum and never reads Well Calibrated over unskilled strata (#3550)", () => {
  const html = renderCalibration({ platform: { ...POOLED, lifetime: POOLED }, coaches: [], hypotheses: {}, cycle: 17, cycle_start: "2026-09-06" });
  assert.ok(!html.includes("Well Calibrated"), "the 2026-09-05 defect string");
  assert.ok(html.includes("Over Confident") || html.includes("Over-confident") || html.includes("Over-Confident"), html);
  assert.ok(html.includes("By stratum, each against its own base rate"), html);
  assert.ok(html.includes("coach calls n=37"), html);
  assert.ok(html.includes("interval forecasts n=137"), html);
  assert.ok(html.includes("hypothesis bets n=0"), html);
  assert.ok(html.includes("gap +0.28"), "the 27-point over-confidence is on the card");
  assert.ok(html.includes("Verdict driven by the worst stratum&#39;s gap: coach calls") || html.includes("Verdict driven by the worst stratum's gap: coach calls"), html);
  assert.ok(html.includes("skill vs stratified base-rate"), "the skill figure names its reference");
});

test("calibration: a card without strata renders exactly as before (a single stratum is score_pairs)", () => {
  const single = { ...POOLED, strata: undefined, skill_reference: undefined, worst_stratum_gap: undefined, brier_skill: 0.12, skilled: true, calibration: "well-calibrated", label: "reliable" };
  const html = renderCalibration({ platform: { ...single, lifetime: single }, coaches: [], hypotheses: {}, cycle: 17 });
  assert.ok(!html.includes("By stratum"), html);
  assert.ok(html.includes("skill vs base-rate"), html);
});
