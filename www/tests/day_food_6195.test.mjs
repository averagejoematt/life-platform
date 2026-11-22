// #6195 (owner ruling 2026-11-22): a day page prints the window's maintenance estimate with the date it is from, and only
// when the snapshot says so. The generator (scripts/publish_snapshot_day.py) sends `tdee_as_of` only with the
// DAY_PAGE_MAINTENANCE_DATED switch on; without it the row is exactly as before.
import { test } from "node:test";
import assert from "node:assert/strict";

import { foodRows } from "../src/lib/day.js";

const food = { calories: 1000, protein_g: 150, carbs_g: 80, fat_g: 40, logging_gap: false, floor_g: 170, tdee: 3000 };

test("OFF: the calorie row is unchanged when the snapshot carries no as-of date", () => {
  assert.equal(foodRows(food)[0][1], "1,000 kcal · maintenance about 3,000");
});

test("ON: the maintenance figure carries the date it is from", () => {
  assert.equal(foodRows({ ...food, tdee_as_of: "2026-05-01" })[0][1], "1,000 kcal · maintenance about 3,000 (an estimate as of 1 May)");
});

test("ON: a day before the estimate existed prints no maintenance figure", () => {
  assert.equal(foodRows({ ...food, tdee: null, tdee_as_of: null })[0][1], "1,000 kcal");
});
