// tests/js/projected_year_4766.test.mjs — #4766.
//
// /data/physical/ printed the goal projection as "between Friday, July 2 and Saturday,
// September 18" — a 2027 window with no year, which a reader in October 2026 reads as dates
// already past (the Visual QA truth check's temporal_contradiction). weightGoalLine now opts
// in to dayInWords' { yearIfNotCurrent } spelling; `now` is pinned so the test is clock-free.

import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { weightGoalLine } = await import("../../site/assets/js/evidence_body.js");

const J = { goal_weight_lbs: 185, remaining_lbs: 100, weekly_rate_lbs: -1.2, projected_goal_date: "2027-08-10" };
const NOW_2026 = new Date("2026-10-10T20:00:00Z");

test("#4766 a next-year projection window prints its year at both ends", () => {
  const line = weightGoalLine({ ...J, projected_goal_date_earliest: "2027-07-02", projected_goal_date_latest: "2027-09-18" }, NOW_2026);
  assert.match(line, /Projected to reach 185 between Friday, July 2, 2027 and Saturday, September 18, 2027\./);
});

test("#4766 a single next-year projected date prints its year", () => {
  assert.match(weightGoalLine(J, NOW_2026), /Projected to reach 185 around Tuesday, August 10, 2027\./);
});

test("#4766 a same-year end stays year-less; the other end still carries its year", () => {
  const line = weightGoalLine({ ...J, projected_goal_date_earliest: "2026-12-20", projected_goal_date_latest: "2027-02-11" }, NOW_2026);
  assert.match(line, /between Sunday, December 20 and Thursday, February 11, 2027\./);
});
