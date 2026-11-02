// The Journey's layers 2–3 (#5583): placement helpers only — the published rate and interval on one
// scale, the published rungs as a ladder, the chapter of the week each rung fell, and the plain means
// the heart captions state. Nothing here computes a statistic the platform did not publish.
import assert from "node:assert/strict";
import { test } from "node:test";

import { heartChart, heartWeeks, ladderRows, ordinal, paceBar, plainMean, rungChapters, visceralBand } from "../src/lib/journey.js";

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

test("a rung's chapter is the published chapter whose week (the seven days ending on its date) holds the crossing", () => {
  const chapters = [
    { id: "week-04", week: 1, date: "2026-09-08", status: "published" },
    { id: "week-05", week: 2, date: "2026-09-15", status: "published" },
    { id: "week-08", week: 5, date: "2026-10-06", status: "published" },
    { id: "week-09", week: 6, date: "2026-10-13", status: "published" },
    { id: "program-week-08", week: 8, date: "2026-10-25", status: "held" },
    { id: "week-01", week: 0, date: "2026-08-31", status: "published" },
  ];
  const got = rungChapters(
    [
      { lb: 320, date: "2026-09-12" },
      { lb: 310, date: "2026-10-06" },
      { lb: 300, date: "2026-10-21" },
      { lb: 290, date: null },
    ],
    chapters,
  );
  assert.deepEqual(
    got.map((r) => [r.lb, r.chapter.id]),
    [
      [320, "week-05"],
      [310, "week-08"],
    ],
    "300 fell in a week whose chapter is held, so it has none",
  );
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
