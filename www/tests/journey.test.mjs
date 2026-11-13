// The Journey's layers 2–3 (#5583): placement helpers only — the published rate and interval on one
// scale, the published rungs as a ladder, the chapter of the week each rung fell, and the plain means
// the heart captions state. Nothing here computes a statistic the platform did not publish.
import assert from "node:assert/strict";
import { test } from "node:test";

import { heartChart, heartWeeks, journeyChart, ladderRows, monthStep, ordinal, paceBar, plainMean, rungChapters, visceralBand } from "../src/lib/journey.js";

test("the pace bar places the published rate and its interval on one scale; zero inside the interval is said", () => {
  const p = paceBar({ weekly_rate_lbs: -3.65, weekly_rate_ci_low: -4.05, weekly_rate_ci_high: -3.36 });
  assert.equal(p.excludesZero, true);
  assert.equal(p.losing, true);
  assert.ok(p.bar > 0 && p.bar < 100);
  assert.ok(p.ciLeft < p.bar && p.ciLeft + p.ciWidth > p.bar, "the whisker brackets the bar's end");
  const q = paceBar({ weekly_rate_lbs: -0.2, weekly_rate_ci_low: -0.9, weekly_rate_ci_high: 0.4 });
  assert.equal(q.excludesZero, false);
  assert.equal(q.ciLeft, 0);
});

test("the ladder: crossed rungs carry their date in words and the gap, the next rung its distance, the rest are faint", () => {
  const rungs = [
    { lb: 320, date: "2026-09-12", days: 6 },
    { lb: 310, date: "2026-10-06", days: 24 },
    { lb: 300, date: "2026-10-21", days: 15 },
    { lb: 290, date: null, days: null },
    { lb: 280, date: null, days: null },
  ];
  const rows = ladderRows(rungs, 298.8);
  assert.deepEqual(
    rows.map((r) => r.cls),
    ["hit", "hit", "hit", "next", "future"],
  );
  assert.equal(rows[0].right, "crossed 12 Sep · 6 days from the start");
  assert.equal(rows[1].right, "crossed 6 Oct · 24 days after 320");
  assert.equal(rows[3].right, "8.8 lb away");
  assert.equal(rows[4].right, "");
  assert.ok(!rows.some((r) => /\d{4}-\d\d-\d\d/.test(r.right)), "no ISO date reaches the page");
});

// The production shape on 2 November (the owner's review): Week 1 is 6–12 September, published on the 8th; Week 7
// (18–24 October) was skipped; Week 8 (25–31 October) is held. The intervals decide the week, never the publication date.
const W = (id, week, start, status, extra = {}) => {
  const end = new Date(Date.parse(`${start}T00:00:00Z`) + 6 * 86400000).toISOString().slice(0, 10);
  return { id, week, week_start: start, week_end: end, status, week_label: `Week ${week}`, ...extra };
};
const PRODUCTION_WEEKS = [
  W("week-04", 1, "2026-09-06", "published", { date: "2026-09-08" }),
  W("week-05", 2, "2026-09-13", "published", { date: "2026-09-15" }),
  W("week-08", 5, "2026-10-04", "published", { date: "2026-10-06" }),
  W("week-09", 6, "2026-10-11", "published", { date: "2026-10-13" }),
  W("program-week-07", 7, "2026-10-18", "skipped", { date: "2026-10-18" }),
  W("program-week-08", 8, "2026-10-25", "held", { date: "2026-10-25" }),
  { id: "week-01", week: 0, week_start: null, week_end: null, date: "2026-08-31", status: "published", week_label: "Prologue · Part I" },
];

test("every crossed rung falls in the week whose explicit interval contains it — 12 Sep is Week 1, 21 Oct is Week 7 (acceptance item 3)", () => {
  const got = rungChapters(
    [
      { lb: 320, date: "2026-09-12" },
      { lb: 310, date: "2026-10-06" },
      { lb: 300, date: "2026-10-21" },
      { lb: 290, date: null },
    ],
    PRODUCTION_WEEKS,
  );
  assert.deepEqual(
    got.map((r) => [r.lb, r.link, r.label, r.state, r.chapter ? r.chapter.id : null]),
    [
      [320, true, "Week 1", "published", "week-04"],
      [310, true, "Week 5", "published", "week-08"],
      [300, false, "Week 7", "skipped", null],
    ],
    "a milestone keeps its date in every case; only a published chapter links",
  );
});

test("the last day of a week stays in it and the next morning starts the next one", () => {
  const got = rungChapters([{ lb: 1, date: "2026-10-24" }, { lb: 2, date: "2026-10-25" }], PRODUCTION_WEEKS);
  assert.deepEqual(got.map((r) => [r.week, r.state]), [[7, "skipped"], [8, "held"]]);
});

test("a crossed rung in a week with no chapter object reads 'no chapter yet', numbered from the intervals", () => {
  const chapters = [W("week-09", 6, "2026-10-11", "published")];
  const got = rungChapters([{ lb: 240, date: "2026-11-09" }, { lb: 250, date: "2026-10-10" }], chapters);
  assert.deepEqual(got.map((r) => [r.link, r.label, r.state, r.chapter]), [[false, "Week 10", "no chapter yet", null], [false, "Week 5", "no chapter yet", null]]);
});

