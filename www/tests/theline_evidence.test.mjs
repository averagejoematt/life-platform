// The Line and evidence in the margin (2026-11-14, sprint II): placement only. The line draws only published
// readings, never fills a missing morning; the evidence figures go between paragraphs, never into the text.
import assert from "node:assert/strict";
import { test } from "node:test";

import { chapterWindow, dailyBars, placeEvidence, windowValues } from "../src/lib/evidence.js";
import { lineCounts, theLine } from "../src/lib/theline.js";

const days = [
  { date: "2026-09-06", value: 327.3 },
  { date: "2026-09-07", value: null },
  { date: "2026-09-08", value: 325.1 },
  { date: "2026-09-09", value: 324.0 },
];

test("The Line: one inspectable point per real reading, a missing morning marked and dashed across, no point invented", () => {
  const svg = theLine({ days, startDate: "2026-09-06", startValue: 327.3, rungs: [], chapters: [] });
  const pts = JSON.parse(/data-points="([^"]*)"/.exec(svg)[1].replace(/&quot;/g, '"'));
  assert.deepEqual(
    pts.map((p) => p.date),
    ["2026-09-06", "2026-09-08", "2026-09-09"],
  );
  assert.match(svg, /stroke-dasharray="2 3"/, "the segment across the missing morning is dashed");
  assert.equal(lineCounts(days).missing, 1);
  assert.equal(lineCounts(days).readings, 3);
  assert.doesNotMatch(svg, /\d{4}-\d{2}-\d{2}<\/text>/, "labels carry dates in words");
});

test("The Line draws no projection and no goal", () => {
  const svg = theLine({ days, startValue: 327.3 });
  assert.doesNotMatch(svg, /goal|projected/i);
});

test("a chapter's window: the served interval, else the seven days to its data date, never before day one", () => {
  assert.deepEqual(chapterWindow({ status: "published", week: 10, covers_start: "2026-11-04", covers_end: "2026-11-10" }), { from: "2026-11-04", to: "2026-11-10" });
  assert.deepEqual(chapterWindow({ status: "published", week: 10, data_through: "2026-11-10" }), { from: "2026-11-04", to: "2026-11-10" });
  assert.deepEqual(chapterWindow({ status: "published", week: 1, data_through: "2026-09-08" }, "2026-09-06"), { from: "2026-09-06", to: "2026-09-08" });
  assert.equal(chapterWindow({ status: "published", week: 0, data_through: "2026-08-31" }), null);
  assert.equal(chapterWindow({ status: "held", week: 8, data_through: "2026-10-31" }), null);
});

test("daily bars: a day with no reading is an open slot, below the stated floor is hollow, the floor drawn only when given", () => {
  const vals = windowValues({ days: [{ date: "2026-11-04", value: 160 }, { date: "2026-11-06", value: 188 }] }, "2026-11-04", "2026-11-06");
  assert.deepEqual(vals.map((d) => d.value), [160, null, 188]);
  const svg = dailyBars({ values: vals, floor: 170, unit: "g" });
  assert.match(svg, /stroke-dasharray="2 2"/, "the missing day is an open slot");
  assert.match(svg, /stroke-dasharray="5 4"/, "the floor line");
  assert.equal(dailyBars({ values: [{ date: "2026-11-04", value: null }] }), null);
  assert.doesNotMatch(dailyBars({ values: vals }), /stroke-dasharray="5 4"/);
});

test("evidence goes between paragraphs: after the first that names it, once, never inside one, never after a signature", () => {
  const html = '<p class="signature">Protein and recovery, filed</p><p>The scale read 292.6 pounds.</p><p>Protein was low.</p><p>More protein talk.</p>';
  const out = placeEvidence(html, [
    { key: "protein", match: /protein/i, html: "<figure>P</figure>" },
    { key: "recovery", match: /recovery/i, html: "<figure>R</figure>" },
  ]);
  assert.equal(out.html, '<p class="signature">Protein and recovery, filed</p><p>The scale read 292.6 pounds.</p><p>Protein was low.</p><figure>P</figure><p>More protein talk.</p>');
  assert.deepEqual(out.placed, ["protein"]);
  assert.equal(out.html.replace(/<figure>P<\/figure>/, ""), html, "the words are untouched");
});
