// tests/js/v7_home.test.mjs — #4182: the v7 Home renderer's contract, from fixtures.
//
// Prototype C's screen I is the design source; what is pinned here is what a reader would
// believe: the lead's day-only branches (before day 30 / day 30 / after / the eve), the
// this-week line's three states, the follow line's subscriber states, the honest empty
// state of "what resolves next", the weigh-in strip drawn to the DAY (a six-day gap is six
// days wide, not one point), every number carrying its served field in data-src, dates in
// words never ISO, and the owner's 2026-09-26 ruling — no earlier starts, attempts, cycles
// or resets anywhere in the rendered copy.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const H = await import("../../site/assets/js/v7_home.js");

const journey = {
  start_weight_lbs: 327.3,
  current_weight_lbs: 313.8,
  lost_lbs: 13.5,
  weighin_count: 13,
  weekly_rate_lbs: -4.36,
  weekly_rate_ci_low: -4.74,
  weekly_rate_ci_high: -2.75,
  rate_provisional: true,
  weighin_span_days: 20,
  projected_goal_date: null,
  started_date: "2026-09-06",
  last_weighin_date: "2026-09-26",
  day_n: 21,
  week_n: 3,
  pre_start: false,
};
const progress = [
  { date: "2026-09-06", weight_lbs: 327.3 },
  { date: "2026-09-12", weight_lbs: 319.7 },
  { date: "2026-09-15", weight_lbs: 318.9 },
  { date: "2026-09-22", weight_lbs: 315.0 },
  { date: "2026-09-26", weight_lbs: 313.8 },
];
const posts = [{ date: "2026-09-22", title: "The Silence and the Signal" }];
const cadence = { chronicle: { paused: false, next_date: "2026-09-30" } };
const coaches = [
  { persona_id: "sleep_coach", name: "Dr. Lisa Park" },
  { persona_id: "mind_coach", name: "Dr. Nathan Reeves" },
];
const docket = [
  {
    coach_a: "mind_coach",
    coach_b: "sleep_coach",
    sides: { mind_coach: false, sleep_coach: true },
    criterion: { metric: "recovery_score_7day_avg", condition: "gte", threshold: 80 },
    resolution_date: "2026-10-07",
  },
];
// Tags stripped to a fixpoint (CodeQL js/incomplete-multi-character-sanitization: one pass
// can leave a tag behind); this is a test-side text extractor, never a sanitizer on the site.
const strip = (html) => {
  let s = String(html);
  for (;;) {
    const next = s.replace(/<[^>]*>/g, "");
    if (next === s) return s;
    s = next;
  }
};

test("the lead sentence: the day-only branches, and the day in words", () => {
  const before = strip(H.leadSentence(journey, 8));
  assert.match(before, /^Day 21 of an experiment run in public: a 300-plus-pound man, his own numbers, eight AI coaches reading them/);
  assert.match(before, /Matthew weighed 327\.3 lb on Sunday, September 6, the day it began\. Day 30 is Monday, October 5\.$/);
  const on30 = strip(H.leadSentence({ ...journey, day_n: 30 }, 8));
  assert.match(on30, /Today is day 30 — the next photo is due\.$/);
  const after = strip(H.leadSentence({ ...journey, day_n: 31 }, 8));
  assert.match(after, /the day it began\.$/);
  assert.doesNotMatch(after, /Day 30 is/);
  const eve = strip(H.leadSentence({ ...journey, day_n: 0, pre_start: true }, 8));
  assert.match(eve, /^The eve of an experiment run in public/);
  assert.match(eve, /It begins Sunday, September 6\./);
});

