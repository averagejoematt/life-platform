// tests/js/ck_pages_4586.test.mjs — #4586: the four kit pages of the living front page.
//
// The builders are driven from the committed captures in tests/fixtures/kit_pages_4586/
// (live, 2026-10-03). Nothing here reads the wall clock: every date comes from a fixture.
// What is held: every block prints its own absence sentence instead of a blank; the
// coaches' count never renders without its comparison; no percentage picture on fewer
// than 20 calls; his words are quoted only when fresh; no honorific, no ISO date.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const P = await import("../../site/assets/js/ck_pages.js");
const FIX = join(dirname(fileURLToPath(import.meta.url)), "..", "fixtures", "kit_pages_4586");
const load = (name) => JSON.parse(readFileSync(join(FIX, `${name}.json`), "utf8"));
const edition = load("edition");
const B = edition.blocks;
const UNAVAILABLE = { state: "unavailable", as_of: null, source: null, absent_text: "The latest chapter is not served right now.", data: null };

test("the header carries the edition's one day and day number, in words", () => {
  assert.equal(P.headerDay(edition), "Saturday, October 3 · Day 28");
  assert.equal(P.headerDay({}), "");
});

test("a fresh chapter leads with its badge, title, player and the AI byline", () => {
  const html = P.chapterHTML(B.chapter, B.next);
  assert.match(html, /New this week · Week 4/);
  assert.match(html, /<h1>The Body Answers Back<\/h1>/);
  assert.match(html, /<audio controls preload="none" src="\/panelcast\/wk4\.mp3"/);
  assert.match(html, /Written by AI from the record on September 29\. Matthew reads each chapter before it publishes\./);
  assert.ok(html.indexOf("Written by AI") < html.indexOf("He has trained"), "the AI label sits above the AI's words");
});

test("a stale chapter is not called new, and an unserved one prints its sentence", () => {
  assert.match(P.chapterHTML({ ...B.chapter, state: "stale" }, B.next), /The latest chapter · Week 4/);
  assert.doesNotMatch(P.chapterHTML({ ...B.chapter, state: "stale" }, B.next), /New this week/);
  assert.equal(P.chapterHTML(UNAVAILABLE, B.next), '<p class="ck-soft">The latest chapter is not served right now.</p>');
});

test("a chapter with no episode says so instead of showing a dead player", () => {
  const noPod = { ...B.chapter, data: { ...B.chapter.data, podcast: { state: "absent", absent_text: "No podcast episode for this chapter yet.", data: null } } };
  const html = P.chapterHTML(noPod, B.next);
  assert.doesNotMatch(html, /<audio/);
  assert.match(html, /No podcast episode for this chapter yet\./);
});

test("today's weight says 'this morning' only on the day it was taken", () => {
  assert.match(P.todayHTML(B.today, edition), /<b>311\.0<\/b>.*lb this morning\. Down 16\.3 since September 6\./);
  const older = { ...B.today, state: "stale", data: { ...B.today.data, date: "2026-10-01" } };
  assert.match(P.todayHTML(older, edition), /lb on Thursday, October 1\./);
  assert.match(P.todayHTML({ state: "absent", absent_text: "No weigh-in yet.", data: null }, edition), /No weigh-in yet\./);
});

test("coach lines render at most what is served, and silence is a sentence", () => {
  const html = P.coachLinesHTML(B.coach_lines);
  assert.equal((html.match(/<li>/g) || []).length, 3);
  assert.match(html, /Lisa Park · sleep/);
  assert.match(P.coachLinesHTML({ state: "absent", absent_text: "The coaches have written nothing yet.", data: null }), /The coaches have written nothing yet\./);
  const reply = { state: "ok", data: { lines: [{ coach: "Max Reyes", domain: "training", text: "I disagree.", replies_to: "Lisa Park" }] } };
  assert.match(P.coachLinesHTML(reply), /Max Reyes · training · replying to Lisa Park/);
});

test("the coaches' count never renders without its comparison", () => {
  assert.equal(P.recordLine(B.record), "41 of 96 checked calls right. So far they do not beat a simple guess.");
  const alone = { ...B.record, data: { ...B.record.data, comparison_text: "" } };
  assert.equal(P.recordLine(alone), "");
  assert.doesNotMatch(P.recordBigHTML(alone), /ck-big/);
  assert.match(P.recordBigHTML(B.record), /41<span>of 96 checked calls<\/span>/);
  assert.match(P.recordBigHTML(B.record), /So far they do not beat a simple guess\./);
});

