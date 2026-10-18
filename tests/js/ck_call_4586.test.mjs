// tests/js/ck_call_4586.test.mjs — #4586: a page for each settled coach call. Driven from
// tests/fixtures/kit_pages_4586/calls.json, GET /api/calls as the live site served it (one
// capture with the rest of the kit fixtures, #4671; tests/test_site_api_calls_4586.py holds
// it to the route's shape); no builder reads the wall clock.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const C = await import("../../site/assets/js/ck_call.js");
const V = await import("../../site/assets/js/ck_verdict.js");
const FIX = join(dirname(fileURLToPath(import.meta.url)), "..", "fixtures", "kit_pages_4586");
const BODY = JSON.parse(readFileSync(join(FIX, "calls.json"), "utf8"));
const BASE = "/next/v8/";
const NUMBER = "sleep-20260907-8436f03290";
const BET = "bet-20260930-994b3d89f6";
const clone = (v) => JSON.parse(JSON.stringify(v));

test("a call is found by its own id, and an address that names none finds nothing", () => {
  assert.equal(C.findCall(BODY, NUMBER).coach_name, "Lisa Park");
  assert.equal(C.findCall(BODY, "sleep-20260907-0000000000"), null);
  assert.equal(C.findCall(BODY, "__proto__"), null);
  assert.equal(C.findCall(null, NUMBER), null);
  assert.equal(C.findCall({ state: "unavailable", calls: [] }, NUMBER), null);
});

test("the call is shown in the coach's own words, with who, when and what it means", () => {
  const html = C.claimHTML(C.findCall(BODY, NUMBER));
  assert.match(html, /<p class="ck-small">Lisa Park · logged September 7<\/p>/);
  assert.match(html, /<b>“Recovery score is expected to climb back to roughly 61% tomorrow/);
  // Site-to-A round 1: the route's sentence is the page's title; it is not said again under the coach's words.
  assert.doesNotMatch(html, /at about 61 for September 8/);
  const sealed = C.claimHTML(C.callsOf(BODY).find((c) => c.sealed));
  assert.match(sealed, / · sealed September 5, before day one<\/p>/);
});

test("what happened carries the verdict as the kit's tag, beside the simple guess", () => {
  const call = C.findCall(BODY, NUMBER);
  const tol = call.tolerance.text;
  const right = C.outcomeHTML(call);
  // Site-to-A round 1: the result is the heading above the card and the verdict is the tag's word, so the
  // card is the tag and one soft line — neither `happened` in bold nor "<coach> was right" again.
  assert.match(right, new RegExp(`<span class="ck-verdicts__tag ck-verdicts__tag--right">Right · within ${tol.replace(".", "\\.")}% either way</span><p class="ck-soft">The allowed distance is`));
  assert.ok(!right.includes(`<b>${call.happened}</b>`) && !right.includes(call.verdict_text), "the call and its verdict are not restated");
  // #4808: the allowed distance is in the tag, and what it is — its statistic and window — once, below
  assert.ok(right.includes(`The allowed distance is ${call.tolerance.statistic}.`));
  assert.match(right, /The allowed distance is [^<]+\. Graded on the reading for [A-Z][a-z]+ \d+\.(<\/p>| The simple guess was also right\.<\/p>)/);
  assert.doesNotMatch(right, /Checked [A-Z][a-z]+ \d+\./, "the page's label says the day it settled");
  // The number sits in the call's own tag; a call the simple guess was scored on prints it in that guess's tag too, and nowhere else.
  const scored = call.simple_guess && call.simple_guess.state === "scored";
  assert.equal(right.split(tol).length - 1, scored ? 2 : 1, "the number is printed once per verdict tag");
  if (scored) assert.ok(right.includes(`<p>${call.simple_guess.text}</p>`));
  // A call the guess has not been checked on says so (built from the capture: the capture's call is scored).
  const unchecked = clone(call);
  delete unchecked.simple_guess;
  assert.match(C.outcomeHTML(unchecked), /<span class="ck-verdicts__tag">The simple guess<\/span><p>The simple guess has not been checked against this call yet\.<\/p>/);
  const wrong = C.outcomeHTML(C.callsOf(BODY).find((c) => c.verdict === "wrong"));
  assert.match(wrong, /<span class="ck-verdicts__tag">Wrong · not within [\d.]+% either way<\/span>/);
});

