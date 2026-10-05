// tests/js/ck_verdict_4647.test.mjs — #4647: no "Right" or "Wrong" on a preview page without
// the rule that decided it. Driven from tests/fixtures/kit_pages_4586/, the served bodies
// the page gate renders; no builder reads the wall clock.
//
// Two holds. (1) Every builder that prints a verdict is run on the fixtures and every tag it
// emits must carry a rule. (2) No kit module other than ck_verdict.js may write the tag's
// class at all, so a page cannot hand-build one. Mutation run on 2026-10-04: restoring the
// old bare `<span class="ck-verdicts__tag">Wrong</span>` in ck_call.js failed both.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const V = await import("../../site/assets/js/ck_verdict.js");
const C = await import("../../site/assets/js/ck_call.js");
const P = await import("../../site/assets/js/ck_pages.js");
const K = await import("../../site/assets/js/ck_coach.js");
const HERE = dirname(fileURLToPath(import.meta.url));
const FIX = join(HERE, "..", "fixtures", "kit_pages_4586");
const JS = join(HERE, "..", "..", "site", "assets", "js");
const load = (name) => JSON.parse(readFileSync(join(FIX, `${name}.json`), "utf8"));
const BODY = load("calls");
const BASE = "/next/v8/";
const clone = (v) => JSON.parse(JSON.stringify(v));
const byId = (id) => BODY.calls.find((c) => c.id === id);

// A verdict tag is bare when it says right or wrong and nothing after it. A rule is at
// least " · " and three more characters.
const TAG = /<span class="ck-verdicts__tag[^"]*">([^<]*)<\/span>/g;
const VERDICT = /\b(right|wrong)\b/i;
const RULED = /\b(Right|Wrong|right|wrong) · \S.{2,}$/;
function bareTags(html) {
  const bare = [];
  for (const m of String(html).matchAll(TAG)) if (VERDICT.test(m[1]) && !RULED.test(m[1])) bare.push(m[0]);
  return bare;
}
// A list row's verdict is a plain span at the end of its link.
function bareRows(html) {
  return [...String(html).matchAll(/<span>([^<]*)<\/span><\/a><\/li>/g)].filter((m) => /^(Right|Wrong)\.?$/.test(m[1].trim())).map((m) => m[0]);
}

test("the rule is lifted from the served sentence, per kind of call", () => {
  const number = byId("explorer-20260919-aecd9fef2c");
  assert.equal(V.toleranceText(number), "22.5");
  assert.equal(V.ruleFor(number, true), "within 22.5 either way");
  assert.equal(V.ruleFor(byId("mind-20260914-7fc4b43947"), false), "not within 18.6 either way");
  assert.equal(V.ruleFor(byId("sleep-20260925-6c64d91f26"), true), "within 1.2 hours either way", "the unit travels with the number");
  assert.equal(V.ruleFor(byId("labs-20260906-d2deb9b27d"), true), "by the trend in his most recent readings");
  assert.equal(V.ruleFor(byId("bet-20260930-994b3d89f6"), true), "on whether his morning recovery score would be below 70 on September 30");
  const mute = { ...clone(number), called: "Henning Brandt called it." };
  assert.equal(V.ruleFor(mute, true), "", "a sentence with no rule yields none, never a guess");
  assert.equal(V.ruleFor(null, true), "");
});

test("a verdict is never the bare word: with no rule it is a sentence that says so, not a tag", () => {
  assert.equal(V.verdictTag(true, "within 22.5 either way"), '<span class="ck-verdicts__tag ck-verdicts__tag--right">Right · within 22.5 either way</span>');
  assert.equal(V.verdictTag(false, "not within 18.6 either way"), '<span class="ck-verdicts__tag">Wrong · not within 18.6 either way</span>');
  for (const rule of ["", "   ", null, undefined]) {
    const html = V.verdictTag(true, rule);
    assert.doesNotMatch(html, /ck-verdicts__tag/);
    assert.match(html, /Marked right\. The rule that decided it is not available for this call\./);
  }
  assert.match(V.verdictTag(false, "", "The simple guess"), /The simple guess was marked wrong\. The rule that decided it is not available/);
  assert.equal(V.cardLabel("The simple guess"), '<span class="ck-verdicts__tag">The simple guess</span>');
  assert.equal(V.cardLabel("Right"), "", "a card heading cannot be used to print a verdict");
  assert.equal(V.cardLabel("The simple guess: wrong"), "");
});

