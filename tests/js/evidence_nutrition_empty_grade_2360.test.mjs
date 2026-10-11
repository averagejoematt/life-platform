// tests/js/evidence_nutrition_empty_grade_2360.test.mjs — #2360: the nutrition door
// must not grade a protein failure out of zero logged days.
//
// The live defect (measured 2026-08-09, with MacroFactor quiet 45 days per #2326):
// /api/nutrition_overview published `protein_floor_hit_pct: 0` alongside
// `days_logged: 0`, and this renderer graded that 0. A stranger on the public door
// was told, in the serif verdict voice:
//
//     "Protein's under the floor every logged day — it isn't being cleared yet."
//
// alongside the self-contradictory "floor missed every logged day · 0/0" and the
// ember `lead-warn` treatment. Nothing had been logged all cycle.
//
// The API now publishes null for a rate over an empty set, which alone would fix the
// live render. The guard is pinned HERE as well because the render layer must not
// depend on the payload being correct: a CloudFront-cached body predating the API
// fix, or any future writer, can still hand this function a 0. Absence is not a
// failing grade (ADR-104) — and `days_logged` is in the same payload, so the
// renderer always had the evidence to know the set was empty.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { nutritionVerdict, nutritionProteinLead, nutritionHero, nutritionProteinAnnotation } = await import("../../site/assets/js/evidence_nutrition.js");

// The exact shape the live API served on 2026-08-09, before the fix.
const LIVE_EMPTY_PAYLOAD = {
  avg_calories: null,
  avg_protein_g: null,
  protein_target_g: 190,
  protein_hit_pct: 0,
  protein_hit_days: 0,
  protein_floor_g: 170,
  protein_floor_hit_pct: 0,
  protein_floor_hit_days: 0,
  days_logged: 0,
  tdee: null,
  avg_deficit: null,
};

/* ── the verdict voice ───────────────────────────────────────────────────── */

test("zero logged days yields no verdict at all, even when the payload grades 0%", () => {
  assert.equal(nutritionVerdict(LIVE_EMPTY_PAYLOAD), null);
});

