// tests/js/ck_deep_links_4675.test.mjs — #4675: the preview's deep pages link to each other
// both ways. A coach page's right and wrong cards open the call's page; a call page opens
// its coach's page and the day it was graded on; and every deep page's back link returns to
// the page named by `from=`, by name, falling back to the front page without one.
//
// Driven from the committed live captures in tests/fixtures/kit_pages_4586/ (GET /api/calls
// and GET /api/coach/sleep_coach, one capture, #4671).
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const CALL = await import("../../site/assets/js/ck_call.js");
const COACH = await import("../../site/assets/js/ck_coach.js");
const DEPTH = await import("../../site/assets/js/ck_depth.js");
const PAGES = await import("../../site/assets/js/ck_pages.js");
const FIX = join(dirname(fileURLToPath(import.meta.url)), "..", "fixtures", "kit_pages_4586");
const load = (name) => JSON.parse(readFileSync(join(FIX, `${name}.json`), "utf8"));
const BODY = load("calls");
const SLEEP = load("coach_sleep_coach");
const BASE = "/next/v8/";
const NUMBER = "sleep-20260907-8436f03290"; // "… at about 61 for September 8.", settled September 21
const BET = "bet-20260930-994b3d89f6";
const hrefs = (html) => [...html.matchAll(/href="([^"]+)"/g)].map((m) => m[1].replace(/&amp;/g, "&"));