test("no percentage picture on fewer than 20 checked calls", () => {
  const html = P.teamHTML(load("coaches"));
  const row = (name) => html.split("<li>").find((li) => li.includes(name));
  assert.match(row("Lisa Park"), /10 of 23<span class="ck-meter">/);
  assert.doesNotMatch(row("Henning Brandt"), /ck-meter/);
  assert.match(row("Henning Brandt"), /9 of 18/);
  assert.match(row("Eli Marsh"), /no bets/);
  assert.match(row("Amara Patel"), /Sitting out: no sensor since August 27\./);
  const few = { ...B.record, data: { ...B.record.data, right: 3, decided: 7 } };
  assert.doesNotMatch(P.recordBigHTML(few), /ck-track/);
});

test("his words are quoted only when fresh; silence prints the block's sentence", () => {
  assert.equal(P.hisWordsFresh(B.his_words), false);
  assert.match(P.hisWordsHTML(B.his_words), /Nothing new in his own words since Wednesday, September 23\./);
  assert.doesNotMatch(P.hisWordsHTML(B.his_words), /ck-quote/);
  const fresh = { state: "ok", as_of: "2026-10-01", data: { text: "Right now I still feel good.", date: "2026-10-01" } };
  assert.equal(P.hisWordsFresh(fresh), true);
  assert.match(P.hisWordsHTML(fresh), /In my words · October 1/);
  assert.match(P.hisWordsHTML(fresh), /“Right now I still feel good\.”/);
  assert.match(P.hisWordsHTML({ ...fresh, data: { ...fresh.data, question: "What did this week ask of you?" } }), /Asked: What did this week ask of you\?/);
});

test("the bet card states the question, the date and both sides", () => {
  const html = P.betHTML(B.next);
  assert.match(html, /Settles Monday, October 5/);
  assert.match(html, /Max Reyes says no\. Lisa Park says yes\./);
  assert.equal(P.betLine(B.next), "A bet between Max Reyes and Lisa Park settles Monday, October 5.");
  assert.equal(P.moreBetsLine(load("coach_docket"), "2026-10-05"), "Three more bets settle on October 7, 12 and 16.");
  assert.equal(P.moreBetsLine({ open: [{ resolution_date: "2026-10-05" }] }, "2026-10-05"), "");
});

test("one right and one wrong, each with a plain measured result", () => {
  const { right, wrong } = P.verdictPick(load("coaches"));
  assert.equal(right.status, "confirmed");
  assert.equal(wrong.status, "refuted");
  assert.equal(wrong.eval_type, "point");
  const html = P.verdictsHTML(load("coaches"));
  assert.match(html, /The result was 166\. Checked October 3\./);
  assert.equal(P.verdictsHTML({ coaches: [] }), "");
});

test("the recap skips an editor's note and never prints a clipped sentence", () => {
  assert.equal(P.summarySentence("*Editor's note, October 2026 — a note.*\n\n*Day 17: the scale reads 315.0 lbs and a…"), "");
  assert.equal(P.summarySentence("*He trained every day. Then more.*…"), "He trained every day.");
  const html = P.recapHTML(P.postsInOrder(load("posts")));
  assert.doesNotMatch(html, /Editor/);
  assert.doesNotMatch(html, /…/);
  assert.match(html, /Week 3 · Storming Mode<\/span><span>Day 11 to Day 17 · 315\.0 lbs/);
});

test("chapters list in order with the current one marked; the chart labels both ends", () => {
  const posts = P.postsInOrder(load("posts"));
  assert.deepEqual(posts.map((p) => p.date), [...posts.map((p) => p.date)].sort());
  const rows = P.chapterRowsHTML(posts, { currentUrl: "/journal/posts/week-07/" });
  assert.equal((rows.match(/ck-rows__now/g) || []).length, 1);
  const chart = P.chartHTML(load("timeline").timeline.weights);
  assert.match(chart, /September 6 · 327\.3/);
  assert.match(chart, /ck-chart__line/);
  assert.equal(P.chartHTML([{ date: "2026-09-06", lbs: 327.3 }]), "");
});

