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
  assert.match(html, /155 minutes in the session, 22,356 lb moved in working sets\. Warm-up sets are left out; each lift opens its own trend\./);
  assert.match(html, /href="\/next\/v8\/trend\/\?m=lift&amp;x=Bench%20Press%20\(Barbell\)&amp;from=2026-10-02">Bench Press \(Barbell\)<\/a>/);
  assert.match(html, /Also in the session: Cycling \(11\.8 miles\), Stretching\./);
  assert.doesNotMatch(html, /[Ww]arm-up: Cycling/, "timed work is not a warm-up");
});

test("a day with no lifting says what else was recorded, or that nothing was", () => {
  assert.match(D.dayLiftsHTML("2026-10-03", SRC, BASE), /Also that day: 241 minutes of walking\./);
  assert.match(D.dayLiftsHTML("2026-01-01", SRC, BASE), /No training was recorded on this day\./);
});

test("the day's numbers are doors to their trends, and a missing reading is left out", () => {
  const html = D.dayFactsHTML("2026-10-02", SRC, BASE);
  assert.match(html, /href="\/next\/v8\/trend\/\?m=steps&amp;from=2026-10-02">Steps: 1,113 </);
  assert.match(html, /href="\/next\/v8\/trend\/\?m=weight&amp;from=2026-10-02">Weight: 311\.0 lb </);
  assert.match(D.dayFactsHTML("2026-10-02", SRC, BASE, "2026-10-02"), /Steps: 1,113 so far today/);
  const noWeight = { ...SRC, pulse: { pulse_history: [{ date: "2026-10-02", sleep_hours: 8.4 }] } };
  assert.doesNotMatch(D.dayFactsHTML("2026-10-02", noWeight, BASE), /Weight/);
  assert.match(D.dayFactsHTML("2026-01-01", SRC, BASE), /Nothing was measured on this day\./);
});

test("food is the day's totals against the floor; no log entry is shown", () => {
  const html = D.dayFoodHTML("2026-10-02", SRC, BASE);
  assert.match(html, /1,568 kcal/);
  assert.match(html, /Protein: 172 g, at or above the 170 g floor/);
  assert.match(D.dayFoodHTML("2026-10-03", SRC, BASE), /Protein: 153 g, under the 170 g floor/);
  assert.match(D.dayFoodHTML("2026-01-01", SRC, BASE), /No food was logged on this day\./);
});

test("a trend drops gaps instead of drawing zeroes, and today's unfinished count is left out", () => {
  const steps = D.seriesOf("steps", { pulse: { pulse_history: [{ date: "2026-10-01", steps: 6382 }, { date: "2026-10-02", steps: null }, { date: "2026-10-03", steps: 112 }] } }, "2026-10-03");
  assert.deepEqual(steps, [{ date: "2026-10-01", value: 6382 }]);
  assert.equal(D.seriesOf("weight", SRC).length, SRC.pulse.pulse_history.filter((r) => r.weight_lbs != null).length);
});

test("a lift's trend is its best set per session by estimated one-rep max, oldest first", () => {
  const pts = D.liftSeries(SRC.workouts.workouts, "Bench Press (Barbell)");
  assert.ok(pts.length >= 3);
  assert.deepEqual(pts.map((p) => p.date), [...pts.map((p) => p.date)].sort());
  const last = pts[pts.length - 1];
  assert.equal(last.set, "175 lb × 12");
  assert.equal(last.value, 245, "175 x (1 + 12/30)");
  // Mutation control: by heaviest load alone the same session would read as a DROP from 205.
  const heavier = pts.find((p) => p.set === "205 lb × 5");
  assert.ok(heavier && heavier.value < last.value, "12 reps at 175 outranks 5 reps at 205");
  assert.equal(D.epley(200, 1), 200);
  assert.equal(D.epley(null, 5), null);
  assert.deepEqual(D.liftSeries(SRC.workouts.workouts, "No Such Lift"), []);
  const pullups = [{ date: "2026-10-01", exercises: [{ name: "Pull Up", sets: [{ type: "normal", reps: 8, weight_kg: null }, { type: "normal", reps: 6, weight_kg: 0 }] }] }];
  assert.deepEqual(D.liftSeries(pullups, "Pull Up"), [{ date: "2026-10-01", value: 8, set: "8 reps", bodyweight: true }]);
});

test("the chart needs two readings; a count is drawn from zero, a level as a line alone", () => {
  const pts = D.seriesOf("protein", SRC);
  const w = D.MEASURES.protein.write;
  assert.match(D.trendChartHTML(pts, w, "Protein", { fromZero: true }), /ck-chart__area/);
  assert.doesNotMatch(D.trendChartHTML(pts, w, "Protein"), /ck-chart__area/);
  assert.match(D.trendChartHTML(pts, w, "Protein"), /ck-chart__line/);
  assert.equal(D.trendChartHTML(pts.slice(0, 1), w, "Protein"), "");
});

test("the sentence gives count and range, an average only when asked, and days at the floor", () => {
  const pts = D.seriesOf("protein", SRC);
  const w = D.MEASURES.protein.write;
  assert.match(D.trendSentence(pts, w, { average: true, floor: 170, floorWords: "my 170 g floor" }), /^28 readings from September 6 to October 3\. Lowest 89 g, highest 245 g, average 148 g\. At or above my 170 g floor on 9 of 28 days\.$/);
  assert.doesNotMatch(D.trendSentence(pts, w, { average: false }), /average/);
  assert.match(D.trendSentence(pts.slice(0, 1), w), /^One reading so far/);
  assert.equal(D.weekOnWeek(pts, w), "The last seven readings average 133 g; the seven before, 159 g.");
  assert.equal(D.weekOnWeek(pts.slice(0, 13), w), "");
});

