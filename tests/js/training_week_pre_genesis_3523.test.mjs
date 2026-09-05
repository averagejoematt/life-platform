// tests/js/training_week_pre_genesis_3523.test.mjs — #3523: /data/training's
// "This week — daily movement" must not render a pre-genesis day as zero minutes.
//
// The live state, measured 2026-09-05 (Day 1 of cycle 16):
//   curl -s https://averagejoematt.com/api/weekly_physical_summary
//   → 2026-08-30 … 09-04 : steps null, total_active_minutes 0   (all six pre-genesis)
//     2026-09-05         : steps 202,  total_active_minutes 0   (Day 1, real)
//
// which the table rendered as "Sun — 0 · Mon — 0 · Tue — 0 · …": one absence encoded
// two different ways in the SAME ROW, because `fmt` returns "—" for null and "0" for 0.
// Those six days were never queried at all — `_experiment_date(7)` clamps the window's
// lower bound to EXPERIMENT_START, so the handler asked about one day and then built a
// seven-row array anyway, stamping `round(0)` on the six it had no data for.
//
// The fix is at the API (a pre-genesis day now carries total_active_minutes: null +
// pre_genesis: true) because the front end structurally CANNOT tell 0-the-measurement
// from 0-the-fabrication — the first test below is the proof of that, and the reason
// the Python contract test in tests/test_pre_genesis_reader_absence_3522.py is the
// load-bearing half of this guard.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { fmt } = await import("../../site/assets/js/evidence_shared.js");
const { movementWeekBody } = await import("../../site/assets/js/evidence_body.js");

const rowsOf = (html) => [...html.matchAll(/<tr><td class="rd-name">([^<]*)<\/td><td class="num">([^<]*)<\/td><td class="num">([^<]*)<\/td><\/tr>/g)].map((m) => [m[1], m[2], m[3]]);

/* ── why the fix had to be at the API ────────────────────────────────────── */

test("#3523 fmt cannot distinguish a measured 0 from a fabricated one", () => {
  assert.equal(fmt(null), "—", "absence");
  assert.equal(fmt(0), "0", "a measured zero — and it must stay a 0 (ADR-104 #2388)");
  // So a row carrying `steps: null, total_active_minutes: 0` is BOTH at once. The
  // handler is the only place that knows which it is.
});

/* ── pre-start: the whole week is outside the experiment window ──────────── */

const PRE_START_WEEK = ["Sat", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri"].map((dow, i) => ({
  date: `2026-08-${29 + i}`.slice(0, 10),
  day_of_week: dow,
  steps: null,
  activities: [],
  total_active_minutes: null,
  pre_genesis: true,
}));

test("#3523 pre-start: every column of every row reads as absence", () => {
  const html = movementWeekBody(PRE_START_WEEK);
  const rows = rowsOf(html);
  assert.equal(rows.length, 7);
  for (const [dow, steps, mins] of rows) {
    assert.ok(dow, "the day label still renders");
    assert.equal(steps, "—");
    assert.equal(mins, "—", "never a 0 for a day the window never reached");
  }
  assert.match(html, /7 of these 7 days fall before Day 1/, "and the table says why");
});

test("#3523 negative control: the pre-fix payload DOES render seven zeros", () => {
  // Verbatim the shape the endpoint returned before this change: minutes round(0),
  // steps None, no pre_genesis flag. The assertions above must be able to see it.
  const old = PRE_START_WEEK.map(({ pre_genesis, ...d }) => ({ ...d, total_active_minutes: 0 }));
  const rows = rowsOf(movementWeekBody(old));
  assert.deepEqual(rows.map((r) => r[2]), ["0", "0", "0", "0", "0", "0", "0"], "control: seven fabricated zeros");
  assert.deepEqual(rows.map((r) => r[1]), ["—", "—", "—", "—", "—", "—", "—"], "control: and the same absence spelled '—' next to them");
  assert.ok(!movementWeekBody(old).includes("fall before Day 1"), "control: and nothing said why");
});

/* ── Day 1: six pre-genesis days + today, which has real data ────────────── */

const DAY_ONE_WEEK = [
  ...["Sun", "Mon", "Tue", "Wed", "Thu", "Fri"].map((dow, i) => ({
    date: `2026-08-${30 + i}`.slice(0, 10),
    day_of_week: dow,
    steps: null,
    activities: [],
    total_active_minutes: null,
    pre_genesis: true,
  })),
  { date: "2026-09-05", day_of_week: "Sat", steps: 202, activities: [], total_active_minutes: 0, pre_genesis: false },
];

test("#3523 Day 1: the six pre-genesis rows are absent, today's real 0 stays a 0", () => {
  const rows = rowsOf(movementWeekBody(DAY_ONE_WEEK));
  assert.deepEqual(rows.slice(0, 6).map((r) => r[2]), ["—", "—", "—", "—", "—", "—"]);
  // 2026-09-05 IS inside the window and WAS queried: 202 steps and no logged activity
  // is a real measurement of a quiet morning. It must not be erased along with the gap.
  assert.deepEqual(rows[6], ["Sat", "202", "0"]);
  assert.match(movementWeekBody(DAY_ONE_WEEK), /6 of these 7 days fall before Day 1/);
});

/* ── Day N: a full week inside the window ────────────────────────────────── */

const FULL_WEEK = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((dow, i) => ({
  date: `2026-10-${11 + i}`,
  day_of_week: dow,
  steps: 6000 + i * 100,
  activities: [{ type: "Walk", minutes: 30 + i }],
  total_active_minutes: 30 + i,
  pre_genesis: false,
}));

test("#3523 Day N: a fully in-window week is untouched, no caption", () => {
  const html = movementWeekBody(FULL_WEEK);
  const rows = rowsOf(html);
  assert.deepEqual(rows.map((r) => r[1]), ["6000", "6100", "6200", "6300", "6400", "6500", "6600"]);
  assert.deepEqual(rows.map((r) => r[2]), ["30", "31", "32", "33", "34", "35", "36"]);
  assert.ok(!html.includes("fall before Day 1"), "no caption when nothing is missing");
});

test("#3523 a real rest day inside the window still reads 0, not '—'", () => {
  // The guard must not overreach: an in-window day with genuinely no movement logged
  // is a measurement (the steps feed reported, the activity list was empty).
  const rest = [{ date: "2026-10-18", day_of_week: "Sun", steps: 1400, activities: [], total_active_minutes: 0, pre_genesis: false }];
  assert.deepEqual(rowsOf(movementWeekBody(rest))[0], ["Sun", "1400", "0"]);
});
