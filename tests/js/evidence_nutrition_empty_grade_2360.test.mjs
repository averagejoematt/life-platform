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

const { nutritionVerdict, nutritionProteinLead, nutritionHero } = await import("../../site/assets/js/evidence_nutrition.js");

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