test("a chapter without an interval (a prologue) never claims a crossing", () => {
  const got = rungChapters([{ lb: 330, date: "2026-08-31" }], PRODUCTION_WEEKS);
  assert.equal(got[0].link, false);
  assert.equal(got[0].state, "no chapter yet");
});

test("the heart captions are plain means of the readings shown, with their counts", () => {
  const d = (i, v, gap = false) => ({ date: `2026-09-${String(6 + i).padStart(2, "0")}`, value: v, present: v != null, gap });
  const days = [d(0, 60), d(1, null), d(2, 62), d(3, 64, true), d(4, 58), d(5, 60), d(6, 60), d(7, 50), d(8, 52)];
  assert.deepEqual(plainMean(days.slice(0, 7)), { mean: 60, n: 5 });
  const w = heartWeeks(days);
  assert.equal(w.first.n, 5);
  assert.equal(w.last.n, 6); // 62, 58, 60, 60, 50, 52 — the gap day is not a reading
  assert.deepEqual(plainMean([]), { mean: null, n: 0 });
});

test("the heart chart takes the container's width as its viewBox and emits inspectable points", () => {
  const days = Array.from({ length: 14 }, (_, i) => ({ date: `2026-10-${String(1 + i).padStart(2, "0")}`, value: 50 + i, present: true, gap: false }));
  const svg = heartChart({ days, markers: [{ date: "2026-10-10", label: "baseline change" }], unit: "bpm", name: "Resting heart rate", width: 343, mobile: true });
  assert.match(svg, /viewBox="0 0 343 240"/);
  assert.match(svg, /data-points=/);
  assert.match(svg, /font-size="12.5"/);
  assert.doesNotMatch(svg, />\d\d-\d\d</, "axis days are in words, not ISO fragments");
});

test("the visceral band on the previous site's scale, and ordinals", () => {
  assert.equal(visceralBand(0.8), "low");
  assert.equal(visceralBand(1.5), "moderate");
  assert.equal(visceralBand(3.21), "elevated");
  assert.equal(visceralBand(null), null);
  assert.deepEqual([1, 2, 3, 11, 12, 13, 22, 99].map(ordinal), ["1st", "2nd", "3rd", "11th", "12th", "13th", "22nd", "99th"]);
});

// The live shape on 12 November: 68 days of weigh-ins from 6 September and a projection wedge out to 28 August
// 2027 — a twelve-month axis. At 390 px (a ~350-unit viewBox) one-month ticks put 'Feb' on 'Mar' (the render gate,
// live build). The month labels on the axis line must clear each other by the gate's own measure at every width.
test("the journey's month ticks thin by the width they have: no two axis labels collide on a phone, none dropped on a desktop", () => {
  const days = Array.from({ length: 68 }, (_, i) => {
    const d = new Date(Date.UTC(2026, 8, 6 + i)).toISOString().slice(0, 10);
    return { date: d, value: 327 - i * 0.52, present: true, gap: false };
  });
  const journey = {
    start_weight_lbs: 327.3, goal_weight_lbs: 185, start_date: "2026-09-06",
    projected_goal_date: "2027-07-25", projected_goal_date_latest: "2027-08-28", projected_goal_date_earliest: "2027-07-09",
  };
  const base = { days, journey, rungs: [], markers: [], chapters: [], unit: "lb", decimals: 1, frame: "distance", range: null,
    show: { mean: true, projection: true, rungs: true, chapters: false, events: true } };
  const axis = (svg, fs) => {
    const h = Number(/viewBox="0 0 [\d.]+ ([\d.]+)"/.exec(svg)[1]);
    return [...svg.matchAll(/<text x="([\d.]+)" y="([\d.]+)" text-anchor="middle"[^>]*>([A-Z][a-z]{2})<\/text>/g)]
      .filter((m) => Number(m[2]) === h - 9)
      .map((m) => ({ x: Number(m[1]), s: m[3], w: m[3].length * fs * 0.6 }));
  };
  for (const width of [320, 343, 350, 358]) {
    const ticks = axis(journeyChart({ ...base, mobile: true, width }), 12.5);
    assert.ok(ticks.length >= 3, `${width}: the axis still names months (${ticks.length})`);
    for (let i = 1; i < ticks.length; i++) {
      const gap = ticks[i].x - ticks[i].w / 2 - (ticks[i - 1].x + ticks[i - 1].w / 2);
      assert.ok(gap >= 2, `${width}: '${ticks[i - 1].s}' and '${ticks[i].s}' collide (gap ${gap.toFixed(1)})`);
    }
  }
  const wide = axis(journeyChart({ ...base, mobile: false }), 11);
  assert.deepEqual(wide.map((x) => x.s), ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug"], "a desktop keeps every month");
  // the step is calendar-regular, and a month a tick is kept wherever the width allows it
  assert.equal(monthStep(30 * 864e5, 300, 12.5), 1);
  assert.ok([2, 3].includes(monthStep(356 * 864e5, 302, 12.5)));
  assert.equal(monthStep(356 * 864e5, 1042, 11), 1);
});
