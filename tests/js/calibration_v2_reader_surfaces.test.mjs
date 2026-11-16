// tests/js/calibration_v2_reader_surfaces.test.mjs — every legacy-site surface that shows a calibration verdict shows
// calibration-v2's three answers, and never a v1 label (owner ruling 2026-11-09).
//
//   /method/calibration/        evidence_intelligence.renderCalibration (/api/calibration)
//   /method/grade-your-coach/   grade_your_coach.grade (the browser port, calibration-v2-core.js)
//
// SENTINEL + MUTATION CONTROL: the payload's deprecated v1 fields (`calibration`, `label`, `score`) carry a sentinel
// that must never reach the HTML; the control proves the sentinel IS in the payload the renderer was handed.
// Every payload here is SYNTHETIC.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { renderCalibration } = await import("../../site/assets/js/evidence_intelligence.js");
const { grade } = await import("../../site/assets/js/grade_your_coach.js");
const { shortHTML, answersHTML } = await import("../../site/assets/js/calibration_v2_words.js");

const SENT = "V1SENTINEL";

function answers(est, cd, cdShort, skill, skillShort) {
  return {
    method_version: "calibration-v2",
    n: 44,
    estimability: { result: "not_estimable", wording: est, short: "not estimable across confidence levels" },
    confidence_direction: { result: "x", wording: cd, short: cdShort },
    skill: { result: "no_demonstrated_advantage", wording: skill, short: skillShort },
  };
}

const NUTRITION_CD =
  "Over-confident at its 50% calls (12 of 43 came true, 95% CI 15%–44%; Holm-adjusted p 0.0108) — a finding about calls at that confidence level, not about calibration across confidence levels.";
const EST = "Calibration across confidence levels not estimable: 1 confidence level(s) with at least 17 calls, 2 needed; 13 calls of the rarer outcome, 20 needed.";
const SKILL = "No demonstrated advantage over the guess that nothing changes (44 calls compared).";

function coach(id, name, n) {
  return { coach_id: id, coach_name: name, n, confirmed: 12, brier: 0.25, accuracy_pct: 27.9, calibration: SENT, label: SENT, score: SENT, reliability_bins: [{ lo: 0.5, hi: 0.6, n, mean_confidence: 0.5, observed_rate: 0.28 }], lifetime: { n, calibration: SENT, label: SENT } };
}

function payload() {
  const stratum = { n: 90, confirmed: 30, brier: 0.24, brier_skill: -0.02, calibration: SENT, label: SENT, reliability_gap: 0.1 };
  return {
    platform: { n: 90, confirmed: 30, brier: 0.24, brier_skill: -0.02, calibration: SENT, label: SENT, score: SENT, skill_reference: "stratified", strata: { coaches: stratum }, reliability_bins: [], lifetime: { n: 90, confirmed: 30, calibration: SENT, label: SENT, strata: { coaches: stratum } } },
    coaches: [coach("nutrition", "Dr. Marcus Webb", 44), coach("sleep", "Lisa Park", 46)],
    hypotheses: { n: 3, brier: 0.2, calibration: SENT, label: SENT, lifetime: { n: 3 } },
    assessment_v2: {
      method_version: "calibration-v2",
      status: "adopted",
      adopted: "2026-11-09",
      coaches: {
        nutrition: answers(EST, NUTRITION_CD, "over-confident at its 50% calls", SKILL, "no demonstrated advantage"),
        sleep: answers(EST, "Consistent with stated confidence (not established): no level departs at alpha 0.05 over 46 calls.", "consistent with stated confidence (not established)", SKILL, "no demonstrated advantage"),
      },
      strata: { coaches: answers(EST, "Consistent with stated confidence (not established): no level departs at alpha 0.05 over 90 calls.", "consistent with stated confidence (not established)", SKILL, "no demonstrated advantage") },
    },
    calibration_method: { version: "calibration-v2", adopted: "2026-11-09", deprecated_fields: { fields: ["calibration", "label", "score"] } },
    cycle: 17,
    cycle_start: "2026-09-06",
  };
}

test("/method/calibration/: the scoreboard shows the three v2 answers and no v1 label", () => {
  const d = payload();
  const html = renderCalibration(d);
  assert.ok(JSON.stringify(d).includes(SENT), "control: the sentinel is in the payload");
  assert.ok(!html.toLowerCase().includes(SENT.toLowerCase()), "a deprecated v1 field reached the page");
  assert.ok(html.includes("over-confident at its 50% calls"), "Nutrition's short answer names its level");
  assert.ok(html.includes("Over-confident at its 50% calls (12 of 43 came true, 95% CI 15%–44%; Holm-adjusted p 0.0108)"), "the full answer with its interval and corrected p");
  assert.ok(html.includes("not about calibration across confidence levels"));
  assert.ok(html.includes("consistent with stated confidence (not established)"));
  assert.ok(html.includes("no demonstrated advantage"));
  assert.ok(html.includes("Can calibration be estimated across confidence levels?"));
  assert.ok(html.includes("calibration-v2, adopted 2026-11-09"));
  assert.ok(!/poorly calibrated|well[ -]calibrated|not yet skillful/i.test(html), html);
});

test("/method/calibration/: an older cache without assessment_v2 renders no verdict at all, never the v1 one", () => {
  const d = payload();
  delete d.assessment_v2;
  const html = renderCalibration(d);
  assert.ok(!html.toLowerCase().includes(SENT.toLowerCase()));
  assert.ok(html.includes("The scoreboard — by coach"));
});

test("the words module never turns a bare label into words", () => {
  assert.equal(shortHTML({ confidence_direction: { label: "over_confident" } }), "—");
  assert.equal(answersHTML({ calibration: SENT }), "");
  assert.equal(shortHTML(null), "—");
});

test("/method/grade-your-coach/: a pasted ledger gets the three v2 answers, never the v1 verdict", () => {
  const rows = ["confidence,outcome"];
  for (let i = 0; i < 43; i++) rows.push(`0.5,${i < 12 ? "confirmed" : "refuted"}`);
  const { html } = grade(rows.join("\n"));
  assert.ok(html.includes("Over-confident at its 50% calls (12 of 43 came true"), html);
  assert.ok(html.includes("Can calibration be estimated across confidence levels?"));
  assert.ok(html.includes("No baseline: a pasted ledger carries no same-call guess"));
  assert.ok(!/well[ -]calibrated|not yet skillful|not measurable|credibility:/i.test(html), html);
});

test("/method/grade-your-coach/: a ledger with no departure reads 'not established', never a compliment", () => {
  const rows = ["confidence,outcome"];
  for (let i = 0; i < 20; i++) rows.push(`0.5,${i % 2 ? "confirmed" : "refuted"}`);
  const { html } = grade(rows.join("\n"));
  assert.ok(html.includes("Consistent with stated confidence (not established)"), html);
});
