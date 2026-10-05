// tests/js/ck_front_4586.test.mjs — #4586: the reshaped preview front page.
//
// Driven from the committed captures in tests/fixtures/kit_pages_4586/ (live, 2026-10-03
// and 2026-10-04). Nothing reads the wall clock. What is held: the daily mark draws one
// cell per day in a frame that never changes; the Today band is about the last 24 hours
// and nothing older; the week is sorted by a printed rule; a quote is verbatim or absent;
// every builder prints a sentence when its data is missing; nothing is first person.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const F = await import("../../site/assets/js/ck_front.js");
const FIX = join(dirname(fileURLToPath(import.meta.url)), "..", "fixtures", "kit_pages_4586");
const load = (name) => JSON.parse(readFileSync(join(FIX, `${name}.json`), "utf8"));
const edition = load("edition");
const B = edition.blocks;
const TODAY = edition.as_of;
const SERIES = B.week.data.weight_series;
const GONE = { state: "unavailable", absent_text: "Not served right now.", data: null };

const START = B.today.data.start_weight_lbs;
const GOAL = B.today.data.goal_weight_lbs;

test("the mark is always 28 cells ending today, whatever was recorded", () => {
  const cells = F.markDays(SERIES, TODAY, START, GOAL);
  assert.equal(cells.length, F.MARK_DAYS);
  assert.equal(cells[cells.length - 1].date, TODAY);
  assert.ok(F.markDays([], TODAY, START, GOAL).every((c) => c.gone === null));
});

test("a column's green is the share of the whole distance gone that day; a missed day is a gap, never a guess", () => {
  const cells = F.markDays([{ date: "2026-10-02", lbs: 300 }, { date: "2026-10-04", lbs: 250 }], "2026-10-04", 350, 150, 3);
  assert.deepEqual(cells.map((c) => c.gone), [0.25, null, 0.5]);
  const over = F.markDays([{ date: "2026-10-04", lbs: 360 }], "2026-10-04", 350, 150, 1);
  assert.equal(over[0].gone, 0, "above the start weight draws no green, never a negative bar");
  assert.equal(F.markDays(SERIES, TODAY, START, null)[27].gone, null, "no goal: no drawing");
});

