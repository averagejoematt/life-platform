// tests/js/ck_coach_4586.test.mjs — #4586: one page per AI coach on the preview. Driven
// from the committed live captures in tests/fixtures/kit_pages_4586/ (the coach's own
// route, the docket and the pending calls, one capture with the rest — its time in
// _capture.json, #4671); no builder reads the wall clock — "today" is passed in, and is the
// capture's own day in Seattle. Expectations read their numbers from the capture (#4839), so a
// recapture of changed figures never fails them; a stance state the capture no longer holds
// (a withheld list, a changed read) is built here from the capture and says so.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const C = await import("../../site/assets/js/ck_coach.js");
// #4586 round 2: these tests pin the coach pages to the 2026-10-13 capture they were written against
// (copied verbatim into kit_pages_4586_pinned when kit_pages_4586 was recaptured on 2026-10-17); the
// kit gate renders the coach pages from the live recapture.
const FIX = join(dirname(fileURLToPath(import.meta.url)), "..", "fixtures", "kit_pages_4586_pinned");
const load = (name) => JSON.parse(readFileSync(join(FIX, `${name}.json`), "utf8"));
const [SLEEP, PHYSICAL, GLUCOSE, LEAD, MIND] = ["sleep_coach", "physical_coach", "glucose_coach", "eli_marsh", "mind_coach"].map((id) => load(`coach_${id}`));
const DOCKET = load("coach_docket_full");
const ROSTER = load("coaches");
const NAMES = C.rosterNames(ROSTER);
const CALLS = { sleep: load("predictions_sleep"), physical: load("predictions_physical"), glucose: load("predictions_glucose") };
const TODAY = new Date(JSON.parse(readFileSync(join(FIX, "_capture.json"), "utf8")).captured_at).toLocaleDateString("en-CA", { timeZone: "America/Los_Angeles" });
const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1);
// #4649: the route withholds a watch item a general reader cannot read, and on the capture
// day that was every item Lisa Park and Nathan Reeves had written (so `focused_on_now` is
// [] in both captures). OWN is the same capture carrying a list of the kind the writer
// stores under the new rule: short, plain, the coach's own. The items are this test's.
const OWN_LIST = ["Whether more protein helps his deep sleep", "Whether easy cardio shows up in his training log", "Whether he notes how he slept each morning"];
const READ_CHANGED = "The downward deep sleep refutation changed what I am watching for.";
const OWN = { ...structuredClone(SLEEP), stance: { ...structuredClone(SLEEP.stance), focused_on_now: OWN_LIST, how_my_read_changed: READ_CHANGED } };
// The same capture with every item the route would have withheld (#4649): the stage's list stands in.
const WITHHELD = { ...structuredClone(SLEEP), stance: { ...structuredClone(SLEEP.stance), focused_on_now: [], how_my_read_changed: "" } };
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

// Where Back goes (`from=`, by name, else the front page) is one rule for every deep page
// since #4675: tests/js/ck_deep_links_4675.test.mjs.

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
  assert.match(html, /In Lisa Park’s own words, written [A-Z][a-z]+ \d+\./);
  const [onPage, behind] = [html.split("<details>")[0], html.slice(html.indexOf("<details>"))];
  assert.ok(onPage.includes(`“${OWN_LIST[0]}.”`), "the first item, verbatim, in quotation marks");
  for (const item of OWN_LIST.slice(1)) {
    assert.ok(!text(onPage).includes(item), `not on the page: ${item}`);
    assert.ok(text(behind).includes(item), `one tap away: ${item}`);
  }
  assert.match(html, /<details><summary>Two more on the list<\/summary>/);
  assert.match(html, /<summary>What Lisa Park has set aside for now<\/summary>/);
  assert.ok(text(html).includes(cap(SLEEP.stance.set_aside_for_now.at(-1))), "with a list of its own, what is set aside is the coach's too");
  assert.match(html, /The latest thing Lisa Park asked of Matthew, [A-Z][a-z]+ \d+: “[^”]+”\s*Due [A-Z][a-z]+ \d+\./);
  assert.ok(html.includes(`<details><summary>How Lisa Park’s read changed</summary><p class="ck-soft">“${READ_CHANGED}`));
  const unchanged = { ...OWN, stance: { ...OWN.stance, how_my_read_changed: "" } };
  assert.doesNotMatch(C.watchingHTML(unchanged), /read changed/, "an empty field prints nothing");
  assert.doesNotMatch(html, /Set by the author/);
});

