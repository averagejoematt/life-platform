// The Coaching Room's docket and "wrong this month" view (src/lib/docket.js, CR3): carried values only, withheld words
// stay withheld (the API's own message or "not published"), no concession or outcome is composed, a disputed call is
// never wrong, a corrected grade shows its correction, and every grade is "as first graded". Each with a control.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  DOCKET_NOT_PUBLISHED,
  allDocketEntries,
  callWords,
  incompleteEntries,
  incompleteText,
  isPublishable,
  concessionOf,
  datesOf,
  docketEntries,
  docketEntry,
  entryForDisagreement,
  gapsOf,
  liveMeasure,
  measureWords,
  monthOf,
  monthWords,
  previousMonth,
  questionOf,
  refutedLedger,
  verifiedMisses,
  refutedRow,
  resultOf,
  sidesOf,
  stakeText,
  tallyText,
  testWords,
} from "../src/lib/docket.js";
import { NOT_PUBLISHED } from "../src/lib/coach_room.js";

const FIX = join(dirname(fileURLToPath(import.meta.url)), "..", "content", "fixtures");
const FILE = JSON.parse(readFileSync(join(FIX, "coach_room.json"), "utf8"));
const PREDS = JSON.parse(readFileSync(join(FIX, "predictions.json"), "utf8"));
const NAMES = { sleep_coach: "Lisa Park", nutrition_coach: "Nathan Reeves", glucose_coach: "Amara Patel", training_coach: "Sam Ortiz" };
const nameOf = (id) => NAMES[id] || id;

test("the docket: open first (soonest to settle), then settled newest first; an absent file is no entry", () => {
  assert.deepEqual(
    allDocketEntries(FILE).map((e) => e.id),
    [
      "2026-10-27-sleep-coach-training-coach", // open, settles 10 November
      "2026-10-02-nutrition-coach-sleep-coach", // settled 16 October
      "2026-10-06-sleep-coach-training-coach", // settled 13 October
      "2026-09-23-glucose-coach-nutrition-coach", // settled 30 September
    ]
  );
  // only the complete entries get a row and a page (owner, 2026-11-09), in the same order
  assert.deepEqual(
    docketEntries(FILE).map((e) => e.id),
    ["2026-10-27-sleep-coach-training-coach", "2026-10-06-sleep-coach-training-coach"]
  );
  assert.deepEqual(docketEntries({ state: "absent" }), []);
  assert.deepEqual(docketEntries(null), []);
  assert.equal(docketEntry(FILE, "nope"), null);
  assert.equal(tallyText(FILE.docket_counts), "1 open · 3 settled");
  assert.equal(tallyText(null), null);
});

test("the question: the topic's words when served, else the criterion's, else the frozen test — never a paraphrase", () => {
  const e = docketEntry(FILE, "2026-10-02-nutrition-coach-sleep-coach");
  const q = questionOf(e);
  assert.equal(q.from, "test", "topic and description are withheld: the page states the frozen test");
  assert.equal(q.text, "Recovery score, 7-day average, at or above 70?");
  assert.deepEqual(questionOf({ ...e, topic: "Does protein help recovery?" }), { text: "Does protein help recovery?", from: "topic" });
  const c = docketEntry(FILE, "2026-10-06-sleep-coach-training-coach");
  assert.equal(questionOf(c).from, "topic");
  assert.equal(questionOf({ ...c, topic: "" }).from, "criterion");
  assert.equal(questionOf({ ...e, criterion: {} }).text, null, "no topic, no description, no measure: nothing is invented");
  assert.equal(measureWords("recovery_score_7day_avg"), "recovery score, 7-day average");
  assert.equal(testWords({ metric: "resting_hr", condition: "lte", threshold: 58 }), "resting hr at or below 58");
  assert.equal(testWords({ metric: "recovery_score", condition: "gte", threshold: 81.6 }), "recovery score at or above 81.6");
});

test("each side: its served bet, its words or the API's OWN withheld message, its frozen stake", () => {
  const e = docketEntry(FILE, "2026-09-23-glucose-coach-nutrition-coach");
  const [g, n] = sidesOf(e, nameOf);
  assert.equal(g.name, "Amara Patel");
  assert.equal(g.side, "bet the test would not hold");
  assert.equal(g.text, null);
  assert.match(g.message, /^Not quoted: this was said on September 23/, "the API's own message, carried");
  assert.equal(g.apiMessage, true);
  assert.equal(g.lost, true);
  assert.equal(n.text, "Sample claim for the fixture build, nutrition side.");
  assert.equal(n.won, true);
  assert.equal(n.stake, "Brier 0.250 over 10 calls, frozen at the open");
  // the control: no claim and no API message → only that the words are not published
  const [a] = sidesOf(docketEntry(FILE, "2026-10-02-nutrition-coach-sleep-coach"), nameOf);
  assert.equal(a.message, NOT_PUBLISHED.claim);
  assert.equal(a.apiMessage, false);
  assert.equal(stakeText(null), null);
  assert.equal(sidesOf({ coach_a: "x", coach_b: "y", status: "open" })[0].side, "side not recorded");
});

