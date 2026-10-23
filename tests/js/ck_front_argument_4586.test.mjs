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
// #4586 round 2: the 2026-10-17 recapture has no open bet. The bet card's tests read the bet the
// 2026-10-13 capture served (tests/fixtures/kit_pages_4586_pinned), injected only when the capture has none.
const PINNED = JSON.parse(readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "fixtures", "kit_pages_4586_pinned", "open_bet.json"), "utf8"));
const PINNED_DOCKET = JSON.parse(readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "fixtures", "kit_pages_4586_pinned", "coach_docket.json"), "utf8"));
const CAPTURE_HAS_BET = !!(B.next.data.bet && B.next.data.bet.data);
if (!CAPTURE_HAS_BET) B.next.data.bet = PINNED.bet;
const BASE = "/next/v8/";
const inWords = (iso) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { month: "long", day: "numeric", timeZone: "UTC" });
const esc0 = (t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
// The protein floor is the plan's, as the captured nutrition route serves it (#4540) — never a literal here.
const FLOOR = load(KIT, "nutrition_overview").nutrition.protein_floor_g;
const BETD = B.next.data.bet.data;
const [SA, SB] = BETD.sides;
const OTHER = (CAPTURE_HAS_BET ? load(KIT, "coach_docket") : PINNED_DOCKET).open.map((d) => d.resolution_date).filter((d) => d && d !== BETD.settle_date).sort()[0];
const MORE_BETS = `One more bet settles on ${inWords(OTHER)}.`;
const WEEK_SPAN = `${inWords(B.week.data.days[0])} to ${inWords(B.week.data.days.at(-1))}`;
// The edition's `next` block with its bet absent: what the page sees between bets.
const NO_BET = { ...B.next, data: { ...B.next.data, bet: { state: "absent", as_of: null, source: "/api/coach_docket", absent_text: "No coach bet is waiting to settle.", data: null } } };

test("the fixtures are the wire: five days, one absent, eight lines, three of them self-naming", () => {
  assert.equal(DAYS.length, 5);
  assert.deepEqual(DAYS.map((d) => d.state).sort(), ["absent", "ok", "ok", "ok", "ok"]);
  const lines = F.argumentLines(DAYS);
  assert.equal(lines.length, DAYS.reduce((n, d) => n + (d.lines || []).length, 0), "every served line of every day");
  // The self-naming lines are read from the captured lines: each names its own coach (first or last name, whole word),
  // and no line that does not is counted.
  const names = (l) => l.coach.split(" ").some((part) => new RegExp(`\\b${esc0(part)}\\b`).test(l.text));
  const selfNaming = lines.filter(F.namesSelf);
  assert.ok(selfNaming.length > 0 && selfNaming.every(names), "each self-naming line names its own coach");
  assert.ok(lines.filter((l) => !F.namesSelf(l)).every((l) => !l.text.includes(l.coach)), "a line that quotes its coach's full name is self-naming");
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
  // The measure follows the bet's question (a recapture may bring a bet about another measure): protein reads against the plan's floor.
  const WEEKDAY = "(Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day";
  const live = /protein/i.test(BETD.question)
    ? new RegExp(`^${WEEKDAY}: \\d+(\\.\\d)? g protein\\. This week, at or above ${FLOOR} g protein on \\d+ of \\d+ days recorded\\.$`)
    : new RegExp(`^${WEEKDAY}: .*\\d.*\\. This week, .+\\.$`);
  // Round 2: a deep- or REM-sleep share is not a measure the week carries — no line, rather than
  // the night's hours beside a bet about the share.
  if (/deep|REM|share/i.test(BETD.question)) assert.equal(line, "", line);
  else assert.match(line, live, line);
  // The first mention of a name carries the job, when the served lines pair the name with its id.
  const jobs = F.jobsByName(DAYS);
  // a name carries its job only when the served lines pair it with one (a recapture may bring a coach with none)
  const who = (c) => (jobs[c] ? `${c} (${jobs[c]})` : c);
  // #4809: each side carries the coach's reason — the opening position the docket row holds, one
  // clause in its served words (`next.bet.data.sides[].reason`) — on its own line under the question.
  const why = Object.fromEntries(pick.bet.data.sides.map((s) => [s.coach, s.reason]));
  assert.ok(why[SA.coach] && why[SB.coach], "the wire fixture serves both reasons");
  // Round 2: a job beside every side or none; a reason only when it reads in plain language.
  const both = !!(jobs[SA.coach] && jobs[SB.coach]);
  const side = (x) => `${both ? who(x.coach) : x.coach} says ${x.says}${F.plainLanguage(why[x.coach]) ? `: “${why[x.coach]}”` : ""}.`;
  assert.deepEqual(F.betSidesLines(pick.bet, jobs), [side(SA), side(SB)]);
  for (const l of F.betSidesLines(pick.bet, jobs)) {
    const q = /“(.*)”/.exec(l);
    if (q) assert.ok(F.plainLanguage(q[1]), `a quoted reason passes the plain-language rule: ${l}`);
  }
  const said = (x) => `${x.coach} says ${x.says}${F.plainLanguage(why[x.coach]) ? `: “${why[x.coach]}”` : ""}.`;
  assert.equal(F.betSidesLine(pick.bet), `${said(SA)} ${said(SB)}`);
  // a side with no served reason is the side alone; nothing is written in its place
  const bare = { ...pick.bet, data: { ...pick.bet.data, sides: pick.bet.data.sides.map((s) => ({ coach: s.coach, says: s.says })) } };
  assert.equal(F.betSidesLine(bare, jobs), `${both ? who(SA.coach) : SA.coach} says ${SA.says}. ${both ? who(SB.coach) : SB.coach} says ${SB.says}.`);
  // Ruling 2026-10-11 (the coaches page keeps four screens): the FRONT card prints each reason
  // under its side; the coaches page's card prints the sides alone, on one line, and its door
  // goes to the front card — the two doors never loop on a promise neither page keeps.
  const front = P.frontReadSlots(edition, B, BASE)["ck-bet"];
  assert.match(front, /<a class="ck-link" href="\/next\/v8\/coaches\/#ck-bet">Every open bet, on the coaches page<\/a>/, front);
  assert.doesNotMatch(front, /What each one argued/, "the front card prints the argument itself");
  const coaches = P.betHTML(B.next, { ...P.reasonsDoor(B.next, BASE), extra: MORE_BETS, oneLine: true });
  for (const [who, reason] of Object.entries(why)) {
    const esc = (t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    // Round 2: a reason in the statistician's jargon is not printed; the side stands alone.
    if (F.plainLanguage(reason)) assert.match(front, new RegExp(`<p class="ck-soft">${esc(who)}(?: \\([a-z ]+\\))? says (yes|no): “${esc(reason)}”\\.</p>`), front);
    else assert.match(front, new RegExp(`<p class="ck-soft">${esc(who)}(?: \\([a-z ]+\\))? says (yes|no)\\.</p>`), front);
    assert.ok(!coaches.includes(reason), `the coaches page does not print ${who}'s reason`);
  }
  // one paragraph (the four-screen budget): the sides, the door to the reasons, the extra sentence
  assert.match(coaches, new RegExp(`<p class="ck-soft">${esc0(`${SA.coach} says ${SA.says}. ${SB.coach} says ${SB.says}.`)} <a class="ck-link" href="\\/next\\/v8\\/#ck-bet">Why each says so\\.</a> ${esc0(MORE_BETS)}</p></div>$`), coaches);
  // no served reason: no door to a card that would not print one
  assert.deepEqual(P.reasonsDoor({ ...B.next, data: { ...B.next.data, bet: bare } }, BASE), {});
  assert.match(P.betHTML(B.next, { sidesText: "x says no.", extra: "Friday: 1 g.", href: "/next/v8/coaches/#ck-bet" }), /<p class="ck-soft">x says no\.<\/p><p class="ck-soft">Friday: 1 g\.<\/p><p><a class="ck-link" href="\/next\/v8\/coaches\/#ck-bet">What each one argued<\/a><\/p><\/div>$/);
  // the newest recorded day's value of the measure the question names (protein -> food; sleep -> sleep)
  const [measure, unit] = /protein/i.test(BETD.question) ? ["food", "g protein"] : ["sleep", "hours of sleep"];
  const vals = B.week.data.measures[measure].data.values;
  const lastIdx = vals.map((v, i) => (typeof v === "number" ? i : -1)).filter((i) => i >= 0).pop();
  // A deep-sleep-share bet has no live line (round 2); the rule is held on a sleep-time question.
  const timeBet = { ...pick.bet, data: { ...pick.bet.data, question: "Will the sleep time (7-day average) be 7 hours or more on Friday?" } };
  const subject = /deep|REM|share/i.test(BETD.question) ? F.betLiveLine(timeBet, B.week) : line;
  assert.ok(subject.includes(`: ${String(Number(vals[lastIdx].toFixed(1)))} ${unit}. `), subject);
  assert.equal(F.betLiveLine({ ...pick.bet, data: { ...pick.bet.data, question: "Will the moon be full on Monday?" } }, B.week), "", "a question naming no measure the week carries");
  assert.equal(F.betLiveLine(pick.bet, { state: "unavailable", absent_text: "x", data: null }), "");
});

// Round 3: the exchange is built only from lines the front page may quote (F.frontQuotable — one
// sentence, at most F.FRONT_MAX_WORDS words, no glossary term, no hedge chain, no mechanism noun,
// no other coach named unless replied to). The wire's own week of lines is long-form, so the
// rule is held on this test's own short lines, and the wire is held to "nothing unquotable leads".
const SHORT = [
  { state: "ok", date: "2026-10-07", lines: [{ coach_id: "nutrition_coach", coach: "Marcus Webb", move: "call", text: "Dinner protein will stay short of the target this week." }] },
  { state: "ok", date: "2026-10-08", lines: [{ coach_id: "labs_coach", coach: "James Okafor", move: "reply", replies_to: "Marcus Webb", text: "Marcus Webb is right that dinner is the weak meal." }] },
];
test("with no bet, the newest quotable reply and the line it answers are the latest exchange — never 'disagree'", () => {
  const pick = F.pickArgument(SHORT, NO_BET);
  assert.equal(pick.kind, "reply");
  assert.equal(pick.second.coach, "James Okafor");
  assert.equal(pick.first.coach, "Marcus Webb");
  assert.equal(F.argumentLabel(pick), "The latest exchange");
  assert.equal(F.argumentHeading(pick), "One coach answers another.");
  const html = F.argumentHTML(pick, BASE);
  assert.equal((html.match(/<li>/g) || []).length, 2);
  assert.match(html, /Marcus Webb<\/a> · Wednesday, October 7<\/span><span>“Dinner protein/);
  assert.match(html, /James Okafor<\/a> · answering Marcus Webb · Thursday, October 8<\/span>/);
  assert.match(html, /href="\/next\/v8\/coach\/\?c=labs_coach"/);
  assert.doesNotMatch(F.argumentHeading(pick), /disagree/i);
  assert.deepEqual(F.argumentTexts(pick), [pick.first.text, pick.second.text]);
  // The wire: whatever leads passes the rule, line by line.
  const wire = F.pickArgument(DAYS, NO_BET);
  for (const t of F.argumentTexts(wire)) assert.ok(F.plainLanguage(t), t);
});

test("a line about another coach's call is dropped; a long or hedged line never leads", () => {
  const other = [{ state: "ok", date: "2026-10-11", lines: [{ coach_id: "nutrition_coach", coach: "Marcus Webb", move: "reaction", text: "Lisa's protein prediction came true this week." }] }];
  assert.equal(F.lastHeardHTML(other, [], BASE), "", "the food coach on the sleep coach's call reads as the wrong owner");
  assert.equal(F.plainLanguage("Protein escalation held, yet deep sleep didn't improve, which means, for now, I can't claim it."), false);
  assert.equal(F.plainLanguage("Activation hasn't closed the dinner gap."), false, "a mechanism noun");
  assert.equal(F.plainLanguage("Dinner is short. Breakfast is fine."), false, "one sentence only");
  assert.equal(F.plainLanguage(Array(F.FRONT_MAX_WORDS + 1).fill("word").join(" ") + "."), false);
  assert.equal(F.plainLanguage("Recovery climbed all week."), false, "a glossary term (ck_terms.js) is kept off the front page");
  assert.equal(F.plainLanguage("Dinner is still the short meal."), true);
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
  assert.equal(F.argumentHeading(none), "No open bet between them this week.");
  assert.equal(F.pickArgument([], null), null);
  assert.equal(F.pickArgument([null, {}, { state: "absent", date: "2026-10-10", lines: [] }], { state: "unavailable", absent_text: "x", data: null }), null);
});

test("the Today band leaves out a line the argument already printed, and says nothing when every line was", () => {
  const block = { state: "ok", as_of: "2026-10-08", data: { lines: [{ coach: "James Okafor", domain: "labs", move: "reply", text: "A line the argument printed.", replies_to: "Marcus Webb" }, { coach: "Lisa Park", domain: "sleep", move: "call", text: "A call on his sleep." }] } };
  const html = F.coachTodayHTML(block, { skip: ["A line the argument printed."] });
  assert.equal((html.match(/<li>/g) || []).length, 1);
  assert.match(html, /Lisa Park · sleep/);
  assert.equal(F.coachTodayHTML(block, { skip: block.data.lines.map((l) => l.text) }), "");
  assert.equal(F.coachTodayHTML(block), F.coachTodayHTML(block, { skip: [] }));
  assert.match(F.coachTodayHTML({ state: "absent", absent_text: "No coach had anything to say on Saturday, October 10.", data: null }, { skip: ["x"] }), /No coach had anything to say on Saturday, October 10\./);
});

test("when no coach spoke today, the newest quotable line heard stands with its day and the coach's job — never one already printed", () => {
  const html = F.lastHeardHTML(SHORT, [], BASE);
  assert.equal((html.match(/<li>/g) || []).length, 1);
  assert.ok(html.includes(`“${SHORT[1].lines[0].text}”`), html);
  assert.match(html, /<\/a> \((food|mind|blood tests|sleep|statistics|training|blood sugar|lead)\) · /, "the job beside the name");
  assert.ok(F.lastHeardHTML(SHORT, [SHORT[1].lines[0].text], BASE).includes(SHORT[0].lines[0].text));
  assert.equal(F.lastHeardHTML([], [], BASE), "");
  // The wire's lines: whatever stands passes the rule.
  const wire = F.lastHeardHTML(DAYS, [], BASE);
  const q = /“([^”]*)”/.exec(wire);
  if (q) assert.ok(F.plainLanguage(q[1]), q[1]);
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
  // Site-to-A round 1 (front:F6): the note is the chapter's own date and length, never the dek's claims.
  const note = `The latest chapter · October 13 · ${B.chapter.data.read_minutes} min`;
  assert.equal(row, `<a class="ck-rows__key" href="/journal/posts/week-09/">Week 6 · “The Quiet Accumulation”</a><span>${note.replace(/'/g, "&#39;")}</span>`);
  assert.equal(F.chapterRowHTML({ state: "unavailable", absent_text: "The latest chapter is not served right now.", data: null }), '<p class="ck-soft">The latest chapter is not served right now.</p>');
  const slots = P.frontSlots(edition, B, BASE);
  assert.equal(slots["ck-chapter-row"], row);
  assert.equal(slots["ck-week-span"], `How the whole thing is going · ${WEEK_SPAN}`);
  for (const gone of ["ck-week", "ck-quotes", "ck-lead-read", "ck-sheet-line"]) assert.equal(slots[gone], undefined, `${gone} left the front page`);
  // The first screen's numbers are doors; a failed block prints its sentence with no door.
  // Site-to-A round 1 (front:F5, item 3): the door is on the count alone; the comparison is one sayable sentence.
  assert.ok(slots["ck-record"].startsWith(`<a class="ck-link" href="/next/v8/coaches/">${B.record.data.count_text}</a> The coaches do not beat a simple guess yet.`));
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
  assert.match(slots["ck-quotes"], /“The Quiet Accumulation”, the chapter/);
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

// Red team 2026-10-17: the front page quoted the mind coach diagnosing him ("until he names what he's
// actually avoiding"). The rule (F.frontQuotable) is read off served fields: a move about the record
// (call / reply / reaction / bet — not a question), and never the mind coach.
test("the front page never quotes the mind coach or a question, on any of its three quote paths", () => {
  const mind = { coach: "Nathan Reeves", coach_id: "mind_coach", domain: "mind", move: "call", text: "Until he names what he is avoiding." };
  const ask = { coach: "James Okafor", coach_id: "labs_coach", move: "question", text: "When is the lab draw?" };
  const data = { coach: "Max Reyes", coach_id: "physical_coach", move: "reaction", text: "The scale moved." };
  assert.equal(F.frontQuotable(mind), false);
  assert.equal(F.frontQuotable({ ...mind, coach_id: undefined }), false, "the day's lines carry the domain only");
  assert.equal(F.frontQuotable(ask), false);
  assert.equal(F.frontQuotable({ ...data, move: undefined }), false, "a line with no served move is not quoted");
  assert.equal(F.frontQuotable(data), true);
  const today = { state: "ok", as_of: "2026-10-17", data: { lines: [mind, ask] } };
  assert.equal(F.coachTodayHTML(today), "", "nothing quotable today: the caller falls back to the last line heard");
  const days = [{ state: "ok", date: "2026-10-17", lines: [mind, ask] }, { state: "ok", date: "2026-10-16", lines: [data] }];
  assert.match(F.lastHeardHTML(days, [], BASE), /The scale moved\./);
  assert.doesNotMatch(F.lastHeardHTML(days, [], BASE), /avoiding|lab draw/);
  const reply = { coach: "Nathan Reeves", coach_id: "mind_coach", domain: "mind", move: "reply", replies_to: "Max Reyes", text: "Max is wrong." };
  assert.equal(F.pickArgument([{ state: "ok", date: "2026-10-17", lines: [reply] }, ...days.slice(1)], null), null, "a mind-coach reply never leads the argument");
});
