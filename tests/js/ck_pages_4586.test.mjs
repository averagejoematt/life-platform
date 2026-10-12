// tests/js/ck_pages_4586.test.mjs — #4586: the four kit pages of the living front page.
//
// The builders are driven from the committed captures in tests/fixtures/kit_pages_4586/
// (one live capture, its time in _capture.json — #4671). Nothing here reads the wall clock:
// every date comes from a fixture, and a figure that changes with a recapture is read from the
// capture it tests, never pinned (#4839).
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
// The captured chapter (week 5) has no podcast episode yet. WITH_POD is that chapter carrying
// the week 4 episode as the edition served it on October 3, so the player stays pinned.
const POD = { state: "ok", as_of: "2026-10-01", source: "/panelcast/episodes.json", absent_text: "No podcast episode for this chapter yet.", data: { title: "EP4 · The Body Answers Back", guest: "Marcus Webb", guest_domain: "food", duration_sec: 420, duration_minutes: 7, mp3_url: "/panelcast/wk4.mp3", date: "2026-10-01" } };
const WITH_POD = { ...B.chapter, data: { ...B.chapter.data, podcast: POD } };
const WEIGHT = B.today.data.weight_lbs;
const fmt1 = (n) => n.toFixed(1);
// Dates and names the tests print are read from the capture they test, so a recapture that
// moves the open bet on never fails them (#4839).
const longDay = (iso) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", timeZone: "UTC" });
const shortDayOf = (iso) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { month: "long", day: "numeric", timeZone: "UTC" });
const BET = B.next.data.bet.data;
const BET_DAY = longDay(BET.settle_date);
const [SIDE_A, SIDE_B] = BET.sides.map((x) => x.coach);
const SAYS = (x) => `${x.coach} says ${x.says}.`;
const SIDES_LINE = BET.sides.map(SAYS).join(" ");
const OTHER_BET = load("coach_docket").open.map((d) => d.resolution_date).filter((d) => d && d !== BET.settle_date).sort()[0];
const UNAVAILABLE = { state: "unavailable", as_of: null, source: null, absent_text: "The latest chapter is not served right now.", data: null };

test("the header carries the edition's one day and day number, in words", () => {
  assert.match(P.headerDay(edition), new RegExp(`^[A-Z][a-z]+day, [A-Z][a-z]+ \\d+ · Day ${edition.day_n}$`));
  assert.equal(P.headerDay({}), "");
});

