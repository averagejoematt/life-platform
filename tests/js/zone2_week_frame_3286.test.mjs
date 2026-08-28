// tests/js/zone2_week_frame_3286.test.mjs — #3286: the Zone-2 panel names the week it is
// actually showing.
//
// The API served `current_week = weeks[-1]` (the last week WITH activity) and the panel
// rendered it under the heading "This week vs the 150-minute reference", `valueLabel:
// "this week"`, and a "week-so-far" caption — with no date anywhere on the surface. On
// 2026-08-27 that was the week of 08-17: ten days old, published as this week, while
// /api/training_overview reported trailing-7d Zone-2 of 0.
//
// The API half is fixed in lambdas/web/site_api_autonomic.py (tests/
// test_zone2_current_week_frame_3286.py). This is the half the reader sees: the range is
// rendered unconditionally, the zero week says why it is zero, and the real last-active
// tally is named rather than hidden.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { renderZone2, weekRange } = await import("../../site/assets/js/evidence_autonomic.js");

const SUMMARY = { zone_2_hr_range: "114–133 bpm", max_hr_used: 190, weeks_analyzed: 2, weeks_meeting_target: 1, target_hit_rate_pct: 50 };

// The wire shape /api/zone2 now serves on the filed day: an explicit dated zero for the
// current calendar week, with the last active week named separately.
const DARK_WEEK = {
  available: true,
  weekly_target_min: 150,
  pacific_today: "2026-08-27",
  current_week: {
    week_start: "2026-08-24",
    week_end: "2026-08-30",
    zone_2_minutes: 0,
    target_pct: 0,
    target_met: false,
    total_exercise_min: 0,
    activity_count: 0,
    no_activity_recorded: true,
    is_current_calendar_week: true,
    source_last_activity: "2026-08-21",
    days_since_activity: 6,
  },
  latest_active_week: { week_start: "2026-08-17", week_end: "2026-08-23", zone_2_minutes: 150, target_met: true, activity_count: 3 },
  weeks: [
    { week_start: "2026-08-10", week_end: "2026-08-16", zone_2_minutes: 95, target_met: false, activity_count: 2 },
    { week_start: "2026-08-17", week_end: "2026-08-23", zone_2_minutes: 150, target_met: true, activity_count: 3 },
  ],
  zone_distribution: [],
  sport_breakdown: [],
  summary: SUMMARY,
};

const LIVE_WEEK = {
  ...DARK_WEEK,
  current_week: {
    week_start: "2026-08-24",
    week_end: "2026-08-30",
    zone_2_minutes: 90,
    target_pct: 60,
    target_met: false,
    total_exercise_min: 90,
    activity_count: 2,
    is_current_calendar_week: true,
    source_last_activity: "2026-08-26",
    days_since_activity: 1,
  },
  latest_active_week: { week_start: "2026-08-24", week_end: "2026-08-30", zone_2_minutes: 90, target_met: false, activity_count: 2 },
};

test("the panel renders the current week's date range, never a bare 'this week'", () => {
  const html = renderZone2(DARK_WEEK);
  assert.match(html, /Aug 24–30/, "the week the panel is showing must be named on the panel");
  assert.ok(!/valueLabel/.test(html));
  // The old surface said "this week" three times with no date. Any remaining bare
  // "this week" must be adjacent to the range, never standing in for it.
  const bare = [...html.matchAll(/this week(?!\s*\()/gi)];
  assert.equal(bare.length, 0, `the panel still says a bare "this week" ${bare.length}x — every "this week" must carry its range`);
  assert.match(html, /This week \(Aug 24–30\) vs the 150-minute reference/);
});

test("a zero current week says WHY it is zero rather than implying a lazy week", () => {
  const html = renderZone2(DARK_WEEK);
  assert.match(html, /Nothing has qualified since/, "an unexplained 0 reads as 'he did nothing', not 'the source is dark'");
  assert.match(html, /2026-08-21/);
  assert.match(html, /6 days/);
  assert.match(html, /measured zero, not a missing read/);
});

test("the real number is named, not withheld — under the week it belongs to", () => {
  const html = renderZone2(DARK_WEEK);
  assert.match(html, /most recent week with a qualifying session was <strong>Aug 17–23<\/strong>/);
  assert.match(html, /150 min/);
});

test("a live current week renders as itself, with no darkness note", () => {
  const html = renderZone2(LIVE_WEEK);
  assert.match(html, /This week \(Aug 24–30\)/);
  assert.ok(!/Nothing has qualified since/.test(html), "a week WITH activity must not wear the dark-source note");
  assert.ok(!/most recent week with a qualifying session/.test(html), "no need to point elsewhere when the current week has data");
});

test("the by-week chart says a blank week is ABSENT, not a zero bar", () => {
  // `weeks` has always held only weeks with qualifying activity — which is exactly why
  // `weeks[-1]` could never be "the current week". Said out loud so the last bar is not
  // read as this week.
  const html = renderZone2(DARK_WEEK);
  assert.match(html, /a blank week is absent, not a zero bar/);
});

test("weekRange formats from the STRING parts — never through new Date()", () => {
  // A bare YYYY-MM-DD parses as UTC midnight; rendering that through a Pacific locale
  // prints the PREVIOUS day. Reintroducing that here would recreate, in the label, the
  // exact frame defect this panel is being fixed for (#3196's class).
  assert.equal(weekRange({ week_start: "2026-08-24", week_end: "2026-08-30" }), "Aug 24–30");
  assert.equal(weekRange({ week_start: "2026-08-31", week_end: "2026-09-06" }), "Aug 31 – Sep 6");
  assert.equal(weekRange({ week_start: "2026-12-28", week_end: "2027-01-03" }), "Dec 28 – Jan 3");
  assert.equal(weekRange({ week_start: "2026-08-24" }), "Aug 24");
  assert.equal(weekRange({}), "—");
  // The control: what the tempting implementation would have printed in Pacific.
  const viaDate = new Date("2026-08-24").toLocaleDateString("en-US", { timeZone: "America/Los_Angeles", month: "short", day: "numeric" });
  assert.equal(viaDate, "Aug 23", "the new Date() hazard did not reproduce — this control is not exercising it");
});

test("the honest empty state is untouched", () => {
  const html = renderZone2({ available: false, reason: "No qualifying cardio activity in the window yet." });
  assert.match(html, /No qualifying cardio activity/);
});
