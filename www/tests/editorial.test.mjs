// The editorial release (owner authorisation, review 14, 2026-11-24): the date-first index reproduces the approved labels
// from the chapters' own data, "What happens next" and the homepage read ONE progress computation, and the feature's
// approved text round-trips through its blocks byte for byte.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { applyChapterNumbers, chapterMeta } from "../src/lib/format.js";
import { chapterIndex, dashRange, gapSentence, progress, progressLine, whatHappensNext, askTally, coachRecordWords, kindWords, floorDays, PATH } from "../src/lib/editorial.js";
import { featureAddresses, featureBlocks, featureHead, featureMeta, featureText, inline, renderFeature } from "../src/lib/feature.js";

const url = (p) => new URL(p, import.meta.url);
const ch = (id, week, status, extra = {}) => ({ id, week, status, week_label: week === 0 ? "Prologue · Part I" : `Week ${week}`, ...extra });
// the chapters as the live snapshot served them on 24 November 2026 (covered days applied, as loadAll does)
const live = () => [
  ch("week-01", 0, "published", { title: "Before the Numbers", date: "2026-08-31" }),
  ch("week-04", 1, "published", { title: "76% on Day Two", covers_start: "2026-09-06", covers_end: "2026-09-08", week_start: "2026-09-06", week_end: "2026-09-12" }),
  ch("week-05", 2, "published", { title: "Eight Pounds and a Flag", covers_start: "2026-09-09", covers_end: "2026-09-15", week_start: "2026-09-13", week_end: "2026-09-19" }),
  ch("week-06", 3, "published", { title: "The Scoreboard Splits", covers_start: "2026-09-16", covers_end: "2026-09-22", week_start: "2026-09-20", week_end: "2026-09-26" }),
  ch("week-07", 4, "published", { title: "The Back Half", covers_start: "2026-09-23", covers_end: "2026-09-29", week_start: "2026-09-27", week_end: "2026-10-03" }),
  ch("week-08", 5, "published", { title: "Park's Blind Spot", covers_start: "2026-09-30", covers_end: "2026-10-06", week_start: "2026-10-04", week_end: "2026-10-10" }),
  ch("week-09", 6, "published", { title: "The Quiet Accumulation", covers_start: "2026-10-07", covers_end: "2026-10-13", week_start: "2026-10-11", week_end: "2026-10-17" }),
  ch("program-week-07", 7, "skipped", { week_start: "2026-10-18", week_end: "2026-10-24" }),
  ch("program-week-08", 8, "retired", { week_start: "2026-10-25", week_end: "2026-10-31" }),
  ch("program-week-09", 9, "retired", { week_start: "2026-11-01", week_end: "2026-11-07" }),
  ch("week-12", 10, "published", { title: "The Rate Flag", covers_start: "2026-11-04", covers_end: "2026-11-10", week_start: "2026-11-08", week_end: "2026-11-14", published_at: "2026-11-13" }),
  ch("program-week-11", 11, "retired", { week_start: "2026-11-15", week_end: "2026-11-21" }),
  ch("program-week-12", 12, "pending", { week_start: "2026-11-22", week_end: "2026-11-28" }),
];

test("the date-first index reproduces the approved labels (preview/chapters.html) from the chapters' own data", () => {
  const chapters = applyChapterNumbers(live());
  const rows = chapterIndex({ chapters, startDate: "2026-09-06", asOf: "2026-11-24", prologueFirstPublished: "2026-10-02" });
  const said = rows.map((r) => (r.kind === "gap" ? [r.d, r.s, r.t] : [r.d, r.s, r.chapter.title]));
  assert.deepEqual(said, [
    ["Saturday 5 September 2026", "Prologue · the night before day 1 · first published 2 October 2026", "Before the Numbers"],
    ["6–8 September", "Chapter 1 · days 1–3", "76% on Day Two"],
    ["9–15 September", "Chapter 2 · days 4–10", "Eight Pounds and a Flag"],
    ["16–22 September", "Chapter 3 · days 11–17", "The Scoreboard Splits"],
    ["23–29 September", "Chapter 4 · days 18–24", "The Back Half"],
    ["30 September – 6 October", "Chapter 5 · days 25–31", "Park's Blind Spot"],
    ["7–13 October", "Chapter 6 · days 32–38", "The Quiet Accumulation"],
    ["14 October – 3 November", "days 39–59", "No published chapter covers these days. The week of 18–24 October had no chapter written; drafts for 25–31 October and 1–7 November were retired."],
    ["4–10 November", "Chapter 7 · days 60–66", "The Rate Flag"],
    ["11–24 November (to the build date)", "days 67–80", "No published chapter covers these days yet. A draft for 15–21 November was retired."],
  ]);
  // the index never repeats the prologue header's disputed data cutoff (owner, review 13 §5)
  assert.ok(!JSON.stringify(said).includes("31 August"));
});

