// tests/js/ck_sheet_not_scored_6224.test.mjs — #6224 (owner rulings 2026-11-26): Mind is not scored in public.
//
// /api/character serves Mind with `not_scored: true`, its reason, and no number. The sheet says WHY it is left out —
// "not scored in public, because the inputs are private" — and never "nothing records this area" (which would be false:
// something does record it; the record is private). Synthetic body only.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const S = await import("../../site/assets/js/ck_sheet.js");
const NOTE = "Not scored in public: its inputs are private.";
const mind = { name: "mind", level: null, raw_score: null, tier: null, not_instrumented: true, not_scored: true, not_scored_note: NOTE, coverage_hold: true };
const rel = { name: "relationships", level: 1, raw_score: 50, not_instrumented: true, coverage_hold: true };
const sleep = { name: "sleep", level: 9, raw_score: 72, not_instrumented: false, coverage_hold: false };

test("a pillar not scored in public gives its reason, never 'nothing records it' and never a number", () => {
  assert.equal(S.areaSentence(mind), NOTE);
  assert.equal(S.areaLevel(mind), "");
  assert.equal(S.areaSentence(rel), "Not measured yet: nothing records this area.");
});

test("the counts note names Mind as not scored in public, apart from the uninstrumented area", () => {
  const note = S.countsNote({ pillars: [sleep, mind, rel] });
  assert.match(note, /Mind is not scored in public, because the inputs are private, and is left out/);
  assert.match(note, /Relationships has nothing measuring it and is left out/);
  assert.doesNotMatch(note, /Mind has nothing measuring/);
});
