// tests/js/home_dial_and_figures_3524.test.mjs — #3524: home's dial hub and its
// "where it started · where it is" stat row.
//
// TWO defects, one class, both only visible in a window nobody browses (launch eve, and
// the morning of Day 1 before the first weigh-in) — which is why `grep 'day to go|
// dial-center' tests/` returned 0 before this file.
//
// (a) THE DIAL. Rendered DOM on 2026-09-04 (Playwright, /, networkidle):
//       <span class="label">day</span>
//       <span class="dc-num num" data-bind="dayNum">1</span>
//       <span class="label dc-sub" data-bind="dayCap">day to go — the experiment
//         begins tomorrow, Saturday, September 5</span>
//     DAY / 1 / DAY TO GO on launch eve — and DAY / 1 the next morning, meaning the
//     opposite. The eyebrow was hard-coded in site/index.html and no branch ever wrote
//     it; only two of the hub's three glyphs were bound. Recurs on every future-genesis
//     reset, so the fix is structural, not copy.
//
// (b) THE STAT ROW. Live on 2026-09-05, Day 1, /api/journey serving
//       {"current_weight_lbs": null, "lost_lbs": null, "progress_pct": null,
//        "weighin_count": 0, "day_n": 1, "pre_start": false}
//     renderNumbers wrote `current` ONLY when current_weight_lbs != null, so
//     site/index.html's own static shimmer "···" survived into the rendered page beside
//     two rewritten "—" glyphs. Three placeholder vocabularies in one row, and the odd
//     one out reads as a widget that failed to load rather than a record that hasn't
//     started. ADR-104: one deliberate absence glyph, bound in every state.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { dialCopy, journeyFigures, ABSENT_FIGURE } = await import("../../site/assets/js/daily_line.js");

// The shape coach_popover.preStart() returns (_preShape): days until genesis + labels.
const pre = (daysUntil) => ({ daysUntil, startLabel: "Saturday, September 5", startDow: "Saturday" });

/* ── (a) the dial hub ────────────────────────────────────────────────────── */

test("#3524 T−1: the hub never reads 'day' + '1'", () => {
  const d = dialCopy(pre(1), 0, 0);
  assert.equal(d.eyebrow, "until day 1");
  assert.equal(d.num, "1");
  assert.match(d.cap, /day to go/);
  // The exact live failure: eyebrow + number reading as a day-of-experiment count.
  assert.notEqual(`${d.eyebrow} ${d.num}`, "day 1");
});

test("#3524 the eyebrow says 'day' ONLY once the experiment is running", () => {
  // The whole pre-start range, not just the T−1 instance that was reported (#3199 class:
  // guard the SET). A future-genesis reset can stage any of these.
  for (let n = 1; n <= 30; n++) {
    const d = dialCopy(pre(n), 0, 0);
    assert.equal(d.eyebrow, "until day 1", `T−${n} must not claim a day count`);
    assert.ok(!/^day$/.test(d.eyebrow));
  }
  assert.equal(dialCopy(pre(0), 0, 0).eyebrow, "until day 1", "genesis morning, before the flip");
});

test("#3524 negative control: the static eyebrow DOES produce 'DAY / 1 / day to go'", () => {
  // site/index.html shipped `<span class="label">day</span>` with nothing bound to it.
  // Reproduce that: take the number + caption the pre-start branch writes, pair them
  // with the unwritten static eyebrow, and read the hub.
  const STATIC_EYEBROW = "day";
  const d = dialCopy(pre(1), 0, 0);
  const hub = `${STATIC_EYEBROW} ${d.num} ${d.cap}`;
  assert.match(hub, /^day 1 day to go/, "control: the exact live DOM, one day before Day 1");
  // And the same three glyphs, one day later, mean the opposite:
  const dayOne = dialCopy(null, 1, 1);
  assert.equal(`${dayOne.eyebrow} ${dayOne.num}`, "day 1");
});

test("#3524 T−N ≥ 2 counts down without claiming a day number", () => {
  const d = dialCopy(pre(6), 0, 0);
  assert.equal(d.eyebrow, "until day 1");
  assert.equal(d.num, "6");
  assert.match(d.cap, /days to go — the experiment begins Saturday, September 5/);
});

test("#3524 Day 1 and Day N read as the day count they are", () => {
  const one = dialCopy(null, 1, 1);
  assert.deepEqual(one, { eyebrow: "day", num: "1", cap: "day one of the experiment" });
  const n = dialCopy(null, 23, 4);
  assert.deepEqual(n, { eyebrow: "day", num: "23", cap: "days into the experiment · week 4" });
});