test("a watch item that uses a known term gets the plain line directly under it, not behind a tap", () => {
  const onPage = C.watchingHTML(OWN).split("<details>")[0];
  assert.match(onPage, /helps his deep sleep\.”<\/p><p class="ck-soft">Deep sleep: also called slow-wave sleep: the share of the night spent in the deepest stage\.<\/p>/);
  assert.deepEqual(C.glossLines("Recovery and HRV"), ["Recovery: his wrist strap’s morning score out of 100.", "HRV: heart-rate variability: how much the gap between heartbeats changes overnight, as the wrist strap measures it."]);
  assert.deepEqual(C.glossLines(OWN_LIST[2]), [], "no known term, no line");
});

test("a coach whose own items were all withheld shows the stage's list as the author's, never as the coach's (#4649)", () => {
  // WITHHELD: the capture's stance with focused_on_now [] and the ladder beside it.
  const SLEEP = WITHHELD;
  assert.deepEqual(SLEEP.stance.focused_on_now, []);
  assert.equal(SLEEP.stance.source, "stance");
  const html = C.watchingHTML(SLEEP);
  assert.match(html, /Set by the author for the stage Matthew is in\. Not written this week\./);
  assert.doesNotMatch(html, /own words/);
  const stageList = SLEEP.stance.rung.cares_most;
  assert.ok(html.includes(`“${cap(stageList[0])}.”`), "the stage's first item, verbatim");
  assert.ok(html.includes(`<details><summary>${stageList.length === 2 ? "One more" : "More"} on the list</summary>`) || /<details><summary>\w+ more on the list<\/summary>/.test(html));
  // What is set aside comes from the same place as the list above it: the stage, not the stance.
  const aside = html.slice(html.indexOf("has set aside for now"));
  assert.ok(text(aside).toLowerCase().includes(SLEEP.stance.rung.cares_less_right_now[0].toLowerCase()));
  assert.ok(!text(html).includes(cap(SLEEP.stance.set_aside_for_now.at(-1))));
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
  const changed = { ...structuredClone(MIND), stance: { ...structuredClone(MIND.stance), how_my_read_changed: "The protein reversal refutes my prediction, so I changed what I watch." } };
  const html = C.watchingHTML(changed);
  assert.match(html, /<details><summary>How Nathan Reeves’s read changed<\/summary><p class="ck-soft">“The protein reversal refutes my prediction/);
  assert.doesNotMatch(C.watchingHTML({ ...changed, stance: { ...changed.stance, how_my_read_changed: "" } }), /read changed/);
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
  const upcoming = CALLS.sleep.predictions.filter((c) => C.isUpcoming(c, TODAY)).sort((a, b) => a.due_date.localeCompare(b.due_date));
  const shown = upcoming.slice(0, 2);
  assert.ok(shown.length === 2, "the capture holds two upcoming calls to list");
  assert.match(html, /<b>[A-Z][a-z]+day, [A-Z][a-z]+ \d+:<\/b> a (call comes due to be checked|bet against [A-Z][a-z]+ [A-Z][a-z]+ settles)\./);
  assert.match(html, /(\w+) calls? (is|are) waiting to be checked\./, "the whole count is never hidden");
  assert.equal((html.match(/<time /g) || []).length, 2, "the two soonest calls");
  for (const c of shown) assert.ok(html.includes(`<time datetime="${c.due_date.slice(0, 10)}">`), c.due_date);
  assert.doesNotMatch(text(html), /\b20\d\d-\d\d-\d\d\b/);
  assert.match(html, /<p class="ck-soft">[^<]*(more are due after these|older calls? (is|are) still waiting to be checked)[^<]*<\/p>$|<\/ul>$/, "the accounting is one paragraph");
  // the open bet is the next section's own card; this section does not signpost it (2026-10-11)
  assert.doesNotMatch(html, /next section/);
  assert.match(C.nextHTML(SLEEP, null, CALLS.sleep, NAMES, TODAY), /The bets between coaches are not available right now\.<\/p>$/);
  // A bet that settles before the first call leads instead (the October 4 shape of the docket).
  const soon = structuredClone(DOCKET);
  soon.open.find((b) => [b.coach_a, b.coach_b].includes("sleep_coach")).resolution_date = TODAY;
  const led = C.nextHTML(SLEEP, soon, CALLS.sleep, NAMES, TODAY);
  assert.match(led, /^<p><b>[A-Z][a-z]+day, [A-Z][a-z]+ \d+:<\/b> a bet against [A-Z][a-z]+ [A-Z][a-z]+ settles\./);
});

