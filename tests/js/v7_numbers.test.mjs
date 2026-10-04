// tests/js/v7_numbers.test.mjs — the pure helpers of site/assets/js/v7_numbers.js (#4182, the v7
// "His numbers" page). Every helper takes its inputs explicitly, so nothing here reads the wall
// clock; the fixtures are the served shapes of 2026-09-26 (scratchpad b2 + the live freshness).
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

// charts.js (a static import of v7_numbers.js) pulls "/assets/js/svgtype.js" — a root-relative
// specifier the loader hook rewrites — so the module under test is imported dynamically, after
// the hook above has registered (the same reason tests/js/charts.test.mjs does this).
// evidence_sleep.js (one of the pure halves this page reuses) imports explain.js, whose
// once-wiring touches window/document at import time — the same reason
// scripts/import_site_js_graph.mjs runs under a minimal shim. Enough surface for the guards to
// take their no-op branch; the page's own boot guard finds no #nm-weight and never runs main().
if (typeof globalThis.window === "undefined") {
  const noop = () => {};
  globalThis.document = { readyState: "complete", body: {}, addEventListener: noop, getElementById: () => null, querySelector: () => null, querySelectorAll: () => [] };
  globalThis.window = { document: globalThis.document, addEventListener: noop, removeEventListener: noop, requestAnimationFrame: (cb) => setTimeout(cb, 0) };
}
const M = await import("../../site/assets/js/v7_numbers.js");
// The reader-visible text of an HTML fragment — the data-src attributes name served fields
// (days_dark, composite_pillar_count) and are not prose, so the vocabulary asserts read this.
// A character walk, not a tag-stripping regex: this is a test-side text extractor over the
// module's own output, never a sanitizer (CodeQL's incomplete-multi-character-sanitization).
const visible = (html) => {
  let out = "", inTag = false;
  for (const ch of String(html)) {
    if (ch === "<") inTag = true;
    else if (ch === ">") inTag = false;
    else if (!inTag) out += ch;
  }
  return out;
};

const JOURNEY = {
  start_weight_lbs: 327.3, goal_weight_lbs: 185.0, current_weight_lbs: 313.8, lost_lbs: 13.5, remaining_lbs: 128.8,
  weighin_count: 13, weekly_rate_lbs: -4.36, weekly_rate_ci_low: -4.74, weekly_rate_ci_high: -2.75, rate_provisional: true,
  weighin_span_days: 20, projected_goal_date: null, started_date: "2026-09-06", last_weighin_date: "2026-09-26", pre_start: false,
};

test("marginParts — a served date becomes the margin's day, month and weekday", () => {
  assert.deepEqual(M.marginParts("2026-09-26"), { d: "26", mo: "Sep", w: "Saturday" });
  assert.equal(M.marginParts("not a date"), null);
});

test("toCsv — a header row, one row per object, quoting only where a cell needs it", () => {
  const csv = M.toCsv([{ date: "2026-09-06", weight_lbs: 327.3 }, { date: "2026-09-12", weight_lbs: null, note: 'a "quoted", note' }], ["date", "weight_lbs", "note"]);
  assert.equal(csv, 'date,weight_lbs,note\n2026-09-06,327.3,\n2026-09-12,,"a ""quoted"", note"\n');
  assert.equal(M.toCsv([], ["a"]), "a\n");
  assert.equal(M.csvName("weight", "2026-09-26"), "weight_through_2026-09-26.csv");
  assert.equal(M.csvName("weight", null), "weight.csv");
});

