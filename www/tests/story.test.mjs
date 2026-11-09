// HS1's read-side helpers (src/lib/story.js): the timeline, the episode index and the "story so far" are built from the
// story's data file + the public Day objects only — dates in words, no audio, and nothing about the journal, State of
// Mind or the video diary (owner ruling 2026-11-03: activity, counts, gaps and cadence are private).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { installmentRows, soFar, spanWords, timelineRows } from "../src/lib/story.js";

const WWW = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const ISO = /\b\d{4}-\d{2}-\d{2}\b/;

const story = {
  state: "ok",
  genesis: "2026-09-06",
  as_of: "2026-11-08",
  story_weeks: [
    { week: 2, start: "2026-09-13", end: "2026-09-19", chapter_id: null },
    { week: 1, start: "2026-09-06", end: "2026-09-12", chapter_id: "week-04" },
    { week: 4, start: "2026-09-27", end: "2026-10-03", chapter_id: "week-07" },
  ],
  installments_index: [
    { chapter_id: "week-07", week: 4, date: "2026-09-29", title: "The Back Half" },
    { chapter_id: "week-04", week: 1, date: "2026-09-08", title: "76% on Day Two" },
  ],
  story_exclusions: [{ ref: "week-05", reason: "owner brief" }],
};
const days = [
  { id: "2026-09-06", date: "2026-09-06", journal_entries: 3, som: 2 },
  { id: "2026-09-13", date: "2026-09-13" },
  { id: "2026-10-01", date: "2026-10-01" },
  { id: "2026-10-04", date: "2026-10-04" },
];

test("spans are in words, across a month and a year", () => {
  assert.equal(spanWords("2026-09-06", "2026-09-12"), "6 to 12 September 2026");
  assert.equal(spanWords("2026-09-27", "2026-10-03"), "27 September to 3 October 2026");
  assert.equal(spanWords("2026-12-27", "2027-01-02"), "27 December 2026 to 2 January 2027");
  assert.equal(spanWords("x", "2026-01-01"), null);
});

test("the index is in reading order with dates in words, and carries only id, week, title and date", () => {
  const rows = installmentRows(story);
  assert.deepEqual(rows.map((r) => r.week), [1, 4]);
  assert.equal(rows[0].dateWords, "8 September 2026");
  for (const r of rows) {
    assert.deepEqual(Object.keys(r).sort(), ["dateWords", "id", "title", "week", "weekLabel"]);
    assert.ok(!ISO.test(r.dateWords));
  }
  assert.deepEqual(installmentRows({ state: "absent" }), []);
  assert.deepEqual(installmentRows(null), []);
});

test("the timeline: one row per served week, its installment when indexed, its days as Day links — nothing else", () => {
  const rows = timelineRows(story, days);
  assert.deepEqual(rows.map((r) => r.week), [1, 2, 4]);
  assert.equal(rows[0].installment.title, "76% on Day Two");
  assert.equal(rows[1].installment, null, "a week with no indexed installment has none — and no state word");
  assert.deepEqual(rows[0].days, [{ id: "2026-09-06", words: "Sunday 6 September" }]);
  assert.deepEqual(rows[2].days.map((d) => d.id), ["2026-10-01"]);
  for (const r of rows) {
    assert.deepEqual(Object.keys(r).sort(), ["days", "installment", "span", "week", "weekLabel"]);
    for (const d of r.days) assert.deepEqual(Object.keys(d).sort(), ["id", "words"], "a day row never carries a journal / mood / diary field");
  }
});

test("the story so far: the day, the start in words, the first and the latest installment", () => {
  const so = soFar(story, { day_n: 64 });
  assert.equal(so.sentence, "Day 64 of an experiment that began on 6 September 2026.");
  assert.equal(so.count, 2);
  assert.equal(so.first.id, "week-04");
  assert.equal(so.latest.id, "week-07");
  assert.equal(soFar({ ...story, installments_index: [story.installments_index[1]] }, null).latest, null, "one installment: no separate 'latest'");
  assert.equal(soFar({ state: "absent" }, { day_n: 1 }), null);
});

test("no HS1 template or helper reads audio, an excerpt, or a journal / State of Mind / diary field", () => {
  const sources = ["src/lib/story.js", "src/story/timeline.astro", "src/story/episodes.astro", "src/components/StoryEntry.astro"].map((p) => [
    p,
    readFileSync(join(WWW, p), "utf8").replace(/^\s*\/\/.*$/gm, ""),
  ]);
  const forbidden = /audio|episode_id|transcript|podcast|panelcast|\.mp3|\.wav|excerpt|body_html|journal_|state_of_mind|som_|diary|vlog|<Quote|data-verbatim/i;
  for (const [p, text] of sources) {
    const code = text.replace(/\/\*[\s\S]*?\*\//g, "");
    const m = code.match(forbidden);
    assert.equal(m, null, `${p} must not reference ${m && m[0]}`);
  }
});