test("a call about a day before it was said, a 'tomorrow' long gone and a due date in another year are counted, not listed", () => {
  // The specimens are this test's own, appended to the capture's list (the capture holds whichever calls are pending today).
  const gone = { coach_id: "sleep", status: "pending", text: "Recovery score tomorrow will be 90.6%", date: "2026-09-03", due_date: "2026-09-04" };
  const far = { coach_id: "sleep", status: "pending", text: "Sleep will improve over the long run", date: "2026-09-03", due_date: "2032-04-13" };
  const withSpecimens = { ...CALLS.sleep, predictions: [...CALLS.sleep.predictions, gone, far] };
  const html = C.nextHTML(SLEEP, DOCKET, withSpecimens, NAMES, TODAY);
  assert.equal(C.statedDay(gone), "2026-09-04");
  assert.equal(C.isUpcoming(gone, TODAY), false);
  assert.doesNotMatch(html, /90\.6%/);
  assert.doesNotMatch(html, /tomorrow/i, "no days-old 'tomorrow' is listed as coming up");
  assert.doesNotMatch(html, /Sleep will improve over the long run/, "a due date years out is counted, not listed");
  // A call about a day before it was said (the October 4 capture's specimen, as it was stored).
  const past = { status: "pending", text: "Recovery score is expected to hold around 90.9% on 2026-09-20 based on current model", date: "2026-09-21", due_date: "2026-10-12" };
  assert.equal(C.statedDay(past), "2026-09-20");
  assert.equal(C.isUpcoming(past, TODAY), false);
  const upcoming = CALLS.sleep.predictions.filter((c) => C.isUpcoming(c, TODAY));
  for (const c of upcoming) assert.ok(c.due_date.slice(0, 4) <= String(Number(TODAY.slice(0, 4)) + 1), c.text);
  // The rule, on its own terms.
  const call = (o) => ({ status: "pending", text: "x", date: "2026-10-03", due_date: "2026-10-17", ...o });
  assert.equal(C.isUpcoming(call({}), TODAY), true, "names no day: listed");
  assert.equal(C.isUpcoming(call({ text: "Recovery tomorrow will be 80", date: TODAY }), TODAY), true, "tomorrow really is ahead");
  assert.equal(C.isUpcoming(call({ text: "Recovery tomorrow will be 80", date: "2026-09-25" }), TODAY), false);
  assert.equal(C.isUpcoming(call({ due_date: "2032-04-13" }), TODAY), false);
  assert.equal(C.isUpcoming(call({ due_date: "2026-10-01" }), TODAY), false, "past its date");
  // Mutation control: with nothing left to list, the count and the older-calls sentence still print.
  const later = C.nextHTML(SLEEP, { open: [], resolved: [] }, CALLS.sleep, NAMES, "2027-01-01");
  assert.doesNotMatch(later, /<time /);
  assert.match(later, /\w+ calls are waiting to be checked\./);
  assert.match(later, /\w+ older calls are still waiting to be checked\./);
});

