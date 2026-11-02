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

// ── M4 (#5586): the day's layers 2–3 ──
import { engineLine, engineRows, fellAsleep, foodRows, nearestGraded, recoveryRows, sessionLine, sessionRows, sessionTitle, stageRows, unservedText } from "../src/lib/day.js";

const W1029 = {
  title: "Foundation - Upper - 13 - 41",
  duration_min: 143,
  volume_kg: 7932.2,
  exercises: [
    {
      name: "Bench Press (Barbell)",
      sets: [
        { type: "warmup", reps: 8, weight_kg: 52.2, rpe: null },
        { type: "normal", reps: 4, weight_kg: 102.1, rpe: 9 },
        { type: "normal", reps: 5, weight_kg: 93, rpe: 8 },
      ],
    },
    { name: "Suitcase Carry", sets: [{ type: "normal", reps: null, weight_kg: 20, rpe: null }] },
    { name: "Treadmill", sets: [{ type: "normal", reps: null, weight_kg: null, rpe: null }] },
  ],
};

test("the session: title without counters, working sets, top set, warm-ups, no-load blocks", () => {
  assert.equal(sessionTitle(W1029.title), "Foundation · Upper");
  assert.equal(sessionLine({ ...W1029, exercises: Array(9).fill(W1029.exercises[0]) }), "143 minutes · 9 exercises · 7,932 kg moved (17,487 lb)");
  const [bench, carry, tread] = sessionRows(W1029);
  assert.deepEqual(bench.sets, ["4 × 102.1 kg @9", "5 × 93 kg @8"]);
  assert.equal(bench.top, "102.1 kg × 4");
  assert.equal(bench.warmups, 1);
  assert.equal(bench.heavy, true);
  assert.deepEqual(carry.sets, ["20 kg"]);
  assert.equal(carry.heavy, false);
  assert.equal(tread.noLoad, true);
  assert.equal(tread.top, "—");
});

test("the night: shares and both devices' hours; fell asleep in Pacific", () => {
  const night = { deep_pct: 14.4, rem_pct: 28.7, light_pct: 56.9, by_device: { eightsleep: { deep_hours: 1.1 }, whoop: null } };
  assert.equal(stageRows(night)[0].value, "14.4% of the night · 1.1 h bed · — strap");
  assert.equal(fellAsleep("2026-10-29T06:56:44.190Z"), "23:56 Pacific");
  assert.equal(fellAsleep(null), null);
});

test("recovery decomposed reads the exporter's normals; a missing reading is a dash, never zero", () => {
  const d = {
    sleep_target_h: 7.5,
    readings: { recovery_pct: 74, hrv_ms: 59.8, rhr_bpm: null, sleep_hours: 7.5 },
    normals: { recovery_pct: { mean7: 70.1 }, hrv_ms: { mean30: 57.7, n30: 30 }, rhr_bpm: { mean7: 52 }, sleep_hours: {} },
  };
  const [rec, hrv, rhr, sleep] = recoveryRows(d);
  assert.equal(rec.text, "74 of 100 · 7-day mean 70");
  assert.equal(hrv.text, "59.8 ms · 30-day mean 57.7 (n=30)");
  assert.equal(rhr.value, "—");
  assert.equal(rhr.width, 0);
  assert.equal(sleep.text, "7.5 h of a 7.5 h target");
});

test("food rows as logged; an unlogged macro says so", () => {
  const rows = foodRows({ calories: 80, protein_g: 15, carbs_g: 4, fat_g: null, floor_g: 170, tdee: 2619, logging_gap: true });
  assert.deepEqual(rows[0], ["Calories logged", "80 kcal · maintenance about 2,619"]);
  assert.deepEqual(rows[1], ["Protein", "15 g · floor 170 g"]);
  assert.deepEqual(rows[3], ["Fat", "not logged"]);
});

test("the engine: absent is 'absent', never 50", () => {
  const e = { level: 15, composite: 43.1, delta: 0.6, pillars: [{ name: "relationships", score: null, not_instrumented: true }, { name: "mind", score: 8.3, not_instrumented: false }] };
  assert.equal(engineLine(e), "Level 15 · composite 43.1 of 100 · up 0.6 since the morning before");
  const [rel, mind] = engineRows(e);
  assert.equal(rel.value, "absent");
  assert.equal(rel.width, 0);
  assert.equal(mind.low, true);
});

test("the nearest graded day before, and every unavailable state has its own sentence", () => {
  const days = [{ calls_settled: [{}] }, { calls_settled: [] }, { calls_settled: [] }];
  assert.equal(nearestGraded(days, 2), days[0]);
  assert.equal(nearestGraded(days, 0), null);
  assert.match(unservedText("food", "not logged", "Saturday 31 October"), /missing, not as eaten/);
  assert.match(unservedText("workout", "none logged", "Monday 26 October"), /^No gym session was logged on Monday 26 October\.$/);
  for (const [b, s] of [["workout", "older than the served window"], ["night", "none recorded"], ["night", "not served"], ["food", "older than the served window"]]) {
    assert.ok(!unservedText(b, s, "X").startsWith("Not readable"), `${b}/${s}`);
  }
});
