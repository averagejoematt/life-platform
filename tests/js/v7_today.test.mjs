// tests/js/v7_today.test.mjs — #4182: the v7 "Today" page's pure helpers, against the live
// shapes saved 2026-09-26 (scratchpad/b2). Every helper takes its date explicitly, so
// nothing here reads the wall clock.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const T = await import("../../site/assets/js/v7_today.js");
const { nightLine, weekLine } = await import("../../site/assets/js/three_questions.js");

const NOW = new Date("2026-09-26T19:31:00Z"); // 12:31 PT, Saturday Sep 26
const JOURNEY = { current_weight_lbs: 313.8, lost_lbs: 13.5, weighin_count: 13, started_date: "2026-09-06", last_weighin_date: "2026-09-26", day_n: 21, pre_start: false };
const VITALS = { as_of_date: "2026-09-26", night_of: "2026-09-25", sleep_hours: 8.6, recovery_pct: 77 };
const NUT = { nutrition: { latest_date: "2026-09-25", latest_protein_g: 182, days_logged: 20 } };
const PILLARS = [
  { name: "sleep", raw_score: 85.2 },
  { name: "nutrition", raw_score: 1.6, absence: { state: "logged", sources: ["macrofactor"], dark_sources: [], last_log_date: "2026-09-25", days_dark: null, transition: "paused", days_since_last_log: 1, absent_behaviors: ["protein_total"] } },
  { name: "mind", raw_score: 12, absence: { state: "dark", sources: ["notion"], dark_sources: ["notion"], last_log_date: "2026-09-09", days_dark: 17, stale_hours: 336, transition: "paused", days_since_last_log: 17, absent_behaviors: [] } },
];
const FRESH = {
  pacific_today: "2026-09-26",
  sources: [
    { id: "whoop", label: "Whoop", status: "fresh", last_update: "2026-09-26", age_hours: 16.8 },
    {
      id: "apple_health",
      label: "Apple Health",
      status: "fresh",
      last_update: "2026-09-26",
      datatypes: [
        { key: "cgm", label: "CGM (glucose)", dark: true, age_days: 30.0, last_seen: "2026-08-27" },
        { key: "blood_pressure", label: "Blood pressure", dark: true, age_days: 17.0, last_seen: "2026-09-09" },
        { key: "water", label: "Water", dark: false, age_days: 0.0, last_seen: "2026-09-26" },
      ],
    },
    { id: "food_delivery", label: "Food delivery", status: "behavioral-stale", last_update: "2026-03-28", age_hours: 4377.8 },
    { id: "garmin", label: "Garmin", status: "paused", last_update: "2026-06-15", age_hours: null },
  ],
};
const row = (coach_name, text, due) => ({ coach_id: "sleep_coach", coach_name, text, asked_on: "2026-09-12", due, status: "pending" });

test("the margin is the served day, split for the column", () => {
  assert.deepEqual(T.marginParts("2026-09-26"), { d: "26", mo: "Sep", w: "Saturday" });
  assert.equal(T.marginParts("nope"), null);
});

test("data through is the latest of the three served dates the page prints", () => {
  assert.equal(T.throughDate({ journey: JOURNEY, vitals: VITALS, nutrition: NUT }), "2026-09-26");
  assert.equal(T.throughDate({ nutrition: NUT }), "2026-09-25");
  assert.equal(T.throughDate({}), "");
});

test("the return line is the last weigh-in plus a day, in words", () => {
  assert.deepEqual(T.returnLine(JOURNEY), { date: "2026-09-27", text: "Rewritten every morning. The next weigh-in is due Sunday, September 27." });
  assert.deepEqual(T.returnLine(null), { date: "", text: "Rewritten every morning." });
  assert.equal(T.plusDays("2026-09-30", 1), "2026-10-01");
  assert.equal(T.daysBetween("2026-06-15", "2026-09-26"), 103);
  assert.equal(T.daysBetween("x", "2026-09-26"), null);
});

