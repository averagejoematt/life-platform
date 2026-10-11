// tests/js/ck_front_argument_4586.test.mjs — round 8 of the preview front page (#4586):
// the page leads with the coaches' open argument and the clearest miss, and the week band
// is its own page.
//
// Driven from live captures of GET /api/coach_moves?date=<day> for 2026-10-05 → 10-09
// (tests/fixtures/front_argument_4586/, the wire minus _meta). What is held: the argument is
// the newest reply and the line it answers; a line in which a coach names herself is never
// chosen; with no reply the open bet's sides stand; lines already in the argument leave the
// Today band; the deeper rows and the week page print a sentence for a failed block.
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

test("the argument is the newest reply and the line it answers, dated, in the served words", () => {
  const pick = F.pickArgument(DAYS, B.next);
  assert.equal(pick.kind, "reply");
  assert.equal(pick.second.coach, "James Okafor");
  assert.equal(pick.second.date, "2026-10-08");
  assert.equal(pick.second.replies_to, "Marcus Webb");
  assert.equal(pick.first.coach, "Marcus Webb");
  assert.equal(pick.first.date, "2026-10-07");
  const html = F.argumentHTML(pick, BASE);
  assert.equal((html.match(/<li>/g) || []).length, 2);
  assert.match(html, /Marcus Webb<\/a> · Wednesday, October 7<\/span><span>“James Okafor's protein hold deserves scrutiny/);
  assert.match(html, /James Okafor<\/a> · answering Marcus Webb · Thursday, October 8<\/span>/);
  assert.match(html, /href="\/next\/v8\/coach\/\?c=labs_coach"/);
  assert.doesNotMatch(html, /\b20\d\d-\d\d-\d\d\b/);
  assert.equal(F.argumentLabel(pick), "The open argument");
  assert.equal(F.argumentHeading(pick), "Two coaches disagree.");
  assert.deepEqual(F.argumentTexts(pick), [pick.first.text, pick.second.text]);
});

test("a self-naming line is never the argument, even when it is the newest reply's target", () => {
  const days = [
    { state: "ok", date: "2026-10-02", lines: [{ coach_id: "sleep_coach", coach: "Lisa Park", move: "call", text: "Lisa expects a rest day." }] },
    { state: "ok", date: "2026-10-03", lines: [{ coach_id: "physical_coach", coach: "Max Reyes", move: "reply", replies_to: "Lisa Park", text: "I disagree with Lisa Park: keep the streak." }] },
  ];
  const pick = F.pickArgument(days, B.next);
  assert.equal(pick.kind, "reply");
  assert.equal(pick.first, null, "the answered line names its own speaker and is left out");
  assert.equal(F.argumentHeading(pick), "One coach answers another.");
  assert.match(F.argumentHTML(pick, BASE), /answering Lisa Park/);
  // The reply itself naming its speaker: nothing qualifies, so the bet's sides stand.
  const self = [{ state: "ok", date: "2026-10-03", lines: [{ coach: "Max Reyes", move: "reply", replies_to: "Lisa Park", text: "Max Reyes disagrees." }] }];
  assert.equal(F.pickArgument(self, B.next).kind, "bet");
});

test("with no reply in the window, the open bet's two sides stand with their newest lines; with no bet either, nothing is called an argument", () => {
  const noReplies = DAYS.map((d) => ({ ...d, lines: (d.lines || []).filter((l) => l.move !== "reply") }));
  const pick = F.pickArgument(noReplies, B.next);
  assert.equal(pick.kind, "bet");
  assert.deepEqual(B.next.data.bet.data.sides.map((s) => s.coach), ["Nathan Reeves", "Marcus Webb"]);
  assert.deepEqual(pick.lines.map((l) => `${l.coach} ${l.date}`), ["Nathan Reeves 2026-10-08"], "Marcus's only remaining lines name himself or are replies");
  assert.equal(F.argumentLabel(pick), "The open bet");
  assert.match(F.argumentHTML(pick, BASE), /Nathan Reeves<\/a> · Thursday, October 8/);
  const none = F.pickArgument(noReplies, { state: "unavailable", absent_text: "What comes next is not served right now.", data: null });
  assert.equal(none, null);
  assert.equal(F.argumentHTML(none, BASE), "");
  assert.equal(F.argumentLabel(none), "The coaches");
  assert.equal(F.pickArgument([], null), null);
  assert.equal(F.pickArgument([null, {}, { state: "absent", date: "2026-10-10", lines: [] }], null), null);
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

test("the argument reads the edition's day and the six before it", () => {
  assert.deepEqual(P.argumentDays("2026-10-09"), ["2026-10-09", "2026-10-08", "2026-10-07", "2026-10-06", "2026-10-05", "2026-10-04", "2026-10-03"]);
  assert.deepEqual(P.argumentDays(""), []);
  assert.equal(P.argumentDays("2026-03-01")[1], "2026-02-28");
});

test("the front page's miss leads with the clearest wrong call, and says which kind it found", () => {
  const calls = load(KIT, "calls");
  const pick = C.lastCallPick(calls);
  assert.equal(pick.kind, "wrong");
  assert.equal(pick.call.kind !== "bet" ? pick.call.status || "refuted" : "refuted", "refuted");
  assert.match(C.lastCallHTML(calls, BASE), new RegExp(`call/\\?id=${pick.call.id}`));
  assert.deepEqual(C.lastCallPick({ state: "ok", calls: [] }), { call: null, kind: "" });
  assert.deepEqual(C.lastCallPick(null), { call: null, kind: "" });
});

test("the deeper rows: the chapter is one door with its week and read time; a failed block is its sentence", () => {
  const row = F.chapterRowHTML(B.chapter);
  assert.match(row, /^<a href="\/journal\/posts\/week-08\/">Week 5 · “Park's Blind Spot” <span>The chapter · 6 min · October 6<\/span><\/a>$/);
  assert.equal(F.chapterRowHTML({ state: "unavailable", absent_text: "The latest chapter is not served right now.", data: null }), '<p class="ck-soft">The latest chapter is not served right now.</p>');
  const slots = P.frontSlots(edition, B, BASE);
  assert.equal(slots["ck-chapter-row"], row);
  assert.equal(slots["ck-week-span"], "How the whole thing is going · October 3 to October 9");
  for (const gone of ["ck-week", "ck-quotes", "ck-lead-read", "ck-sheet-line"]) assert.equal(slots[gone], undefined, `${gone} left the front page`);
});

test("the week page carries the band whole: the sorted week, the chapter lines and the silence sentence", () => {
  const slots = P.weekSlots(edition, B, BASE);
  assert.equal(slots["ck-week-label"], "This week · October 3 to October 9");
  assert.match(slots["ck-week"], /How the whole thing is going|Going well/);
  assert.match(slots["ck-quotes"], /“Park's Blind Spot”, the chapter/);
  assert.equal(slots["ck-words"], null);
  assert.match(slots["ck-words-absent"], /Nothing new in his own words since/);
  const gone = { state: "unavailable", absent_text: "Not served right now.", data: null };
  const failed = P.weekSlots(edition, { ...B, week: gone, scorecard: gone, chapter: gone }, BASE);
  assert.equal(failed["ck-week"], '<p class="ck-soft">Not served right now.</p>');
  assert.equal(failed["ck-quotes"], '<p class="ck-soft">Not served right now.</p>');
});

test("nothing the round-8 builders emit carries an honorific, an ISO date or a first-person line of the page's own", () => {
  const pick = F.pickArgument(DAYS, B.next);
  const out = [F.argumentHTML(pick, BASE), F.chapterRowHTML(B.chapter), ...Object.values(P.weekSlots(edition, B, BASE)).filter(Boolean)].join("\n");
  assert.doesNotMatch(out, /\bDr\.\s/);
  assert.doesNotMatch(out, /\b20\d\d-\d\d-\d\d\b/);
  assert.doesNotMatch(out, /undefined|NaN|\[object Object\]/);
});
