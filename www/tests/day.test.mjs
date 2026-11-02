// The Day object's vocabulary (#5585): the sentence, the deltas, the strip window, the sparkline.
import { test } from "node:test";
import assert from "node:assert/strict";

import { READING_TILES, deltaLine, dekSentence, plain, signed, sinceWords, sparkline, stripWindow } from "../src/lib/day.js";

const KEYS = READING_TILES.map((t) => t.key);
const norm = (o = {}) => Object.fromEntries(KEYS.map((k) => [k, { mean7: null, n7: 0, mean30: null, n30: 0, ...(o[k] || {}) }]));
const day = (date, readings, normals = {}) => ({ date, readings: { ...Object.fromEntries(KEYS.map((k) => [k, null])), ...readings }, normals: norm(normals) });
const tile = (k) => READING_TILES.find((t) => t.key === k);

test("the dek reads the owner's sentence: weight against the previous weigh-in, sleep, recovery", () => {
  // /api/pulse_history, 28 and 29 October 2026 (the acceptance line of #5585)
  const wed = day("2026-10-28", { weight_lbs: 297.9 });
  const thu = day("2026-10-29", { weight_lbs: 295.7, sleep_hours: 7.5, recovery_pct: 74 });
  assert.equal(dekSentence(thu, wed), "295.7 lb (down 2.2 since Wednesday). slept 7.5 hours. recovery 74.");
  assert.equal(dekSentence(day("2026-09-07", { sleep_hours: 8.4, recovery_pct: 76 }), null), "no weigh-in. slept 8.4 hours. recovery 76.");
  assert.equal(dekSentence(day("2026-10-30", { weight_lbs: 295.7 }), thu), "295.7 lb (unchanged since Thursday).");
});

test("a weigh-in more than six days back is named by its date, never an ambiguous weekday", () => {
  assert.equal(sinceWords("2026-10-28", "2026-10-29"), "Wednesday");
  assert.equal(sinceWords("2026-10-10", "2026-10-29"), "10 October");
});

test("deltas: against the 7-day mean; HRV against the 30-day mean with its n; a missing reading says so", () => {
  const d = day("2026-10-29", { weight_lbs: 295.7, hrv_ms: 59.8, steps: 9099 }, { weight_lbs: { mean7: 298.5, n7: 7 }, hrv_ms: { mean7: 57, n7: 7, mean30: 57.7, n30: 30 }, steps: { mean7: 9604, n7: 7 } });
  assert.equal(deltaLine(d, tile("weight_lbs")), "−2.8 vs 7-day mean");
  assert.equal(deltaLine(d, tile("hrv_ms")), "+2.1 vs his 30-day mean of 57.7 (n=30)");
  assert.equal(deltaLine(d, tile("steps")), "−505 vs 7-day mean");
  assert.equal(deltaLine(d, tile("rhr_bpm")), "no reading");
  assert.equal(deltaLine(day("2026-10-29", { strain: 10 }, { strain: { mean7: 10, n7: 1 } }), tile("strain")), "no other reading in seven days");
});

test("no bare percentage anywhere in the tile vocabulary", () => {
  for (const t of READING_TILES) assert.ok(!t.unit.includes("%"), t.key);
  assert.equal(signed(0.04, 1), "0.0");
  assert.equal(plain(8, 1), "8");
});

test("the strip is the fourteen days ending on this one", () => {
  const days = Array.from({ length: 20 }, (_, i) => ({ id: String(i) }));
  assert.deepEqual(stripWindow(days, 19).map((d) => d.id), Array.from({ length: 14 }, (_, i) => String(i + 6)));
  assert.equal(stripWindow(days, 3).length, 4);
});

test("the sparkline carries readable points, marks the day, dashes the mean and has no text to shrink", () => {
  const rows = [day("2026-10-27", { weight_lbs: 299.1 }), day("2026-10-28", { weight_lbs: 297.9 }), day("2026-10-29", { weight_lbs: 295.7 })];
  const svg = sparkline({ rows, tile: tile("weight_lbs"), markDate: "2026-10-29", mean: 298.5 });
  const pts = JSON.parse(svg.match(/data-points="([^"]*)"/)[1].replace(/&quot;/g, '"'));
  assert.equal(pts.length, 3);
  assert.equal(pts[2].label, "Thursday 29 October · 295.7 lb");
  assert.ok(svg.includes('class="mean"') && svg.includes('class="mark"'));
  assert.ok(!/<text/.test(svg));
  assert.ok(!/\d{4}-\d{2}-\d{2}/.test(svg.replace(/data-points="[^"]*"/, "")), "no ISO date outside the data attribute");
  assert.ok(!sparkline({ rows: rows.slice(0, 1), tile: tile("weight_lbs"), markDate: "2026-10-27", mean: null }).includes("data-points"));
});
