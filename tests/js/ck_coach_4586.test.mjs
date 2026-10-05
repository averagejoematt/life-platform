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
// #4649: the route withholds a watch item a general reader cannot read, and on the capture
// day that was every item Lisa Park and Nathan Reeves had written (so `focused_on_now` is
// [] in both captures). OWN is the same capture carrying a list of the kind the writer
// stores under the new rule: short, plain, the coach's own. The items are this test's.
const OWN_LIST = ["Whether more protein helps his deep sleep", "Whether easy cardio shows up in his training log", "Whether he notes how he slept each morning"];
const OWN = { ...structuredClone(SLEEP), stance: { ...structuredClone(SLEEP.stance), focused_on_now: OWN_LIST } };
const ALL = [SLEEP, PHYSICAL, GLUCOSE, LEAD, MIND, OWN];
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
  assert.match(html, /How the author wrote this character\./);
  assert.match(C.whoHTML(GLUCOSE), /<b>Sitting out: no sensor since August 27\.<\/b>/);
  assert.doesNotMatch(C.whoHTML(SLEEP), /Sitting out/);
});

test("watching now shows ONE item in the coach's own words with its date; the rest is one tap away", () => {
  const html = C.watchingHTML(OWN);
  assert.match(html, /In Lisa Park’s own words, written October 4\./);
  const [onPage, behind] = [html.split("<details>")[0], html.slice(html.indexOf("<details>"))];
  assert.ok(onPage.includes(`“${OWN_LIST[0]}.”`), "the first item, verbatim, in quotation marks");
  for (const item of OWN_LIST.slice(1)) {
    assert.ok(!text(onPage).includes(item), `not on the page: ${item}`);
    assert.ok(text(behind).includes(item), `one tap away: ${item}`);
  }
  assert.match(html, /<details><summary>Two more on the list<\/summary>/);
  assert.match(html, /<summary>What Lisa Park has set aside for now<\/summary>/);
  assert.ok(text(html).includes(SLEEP.stance.set_aside_for_now[0]), "with a list of its own, what is set aside is the coach's too");
  assert.match(html, /The latest thing Lisa Park asked of Matthew, October 3: “I've asked him to resume morning logging[^”]*”\s*Due October 10\./);
  assert.doesNotMatch(html, /read changed/, "an empty field prints nothing");
  assert.doesNotMatch(html, /Set by the author/);
});

test("a watch item that uses a known term gets the plain line directly under it, not behind a tap", () => {
  const onPage = C.watchingHTML(OWN).split("<details>")[0];
  assert.match(onPage, /helps his deep sleep\.”<\/p><p class="ck-soft">Deep sleep: also called slow-wave sleep: the share of the night spent in the deepest stage\.<\/p>/);
  assert.deepEqual(C.glossLines("Recovery and HRV"), ["Recovery: his wrist strap’s morning score out of 100.", "HRV: heart-rate variability: how much the gap between heartbeats changes overnight, as the wrist strap measures it."]);
  assert.deepEqual(C.glossLines(OWN_LIST[2]), [], "no known term, no line");
});

test("a coach whose own items were all withheld shows the stage's list as the author's, never as the coach's (#4649)", () => {
  // The capture: a stance dated October 4 with focused_on_now [] and the ladder beside it.
  assert.deepEqual(SLEEP.stance.focused_on_now, []);
  assert.equal(SLEEP.stance.source, "stance");
  const html = C.watchingHTML(SLEEP);
  assert.match(html, /Set by the author for the stage Matthew is in\. Not written this week\./);
  assert.doesNotMatch(html, /own words/);
  assert.match(html, /“Time in bed most nights\.”/);
  assert.match(html, /<details><summary>One more on the list<\/summary>/);
  // What is set aside comes from the same place as the list above it: the stage, not the stance.
  const aside = html.slice(html.indexOf("has set aside for now"));
  assert.ok(text(aside).includes("Perfect sleep scores"));
  assert.ok(!text(html).includes(SLEEP.stance.set_aside_for_now[0]));
  // No words of the coach's are composed: every watch line on the page is a served stage item.
  for (const quoted of html.split("</details>")[0].match(/“[^”]*”/g) || []) {
    assert.ok(SLEEP.stance.rung.cares_most.some((t) => quoted.toLowerCase().includes(t.toLowerCase())), quoted);
  }
  // No stance list and no stage list: the plain sentence, and nothing else.
  const bare = structuredClone(SLEEP);
  bare.stance.rung.cares_most = [];
  bare.dossier = null;
  assert.equal(C.watchingHTML(bare), '<p class="ck-soft">Lisa Park has no watch list on record right now.</p>');
});

test("a watch list that belongs to the stage says it is the author's and is not this week's", () => {
  const html = C.watchingHTML(PHYSICAL);
  assert.match(html, /Set by the author for the stage Matthew is in\. Not written this week\./);
  assert.match(html, /“Weight trending down at all\.”/);
  assert.doesNotMatch(html, /own words/);
});

test("a coach that changed its read shows the change, in its words, one tap away", () => {
  const html = C.watchingHTML(MIND);
  assert.match(html, /<details><summary>How Nathan Reeves’s read changed<\/summary><p class="ck-soft">“My previous stance held/);
});

test("a benched coach, the lead and a missing profile each get a plain sentence, never a blank", () => {
  assert.match(C.watchingHTML(GLUCOSE), /Amara Patel is sitting out \(no sensor since August 27\) and has nothing to watch until the readings come back\./);
  assert.match(C.watchingHTML(LEAD), /Eli Marsh is the lead and keeps no watch list: the lead reads what the other coaches report\./);
  assert.match(C.watchingHTML(null), /not available right now/);
  assert.match(C.longerHTML(GLUCOSE), /Amara Patel has no longer view on record while sitting out\./);
  for (const build of [C.watchingHTML, C.longerHTML, C.recordHTML, C.personaHTML]) assert.ok(build(null).length > 20, build.name);
});

test("next names the first date something settles, gives the whole count and lists the two soonest real calls", () => {
  const html = C.nextHTML(SLEEP, DOCKET, CALLS.sleep, NAMES, TODAY);
  assert.match(html, /<b>Monday, October 5:<\/b> a bet against Max Reyes settles\./);
  assert.match(html, /21 calls are waiting to be checked\./, "the whole count is never hidden");
  assert.equal((html.match(/<time /g) || []).length, 2, "the two soonest calls");
  assert.match(html, /<time datetime="2026-10-06">Oct 6<\/time>/);
  assert.match(html, /Ten older calls are still waiting to be checked\./);
  assert.doesNotMatch(text(html), /\b20\d\d-\d\d-\d\d\b/);
  assert.match(html, /Three open bets against another coach: the next section has them\./);
});

test("a call about a day before it was said, a 'tomorrow' long gone and a due date in another year are counted, not listed", () => {
  const html = C.nextHTML(SLEEP, DOCKET, CALLS.sleep, NAMES, TODAY);
  // The live capture's own specimen: said September 21 about September 20, due October 5.
  const past = CALLS.sleep.predictions.find((c) => /on 2026-09-20 based on current model/.test(c.text));
  assert.equal(past.date, "2026-09-21");
  assert.equal(C.statedDay(past), "2026-09-20");
  assert.equal(C.isUpcoming(past, TODAY), false);
  assert.doesNotMatch(html, /90\.9%/);
  assert.doesNotMatch(html, /tomorrow/i, "no weeks-old 'tomorrow' is listed as coming up");
  const upcoming = CALLS.sleep.predictions.filter((c) => C.isUpcoming(c, TODAY));
  assert.equal(upcoming.length, 11);
  for (const c of upcoming) assert.equal(c.due_date.slice(0, 4), "2026", c.text);
  assert.ok(CALLS.sleep.predictions.some((c) => c.due_date > "2027"), "the capture does carry due dates years out");
  // The rule, on its own terms.
  const call = (o) => ({ status: "pending", text: "x", date: "2026-10-03", due_date: "2026-10-17", ...o });
  assert.equal(C.isUpcoming(call({}), TODAY), true, "names no day: listed");
  assert.equal(C.isUpcoming(call({ text: "Recovery tomorrow will be 80", date: "2026-10-04" }), TODAY), true, "tomorrow really is ahead");
  assert.equal(C.isUpcoming(call({ text: "Recovery tomorrow will be 80", date: "2026-09-25" }), TODAY), false);
  assert.equal(C.isUpcoming(call({ due_date: "2032-04-13" }), TODAY), false);
  assert.equal(C.isUpcoming(call({ due_date: "2026-10-01" }), TODAY), false, "past its date");
  // Mutation control: with nothing left to list, the count and the older-calls sentence still print.
  const later = C.nextHTML(SLEEP, { open: [], resolved: [] }, CALLS.sleep, NAMES, "2027-01-01");
  assert.doesNotMatch(later, /<time /);
  assert.match(later, /21 calls are waiting to be checked\./);
  assert.match(later, /21 older calls are still waiting to be checked\./);
});

test("next says so when the calls or the bets are not served, and the lead has nothing to settle", () => {
  assert.match(C.nextHTML(SLEEP, DOCKET, null, NAMES, TODAY), /Lisa Park’s open calls are not available right now\./);
  assert.match(C.nextHTML(SLEEP, null, CALLS.sleep, NAMES, TODAY), /The bets between coaches are not available right now\./);
  assert.match(C.nextHTML(LEAD, DOCKET, { predictions: [] }, NAMES, TODAY), /Eli Marsh is the lead\. The lead makes no dated calls and has no bet open, so nothing is waiting to settle\./);
  assert.match(C.nextHTML(SLEEP, DOCKET, { predictions: [] }, NAMES, TODAY), /Lisa Park has no call waiting to be checked\./);
  assert.deepEqual(C.pendingCalls(CALLS.physical, "sleep_coach"), [], "another coach's calls are never this coach's");
});

test("the stage Matthew is in, its plan and what opens the next one; then the stages after it — all from served fields", () => {
  const html = C.longerHTML(PHYSICAL);
  assert.match(html, /The stages this coach works through, set by the author\./);
  // medium: the current stage, its plan, and the test that opens the next
  assert.match(html, /<b>This stage:<\/b> Move the scale and protect the engine\./);
  assert.match(html, /The plan for this stage: Prioritize sustainable weight loss/);
  assert.match(html, /What opens the next stage: A steady downward weight trend over a month/);
  // long: the stages after it, in the served order, and not the current one again
  const after = PHYSICAL.stance.ladder.slice(1).map((s) => s.headline);
  assert.ok(html.includes(`Further out, the stages after it, in order: ${after.join(" ")}</p>`), html);
  assert.equal(html.split("Move the scale and protect the engine").length - 1, 1);
  // #4649: a coach that has written a stance has the ladder beside it, so it has this view too
  assert.equal(SLEEP.stance.source, "stance");
  const sleep = C.longerHTML(SLEEP);
  assert.match(sleep, /<b>This stage:<\/b> Get enough hours, regularly\./);
  assert.match(sleep, /The plan for this stage: Anchor a bedtime window and protect duration\./);
  assert.doesNotMatch(sleep, /What opens the next stage/, "an empty served field prints nothing");
  assert.ok(sleep.includes("in order: Make the timing tight. Now we care about the stages. Protect what works.</p>"));
  // a stage served with no headline is never drawn as a blank
  assert.ok(C.longerHTML(MIND).includes("in order: Let the wins compound. Handle the hard weeks.</p>"));
  // the last stage says so; no ladder at all is the plain sentence
  const last = structuredClone(PHYSICAL);
  last.stance.rung.stage_id = last.stance.ladder.at(-1).stage_id;
  assert.match(C.longerHTML(last), /This is the last stage on the list\./);
  const none = structuredClone(SLEEP);
  delete none.stance.ladder;
  assert.equal(C.longerHTML(none), '<p class="ck-soft">Lisa Park has no longer view on record yet.</p>');
  assert.match(C.longerHTML(LEAD), /Eli Marsh has no longer view on record yet\./);
});

test("the record is a count beside the comparison, never a percentage and never alone", () => {
  const html = C.recordHTML(SLEEP);
  assert.match(html, /<p class="ck-big">10<span>of 24 checked calls<\/span><\/p>/);
  // The route serves the comparison for this coach's calls alone, so the sentence says whose.
  assert.equal(SLEEP.report_card.track_record.comparison.sentence, "Across 24 checked calls, so far they do not beat a simple guess.");
  assert.match(html, /Across Lisa Park’s 24 checked calls, so far they do not beat a simple guess\. The simple guess is that nothing changes from the last reading\./);
  assert.match(html, /Lisa Park’s calls alone through October 4\./);
  assert.equal((html.match(/The simple guess is/g) || []).length, 1);
  assert.match(C.recordHTML(PHYSICAL), /Too few checked calls yet \(13\) to compare them with a simple guess\. The simple guess is/, "any other wording is printed untouched");
  const other = structuredClone(SLEEP);
  other.report_card.track_record.comparison.sentence = "Across 96 checked calls, so far they do not beat a simple guess.";
  assert.doesNotMatch(C.recordHTML(other), /Lisa Park’s 96/, "a count that is not this coach's is never given this coach's name");
  for (const p of ALL) assert.doesNotMatch(text(C.recordHTML(p)), /%|ck-meter|ck-track/, p.name);
  // Mutation control: the same record with its comparison gone draws no count at all.
  const bare = structuredClone(SLEEP);
  bare.report_card.track_record.comparison = null;
  assert.doesNotMatch(C.recordHTML(bare), /ck-big|10/);
  assert.match(C.recordHTML(bare), /What a simple guess would have scored on these calls is not available right now\./);
  assert.match(C.recordHTML(LEAD), /Eli Marsh is the lead\. The lead makes no checked calls, so there is no record here\./);
});

test("the newest right call and the newest wrong call are shown in reader words", () => {
  const { right, wrong } = C.verdictPair(SLEEP);
  assert.match(right.text, /^For Saturday, September 26, Park said .* would land near 7\.8, give or take 1\.2 — it came in at 8\.6\.$/);
  assert.equal(right.checked, "Checked Friday, October 2.");
  assert.match(wrong.text, /Park said the share of deep sleep would go up over the checked window — it went down\./);
  assert.equal(wrong.checked, "Checked Sunday, October 4.");
  const html = C.verdictsHTML(SLEEP);
  assert.match(html, /ck-verdicts__tag--right">Right · within 1\.2 either way</);
  assert.match(html, /ck-verdicts__tag">Wrong · by which way the trend went over the checked window</);
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
  assert.match(html, /No bet of Lisa Park’s has settled yet\./);
  assert.doesNotMatch(text(html), /_coach|brier|recovery_score/i, "no machine name");
});

test("a settled bet says who was right, who was wrong and the result — the loser's page too", () => {
  const html = C.disagreementsHTML(GLUCOSE, DOCKET, NAMES);
  assert.match(html, /Bets settled so far: none won, one lost\./);
  assert.match(html, /Against Marcus Webb · settled September 30/);
  assert.match(html, /The question was: Will the night’s recovery be under 70 on Wednesday, September 30\?/);
  assert.match(html, /Marcus Webb was right\. Amara Patel was wrong\. The result was 59\./);
  assert.match(C.disagreementsHTML(LEAD, DOCKET, NAMES), /Eli Marsh has no bet against another coach, open or settled\./);
  assert.match(C.disagreementsHTML(SLEEP, null, NAMES), /not available right now/);
});

test("the character notes are the served ones, marked as the author's design", () => {
  const html = C.personaHTML(SLEEP);
  assert.match(html, /Written by the author as character design\. Not generated day to day, and not a measurement\./);
  assert.ok(html.includes(`“${SLEEP.character.principles[0]}”`));
  assert.match(html, /<summary>Two more of this coach’s rules<\/summary>/);
  assert.match(html, /The arc this coach was given: from establishing baseline to/);
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
  assert.match(C.watchingHTML(view), /not available right now/);
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
    assert.doesNotMatch(plain, /\bis served\b|\bnot served\b|\bserved for\b/, `${p.name}: plain words, not "served"`);
    // The page's own sentences (everything outside quotation marks) never give a persona a
    // gendered pronoun, and never call the coach "it".
    const own = plain.replace(/“[^”]*”/g, " ");
    assert.doesNotMatch(own, /\b(she|her|hers|he's|she's)\b/i, p.name);
    assert.doesNotMatch(own, /\b(it|its) (asked|bets|has set|was given|reads|keeps)\b|\bfor it to\b|\bits (own|read|rules|record)\b/i, p.name);
    assert.doesNotMatch(plain, /\bundefined\b|\bNaN\b|\[object Object\]|\bnull\b/, p.name);
    assert.doesNotMatch(plain, /\b20\d\d-\d\d-\d\d\b/, p.name);
    assert.doesNotMatch(plain, /\b(cycle|attempt)s?\b|\bresets?\b|earlier starts?|\d+(st|nd|rd|th) start/i, p.name);
  }
});
