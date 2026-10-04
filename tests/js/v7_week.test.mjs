// tests/js/v7_week.test.mjs — #4182: the v7 "This week" page's pure helpers, against the
// live shapes saved 2026-09-26 (scratchpad/b2). Every helper takes its date explicitly, so
// nothing here reads the wall clock.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const W = await import("../../site/assets/js/v7_week.js");

const POSTS = [
  { week: 3, label: "Week 3", sequence: 6, title: "The Silence and the Signal", date: "2026-09-22", stats_line: "Weight: 315.0 lbs | Week Grade: avg 74 | T0 Streak: 0 days", url: "/journal/posts/week-06/", excerpt: '"The Silence and the Signal"\n\n[Weight: 315.0 lbs | Week Grade: avg 74 | T0 Streak: 0 days]\n\nOn Monday afternoon, Matthew logged…', word_count: 1114 },
  { week: 2, label: "Week 2", sequence: 5, title: "The Volume Problem", date: "2026-09-15", stats_line: "Weight: 318.9 lbs | Week Grade: avg 63 | T0 Streak: 0 days", url: "/journal/posts/week-05/", excerpt: "x", word_count: 1414.0 },
  { week: 1, label: "Week 1", sequence: 4, title: "The Fifteenth Reset, or: What the Body Remembers", date: "2026-09-08", stats_line: "Weight: 327.3 lbs | Week Grade: avg 69 | T0 Streak: 0 days", url: "/journal/posts/week-04/", excerpt: "x", word_count: 1292.0 },
  { week: 0, label: "Prologue · Part III", sequence: 3, title: "The Plan, On the Record", date: "2026-09-05", stats_line: "326.2 lbs at the start · 185 lbs the target", url: "/journal/posts/week-03/", excerpt: "x", word_count: 1615.0 },
  { week: 0, label: "Prologue · Part I", sequence: 1, title: "Before the Numbers", date: "2026-08-31", stats_line: "Prologue | Before Day 1 | Seattle, WA", url: "/journal/posts/week-01/", excerpt: "x", word_count: 1242.0 },
];
const WEIGHTS = [
  { date: "2026-09-06", weight_lbs: 327.3 },
  { date: "2026-09-21", weight_lbs: 315.8 },
  { date: "2026-09-22", weight_lbs: 315.0 },
  { date: "2026-09-24", weight_lbs: 313.7 },
  { date: "2026-09-26", weight_lbs: 313.8 },
];
const TREND = [
  { week: "2026-W38", workouts: 13, minutes: 1336 },
  { week: "2026-W39", workouts: 9, minutes: 1055 },
];
const SLEEP = [
  { date: "2026-09-23", recovery_score: 80 },
  { date: "2026-09-24", recovery_score: 86 },
  { date: "2026-09-25", recovery_score: 99 },
  { date: "2026-09-26", recovery_score: 77 },
  { date: "2026-09-27", recovery_score: null },
];
const CAD = { chronicle: { paused: false, next_date: "2026-09-30", display: "Next Chronicle installment drafted Wednesday, September 30 — publishes once Matthew reviews and approves the draft." } };
const DOCKET = {
  open: [
    { coach_a: "glucose_coach", coach_b: "nutrition_coach", resolution_date: "2026-09-30" },
    { coach_a: "mind_coach", coach_b: "sleep_coach", resolution_date: "2026-10-07" },
  ],
};
const NAMES = { glucose_coach: "Amara Patel", nutrition_coach: "Marcus Webb", sleep_coach: "Lisa Park" };

test("the margin is the served day, split for the column", () => {
  assert.deepEqual(W.marginParts("2026-09-22"), { d: "22", mo: "Sep", w: "Tuesday" });
  assert.equal(W.marginParts("nope"), null);
});

test("the weight that week comes from the post's own stat line; a prologue line has none", () => {
  assert.equal(W.weightThatWeek(POSTS[0].stats_line), 315.0);
  assert.equal(W.weightThatWeek("Weight: — lbs | Week Grade: —"), null);
  assert.equal(W.weightThatWeek(POSTS[4].stats_line), null);
});