test("a fresh chapter leads with its badge, title, player and the AI byline", () => {
  const html = P.chapterHTML(WITH_POD, B.next);
  assert.match(html, /New this week · Week 5/);
  assert.match(html, /<h1>Park's Blind Spot<\/h1>/);
  assert.match(html, /<audio controls preload="none" src="\/panelcast\/wk4\.mp3"/);
  assert.match(html, /Written by AI from the record on October 6\. Matthew reads each chapter before it publishes\./);
  assert.ok(html.indexOf("Written by AI") < html.indexOf("After 23 consecutive"), "the AI label sits above the AI's words");
  // As captured: no episode yet, so no player and the block's own sentence.
  const live = P.chapterHTML(B.chapter, B.next);
  assert.doesNotMatch(live, /<audio/);
  assert.match(live, /No podcast episode for this chapter yet\./);
});

test("a stale chapter is not called new, and an unserved one prints its sentence", () => {
  assert.match(P.chapterHTML({ ...B.chapter, state: "stale" }, B.next), /The latest chapter · Week 5/);
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
  const down = B.today.data.start_weight_lbs - WEIGHT;
  assert.match(P.todayHTML(B.today, edition), new RegExp(`<b>${fmt1(WEIGHT)}</b>.*lb ${B.today.data.date === edition.as_of ? "this morning" : "on [A-Z][a-z]+day, [A-Z][a-z]+ \\d+"}\\. (Down|Up) ${fmt1(Math.abs(down))} since [A-Z][a-z]+ \\d+\\.`));
  const older = { ...B.today, state: "stale", data: { ...B.today.data, date: "2026-10-01" } };
  assert.match(P.todayHTML(older, edition), /lb on Thursday, October 1\./);
  assert.match(P.todayHTML({ state: "absent", absent_text: "No weigh-in yet.", data: null }, edition), /No weigh-in yet\./);
});

test("coach lines render at most what is served, and silence is a sentence", () => {
  const html = P.coachLinesHTML(B.coach_lines);
  assert.equal((html.match(/<li>/g) || []).length, B.coach_lines.data.lines.length);
  const first = B.coach_lines.data.lines[0];
  assert.ok(B.coach_lines.data.lines.length >= 1 && html.includes(`${first.coach} · ${first.domain}`), "each line names its coach and field");
  assert.match(P.coachLinesHTML({ state: "absent", absent_text: "The coaches have written nothing yet.", data: null }), /The coaches have written nothing yet\./);
  const reply = { state: "ok", data: { lines: [{ coach: "Max Reyes", domain: "training", text: "I disagree.", replies_to: "Lisa Park" }] } };
  assert.match(P.coachLinesHTML(reply), /Max Reyes · training · replying to Lisa Park/);
});

test("the coaches' count never renders without its comparison", () => {
  const rd = B.record.data;
  assert.ok(P.recordLine(B.record).startsWith(rd.count_text) && P.recordLine(B.record).endsWith(rd.comparison_text), "the count, then the comparison");
  const alone = { ...B.record, data: { ...B.record.data, comparison_text: "" } };
  assert.equal(P.recordLine(alone), "");
  assert.doesNotMatch(P.recordBigHTML(alone), /ck-big/);
  assert.ok(P.recordBigHTML(B.record).includes(`${rd.right}<span> of ${rd.decided} checked calls</span>`));
  assert.ok(P.recordBigHTML(B.record).includes(rd.comparison_text));
});

test("no percentage picture on fewer than 20 checked calls", () => {
  const html = P.teamHTML(load("coaches"));
  const row = (name) => html.split("<li>").find((li) => li.includes(name));
  const withRecord = load("coaches").coaches.filter((c) => c.record && c.record.n);
  assert.ok(withRecord.length >= 2, "the capture has coaches with a checked call");
  for (const c of withRecord) {
    assert.ok(row(c.name).includes(`${c.record.confirmed} of ${c.record.n}`), c.name);
    assert.equal(row(c.name).includes('<span class="ck-meter">'), c.record.n >= 20, `${c.name}: a percentage picture only from 20 checked calls`);
  }
  assert.match(row("Eli Marsh"), /no bets/);
  assert.match(row("Amara Patel"), /Sitting out: no sensor since August 27\./);
  const few = { ...B.record, data: { ...B.record.data, right: 3, decided: 7 } };
  assert.doesNotMatch(P.recordBigHTML(few), /ck-track/);
});

test("his words are quoted only when fresh; silence prints the block's sentence", () => {
  assert.equal(P.hisWordsFresh(B.his_words), false);
  assert.match(P.hisWordsHTML(B.his_words), new RegExp(`Nothing new in his own words since ${B.his_words.data.date_text}\\.`));
  assert.doesNotMatch(P.hisWordsHTML(B.his_words), /ck-quote/);
  const fresh = { state: "ok", as_of: "2026-10-01", data: { text: "Right now I still feel good.", date: "2026-10-01" } };
  assert.equal(P.hisWordsFresh(fresh), true);
  assert.match(P.hisWordsHTML(fresh), /In my words · October 1/);
  assert.match(P.hisWordsHTML(fresh), /“Right now I still feel good\.”/);
  assert.match(P.hisWordsHTML({ ...fresh, data: { ...fresh.data, question: "What did this week ask of you?" } }), /Asked: What did this week ask of you\?/);
});

test("the bet card states the question, the date and both sides", () => {
  const html = P.betHTML(B.next);
  // the question names its day, so the card says it once (#4809); a question that does not gets the line
  assert.match(html, new RegExp(`^<div class="ck-bet"><p><b>Will [^<]+ on ${BET_DAY}\\?</b></p>`));
  assert.doesNotMatch(html, new RegExp(`Settles ${BET_DAY}`));
  const undated = { ...B.next, data: { ...B.next.data, bet: { ...B.next.data.bet, data: { ...B.next.data.bet.data, question: "Will protein stay high?" } } } };
  assert.match(P.betHTML(undated), new RegExp(`<p class="ck-small">Settles ${BET_DAY}</p>`));
  // ruling 2026-10-11: off the front card the sides stand alone on one line; the reasons are the front card's
  assert.ok(html.includes(`<p class="ck-soft">${SIDES_LINE}</p>`));
  assert.doesNotMatch(html, /Fuel-cognition link|Protein intake gap/);
  assert.equal(P.betLine(B.next), `A bet between ${SIDE_A} and ${SIDE_B} settles ${BET_DAY}.`);
  assert.equal(P.moreBetsLine(load("coach_docket"), BET.settle_date), `One more bet settles on ${shortDayOf(OTHER_BET)}.`);
  assert.equal(P.moreBetsLine({ open: [{ resolution_date: "2026-10-12" }, { resolution_date: "2026-10-14" }, { resolution_date: "2026-10-16" }] }, "2026-10-12"), "Two more bets settle on October 14 and 16.");
  assert.equal(P.moreBetsLine({ open: [{ resolution_date: "2026-10-05" }] }, "2026-10-05"), "");
});

test("one right and one wrong, never a conditional or a claim that quotes a raw date", () => {
  const { right, wrong } = P.verdictPick(load("coaches"));
  assert.equal(right.status, "confirmed");
  assert.equal(wrong.status, "refuted");
  for (const c of [right, wrong]) assert.doesNotMatch(c.claim, /^\s*(if|once|when)\b|\b20\d\d-\d\d-\d\d\b/i);
  assert.equal(P.verdictsHTML({ coaches: [] }), "");
});

test("the showcase pair leads with the tightest right call and the clearest miss, each a door to its page", () => {
  const calls = load("calls");
  const html = P.callVerdictsHTML(calls, "/next/v8/");
  // #4647: not the newest right call (83.7 called, 97 came in, 22.5 allowed either way),
  // which reads as a miss marked right. The tightest rule on the wire is the pick.
  // #4808, the house rule: the tag (the rule, once), the call with the RESULT bold, then in one
  // soft line what the allowed distance is in words, the day it was graded on, and the door.
  assert.match(html, /--right">Right · within [\d.]+ [a-z]+ either way<\/span><p>[^<]+ called [^<]+\. <b>It came in at [^<]+\.<\/b><\/p>/);
  assert.match(html, /<p class="ck-soft">Graded on the reading for [A-Z][a-z]+ \d+\. Checked [A-Z][a-z]+ \d+\. <a class="ck-link" href="\/next\/v8\/call\/\?id=[a-z0-9-]+">The whole call<\/a>/);
  // both distances were computed the same way, so what they are is said once, under the pair
  assert.match(html, /<\/div><\/div><p class="ck-soft">Each allowed distance is one standard deviation of his readings over the 30 days before the call\.<\/p>$/);
  assert.equal((html.match(/standard deviation/g) || []).length, 1);
  // the coaches page's scorecard door closes that same paragraph (one line given back, 2026-10-11)
  const door = '<a class="ck-link" href="/coaching/scorecard/">Every prediction, right and wrong</a>';
  assert.ok(P.callVerdictsHTML(calls, "/next/v8/", "coaches", { trailer: door }).endsWith(`before the call. ${door}</p>`));
  assert.match(html, /<span class="ck-verdicts__tag">Wrong · not within [\d.]+ [a-z]*\s?either way<\/span><p>[^<]+ called [^<]+\. <b>It came in at [^<]+\.<\/b><\/p>/);
  const ids = [...html.matchAll(/call\/\?id=([a-z0-9-]+)/g)].map((m) => m[1]);
  assert.equal(ids.length, 2, "one door per call");
  for (const id of ids) assert.ok(calls.calls.some((c) => c.id === id), `${id} is a served call`);
  assert.equal(P.callVerdictsHTML(null), "");
  assert.equal(P.callVerdictsHTML({ calls: [] }), "");
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
  const html = P.chapterHTML(WITH_POD, B.next, { heading: "h2", player: false, listenHref: "/next/v8/story/" });
  assert.doesNotMatch(html, /<audio/);
  assert.match(html, /<a class="ck-btn ck-btn--ghost" href="\/next\/v8\/story\/">Listen · 7 min<\/a>/);
  assert.equal((html.match(/ck-premise/g) || []).length, 1, "one paragraph of the chapter");
  assert.match(html, /<p class="ck-premise ck-soft">After 23 consecutive training days/);
  assert.match(html, /On the podcast: the food coach, Marcus Webb\. Next chapter due Wednesday, October 14\./);
  // As captured, with no episode: no Listen button, and the next chapter's day still said.
  const live = P.chapterHTML(B.chapter, B.next, { heading: "h2", player: false, listenHref: "/next/v8/story/" });
  assert.doesNotMatch(live, /Listen|<audio/);
  assert.match(live, /Next chapter due Wednesday, October 14\./);
});

test("progress runs from the start to the goal, and is not drawn without a goal", () => {
  const html = P.todayHTML(B.today, edition);
  const t = B.today.data;
  assert.ok(html.includes(`<i style="width:${Math.round(((t.start_weight_lbs - t.weight_lbs) / (t.start_weight_lbs - t.goal_weight_lbs)) * 100)}%"></i>`));
  assert.ok(html.includes(`${fmt1(t.start_weight_lbs)} at the start</span><span>${fmt1(t.weight_lbs - t.goal_weight_lbs)} to go to ${t.goal_weight_lbs}<`));
  assert.equal(P.progressHTML({ ...B.today.data, goal_weight_lbs: null }), "");
});



test("the coaches' fallback never shows a call whose rule it cannot print, and says how many it passed over (#4808)", () => {
  // /api/coaches serves no allowed distance for a number call, so those are passed over and
  // counted; a direction call (its rule is the trend) is shown.
  const coaches = load("coaches");
  const html = P.verdictsHTML(coaches);
  const point = coaches.coaches.filter((c) => c.latest_checked && c.latest_checked.eval_type === "point" && ["confirmed", "refuted"].includes(c.latest_checked.status));
  assert.ok(point.length >= 1, "the fixture has number calls to pass over");
  for (const c of point) assert.ok(!html.includes(c.latest_checked.claim), `${c.name}'s number call was shown without its rule`);
  assert.match(html, /settled calls? (has|have) no rule the page can print, so (it is|they are) not shown as right or wrong here\./);
  assert.doesNotMatch(html, /not available for this call|Marked (right|wrong)/);
});