test("one chapter number on every page: date-first, the program week kept as the identifier, no number for a week without a chapter", () => {
  const chapters = applyChapterNumbers(live());
  const by = (id) => chapters.find((c) => c.id === id);
  assert.equal(chapterMeta(by("week-12")).number, "07");
  assert.equal(chapterMeta(by("week-12")).name, "Chapter 07");
  assert.deepEqual(chapterMeta(by("week-12")).tick, { date: "2026-11-10", n: "7" });
  assert.equal(by("week-12").week_label, "Week 10");
  assert.equal(chapterMeta(by("week-08")).number, "05");
  assert.equal(chapterMeta(by("week-01")).number, "00");
  assert.equal(chapterMeta(by("program-week-12")).number, "—");
  assert.equal(chapterMeta(by("program-week-12")).name, "Week 12");
});

test("dashRange and the gap sentence say only what the weeks' states say", () => {
  assert.equal(dashRange("2026-11-04", "2026-11-10", { year: true }), "4–10 November 2026");
  assert.equal(dashRange("2026-09-30", "2026-10-06"), "30 September – 6 October");
  assert.equal(gapSentence([], true), "No published chapter covers these days yet.");
  assert.equal(gapSentence([ch("x", 3, "held", { week_start: "2026-10-01", week_end: "2026-10-07" })], false), "No published chapter covers these days. A draft for 1–7 October is held.");
});

const day = (date, value) => ({ date, value, gap: false, present: value != null });
const series = { days: [day("2026-09-06", 327.34), day("2026-09-07", null), day("2026-11-23", 284.48), day("2026-11-24", 285.17)] };

test("ONE progress computation: the homepage's data line and What happens next say the same figure", () => {
  const p = progress({ weightSeries: series, startDate: "2026-09-06", startValue: 327.3, dayN: 80 });
  assert.equal(p.below, "42.1");
  assert.equal(progressLine(p), "Day 80 · latest weigh-in 285.2 lb on 24 November 2026 · 42.1 lb below the 6 September start (327.3 lb)");
  const qs = whatHappensNext({ p, checked: { k: 37, n: 72, eligible: 209, baseline: 39, verdict: "no_clear_difference", words: "no detectable difference" }, own: { coaches_changed: "None of the coaches has really changed what I do.", content: "x" } });
  assert.equal(qs[0].text, `It's day 80. He is 42.1 pounds lighter and has weighed in on ${p.body.readings} of the ${p.body.days} mornings. He counted this start as “the 15th or 16th reset in a few months”. Only the weeks ahead can answer it.`);
  assert.ok(qs[0].text.includes(`${p.below} pounds`), "What happens next reads the homepage's figure");
  assert.equal(
    qs[1].text,
    "So far the coaches' predictions are level with a guess that nothing changes: 37 to 39, on the 72 of 209 graded calls that could be checked fairly. On 8 November 2026 Matt wrote: “None of the coaches has really changed what I do.” More graded calls could move this, and so could a day he records acting on a coach's advice.",
  );
  // his words appear only while the platform serves them
  assert.ok(!whatHappensNext({ p, checked: null, own: {} })[1].text.includes("Matt wrote"));
  assert.ok(!whatHappensNext({ p, checked: null, own: {} })[2].text.includes("content"));
});

