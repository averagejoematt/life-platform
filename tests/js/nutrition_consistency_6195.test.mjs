// tests/js/nutrition_consistency_6195.test.mjs — #6195 (owner ruling 2026-11-22): the /data/nutrition/ blocks the
// target-neutral switchboard (lambdas/common/nutrition_consistency.py) reaches.
//
// OFF: the API sends none of the new fields, and every block renders byte-for-byte what the tree before the
// switchboard rendered (tests/fixtures/nutrition_consistency_6195/js_off_golden.json, written by the same render helper
// run against origin/main).
// ON: each new field changes only its own label or sentence — the five-channel read states what it is not based on and
// its date, the chart captions maintenance as an estimate (never "goal"), the loss-rate line drops "defensible", and a
// maintenance figure carries its source and date.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { renderOff, N_OFF, LR_OFF, DS_OFF, TREND } from "./support/nutrition_6195_render.mjs";

const { nutritionVerdict, nutritionLossRate, nutritionDeficitSustainability } = await import("../../site/assets/js/evidence_nutrition.js");
const { lineChart } = await import("../../site/assets/js/charts.js");

const HERE = dirname(fileURLToPath(import.meta.url));
const GOLDEN = JSON.parse(readFileSync(join(HERE, "..", "fixtures", "nutrition_consistency_6195", "js_off_golden.json"), "utf8"));

test("OFF: every touched block renders exactly what origin/main rendered", () => {
  assert.deepEqual(renderOff(), GOLDEN);
});

test("F1/F2 ON: the five-channel read carries its limits and date, and its heading asks no yes/no question", () => {
  const ds = {
    ...DS_OFF,
    severity: "channels_holding",
    verdict: "1 of 5 recovery channels held steady from Apr 27 to May 10. This read has no food, protein, lab or lean-mass input, so it does not say whether the deficit itself is safe or sustainable.",
    as_of: "2026-05-10",
    based_on: ["HRV", "sleep quality", "recovery", "habit completion", "training output"],
    not_based_on: ["food intake", "protein", "blood tests", "electrolytes", "lean mass"],
    honesty: "These five channels are recovery signals only.",
    deficit: { ...DS_OFF.deficit, tdee_as_of: "2026-05-01" },
  };
  const html = nutritionDeficitSustainability(ds);
  assert.match(html, /Recovery channels during the cut — the five-channel read/);
  assert.doesNotMatch(html, /Is the cut costing you\?/);
  assert.match(html, /Not based on: food intake, protein, blood tests, electrolytes, lean mass\./);
  assert.match(html, /As of May 10\./);
  assert.doesNotMatch(html, /absorbing/);
  // F4: the intake figure carries its window; the maintenance figure its source and date
  assert.match(html, /a day from Apr 27 to May 10 against an estimated 3,000 to maintain \(MacroFactor's adaptive estimate, as of May 1\)/);
  // the strain tone is the same as before: channels_holding is not a warning
  assert.match(html, /dsx-sev-ok/);
});

test("F4/F6 ON: the hero names maintenance's source and date; the calorie chart captions it, never 'goal'", () => {
  const n = { ...N_OFF, tdee_as_of: "2026-05-01" };
  assert.equal(nutritionVerdict(n).machine, "1000 in (13 complete days) · 3000 estimated maintenance (MacroFactor's adaptive estimate, as of May 1) · protein floor 0 of 13 days");
  const formula = nutritionVerdict({ ...n, tdee_source: "estimate_mifflin", tdee_as_of: "2026-05-10" }).machine;
  assert.match(formula, /3000 estimated maintenance \(formula estimate, as of May 10\)/);
  assert.match(nutritionVerdict({ ...n, tdee_as_of: null }).machine, /\(MacroFactor's adaptive estimate, date unknown\)/);
  const chart = lineChart(TREND, { valueKey: "calories", goal: 3000, goalWord: "estimated maintenance", unit: " kcal", label: "Calories vs maintenance", spine: true });
  assert.match(chart, /estimated maintenance 3000 kcal/);
  assert.doesNotMatch(chart, /\bgoal \d/); // reader text; the `chart-goal` CSS class is the line's style, not a word
  // the default word is unchanged for every other chart
  assert.match(lineChart(TREND, { valueKey: "calories", goal: 900, unit: " lb", label: "Weight" }), /goal 900 lb/);
});

test("F7 ON: the loss-rate line drops the 'defensible' verdict and the bench attribution", () => {
  const html = nutritionLossRate({ ...LR_OFF, rate_line_v2: true }, N_OFF);
  assert.doesNotMatch(html, /defensible|bench/);
  assert.match(html, /this page does not rate the pace as safe or unsafe/);
  assert.match(html, /right now that floor's missed most days/);
});