test("the day-1 photograph's caption: the served start in words, day 1, the served start weight (#3761)", () => {
  assert.equal(strip(H.photoCaption(journey)), "Sunday, September 6 — day 1, 327.3 lb");
  const html = H.photoCaption(journey);
  assert.match(html, /<time datetime="2026-09-06" data-src="journey\.started_date">/);
  assert.match(html, /data-src="journey\.start_weight_lbs"/);
  assert.match(html, /data-src="journey\.started_date → photo date">1</);
  // the day number is computed from the served start, never typed
  assert.equal(strip(H.photoCaption({ ...journey, started_date: "2026-09-05" })), "Sunday, September 6 — day 2");
  assert.equal(H.photoCaption({}), "");
  assert.equal(H.photoCaption({ ...journey, started_date: "2026-09-07" }), "");
  assert.doesNotMatch(html, /2026-09-06</);
});

test("no rendered line still says the first photo is due — the next one is", () => {
  const rows = H.nextRows([], null, cadence, journey, coaches).map((r) => strip(r.html)).join(" ");
  assert.match(rows, /Day 30 — and the next photo\./);
  assert.doesNotMatch(rows + strip(H.leadSentence({ ...journey, day_n: 30 }, 8)), /first photo/);
  assert.equal(H.photoDue, undefined);
});

test("the this-week line has three states", () => {
  assert.match(strip(H.thisWeekLine(progress, posts)), /^This week: 315\.0 → 313\.8 lb since Tuesday’s write-up\.$/);
  assert.match(strip(H.thisWeekLine(progress.slice(0, 4), posts)), /no weigh-in since the last write-up; the latest is 315\.0 lb on Tuesday, September 22\./);
  assert.match(strip(H.thisWeekLine([], posts)), /no weigh-ins on record/);
});

test("the weigh-in strip is drawn to the day, and the gaps are counted from the record", () => {
  const pts = H.stripPoints(progress);
  assert.equal(pts.length, 5);
  assert.equal(pts[0].x, 6);
  assert.equal(pts[4].x, 314);
  // Sep 6 → Sep 12 is six of the twenty days: 6/20 of the width, not one step.
  assert.ok(Math.abs(pts[1].x - (6 + (6 / 20) * 308)) < 0.2);
  assert.equal(pts[0].y, 6, "the heaviest weigh-in sits on the top axis");
  const html = H.weighinsBlock(progress, journey);
  assert.match(strip(html), /No weigh-in between Tuesday, September 15 and Tuesday, September 22; the scale was skipped on 8 of the 21 days\./);
  assert.match(strip(html), /No date to goal is served — 20 days of weigh-ins is too few to forecast one\./);
  assert.match(H.weighinsBlock([], journey), /not served right now/);
});

test("the alive line carries the ONE data-through, K of N from one producer, the next write-up", () => {
  const html = H.aliveLine("2026-09-26", { platform: { strata: { coaches: { n: 37, confirmed: 18 } } } }, cadence);
  assert.match(strip(html), /^Data through Saturday, September 26 · the coaches’ checked calls so far, by the site’s own count: 18 of 37 right · next write-up Wednesday, September 30$/);
  assert.match(html, /data-src="calibration\.platform\.strata\.coaches\.confirmed"/);
  assert.match(strip(H.aliveLine("2026-09-26", null, { chronicle: { paused: true } })), /the coaches’ record is not served right now · the write-up is paused/);
});

test("what resolves next: sorted by date, the docket in plain words, and the honest empty state", () => {
  const rows = H.nextRows(docket, { overall: { due: { earliest_due: "2026-09-27" } } }, cadence, journey, coaches);
  assert.deepEqual(
    rows.map((r) => r.date),
    ["2026-09-27", "2026-09-30", "2026-10-05", "2026-10-07"],
  );
  assert.match(strip(rows[3].html), /Dr\. Lisa Park says the seven-night average recovery reads 80 or better that day; Dr\. Nathan Reeves says it won’t\. Graded by code\./);
  const empty = strip(H.nextBlock([], {}, { chronicle: { paused: true } }, { ...journey, day_n: 40 }, coaches, "2026-09-26"));
  assert.match(empty, /^Nothing is on the docket and no graded call is due\. The next weigh-in is due Sunday, September 27\.$/);
});