test("weightGoalSentence — the rate with its interval and n, provisional, and the refusal verbatim", () => {
  const s = M.weightGoalSentence(JOURNEY);
  assert.match(s, /Goal <span data-src="api_journey.journey.goal_weight_lbs">185<\/span> lb; <span[^>]*>128\.8<\/span> lb to go\./);
  assert.match(s, /About <span data-src="api_journey.journey.weekly_rate_lbs">4\.4<\/span> lb a week down so far over <span[^>]*>13<\/span> weigh-ins, provisional; the likely range is <span[^>]*>2\.8<\/span> to <span[^>]*>4\.7<\/span>\./);
  assert.match(s, /No date to goal\.$/);
  assert.doesNotMatch(visible(s), /cycle|reset|attempt|as of/i);
  // R7 fix 5: a month, a year and the engine's range — "Tuesday, April 20" with no year read as a day already past
  assert.match(visible(M.weightGoalSentence({ ...JOURNEY, projected_goal_date: "2027-04-20" })), /At this rate the goal lands around April 2027\.$/);
  const ranged = visible(M.weightGoalSentence({ ...JOURNEY, projected_goal_date: "2027-06-09", projected_goal_date_earliest: "2027-05-22", projected_goal_date_latest: "2027-09-22" }));
  assert.match(ranged, /At this rate the goal lands around June 2027 — between May and September 2027\.$/);
  assert.doesNotMatch(ranged, /Wednesday, June 9|engine dates/);
  assert.match(visible(M.weightGoalSentence({ ...JOURNEY, projected_goal_date: "2027-12-20", projected_goal_date_earliest: "2027-11-02", projected_goal_date_latest: "2028-02-11" })), /around December 2027 — between November 2027 and February 2028\.$/);
  assert.equal(M.weightGoalSentence(null), "");
});

test("weightSeries / sleepSeries / eatingSeries — usable rows only, oldest first", () => {
  assert.deepEqual(M.weightSeries([{ date: "2026-09-12", weight_lbs: 319.7 }, { date: "2026-09-06", weight_lbs: "327.3" }, { date: "bad", weight_lbs: 1 }, { date: "2026-09-13" }]), [
    { date: "2026-09-06", weight_lbs: 327.3 }, { date: "2026-09-12", weight_lbs: 319.7 },
  ]);
  const sl = M.sleepSeries([{ date: "2026-09-07", hours: 7.9, recovery_score: 48, hrv: 31.3, rhr: 65, sleep_score: 87 }, { date: "2026-09-06", hours: null }]);
  assert.deepEqual(sl, [{ date: "2026-09-07", hours: 7.9, sleep_score: 87, recovery_score: 48, hrv: 31.3, rhr: 65 }]);
  const ea = M.eatingSeries([{ date: "2026-09-06", calories: 2142, protein_g: 131 }]);
  assert.deepEqual(ea, [{ date: "2026-09-06", calories: 2142, protein_g: 131, carbs_g: null, fat_g: null }]);
});

test("trainingSeries + barLabel — the day of the month every fifth day and at both ends, blank between", () => {
  const days = Array.from({ length: 21 }, (_, i) => ({ date: `2026-09-${String(6 + i).padStart(2, "0")}`, total_min: i % 3 === 0 ? 0 : 60 }));
  const rows = M.trainingSeries(days.slice().reverse());
  assert.equal(rows[0].date, "2026-09-06");
  assert.deepEqual(rows.map((r) => r.label), ["6", "", "", "", "10", "", "", "", "", "15", "", "", "", "", "20", "", "", "", "", "25", "26"]);
  assert.equal(M.barLabel("2026-10-01", 3, 9), "1");
});

test("trainingSentence — k of n days since the start, every count served, nothing invented", () => {
  const t = {
    training: { workouts_30d: 33, strength_sessions_30d: 19 },
    walking: { total_walks_30d: 14, avg_daily_steps: 2245, avg_daily_steps_n: 20 },
    weekly_trend: [{ week: "2026-W38", workouts: 12, minutes: 1300 }, { week: "2026-W39", workouts: 9, minutes: 1055 }],
    daily_modality_minutes_30d: [{ date: "2026-09-06", total_min: 65 }, { date: "2026-09-07", total_min: 0 }, { date: "2026-09-08", total_min: 120 }],
  };
  const s = M.trainingSentence(t, "2026-09-06");
  assert.match(s, /^Trained on <span[^>]*>2<\/span> of <span[^>]*>3<\/span> days since September 6\./);
  assert.match(s, /In the last thirty days: <span[^>]*>33<\/span> workouts, <span[^>]*>19<\/span> of them strength, <span[^>]*>14<\/span> walks\./);
  assert.match(s, /This calendar week so far: <span[^>]*>9<\/span> workouts, <span[^>]*>1,055<\/span> minutes\./);
  assert.match(s, /<span[^>]*>2,245<\/span> steps a day on average over <span[^>]*>20<\/span> days\.$/);
  assert.equal(M.trainingSentence({ daily_modality_minutes_30d: [] }, "2026-09-06"), "");
  assert.equal(M.trainingSentence({ daily_modality_minutes_30d: [{ date: "2026-09-06", total_min: 65 }] }, ""), 'Trained on <span data-src="api_training_overview.daily_modality_minutes_30d[].total_min">1</span> of <span data-src="api_training_overview.daily_modality_minutes_30d.length">1</span> days.');
});