test("the result restates served fields only: winner, the value, whether the test held; open = when the data decides", () => {
  const r = resultOf(docketEntry(FILE, "2026-10-02-nutrition-coach-sleep-coach"), nameOf);
  assert.equal(r.headline, "Lisa Park won; Nathan Reeves lost.");
  assert.equal(r.measured, "The measure came in at 74.4: the test held.");
  const o = resultOf(docketEntry(FILE, "2026-10-27-sleep-coach-training-coach"), nameOf);
  assert.equal(o.settled, false);
  assert.equal(o.headline, "Not settled yet. The data decides on 10 November 2026.");
  const v = resultOf({ coach_a: "a", coach_b: "b", status: "resolved", outcome: "void_no_data", winner: null }, nameOf);
  assert.equal(v.headline, "Settled without a winner (void no data).");
  assert.equal(v.measured, "");
  // no word of motive or concession is ever composed
  for (const x of [r, o, v]) assert.doesNotMatch(`${x.headline} ${x.measured || ""}`, /conced|admit|because|wanted|accept/i);
  assert.deepEqual(datesOf(docketEntry(FILE, "2026-10-27-sleep-coach-training-coach")), { opened: "27 October 2026", settles: "10 November 2026", settled: null });
});

test("a concession: quoted only when served; else the API's own message; else none — never written", () => {
  assert.deepEqual(concessionOf(docketEntry(FILE, "2026-10-06-sleep-coach-training-coach")), { text: "Sample concession text for the fixture build.", message: null });
  assert.match(concessionOf(docketEntry(FILE, "2026-09-23-glucose-coach-nutrition-coach")).message, /^Not quoted:/);
  assert.equal(concessionOf(docketEntry(FILE, "2026-10-02-nutrition-coach-sleep-coach")), null);
  assert.equal(concessionOf(docketEntry(FILE, "2026-10-27-sleep-coach-training-coach")), null, "an open entry has no concession");
  assert.equal(DOCKET_NOT_PUBLISHED.concession, "No concession is served for this entry.");
});

test("the live measure: only an open entry, only under the SAME measure id (no proxy for a 7-day average)", () => {
  const open = docketEntry(FILE, "2026-10-27-sleep-coach-training-coach");
  const series = { unit: "out of 100", days: [{ date: "2026-10-16", present: true, value: 69 }, { date: "2026-10-17", present: false, value: null }] };
  assert.deepEqual(liveMeasure(open, { title: "Recovery", decimals: 0 }, series), { value: "69", unit: "out of 100", day: "16 October 2026", label: "Recovery" });
  const avg = { ...open, criterion: { metric: "recovery_score_7day_avg", condition: "gte", threshold: 80 } };
  assert.match(liveMeasure(avg, null, null).missing, /serves no series for recovery score, 7-day average/);
  assert.equal(liveMeasure(docketEntry(FILE, "2026-10-02-nutrition-coach-sleep-coach"), {}, series), null);
});

test("what the page cannot show is named with its field; the disagreement page finds its entry by seats and day", () => {
  const gaps = gapsOf(docketEntry(FILE, "2026-10-02-nutrition-coach-sleep-coach"), nameOf);
  assert.ok(gaps.includes("the question's own words (topic)"));
  assert.ok(gaps.includes("Lisa Park's words (claims)") && gaps.includes("Nathan Reeves's words (claims)"));
  assert.ok(gaps.includes("the criterion's own words (criterion.description)"));
  assert.ok(gaps.some((g) => g.startsWith("an integrator's call")));
  assert.ok(!gaps.join(" ").includes("sleep_coach"), "a raw persona id is never page text");
  const entries = allDocketEntries(FILE);
  assert.equal(entryForDisagreement(entries, { coach_a: "sleep_coach", coach_b: "nutrition_coach", status: "resolved", resolved_date: "2026-10-16" }).id, "2026-10-02-nutrition-coach-sleep-coach");
  assert.equal(entryForDisagreement(entries, { coach_a: "sleep_coach", coach_b: "nutrition_coach", status: "open" }), null, "the control: same seats, wrong status");
  assert.equal(entryForDisagreement(entries, { coach_a: "sleep_coach", coach_b: "nutrition_coach", status: "resolved", resolved_date: "2026-10-17" }), null);
});

test("an incomplete entry gets no page: topic, BOTH sides' words and the criterion's words must all be served (each a control)", () => {
  const full = docketEntry(FILE, "2026-10-06-sleep-coach-training-coach");
  assert.equal(isPublishable(full), true, "the control: a complete entry is publishable");
  assert.equal(isPublishable({ ...full, topic: "  " }), false, "no topic");
  assert.equal(isPublishable({ ...full, criterion: { ...full.criterion, description: "" } }), false, "no criterion words");
  assert.equal(isPublishable({ ...full, claims: { ...full.claims, sleep_coach: "" } }), false, "one side's words missing");
  assert.equal(isPublishable({ ...full, claims: {} }), false, "no side's words");
  assert.equal(isPublishable(docketEntry(FILE, "2026-09-23-glucose-coach-nutrition-coach")), false, "a side withheld by the API is not served");
  assert.equal(isPublishable(null), false);
  const inc = incompleteEntries(FILE);
  assert.deepEqual(inc.map((e) => e.id), ["2026-10-02-nutrition-coach-sleep-coach", "2026-09-23-glucose-coach-nutrition-coach"]);
  const line = incompleteText(inc);
  assert.match(line, /^2 settled entries are incomplete — not yet cleared for publication\./);
  assert.match(line, /no page here\.$/);
  assert.equal(incompleteText([]), null, "nothing incomplete → no line");
  assert.match(incompleteText([{ status: "open" }]), /^1 open entry is incomplete/);
  assert.match(incompleteText([{ status: "open" }, { status: "resolved" }]), /^1 open and 1 settled entries are incomplete/);
});

