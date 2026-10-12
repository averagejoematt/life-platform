// tests/js/ck_front_argument_4586.test.mjs — round 8 of the preview front page (#4586):
// the page leads with what the coaches are arguing about and the clearest miss, and the
// week band is its own page.
//
// Driven from live captures of GET /api/coach_moves?date=<day> for 2026-10-05 → 10-09
// (tests/fixtures/front_argument_4586/, the wire minus _meta). What is held, after round
// 8a's seven reviewers: only the open bet is ever headed "disagree" (two coaches on opposite
// sides of a dated question), with the live number against it; an exchange is "the latest
// exchange" and stands in only when there is no bet; a line in which a coach names herself
// is never chosen; the Today band never prints an empty room under a heading; the miss
// rotates to the week's clearest; the deeper rows and the week page print a sentence for a
// failed block.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const F = await import("../../site/assets/js/ck_front.js");
const P = await import("../../site/assets/js/ck_pages.js");
const C = await import("../../site/assets/js/ck_call.js");
const HERE = dirname(fileURLToPath(import.meta.url));
const FIX = join(HERE, "..", "fixtures", "front_argument_4586");
const KIT = join(HERE, "..", "fixtures", "kit_pages_4586");
const load = (dir, name) => JSON.parse(readFileSync(join(dir, `${name}.json`), "utf8"));
const DAYS = readdirSync(FIX).filter((n) => n.startsWith("coach_moves_")).map((n) => load(FIX, n.replace(/\.json$/, "")));
const edition = load(KIT, "edition");
const B = edition.blocks;
const BASE = "/next/v8/";
const inWords = (iso) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { month: "long", day: "numeric", timeZone: "UTC" });
const esc0 = (t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const BETD = B.next.data.bet.data;
const [SA, SB] = BETD.sides;
const OTHER = load(KIT, "coach_docket").open.map((d) => d.resolution_date).filter((d) => d && d !== BETD.settle_date).sort()[0];
const MORE_BETS = `One more bet settles on ${inWords(OTHER)}.`;
const WEEK_SPAN = `${inWords(B.week.data.days[0])} to ${inWords(B.week.data.days.at(-1))}`;
// The edition's `next` block with its bet absent: what the page sees between bets.
const NO_BET = { ...B.next, data: { ...B.next.data, bet: { state: "absent", as_of: null, source: "/api/coach_docket", absent_text: "No coach bet is waiting to settle.", data: null } } };

test("the fixtures are the wire: five days, one absent, eight lines, three of them self-naming", () => {
  assert.equal(DAYS.length, 5);
  assert.deepEqual(DAYS.map((d) => d.state).sort(), ["absent", "ok", "ok", "ok", "ok"]);
  const lines = F.argumentLines(DAYS);
  assert.equal(lines.length, 8);
  assert.deepEqual(lines.filter(F.namesSelf).map((l) => `${l.date} ${l.coach}`), ["2026-10-09 Henning Brandt", "2026-10-07 Lisa Park", "2026-10-05 Marcus Webb"]);
});

test("a coach naming herself is read as such; an ordinary word that is also a name is not", () => {
  assert.equal(F.namesSelf({ coach: "Lisa Park", text: "I was skeptical when Lisa called the spike genuine." }), true);
  assert.equal(F.namesSelf({ coach: "Henning Brandt", text: "Henning’s prediction just came true." }), true);
  assert.equal(F.namesSelf({ coach: "Lisa Park", text: "A walk in the park helped." }), false);
  assert.equal(F.namesSelf({ coach: "Max Reyes", text: "Max effort today." }), false);
  assert.equal(F.namesSelf({ coach: "Max Reyes", text: "Max Reyes was right." }), true);
  assert.equal(F.namesSelf({ coach: "James Okafor", text: "Marcus Webb is right that dinner underperforms." }), false);
});

test("with an open bet, the bet is the argument: two coaches on opposite sides, and only that is headed 'disagree'", () => {
  const pick = F.pickArgument(DAYS, B.next);
  assert.equal(pick.kind, "bet");
  assert.deepEqual(pick.bet.data.sides.map((s) => s.says).sort(), ["no", "yes"], "opposite sides by construction");
  assert.equal(F.argumentLabel(pick), "The open bet");
  assert.equal(F.argumentHeading(pick), "Two coaches disagree.");
  assert.equal(F.argumentHTML(pick, BASE), "", "the bet card carries it; no exchange is printed above a bet");
  assert.deepEqual(F.argumentTexts(pick), []);
  // The live number against the bet: the newest recorded day of the measure the question names.
  const line = F.betLiveLine(pick.bet, B.week);
  assert.match(line, /^(Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day: \d+(\.\d)? g protein\. This week, at or above 170 g protein on \d of \d days recorded\.$/, line);
  // The first mention of a name carries the job, when the served lines pair the name with its id.
  const jobs = F.jobsByName(DAYS);
  // a name carries its job only when the served lines pair it with one (a recapture may bring a coach with none)
  const who = (c) => (jobs[c] ? `${c} (${jobs[c]})` : c);
  // #4809: each side carries the coach's reason — the opening position the docket row holds, one
  // clause in its served words (`next.bet.data.sides[].reason`) — on its own line under the question.
  const why = Object.fromEntries(pick.bet.data.sides.map((s) => [s.coach, s.reason]));
  assert.ok(why[SA.coach] && why[SB.coach], "the wire fixture serves both reasons");
  assert.deepEqual(F.betSidesLines(pick.bet, jobs), [
    `${who(SA.coach)} says ${SA.says}: “${why[SA.coach]}”.`,
    `${who(SB.coach)} says ${SB.says}: “${why[SB.coach]}”.`,
  ]);
  assert.equal(F.betSidesLine(pick.bet), `${SA.coach} says ${SA.says}: “${why[SA.coach]}”. ${SB.coach} says ${SB.says}: “${why[SB.coach]}”.`);
  // a side with no served reason is the side alone; nothing is written in its place
  const bare = { ...pick.bet, data: { ...pick.bet.data, sides: pick.bet.data.sides.map((s) => ({ coach: s.coach, says: s.says })) } };
  assert.equal(F.betSidesLine(bare, jobs), `${who(SA.coach)} says ${SA.says}. ${who(SB.coach)} says ${SB.says}.`);
  // Ruling 2026-10-11 (the coaches page keeps four screens): the FRONT card prints each reason
  // under its side; the coaches page's card prints the sides alone, on one line, and its door
  // goes to the front card — the two doors never loop on a promise neither page keeps.
  const front = P.frontReadSlots(edition, B, BASE)["ck-bet"];
  assert.match(front, /<a class="ck-link" href="\/next\/v8\/coaches\/#ck-bet">Every open bet, on the coaches page<\/a>/, front);
  assert.doesNotMatch(front, /What each one argued/, "the front card prints the argument itself");
  const coaches = P.betHTML(B.next, { ...P.reasonsDoor(B.next, BASE), extra: MORE_BETS, oneLine: true });
  for (const [who, reason] of Object.entries(why)) {
    const esc = (t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    assert.match(front, new RegExp(`<p class="ck-soft">${esc(who)}(?: \\([a-z ]+\\))? says (yes|no): “${esc(reason)}”\\.</p>`), front);
    assert.ok(!coaches.includes(reason), `the coaches page does not print ${who}'s reason`);
  }
  // one paragraph (the four-screen budget): the sides, the door to the reasons, the extra sentence
  assert.match(coaches, new RegExp(`<p class="ck-soft">${esc0(`${SA.coach} says ${SA.says}. ${SB.coach} says ${SB.says}.`)} <a class="ck-link" href="\\/next\\/v8\\/#ck-bet">Why each says so\\.</a> ${esc0(MORE_BETS)}</p></div>$`), coaches);
  // no served reason: no door to a card that would not print one
  assert.deepEqual(P.reasonsDoor({ ...B.next, data: { ...B.next.data, bet: bare } }, BASE), {});
  assert.match(P.betHTML(B.next, { sidesText: "x says no.", extra: "Friday: 1 g.", href: "/next/v8/coaches/#ck-bet" }), /<p class="ck-soft">x says no\.<\/p><p class="ck-soft">Friday: 1 g\.<\/p><p><a class="ck-link" href="\/next\/v8\/coaches\/#ck-bet">What each one argued<\/a><\/p><\/div>$/);
  const food = B.week.data.measures.food.data.values;
  const lastIdx = food.map((v, i) => (typeof v === "number" ? i : -1)).filter((i) => i >= 0).pop();
  assert.match(line, new RegExp(`: ${String(Number(food[lastIdx].toFixed(1)))} g protein\\. `));
  assert.equal(F.betLiveLine({ ...pick.bet, data: { ...pick.bet.data, question: "Will the moon be full on Monday?" } }, B.week), "", "a question naming no measure the week carries");
  assert.equal(F.betLiveLine(pick.bet, { state: "unavailable", absent_text: "x", data: null }), "");
});

test("with no bet, the newest reply and the line it answers are the latest exchange — never 'disagree'", () => {
  const pick = F.pickArgument(DAYS, NO_BET);
  assert.equal(pick.kind, "reply");
  assert.equal(pick.second.coach, "James Okafor");
  assert.equal(pick.second.date, "2026-10-08");
  assert.equal(pick.second.replies_to, "Marcus Webb");
  assert.equal(pick.first.coach, "Marcus Webb");
  assert.equal(pick.first.date, "2026-10-07");
  assert.equal(F.argumentLabel(pick), "The latest exchange");
  assert.equal(F.argumentHeading(pick), "One coach answers another.");
  const html = F.argumentHTML(pick, BASE);
  assert.equal((html.match(/<li>/g) || []).length, 2);
  assert.match(html, /Marcus Webb<\/a> · Wednesday, October 7<\/span><span>“James Okafor's protein hold deserves scrutiny/);
  assert.match(html, /James Okafor<\/a> · answering Marcus Webb · Thursday, October 8<\/span>/);
  assert.match(html, /href="\/next\/v8\/coach\/\?c=labs_coach"/);
  assert.doesNotMatch(html, /\b20\d\d-\d\d-\d\d\b/);
  assert.doesNotMatch(F.argumentHeading(pick), /disagree/i);
  assert.deepEqual(F.argumentTexts(pick), [pick.first.text, pick.second.text]);
});

test("a self-naming line is never the exchange, even when it is the newest reply's target", () => {
  const days = [
    { state: "ok", date: "2026-10-02", lines: [{ coach_id: "sleep_coach", coach: "Lisa Park", move: "call", text: "Lisa expects a rest day." }] },
    { state: "ok", date: "2026-10-03", lines: [{ coach_id: "physical_coach", coach: "Max Reyes", move: "reply", replies_to: "Lisa Park", text: "I disagree with Lisa Park: keep the streak." }] },
  ];
  const pick = F.pickArgument(days, NO_BET);
  assert.equal(pick.kind, "reply");
  assert.equal(pick.first, null, "the answered line names its own speaker and is left out");
  assert.match(F.argumentHTML(pick, BASE), /answering Lisa Park/);
  const self = [{ state: "ok", date: "2026-10-03", lines: [{ coach: "Max Reyes", move: "reply", replies_to: "Lisa Park", text: "Max Reyes disagrees." }] }];
  assert.equal(F.pickArgument(self, NO_BET), null);
});

test("with no bet and no reply, nothing is called an argument", () => {
  const noReplies = DAYS.map((d) => ({ ...d, lines: (d.lines || []).filter((l) => l.move !== "reply") }));
  const none = F.pickArgument(noReplies, NO_BET);
  assert.equal(none, null);
  assert.equal(F.argumentHTML(none, BASE), "");
  assert.equal(F.argumentLabel(none), "The coaches");
  assert.equal(F.argumentHeading(none), "Nothing is in dispute this week.");
  assert.equal(F.pickArgument([], null), null);
  assert.equal(F.pickArgument([null, {}, { state: "absent", date: "2026-10-10", lines: [] }], { state: "unavailable", absent_text: "x", data: null }), null);
});

test("the Today band leaves out a line the argument already printed, and says nothing when every line was", () => {
  const block = { state: "ok", as_of: "2026-10-08", data: { lines: [{ coach: "James Okafor", domain: "labs", text: "A line the argument printed.", replies_to: "Marcus Webb" }, { coach: "Nathan Reeves", domain: "mind", text: "A question for Matthew?" }] } };
  const html = F.coachTodayHTML(block, { skip: ["A line the argument printed."] });
  assert.equal((html.match(/<li>/g) || []).length, 1);
  assert.match(html, /Nathan Reeves · mind/);
  assert.equal(F.coachTodayHTML(block, { skip: block.data.lines.map((l) => l.text) }), "");
  assert.equal(F.coachTodayHTML(block), F.coachTodayHTML(block, { skip: [] }));
  assert.match(F.coachTodayHTML({ state: "absent", absent_text: "No coach had anything to say on Saturday, October 10.", data: null }, { skip: ["x"] }), /No coach had anything to say on Saturday, October 10\./);
});

test("when no coach spoke today, the newest SHORT line heard stands with its day and the coach's job — never a self-naming one, never one already printed", () => {
  const words = (t) => t.trim().split(/\s+/).length;
  const clean = F.argumentLines(DAYS).filter((l) => !F.namesSelf(l));
  const expected = clean.find((l) => words(l.text) <= F.HEARD_MAX_WORDS);
  assert.ok(words(clean[0].text) > F.HEARD_MAX_WORDS, "the wire's newest clean line is long, so the rule has something to prefer");
  const html = F.lastHeardHTML(DAYS, [], BASE);
  assert.equal((html.match(/<li>/g) || []).length, 1);
  assert.ok(html.includes(`“${expected.text}”`), html);
  assert.match(html, /<\/a> \((food|mind|blood tests|sleep|statistics|training|blood sugar|lead)\) · /, "the job beside the name");
  const skipped = F.lastHeardHTML(DAYS, clean.filter((l) => words(l.text) <= F.HEARD_MAX_WORDS).map((l) => l.text), BASE);
  assert.ok(skipped.includes(`“${clean[0].text}”`), "with every short line printed already, the newest line at all");
  assert.equal(F.lastHeardHTML([], [], BASE), "");
  assert.doesNotMatch(html, /\b20\d\d-\d\d-\d\d\b/);
});

test("the argument reads the edition's day and the six before it", () => {
  assert.deepEqual(P.argumentDays("2026-10-09"), ["2026-10-09", "2026-10-08", "2026-10-07", "2026-10-06", "2026-10-05", "2026-10-04", "2026-10-03"]);
  assert.deepEqual(P.argumentDays(""), []);
  assert.equal(P.argumentDays("2026-03-01")[1], "2026-02-28");
});

test("the miss leads with the week's clearest wrong call when there is one, else the clearest on record, and says which", () => {
  const calls = load(KIT, "calls");
  const all = C.callsOf(calls);
  const recentWrong = all.filter((c) => c.kind !== "bet" && c.verdict === "wrong" && c.settled_date >= "2026-10-02" && c.settled_date <= "2026-10-09");
  const pick = C.lastCallPick(calls, "2026-10-09");
  if (recentWrong.length) {
    assert.equal(pick.kind, "recent");
    assert.ok(pick.call.settled_date >= "2026-10-02" && pick.call.settled_date <= "2026-10-09");
  } else {
    assert.equal(pick.kind, "wrong");
  }
  assert.equal(C.lastCallPick(calls).kind, "wrong", "without a day, the all-time clearest miss");
  assert.match(C.lastCallHTML(calls, BASE, "2026-10-09"), new RegExp(`call/\\?id=${pick.call.id}`));
  const withJobs = C.lastCallHTML(calls, BASE, "2026-10-09", F.SHORT_JOBS);
  // #4808, the house rule: the tag, then the call with the result in bold
  assert.match(withJobs, new RegExp(`^<div class="ck-bet"><p class="ck-small">Settled [A-Z][a-z]+, [A-Z][a-z]+ \\d+ · ${pick.call.coach_name}, the [a-z ]+ coach</p><span class="ck-verdicts__tag[^"]*">(Right|Wrong) · [^<]+</span><p>[^<]+ <b>${pick.call.happened_short.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}</b></p>`), withJobs);
  assert.equal(C.lastCallPick(calls, "2020-01-01").kind, "wrong", "a window with nothing settled falls back to the record");
  assert.deepEqual(C.lastCallPick({ state: "ok", calls: [] }), { call: null, kind: "" });
  assert.deepEqual(C.lastCallPick(null), { call: null, kind: "" });
});

test("the deeper rows: the chapter is one door with its week and its own first sentence; a failed block is its sentence", () => {
  const row = F.chapterRowHTML(B.chapter);
  const note = F.firstSentences(B.chapter.data.dek, 150) || `The chapter · ${B.chapter.data.read_minutes} min · October 6`;
  assert.equal(row, `<a class="ck-rows__key" href="/journal/posts/week-08/">Week 5 · “Park's Blind Spot”</a><span>${note.replace(/'/g, "&#39;")}</span>`);
  assert.equal(F.chapterRowHTML({ state: "unavailable", absent_text: "The latest chapter is not served right now.", data: null }), '<p class="ck-soft">The latest chapter is not served right now.</p>');
  const slots = P.frontSlots(edition, B, BASE);
  assert.equal(slots["ck-chapter-row"], row);
  assert.equal(slots["ck-week-span"], `How the whole thing is going · ${WEEK_SPAN}`);
  for (const gone of ["ck-week", "ck-quotes", "ck-lead-read", "ck-sheet-line"]) assert.equal(slots[gone], undefined, `${gone} left the front page`);
  // The first screen's numbers are doors; a failed block prints its sentence with no door.
  assert.ok(slots["ck-record"].startsWith(`<a href="/next/v8/coaches/">${B.record.data.count_text}`));
  assert.ok(slots["ck-mark-caption"].startsWith(`<a href="/next/v8/trend/?m=weight"><b>${B.today.data.weight_lbs.toFixed(1)} lb</b>`));
  const gone = { state: "unavailable", absent_text: "Not served right now.", data: null };
  assert.equal(P.frontSlots(edition, { ...B, record: gone, today: gone }, BASE)["ck-record"], "Not served right now.");
  assert.equal(P.frontSlots(edition, { ...B, record: gone, today: gone }, BASE)["ck-mark-caption"], "Not served right now.");
});

test("the week page carries the band whole: the sorted week without a second kicker, the chapter lines and the silence sentence", () => {
  const slots = P.weekSlots(edition, B, BASE);
  assert.equal(slots["ck-week-label"], `This week · ${WEEK_SPAN}`);
  assert.doesNotMatch(slots["ck-week"], /ck-label">How the whole thing is going/, "the page's own heading says it");
  assert.match(slots["ck-week"], /Going well|Not yet/);
  assert.match(slots["ck-quotes"], /“Park's Blind Spot”, the chapter/);
  assert.equal(slots["ck-words"], null);
  assert.match(slots["ck-words-absent"], /Nothing new in his own words since/);
  const gone = { state: "unavailable", absent_text: "Not served right now.", data: null };
  const failed = P.weekSlots(edition, { ...B, week: gone, scorecard: gone, chapter: gone }, BASE);
  assert.equal(failed["ck-week"], '<p class="ck-soft">Not served right now.</p>');
  assert.equal(failed["ck-quotes"], '<p class="ck-soft">Not served right now.</p>');
});

test("nothing the round-8 builders emit carries an honorific, an ISO date or a leaked non-value", () => {
  const out = [F.argumentHTML(F.pickArgument(DAYS, NO_BET), BASE), F.lastHeardHTML(DAYS, [], BASE), F.chapterRowHTML(B.chapter), F.betLiveLine(B.next.data.bet, B.week), ...Object.values(P.weekSlots(edition, B, BASE)).filter(Boolean)].join("\n");
  assert.doesNotMatch(out, /\bDr\.\s/);
  assert.doesNotMatch(out, /\b20\d\d-\d\d-\d\d\b/);
  assert.doesNotMatch(out, /undefined|NaN|\[object Object\]/);
});
