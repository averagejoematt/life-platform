// tests/js/v7_follow.test.mjs — #4182: the v7 "Follow" page's pure functions.
//
// The fixtures are the live shapes captured 2026-09-26 (scratchpad b2: /api/content_cadence,
// /api/journey, /journal/posts.json's `pending`) trimmed to what each function reads.
// Nothing here reads the wall clock.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const F = await import("../../site/assets/js/v7_follow.js");

const CAD = { chronicle: { paused: false, next_date: "2026-09-30", display: "Next Chronicle installment drafted Wednesday, September 30 — publishes once Matthew reviews and approves the draft." } };
const JOURNEY = { journey: { started_date: "2026-09-06", last_weighin_date: "2026-09-26", day_n: 21 } };

test("the weigh-in line is entry_age's one spelling: due through the PT day, then the counted silence (R6 fix 4)", () => {
  assert.deepEqual(F.weighInLine(JOURNEY, "2026-09-26"), { text: "The next weigh-in is due Sunday, September 27.", day: "2026-09-27" });
  assert.deepEqual(F.weighInLine(JOURNEY, "2026-09-27"), { text: "The next weigh-in is due Sunday, September 27.", day: "2026-09-27" });
  // a skipped week: the absence branch, the margin on the last weigh-in
  assert.deepEqual(F.weighInLine({ journey: { last_weighin_date: "2026-09-21" } }, "2026-09-26"), { text: "No weigh-in since Monday, September 21 — 5 days.", day: "2026-09-21" });
  // a month boundary rolls over, pinned to UTC noon so no viewer's offset moves it
  assert.equal(F.weighInLine({ journey: { last_weighin_date: "2026-09-30" } }, "2026-09-26").day, "2026-10-01");
  assert.deepEqual(F.weighInLine({ journey: { last_weighin_date: null } }, "2026-09-26"), { text: "", day: "" });
  assert.deepEqual(F.weighInLine(null, "2026-09-26"), { text: "", day: "" });
  assert.deepEqual(F.weighInLine({ journey: { last_weighin_date: "not a date" } }, "2026-09-26"), { text: "", day: "" });
  assert.equal(F.nextWeighIn, undefined, "the '+ 1 day' spelling is gone; entry_age carries the one rule");
});

test("what you'd get: the next write-up's day in words from the cadence (the cadence itself is the fold's derived line)", () => {
  assert.equal(F.writeUpLine(CAD, null), "The next write-up is drafted Wednesday, September 30 and publishes once Matthew has read it.");
  assert.equal(F.returnLine(CAD, null), "Next write-up: Wednesday, September 30.");
  assert.equal(F.returnDay(CAD, null), "2026-09-30");
});

test("a held draft's served words win over the cadence date; a paused cadence keeps its own words", () => {
  const pending = { display: "This week's write-up is drafted and waiting for Matthew to read it.", expected_date: "2026-10-02" };
  assert.equal(F.writeUpLine(CAD, pending), "This week's write-up is drafted and waiting for Matthew to read it.");
  assert.equal(F.returnLine(CAD, pending), "This week's write-up is drafted and waiting for Matthew to read it.");
  assert.equal(F.returnDay(CAD, pending), "2026-10-02");
  const paused = { chronicle: { paused: true, next_date: null, display: "The write-up is paused between experiments" } };
  assert.equal(F.returnLine(paused, null), "The write-up is paused between experiments.");
  assert.equal(F.returnDay(paused, null), "");
  assert.equal(F.writeUpLine(paused, null), "The write-up is paused between experiments.");
});

test("nothing served → empty strings, never an ISO date or 'undefined' for the reader", () => {
  for (const cad of [null, {}, { chronicle: null }, { chronicle: { paused: false, next_date: "" } }]) {
    assert.equal(F.writeUpLine(cad, null), "");
    assert.equal(F.returnLine(cad, null), "");
    assert.equal(F.returnDay(cad, null), "");
  }
  assert.ok(!F.writeUpLine(CAD, null).includes("2026-"), "the line is in words, not ISO");
});