test("#3524 no genesis frame yet → the shimmer is left alone", () => {
  // dayN < 1 with no pre-start meta (a stale/failed journey fetch): write nothing rather
  // than stamp a wrong frame over the placeholder.
  assert.equal(dialCopy(null, 0, 0), null);
  assert.equal(dialCopy(null, null, null), null);
});

/* ── (b) the stat row ────────────────────────────────────────────────────── */

const figTexts = (f) => ["lost", "current", "progress"].map((k) => (f[k].present ? "<live>" : f[k].text));

test("#3524 Day 1, no weigh-in yet: all three figures are the SAME absence glyph", () => {
  // The live payload, verbatim.
  const journey = { start_weight_lbs: 324.6, goal_weight_lbs: 185, current_weight_lbs: null, lost_lbs: null, progress_pct: null, weighin_count: 0, day_n: 1, pre_start: false };
  const f = journeyFigures(journey, null);
  assert.deepEqual(figTexts(f), [ABSENT_FIGURE, ABSENT_FIGURE, ABSENT_FIGURE]);
  assert.equal(new Set(figTexts(f)).size, 1, "one glyph, not three vocabularies");
  assert.match(f.current.cap, /awaiting the first weigh-in/, "and it says when the number arrives");
  assert.match(f.lost.cap, /counts from the first weigh-in/);
});

test("#3524 negative control: the pre-fix branch left `current` unwritten", () => {
  // renderNumbers only touched `current` when current_weight_lbs != null, so the HTML's
  // static "···" survived. That is the state this guard has to be able to see.
  const journey = { current_weight_lbs: null, lost_lbs: null, progress_pct: null, pre_start: false };
  const STATIC_HTML_PLACEHOLDER = "···";
  const oldRow = [ABSENT_FIGURE, STATIC_HTML_PLACEHOLDER, ABSENT_FIGURE];
  assert.equal(new Set(oldRow).size, 2, "control: the live row really did mix two glyphs");
  // The fix writes the middle one.
  assert.equal(journeyFigures(journey, null).current.present, false);
  assert.equal(journeyFigures(journey, null).current.text, ABSENT_FIGURE);
});

test("#3524 pre-start: no delta and no progress exist by definition", () => {
  const f = journeyFigures({ start_weight_lbs: 324.6, current_weight_lbs: null, lost_lbs: null, progress_pct: null, pre_start: true }, pre(1));
  assert.deepEqual(figTexts(f), [ABSENT_FIGURE, ABSENT_FIGURE, ABSENT_FIGURE]);
  assert.match(f.lost.cap, /counts from Day 1/);
  assert.match(f.current.cap, /first weigh-in Saturday, September 5/);
  assert.match(f.progress.cap, /counts from Day 1/);
});

test("#3524 pre-start with a banked baseline: the real number still shows", () => {
  // A weigh-in taken before genesis is a real measurement — the #931 "lbs at the start
  // line" branch must keep its number. Absence handling must not erase data.
  const f = journeyFigures({ current_weight_lbs: 324.6, lost_lbs: null, progress_pct: null, pre_start: true }, pre(2));
  assert.equal(f.current.present, true, "the live branch owns this figure");
  assert.equal(f.lost.present, false);
});

test("#3524 Day N with data: every figure defers to the live branch", () => {
  const f = journeyFigures({ current_weight_lbs: 318.2, lost_lbs: 6.4, progress_pct: 4.6, weighin_count: 9, pre_start: false }, null);
  assert.deepEqual(figTexts(f), ["<live>", "<live>", "<live>"]);
});

test("#3524 a partially populated journey mixes live and absent, never a stale glyph", () => {
  // One weigh-in banked: current is real, but there is no delta and no progress yet
  // (#1225 — a trend needs two). The two that have nothing behind them read the same.
  const f = journeyFigures({ current_weight_lbs: 324.6, lost_lbs: null, progress_pct: null, weighin_count: 1, pre_start: false }, null);
  assert.deepEqual(figTexts(f), [ABSENT_FIGURE, "<live>", ABSENT_FIGURE]);
});

test("#3524 a missing journey payload still binds all three", () => {
  const f = journeyFigures(null, null);
  assert.deepEqual(figTexts(f), [ABSENT_FIGURE, ABSENT_FIGURE, ABSENT_FIGURE]);
});

test("#3524 ABSENT_FIGURE is the site's one absence glyph, not a new placeholder", () => {
  assert.equal(ABSENT_FIGURE, "—");
  assert.notEqual(ABSENT_FIGURE, "···");
  assert.notEqual(ABSENT_FIGURE, "··");
});