test("flaggedByCategory / labsBars / labRows — k of n per category, flagged rows first, the share as the bar", () => {
  const bm = [
    { name: "Ldl C", value: 160, unit: "mg/dL", range: "0-99", flag: "H", category: "Lipids" },
    { name: "Hdl Large", value: 30, unit: "mg/dL", range: "20-60", flag: null, category: "Lipids" },
    { name: "Tsh", value: 2, unit: "mIU/L", range: "0.4-4.5", flag: "null", category: "Thyroid" },
    { name: "Ferritin", value: 10, unit: "ng/mL", range: "30-400", flag: "L", category: "Iron Metabolism" },
  ];
  assert.deepEqual(M.flaggedByCategory(bm), [{ label: "Lipids", flagged: 1, total: 2 }, { label: "Thyroid", flagged: 0, total: 1 }, { label: "Iron Metabolism", flagged: 1, total: 1 }]);
  const bars = M.labsBars(M.flaggedByCategory(bm));
  assert.match(bars, /Iron Metabolism.*width:100\.0%.*1<\/span> of <span[^>]*>1/s);
  assert.match(bars, /Lipids.*width:50\.0%/s);
  assert.doesNotMatch(bars, /Thyroid/);
  assert.equal(M.labsBars([{ label: "Thyroid", flagged: 0, total: 1 }]), "");
  const rows = M.labRows(bm);
  assert.deepEqual(rows.map((r) => [r.marker, r.flag]), [["LDL cholesterol", "high"], ["Ferritin", "low"], ["Large HDL particles", ""], ["TSH", ""]]);
});

const FRESH = {
  pacific_today: "2026-09-26",
  sources: [
    { id: "apple_health", status: "fresh", datatypes: [
      { key: "cgm", dark: true, age_days: 30, label: "CGM (glucose)" },
      { key: "blood_pressure", dark: true, age_days: 17 },
      { key: "state_of_mind", dark: true, age_days: 18 },
      { key: "water", dark: false, age_days: 0, last_seen: "2026-09-26" },
    ] },
    { id: "garmin", status: "paused", days_dark: 103 },
  ],
};
const PULSE = { pulse: { glyphs: { journal: { written_today: false, gap_days: 17 } } } };