test("follow: the subscriber states and the next weigh-in as last + 1", () => {
  assert.match(strip(H.followBlock({ count: 1, available: true }, cadence, journey, "2026-09-26")), /^One subscriber so far\. The next write-up is Wednesday, September 30; the next weigh-in is due Sunday, September 27\. matt@averagejoematt\.com$/);
  assert.match(strip(H.followBlock({ count: 0, available: true }, cadence, journey, "2026-09-26")), /^No subscribers yet\./);
  assert.match(strip(H.followBlock({ count: 12, available: true }, cadence, journey, "2026-09-26")), /^12 subscribers so far\./);
  assert.match(strip(H.followBlock({ available: false }, cadence, journey, "2026-09-26")), /^The subscriber count is not available right now\./);
  assert.match(strip(H.followBlock(null, { chronicle: { paused: true } }, journey, "2026-09-26")), /The next write-up is not yet scheduled/);
});

test("the next weigh-in: entry_age's one spelling — due through the data-through day, then the counted silence (R6 fix 4)", () => {
  assert.equal(strip(H.nextWeighinText(journey, "2026-09-26")), "the next weigh-in is due Sunday, September 27");
  assert.equal(strip(H.nextWeighinText(journey, "2026-09-27")), "the next weigh-in is due Sunday, September 27");
  assert.equal(strip(H.nextWeighinText(journey, "2026-09-29")), "no weigh-in since Saturday, September 26 — 3 days");
  assert.match(strip(H.followBlock({ count: 1, available: true }, cadence, journey, "2026-09-29")), /; no weigh-in since Saturday, September 26 — 3 days\./);
  assert.match(strip(H.nextBlock([], {}, { chronicle: { paused: true } }, { ...journey, day_n: 40 }, coaches, "2026-09-29")), /No weigh-in since Saturday, September 26 — 3 days\.$/);
  // the day names its served field, never "+ 1 day"; the due day and the last weigh-in each sit in <time>
  assert.match(H.nextWeighinText(journey, "2026-09-26"), /<time datetime="2026-09-27" data-src="journey\.last_weighin_date">Sunday, September 27<\/time>/);
  assert.match(H.nextWeighinText(journey, "2026-09-29"), /<time datetime="2026-09-26" data-src="journey\.last_weighin_date">Saturday, September 26<\/time>/);
  assert.doesNotMatch(H.followBlock({ count: 1, available: true }, cadence, journey, "2026-09-26"), /\+ 1 day/);
  assert.equal(H.nextWeighinText({}), "");
});

test("in his words: every note from the first evening, then the latest", () => {
  const html = H.wordsBlock(
    [
      { date: "2026-09-23", note_at: "2026-09-24T03:10:59Z", note: "Yes lets switch to this." },
      { date: "2026-09-08", note_at: "2026-09-07T04:02:58Z", note: "I am 320+lb. So I want tomorrow to be day 1." },
      { date: "2026-09-06", note_at: "2026-09-07T03:31:14Z", note: "It was just bubbling up." },
    ],
    null,
  );
  const text = strip(html);
  assert.match(text, /Sunday, September 6, 8:31 pm — the earliest note of his on file, to his coaches:“It was just bubbling up\.”Sunday, September 6, 9:02 pm — the same evening:“I am 320\+lb\. So I want tomorrow to be day 1\.”Wednesday, September 23, 8:10 pm — the most recent words of his on file:“Yes lets switch to this\.”/);
  assert.match(html, /data-src="decisions\[1\]\.note"/);
});