test("a sealed bet the route marks reader_plain:false is listed with a note, never hidden (#4714)", () => {
  const sealed = { coach_id: "sleep", status: "pending", text: "Sleep EWMA should rise once the fixed bedtime holds.", date: "2026-09-06", due_date: "2026-10-14", pre_registered: true, reader_plain: false };
  const html = C.nextHTML(SLEEP, { open: [], resolved: [] }, { predictions: [sealed] }, NAMES, TODAY);
  assert.match(html, /Sleep EWMA should rise/, "the sealed bet is listed");
  assert.match(html, /Sealed before the experiment began, so it keeps its original wording\./);
  // the note is the label's alone: a plain sealed bet and an in-cycle call carry none
  assert.equal(C.sealedNote({ ...sealed, reader_plain: undefined }), "");
  assert.equal(C.sealedNote({ ...sealed, pre_registered: false }), "");
  assert.doesNotMatch(C.nextHTML(SLEEP, { open: [], resolved: [] }, { predictions: [{ ...sealed, reader_plain: undefined }] }, NAMES, TODAY), /Sealed before/);
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
  const tr = SLEEP.report_card.track_record;
  assert.ok(html.includes(`<p class="ck-big">${tr.record.confirmed}<span> of ${tr.record.n} checked calls</span></p>`));
  // The route serves the comparison for this coach's calls alone, so the sentence says whose. Its shape changes with the
  // engine: one "Across N checked calls, so far they ..." line, or a line per kind of call. Either way the served sentence
  // is printed, never rewritten into another coach's count; the "Across N" shape is named after the coach.
  assert.ok(tr.comparison.sentence.trim().length > 20 && tr.comparison.sentence.endsWith("."));
  const named = (p) => p.report_card.track_record.comparison.sentence.replace(/^Across (\d+) checked calls\b/, (all, k) => (Number(k) === p.report_card.track_record.record.n ? `Across ${p.name}’s ${k} checked calls` : all));
  assert.ok(html.includes(named(SLEEP).replace(/&/g, "&amp;")), "the served comparison is printed");
  assert.match(html, /The simple guess is that nothing changes from the last reading\./);
  assert.match(html, /Lisa Park’s calls alone through [A-Z][a-z]+ \d+\./);
  assert.equal((html.match(/The simple guess is/g) || []).length, 1);
  assert.ok(C.recordHTML(PHYSICAL).includes(named(PHYSICAL).replace(/&/g, "&amp;")), "the served comparison is printed, never rewritten into another coach's count");
  const other = structuredClone(SLEEP);
  other.report_card.track_record.comparison.sentence = "Across 131 checked calls, so far they do not beat a simple guess.";
  assert.doesNotMatch(C.recordHTML(other), /Lisa Park’s 131/, "a count that is not this coach's is never given this coach's name");
  for (const p of ALL) assert.doesNotMatch(text(C.recordHTML(p)), /%|ck-meter|ck-track/, p.name);
  // Mutation control: the same record with its comparison gone draws no count at all.
  const bare = structuredClone(SLEEP);
  bare.report_card.track_record.comparison = null;
  assert.doesNotMatch(C.recordHTML(bare), /ck-big/);
  assert.match(C.recordHTML(bare), /What a simple guess would have scored on these calls is not available right now\./);
  assert.match(C.recordHTML(LEAD), /Eli Marsh is the lead\. The lead makes no checked calls, so there is no record here\./);
});