test("the fabricated sentence is not reachable from an empty payload", () => {
  const v = nutritionVerdict(LIVE_EMPTY_PAYLOAD);
  const rendered = v ? `${v.machine} ${v.human}` : "";
  assert.ok(!/every logged day/.test(rendered), "the empty state must not claim anything about 'every logged day'");
  assert.ok(!/isn't being cleared/.test(rendered));
});

test("the API's corrected null payload also yields no verdict", () => {
  const nulled = { ...LIVE_EMPTY_PAYLOAD, protein_hit_pct: null, protein_floor_hit_pct: null };
  assert.equal(nutritionVerdict(nulled), null);
});

/* ── the §2 protein lead ─────────────────────────────────────────────────── */

test("zero logged days renders no protein lead figure", () => {
  assert.equal(nutritionProteinLead(LIVE_EMPTY_PAYLOAD), "");
});

test("the '0/0' contradiction and the ember warning are both unreachable when empty", () => {
  const html = nutritionProteinLead(LIVE_EMPTY_PAYLOAD);
  assert.ok(!/0\/0/.test(html), "'missed every logged day · 0/0' must not render");
  assert.ok(!/lead-warn/.test(html), "an unmeasured set must not take the ember failure treatment");
  assert.ok(!/under floor/.test(html));
});

test("the hero renders nothing for a wholly empty payload", () => {
  assert.equal(nutritionHero(LIVE_EMPTY_PAYLOAD), "");
});

/* ── the negative half: a MEASURED failure must still read as one ────────── */
// The guard keys on days_logged, never on the rate's value, so a real 0% — days
// were logged and every one of them missed the floor — survives intact. A guard
// that swallowed this would trade a fabricated failure for a hidden one.

test("a measured 0% over real logged days still renders the failure verdict", () => {
  const measured = { ...LIVE_EMPTY_PAYLOAD, days_logged: 6, avg_protein_g: 120, protein_floor_hit_days: 0 };
  const v = nutritionVerdict(measured);
  assert.ok(v, "six logged days that all missed the floor is a real grade");
  assert.ok(/every logged day/.test(v.human), "the honest failure sentence must survive");
});

test("a measured 0% still renders the lead with its ember treatment and real denominator", () => {
  const measured = { ...LIVE_EMPTY_PAYLOAD, days_logged: 6, avg_protein_g: 120, protein_floor_hit_days: 0 };
  const html = nutritionProteinLead(measured);
  assert.ok(/lead-warn/.test(html), "a real miss keeps the warning treatment");
  assert.ok(/0\/6/.test(html), "the denominator must be the real logged-day count");
});

test("a healthy payload is untouched by the guard", () => {
  const good = { ...LIVE_EMPTY_PAYLOAD, days_logged: 10, protein_floor_hit_pct: 100, protein_floor_hit_days: 10, avg_protein_g: 195 };
  const html = nutritionProteinLead(good);
  assert.ok(/lead-ok/.test(html));
  assert.ok(/cleared 10\/10 days/.test(html));
});

/* ── #4244: the micronutrient section's label derives from the channels counted ── */
// The API half of #4244 (PR #4333) made `sufficiency` the food + supplements TOTAL, each
// entry carrying `channels_counted`. The page kept the header "Micronutrients — what the food
// is short on" above that total — food-only copy over a figure that counted the supplement
// stack. The label is now derived from the entries' own channels. Guard the SET of labels in
// the section (header, avg figure, bar label, caption), not the one header.

const { nutritionMicronutrients, micronutrientChannels } = await import("../../site/assets/js/evidence_nutrition.js");

// The shape /api/nutrition_overview served on 2026-09-29 (as_of 2026-09-26), trimmed.
const LIVE_JOINED_MICROS = {
  sufficiency: {
    fiber_g: { actual: 24.4, target: 38, pct: 64.2, from_food: 24.4, from_supplements: 0.0, channels_counted: ["food", "supplements"] },
    potassium_mg: { actual: 4823.4, target: 3400, pct: 100.0, from_food: 4823.4, from_supplements: null, channels_counted: ["food"], uncounted_supplements: ["Multivitamin", "Electrolytes"] },
    magnesium_mg: { actual: 351.9, target: 420, pct: 83.8, from_food: 207.9, from_supplements: 144.0, channels_counted: ["food", "supplements"], uncounted_supplements: ["Multivitamin", "Electrolytes"] },
    vitamin_d_mcg: { actual: 125.4, target: 100, pct: 100.0, from_food: 0.4, from_supplements: 125.0, channels_counted: ["food", "supplements"], uncounted_supplements: ["Multivitamin"] },
    omega3_total_g: { actual: 2.4, target: 3, pct: 80.0, from_food: 0.4, from_supplements: 2.0, channels_counted: ["food", "supplements"] },
  },
  avg_pct: 85.6,
  avg_pct_basis: "average of per-nutrient TOTALS (food + supplements), each capped at 100%",
  intake_channels: ["food", "supplements"],
  supplements_state: "recorded",
  unconverted: [{ name: "Multivitamin", reason: "x" }, { name: "Basic B Complex", reason: "x" }, { name: "Electrolytes", reason: "x" }],
  food_only_avg_pct: 45.5,
  as_of: "2026-09-26",
};

// The same day with no supplement record: the API serves food-only totals, entries carry
// channels_counted ["food"], BUT intake_channels still lists both (it names the join).
const ABSENT_SUPPS_MICROS = {
  sufficiency: {
    fiber_g: { actual: 24.4, target: 38, pct: 64.2, from_food: 24.4, from_supplements: null, channels_counted: ["food"] },
    vitamin_d_mcg: { actual: 0.4, target: 100, pct: 0.4, from_food: 0.4, from_supplements: null, channels_counted: ["food"] },
  },
  avg_pct: 32.3,
  intake_channels: ["food", "supplements"],
  supplements_state: "absent",
  unconverted: [],
  food_only_avg_pct: 32.3,
  as_of: "2026-09-26",
};

const _text = (html) => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");

test("#4244 a food + supplements total is never headed as what the food is short on", () => {
  const html = nutritionMicronutrients(LIVE_JOINED_MICROS);
  assert.ok(!/what the food is short on/.test(html), "food-only header over a joined figure");
  assert.ok(/Micronutrients — what food and supplements cover/.test(html));
  assert.ok(/micronutrient avg, food \+ supplements/.test(html), "the avg figure names both channels");
  assert.ok(/Food \+ supplements vs daily target/.test(html), "the bar label names both channels");
  assert.ok(!/from logged food,/.test(html), "the caption must not scope a joined figure to food");
});

test("#4244 the food-only average stays visible beside the joined one", () => {
  const t = _text(nutritionMicronutrients(LIVE_JOINED_MICROS));
  assert.ok(/85\.6% micronutrient avg, food \+ supplements/.test(t), t);
  assert.ok(/45\.5% from food alone/.test(t), t);
});

test("#4244 per-nutrient rows honour channels_counted and name what the supplements added", () => {
  const html = nutritionMicronutrients(LIVE_JOINED_MICROS);
  assert.ok(/Potassium \(food only\)/.test(html), "a nutrient no dose was counted into says food only");
  assert.ok(!/Vitamin D \(food only\)/.test(html));
  const t = _text(html);
  assert.ok(/From supplements on Saturday, September 26: Magnesium 144 mg, Vitamin D 125 mcg, Omega-3 2 g\./.test(t), t);
  assert.ok(/not counted — no record of what they contain: Multivitamin, Basic B Complex, Electrolytes\./.test(t), t);
  assert.ok(/Potassium, Magnesium, Vitamin D are therefore floors — the true amount may be higher\./.test(t), t);
});

test("#4244 a supplement-covered nutrient is not drawn as a gap (the contract fixture)", () => {
  const html = nutritionMicronutrients(LIVE_JOINED_MICROS);
  assert.ok(/aria-label="Vitamin D: 100 percent of target"/.test(html), "vitamin D reads covered, not short");
});

test("#4244 channels come from the entries, not intake_channels (which names the join)", () => {
  assert.deepEqual(micronutrientChannels(LIVE_JOINED_MICROS), { food: true, supplements: true });
  assert.deepEqual(micronutrientChannels(ABSENT_SUPPS_MICROS), { food: true, supplements: false });
});

test("#4244 a day with no supplement record reads food-only and says absent, not zero", () => {
  const html = nutritionMicronutrients(ABSENT_SUPPS_MICROS);
  const t = _text(html);
  assert.ok(/Micronutrients — from food alone/.test(t), t);
  assert.ok(!/supplements cover|Food \+ supplements/.test(t), "no channel claim the record cannot back");
  assert.ok(/No supplement record on Saturday, September 26 — these are food alone\. The supplement doses are absent from the record, not zero\./.test(t), t);
  assert.ok(!/\(food only\)/.test(html), "no per-row suffix when the whole section is food only");
});

test("#4244 a pre-#4244 cached body (no channels_counted) reads food-only", () => {
  const legacy = { sufficiency: { vitamin_d_mcg: { actual: 5, target: 100, pct: 5 } }, avg_pct: 36.4 };
  assert.ok(/from food alone/.test(nutritionMicronutrients(legacy)));
});

test("#4244 an empty micronutrient block renders nothing", () => {
  assert.equal(nutritionMicronutrients({}), "");
  assert.equal(nutritionMicronutrients(null), "");
});

/* ── #4245: omega-3 as two labelled targets, and a scheduled supplement miss ── */
const SCHEDULED_MISS_MICROS = {
  sufficiency: {
    fiber_g: { label: "Fiber", total: 24.4, actual: 24.4, target: 38, pct: 64.2, from_food: 24.4, from_supplements: 0.0, channels_counted: ["food", "supplements"] },
    vitamin_d_mcg: { label: "Vitamin D", total: 0.4, actual: 0.4, target: 100, pct: 0.4, from_food: 0.4, from_supplements: 0.0, channels_counted: ["food", "supplements"], missed_supplements: ["Vitamin D"] },
    omega3_epa_dha_g: { label: "Omega-3 EPA+DHA", total: 0.0, actual: 0.0, target: 0.5, pct: 0.0, from_food: null, from_supplements: 0.0, channels_counted: ["supplements"], missed_supplements: ["Omega 3"] },
    omega3_ala_g: { label: "Omega-3 ALA", total: 3.7, actual: 3.7, target: 1.6, pct: 100.0, from_food: 3.7, from_supplements: 0.0, channels_counted: ["food", "supplements"] },
  },
  avg_pct: 41.2,
  intake_channels: ["food", "supplements"],
  supplements_state: "scheduled_miss",
  unconverted: [],
  not_taken: [{ name: "Vitamin D", status: "failed", miss_source: "vendor" }, { name: "Omega 3", status: "failed", miss_source: "platform" }],
  food_only_avg_pct: 41.2,
  as_of: "2026-09-24",
};

test("#4245 omega-3 renders as two named targets from the served label", () => {
  const html = nutritionMicronutrients(SCHEDULED_MISS_MICROS);
  assert.ok(/Omega-3 EPA\+DHA/.test(html) && /Omega-3 ALA/.test(html), html);
  assert.ok(!/Omega3 Epa Dha/.test(html), "the key-derived fallback must not show when a label is served");
});

test("#4245 a scheduled supplement miss reads as a named zero, not an absent record", () => {
  const t = _text(nutritionMicronutrients(SCHEDULED_MISS_MICROS));
  assert.ok(/Scheduled but not taken on Thursday, September 24: Vitamin D, Omega 3 — counted as zero\./.test(t), t);
  assert.ok(!/No supplement record/.test(t), "a scheduled miss is not an absent record");
});

// #4540: the plan states ONE protein line (a 170 g floor). The API serves that figure on
// both `protein_target_g` and `protein_floor_g`, so the page must not say it twice.
const ONE_LINE_PAYLOAD = {
  avg_protein_g: 150,
  protein_target_g: 170,
  protein_hit_pct: 0,
  protein_hit_days: 0,
  protein_floor_g: 170,
  protein_floor_hit_pct: 0,
  protein_floor_hit_days: 0,
  days_logged: 12,
};

test("#4540: a target equal to the floor is named once in the protein lead", () => {
  const html = nutritionProteinLead(ONE_LINE_PAYLOAD);
  assert.match(html, /floor 170 g/);
  assert.doesNotMatch(html, /target 170 g/);
});

test("#4540: a target that differs from the floor is still named beside it", () => {
  const html = nutritionProteinLead({ ...ONE_LINE_PAYLOAD, protein_target_g: 190 });
  assert.match(html, /floor 170 g/);
  assert.match(html, /target 190 g/);
});

test("#4540: the chart annotation does not restate one line as two", () => {
  const html = nutritionProteinAnnotation(ONE_LINE_PAYLOAD);
  assert.match(html, /170 g target/);
  assert.doesNotMatch(html, /170 g floor too/);
  const two = nutritionProteinAnnotation({ ...ONE_LINE_PAYLOAD, protein_target_g: 190 });
  assert.match(two, /under the 170 g floor too/);
});
