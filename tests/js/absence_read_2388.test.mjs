// tests/js/absence_read_2388.test.mjs — #2388: the reader surfaces must not translate a
// behavioral absence into a trend verb, and the cockpit must read the coach payload's
// real fields instead of asking a string for object attributes.
//
// The two live sentences this pins out of existence (measured 2026-08-09, MacroFactor
// quiet 45 days per #2326, zero food logs in the cycle):
//
//     home family panel   →  "EATING eased off a little"
//     cockpit pillar read →  "Nutrition is at 1 and slipping"
//
// The engine was never wrong: an unlogged behavioral component scoring 0 at full weight
// with data_coverage 1.0 is ADR-104's documented design. Nothing here asserts otherwise.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { pillarAbsence, isDark, absenceLine, familyChip, deterministicPillarRead, coachPayloadRead } = await import("../../site/assets/js/absence_read.js");

// The live /api/character nutrition pillar, with the #2388 absence block the API now
// derives from MacroFactor's registry stale_hours (96h) and its last DATE# write.
const DARK_NUTRITION = {
  name: "nutrition",
  raw_score: 1,
  xp_delta: -0.4,
  tier: "Foundation",
  data_coverage: 1.0,
  coverage_hold: false,
  absent_behaviors: ["protein_target", "calorie_adherence", "logging_streak", "deficit_adherence"],
  absence: {
    state: "dark",
    sources: ["macrofactor"],
    dark_sources: ["macrofactor"],
    last_log_date: "2026-06-25",
    days_dark: 45,
    stale_hours: 96,
    transition: "never_logged",
    days_since_last_log: null,
    absent_behaviors: ["protein_target"],
  },
};

const LIVE_SLEEP = { name: "sleep", raw_score: 71, xp_delta: 1.2, tier: "Foundation", data_coverage: 1.0 };

/* ── the state read ──────────────────────────────────────────────────────── */

test("a dark pillar is recognised; a pillar with no absence block is not", () => {
  assert.equal(isDark(DARK_NUTRITION), true);
  assert.equal(isDark(LIVE_SLEEP), false);
  assert.equal(pillarAbsence(LIVE_SLEEP), null);
});

test("a pre-#2388 cached payload (no absence key) never reads as dark", () => {
  // A CloudFront body cached before the API deploy must degrade to the old behavior,
  // not to a manufactured "nothing logged" claim.
  const { absence, ...stale } = DARK_NUTRITION;
  assert.equal(isDark(stale), false);
  assert.equal(absenceLine(stale), null);
});

test("unknown is never narrated as absence", () => {
  const unk = { ...DARK_NUTRITION, absence: { ...DARK_NUTRITION.absence, state: "unknown" } };
  assert.equal(isDark(unk), false);
  assert.equal(absenceLine(unk), null);
});

/* ── the copy ────────────────────────────────────────────────────────────── */

test("the family chip says nothing is logged — never a trend verb", () => {
  const chip = absenceLine(DARK_NUTRITION, { short: true });
  assert.equal(chip, "nothing logged this cycle");
  assert.ok(!/eased off|slipping|holding steady|on the up/i.test(chip));
});

test("a never-logged channel gets NO day-count attached (#2382)", () => {
  const chip = absenceLine(DARK_NUTRITION, { short: true });
  assert.ok(!/\d+\s*days?/.test(chip), `never_logged must not carry a gap number: ${chip}`);
});

test("a real in-window pause reports its measured gap", () => {
  const paused = {
    ...DARK_NUTRITION,
    absence: { ...DARK_NUTRITION.absence, transition: "paused", last_log_date: "2026-08-04", days_since_last_log: 5, days_dark: 5 },
  };
  assert.equal(absenceLine(paused, { short: true }), "nothing logged for 5 days");
});

test("a dark pillar with no transition kind still says nothing logged", () => {
  const consistency = { name: "consistency", raw_score: 4, absence: { state: "dark", transition: null, days_dark: 12, days_since_last_log: null } };
  assert.equal(absenceLine(consistency, { short: true }), "nothing logged for 12 days");
});

/* ── the cockpit's deterministic read ────────────────────────────────────── */

