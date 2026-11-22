// tests/js/support/nutrition_6195_render.mjs — the /data/nutrition/ blocks #6195 touches, rendered from synthetic
// payloads. Run against the tree before the switchboard (origin/main) it wrote
// tests/fixtures/nutrition_consistency_6195/js_off_golden.json; tests/js/nutrition_consistency_6195.test.mjs renders the
// same OFF payloads here and requires the identical strings (the API sends none of the new fields while a switch is off).
import "./loader.mjs";

const { nutritionVerdict, nutritionLossRate, nutritionDeficitSustainability } = await import("../../../site/assets/js/evidence_nutrition.js");
const { lineChart } = await import("../../../site/assets/js/charts.js");

export const N_OFF = {
  avg_calories: 1000,
  tdee: 3000,
  tdee_source: "macrofactor_adaptive",
  avg_deficit: null,
  avg_deficit_published: false,
  protein_floor_hit_pct: 0,
  protein_floor_hit_days: 0,
  days_logged: 13,
  protein_target_g: 170,
  protein_floor_g: 170,
};
export const LR_OFF = { actual_deficit_kcal: null, deficit_published: false, protein_floor_hit_pct: 40, deficit_label: null };
export const DS_OFF = {
  available: true,
  period: { start: "2026-04-27", end: "2026-05-10", days: 14 },
  deficit: { in_deficit: true, avg_intake_kcal: 1000, tdee: 3000, tdee_source: "macrofactor_adaptive", deficit_published: false, deficit_kcal: null },
  channels: [
    { name: "HRV", status: "stable", direction: "stable", delta_pct: 0 },
    { name: "Recovery", status: "stable", direction: "declining", delta_pct: -4 },
  ],
  degraded_count: 0,
  severity: "sustainable",
  verdict: "The body's absorbing the deficit — recovery, sleep, and output are holding while the weight comes off.",
};
export const TREND = [
  { date: "2026-05-05", calories: 1000 },
  { date: "2026-05-06", calories: 1100 },
  { date: "2026-05-07", calories: 950 },
  { date: "2026-05-08", calories: 1000 },
  { date: "2026-05-09", calories: 1100 },
];

export function renderOff() {
  return {
    verdict: nutritionVerdict(N_OFF),
    loss_rate: nutritionLossRate(LR_OFF, N_OFF),
    deficit_sustainability: nutritionDeficitSustainability(DS_OFF),
    calorie_chart: lineChart(TREND, { valueKey: "calories", goal: N_OFF.tdee, unit: " kcal", label: "Calories vs maintenance", spine: true }),
    weight_chart: lineChart(TREND, { valueKey: "calories", goal: 900, unit: " lb", label: "Weight" }),
  };
}

if (process.argv[2] === "--print") console.log(JSON.stringify(renderOff(), null, 1));
