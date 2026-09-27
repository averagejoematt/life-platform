// tests/js/v7_today.test.mjs — #4182: the v7 "Today" page's pure helpers, against the live
// shapes saved 2026-09-26 (scratchpad/b2). Every helper takes its date explicitly, so
// nothing here reads the wall clock.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const T = await import("../../site/assets/js/v7_today.js");

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

test("the return line: entry_age's one next-weigh-in spelling — due through the data-through day, then the counted silence (R6 fix 4)", () => {
  assert.deepEqual(T.returnLine(JOURNEY, "2026-09-26"), { date: "2026-09-27", text: "Rewritten every morning. The next weigh-in is due Sunday, September 27." });
  assert.deepEqual(T.returnLine(JOURNEY, "2026-09-27"), { date: "2026-09-27", text: "Rewritten every morning. The next weigh-in is due Sunday, September 27." });
  // a skipped week: the data-through day has moved on (the vitals' day), the scale has not
  assert.deepEqual(T.returnLine(JOURNEY, "2026-10-01"), { date: "2026-09-26", text: "Rewritten every morning. No weigh-in since Saturday, September 26 — 5 days." });
  assert.deepEqual(T.returnLine(null, "2026-09-26"), { date: "", text: "Rewritten every morning." });
  assert.equal(T.plusDays("2026-09-30", 1), "2026-10-01");
  assert.equal(T.daysBetween("2026-06-15", "2026-09-26"), 103);
  assert.equal(T.daysBetween("x", "2026-09-26"), null);
});

test("what he skips: the dark area, the dark channels, the stale and paused sources — one vocabulary", () => {
  const rows = T.skipsList({ pillars: PILLARS, freshness: FRESH });
  assert.deepEqual(
    rows.map((r) => [r.label, r.text]),
    [
      ["the journal", "nothing logged for 17 days"],
      ["the blood-sugar sensor", "nothing logged for 30 days"],
      ["the blood-pressure cuff", "nothing logged for 17 days"],
      ["Food delivery", "nothing logged for 182 days"],
      ["Garmin", "paused by the site, not by him — nothing logged for 103 days"],
    ],
  );
  // every row names its served field; the logged food log (flagged behaviors, not dark) is NOT a skip
  assert.ok(rows.every((r) => /^api_(snapshot|source_freshness)\./.test(r.src)));
  assert.ok(!rows.some((r) => r.label === "the food log"));
  assert.deepEqual(T.skipsList({}), []);
  assert.deepEqual(T.skipsList({ pillars: [PILLARS[0]], freshness: { pacific_today: "2026-09-26", sources: [FRESH.sources[0]] } }), []);
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