// ── acceptance 1: each right/wrong card on a coach page links to that call's page ──
test("each right and wrong card on a coach page opens that call's page, which returns to the coach", () => {
  const html = COACH.verdictsHTML(SLEEP, BODY, BASE);
  const cards = html.split("</div><div>");
  assert.equal(cards.length, 2, "one right card and one wrong card");
  const right = BODY.calls.find((c) => c.coach_id === "sleep" && c.kind !== "bet" && c.verdict === "right");
  const wrong = BODY.calls.find((c) => c.coach_id === "sleep" && c.kind !== "bet" && c.verdict === "wrong");
  assert.deepEqual(hrefs(cards[0]), [`/next/v8/call/?id=${right.id}&from=coach%3Asleep_coach`]);
  assert.deepEqual(hrefs(cards[1]), [`/next/v8/call/?id=${wrong.id}&from=coach%3Asleep_coach`]);
  assert.match(cards[0], /ck-verdicts__tag--right">Right · within [^<]+<\/span>/);
  assert.match(cards[1], /<span class="ck-verdicts__tag">Wrong · not within [^<]+<\/span>/);
  assert.ok(cards[0].includes(right.called_short) && cards[1].includes(wrong.called_short), "each card says the call it opens");
  // Another coach's calls never stand in for this coach's.
  for (const h of hrefs(html)) assert.match(h, /id=sleep-/);
});

test("with no paged call served, the coach page keeps the record's own lines, and draws nothing new", () => {
  const without = COACH.verdictsHTML(SLEEP);
  assert.equal(without, COACH.verdictsHTML(SLEEP, { state: "unavailable", calls: [] }, BASE));
  assert.doesNotMatch(without, /call\/\?id=/);
  assert.match(without, /ck-verdicts/);
});

// ── acceptance 2: a call page links the coach's name and the graded day ──────────
test("a call page links the coach's name to the coach page, and the graded day to its day page", () => {
  const call = CALL.findCall(BODY, NUMBER);
  const claim = CALL.claimHTML(call, BASE);
  assert.ok(claim.includes(`<a class="ck-link" href="/next/v8/coach/?c=sleep_coach&amp;from=call%3A${NUMBER}">Lisa Park</a> · logged September 7`), claim);
  assert.equal(CALL.gradedDayISO(call), "2026-09-08");
  const out = CALL.outcomeHTML(call, BASE);
  assert.ok(out.includes(`Graded on the reading for <a class="ck-link" href="/next/v8/day/?d=2026-09-08&amp;from=call%3A${NUMBER}">September 8</a>. Checked September 21.`), out);
  // Without a base the builders print the same words with no links (the front page's use).
  assert.doesNotMatch(CALL.claimHTML(call) + CALL.outcomeHTML(call), /<a /);
});

test("a bet links both coaches and the day its question named", () => {
  const bet = CALL.findCall(BODY, BET);
  const claim = CALL.claimHTML(bet, BASE);
  assert.ok(claim.includes(`href="/next/v8/coach/?c=nutrition_coach&amp;from=call%3A${BET}">Marcus Webb</a> said yes`), claim);
  assert.ok(claim.includes(`href="/next/v8/coach/?c=glucose_coach&amp;from=call%3A${BET}">Amara Patel</a> said no`), claim);
  assert.match(CALL.outcomeHTML(bet, BASE), /Graded on the reading for <a class="ck-link" href="\/next\/v8\/day\/\?d=2026-09-30&amp;from=call%3Abet-20260930-994b3d89f6">September 30<\/a>\./);
});

test("a call graded on a trend names no day, so no day is linked", () => {
  const trend = BODY.calls.find((c) => c.kind === "direction");
  assert.equal(CALL.gradedDayISO(trend), "");
  assert.doesNotMatch(CALL.outcomeHTML(trend, BASE), /day\/\?d=/);
});

test("a graded day named without a year takes the year it was checked in, never a day after the check", () => {
  const dec = { kind: "number", called: "X called his weight at about 300 for December 31.", settled_date: "2027-01-02" };
  assert.equal(CALL.gradedDayISO(dec), "2026-12-31");
  assert.equal(CALL.gradedDayISO({ ...dec, called: "X called his weight at about 300 for February 30." }), "", "not a real day");
  assert.equal(CALL.gradedDayISO({ ...dec, settled_date: "" }), "");
});

// ── acceptance 3: `from=` names the back link; without it, the front page ────────
test("a deep page opened with from= shows a back link to that page, by name", () => {
  assert.deepEqual(CALL.backFor("2026-09-08", BASE), { href: "/next/v8/day/?d=2026-09-08", text: "← Tuesday, September 8" });
  assert.deepEqual(CALL.backFor(`call:${NUMBER}`, BASE), { href: `/next/v8/call/?id=${NUMBER}`, text: "← The call" });
  assert.deepEqual(CALL.backFor("coach:sleep_coach", BASE, { sleep_coach: "Lisa Park" }), { href: "/next/v8/coach/?c=sleep_coach", text: "← Lisa Park" });
  assert.deepEqual(CALL.backFor("coach:sleep_coach", BASE), { href: "/next/v8/coach/?c=sleep_coach", text: "← The coach" }, "before the name is served");
  assert.deepEqual(CALL.backFor("calls", BASE), { href: "/next/v8/call/", text: "← Every settled call" });
  assert.deepEqual(CALL.backFor("coaches", BASE), { href: "/next/v8/coaches/", text: "← The AI coaches" });
  // The names a call page has come from the served calls themselves.
  assert.equal(CALL.backFor("coach:glucose_coach", BASE, CALL.callNames(BODY)).text, "← Amara Patel");
});

test("without from=, or with anything outside the closed set, the back link is the front page", () => {
  const front = { href: BASE, text: "← Average Joe Matt" };
  for (const hostile of ["", null, undefined, "https://evil.example/", "//evil.example", "javascript:alert(1)", "call:../x", "coach:Sleep", "coach:__proto__x/", "2026-02-30", "constructor", "__proto__", "toString", "calls/"]) {
    assert.deepEqual(CALL.backFor(hostile, BASE), front, String(hostile));
  }
  assert.deepEqual(CALL.backFor("coach:sleep_coach", BASE, { toString: "x" }).text, "← The coach");
});

test("the links into a deep page carry from=, so the page they open can return", () => {
  assert.equal(CALL.withFrom("/next/v8/call/?id=x", "coaches"), "/next/v8/call/?id=x&from=coaches");
  assert.equal(CALL.withFrom("/next/v8/call/", "calls"), "/next/v8/call/?from=calls");
  assert.equal(CALL.withFrom("/next/v8/call/?id=x", ""), "/next/v8/call/?id=x");
  // The settled-call list, the Coaches page and a day page each say where they are.
  assert.ok(hrefs(CALL.listHTML(BODY, BASE)).every((h) => h.endsWith("&from=calls")));
  const team = PAGES.teamHTML(load("coaches"), BASE, "coaches");
  assert.ok(hrefs(team).length > 0 && hrefs(team).every((h) => /\/coach\/\?c=[a-z_]+&from=coaches$/.test(h)), team);
  assert.ok(hrefs(PAGES.callVerdictsHTML(BODY, BASE, "coaches")).every((h) => h.endsWith("&from=coaches")));
  const day = DEPTH.daySettledHTML("2026-09-24", BODY, BASE);
  assert.ok(hrefs(day).length > 0 && hrefs(day).every((h) => h.endsWith("&from=2026-09-24")));
});

// The shells: every deep page's back link has the id the mount points, and its static
// fallback (what a reader sees before scripts run, or without from=) is the front page.
test("every deep page shell's back link starts at the front page, ready to be pointed", () => {
  const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "site", "next", "v8");
  for (const page of ["coach", "call", "day", "trend"]) {
    const html = readFileSync(join(root, page, "index.html"), "utf8");
    assert.match(html, /<a class="ck-header__back" id="ck-back" href="\/next\/v8\/">← Average Joe Matt<\/a>/, page);
  }
});
