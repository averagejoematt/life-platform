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
  assert.match(html, /his morning recovery score \(his wrist strap’s morning score out of 100\) at about 61 for September 8\./);
  const sealed = C.claimHTML(C.callsOf(BODY).find((c) => c.sealed));
  assert.match(sealed, / · sealed September 5, before day one<\/p>/);
});

test("what happened carries the verdict as the kit's tag, beside the simple guess", () => {
  const right = C.outcomeHTML(C.findCall(BODY, NUMBER));
  assert.match(right, /<span class="ck-verdicts__tag ck-verdicts__tag--right">Right · within 17\.9 either way<\/span><p><b>Morning recovery score came in at 67 against a call of 61/);
  assert.match(right, /Lisa Park was right\. Graded on the reading for September 8\. Checked September 21\./);
  assert.match(right, /<span class="ck-verdicts__tag">The simple guess<\/span><p>The simple guess, that nothing changes, has not been checked against this call yet\.<\/p>/);
  const wrong = C.outcomeHTML(C.callsOf(BODY).find((c) => c.verdict === "wrong"));
  assert.match(wrong, /<span class="ck-verdicts__tag">Wrong · not within 18\.6 either way<\/span>/);
});

test("a call the simple guess was checked on says what it said and whether it was right", () => {
  const call = clone(C.findCall(BODY, NUMBER));
  call.simple_guess = { state: "scored", right: true, text: "The simple guess was that it would stay at 62, the last reading before the call. That guess was also right.", short: "also right" };
  assert.match(C.outcomeHTML(call), /<span class="ck-verdicts__tag ck-verdicts__tag--right">The simple guess: right · within 17\.9 either way<\/span><p>The simple guess was that it would stay at 62/);
  call.simple_guess = { ...call.simple_guess, right: false, short: "wrong" };
  assert.match(C.outcomeHTML(call), /<span class="ck-verdicts__tag">The simple guess: wrong · not within 17\.9 either way<\/span>/);
});