test("the homepage and both What-happens-next placements read loadEditorial(), and nothing else computes the weight", () => {
  const home = readFileSync(url("../src/pages/index.astro"), "utf8");
  const whn = readFileSync(url("../src/components/WhatHappensNext.astro"), "utf8");
  assert.match(home, /const ed = await loadEditorial\(\);/);
  assert.match(home, /const body = ed\.p \? ed\.p\.body : null;/);
  assert.ok(!/bodyChange\(/.test(home), "the homepage computes no second body figure");
  assert.match(whn, /const ed = await loadEditorial\(\);/);
  assert.match(whn, /whatHappensNext\(\{ p: ed\.p/);
});

test("his dated 8 November 2026 sentence about the coaches is on the path's page only, never the homepage (owner, PR #6263)", () => {
  const home = readFileSync(url("../src/pages/index.astro"), "utf8");
  const page = readFileSync(url("../src/pages/story/start/what-happens-next.astro"), "utf8");
  assert.ok(home.includes("<WhatHappensNext />") && !/<WhatHappensNext[^>]*quote/.test(home));
  assert.ok(page.includes("<WhatHappensNext page follow quote />"));
  assert.ok(!home.includes("href(\"/story/moments/\")"), "the old 'Start here: the moments' button is retired (decision 2A)");
});

test("the owner's first-person opening is static text in the page, never an expression", () => {
  const home = readFileSync(url("../src/pages/index.astro"), "utf8");
  const opening = "I’m Matt. British, in Seattle. On 6 September 2026 I weighed 327.3 pounds and started again, by my own count ‘the 15th or 16th reset in a few months’. This time a team of AI coaches is part of it. I can’t yet say whether the coaches are helping.";
  assert.ok(home.includes(`<p class="ed-opening" data-first-person>${opening}</p>`));
  assert.ok(home.includes("<h1 data-first-person-headline>I lost 115 pounds once. I regained it all, and more.</h1>"));
});

test("the feature's approved text round-trips through its blocks, byte for byte, and hashes to its pin", () => {
  const f = featureMeta("parks-blind-spot-revisited");
  const text = readFileSync(url(`../src/features/${f.text_file}`), "utf8");
  assert.equal(createHash("sha256").update(text, "utf8").digest("hex"), "68406186f91e76fe4b5faa08ed04ce584d20e7befc6ed13e4570a40ad717ed5b");
  assert.equal(f.sha256, "68406186f91e76fe4b5faa08ed04ce584d20e7befc6ed13e4570a40ad717ed5b");
  assert.equal(featureText(featureBlocks(text)), text);
  assert.equal(featureHead(text).title, "Park's Blind Spot, revisited");
  assert.equal(featureAddresses(text).length, 12);
  assert.ok(text.includes("her record, on her coach page (direction calls"), "the coach page is named in words, never by its raw address (owner, PR #6263)");
  assert.ok(!text.includes("sleep_coach"));
  assert.ok(text.includes("- Elena's bets. Elena lost her bet that Thursday 1 October's recovery would come in below 60"));
  const html = renderFeature(text, (p) => p);
  assert.equal((html.match(/<details/g) || []).length, 4, "four evidence sections a reader opens");
  assert.ok(!html.includes(f.first_published), "the first-publication day is chrome, never inside the text");
  // a site address becomes a link whose words are the address; one the build lacks stays plain text
  assert.equal(inline("see /story/week-08/.", () => "/story/week-08/"), 'see <a href="/story/week-08/">/story/week-08/</a>.');
  assert.equal(inline("see /story/week-08/.", () => null), "see /story/week-08/.");
});

test("the coaches' records are the producer's, as served", () => {
  assert.equal(askTally({ held: 21, kept: 1, broken: 0, pending: 0, unresolved: 20, ungradeable: 0 }), "21 held, 1 kept, 20 unresolved");
  assert.equal(coachRecordWords({ k: 14, n: 28, baseline: { right: 15 } }), "14 right of 28 checked forecasts; a guess that nothing changes, 15");
  assert.equal(coachRecordWords({ k: 9, n: 14, baseline: { right: 8 }, sign: { verdict: "too_few" } }, { short: true }), "9 right of 14 checked forecasts; the guess, 8; too few to tell");
  const vw = (v) => ({ too_few: "too few to tell", no_clear_difference: "no clear difference" })[v];
  const kinds = [
    { kind: "number", coach_right: 13, rule_right: 9, scored: 24, verdict: "no_clear_difference" },
    { kind: "direction", coach_right: 0, rule_right: 5, scored: 5, verdict: "too_few" },
  ];
  assert.equal(kindWords(kinds, "direction", vw), "0 of 5 (guess 5 of 5, too few to tell)");
  assert.equal(kindWords(kinds, "number", vw, { guessOf: false }), "13 of 24 (guess 9, no clear difference)");
  assert.deepEqual(floorDays({ state: "ok", data: { met: [false, false, false, false, null, null, null] } }), { met: 0, logged: 4 });
});

test("the featured path: The Rate Flag → Prologue → the feature → What happens next → Subscribe", () => {
  assert.deepEqual(
    PATH.map((s) => s.label),
    ["1 · The Rate Flag", "2 · How it started", "3 · Park's Blind Spot, revisited", "What happens next", "Subscribe"],
  );
  assert.equal(PATH[2].to, "/story/features/parks-blind-spot-revisited/");
});
