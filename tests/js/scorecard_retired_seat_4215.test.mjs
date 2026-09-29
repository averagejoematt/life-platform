// tests/js/scorecard_retired_seat_4215.test.mjs — a retired seat on /coaching/scorecard/
// is labelled and grouped apart, never a ninth live coach (#4215).
//
// The fixtures are the WIRE: reduced copies of /api/predictions (by_coach + the
// coach_id/coach_name/retired/pre_registered fields of its rows) and /api/coaches as
// served 2026-09-26 16:46Z. The two Dr. Sarah Chen rows are the cycle-17 pre-registration
// sealed at 2026-09-06T02:13:38Z, before #3520's cast guard — they stay on the record.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { scorecardSeats, retiredSeats, retiredSeatNote, rateText, rateWord } = await import("../../site/assets/js/coach_roster.js");

const bc = (total, decided, lifeTotal, lifeDecided) => ({ total, decided, pending: total - decided, lifetime: { total: lifeTotal, decided: lifeDecided } });
const BY_COACH = {
  sleep: bc(52, 12, 480, 40), training: bc(2, 0, 371, 9), nutrition: bc(40, 5, 487, 30), mind: bc(38, 3, 371, 20),
  physical: bc(51, 7, 452, 31), glucose: bc(47, 4, 398, 22), labs: bc(53, 3, 324, 18), explorer: bc(39, 3, 354, 19),
};
const NAMES = {
  sleep: "Dr. Lisa Park", physical: "Dr. Max Reyes", glucose: "Dr. Amara Patel", explorer: "Dr. Henning Brandt",
  nutrition: "Dr. Marcus Webb", mind: "Dr. Nathan Reeves", labs: "Dr. James Okafor", training: "Dr. Sarah Chen",
};
const PREDICTIONS = Object.keys(NAMES)
  .filter((c) => c !== "training")
  .map((c) => ({ coach_id: c, coach_name: NAMES[c], retired: false, pre_registered: true }))
  .concat([
    { coach_id: "training", coach_name: "Dr. Sarah Chen", retired: true, pre_registered: true, pre_registered_at: "2026-09-06T02:13:38.690141+00:00", metric: "steps" },
    { coach_id: "training", coach_name: "Dr. Sarah Chen", retired: true, pre_registered: true, pre_registered_at: "2026-09-06T02:13:38.690141+00:00", metric: "resting_heart_rate" },
  ]);
const DATA = { by_coach: BY_COACH, predictions: PREDICTIONS };
const API_COACHES = ["Dr. Eli Marsh", "Dr. Lisa Park", "Dr. Marcus Webb", "Dr. Nathan Reeves", "Dr. Max Reyes", "Dr. Amara Patel", "Dr. James Okafor", "Dr. Henning Brandt"];

test("the retired flag on the served rows puts the training seat in its own group", () => {
  assert.deepEqual([...retiredSeats(DATA)], ["training"]);
  const s = scorecardSeats(DATA);
  assert.deepEqual(s.retired, ["training"]);
  assert.ok(!s.live.includes("training"));
  assert.equal(s.live.length, 7);
  // by_coach.retired (once the server serves it) is honoured on its own too
  assert.deepEqual(scorecardSeats({ by_coach: { ...BY_COACH, training: { ...BY_COACH.training, retired: true } }, predictions: [] }).retired, ["training"]);
});

test("the label says why she still has calls — sealed, from the pre-registration, dated (never 'cycle')", () => {
  assert.equal(retiredSeatNote("training", DATA), "retired seat · 2 sealed calls from the pre-registration on September 6, graded like any other");
  // no served stamp → the date drops, never guessed; reader text never says "cycle"
  const noStamp = { ...DATA, predictions: PREDICTIONS.map((p) => ({ ...p, pre_registered_at: undefined })) };
  assert.equal(retiredSeatNote("training", noStamp), "retired seat · 2 sealed calls from the pre-registration, graded like any other");
  assert.equal(retiredSeatNote("training", { by_coach: { training: { total: 2 } }, predictions: [] }), "retired seat · 2 calls on the board, graded like any other");
  for (const d of [DATA, noStamp]) assert.ok(!/cycle|reset/i.test(retiredSeatNote("training", d)));
  assert.equal(retiredSeatNote("training", { by_coach: { training: { total: 0 } }, predictions: [] }), "retired seat · career record kept on file");
});

test("guard: the untagged scorecard names are /api/coaches' names (minus the lead, who makes no graded calls)", () => {
  const untagged = new Set(scorecardSeats(DATA).live.map((c) => NAMES[c]));
  const roster = new Set(API_COACHES);
  for (const n of untagged) assert.ok(roster.has(n), `${n} is on the scorecard untagged but not on /api/coaches`);
  const missing = API_COACHES.filter((n) => !untagged.has(n));
  assert.deepEqual(missing, ["Dr. Eli Marsh"]);
  for (const c of scorecardSeats(DATA).retired) assert.ok(!roster.has(NAMES[c]));
});

// #4220 box 3 (it rides this file: the same scorecard, the same pure roster module). Live
// 2026-09-29 16:24Z: /api/predictions by_coach served Webb 0/9 (0.0), Brandt 3/7 (42.9),
// Park 8/19 (42.1), labs 2/2 (100.0), percent_floor 10. The scorecard printed "0%",
// "42.9%" and "100%" on nine, seven and two calls.
test("#4220: below the served floor a coach's rate is counts, never a percentage", () => {
  assert.equal(rateText(0, 9, 0.0, 10), "0 of 9");
  assert.equal(rateText(3, 7, 42.9, 10), "3 of 7");
  assert.equal(rateText(2, 2, 100.0, 10), "2 of 2");
  assert.equal(rateWord(9, 10), "came true");
  // at or above the floor the served percentage rides
  assert.equal(rateText(8, 19, 42.1, 10), "42.1%");
  assert.equal(rateWord(19, 10), "hit rate");
  assert.equal(rateText(4, 10, 40.0, 10), "40%");
  // nothing decided is "—", never "0%"; a missing floor falls back to 10, never to "always %"
  assert.equal(rateText(0, 0, null, 10), "—");
  assert.equal(rateText(0, 9, 0.0, undefined), "0 of 9");
  // a decided count with no served percentage still prints counts rather than "null%"
  assert.equal(rateText(12, 20, null, 10), "12 of 20");
  for (const [k, n, p] of [[0, 9, 0], [3, 7, 42.9], [2, 2, 100], [5, 7, 71.4]]) assert.ok(!rateText(k, n, p, 10).includes("%"));
});