test("nothing the builders emit carries an honorific or an ISO date", () => {
  const all = [
    P.chapterHTML(B.chapter, B.next), P.todayHTML(B.today, edition), P.coachLinesHTML(B.coach_lines), P.recordBigHTML(B.record),
    P.hisWordsHTML(B.his_words), P.betHTML(B.next), P.catchUpHTML(B.catch_up, B.chapter), P.teamHTML(load("coaches")),
    P.verdictsHTML(load("coaches")), P.recapHTML(P.postsInOrder(load("posts"))), P.episodeRowsHTML(load("episodes")),
  ].join("\n").replace(/<[^>]+>/g, " ");
  assert.doesNotMatch(all, /\bDr\.\s/);
  assert.doesNotMatch(all, /\b20\d\d-\d\d-\d\d\b/);
  assert.doesNotMatch(all, /undefined|NaN/);
});

test("the front page runs one sentence of the chapter, a Listen button and no idle player", () => {
  const html = P.chapterHTML(B.chapter, B.next, { heading: "h2", player: false, listenHref: "/next/v8/story/" });
  assert.doesNotMatch(html, /<audio/);
  assert.match(html, /<a class="ck-btn ck-btn--ghost" href="\/next\/v8\/story\/">Listen · 7 min<\/a>/);
  assert.match(html, /answer back\.<\/p>/);
  assert.doesNotMatch(html, /He is down 15 pounds/);
  assert.match(html, /On the podcast: the food coach, Marcus Webb\. Next chapter due Wednesday, October 7\./);
});

test("progress runs from the start to the goal, and is not drawn without a goal", () => {
  const html = P.todayHTML(B.today, edition);
  assert.match(html, /<i style="width:11%"><\/i>/);
  assert.match(html, /327\.3 at the start<\/span><span>126 to go to 185</);
  assert.equal(P.progressHTML({ ...B.today.data, goal_weight_lbs: null }), "");
});

test("the seven days show a dot per recorded day and the block's own sentence", () => {
  const html = P.weekHTML(B.week);
  assert.match(html, /Trained on 7 of 7 days recorded\./);
  assert.match(html, /aria-label="2 of 3 days"/);
  assert.equal((html.split("At or above")[0].split("Food")[1].match(/ck-dot/g) || []).length, 4, "three days recorded: two met, one open (the open dot carries two class tokens)");
  const gone = { ...B.week, data: { ...B.week.data, measures: { ...B.week.data.measures, sleep: { state: "unavailable", absent_text: "Sleep is not served right now.", data: null } } } };
  assert.match(P.weekHTML(gone), /Sleep is not served right now\./);
});

test("the rest of it is one served fact per area, each a door", () => {
  const html = P.lifeHTML(B.life, { habits: "/data/habits/", supplements: "/protocols/" });
  assert.match(html, /<a href="\/data\/habits\/">Habits: 5 of 7 daily habits kept on Friday, October 2\./);
  assert.match(html, /Supplements: 21 in the daily stack\./);
  assert.match(html, /Mind: Nothing new in his own words since Wednesday, September 23\./);
  assert.doesNotMatch(html, /Body:/);
});

test("a right call that gave a range says the result fell inside it", () => {
  assert.match(P.verdictsHTML(load("coaches")), /The result was 97, inside the range given\. Checked October 3\./);
});

test("each day opens in place to what was recorded that day, newest first", () => {
  const html = P.daysHTML(B.week, "2026-10-03");
  assert.equal((html.match(/<details>/g) || []).length, 7);
  assert.match(P.daysHTML(B.week, "2026-10-03", "/next/v8/"), /href="\/next\/v8\/day\/\?d=2026-10-02">The full day: lifts, food and trends<\/a>/);
  assert.match(html, /<time datetime="2026-10-03">Today<\/time>/);
  assert.match(html, /<time datetime="2026-10-02">Fri 2<\/time>/);
  assert.match(html, /<summary>311\.0 lb · trained · slept 8\.8 h<\/summary>/);
  assert.match(html, /Food<\/span><span>153 g protein, 1,732 kcal/);
  assert.ok(html.indexOf("2026-10-03") < html.indexOf("2026-09-27"), "newest day first");
  const empty = { ...B.week, data: { ...B.week.data, detail: [{ date: "2026-10-03", summary: "Nothing recorded yet.", facts: [] }] } };
  assert.doesNotMatch(P.daysHTML(empty, "2026-10-03"), /<details>/);
  assert.match(P.daysHTML(empty, "2026-10-03"), /Nothing recorded yet\./);
});