test("instalments newest first; the prologue is its own list", () => {
  const { instalments, prologue } = W.splitPosts(POSTS.slice().reverse());
  assert.deepEqual(instalments.map((p) => p.week), [3, 2, 1]);
  assert.deepEqual(prologue.map((p) => p.title), ["The Plan, On the Record", "Before the Numbers"]);
});

test("the opening lines never print the quoted title or the bracketed stat line", () => {
  const lines = W.openingLines(POSTS[0]);
  assert.equal(lines, "On Monday afternoon, Matthew logged…");
  assert.ok(!/\[Weight/.test(lines));
});

test("ISO week keys match the served weekly_trend spelling", () => {
  assert.equal(W.isoWeekKey("2026-09-26"), "2026-W39");
  assert.equal(W.isoWeekKey("2026-09-21"), "2026-W39"); // Monday opens the week
  assert.equal(W.isoWeekKey("2026-09-20"), "2026-W38");
  assert.equal(W.isoWeekKey(""), "");
  assert.deepEqual(W.thisWeekTraining(TREND, "2026-09-26"), TREND[1]);
  assert.equal(W.thisWeekTraining(TREND, "2026-10-05"), null);
});

test("weight since the write-up: the weigh-in on the post's day and the latest after it", () => {
  const s = W.sinceWriteUp(WEIGHTS, "2026-09-22");
  assert.deepEqual(s, { from: { date: "2026-09-22", weight_lbs: 315.0 }, to: { date: "2026-09-26", weight_lbs: 313.8 } });
  // no weigh-in on the post's day → the last one before it
  assert.equal(W.sinceWriteUp(WEIGHTS, "2026-09-23").from.date, "2026-09-22");
  // nothing weighed since → `to` is null (the honest branch)
  assert.equal(W.sinceWriteUp(WEIGHTS, "2026-09-26").to, null);
  assert.equal(W.sinceWriteUp([], "2026-09-22"), null);
});

test("the last three mornings with a recovery reading, oldest first, nulls skipped", () => {
  assert.deepEqual(
    W.lastMornings(SLEEP, 3).map((m) => m.recovery_score),
    [86, 99, 77],
  );
  assert.equal(W.joinNumbers([86, 99, 77]), "86, 99 and 77");
  assert.equal(W.joinNumbers([77]), "77");
});

test("the journal line from the pulse glyph", () => {
  assert.equal(W.journalLine({ pulse: { glyphs: { journal: { written_today: false, gap_days: 17 } } } }), "nothing in the journal for 17 days");
  assert.equal(W.journalLine({ pulse: { glyphs: { journal: { written_today: true, gap_days: 0 } } } }), "a journal entry today");
  assert.equal(W.journalLine({}), "");
});

test("his testimony is honest-empty when has_matthew_response is false everywhere", () => {
  const notes = { entries: [{ week_label: "Week 3", has_matthew_response: false }, { week_label: "Week 2", has_matthew_response: false }, { week_label: "Week 1", has_matthew_response: false }] };
  const t = W.testimonyLine(notes);
  assert.equal(t.answered.length, 0);
  assert.match(t.text, /^None on file\. The site has put 3 weekly notes to him \(Week 1 to Week 3\); he has not answered one yet\.$/);
  assert.equal(W.testimonyLine({ entries: [] }).text, "No notes have been put to him yet.");
  const some = W.testimonyLine({ entries: [{ week_label: "Week 4", has_matthew_response: true }, { week_label: "Week 3", has_matthew_response: false }] });
  assert.equal(some.text, "He answered Week 4.");
});

test("next: the write-up in words, a held draft's own words winning", () => {
  assert.equal(W.nextWriteUpLine(CAD, null), "The next write-up is drafted Wednesday, September 30 and publishes once Matthew has read it.");
  assert.equal(W.nextWriteUpLine(CAD, { display: "Week 4 is drafted and held for Matthew's review." }), "Week 4 is drafted and held for Matthew's review.");
  assert.equal(W.nextWriteUpLine(null, null), "");
});

test("next: the panel line says plainly when no episode is scheduled", () => {
  assert.equal(W.panelLine({ pending: { week: 3, reason: "held_for_review", expected_date: null } }), "No next panel episode is scheduled. Week 3's is held for review.");
  assert.equal(W.panelLine({ pending: { week: 4, expected_date: "2026-10-01" } }), "The next panel episode: Thursday, October 1.");
  assert.equal(W.panelLine({ episodes: [] }), "");
  assert.equal(W.panelLine(null), "");
});

test("next: the first bet settling on or after today, both coaches named", () => {
  assert.deepEqual(W.nextBet(DOCKET, "2026-09-26", NAMES), { date: "2026-09-30", a: "Amara Patel", b: "Marcus Webb", index: 0 });
  const later = W.nextBet(DOCKET, "2026-10-01", NAMES);
  assert.equal(later.date, "2026-10-07");
  assert.equal(later.a, "mind"); // no roster → the id, humanised
  assert.equal(W.nextBet(DOCKET, "2026-10-08", NAMES), null);
  assert.equal(W.nextBet({}, "2026-09-26", NAMES), null);
});

test("the next weigh-in line is entry_age's one spelling: due, or the counted silence once that day is past (R6 fix 4)", () => {
  const journey = { journey: { last_weighin_date: "2026-09-26" } };
  assert.deepEqual(W.nextWeighInLine(journey, "2026-09-26"), { text: "the next weigh-in is due Sunday, September 27", day: "2026-09-27" });
  assert.deepEqual(W.nextWeighInLine(journey, "2026-09-27"), { text: "the next weigh-in is due Sunday, September 27", day: "2026-09-27" });
  // a skipped week: the clock is the served PT day, the line is the silence, the margin the last weigh-in
  assert.deepEqual(W.nextWeighInLine({ journey: { last_weighin_date: "2026-09-21" } }, "2026-09-26"), { text: "no weigh-in since Monday, September 21 — 5 days", day: "2026-09-21" });
  assert.deepEqual(W.nextWeighInLine(null, "2026-09-26"), { text: "", day: "" });
  assert.deepEqual(W.nextWeighInLine({ journey: {} }, "2026-09-26"), { text: "", day: "" });
  // plusDays stays a pure date helper
  assert.equal(W.plusDays("2026-09-30", 1), "2026-10-01");
  assert.equal(W.plusDays(null, 1), "");
});

test("the roster map reads persona_id → name", () => {
  assert.deepEqual(W.coachNames({ coaches: [{ persona_id: "sleep_coach", name: "Lisa Park" }, { persona_id: "x" }] }), { sleep_coach: "Lisa Park" });
});

// ── R7 (#4329) ──────────────────────────────────────────────────────────────────
test("R7 fix 4: the opening lines drop markdown emphasis marks — the words between are untouched", () => {
  const served = { title: "The Body Answers Back", excerpt: "*He has trained every day for 23 days straight — his deliberate choice — and by Tuesday his recovery score had fallen to 54%, a sign that the body is starting to answer back. He is down 15 pounds total, but the pace flag is live and the streak is the question that will define the coming week.*…" };
  const lines = W.openingLines(served);
  assert.ok(!/[*_]/.test(lines), lines);
  assert.match(lines, /^He has trained every day for 23 days straight — his deliberate choice — /);
  assert.match(lines, /define the coming week\.…$/);
  assert.equal(W.stripEmphasis("_really_ and **bold** and ***both***"), "really and bold and both");
  // not emphasis: an underscore inside a word, a spaced asterisk, an unmatched mark
  assert.equal(W.stripEmphasis("a snake_case_name, 2 * 3 * 4, and one *lone mark"), "a snake_case_name, 2 * 3 * 4, and one *lone mark");
  assert.equal(W.stripEmphasis(null), "");
});

test("R7 fix 9: a field-notes fetch that failed is 'not served right now', never 'no notes have been put to him'", () => {
  assert.equal(W.testimonyLine(null).text, "The notes put to him are not served right now.");
  assert.equal(W.testimonyLine({ entries: [] }).text, "No notes have been put to him yet.");
});
