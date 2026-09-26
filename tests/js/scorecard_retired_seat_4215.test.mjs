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

const { scorecardSeats, retiredSeats, retiredSeatNote } = await import("../../site/assets/js/coach_roster.js");

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

test("the label says why she still has calls — sealed, from the pre-registration", () => {
  assert.equal(retiredSeatNote("training", DATA), "retired seat · 2 sealed calls from this cycle's pre-registration, graded like any other");
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