test("a bet shows both coaches' words and who was right", () => {
  const bet = C.findCall(BODY, BET);
  const claim = C.claimHTML(bet);
  assert.match(claim, /<p class="ck-small">A bet opened September 23<\/p>/);
  assert.match(claim, /Marcus Webb said yes: “Any carb reduction/);
  assert.match(claim, /Amara Patel said no: “Evening carb reduction/);
  const out = C.outcomeHTML(bet);
  assert.match(out, /ck-verdicts__tag--right">Right · on whether his morning recovery score would be below 70 on September 30<\/span><p><b>Marcus Webb said yes\.<\/b>/);
  assert.match(out, /<span class="ck-verdicts__tag">Wrong · on whether his morning recovery score would be below 70 on September 30<\/span><p><b>Amara Patel said no\.<\/b>/);
  assert.match(out, /It came in at 59\. Graded on the reading for September 30\. Checked September 30\./);
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
  assert.match(html, /<p>Lisa Park: 15 of 35 checked calls right\.<\/p><p class="ck-soft" data-coach-comparison>Across 35 checked calls, so far they do not beat a simple guess\.<\/p>/);
  const bare = clone(C.findCall(BODY, NUMBER));
  bare.records[0].comparison = null;
  assert.match(C.recordHTML(bare, BODY), /What a simple guess would have scored on these calls is not available right now\./, "a count never stands alone");
  assert.match(html, /The record counts every checked call, including the ones with no page of their own\./);
  assert.doesNotMatch(html, /%/);
  const both = C.recordHTML(C.findCall(BODY, BET), BODY);
  assert.match(both, /Marcus Webb: 7 of 28 checked calls right\..*Amara Patel: 2 of 6 checked calls right\./);
});

test("the front page's last settled call is one block that opens its page", () => {
  // It leads with the clearest miss on record, not the newest call (red team, round 7).
  const html = C.lastCallHTML(BODY, BASE);
  assert.match(html, /^<div class="ck-bet"><p class="ck-small">Settled Thursday, September 24<\/p>/);
  assert.match(html, /<b>Lisa Park called his morning recovery score \(his wrist strap’s morning score out of 100\) at about 66\.2 for September 11\. A call like this counts as right within 17\.9 either way, his usual day-to-day swing\.<\/b> It came in at 24\./, "the card says which day the call was for and what counts as right");
  assert.match(html, /<span class="ck-verdicts__tag">Wrong · not within 17\.9 either way<\/span>/);
  assert.doesNotMatch(html, /The simple guess/, "the guess is said only once it has a result on this call");
  assert.match(html, /href="\/next\/v8\/call\/\?id=[a-z0-9-]+">The whole call<\/a>/);
  assert.doesNotMatch(html, /\d{4}-\d{2}-\d{2}|undefined|%/);
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
  assert.equal(
    C.nextCallHTML(BODY),
    // #4618: a next-day number call is due the day its sentence names, so it is what settles next.
    '<p class="ck-soft">Next: Henning Brandt’s call that his weight will be about 307.2 lb settles Friday, October 9.</p>',
  );
  assert.equal(C.nextCallHTML(null), "");
  assert.equal(C.nextCallHTML({ next: { state: "absent", data: null, absent_text: "No call or bet has a settle date right now." } }), "");
  assert.equal(C.nextCallHTML({ next: { state: "ok", data: { question: "a call", due_date: "soon" } } }), "", "an unusable date draws nothing");
});

test("the list is every settled call newest first, the older ones folded away", () => {
  const html = C.listHTML(BODY, BASE);
  const hrefs = [...html.matchAll(/href="\/next\/v8\/call\/\?id=([a-z0-9-]+)"/g)].map((m) => m[1]);
  assert.deepEqual(hrefs, BODY.calls.map((c) => c.id));
  assert.equal(hrefs.length, 39);
  assert.match(html, /^<ul class="ck-rows ck-rows--more ck-rows--calls"><li><a href="[^"]+">October 9: Lisa Park called his morning recovery score at about 89\.1\. <span>Right · within 21\.5 either way<\/span><\/a><\/li>/);
  assert.match(html, /<details><summary>31 earlier calls<\/summary>/);
  assert.match(html, /<span>Marcus Webb was right; Amara Patel was wrong\.<\/span>/, "a bet row says who was right");
  assert.match(html, /89 more checked calls have no page here/);
  assert.equal(C.listHTML(null, BASE), "");
});

test("each page names itself from the call", () => {
  const meta = C.metaFor(C.findCall(BODY, NUMBER));
  assert.equal(meta.title, "Lisa Park called his morning recovery score at about 61: right — Average Joe Matt");
  assert.equal(meta.description, "Lisa Park called his morning recovery score at about 61. It came in at 67. Right · within 17.9 either way.");
  assert.equal(C.metaFor(C.findCall(BODY, BET)).description, "Marcus Webb and Amara Patel bet on whether his morning recovery score would be below 70 on September 30. It came in at 59. Marcus Webb was right; Amara Patel was wrong.");
  assert.equal(C.metaFor(null).title, "A coach’s call, checked — Average Joe Matt");
});

test("Back returns where the reader came from on this site, else the front page", () => {
  const origin = "https://averagejoematt.com";
  assert.deepEqual(C.backTarget(`${origin}/next/v8/coaches/?x=1`, origin, BASE), { href: "/next/v8/coaches/?x=1", text: "← Back" });
  assert.deepEqual(C.backTarget("https://news.ycombinator.com/item?id=1", origin, BASE), { href: BASE, text: "← Average Joe Matt" });
  assert.deepEqual(C.backTarget("", origin, BASE), { href: BASE, text: "← Average Joe Matt" });
  assert.deepEqual(C.backTarget("javascript:alert(1)", origin, BASE), { href: BASE, text: "← Average Joe Matt" });
});

test("no coach on any call page carries an honorific, and no sentence a count of earlier starts", () => {
  const all = BODY.calls.map((c) => C.claimHTML(c) + C.outcomeHTML(c) + C.recordHTML(c, BODY)).join("") + C.listHTML(BODY, BASE);
  assert.doesNotMatch(all, /\bDr\.\s/);
  assert.doesNotMatch(all, /\bcycle \d|\bundefined\b|\bNaN\b/);
});