test("no builder on any preview page emits a verdict tag without its rule", () => {
  const coaches = load("coaches");
  const out = [];
  for (const call of C.callsOf(BODY)) {
    out.push(C.outcomeHTML(call), C.lastCallHTML({ ...BODY, calls: [call] }, BASE));
    // the simple guess, once it is checked, is a verdict too
    for (const right of [true, false]) out.push(C.outcomeHTML({ ...clone(call), simple_guess: { state: "scored", right, text: "The simple guess was that nothing would change.", short: right ? "right" : "wrong" } }));
    // a call whose sentence carries no rule must not fall back to the bare word
    out.push(C.outcomeHTML({ ...clone(call), called: "A call." }), C.lastCallHTML({ ...BODY, calls: [{ ...clone(call), called: "A call." }] }, BASE));
  }
  out.push(C.listHTML(BODY, BASE), P.callVerdictsHTML(BODY, BASE), P.verdictsHTML(coaches));
  out.push(P.callVerdictsHTML({ calls: BODY.calls.map((c) => ({ ...clone(c), called: "A call." })) }, BASE));
  for (const name of ["coach_sleep_coach", "coach_physical_coach", "coach_glucose_coach", "coach_mind_coach", "coach_eli_marsh"]) out.push(K.verdictsHTML(load(name)));
  const html = out.join("\n");
  assert.ok((html.match(TAG) || []).length > 100, "the sweep saw the tags it is here to check");
  assert.deepEqual(bareTags(html), []);
  assert.deepEqual(bareRows(html), []);
  // the check can fail: the old markup is caught
  assert.equal(bareTags('<span class="ck-verdicts__tag ck-verdicts__tag--right">Right</span>').length, 1);
  assert.equal(bareTags('<span class="ck-verdicts__tag">The simple guess: wrong</span>').length, 1);
  assert.equal(bareRows("<li><a href=\"/x\">October 3: A call. <span>Right</span></a></li>").length, 1);
});

test("every row of the call list says the rule beside the verdict", () => {
  const rows = [...C.listHTML(BODY, BASE).matchAll(/<span>([^<]*)<\/span><\/a><\/li>/g)].map((m) => m[1]);
  assert.equal(rows.length, C.callsOf(BODY).length);
  for (const text of rows) assert.match(text, / · (within|not within|by the trend) |was right; .* was wrong\./, text);
});

test("only ck_verdict.js writes the verdict tag: no page module hand-builds one", () => {
  const files = readdirSync(JS).filter((f) => /^ck_.*\.js$/.test(f) && f !== "ck_verdict.js");
  assert.ok(files.includes("ck_call.js") && files.includes("ck_pages.js") && files.includes("ck_coach.js"));
  const offenders = files.filter((f) => /ck-verdicts__tag/.test(readFileSync(join(JS, f), "utf8")));
  assert.deepEqual(offenders, []);
});

test("the pair is the tightest right call and the miss that landed furthest out", () => {
  const { right, wrong } = V.showcasePair(BODY.calls);
  assert.equal(right.id, "sleep-20260925-6c64d91f26", "1.2 hours on a call of 7.8 is the tightest rule among the right calls");
  assert.equal(wrong.id, "sleep-20260910-09aa1ff6cc", "66.2 called, 24 came in, 17.9 allowed");
  for (const c of BODY.calls.filter((x) => x.verdict === "right" && x.kind === "number")) assert.ok(V.tightness(c) >= V.tightness(right), c.id);
  for (const c of BODY.calls.filter((x) => x.verdict === "wrong" && x.kind === "number")) assert.ok(V.missBy(c) <= V.missBy(wrong), c.id);
  assert.ok(V.missBy(right) <= 1 && V.missBy(wrong) > 1, "the served numbers agree with the served verdicts");
  // no number call of a kind: the newest call of that kind stands in, and a bet never does
  const directions = BODY.calls.filter((c) => c.kind !== "number");
  assert.equal(V.showcasePair(directions).right.kind, "direction");
  assert.deepEqual(V.showcasePair([byId("bet-20260930-994b3d89f6")]), { right: null, wrong: null });
  assert.deepEqual(V.showcasePair(null), { right: null, wrong: null });
});

test("the call page states the day whose reading the call was graded on, from the served sentence only", () => {
  const number = byId("explorer-20260919-aecd9fef2c");
  assert.equal(V.measuredDay(number), "September 20");
  assert.equal(V.gradedOnText(number), "Graded on the reading for September 20.");
  assert.match(C.outcomeHTML(number), /Henning Brandt was right\. Graded on the reading for September 20\. Checked October 3\./);
  assert.equal(V.measuredDay(byId("bet-20260930-994b3d89f6")), "September 30");
  const direction = byId("labs-20260906-d2deb9b27d");
  assert.equal(V.measuredDay(direction), "", "a direction call is graded on a trend, not one day");
  assert.equal(V.gradedOnText(direction), "Graded on the trend in his most recent readings.");
  // a sentence that names no day prints no day: nothing is worked out from the other dates
  const mute = { ...clone(number), called: "Henning Brandt called it at about 83.7." };
  assert.equal(V.gradedOnText(mute), "");
  assert.match(C.outcomeHTML(mute), /Henning Brandt was right\. Checked October 3\./);
  for (const call of BODY.calls) assert.ok(V.gradedOnText(call), `${call.id} says what it was graded on`);
});
