import assert from "node:assert/strict";
import { test } from "node:test";

import { chapterCount, chapterCovers, chapterMeta, chapterPublished, chapterWindow, clip, gapWords, nextChapter, dayInWords, domainWords, kOfN, num, rangeInWords } from "../src/lib/format.js";
import { href, pathOf, PATH_OF } from "../src/lib/url.js";
import { COLLECTION_OF } from "../src/lib/edges.js";

test("dates are written in words, never ISO", () => {
  assert.equal(dayInWords("2026-10-31"), "31 October 2026");
  assert.equal(dayInWords("2026-10-31", { short: true }), "31 Oct");
  assert.equal(dayInWords("2026-10-31", { short: true, weekday: true }), "Saturday 31 Oct");
  assert.equal(dayInWords(null), null);
  assert.equal(dayInWords("not a date"), null);
});

test("a chapter's covered days and publication are its own, never its data date (2026-11-14)", () => {
  // program Week 10 ("The Rate Flag"): dated 10 November, covers Day 60 to Day 66, approved 13 November Pacific
  const week10 = { status: "published", week: 10, week_start: "2026-11-08", week_end: "2026-11-14", date: "2026-11-10", data_through: "2026-11-10", covers_start: "2026-11-04", covers_end: "2026-11-10", published_at: "2026-11-13" };
  assert.equal(chapterCovers(week10), "Days 60–66 · 4 to 10 November");
  assert.equal(chapterCovers(week10, { short: true }), "Days 60–66 · 4–10 Nov");
  assert.equal(chapterPublished(week10), "Published 13 November 2026");
  assert.deepEqual(chapterWindow(week10), ["2026-11-04", "2026-11-10"]);
  // Week 1 covered Day 1 to Day 3
  assert.equal(chapterCovers({ week: 1, week_start: "2026-09-06", covers_start: "2026-09-06", covers_end: "2026-09-08" }), "Days 1–3 · 6 to 8 September");
  // not served (an older Lambda, fixture mode): no covered days, the program week is the window, and the data date is
  // never called the publication
  const old = { ...week10, covers_start: null, covers_end: null, published_at: null };
  assert.equal(chapterCovers(old), null);
  assert.deepEqual(chapterWindow(old), ["2026-11-08", "2026-11-14"]);
  assert.equal(chapterPublished(old), "Data through 10 November 2026");
  assert.equal(chapterPublished(old, { lower: true }), "data through 10 November 2026");
  assert.equal(chapterPublished({ status: "held", date: "2026-10-27" }), null);
  assert.equal(chapterWindow({ status: "pending" }), null);
});

test("one chapter, one name: number, days and publication from chapterMeta on every page (#6081)", () => {
  const week10 = { id: "week-12", status: "published", week: 10, week_label: "Week 10", week_start: "2026-11-08", week_end: "2026-11-14", date: "2026-11-10", data_through: "2026-11-10", covers_start: "2026-11-04", covers_end: "2026-11-10", published_at: "2026-11-13" };
  const m = chapterMeta(week10);
  assert.equal(m.number, "10");
  assert.equal(m.name, "Chapter 10");
  assert.equal(m.window, "Days 60–66 · 4 to 10 November");
  assert.equal(m.windowShort, "Days 60–66 · 4–10 Nov");
  assert.equal(m.published, "Published 13 November 2026");
  // #6161: a plain sentence, rendered at the foot of the chapter (never before its prose)
  assert.equal(m.weekNote, "This chapter covers days 60–66, 4 to 10 November; program week 10 ran 8 to 14 November.");
  assert.deepEqual(m.tick, { date: "2026-11-10", n: "10" });
  // Week 6 serves no covered days: the program week, said as one — never bare, never a span off the data date
  const week6 = { ...week10, week: 6, week_label: "Week 6", week_start: "2026-10-11", week_end: "2026-10-17", date: "2026-10-13", covers_start: null, covers_end: null, published_at: "2026-10-17" };
  assert.equal(chapterMeta(week6).window, "program week 11 to 17 October");
  assert.equal(chapterMeta(week6).windowShort, "program week 11–17 Oct");
  assert.equal(chapterMeta(week6).weekNote, null, "nothing to reconcile when the chapter is its program week");
  assert.deepEqual(chapterMeta(week6).tick, { date: "2026-10-17", n: "6" });
  // the prologue: "Prologue", 00 in a numeral slot, no window, its data date never called the publication
  const pro = { status: "published", week: 0, week_label: "Prologue · Part I", date: "2026-08-31", data_through: "2026-08-31", published_at: null, week_start: null, week_end: null };
  assert.equal(chapterMeta(pro).number, "00");
  assert.equal(chapterMeta(pro).name, "Prologue");
  assert.equal(chapterMeta(pro).window, null);
  assert.equal(chapterMeta(pro).published, "Data through 31 August 2026");
  assert.equal(chapterMeta(pro).tick, null);
  // a held week: its program week, labelled; no publication
  const held = { status: "held", week: 8, week_start: "2026-10-25", week_end: "2026-10-31", covers_start: "2026-10-20", covers_end: "2026-10-26" };
  assert.equal(chapterMeta(held).window, "program week 25 to 31 October");
  assert.equal(chapterMeta(held).published, null);
  assert.equal(chapterMeta(null), null);
});