test("wrong this month: served statuses only, disputed never wrong, corrections shown, every grade as first graded", () => {
  assert.equal(monthOf("2026-10-31"), "2026-10");
  assert.equal(monthWords("2026-10"), "October 2026");
  assert.equal(previousMonth("2026-01"), "2025-12");
  assert.equal(previousMonth("2026-11"), "2026-10");
  const v = refutedLedger(PREDS, "2026-10");
  const refutedInMonth = PREDS.filter((p) => p.status === "refuted" && String(p.settled_date).startsWith("2026-10"));
  assert.ok(refutedInMonth.length >= 2, "the fixture holds a wrong call and a disputed one");
  assert.equal(v.wrong.length + v.disputed.length, refutedInMonth.length);
  assert.ok(v.wrong.every((p) => p.classification_review !== true));
  assert.ok(v.disputed.length >= 1 && v.disputed.every((p) => p.classification_review === true), "a disputed call is listed apart");
  assert.ok(v.corrected.length >= 1 && v.corrected.every(({ c }) => c.original_status === "refuted" || c.corrected_status === "refuted"));
  // the control: a disputed call never lands in `wrong`, even when it is the only refuted call
  const only = refutedLedger([{ id: "x", status: "refuted", settled_date: "2026-10-02", classification_review: true }], "2026-10");
  assert.equal(only.wrong.length, 0);
  assert.equal(only.disputed.length, 1);
  assert.equal(refutedLedger(PREDS, "2026-09").wrong.length, 0);
  const row = refutedRow(v.wrong[0], nameOf);
  assert.match(row.outcome, /^wrong, as first graded$/);
  assert.doesNotMatch(`${row.how || ""} ${row.notes || ""}`, /\d{4}-\d{2}-\d{2}/, "dates in words");
  assert.deepEqual(callWords({ claim_withheld: "unsourced", claim: "Not quoted: held." }), { text: null, message: "Not quoted: held." });
  assert.equal(callWords({ claim: "" }).message, "The words of this call are not published.");
});

// ── "wrong this month", as published with CR1 (owner ruling 2026-11-09): verified, eligible, cleared outcomes only ──
test("wrong this month draws only from the producer's counted calls (control: the same refuted call outside the set is not listed)", () => {
  const miss = "nutrition-20261015-protein01";
  assert.ok(
    PREDS.some((p) => p.id === miss && p.status === "refuted" && String(p.settled_date).startsWith("2026-10") && !p.classification_review),
    "the fixture holds a refuted October call to count or not"
  );
  // not in the producer's set (unverified, excluded or a repeat): never listed
  const out = verifiedMisses(PREDS, "2026-10", new Set(["physical-20261015-weight01"]));
  assert.equal(out.verified, true);
  assert.deepEqual(out.wrong, [], "an uncounted miss never reaches the view");
  // mutation control: the same call in the set appears
  assert.deepEqual(verifiedMisses(PREDS, "2026-10", new Set([miss])).wrong.map((p) => p.id), [miss]);
  // a call under classification review is never listed, even when named in the set
  const v = verifiedMisses(PREDS, "2026-10", new Set([miss, "sleep-20261005-deepsleep01"]));
  assert.deepEqual(v.wrong.map((p) => p.id), [miss]);
  assert.deepEqual(v.disputed, [], "a call under review is not a verified outcome");
});

test("wrong this month with no counted list served renders no miss at all — never the unverified ledger (control: the ledger has misses)", () => {
  assert.ok(refutedLedger(PREDS, "2026-10").wrong.length > 0, "the control: unverified misses exist to leak");
  for (const absent of [null, undefined, ["sleep-20261005-deepsleep01"]]) {
    const v = verifiedMisses(PREDS, "2026-10", absent);
    assert.equal(v.verified, false);
    assert.deepEqual([v.wrong.length, v.disputed.length, v.corrected.length], [0, 0, 0]);
  }
});

test("the refuted page reads the counted set, and the docket only on a whole-room build", () => {
  const page = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "src", "room", "refuted.astro"), "utf8");
  assert.match(page, /countedCalls\(file\.calibration\)/);
  assert.match(page, /verifiedMisses\(preds, month, counted\)/);
  assert.doesNotMatch(page, /refutedLedger\(/, "the unverified ledger view is never the page's source");
  assert.match(page, /roomAll\(\) \? docketEntries\(await loadCoachRoom\(\)\)/, "coach_room.json is read only on a whole-room build");
});