test("what he skips: the dark area and the dark channels — one vocabulary; the site's own lapses and a channel parked before Day 1 are not his skips", () => {
  const rows = T.skipsList({ pillars: PILLARS, freshness: FRESH, since: "2026-09-06" });
  assert.deepEqual(
    rows.map((r) => [r.label, r.text]),
    [
      ["the journal", "nothing logged for 17 days"],
      ["the blood-sugar sensor", "nothing logged for 30 days"],
      ["the blood-pressure cuff", "nothing logged for 17 days"],
    ],
  );
  // every row names its served field; the logged food log (flagged behaviors, not dark) is NOT a skip
  assert.ok(rows.every((r) => /^api_(snapshot|source_freshness)\./.test(r.src)));
  assert.ok(!rows.some((r) => r.label === "the food log"));
  // "Food delivery" went quiet in March — before Day 1 — so it is parked, not skipped; Garmin is
  // paused by the site; a `stale` automated pull is the site's lapse. None of them print.
  assert.ok(!rows.some((r) => r.label === "Food delivery" || r.label === "Garmin"));
  const stalePull = { pacific_today: "2026-09-26", sources: [{ id: "whoop", label: "Whoop", status: "stale", last_update: "2026-09-20", age_hours: 150 }] };
  assert.deepEqual(T.skipsList({ freshness: stalePull, since: "2026-09-06" }), []);
  // a manual log he let lapse INSIDE the experiment is his skip, with its served source
  const lapsed = { pacific_today: "2026-09-26", sources: [{ id: "measurements", label: "Tape measure", status: "behavioral-stale", last_update: "2026-09-10", age_hours: 384 }] };
  assert.deepEqual(T.skipsList({ freshness: lapsed, since: "2026-09-06" }).map((r) => [r.label, r.text, r.src]), [["Tape measure", "nothing logged for 16 days", "api_source_freshness.sources[measurements]"]]);
  // with no `since` no source row can be substantiated
  assert.deepEqual(T.skipsList({ freshness: lapsed }), []);
  assert.deepEqual(T.skipsList({}), []);
  assert.deepEqual(T.skipsList({ pillars: [PILLARS[0]], freshness: { pacific_today: "2026-09-26", sources: [FRESH.sources[0]] }, since: "2026-09-06" }), []);
});

test("the skips entry: 'Nothing skipped' only when BOTH feeds arrived and are empty — never on a 404 (R6 fix 1)", () => {
  const empty = { pillars: [PILLARS[0]], freshness: { pacific_today: "2026-09-26", sources: [FRESH.sources[0]] }, since: "2026-09-06" };
  assert.match(T.skipsHTML({ ...empty, snapServed: true, freshServed: true }), /Nothing skipped/);
  for (const flags of [{ snapServed: false, freshServed: true }, { snapServed: true, freshServed: false }, { snapServed: false, freshServed: false }]) {
    const html = T.skipsHTML({ ...empty, ...flags });
    assert.doesNotMatch(html, /Nothing skipped/, JSON.stringify(flags));
    assert.match(html, /not served right now\./);
  }
  // with the snapshot down the freshness rows still print, and the rest is said to be missing
  const partial = T.skipsHTML({ pillars: [], freshness: FRESH, since: "2026-09-06", snapServed: false, freshServed: true });
  assert.match(partial, /the blood-sugar sensor/);
  assert.match(partial, /The rest — the areas of his life the site scores — is not served right now\./);
  assert.match(T.skipsHTML({ snapServed: false, freshServed: false }), /^<p class="td-note">What he skips is not served right now\.<\/p>$/);
});

test("an entry's state: the line, the served-empty fact, or 'not served right now' on a null fetch — never a fact on a 404", () => {
  const args = { what: "The week", fact: "No weigh-in is on the record yet.", src: "api_snapshot.journey.{x}" };
  assert.equal(T.stateHTML({ ...args, served: true, line: "Down 1 lb." }), '<p class="td-a" data-src="api_snapshot.journey.{x}">Down 1 lb.</p>');
  assert.equal(T.stateHTML({ ...args, served: true, line: "" }), '<p class="td-note" data-src="api_snapshot.journey.{x}">No weigh-in is on the record yet.</p>');
  assert.equal(T.stateHTML({ ...args, served: false, line: "" }), '<p class="td-note">The week is not served right now.</p>');
});

