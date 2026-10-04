// tests/js/ck_depth_4586.test.mjs — #4586: the detail layer — a page per day and a page per
// trend. Driven from the committed live captures in tests/fixtures/kit_pages_4586/; no
// builder reads the wall clock.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const D = await import("../../site/assets/js/ck_depth.js");
const FIX = join(dirname(fileURLToPath(import.meta.url)), "..", "fixtures", "kit_pages_4586");
const load = (name) => JSON.parse(readFileSync(join(FIX, `${name}.json`), "utf8"));
const SRC = { pulse: load("pulse_history"), workouts: load("workouts"), training: load("training_overview"), nutrition: load("nutrition_overview") };
const BASE = "/next/v8/";

test("a lift is summarised by its working sets, in pounds, warm-ups set aside", () => {
  const bench = SRC.workouts.workouts.find((w) => w.date === "2026-10-02").exercises.find((e) => e.name === "Bench Press (Barbell)");
  assert.equal(D.liftSummary(bench), "3 sets at 175 lb: 12, 12 and 10 reps; 1 set at 135 lb: 12 reps");
  assert.equal(D.liftSummary({ sets: [{ type: "warmup", reps: 10, weight_kg: 20 }] }), "1 warm-up set only.");
  assert.equal(D.liftSummary({ sets: [] }), "");
});

test("a day lists what was lifted, each exercise a door to its own trend", () => {
  const html = D.dayLiftsHTML("2026-10-02", SRC, BASE);
  assert.match(html, /155 minutes, 7 exercises\. Each one opens its own trend\./);
  assert.match(html, /href="\/next\/v8\/trend\/\?m=lift&amp;x=Bench%20Press%20\(Barbell\)">Bench Press \(Barbell\)<\/a>/);
  assert.match(html, /Warm-up: Cycling, Stretching\./);
  assert.doesNotMatch(html, /warm-up set only/);
});

test("a day with no lifting says what else was recorded, or that nothing was", () => {
  assert.match(D.dayLiftsHTML("2026-10-03", SRC, BASE), /Also that day: 241 minutes of walking\./);
  assert.match(D.dayLiftsHTML("2026-01-01", SRC, BASE), /No training was recorded on this day\./);
});

test("the day's numbers are doors to their trends, and a missing reading is left out", () => {
  const html = D.dayFactsHTML("2026-10-02", SRC, BASE);
  assert.match(html, /href="\/next\/v8\/trend\/\?m=steps">1,113<\/a>/);
  assert.match(html, /href="\/next\/v8\/trend\/\?m=weight">311\.0 lb<\/a>/);
  const noWeight = { ...SRC, pulse: { pulse_history: [{ date: "2026-10-02", sleep_hours: 8.4 }] } };
  assert.doesNotMatch(D.dayFactsHTML("2026-10-02", noWeight, BASE), /Weight/);
  assert.match(D.dayFactsHTML("2026-01-01", SRC, BASE), /Nothing was measured on this day\./);
});

test("food is the day's totals against the floor; no log entry is shown", () => {
  const html = D.dayFoodHTML("2026-10-02", SRC, BASE);
  assert.match(html, /1,568 kcal/);
  assert.match(html, /172 g, at or above the 170 g floor/);
  assert.match(D.dayFoodHTML("2026-10-03", SRC, BASE), /153 g, under the 170 g floor/);
  assert.match(D.dayFoodHTML("2026-01-01", SRC, BASE), /No food was logged on this day\./);
});

test("a trend drops gaps instead of drawing zeroes, and today's unfinished count is left out", () => {
  const steps = D.seriesOf("steps", { pulse: { pulse_history: [{ date: "2026-10-01", steps: 6382 }, { date: "2026-10-02", steps: null }, { date: "2026-10-03", steps: 112 }] } }, "2026-10-03");
  assert.deepEqual(steps, [{ date: "2026-10-01", value: 6382 }]);
  assert.equal(D.seriesOf("weight", SRC).length, SRC.pulse.pulse_history.filter((r) => r.weight_lbs != null).length);
});

test("a lift's trend is its heaviest working set per session, oldest first", () => {
  const pts = D.liftSeries(SRC.workouts.workouts, "Bench Press (Barbell)");
  assert.ok(pts.length >= 3);
  assert.deepEqual(pts.map((p) => p.date), [...pts.map((p) => p.date)].sort());
  assert.equal(pts[pts.length - 1].value, 175);
  assert.deepEqual(D.liftSeries(SRC.workouts.workouts, "No Such Lift"), []);
});

test("the chart needs two readings; the sentence names the range and the count", () => {
  const pts = D.seriesOf("protein", SRC);
  const w = D.MEASURES.protein.write;
  assert.match(D.trendChartHTML(pts, w, "Protein"), /ck-chart__line/);
  assert.equal(D.trendChartHTML(pts.slice(0, 1), w, "Protein"), "");
  assert.match(D.trendSentence(pts, w), /^\d+ readings from September \d+ to October 3\. Lowest \d+ g, highest \d+ g, average \d+ g\.$/);
  assert.match(D.trendSentence(pts.slice(0, 1), w), /^One reading so far/);
});

test("recent readings link to their day; frequent meals name what is eaten most", () => {
  const rows = D.recentRowsHTML(D.seriesOf("steps", SRC), D.MEASURES.steps.write, BASE, 3);
  assert.equal((rows.match(/<li>/g) || []).length, 3);
  assert.match(rows, /href="\/next\/v8\/day\/\?d=2026-10-03"/);
  const meals = D.frequentMealsHTML(load("frequent_meals"));
  assert.match(meals, /What I logged most often over 29 days\./);
  assert.match(meals, /26 times<\/span><span>Morning Smoothies/);
  assert.equal(D.frequentMealsHTML({ meals: [] }), "");
});

test("the day page offers the day before and after only when they exist", () => {
  const nav = D.dayNavHTML("2026-10-03", SRC, BASE);
  assert.match(nav, /d=2026-10-02">← Friday</);
  assert.doesNotMatch(nav, /Sunday/);
});