test("the newest right call and the newest wrong call are shown in reader words", () => {
  const { right, wrong } = C.verdictPair(SLEEP);
  assert.match(right.text, /^For [A-Z][a-z]+day, [A-Z][a-z]+ \d+, Park said .* would land near [\d.]+, give or take [\d.]+ — it came in at [\d.]+\.$/);
  assert.match(right.checked, /^Checked [A-Z][a-z]+day, [A-Z][a-z]+ \d+\.$/);
  assert.match(wrong.text, /^For |^Park said |Park said /);
  assert.match(wrong.checked, /^Checked [A-Z][a-z]+day, [A-Z][a-z]+ \d+\.$/);
  const html = C.verdictsHTML(SLEEP);
  assert.match(html, /ck-verdicts__tag--right">Right · within [\d.]+ either way</);
  assert.match(html, /ck-verdicts__tag">Wrong · [^<]+</);
  assert.doesNotMatch(text(html), /slope|trend=|_pct|\b20\d\d-\d\d-\d\d\b/, "the grader's working never reaches the page");
  assert.equal(C.verdictsHTML(LEAD), "", "no checked call: the mount prints the absence sentence");
});

test("an open bet is a dated yes-or-no question with each coach's side, by name", () => {
  const html = C.disagreementsHTML(SLEEP, DOCKET, NAMES);
  assert.equal((html.match(/class="ck-bet"/g) || []).length, 3, "one open, two settled");
  assert.match(html, /Against Max Reyes · settles Friday, October 16<\/p><p><b>Will the seven-night average share of deep sleep be 26 or better on Friday, October 16\?<\/b>/);
  assert.match(html, /Lisa Park says no\. Max Reyes says yes\./);
  assert.match(html, /<details><summary>What each one argued<\/summary><p class="ck-soft"><b>Lisa Park:<\/b> “/);
  assert.match(html, /Bets settled so far: one won, one lost\./);
  // Before any bet of the coach's settled, the page says so.
  const none = { ...DOCKET, resolved: [] };
  assert.match(C.disagreementsHTML(SLEEP, none, NAMES), /No bet of Lisa Park’s has settled yet\./);
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

// #4673: /api/coach_docket holds a side whose words cite a sensor that had sent no reading by
// the day the bet opened — `claims` loses it, `unsourced` names why. The page prints that
// sentence beside the coach's name where the quote would be; the words never reach it.
test("a settled bet side the route held prints why beside the name, never the words", () => {
  const docket = structuredClone(DOCKET);
  const held = "Not quoted: this was said on September 23 and rests on his glucose sensor, which had sent no reading since August 27.";
  const bet = docket.resolved.find((d) => d.coach_a === "glucose_coach" || d.coach_b === "glucose_coach");
  delete bet.claims.glucose_coach;
  bet.unsourced = { glucose_coach: { reason: "no sensor since 2026-08-27", text: held } };
  const html = C.disagreementsHTML(GLUCOSE, docket, NAMES);
  assert.ok(html.includes(`<p class="ck-soft"><b>Amara Patel:</b> ${held}</p>`), html);
  assert.match(html, /<b>Marcus Webb:<\/b> “Any carb reduction/);
  assert.doesNotMatch(html, /CGM data/);
  // The unmodified capture: a side is quoted unless the route itself held it, and then the route's sentence stands.
  const served = DOCKET.resolved.find((d) => d.coach_a === "glucose_coach" || d.coach_b === "glucose_coach");
  const plain = C.disagreementsHTML(GLUCOSE, DOCKET, NAMES);
  if (served.unsourced && served.unsourced.glucose_coach) assert.ok(plain.includes(served.unsourced.glucose_coach.text));
  else assert.doesNotMatch(plain, /Not quoted/, "nothing held, nothing said");
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
  const rec = ROSTER.coaches.find((c) => c.persona_id === "sleep_coach").record;
  assert.ok(C.recordHTML(view).includes(`${rec.confirmed}<span> of ${rec.n} checked calls`), "the roster carries the record and its comparison");
  const thin = structuredClone(ROSTER);
  thin.coaches.find((c) => c.persona_id === "sleep_coach").comparison = null;
  assert.match(C.recordHTML(C.coachView("sleep_coach", null, thin)), /What a simple guess would have scored/, "a roster entry with no comparison draws no count");
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