test("the cockpit fallback no longer says a dark pillar is slipping", () => {
  const read = deterministicPillarRead("Nutrition", DARK_NUTRITION);
  assert.ok(!/slipping|climbing|holding/.test(read), read);
  assert.ok(/nothing is being logged/i.test(read));
  assert.ok(read.includes("1"), "the real score is still disclosed, just not narrated as a decline");
});

test("a reporting pillar keeps its correlative trend read", () => {
  const read = deterministicPillarRead("Sleep", LIVE_SLEEP);
  assert.ok(/Sleep is at 71 and climbing/.test(read), read);
});

/* ── the string-attribute bug (cockpit.js:520-522) ───────────────────────── */

// The exact /api/coach_analysis shape the site API serves: `analysis` is a STRING.
const LIVE_COACH_PAYLOAD = {
  coach_id: "nutrition_coach",
  coach_name: "Dr. Marcus Webb",
  domain: "nutrition",
  analysis: "Protein intake has no logged days this cycle, so nothing can be graded yet.",
  key_recommendation: "Log one full day before we read anything into the macros.",
  confidence_language: "preliminary",
  generated_at: "2026-08-09T04:12:00Z",
  regeneration_paused: false,
};

test("the served coach read survives — the old code read attributes off a string", () => {
  // Reproduce the defect: `const a = data.analysis || …` then `a.summary` etc.
  const a = LIVE_COACH_PAYLOAD.analysis || LIVE_COACH_PAYLOAD;
  assert.equal(a.summary ?? a.analysis ?? a.read, undefined, "the old read really did yield undefined");

  const r = coachPayloadRead(LIVE_COACH_PAYLOAD);
  assert.equal(r.text, LIVE_COACH_PAYLOAD.analysis);
  assert.equal(r.action, LIVE_COACH_PAYLOAD.key_recommendation);
  assert.equal(r.confidence, "preliminary");
});

test("a nested-object analysis shape still reads", () => {
  const r = coachPayloadRead({ analysis: { summary: "nested summary", action: "do the thing", n: 40 } });
  assert.equal(r.text, "nested summary");
  assert.equal(r.action, "do the thing");
  assert.equal(r.confidence, "n=40");
});

test("an empty / null payload yields empty strings, never a crash", () => {
  for (const bad of [null, undefined, "", 7, { analysis: null }, { coach_id: null, domain: "consistency", analysis: null }]) {
    const r = coachPayloadRead(bad);
    assert.equal(r.text, "");
    assert.equal(r.action, "");
  }
});

test("small-n coach observations still degrade to the honest confidence label", () => {
  assert.equal(coachPayloadRead({ analysis: "x", n: 8 }).confidence, "preliminary pattern");
  assert.equal(coachPayloadRead({ analysis: "x", observations: 20 }).confidence, "low confidence (n<30)");
});

/* ── the family panel's gating decision (story.js okayStatus) ────────────── */

test("the family chip refuses a trend verb on a dark pillar — the #2388 headline", () => {
  const chip = familyChip(DARK_NUTRITION, "down");
  assert.deepEqual(chip, { txt: "nothing logged this cycle", state: "absent" });
  // The exact live sentence this replaces.
  assert.ok(!/eased off/i.test(chip.txt));
});

test("a reporting pillar is not gated — story.js keeps its trend copy", () => {
  assert.equal(familyChip(LIVE_SLEEP, "up"), null);
  assert.equal(familyChip(LIVE_SLEEP, "down"), null);
});

test("flagged absent behaviors on a down trend name the absence, not the trend", () => {
  const partial = { name: "consistency", xp_delta: -0.3, absent_behaviors: ["habit_ticks"] };
  assert.deepEqual(familyChip(partial, "down"), { txt: "some days went unlogged", state: "absent" });
  // …and never on an UP trend: unlogged days can't be used to sour a real climb either.
  assert.equal(familyChip(partial, "up"), null);
});

test("a pillar with neither a dark source nor flagged absences is never gated", () => {
  assert.equal(familyChip({ name: "mind", absent_behaviors: [] }, "down"), null);
  assert.equal(familyChip(null, "down"), null);
});