test("the newest week of readings is on the page and the rest is one tap away", () => {
  const rows = D.recentRowsHTML(D.seriesOf("steps", SRC), D.MEASURES.steps.write, BASE, 3);
  assert.match(rows, /href="\/next\/v8\/day\/\?d=2026-10-03">Oct 3 · Saturday · 9,913 </);
  assert.match(rows, /<details><summary>The \d+ earlier readings<\/summary>/);
  assert.equal((rows.split("<details>")[0].match(/<li>/g) || []).length, 3);
  const lift = D.recentRowsHTML(D.liftSeries(SRC.workouts.workouts, "Bench Press (Barbell)"), (v) => `${v} lb`, BASE);
  assert.match(lift, /Oct 2 · Friday · 175 lb × 12 · est\. max 245 lb/);
});

test("frequent foods are named as foods with protein per serving; related trends carry the day", () => {
  const meals = D.frequentMealsHTML(load("frequent_meals"));
  assert.match(meals, /The foods I logged most often over 29 days, with the protein in one serving\./);
  assert.match(meals, /26 times<\/span><span>Morning Smoothies/);
  assert.equal(D.frequentMealsHTML({ meals: [] }), "");
  assert.match(D.relatedHTML("protein", BASE, "2026-10-02"), /trend\/\?m=calories&amp;from=2026-10-02">Calories /);
  assert.equal(D.relatedHTML("nope", BASE), "");
});

test("the day page offers the day before and after only when they exist", () => {
  const nav = D.dayNavHTML("2026-10-03", SRC, BASE);
  assert.match(nav, /d=2026-10-02">← Friday</);
  assert.doesNotMatch(nav, /Sunday/);
});

test("a daily count is drawn as bars from zero, with the target and the days that met it", () => {
  const pts = D.seriesOf("protein", SRC);
  const html = D.barChartHTML(pts, D.MEASURES.protein.write, "Protein", { target: 170, targetWords: "the 170 g floor" });
  assert.equal((html.match(/<rect /g) || []).length, pts.length, "one bar per day");
  assert.equal((html.match(/<rect class="ck-chart__now"/g) || []).length, pts.filter((p) => p.value >= 170).length, "a dark bar for each day at the floor");
  assert.match(html, /stroke-dasharray/);
  assert.match(html, /Dashed line: the 170 g floor\. Dark bars are days at or above it\. The line is the average of the seven days ending on that day\./);
  assert.doesNotMatch(html, /<text/, "no text inside the drawing");
  const plain = D.barChartHTML(pts, D.MEASURES.protein.write, "Protein");
  assert.doesNotMatch(plain, /ck-chart__now|stroke-dasharray|Dashed/, "no target given, none drawn");
  assert.equal(D.barChartHTML(pts.slice(0, 1), D.MEASURES.protein.write, "Protein"), "");
});

test("each lift on a day says what the best set was last time, and the session's total load", () => {
  const html = D.dayLiftsHTML("2026-10-02", SRC, BASE);
  assert.match(html, /Bench Press \(Barbell\)<\/a><span>3 sets at 175 lb[^<]*<\/span><span class="ck-small">Last time, Sep 29: 205 lb × 5\.<\/span>/);
  assert.match(html, /155 minutes in the session, [\d,]+ lb moved in working sets\./);
  const first = { ...SRC, workouts: { workouts: SRC.workouts.workouts.filter((w) => w.date >= "2026-10-02") } };
  assert.match(D.dayLiftsHTML("2026-10-02", first, BASE), /First time recorded\./);
});

test("macro share is worked from the logged grams and needs all three", () => {
  assert.equal(D.macroShare({ protein_g: 172, carbs_g: 118, fat_g: 48 }), "Of the calories from those three: protein 43%, carbs 30%, fat 27%.");
  assert.equal(D.macroShare({ protein_g: 172, carbs_g: null, fat_g: 48 }), "");
  assert.match(D.dayFoodHTML("2026-10-02", SRC, BASE), /Of the calories from those three: protein 43%/);
});

test("the steps trend says how steps are counted and that some days read low", () => {
  assert.match(D.MEASURES.steps.about, /A day they were not carried reads low/);
});

test("a measure name from the address bar finds only real measures", () => {
  for (const hostile of ["constructor", "toString", "__proto__", "hasOwnProperty"]) {
    assert.equal(D.isMeasure(hostile), false, hostile);
    assert.deepEqual(D.seriesOf(hostile, SRC), [], hostile);
  }
  assert.equal(D.isMeasure("steps"), true);
});

test("the index lists every measure once, in four areas, and no list of lifts", () => {
  const html = D.trendIndexHTML(BASE);
  for (const area of ["Body", "Food", "Training", "Sleep"]) assert.match(html, new RegExp(`<p class="ck-label">${area}</p>`));
  const listed = D.TREND_AREAS.flatMap((a) => a.measures);
  assert.deepEqual([...listed].sort(), Object.keys(D.MEASURES).sort(), "every measure is in exactly one area");
  assert.doesNotMatch(html, /Each lift|m=lift/, "a lift's trend is reached from the lift on a day page, never from a menu");
});