test("absenceRows — the five, in order, each an absence with its served count; never 'went dark'", () => {
  const rows = M.absenceRows({ freshness: FRESH, pulse: PULSE });
  assert.deepEqual(rows.map((r) => r.id), ["journal", "cgm", "blood_pressure", "state_of_mind", "garmin"]);
  assert.match(rows[0].text, /^nothing written for <span data-src="api_pulse.pulse.glyphs.journal.gap_days">17 days<\/span>$/);
  assert.match(rows[1].text, /^no sensor worn; <span[^>]*age_days">30 days<\/span> without a reading$/);
  assert.match(rows[2].text, /17 days<\/span> without a reading$/);
  assert.match(rows[3].text, /18 days<\/span> without an entry$/);
  assert.match(rows[4].text, /^paused — <span[^>]*garmin\]\.days_dark">103 days<\/span> without a record; it cannot report, so the gap is a hole in the record, not a fact about him$/);
  for (const r of rows) assert.doesNotMatch(visible(r.text), /dark|glucose|cycle|reset|attempt/i, r.id);
});

test("absenceRows — a missing breakdown says so; a recorded stream says so; the age floor reads as 'more than'", () => {
  // R7 fix 9: a feed that did not answer is "not served right now"; a served feed with no row is
  // "nothing on record" — and neither names "the payload" (a builder word)
  const none = M.absenceRows({ freshness: { sources: [] }, pulse: null });
  assert.equal(none[0].text, "not served right now");
  assert.equal(none[1].text, "nothing on record");
  assert.equal(none[4].text, "nothing on record");
  const down = M.absenceRows({ freshness: null, pulse: null });
  assert.deepEqual(down.map((r) => r.text), Array(5).fill("not served right now"));
  assert.equal(M.absenceRows({ freshness: { sources: [] }, pulse: { pulse: { glyphs: {} } } })[0].text, "nothing on record");
  for (const r of [...none, ...down]) assert.doesNotMatch(r.text, /payload/);
  const fr = { sources: [{ id: "apple_health", datatypes: [{ key: "cgm", dark: false, last_seen: "2026-09-25" }, { key: "blood_pressure", dark: true, age_days: null, age_floor_days: 400 }] }] };
  const rows = M.absenceRows({ freshness: fr, pulse: { pulse: { glyphs: { journal: { written_today: true } } } } });
  assert.equal(rows[0].text, "an entry today");
  assert.equal(rows[1].text, "being recorded; last reading Friday, September 25");
  assert.match(rows[2].text, /^more than <span[^>]*age_floor_days">400 days<\/span> without a reading$/);
});

test("engineKey — the plain key names the day, the k of n areas, the level; areas without an instrument say so", () => {
  const ch = {
    character: { level: 7.0, composite_score: 41.6, composite_pillar_count: 6, composite_pillar_total: 7, as_of_date: "2026-09-25" },
    pillars: [{ name: "sleep", raw_score: 85.2 }, { name: "mind", not_instrumented: true, not_instrumented_note: "No source feeds this pillar yet — tracked as future work (#747)." }, { name: "social_life", raw_score: 12, coverage_hold: true }],
  };
  const k = M.engineKey(ch);
  assert.match(k.key, /^The engine scores seven areas of his life from his own data, each from 0 to 100, and averages the ones it can see\. On Friday, September 25: <span data-src="api_character.character.composite_score">41\.6<\/span>, from <span[^>]*>6<\/span> of <span[^>]*>7<\/span> areas \(1 has no instrument yet\)\. Its level, <span[^>]*>7<\/span>, is how many weeks the areas have held up\.$/);
  assert.deepEqual(k.rows, [
    { name: "sleep", score: 85.2, note: "" },
    { name: "mind", score: null, note: "no instrument yet" },
    { name: "social life", score: 12, note: "held — too little data" },
  ]);
  assert.doesNotMatch(visible(k.key), /pillar|character level|cycle/i);
  assert.equal(M.engineKey(null), null);
});

// ── R7 (#4329) ──────────────────────────────────────────────────────────────────
test("R7 fix 6: ONE day count — the training rows start at the served start day, and the weight sentence counts the experiment's days", () => {
  // the live shape: the feed's trailing window opens the day BEFORE the start
  const daily = [{ date: "2026-09-05", total_min: 0 }, { date: "2026-09-06", total_min: 65 }, { date: "2026-09-07", total_min: 30 }];
  assert.deepEqual(M.trainingSeries(daily, "2026-09-06").map((r) => r.date), ["2026-09-06", "2026-09-07"]);
  assert.equal(M.trainingSeries(daily).length, 3, "no served start → the rows as served");
  assert.match(M.trainingSentence({ daily_modality_minutes_30d: daily }, "2026-09-06"), /^Trained on <span[^>]*>2<\/span> of <span[^>]*>2<\/span> days since September 6\./);
  const j = { current_weight_lbs: 311.0, lost_lbs: 16.3, start_weight_lbs: 327.3, started_date: "2026-09-06", last_weighin_date: "2026-10-03", weighin_count: 20, weighin_span_days: 27, day_n: 28 };
  assert.match(M.weightLine(j, "2026-10-03"), /, 20 weigh-ins in 28 days\.$/);
  assert.match(M.weightLine({ ...j, day_n: null }, "2026-10-03"), /, 20 weigh-ins in 27 days\.$/, "no served day count → the shared line stands");
});

test("R7 fix 10: the page ends on the dated things to come back for — the next write-up and the next weigh-in", () => {
  const n = M.nextEntry({ cad: { chronicle: { paused: false, next_date: "2026-10-07" } }, pending: null, journey: { journey: { last_weighin_date: "2026-10-03" } }, clock: "2026-10-03" });
  assert.equal(visible(n.html), "The next write-up is drafted Wednesday, October 7 and publishes once Matthew has read it.The next weigh-in is due Sunday, October 4.");
  assert.equal(n.day, "2026-10-07");
  assert.match(n.html, /<time datetime="2026-10-04" data-src="api_journey.journey.last_weighin_date">/);
  assert.equal(M.nextEntry({ cad: null, pending: null, journey: null, clock: "" }).html, "");
});