test("reader words: the shared three-questions sentences re-spelled for the v7 rules — no n=, months in words, no brand", () => {
  assert.equal(T.readerWords("HRV 46.5 ms vs his 21-day average of 41 (n=21). The night of Sep 25."), "HRV 46.5 ms vs his 21-day average of 41 over 21 nights. The night of September 25.");
  assert.equal(T.readerWords("Down 13.5 lb since Sep 6, over 13 weigh-ins; 313.8 lb on Sep 26."), "Down 13.5 lb since September 6, over 13 weigh-ins; 313.8 lb on September 26.");
  assert.equal(T.readerWords("Flex today — 4 exercises, 9 sets, already in Hevy."), "Flex today — 4 exercises, 9 sets, already on his phone.");
  assert.equal(T.readerWords("avg of 41 (n=1)."), "avg of 41 over 1 night.");
  assert.equal(T.readerWords(""), "");
  // the live shapes, end to end: nothing machine-worded survives
  for (const line of [T.readerWords(nightLine(VITALS)), T.readerWords(weekLine(JOURNEY))]) {
    assert.doesNotMatch(line, /n=|\b(Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d|\d{4}-\d{2}-\d{2}|Hevy/);
  }
});

test("the ask is linted before it prints: an ISO date, a percent, a brand or second person folds it under 'as served' (R6 fix 2)", () => {
  assert.deepEqual(T.lintAsk("Start logging the daily 1-to-5 subjective feeling scale before checking the app"), []);
  assert.deepEqual(T.lintAsk("On 2026-09-23 log your Whoop recovery at 86%"), ["an ISO date", "a percent sign", "a device brand", "second person"]);
  assert.deepEqual(T.lintAsk("Matthew, weigh in before coffee."), ["second person"]);
  assert.deepEqual(T.lintAsk("Weigh in before coffee, Matthew."), ["second person"]);
  assert.deepEqual(T.lintAsk("Matthew weighed in before coffee."), []);
  const dirty = { open_actions: [row("Dr. Lisa Park", "Check your Whoop recovery on 2026-09-27", "2026-09-28")] };
  const body = T.askBody(dirty, NOW);
  assert.match(body, /^The ask is not in public words today — Dr\. Lisa Park, asked September 12, due September 28\./);
  assert.match(body, /<details class="td-details"><summary>The ask, as served<\/summary>/);
  assert.match(body, /<span data-verbatim>Check your Whoop recovery on 2026-09-27<\/span>/);
  assert.match(body, /it carries an ISO date, a device brand, second person\. Served without edits\./);
  // the served words appear ONCE, inside the fold — never on the main line
  assert.equal(body.split("Check your Whoop").length - 1, 1);
  assert.ok(body.indexOf("Check your Whoop") > body.indexOf("<details"));
  // a clean ask prints as before, verbatim, unfolded
  assert.doesNotMatch(T.askBody({ open_actions: [row("Dr. Lisa Park", "Weigh in before coffee.", "2026-09-28")] }, NOW), /<details/);
});

test("the ask due today says 'due today', never '0 days late' (#4224)", () => {
  const today = { open_actions: [row("Dr. Max Reyes", "Log the walk before noon.", "2026-09-26")] };
  const body = T.askBody(today, NOW);
  assert.match(body, /due today, September 26\./);
  assert.doesNotMatch(body, /0 days late|late/);
  // due tomorrow: plain; due yesterday: late, no "today"
  assert.match(T.askBody({ open_actions: [row("Dr. Max Reyes", "Log the walk.", "2026-09-27")] }, NOW), /due September 27\.$/);
  const late = T.askBody({ open_actions: [row("Dr. Max Reyes", "Log the walk.", "2026-09-25")] }, NOW);
  assert.match(late, /due September 25 — <strong class="tq-late">1 day late<\/strong>\./);
  assert.doesNotMatch(late, /due today/);
});

test("the one ask: the first current ask leads; when every ask is late the first leads with its lateness", () => {
  const late = { open_actions: [row("Dr. Lisa Park", "Start logging the daily 1-to-5 subjective feeling scale before checking the app", "2026-09-19"), row("Dr. Lisa Park", "(stand-in 2)", "2026-09-19")] };
  assert.equal(T.chosenAsk(late, NOW).text, "Start logging the daily 1-to-5 subjective feeling scale before checking the app");
  const body = T.askBody(late, NOW);
  assert.ok(!/The one ask:/.test(body), "the heading carries the key; the line does not repeat it");
  assert.match(body, /7 days late/);
  assert.match(body, /data-verbatim/);
  const mixed = { open_actions: [row("Dr. Lisa Park", "(late)", "2026-09-19"), row("Dr. Max Reyes", "(current)", "2026-09-28")] };
  assert.equal(T.chosenAsk(mixed, NOW).text, "(current)");
  assert.equal(T.chosenAsk({ open_actions: [] }, NOW), null);
  assert.equal(T.askBody({ open_actions: [] }, NOW), "");
});

test("the loads render only when /api/session serves an exercise list; a 404 is null, never a guessed list", () => {
  assert.equal(T.loadRows(null), null);
  assert.equal(T.loadRows({}), null);
  assert.equal(T.loadRows({ exercises: [] }), null);
  assert.deepEqual(T.loadRows({ exercises: [{ name: "Leg press", sets: 3, reps: 10, load_lbs: 270 }, { name: "Plank", sets: 2 }] }), [
    { name: "Leg press", dose: "3 × 10 · 270 lb" },
    { name: "Plank", dose: "2 sets" },
  ]);
});
