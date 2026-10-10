// tests/js/ck_front_4586.test.mjs — #4586: the reshaped preview front page.
//
// Driven from the committed captures in tests/fixtures/kit_pages_4586/ (one live capture,
// its time in _capture.json — #4671: 2026-10-10 02:38 UTC, edition day October 9). Nothing
// reads the wall clock. What is held: the daily mark draws one
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

// The captured chapter (week 5) has no podcast episode yet: WITH_POD carries the week 4 episode
// as the edition served it on October 3. The captured lead read is null (the route served no
// weekly priority at capture time): LEAD_READ is the read it served on September 28.
const POD = { state: "ok", as_of: "2026-10-01", source: "/panelcast/episodes.json", absent_text: "No podcast episode for this chapter yet.", data: { title: "EP4 · The Body Answers Back", guest: "Marcus Webb", guest_domain: "food", duration_sec: 420, duration_minutes: 7, mp3_url: "/panelcast/wk4.mp3", date: "2026-10-01" } };
const WITH_POD = { ...B.chapter, data: { ...B.chapter.data, podcast: POD } };
const LEAD_READ = {"weekly_priority": "I'm watching Matthew execute with precision: 43 logged training sessions in 30 days, zero missed zone-2 workouts, and a consistent 1,500-calorie eating window across 21 food-logged days. His weight has dropped 12.8 pounds over three weeks—aggressive and intentional—and his recovery score is holding steady at 89%. On day 23 of the Foundation phase, the structural work is solid. The one priority I've asked him to address next is his protein intake, currently averaging 153.5 grams across logged days against a 170-gram floor. This isn't about motivation; it's about convenience. By locking one meal into a deliberate, low-friction protein choice, he can close this gap and protect lean mass as the caloric deficit compounds through the remaining 11 months.", "coach_name": "Eli Marsh", "data_through": "2026-09-28"};

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
  assert.match(html, /role="img" aria-label="The last 28 days: 21\.2 of the 142\.3 pounds to the goal are gone as of the latest weigh-in/);
  assert.equal(F.markHTML([], TODAY, START, GOAL), "", "no weigh-ins: no drawing");
  assert.equal(F.markHTML(SERIES, "", START, GOAL), "");
});

test("the mark's caption carries the day, the weight and the distance, from served numbers", () => {
  assert.equal(F.markCaption(B.today, edition), "<b>306.1 lb</b> · Day 34 · 21.2 down, 121.1 to go to 185");
  const older = { ...B.today, data: { ...B.today.data, date: "2026-10-01" } };
  assert.match(F.markCaption(older, edition), /306\.1 lb<\/b> on October 1/);
  assert.equal(F.markCaption(GONE, edition), "");
});

test("this morning's weight is set against the weigh-in before it", () => {
  assert.equal(F.morningLine(B.week, TODAY), "306.1 lb, down 1.1 from Thursday.");
  assert.equal(F.morningLine(GONE, TODAY), "");
});

test("the Today band is this morning, yesterday and the plan, one line each, with yesterday's full day", () => {
  const html = F.todayBandHTML(edition, B, "/next/v8/");
  assert.match(html, /<span class="ck-rows__key">Today so far<\/span><span>306\.1 lb, down 1\.1 from Thursday\./);
  assert.match(html, /<span class="ck-rows__key">Yesterday, Thursday<\/span>/);
  assert.match(html, /href="\/next\/v8\/day\/\?d=2026-10-08">The full day<\/a>/);
  assert.doesNotMatch(html, /Steps|steps/, "step counts stay off the front page");
  assert.match(html, /Recovery is the wrist strap’s morning score out of 100\./);
  assert.doesNotMatch(html, /Wednesday|October 7/, "nothing older than yesterday");
  // The food log ends October 5 in this capture: read on October 6, yesterday carries its food.
  assert.match(F.todayBandHTML({ ...edition, as_of: "2026-10-06" }, B, "/next/v8/"), /146 g protein, 1,632 kcal, under the protein target/);
  assert.ok((html.match(/<li>/g) || []).length <= 3, "at most three rows");
  assert.match(F.todayBandHTML(edition, { ...B, week: GONE }, "/"), /Not served right now\./);
});

test("a day with nothing recorded yet says so", () => {
  const future = { ...edition, as_of: "2026-10-10" };
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
  assert.match(F.leadReadHTML(load("weekly_priority"), "/next/v8/"), /not served right now/, "the captured read is null: a sentence, never a blank quote");
  const html = F.leadReadHTML(LEAD_READ, "/next/v8/");
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
  const html = F.quotesHTML(WITH_POD, load("transcript_wk4"), "/next/v8/");
  assert.match(html, /Written by AI from the record on October 6; Matthew reads each chapter before it publishes\./);
  assert.match(html, /Marcus Webb, the AI food coach, on the podcast/);
  assert.match(html, /<a class="ck-btn" href="\/journal\/posts\/week-08\/">Read · 6 min<\/a>/);
  assert.doesNotMatch(F.quotesHTML(B.chapter, load("transcript_wk4"), "/"), /on the podcast|Listen/, "as captured, no episode: no podcast line");
  assert.match(html, /<a class="ck-btn ck-btn--ghost" href="\/next\/v8\/story\/">Listen · 7 min<\/a>/);
  assert.doesNotMatch(F.quotesHTML(B.chapter, null, "/"), /on the podcast/, "no transcript: no podcast line");
  assert.match(F.quotesHTML(GONE, null), /Not served right now\./);
});

test("the follow box says what arrives next and when", () => {
  assert.equal(F.followLine(B.next), "The next chapter and podcast are due Wednesday, October 14. The week’s numbers go out every Sunday.");
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