test("a call the simple guess was checked on says what it said and whether it was right", () => {
  const call = clone(C.findCall(BODY, NUMBER));
  call.simple_guess = { state: "scored", right: true, text: "The simple guess was that it would stay at 62, the last reading before the call. That guess was also right.", short: "also right" };
  assert.match(C.outcomeHTML(call), /<span class="ck-verdicts__tag ck-verdicts__tag--right">The simple guess: right · within 17\.9% either way<\/span><p>The simple guess was that it would stay at 62/);
  // Site-to-A round 1: the verdict line says when the simple guess also won.
  assert.match(C.outcomeHTML(call), /<p class="ck-soft">The allowed distance is [^<]+\. Graded on the reading for September 8\. The simple guess was also right\.<\/p>/);
  assert.equal(C.guessAlso(call), "The simple guess was also right.");
  call.simple_guess = { ...call.simple_guess, right: false, short: "wrong" };
  assert.match(C.outcomeHTML(call), /<span class="ck-verdicts__tag">The simple guess: wrong · not within 17\.9% either way<\/span>/);
  assert.equal(C.guessAlso(call), "");
});

test("a bet shows both coaches' words and who was right", () => {
  const bet = C.findCall(BODY, BET);
  const claim = C.claimHTML(bet);
  assert.match(claim, /<p class="ck-small">A bet opened September 23<\/p>/);
  assert.match(claim, /Marcus Webb said yes: “Any carb reduction/);
  // The route may hold a side whose words rest on an unsourced reading: then the name is followed by its sentence, not a quote.
  assert.match(claim, /Amara Patel said no(: “|\. )/);
  const out = C.outcomeHTML(bet);
  assert.match(out, /ck-verdicts__tag--right">Right · on whether his morning recovery score would be below 70 on September 30<\/span><p><b>Marcus Webb said yes\.<\/b>/);
  assert.match(out, /<span class="ck-verdicts__tag">Wrong · on whether his morning recovery score would be below 70 on September 30<\/span><p><b>Amara Patel said no\.<\/b>/);
  assert.match(out, /It came in at 59\. Graded on the reading for September 30\.<\/p>/);
});

// #4673: the route holds a side whose words rest on a sensor that had sent no reading by the
// day the bet opened (claim "" + unsourced). The page prints the route's sentence beside the
// name in the quote's place; the words never reach it.
test("a bet side the route held prints why beside the name, never the words", () => {
  const bet = clone(C.findCall(BODY, BET));
  const held = "Not quoted: this was said on September 23 and rests on his glucose sensor, which had sent no reading since August 27.";
  bet.sides = bet.sides.map((s) => (s.coach_id === "glucose" ? { ...s, claim: "", unsourced: { reason: "no sensor since 2026-08-27", text: held } } : s));
  const claim = C.claimHTML(bet);
  assert.match(claim, /Marcus Webb said yes: “Any carb reduction/);
  assert.ok(claim.includes(`<p class="ck-soft">Amara Patel said no. ${held}</p>`), claim);
  assert.doesNotMatch(claim, /CGM data/);
});

test("the running record is counts in a sentence, never a percentage", () => {
  const html = C.recordHTML(C.findCall(BODY, NUMBER), BODY);
  const rec = C.findCall(BODY, NUMBER).records[0];
  assert.match(rec.text, /^Lisa Park: \d+ of \d+ checked calls right\.$/);
  // Site-to-A round 1: two short sentences naming the coach — the served count and the comparison's
  // verdict per kind of call, never "the coaches" for one coach's record — and the served sentence
  // whole, one tap below.
  const short = C.recordComparisonShort("Lisa Park", rec.comparison);
  assert.match(short, /^Against a guess that nothing changes, Lisa Park is (ahead|level|behind) on /);
  assert.doesNotMatch(short, /the coaches/);
  assert.ok(html.includes(`<p>${rec.text} ${short}</p><details><summary>The record by kind of call</summary><p class="ck-soft" data-coach-comparison>${rec.comparison.sentence}</p></details>`), html);
  assert.equal(C.recordComparisonShort("Lisa Park", { sentence: "Across 24 checked calls, so far they do not beat a simple guess." }), "Across 24 checked calls, so far they do not beat a simple guess.", "another shape: printed as served, nothing reworded");
  assert.equal(short, "Against a guess that nothing changes, Lisa Park is ahead on number calls and level on direction calls, yes/no bets and sealed day-one predictions, none by a clear margin.");
  assert.equal(C.recordComparisonShort("Lisa Park", { sentence: "x", short: "Served short form." }), "Served short form.", "a served short form wins");
  const bare = clone(C.findCall(BODY, NUMBER));
  bare.records[0].comparison = null;
  assert.match(C.recordHTML(bare, BODY), /What a simple guess would have scored on these calls is not available right now\./, "a count never stands alone");
  assert.match(html, /The record counts every checked call, including the ones with no page of their own\./);
  assert.doesNotMatch(html, /%/);
  const both = C.recordHTML(C.findCall(BODY, BET), BODY);
  const bothRecs = C.findCall(BODY, BET).records;
  assert.equal(bothRecs.length, 2);
  for (const r of bothRecs) assert.ok(both.includes(`<p>${r.text}</p>`), r.text);
});

test("the front page's last settled call is one block that opens its page", () => {
  // It leads with the clearest miss on record, not the newest call (red team, round 7).
  const html = C.lastCallHTML(BODY, BASE);
  // The card is the call the page named in its link, read back from the capture: what it says is that call's own words.
  const id = html.match(/href="\/next\/v8\/call\/\?id=([a-z0-9-]+)">The whole call/)[1];
  const call = C.findCall(BODY, id);
  assert.equal(call.verdict, "wrong", "the front page leads with a miss");
  const when = new Date(`${call.settled_date}T12:00:00Z`).toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", timeZone: "UTC" });
  assert.ok(html.startsWith(`<div class="ck-bet"><p class="ck-small">Settled ${when}</p>`));
  // #4808, the house rule: the tag (verdict and rule) first, then the call with the RESULT bold,
  // then what the allowed distance is — the number once, in the tag
  assert.ok(html.includes(`<span class="ck-verdicts__tag">Wrong · not within ${call.tolerance.text}% either way</span><p>${V.matthewsCall(call.called)} <b>${call.happened_short}</b></p>`));
  assert.ok(html.includes(`<p class="ck-soft">The allowed distance is ${call.tolerance.statistic}. `), "the card says what counts as right");
  assert.equal((html.match(new RegExp(call.tolerance.text.replace(".", "\\."), "g")) || []).length, 1, "the allowed distance is printed once");
  const scored = call.simple_guess && call.simple_guess.state === "scored" && call.simple_guess.short;
  // Round 2: the guess is named when its served sentence says which one it is.
  const which = /the last reading before the call/.test(String((call.simple_guess && call.simple_guess.text) || "")) ? "A guess that nothing changes from the last reading" : "The simple guess";
  if (scored) assert.ok(html.includes(`${which}: ${call.simple_guess.short}.`));
  else assert.doesNotMatch(html, /simple guess|A guess that/, "the guess is said only once it has a result on this call");
  assert.match(html, /href="\/next\/v8\/call\/\?id=[a-z0-9-]+">The whole call<\/a>/);
  assert.doesNotMatch(html, /\d{4}-\d{2}-\d{2}|undefined|\d+% (of|chance)/);
});

test("the last settled call is nothing at all when the route is not served or empty", () => {
  assert.equal(C.lastCallHTML(null, BASE), "");
  assert.equal(C.lastCallHTML({}, BASE), "");
  assert.equal(C.lastCallHTML({ state: "unavailable", calls: [], absent_text: C.NOT_SERVED }, BASE), "");
  assert.equal(C.lastCallHTML({ state: "absent", calls: [] }, BASE), "");
  assert.equal(C.lastCallHTML({ state: "ok", calls: [{ id: "x" }] }, BASE), "", "a call missing its sentences is not drawn");
});

test("a bet as the last settled call names who was right instead of one tag", () => {
  const html = C.lastCallHTML({ ...BODY, calls: [C.findCall(BODY, BET)] }, BASE);
  assert.match(html, /Settled Wednesday, September 30/);
  assert.match(html, /<p>Marcus Webb was right; Amara Patel was wrong\.<\/p>/);
});

test("what settles next is one sentence with its day in words", () => {
  // #4618: what settles next is whatever the route names, with its day in words (the weekday, then the date).
  const next = C.nextCallHTML(BODY);
  // The 2026-10-17 capture names nothing due next: then the sentence is not drawn.
  if (BODY.next && BODY.next.data) {
    assert.equal(next, `<p class="ck-soft">${BODY.next.data.text}</p>`);
    assert.match(next, /^<p class="ck-soft">Next: .+ settles [A-Z][a-z]+day, [A-Z][a-z]+ \d+\.<\/p>$/);
  } else assert.equal(next, "");
  assert.equal(C.nextCallHTML({ next: { state: "ok", data: { question: "Will it rain", due_date: "2026-10-21" } } }), '<p class="ck-soft">Next: Will it rain settles Wednesday, October 21.</p>');
  assert.equal(C.nextCallHTML(null), "");
  assert.equal(C.nextCallHTML({ next: { state: "absent", data: null, absent_text: "No call or bet has a settle date right now." } }), "");
  assert.equal(C.nextCallHTML({ next: { state: "ok", data: { question: "a call", due_date: "soon" } } }), "", "an unusable date draws nothing");
});

test("the list is every settled call newest first, the older ones folded away", () => {
  const html = C.listHTML(BODY, BASE);
  // Each row returns to this list by name (#4675).
  const hrefs = [...html.matchAll(/href="\/next\/v8\/call\/\?id=([a-z0-9-]+)&amp;from=calls"/g)].map((m) => m[1]);
  assert.deepEqual(hrefs, BODY.calls.map((c) => c.id));
  assert.ok(hrefs.length > 0 && hrefs.length === BODY.calls.length, "every served call has its row");
  assert.match(html, /^<ul class="ck-rows ck-rows--more ck-rows--calls"><li><a href="[^"]+">[A-Z][a-z]+ \d+: [^<]+ <span>((Right|Wrong) · [^<]+|[^<]+ was right; [^<]+ was wrong\.)<\/span><\/a><\/li>/);
  const folded = Number(html.match(/<details><summary>(\d+) earlier calls<\/summary>/)[1]);
  assert.ok(folded > 0 && folded < hrefs.length, "the older calls are folded, the newest stay open");
  const bet = BODY.calls.find((c) => c.kind === "bet");
  assert.ok(html.includes(`<span>${bet.verdict_text}</span>`), "a bet row says who was right");
  assert.ok(html.includes(`${BODY.excluded.count} more checked calls have no page here`));
  assert.equal(C.listHTML(null, BASE), "");
});

test("each page names itself from the call", () => {
  const meta = C.metaFor(C.findCall(BODY, NUMBER));
  assert.equal(meta.title, "Lisa Park called his morning recovery score at about 61: right — Average Joe Matt");
  assert.equal(meta.description, "Lisa Park called his morning recovery score at about 61. It came in at 67. Right · within 17.9% either way.");
  assert.equal(C.metaFor(C.findCall(BODY, BET)).description, "Marcus Webb and Amara Patel bet on whether his morning recovery score would be below 70 on September 30. It came in at 59. Marcus Webb was right; Amara Patel was wrong.");
  assert.equal(C.metaFor(null).title, "A coach’s call, checked — Average Joe Matt");
});

// Where Back goes (`from=`, by name, else the front page) is one rule for every deep page
// since #4675: tests/js/ck_deep_links_4675.test.mjs.

test("no coach on any call page carries an honorific, and no sentence a count of earlier starts", () => {
  const all = BODY.calls.map((c) => C.claimHTML(c) + C.outcomeHTML(c) + C.recordHTML(c, BODY)).join("") + C.listHTML(BODY, BASE);
  assert.doesNotMatch(all, /\bDr\.\s/);
  assert.doesNotMatch(all, /\bcycle \d|\bundefined\b|\bNaN\b/);
});
