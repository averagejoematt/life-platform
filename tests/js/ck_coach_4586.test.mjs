// tests/js/ck_coach_4586.test.mjs — #4586: one page per AI coach on the preview. Driven
// from the committed live captures in tests/fixtures/kit_pages_4586/ (the coach's own
// route, the docket and the pending calls, captured 2026-10-04 and trimmed to the fields
// the page reads); no builder reads the wall clock — "today" is passed in.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const C = await import("../../site/assets/js/ck_coach.js");
const FIX = join(dirname(fileURLToPath(import.meta.url)), "..", "fixtures", "kit_pages_4586");
const load = (name) => JSON.parse(readFileSync(join(FIX, `${name}.json`), "utf8"));
const [SLEEP, PHYSICAL, GLUCOSE, LEAD, MIND] = ["sleep_coach", "physical_coach", "glucose_coach", "eli_marsh", "mind_coach"].map((id) => load(`coach_${id}`));
const DOCKET = load("coach_docket_full");
const ROSTER = load("coaches");
const NAMES = C.rosterNames(ROSTER);
const CALLS = { sleep: load("predictions_sleep"), physical: load("predictions_physical"), glucose: load("predictions_glucose") };
const TODAY = "2026-10-04";
const ALL = [SLEEP, PHYSICAL, GLUCOSE, LEAD, MIND];
const text = (html) => html.replace(/<[^>]*>/g, " ");

test("a coach's name links to its page, and anything that is not a persona id goes to Coaches", () => {
  assert.equal(C.coachHref("sleep_coach", "/next/v8/"), "/next/v8/coach/?c=sleep_coach");
  assert.equal(C.coachHref("sleep_coach"), "/next/v8/coach/?c=sleep_coach");
  for (const hostile of ["", null, "../admin", "sleep coach", "Sleep_Coach", "a/b", "x".repeat(60), "constructor()"]) {
    assert.equal(C.coachHref(hostile, "/next/v8/"), "/next/v8/coaches/", String(hostile));
    assert.equal(C.isCoachId(hostile), false, String(hostile));
  }
});

test("Back returns to the on-site page the reader came from, otherwise to Coaches", () => {
  const here = "https://averagejoematt.com/next/v8/coach/?c=sleep_coach";
  assert.deepEqual(C.backTarget("https://averagejoematt.com/next/v8/?x=1", here, "/next/v8/"), { href: "/next/v8/?x=1", text: "← Back" });
  const coaches = { href: "/next/v8/coaches/", text: "← The AI coaches" };
  assert.deepEqual(C.backTarget("", here, "/next/v8/"), coaches, "no referrer");
  assert.deepEqual(C.backTarget("https://evil.example/next/v8/", here, "/next/v8/"), coaches, "another site");
  assert.deepEqual(C.backTarget(here, here, "/next/v8/"), coaches, "a reload of this page");
});

test("the top says what the coach is for, that it is software, and how it is written", () => {
  const html = C.whoHTML(SLEEP);
  assert.match(html, /Reads Matthew’s sleep, and the score out of 100 his wrist strap gives each morning\./);
  assert.match(html, /Software Matthew built with Claude\. Not a person, and not a clinician\./);
  assert.ok(html.includes(SLEEP.trait_scores.note), "the served one-line disposition, verbatim");
  assert.match(html, /How the character is written, by its author\./);
  assert.match(C.whoHTML(GLUCOSE), /<b>Sitting out: no sensor since August 27\.<\/b>/);
  assert.doesNotMatch(C.whoHTML(SLEEP), /Sitting out/);
});

