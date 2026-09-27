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
  assert.match(on30, /Today is day 30 — the first photo is due\.$/);
  const after = strip(H.leadSentence({ ...journey, day_n: 31 }, 8));
  assert.match(after, /the day it began\.$/);
  assert.doesNotMatch(after, /Day 30 is/);
  const eve = strip(H.leadSentence({ ...journey, day_n: 0, pre_start: true }, 8));
  assert.match(eve, /^The eve of an experiment run in public/);
  assert.match(eve, /It begins Sunday, September 6\./);
});

test("the photo frame is honest before and after day 30", () => {
  assert.match(strip(H.photoDue(journey)), /The first is due Monday, October 5 — day 30\./);
  assert.match(strip(H.photoDue({ ...journey, day_n: 40 })), /The first was due Monday, October 5 — day 30\./);
  assert.equal(H.photoDue({}), "");
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
  assert.match(strip(html), /^Data through Saturday, September 26 · the coaches’ checked calls so far, by the site’s scorekeeper: 18 of 37 right · next write-up Wednesday, September 30$/);
  assert.match(html, /data-src="calibration\.platform\.strata\.coaches\.confirmed"/);
  assert.match(strip(H.aliveLine("2026-09-26", null, { chronicle: { paused: true } })), /no checked coach call is served yet · the write-up is paused/);
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

test("the next weigh-in: due tomorrow, or the honest overdue line when that day has passed", () => {
  assert.equal(strip(H.nextWeighinText(journey, "2026-09-26")), "the next weigh-in is due Sunday, September 27");
  assert.equal(strip(H.nextWeighinText(journey, "2026-09-27")), "the next weigh-in is due Sunday, September 27");
  assert.equal(strip(H.nextWeighinText(journey, "2026-09-29")), "the last weigh-in was Saturday, September 26; none since");
  assert.match(strip(H.followBlock({ count: 1, available: true }, cadence, journey, "2026-09-29")), /; the last weigh-in was Saturday, September 26; none since\./);
  assert.match(strip(H.nextBlock([], {}, { chronicle: { paused: true } }, { ...journey, day_n: 40 }, coaches, "2026-09-29")), /The last weigh-in was Saturday, September 26; none since\.$/);
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
  assert.match(text, /Friday night he slept 8\.6 hours — the wrist strap and the bed sensor agree\./);
  assert.match(text, /He logged food every day from September 6 to Friday, September 25 — 20 days — averaging 1,577 calories and 153 g of protein\./);
  assert.match(text, /The site does not publish a calorie deficit: its estimate is larger than it is willing to vouch for\./);
  assert.match(text, /Friday: a 72-minute walk\. Saturday: rest day\. Steps are the weak spot: 2,245 a day, averaged over 20 days\./);
  for (const f of ["nutrition_overview.nutrition.protein_floor_g", "nutrition_overview.nutrition.days_logged", "vitals.hrv_avg_window_days", "training_overview.training.strength_sessions_30d", "training_overview.walking.total_walks_30d", "training_overview.walking.avg_daily_steps_n"]) {
    assert.ok(html.includes(`data-src="${f}"`), `${f} is cited`);
  }
  assert.ok(!/data-src="nutrition\./.test(html), "nutrition.* names the endpoint that is fetched");
  const bare = strip(H.okayBlock(null, null, null, null, null));
  assert.match(bare, /Last night’s sleep is not served\./);
  assert.match(bare, /No food log is served\./);
  assert.match(bare, /No training figures are served\./);
});

test("also on the record: two scorekeepers that disagree are both left up; the skips are counted", () => {
  const html = H.recordBlock(
    { coaches: [{ coach_id: "nutrition", coach_name: "Dr. Marcus Webb", n: 5, confirmed: 0 }, { coach_id: "sleep", coach_name: "Dr. Lisa Park", n: 17, confirmed: 7 }] },
    { predictions: { by_coach: [{ coach: "nutrition", confirmed: 20, refuted: 5 }, { coach: "sleep", confirmed: 7, refuted: 10 }] } },
    { commitments: { lifetime: { unresolved: 468, graded: 49, kept: 37 } } },
    { pacific_today: "2026-09-26", sources: [{ id: "garmin", label: "Garmin", status: "paused", last_update: "2026-06-15" }, { id: "apple_health", label: "Apple Health", status: "fresh", datatypes: [{ key: "cgm", label: "CGM (glucose)" }], dark_datatypes: [{ label: "CGM (glucose)", days_dark: 30 }] }] },
    { pulse: { glyphs: { journal: { gap_days: 17 } } } },
  );
  const text = strip(html);
  assert.match(text, /Dr\. Marcus Webb, the nutrition coach: 0 of 5 checked calls right so far, by one of the site’s scorekeepers\. A second says 20 of 25\. The two disagree, and both are left up\./);
  assert.doesNotMatch(text, /Dr\. Lisa Park/, "a coach whose two scorekeepers agree is not on the record");
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
  assert.doesNotMatch(text, /\d{4}-\d{2}-\d{2}/, "no ISO date reaches the reader");
  // The fold's figures each name their field.
  for (const f of ["journey.current_weight_lbs", "journey.lost_lbs", "journey.day_n", "journey.start_weight_lbs", "journey.weighin_count", "journey.weekly_rate_lbs"]) {
    assert.match(all, new RegExp(`data-src="${f.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"`), `${f} is cited`);
  }
  assert.match(all, /data-src="receipts\.month_to_date_usd"/);
  assert.match(all, /data-src="sub_count\.count"/);
  assert.match(all, /data-src="pulse\.glyphs\.journal\.gap_days"/);
});

test("the margin: day, three-letter month, weekday", () => {
  assert.deepEqual(H.marginParts("2026-09-26"), { d: "26", mo: "Sep", w: "Saturday" });
  assert.equal(H.marginParts("nope"), null);
});