test("the chapters are counted once, the prologue said as such; the gaps in /story/'s words; the next chapter from one source (#6081)", () => {
  const list = [
    { status: "published", week: 0 },
    ...[1, 2, 3, 4, 5, 6, 10].map((week) => ({ status: "published", week })),
    { status: "skipped", week: 7 },
    { status: "held", week: 8 },
    { status: "held", week: 9 },
    { status: "pending", week: 11, week_start: "2026-11-15", week_end: "2026-11-21" },
  ];
  assert.deepEqual(chapterCount(list), { n: 7, prologue: true, words: "7 chapters and a prologue" });
  assert.equal(chapterCount(list, { spell: true, capital: true }).words, "Seven chapters and a prologue");
  assert.equal(chapterCount([{ status: "published", week: 6 }], { spell: true, capital: true }).words, "One chapter");
  assert.equal(gapWords(list, 7, 9), "Week 7 was skipped; weeks 8 and 9 are held.");
  assert.equal(gapWords(list, 8, 8), "Week 8 is held.");
  assert.equal(gapWords([], 3, 5), "Weeks 3 to 5 have no chapter.");
  assert.equal(gapWords(list, 9, 8), null);
  // the draft date numbers the chapter by the unpublished week that holds it — not the latest chapter + 1
  assert.deepEqual(nextChapter(list, "2026-11-18"), { number: "11", date: "2026-11-18" });
  assert.deepEqual(nextChapter(list, "2026-12-01"), { number: null, date: "2026-12-01" });
  assert.equal(nextChapter(list, null), null);
});

test("ranges in words cross months and years plainly", () => {
  assert.equal(rangeInWords("2026-09-30", "2026-10-06"), "30 September to 6 October");
  assert.equal(rangeInWords("2026-09-30", "2026-10-06", { short: true }), "30 Sep – 6 Oct");
  assert.equal(rangeInWords("2026-11-04", "2026-11-10", { year: true }), "4 to 10 November 2026");
  assert.equal(rangeInWords("2026-12-29", "2027-01-04"), "29 December 2026 to 4 January 2027");
  assert.equal(rangeInWords("2026-11-10", "2026-11-04"), null);
  assert.equal(rangeInWords(null, "2026-11-04"), null);
});

test("numbers: fixed decimals, en-GB grouping, a dash for nothing", () => {
  assert.equal(num(19730), "19,730");
  assert.equal(num(296.64, 1), "296.6");
  assert.equal(num(null), "—");
  assert.equal(num(Number.NaN), "—");
});

test("the record is K of N, and never a bare percentage", () => {
  assert.equal(kOfN(19, 48), "19 of 48 right");
  assert.equal(kOfN(null, 48), "48 checked");
  assert.equal(kOfN(0, 0), "no checked call yet");
  assert.doesNotMatch(kOfN(19, 48), /%/);
});

test("clip cuts on a word and marks the cut", () => {
  const s = "Deep sleep percentage would rise as zone-2 training volume built, driven by adenosine";
  const c = clip(s, 40);
  assert.ok(c.length <= 40);
  assert.ok(c.endsWith("…"));
  assert.ok(!c.includes("  "));
  assert.equal(clip("short", 40), "short");
});

test("href joins the base path without doubling slashes", () => {
  assert.equal(href("/story/", "/"), "/story/");
  assert.equal(href("/story/", "/next/v9/"), "/next/v9/story/");
  assert.equal(href("story/", "/next/v9"), "/next/v9/story/");
});

test("every object type has a canonical path, directory-style, and episodes resolve to their chapter", () => {
  for (const t of Object.keys(COLLECTION_OF)) {
    assert.ok(PATH_OF[t], `no path for ${t}`);
    const p = pathOf(t, "x1");
    assert.ok(p.startsWith("/") && p.endsWith("/"), `${t}: ${p}`);
  }
  assert.equal(pathOf("episode", "wk8", { chapter_id: "week-08" }), "/story/week-08/#listen");
  assert.throws(() => pathOf("nope", "x"), /no canonical path/);
});

test("a coach's domain id is shown in words, never as an identifier", () => {
  assert.equal(domainWords("nutrition_science"), "nutrition");
  assert.equal(domainWords("biostatistics_n1_research"), "the statistics");
  assert.equal(domainWords("some_new_field"), "some new field");
  assert.equal(domainWords(null), "");
});