test("watching now is the coach's own served list, with whose words they are and their date", () => {
  const html = C.watchingHTML(SLEEP);
  assert.match(html, /In the coach’s own words, written October 4\./);
  for (const item of SLEEP.stance.focused_on_now) assert.ok(text(html).includes(item), item);
  assert.match(html, /<details><summary>Two more<\/summary>/, "three on the page, the rest one tap away");
  assert.match(html, /<summary>What it has set aside for now<\/summary>/);
  assert.match(html, /The latest thing it asked of Matthew, October 3: “I've asked him to resume morning logging[^”]*”\s*Due October 10\./);
  assert.doesNotMatch(html, /How its read changed/, "an empty served field prints nothing");
});

test("a watch list that belongs to the stage says it is the author's and is not this week's", () => {
  const html = C.watchingHTML(PHYSICAL);
  assert.match(html, /Set by the author for the stage Matthew is in\. Not written this week\./);
  assert.match(html, /Weight trending down at all\./);
  assert.doesNotMatch(html, /In the coach’s own words/);
});

test("a coach that changed its read shows the change, in its words, one tap away", () => {
  const html = C.watchingHTML(MIND);
  assert.match(html, /<details><summary>How its read changed<\/summary><p class="ck-soft">“My previous stance held/);
});

test("a benched coach, the lead and a missing profile each get a plain sentence, never a blank", () => {
  assert.match(C.watchingHTML(GLUCOSE), /Amara Patel is sitting out \(no sensor since August 27\), so there is nothing for it to watch/);
  assert.match(C.watchingHTML(LEAD), /The lead keeps no watch list of its own/);
  assert.match(C.watchingHTML(null), /not served right now/);
  assert.match(C.longerHTML(GLUCOSE), /Nothing further out is served while Amara Patel is sitting out\./);
  for (const build of [C.watchingHTML, C.longerHTML, C.recordHTML, C.personaHTML]) assert.ok(build(null).length > 20, build.name);
});

test("next names the first date something settles, counts the open calls and lists the soonest", () => {
  const html = C.nextHTML(SLEEP, DOCKET, CALLS.sleep, NAMES, TODAY);
  assert.match(html, /<b>Monday, October 5:<\/b> a bet against Max Reyes settles, and a call comes due to be checked\./);
  assert.match(html, /21 calls are waiting to be checked, each by the date beside it\./);
  assert.equal((html.match(/<time /g) || []).length, 2, "the two soonest calls");
  assert.match(html, /<time datetime="2026-10-05">Oct 5<\/time>/);
  assert.match(html, /on September 20 based on current model/, "an ISO date inside a served sentence is put into words");
  assert.doesNotMatch(text(html), /\b20\d\d-\d\d-\d\d\b/);
  assert.match(html, /Three open bets against another coach: they are under Disagreements, below\./);
});

test("calls past their date are counted as late and never listed as upcoming", () => {
  const later = C.nextHTML(SLEEP, DOCKET, CALLS.sleep, NAMES, "2026-10-08");
  assert.match(later, /21 calls are waiting to be checked, each by the date beside it\. Three are past their date and not checked yet\./);
  assert.match(later, /<b>Thursday, October 8:<\/b> a call comes due to be checked\./);
  // A due date years out carries its year, so it cannot be read as this year's.
  const far = C.nextHTML(SLEEP, { open: [], resolved: [] }, CALLS.sleep, NAMES, "2027-01-01");
  assert.match(far, /<time datetime="2029-07-01">Jul 1, 2029<\/time>/);
});

test("next says so when the calls or the bets are not served, and the lead has nothing to settle", () => {
  assert.match(C.nextHTML(SLEEP, DOCKET, null, NAMES, TODAY), /This coach’s open calls are not served right now\./);
  assert.match(C.nextHTML(SLEEP, null, CALLS.sleep, NAMES, TODAY), /The bets between coaches are not served right now\./);
  assert.match(C.nextHTML(LEAD, DOCKET, { predictions: [] }, NAMES, TODAY), /The lead makes no dated calls of its own and has no bet open/);
  assert.match(C.nextHTML(SLEEP, DOCKET, { predictions: [] }, NAMES, TODAY), /Lisa Park has no call waiting to be checked\./);
  assert.deepEqual(C.pendingCalls(CALLS.physical, "sleep_coach"), [], "another coach's calls are never this coach's");
});

test("the longer view is the served ladder of stages, the current one marked; without one, a plain sentence", () => {
  const html = C.longerHTML(PHYSICAL);
  assert.match(html, /The stages this coach works through, set by the author\./);
  assert.equal((html.match(/<li>/g) || []).length, PHYSICAL.stance.ladder.length);
  assert.match(html, /<b>Move the scale and protect the engine\.<\/b> Now\./);
  assert.equal((html.match(/ Now\./g) || []).length, 1);
  assert.match(html, /What moves it on: A steady downward weight trend over a month/);
  assert.match(html, /The plan for this stage: Prioritize sustainable weight loss/);
  assert.match(C.longerHTML(SLEEP), /^<p class="ck-soft">No longer view is served for Lisa Park: nothing on record looks further ahead than the dated calls above\.<\/p>$/);
  assert.match(C.longerHTML(LEAD), /No longer view is served for Eli Marsh/);
});

test("the record is a count beside the comparison, never a percentage and never alone", () => {
  const html = C.recordHTML(SLEEP);
  assert.match(html, /<p class="ck-big">10<span>of 24 checked calls<\/span><\/p>/);
  assert.match(html, /Across 24 checked calls, so far they do not beat a simple guess\./);
  assert.match(html, /Through October 4\./);
  for (const p of ALL) assert.doesNotMatch(text(C.recordHTML(p)), /%|ck-meter|ck-track/, p.name);
  // Mutation control: the same record with its comparison gone draws no count at all.
  const bare = structuredClone(SLEEP);
  bare.report_card.track_record.comparison = null;
  assert.doesNotMatch(C.recordHTML(bare), /ck-big|10/);
  assert.match(C.recordHTML(bare), /What a simple guess would have scored on these calls is not available right now\./);
  assert.match(C.recordHTML(LEAD), /The lead makes no checked calls, so it has no record of its own\./);
});

test("the newest right call and the newest wrong call are shown in reader words", () => {
  const { right, wrong } = C.verdictPair(SLEEP);
  assert.match(right.text, /^For Saturday, September 26, Park said .* would land near 7\.8, give or take 1\.2 — it came in at 8\.6\.$/);
  assert.equal(right.checked, "Checked Friday, October 2.");
  assert.match(wrong.text, /Park said the share of deep sleep would go up over the checked window — it went down\./);
  assert.equal(wrong.checked, "Checked Sunday, October 4.");
  const html = C.verdictsHTML(SLEEP);
  assert.match(html, /ck-verdicts__tag--right">Right</);
  assert.doesNotMatch(text(html), /slope|trend=|_pct|\b20\d\d-\d\d-\d\d\b/, "the grader's working never reaches the page");
  assert.equal(C.verdictsHTML(LEAD), "", "no checked call: the mount prints the absence sentence");
});

test("an open bet is a dated yes-or-no question with each coach's side, by name", () => {
  const html = C.disagreementsHTML(SLEEP, DOCKET, NAMES);
  assert.equal((html.match(/class="ck-bet"/g) || []).length, 3);
  assert.match(html, /Against Max Reyes · settles Monday, October 5<\/p><p><b>Will the seven-night average recovery be 81\.6 or better on Monday, October 5\?<\/b>/);
  assert.match(html, /Lisa Park says yes\. Max Reyes says no\./);
  assert.match(html, /Lisa Park says no\. Max Reyes says yes\./, "the deep-sleep bet, where the sides are the other way round");
  assert.match(html, /<details><summary>What each one argued<\/summary><p class="ck-soft"><b>Lisa Park:<\/b> “/);
  assert.match(html, /No bet of this coach’s has settled yet\./);
  assert.doesNotMatch(text(html), /_coach|brier|recovery_score/i, "no machine name");
});

test("a settled bet says who was right, who was wrong and the result — the loser's page too", () => {
  const html = C.disagreementsHTML(GLUCOSE, DOCKET, NAMES);
  assert.match(html, /Bets settled so far: none won, one lost\./);
  assert.match(html, /Against Marcus Webb · settled September 30/);
  assert.match(html, /The question was: Will the night’s recovery be under 70 on Wednesday, September 30\?/);
  assert.match(html, /Marcus Webb was right\. Amara Patel was wrong\. The result was 59\./);
  assert.match(C.disagreementsHTML(LEAD, DOCKET, NAMES), /Eli Marsh has no bet against another coach, open or settled\./);
  assert.match(C.disagreementsHTML(SLEEP, null, NAMES), /not served right now/);
});

test("the character notes are the served ones, marked as the author's design", () => {
  const html = C.personaHTML(SLEEP);
  assert.match(html, /Written by the author as character design\. Not generated day to day, and not a measurement\./);
  assert.ok(html.includes(`“${SLEEP.character.principles[0]}”`));
  assert.match(html, /<summary>Two more of its rules<\/summary>/);
  assert.match(html, /The arc it was given: from establishing baseline to/);
  assert.ok(C.personaHTML(LEAD).includes(`“${LEAD.philosophy}”`), "the lead's served philosophy");
});

test("a term is glossed only when it appears on the page", () => {
  const html = C.termsHTML("<p>Recovery score and the EWMA of HRV</p>");
  assert.match(html, /<summary>Recovery, HRV and Running average<\/summary>/);
  assert.match(html, /His wrist strap’s morning score out of 100\./);
  assert.doesNotMatch(html, /DEXA|Zone 2/);
  assert.equal(C.termsHTML("<p>Nothing technical here.</p>"), "");
});

test("when the coach's own route is not served, the roster still names it and carries its record", () => {
  const view = C.coachView("sleep_coach", null, ROSTER);
  assert.equal(view.name, "Lisa Park");
  assert.equal(view.partial, true);
  assert.match(C.watchingHTML(view), /not served right now/);
  assert.match(C.recordHTML(view), /What a simple guess would have scored/, "this roster capture carries no comparison, so no count is drawn");
  assert.equal(C.coachView("nope_coach", null, ROSTER), null);
  assert.equal(C.coachView("sleep_coach", {}, null), null);
  assert.equal(C.coachView("sleep_coach", SLEEP, null), SLEEP);
});

test("standing rules: no honorific, no leaked non-value, no count of earlier starts, on any coach", () => {
  for (const p of ALL) {
    const calls = CALLS[p.persona_id.replace(/_coach$/, "")] || { predictions: [] };
    const page = [C.whoHTML(p), C.watchingHTML(p), C.nextHTML(p, DOCKET, calls, NAMES, TODAY), C.longerHTML(p), C.recordHTML(p), C.verdictsHTML(p), C.disagreementsHTML(p, DOCKET, NAMES), C.personaHTML(p)].join(" ");
    const plain = text(page);
    assert.doesNotMatch(plain, /\bDr\.\s/, p.name);
    assert.doesNotMatch(plain, /\bundefined\b|\bNaN\b|\[object Object\]|\bnull\b/, p.name);
    assert.doesNotMatch(plain, /\b20\d\d-\d\d-\d\d\b/, p.name);
    assert.doesNotMatch(plain, /\b(cycle|attempt)s?\b|\bresets?\b|earlier starts?|\d+(st|nd|rd|th) start/i, p.name);
  }
});