test("is he okay: the refusals are kept verbatim and absence is stated as absence", () => {
  const html = H.okayBlock(
    { sleep_detail: { total_sleep_hours: 8.6, whoop_hours: 8.6, night_of: "2026-09-25" } },
    { vitals: { recovery_pct: 77, hrv_ms: 46.5, hrv_avg_ms: 41, hrv_avg_window_days: 21 } },
    { nutrition: { days_logged: 20, avg_calories: 1577, avg_protein_g: 153.3, protein_floor_g: 170, protein_floor_hit_days: 7, latest_date: "2026-09-25", avg_deficit_published: false }, nutrition_trend: [{ date: "2026-09-06" }, { date: "2026-09-25" }] },
    { training: { strength_sessions_30d: 19 }, walking: { total_walks_30d: 14, avg_daily_steps: 2245, avg_daily_steps_n: 20 }, cardio_sessions: [{ date: "2026-09-25", sport: "Walk", minutes: 72 }] },
    { pulse: { date: "2026-09-26", glyphs: { lift: { label: "Rest day" } } } },
  );
  const text = strip(html);
  assert.match(text, /Friday night the bed sensor read 8\.6 hours of sleep and the wrist strap 8\.6\./);
  assert.match(text, /He logged food every day from September 6 to Friday, September 25 — 20 days — averaging 1,577 calories and 153 g of protein\./);
  assert.match(text, /The site does not publish a calorie deficit: its estimate is larger than it is willing to vouch for\./);
  assert.match(text, /Friday: a 72-minute walk\. Saturday: rest day\. The step count on record is 2,245 a day, averaged over 20 days\./);
  for (const f of ["nutrition_overview.nutrition.protein_floor_g", "nutrition_overview.nutrition.days_logged", "vitals.hrv_avg_window_days", "training_overview.training.strength_sessions_30d", "training_overview.walking.total_walks_30d", "training_overview.walking.avg_daily_steps_n"]) {
    assert.ok(html.includes(`data-src="${f}"`), `${f} is cited`);
  }
  assert.ok(!/data-src="nutrition\./.test(html), "nutrition.* names the endpoint that is fetched");
  const bare = strip(H.okayBlock(null, null, null, null, null));
  assert.match(bare, /Last night’s sleep is not served\./);
  assert.match(bare, /No food log is served\./);
  assert.match(bare, /No training figures are served\./);
});

test("also on the record: two counts that disagree are both left up; the skips are counted", () => {
  const html = H.recordBlock(
    { coaches: [{ coach_id: "nutrition", coach_name: "Dr. Marcus Webb", n: 5, confirmed: 0 }, { coach_id: "sleep", coach_name: "Dr. Lisa Park", n: 17, confirmed: 7 }] },
    { predictions: { by_coach: [{ coach: "nutrition", confirmed: 20, refuted: 5 }, { coach: "sleep", confirmed: 7, refuted: 10 }] } },
    { commitments: { lifetime: { unresolved: 468, graded: 49, kept: 37 } } },
    { pacific_today: "2026-09-26", sources: [{ id: "garmin", label: "Garmin", status: "paused", last_update: "2026-06-15" }, { id: "apple_health", label: "Apple Health", status: "fresh", datatypes: [{ key: "cgm", label: "CGM (glucose)" }], dark_datatypes: [{ label: "CGM (glucose)", days_dark: 30 }] }] },
    { pulse: { glyphs: { journal: { gap_days: 17 } } } },
  );
  const text = strip(html);
  assert.match(text, /Dr\. Marcus Webb, the nutrition coach: 0 of 5 checked calls right so far, by one of the site’s two counts\. The other says 20 of 25\. The two disagree, and both are left up\./);
  assert.doesNotMatch(text, /Dr\. Lisa Park/, "a coach whose two counts agree is not on the record");
  assert.match(text, /468 asks expired .* Of the 49 that were checked, he kept 37\./);
  assert.match(text, /What he skips, counted: journal 17 days · blood-sugar sensor 30 days · Garmin 103 days, paused by the platform, not by him\./);
});

test("every number carries its served field, dates are words not ISO, and the ruled words are absent", () => {
  const all = [
    H.leadSentence(journey, 8),
    H.numberBlock(journey),
    H.thisWeekLine(progress, posts),
    H.aliveLine("2026-09-26", { platform: { strata: { coaches: { n: 37, confirmed: 18 } } } }, cadence),
    H.weighinsBlock(progress, journey),
    H.wordsBlock([{ date: "2026-09-06", note_at: "2026-09-07T04:02:58Z", note: "I want tomorrow to be day 1." }], { pulse: { glyphs: { journal: { gap_days: 17 } } } }),
    H.howBlock({ summary: { fresh: 11, stale: 1, paused: 1, total: 13 } }, { count: 8 }, { month_to_date_usd: 102.74, as_of: "2026-09-26T04:30:36+00:00" }, { count: 1, available: true }),
    H.nextBlock(docket, { overall: { due: { earliest_due: "2026-09-27" } } }, cadence, journey, coaches, "2026-09-26"),
    H.followBlock({ count: 1, available: true }, cadence, journey, "2026-09-26"),
  ].join("\n");
  const text = strip(all);
  assert.doesNotMatch(text, /\b(cycle|cycles|reset|resets|attempt|attempts|seventeenth|as of|chronicle|cockpit)\b/i);
  // R5 §d — house jargon a reader meets in the fold: "scorekeeper" and "the engine's count" are gone
  assert.doesNotMatch(text + strip(H.recordBlock({ coaches: [{ coach_id: "nutrition", coach_name: "Dr. Marcus Webb", n: 5, confirmed: 0 }] }, { predictions: { by_coach: [{ coach: "nutrition", confirmed: 20, refuted: 5 }] } }, null, null, null)), /scorekeeper|engine’s count|engine's count/i);
  assert.doesNotMatch(text, /\d{4}-\d{2}-\d{2}/, "no ISO date reaches the reader");
  // The fold's figures each name their field.
  for (const f of ["journey.current_weight_lbs", "journey.lost_lbs", "journey.day_n", "journey.start_weight_lbs", "journey.weighin_count", "journey.weekly_rate_lbs"]) {
    assert.match(all, new RegExp(`data-src="${f.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"`), `${f} is cited`);
  }
  assert.match(all, /data-src="receipts\.month_to_date_usd"/);
  assert.match(all, /data-src="sub_count\.count"/);
  assert.match(all, /data-src="pulse\.glyphs\.journal\.gap_days"/);
  // R5 #2 residue: the note stamps, the eating span, the device count, the 30-day window and the
  // When column each name a field too — no numeral on Home sits outside a data-src element.
  assert.match(all, /<p class="v7h-dated" data-src="decisions\[0\]\.note_at">/);
  assert.match(all, /data-src="source_freshness\.summary\.total"/);
  assert.match(all, /<td class="v7h-td-d" data-src="predictions\.overall\.due\.earliest_due">/);
  const okay = H.okayBlock(null, null, { nutrition: { days_logged: 20, latest_date: "2026-09-25", protein_floor_g: 170, protein_floor_hit_days: 7 }, nutrition_trend: [{ date: "2026-09-06" }] }, { training: { strength_sessions_30d: 19, window_days: 22, window_full: false }, walking: { total_walks_30d: 14 } }, null);
  assert.match(okay, /data-src="nutrition_overview\.nutrition_trend\[0\]\.date">September 6</);
  assert.match(okay, /data-src="nutrition_overview\.nutrition\.latest_date">Friday, September 25</);
  // #4370: the window is the one the counts were taken over — Day 22 has 22 days behind it, not 30.
  assert.match(okay, /in the <span data-src="training_overview\.training\.window_days">22<\/span> days since the experiment began/);
  assert.doesNotMatch(okay, />30<\/span> days/);
  const whole = H.okayBlock(null, null, null, { training: { strength_sessions_30d: 19, window_days: 30, window_full: true } }, null);
  assert.match(whole, /in the last <span data-src="training_overview\.training\.window_days">30<\/span> days/);
});

test("the margin: day, three-letter month, weekday", () => {
  assert.deepEqual(H.marginParts("2026-09-26"), { d: "26", mo: "Sep", w: "Saturday" });
  assert.equal(H.marginParts("nope"), null);
});

// ── R7 (#4329): the ten fixes, Home's share ─────────────────────────────────────
const R7_DOCKET = [
  { coach_a: "physical_coach", coach_b: "sleep_coach", sides: { physical_coach: false, sleep_coach: true }, criterion: { metric: "recovery_score_7day_avg", condition: "gte", threshold: 81.6 }, resolution_date: "2026-10-05", topic: "Recovery score directional trend confirmation" },
  { coach_a: "mind_coach", coach_b: "nutrition_coach", sides: { nutrition_coach: true, mind_coach: false }, criterion: { metric: "total_protein_g_7day_avg", condition: "gte", threshold: 190 }, resolution_date: "2026-10-12", topic: "Fuel-cognition link mechanistic validity" },
  { coach_a: "sleep_coach", coach_b: "physical_coach", sides: { sleep_coach: false, physical_coach: true }, criterion: { metric: "deep_pct_7day_avg", condition: "gte", threshold: 26 }, resolution_date: "2026-10-16", topic: "Deep sleep spike interpretation: signal vs. noise" },
  { coach_a: "mind_coach", coach_b: "nutrition_coach", sides: {}, criterion: { metric: "some_new_engine_field", condition: "gte", threshold: 3 }, resolution_date: "2026-10-20", topic: "Fuel-cognition link mechanistic validity" },
];

test("R7 fix 1: an earliest_due before the data-through day is OVERDUE — counted, the oldest day in words, sorted first, never 'the next call'", () => {
  const preds = { overall: { due: { as_of: "2026-10-03", due_now: 2, earliest_due: "2026-09-27" } } };
  const rows = H.nextRows([], preds, cadence, { ...journey, day_n: 40 }, coaches, "2026-10-03");
  assert.equal(rows[0].overdue, true);
  assert.equal(strip(rows[0].html), "Two graded calls are overdue — the oldest was due Sunday, September 27. Graded by code.");
  const block = H.nextBlock([], preds, cadence, { ...journey, day_n: 40 }, coaches, "2026-10-03");
  assert.match(strip(block), /Overdue\s*Two graded calls are overdue/);
  assert.doesNotMatch(strip(block), /Sun Sep 27/, "no past day in the When column");
  assert.doesNotMatch(strip(block), /The next graded call/);
  // one overdue call; and a due day on or after the data-through day is still "the next"
  assert.equal(strip(H.dueRow({ overall: { due: { due_now: 1, earliest_due: "2026-09-27" } } }, "2026-10-03").html), "One graded call is overdue — it was due Sunday, September 27. Graded by code.");
  const next = H.dueRow({ overall: { due: { due_now: 0, earliest_due: "2026-10-05" } } }, "2026-10-03");
  assert.equal(next.overdue, undefined);
  assert.match(strip(next.html), /^The next graded call of any kind comes due\./);
});

test("R7 fix 2: a windowed metric reads in words by RULE; a metric with no words prints the names only — never the topic, never a field name", () => {
  const rows = H.nextRows(R7_DOCKET, null, null, null, coaches, "2026-10-03");
  const text = rows.map((r) => strip(r.html));
  assert.match(text[1], /says the seven-day average protein reads 190 grams or better that day/);
  assert.match(text[2], /says the seven-night average share of deep sleep reads 26 or better that day/);
  assert.match(text[3], /^Dr\. Nathan Reeves and nutrition disagree\. Graded by code\.$/);
  for (const t of text) {
    assert.doesNotMatch(t, /fuel-cognition|mechanistic|7day|some new engine field/i, t);
    assert.doesNotMatch(t, /\b[a-z]+_[a-z_]+\b/, t);
  }
});

test("R7 fix 3: steps are an instrument reading — the count, its n, the same-day walk beside it; no verdict and no cause", () => {
  const training = {
    training: { strength_sessions_30d: 25, window_days: 28 },
    walking: { total_walks_30d: 18, avg_daily_steps: 3450, avg_daily_steps_n: 27, daily_steps_trend: [{ date: "2026-10-02", steps: 1113 }, { date: "2026-10-03", steps: 9913 }] },
    cardio_sessions: [{ date: "2026-10-03", sport: "Walk", distance_mi: 12.0, minutes: 241 }, { date: "2026-10-02", sport: "Cycling", distance_mi: 11.8, minutes: 50 }],
  };
  const fresh = { sources: [{ id: "apple_health", datatypes: [{ key: "steps", dark: false }] }] };
  const s = H.stepsSentence(training, fresh);
  assert.equal(strip(s).trim(), "His phone’s health app counted 3,450 steps a day, averaged over 27 days — and 9,913 on Saturday, October 3, the day of the 12.0-mile walk.");
  for (const f of ["training_overview.walking.avg_daily_steps", "training_overview.walking.daily_steps_trend[2026-10-03].steps", "training_overview.cardio_sessions[0].distance_mi", "source_freshness.sources[apple_health].datatypes[steps]"]) {
    assert.ok(s.includes(`data-src="${f}"`), `${f} is cited`);
  }
  // no freshness → no instrument named; no same-day row → the count alone; never the verdict
  assert.equal(strip(H.stepsSentence({ walking: { avg_daily_steps: 3450, avg_daily_steps_n: 27 } }, null)).trim(), "The step count on record is 3,450 a day, averaged over 27 days.");
  assert.equal(H.stepsSentence({ walking: {} }, fresh), "");
  const okay = strip(H.okayBlock(null, null, null, training, { pulse: { date: "2026-10-03", glyphs: { lift: { label: "Rest day", trained_today: false } } } }, fresh));
  assert.doesNotMatch(okay, /weak spot|rest day|not always on him|undercount/i);
  assert.match(okay, /Saturday: a 241-minute walk \(12\.0 miles\)\. No lifting Saturday\. His phone’s health app counted/);
});

test("R7 fix 5: the date to goal is a month, a year and the engine's range — never a bare weekday and day", () => {
  const j = { ...journey, day_n: 28, weighin_count: 20, projected_goal_date: "2027-06-09", projected_goal_date_earliest: "2027-05-22", projected_goal_date_latest: "2027-09-22" };
  const text = strip(H.weighinsBlock(progress, j));
  assert.match(text, /At this rate the goal lands around June 2027 — between May and September 2027\.$/);
  assert.doesNotMatch(text, /Wednesday, June 9|served date to goal/);
});

test("R7 fix 9: a failed fetch is 'not served right now' — never a fact about him or the record", () => {
  assert.equal(strip(H.wordsBlock(null, null)), "The record of his notes is not served right now.");
  assert.equal(strip(H.wordsBlock([], null)), "No notes of his are on file.");
  assert.equal(strip(H.recordBlock(null, null, null, null, null)), "The rest of the record is not served right now.");
  assert.equal(strip(H.recordBlock({ coaches: [] }, { predictions: {} }, {}, { sources: [] }, { pulse: {} })), "Nothing else is on the record yet.");
  assert.equal(strip(H.nextBlock([], null, null, null, [], "2026-10-03", false)), "What resolves next is not served right now.");
  assert.match(strip(H.followBlock(null, null, null, "2026-10-03")), /The next write-up’s day is not served right now\./);
  assert.match(strip(H.aliveLine("2026-10-03", { platform: {} }, null)), /no checked coach call is on the record yet/);
});