test("the mark draws two rects per weighed day and says what it shows to a screen reader", () => {
  const html = F.markHTML(SERIES, TODAY, START, GOAL);
  const weighed = F.markDays(SERIES, TODAY, START, GOAL).filter((c) => c.gone !== null).length;
  assert.equal((html.match(/<rect /g) || []).length, 2 * weighed);
  assert.match(html, /role="img" aria-label="The last 28 days: 16\.3 of the 142\.3 pounds to the goal are gone as of the latest weigh-in/);
  assert.equal(F.markHTML([], TODAY, START, GOAL), "", "no weigh-ins: no drawing");
  assert.equal(F.markHTML(SERIES, "", START, GOAL), "");
});

test("the mark's caption carries the day, the weight and the distance, from served numbers", () => {
  assert.equal(F.markCaption(B.today, edition), "<b>311.0 lb</b> · Day 28 · 16.3 down, 126.0 to go to 185");
  const older = { ...B.today, data: { ...B.today.data, date: "2026-10-01" } };
  assert.match(F.markCaption(older, edition), /311\.0 lb<\/b> on October 1/);
  assert.equal(F.markCaption(GONE, edition), "");
});

test("this morning's weight is set against the weigh-in before it", () => {
  assert.equal(F.morningLine(B.week, TODAY), "311.0 lb, the same as Friday.");
  assert.equal(F.morningLine(GONE, TODAY), "");
});

test("the Today band is this morning, yesterday and the plan, one line each, with yesterday's full day", () => {
  const html = F.todayBandHTML(edition, B, "/next/v8/");
  assert.match(html, /<span class="ck-rows__key">This morning<\/span><span>311\.0 lb, the same as Friday\./);
  assert.match(html, /<span class="ck-rows__key">Yesterday, Friday<\/span>/);
  assert.match(html, /href="\/next\/v8\/day\/\?d=2026-10-02">The full day<\/a>/);
  assert.match(html, /at or above the protein target/);
  assert.doesNotMatch(html, /Steps|9,913|1,113/, "step counts stay off the front page");
  assert.match(html, /Recovery is the wrist strap’s morning score out of 100\./);
  assert.doesNotMatch(html, /Thursday|October 1/, "nothing older than yesterday");
  assert.ok((html.match(/<li>/g) || []).length <= 3, "at most three rows");
  assert.match(F.todayBandHTML(edition, { ...B, week: GONE }, "/"), /Not served right now\./);
});

test("a day with nothing recorded yet says so", () => {
  const future = { ...edition, as_of: "2026-10-05" };
  assert.match(F.todayBandHTML(future, B, "/"), /Nothing recorded yet today\./);
});

test("coach lines today are the served moves, or the block's own sentence", () => {
  assert.equal((F.coachTodayHTML(B.coach_lines).match(/<li>/g) || []).length, B.coach_lines.data.lines.length);
  assert.equal(F.coachTodayHTML({ state: "absent", absent_text: "No coach had anything to say on Sunday, October 4.", data: null }), '<p class="ck-soft">No coach had anything to say on Sunday, October 4.</p>');
});

test("the week is sorted by the printed rule: five days in seven, or a lower scale", () => {
  const { well, notWell } = F.weekSort(B.week);
  const names = (xs) => xs.map((x) => x.key);
  for (const item of [...well, ...notWell]) {
    const m = B.week.data.measures[item.key];
    if (item.key === "weight") continue;
    const met = m.data.met.filter((x) => x === true || x === false);
    assert.equal(names(well).includes(item.key), met.filter(Boolean).length / met.length >= F.WELL_SHARE, item.key);
  }
  const html = F.weekSortHTML(B.week, "/next/v8/");
  assert.match(html, /<p class="ck-label">Going well<\/p>/);
  assert.match(html, /<p class="ck-label">Not going well<\/p>/);
  assert.match(html, /href="\/next\/v8\/trend\/\?m=protein">Protein<\/a>/);
  assert.match(html, /Going well means the target was met on at least five days in seven/);
  assert.doesNotMatch(html, /Train/, "an unbroken run of training days is not sorted as a win");
  assert.match(F.weekSortHTML(GONE), /Not served right now\./);
});

test("a rising week puts the weight under not going well", () => {
  const up = JSON.parse(JSON.stringify(B.week));
  up.data.measures.weight.data.values = [310, 311, 312];
  assert.ok(F.weekSort(up).notWell.some((x) => x.key === "weight"));
});

test("first sentences are whole sentences inside the limit", () => {
  assert.equal(F.firstSentences("One. Two is longer. Three.", 10), "One.");
  assert.equal(F.firstSentences("One. Two.", 100), "One. Two.");
  assert.equal(F.firstSentences("no full stop here", 100), "");
});

test("the lead coach's read is quoted with its author, as an AI, and its date", () => {
  const html = F.leadReadHTML(load("weekly_priority"), "/next/v8/");
  assert.match(html, /Eli Marsh, the AI lead coach, on Monday, September 28/);
  assert.match(html, /“The one priority I've asked him to address next is his protein intake/);
  assert.doesNotMatch(html, /execute with precision/, "the recap of numbers is skipped for what the lead asked for");
  assert.match(F.leadReadHTML({ weekly_priority: "A plain read. Nothing else.", coach_name: "Eli Marsh", data_through: "2026-09-28" }), /“A plain read\. Nothing else\.”/);
  assert.match(F.leadReadHTML(null), /not served right now/);
  assert.match(F.leadReadHTML({ weekly_priority: "A read.", coach_name: "Eli Marsh" }), /not served right now/, "no date, no quote");
});

test("the podcast line is the guest's own first turn, verbatim, and absent when there is none", () => {
  const t = load("transcript_wk4");
  const q = F.guestQuote(t, "Marcus Webb");
  assert.ok(q.length > 20 && t.turns.some((turn) => turn.speaker === "Marcus Webb" && turn.line.includes(q)), "a verbatim run of the guest's line");
  assert.equal(F.guestQuote(t, "Nobody"), "");
  assert.equal(F.guestQuote(null, "Marcus Webb"), "");
});

test("the chapter and podcast lines are labelled as AI-written and carry Read and Listen", () => {
  const html = F.quotesHTML(B.chapter, load("transcript_wk4"), "/next/v8/");
  assert.match(html, /Written by AI from the record on September 29; Matthew reads each chapter before it publishes\./);
  assert.match(html, /Marcus Webb, the AI food coach, on the podcast/);
  assert.match(html, /<a class="ck-btn" href="\/journal\/posts\/week-07\/">Read · 5 min<\/a>/);
  assert.match(html, /<a class="ck-btn ck-btn--ghost" href="\/next\/v8\/story\/">Listen · 7 min<\/a>/);
  assert.doesNotMatch(F.quotesHTML(B.chapter, null, "/"), /on the podcast/, "no transcript: no podcast line");
  assert.match(F.quotesHTML(GONE, null), /Not served right now\./);
});

test("the follow box says what arrives next and when", () => {
  assert.equal(F.followLine(B.next), "The next chapter and podcast are due Wednesday, October 7. The week’s numbers go out every Sunday.");
  assert.match(F.followLine({}), /most weeks/);
});

test("nothing the builders emit carries an honorific, an ISO date in text, or a first-person line", () => {
  const all = [
    String(F.markCaption(B.today, edition)), F.todayBandHTML(edition, B, "/"), F.coachTodayHTML(B.coach_lines), F.weekSortHTML(B.week, "/"),
    F.followLine(B.next), F.weekSpan(B.week),
  ].join("\n").replace(/<[^>]+>/g, " ");
  assert.doesNotMatch(all, /\bDr\.\s/);
  assert.doesNotMatch(all, /\b20\d\d-\d\d-\d\d\b/);
  assert.doesNotMatch(all.replace(/“[^”]*”/g, ""), /\b(I|I’m|my|me)\b/, "generated copy is never in his voice");
});

test("a measure recorded on fewer than five days is not filed as falling short (red team, round 7)", () => {
  const thin = structuredClone(B.week);
  thin.data.measures.food.data.met = [true, true, false, null, null, null, null];
  const { well, notWell, tooFew } = F.weekSort(thin);
  assert.ok(tooFew.some((x) => x.key === "food"));
  assert.ok(![...well, ...notWell].some((x) => x.key === "food"));
  assert.match(F.weekSortHTML(thin, "/"), /<p class="ck-label">Too few days recorded to say<\/p>/);
  const full = structuredClone(B.week);
  full.data.measures.food.data.met = [true, true, false, false, false, true, true];
  assert.ok(F.weekSort(full).notWell.some((x) => x.key === "food"), "four of seven is sorted, and falls short");
  assert.doesNotMatch(F.weekSortHTML(full, "/"), /Too few days/);
});
