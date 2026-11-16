// HS1's read-side helpers (src/lib/story.js): the timeline, the episode index and the "story so far" are built from the
// story's data file + the public Day objects only — dates in words, no audio, and nothing about the journal, State of
// Mind or the video diary (owner ruling 2026-11-03: activity, counts, gaps and cadence are private).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { installmentRows, soFar, spanWords, timelineRows, weekRecord, weekRecords } from "../src/lib/story.js";

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

test("no HS1 template or helper reads audio or a journal / State of Mind / diary field; an excerpt only from a published chapter", () => {
  const sources = ["src/lib/story.js", "src/story/timeline.astro", "src/components/StoryEntry.astro"].map((p) => [
    p,
    readFileSync(join(WWW, p), "utf8").replace(/^\s*\/\/.*$/gm, ""),
  ]);
  const forbidden = /audio|episode_id|transcript|podcast|panelcast|\.mp3|\.wav|body_html|journal_|state_of_mind|som_|diary|vlog|<Quote|data-verbatim/i;
  for (const [p, text] of sources) {
    const code = text.replace(/\/\*[\s\S]*?\*\//g, "");
    const m = code.match(forbidden);
    assert.equal(m, null, `${p} must not reference ${m && m[0]}`);
  }
  // 2026-11-09 readiness review: the timeline shows an approved installment's own published excerpt — the words /story/
  // already shows — read off the PUBLIC chapter object, and only when that object is published. Nothing else may.
  const [, timeline] = sources[1];
  const reads = timeline.match(/excerpt/g) || [];
  assert.ok(reads.length > 0, "the timeline carries the installment's excerpt");
  assert.match(timeline, /const c = all\.get\("chapter", id\);\s*return c && c\.status === "published" && typeof c\.excerpt === "string"/);
  for (const [p, text] of [sources[0], sources[2]]) assert.ok(!/excerpt/i.test(text), `${p} must not read an excerpt`);
  assert.ok(!/excerpt/.test(readFileSync(join(WWW, "src/lib/story.js"), "utf8").replace(/^\s*\/\/.*$/gm, "")));
});

// ── "That week in the record" (one quiet line per released week, from the public Day objects only) ───────────────
// Week 1 (6–12 Sep) is released (week-04 is indexed); week 2 (13–19 Sep) is HELD — no installment in the index — and its
// days carry sentinel values (999.9 lb, 77 calls) that must never reach any line.
const SENTINEL_WEIGHT = 999.9;
const day = (date, o = {}) => ({
  id: date,
  date,
  has_weighin: false,
  readings: { weight_lbs: null },
  workout_state: "none logged",
  workout: null,
  food_state: "served",
  food: { calories: 2000, logging_gap: false },
  calls_settled: [],
  ...o,
});
const weighed = (lbs) => ({ has_weighin: true, readings: { weight_lbs: lbs } });
const session = { workout_state: "served", workout: { title: "Push", duration_min: 50, volume_kg: 9000, exercises: [] } };
const recordDays = [
  day("2026-09-06", { ...weighed(327.3), journal_entries: 3, som: 2 }),
  day("2026-09-07", { ...session, readings: { weight_lbs: 326.0 } }), // a weight with no recorded weigh-in: never printed
  day("2026-09-08", { ...session, food_state: "served", food: { calories: 300, logging_gap: true } }),
  day("2026-09-09", { ...session, calls_settled: [{ prediction_id: "c-right", verdict: "confirmed" }, { prediction_id: "c-wrong", verdict: "refuted" }] }),
  day("2026-09-10", { food_state: "not logged", food: null, calls_settled: [{ prediction_id: "c-disputed", verdict: "confirmed" }, { prediction_id: "c-private", verdict: "confirmed" }, { prediction_id: "c-expired", verdict: "expired" }] }),
  day("2026-09-12", { ...weighed(319.7), ...session }),
  // the held week
  ...["2026-09-13", "2026-09-14", "2026-09-15"].map((d) => day(d, { ...weighed(SENTINEL_WEIGHT), ...session, calls_settled: Array.from({ length: 77 }, (_, i) => ({ prediction_id: "c-right", verdict: i ? "refuted" : "confirmed" })) })),
];
const PUBLIC_CALLS = { "c-right": { id: "c-right" }, "c-wrong": { id: "c-wrong" }, "c-disputed": { id: "c-disputed", classification_review: true }, "c-expired": { id: "c-expired" } };
const callOf = (id) => PUBLIC_CALLS[id] || null;
const lineText = (r) => (r ? r.parts.map((p) => p.text.map((s) => (typeof s === "string" ? s : s.text)).join("")).join(" · ") : "");
const links = (r) => r.parts.flatMap((p) => p.text.filter((s) => typeof s !== "string"));

test("the record line: first and last RECORDED weigh-in, sessions, food K of N days, calls K of N right — each a link", () => {
  const r = weekRecord(story, story.story_weeks[1], recordDays, callOf);
  assert.equal(lineText(r), "weight 327.3 to 319.7 lb · 4 sessions · food logged 4 of 6 days · calls settled 1 of 2 right");
  assert.deepEqual(r.parts.map((p) => p.key), ["weight", "sessions", "food", "calls"]);
  assert.deepEqual(
    links(r).map((l) => `${l.type}:${l.id}`),
    ["day:2026-09-06", "day:2026-09-12", "day:2026-09-07", "day:2026-09-06", "day:2026-09-09"],
    "weights link their weigh-in days; a count links the first day it counts",
  );
  for (const l of links(r)) assert.ok(l.label && !ISO.test(l.label), "a link's title is the day in words, never an ISO date");
  // a single settled call links the call page itself
  const one = weekRecord(story, story.story_weeks[1], [day("2026-09-09", { calls_settled: [{ prediction_id: "c-wrong", verdict: "refuted" }] })], callOf);
  const call = links(one).find((l) => l.type === "prediction");
  assert.equal(call.id, "c-wrong");
  assert.equal(lineText(one), "food logged 1 of 1 days · call settled 0 of 1 right");
});

test("a field the week cannot answer is omitted, never a zero; an unanswerable week has no line", () => {
  const unread = [day("2026-09-06", { workout_state: "not served", food_state: "older than the served window", food: null })];
  assert.equal(weekRecord(story, story.story_weeks[1], unread, callOf), null);
  const noSessions = weekRecord(story, story.story_weeks[1], [day("2026-09-06", weighed(320))], callOf);
  assert.equal(lineText(noSessions), "weighed 320.0 lb · food logged 1 of 1 days");
  assert.ok(!/\b0 (sessions|of)/.test(lineText(noSessions)));
  const gapOnly = weekRecord(story, story.story_weeks[1], [day("2026-09-06", { ...weighed(320), food: { logging_gap: true } })], callOf);
  assert.equal(lineText(gapOnly), "weighed 320.0 lb", "a week whose only food day is a logging gap shows no food figure, not '0 of 1'");
  assert.equal(weekRecord(story, story.story_weeks[1], [], callOf), null);
});

test("never an estimate: a weight without a recorded weigh-in, a mean or a normal is not printed", () => {
  const r = weekRecord(story, story.story_weeks[1], [day("2026-09-07", { readings: { weight_lbs: 326 }, normals: { weight_lbs: { mean7: 325 } } })], callOf);
  assert.ok(!/weigh/.test(lineText(r)));
});

test("calls: only public, undisputed, graded verdicts are counted", () => {
  const r = weekRecord(story, story.story_weeks[1], recordDays, callOf);
  const calls = r.parts.find((p) => p.key === "calls");
  assert.equal(lineText({ parts: [calls] }), "calls settled 1 of 2 right", "the disputed, the non-public and the expired call are not counted");
});

test("journal presence changes nothing: the record is identical with every journal / mood field stripped", () => {
  const strip = recordDays.map(({ journal_entries, som, ...d }) => d);
  assert.deepEqual(weekRecord(story, story.story_weeks[1], recordDays, callOf), weekRecord(story, story.story_weeks[1], strip, callOf));
});

test("the line is plain words and figures: printable ASCII, no glyph code point, no ISO date", () => {
  const r = weekRecord(story, story.story_weeks[1], recordDays, callOf);
  for (const p of r.parts)
    for (const s of p.text) {
      const t = typeof s === "string" ? s : s.text;
      assert.match(t, /^[\x20-\x7E]*$/, `glyph or non-ASCII in ${JSON.stringify(t)}`);
      assert.ok(!ISO.test(t));
    }
});

// The held-week check, and its must-fail control: the same check run on a forged story that indexes the held week
// MUST find the leak (a check that cannot fail is not a check).
function heldWeekLeaks(storyFile, records) {
  const released = new Set((storyFile.installments_index || []).map((i) => i.week));
  const leaks = [];
  for (const [week, r] of records) {
    if (!released.has(week)) leaks.push(`week ${week}: a record line on a week with no released installment`);
    if (lineText(r).includes(String(SENTINEL_WEIGHT)) || /\b77\b/.test(lineText(r))) leaks.push(`week ${week}: a held week's day reached the line`);
  }
  return leaks;
}

test("a held or excluded week gets no line — and the check fails when one is planted (must-fail control)", () => {
  const records = weekRecords(story, recordDays, callOf);
  assert.deepEqual([...records.keys()], [1], "only the released week has a record line");
  assert.equal(weekRecord(story, story.story_weeks[0], recordDays, callOf), null, "week 2 (no installment) has none");
  // a week whose chapter_id names a chapter the index does not carry (excluded) is refused too
  assert.equal(weekRecord(story, { week: 2, start: "2026-09-13", end: "2026-09-19", chapter_id: "week-05" }, recordDays, callOf), null);
  assert.equal(weekRecord({ ...story, state: "absent" }, story.story_weeks[1], recordDays, callOf), null);
  assert.deepEqual(heldWeekLeaks(story, records), []);

  // MUST FAIL: the held week planted into the index (as if the approval gate were bypassed) leaks its sentinels.
  const forged = {
    ...story,
    story_weeks: story.story_weeks.map((w) => (w.week === 2 ? { ...w, chapter_id: "week-05" } : w)),
    installments_index: [...story.installments_index, { chapter_id: "week-05", week: 2, date: "2026-09-15", title: "Held" }],
  };
  const leaked = weekRecords(forged, recordDays, callOf);
  assert.ok(leaked.has(2), "the forged index composes a week-2 line");
  const found = heldWeekLeaks(story, leaked);
  assert.ok(found.length >= 2, `the held-week check must red on a planted held week: ${JSON.stringify(found)}`);
  assert.ok(found.some((l) => l.includes("held week's day")));
});

test("the timeline renders the record line neutrally: no colour class, no green, no icon glyph", () => {
  const src = readFileSync(join(WWW, "src/story/timeline.astro"), "utf8");
  const block = src.slice(src.indexOf("records.get(r.week) && ("), src.indexOf("{r.days.length > 0 && ("));
  assert.ok(block.length > 0 && block.includes("data-week-record"));
  assert.ok(!/cobalt|verm|ochre|green|--good|--ok\b/i.test(block), "the record line carries no colour: green is for earned outcomes only");
  assert.match(block.replace(/ · /g, ""), /^[\x00-\x7E]*$/, "no glyph code point in the record markup (the site's ' · ' separator only)");
});
