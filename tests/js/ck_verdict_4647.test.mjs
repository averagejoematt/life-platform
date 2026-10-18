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
// The direction call in the capture, with the sentence the route served before #4617: graded against the trend in
// his most recent readings, no allowed-distance band. Built from the capture (it now serves the window shape).
function legacyTrend() {
  const c = clone(byId("labs-20260906-d2deb9b27d"));
  const who = c.called.split(" called ")[0];
  return { ...c, called: `${who} called his resting heart rate to go down, in a prediction sealed before day one. It was checked on September 27 against the trend in his most recent readings.`, tolerance: null };
}
function bareRows(html) {
  return [...String(html).matchAll(/<span>([^<]*)<\/span><\/a><\/li>/g)].filter((m) => /^(Right|Wrong)\.?$/.test(m[1].trim())).map((m) => m[0]);
}

test("the rule is lifted from the served sentence, per kind of call", () => {
  const number = byId("explorer-20260919-aecd9fef2c");
  assert.equal(V.toleranceText(number), "22.5");
  // Re-grade 2026-10-18: recovery is "out of 100" on every kit page (the served unit), so its bare distance is too.
  assert.equal(V.ruleFor(number, true), "within 22.5 out of 100 either way", "a score's bare allowed distance takes the score's unit (out of 100, as served — re-grade 2026-10-18)");
  assert.equal(V.ruleFor(byId("mind-20260914-7fc4b43947"), false), "not within 18.6 out of 100 either way");
  // A served unit (lane E of #4580: `tolerance.unit`, then the call's `unit`) wins over the sentence's measure.
  assert.equal(V.ruleFor({ ...number, tolerance: { ...number.tolerance, unit: "points" } }, true), "within 22.5 points either way");
  assert.equal(V.ruleFor({ ...number, unit: "lb" }, true), "within 22.5 lb either way");
  assert.equal(V.ruleFor(byId("sleep-20260925-6c64d91f26"), true), "within 1.2 hours either way", "the unit travels with the number");
  // The capture's direction call is graded across its own window (#4617); the legacy trend sentence is built from it.
  assert.match(V.ruleFor(byId("labs-20260906-d2deb9b27d"), true), /^by the change from [A-Z][a-z]+ \d+ to [A-Z][a-z]+ \d+$/);
  assert.equal(V.ruleFor(legacyTrend(), true), "by the trend in his most recent readings");
  // Lane E of #4580 (deployed 2026-10-18): the served bet sentence carries the score's unit.
  assert.equal(V.ruleFor(byId("bet-20260930-994b3d89f6"), true), "on whether his morning recovery score would be below 70 out of 100 on September 30");
  const mute = { ...clone(number), called: "Henning Brandt called it.", tolerance: null };
  assert.equal(V.ruleFor(mute, true), "", "a call with no served rule yields none, never a guess");
  // #4808: the allowed distance is served once, in `tolerance`; a route from before it wrote the
  // number into the sentence, and that is still read when `tolerance` is absent.
  assert.equal(number.tolerance.text, "22.5");
  assert.doesNotMatch(number.called, /either way/, "the sentence no longer carries it");
  // `actual.unit` is served since lane E and is read as the call's unit (re-grade 2026-10-18), so the unitless case drops it too.
  const old = { ...clone(number), tolerance: undefined, actual: { ...number.actual, unit: undefined }, called: "Henning Brandt called it at about 83.7. A call like this counts as right within 22.5 either way, his usual day-to-day swing." };
  assert.equal(V.ruleFor(old, true), "within the allowed distance", "a bare number on a measure with no known unit is never printed unitless");
  assert.equal(V.ruleFor(null, true), "");
});

test("a verdict is never the bare word, and with no rule there is no verdict at all (#4808)", () => {
  assert.equal(V.verdictTag(true, "within 22.5 either way"), '<span class="ck-verdicts__tag ck-verdicts__tag--right">Right · within 22.5 either way</span>');
  assert.equal(V.verdictTag(false, "not within 18.6 either way"), '<span class="ck-verdicts__tag">Wrong · not within 18.6 either way</span>');
  for (const rule of ["", "   ", null, undefined]) {
    // "Marked wrong. The rule that decided it is not available for this call." reached Marcus
    // Webb's page from here: a verdict a reader cannot check is not printed in any form.
    assert.equal(V.verdictTag(true, rule), "");
    assert.equal(V.verdictText(false, rule), "");
    assert.equal(V.verdictTag(false, rule, "The simple guess"), "");
  }
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
    out.push(C.outcomeHTML({ ...clone(call), called: "A call.", tolerance: null }), C.lastCallHTML({ ...BODY, calls: [{ ...clone(call), called: "A call.", tolerance: null }] }, BASE));
  }
  out.push(C.listHTML(BODY, BASE), P.callVerdictsHTML(BODY, BASE), P.verdictsHTML(coaches));
  out.push(P.callVerdictsHTML({ calls: BODY.calls.map((c) => ({ ...clone(c), called: "A call.", tolerance: null })) }, BASE));
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
  for (const text of rows) assert.match(text, / · (within|not within|by the trend|by the change) |was right; .* was wrong\./, text);
});

test("only ck_verdict.js writes the verdict tag: no page module hand-builds one", () => {
  const files = readdirSync(JS).filter((f) => /^ck_.*\.js$/.test(f) && f !== "ck_verdict.js");
  assert.ok(files.includes("ck_call.js") && files.includes("ck_pages.js") && files.includes("ck_coach.js"));
  const offenders = files.filter((f) => /ck-verdicts__tag/.test(readFileSync(join(JS, f), "utf8")));
  assert.deepEqual(offenders, []);
});

test("the pair is the tightest right call and the miss that landed furthest out", () => {
  const { right, wrong } = V.showcasePair(BODY.calls);
  assert.equal(right.verdict, "right");
  assert.equal(wrong.verdict, "wrong");
  assert.equal(right.kind, "number");
  assert.equal(wrong.kind, "number");
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
  assert.match(C.outcomeHTML(number), /<p class="ck-soft">The allowed distance is one standard deviation of his readings over the 30 days before the call\. Graded on the reading for September 20\.( The simple guess was also right\.)?<\/p>/);
  assert.equal(V.measuredDay(byId("bet-20260930-994b3d89f6")), "September 30");
  const direction = byId("labs-20260906-d2deb9b27d");
  assert.equal(V.measuredDay(direction), "", "a direction call is graded on a trend, not one day");
  assert.match(V.gradedOnText(direction), /^Graded on the readings from [A-Z][a-z]+ \d+ to [A-Z][a-z]+ \d+\.$/);
  assert.equal(V.gradedOnText(legacyTrend()), "Graded on the trend in his most recent readings.");
  // a sentence that names no day prints no day: nothing is worked out from the other dates
  const mute = { ...clone(number), called: "Henning Brandt called it at about 84." };
  assert.equal(V.gradedOnText(mute), "");
  assert.match(C.outcomeHTML(mute), /<p class="ck-soft">The allowed distance is [^.]+\.(<\/p>| The simple guess)/);
  for (const call of BODY.calls) assert.ok(V.gradedOnText(call), `${call.id} says what it was graded on`);
});


// ── #4808: one house rule for the verdict line ─────────────────────────────────────────────
// The four pages that print a graded call — the front page, the coaches page, a coach's page and
// a day page — draw it with ONE builder (callCardHTML), in one order: the tag (the verdict and the
// rule, the allowed distance said there and nowhere else), the call with the RESULT in bold, then
// one soft line naming what the allowed distance is. A call whose rule cannot be read is never a
// verdict on any of them. Mutation run 2026-10-11: restoring ck_pages' old card
// (`<p><b>${called_short}</b> ${happened_short}</p>`) failed "the four pages print the same call
// in one order"; restoring the "Marked wrong. The rule … is not available" branch in verdictText
// failed "a call with no rule is never a verdict".
const D = await import("../../site/assets/js/ck_depth.js");
const ORDER = /<span class="ck-verdicts__tag[^"]*">(Right|Wrong) · (not )?within ([^<]+) either way<\/span><p>([^<]+) <b>([^<]+)<\/b><\/p><p class="ck-soft">The allowed distance is ([^<.]+)\./;

function fourPages(call) {
  const body = { ...BODY, calls: [call] };
  // the coach's page with no record lines of its own, so its card for this call is the paged one
  const coachBody = { persona_id: `${call.coach_id}_coach`, name: call.coach_name };
  return {
    front: C.lastCallHTML(body, BASE),
    coaches: P.callVerdictsHTML(body, BASE, "coaches"),
    coach: K.verdictsHTML(coachBody, body, BASE),
    day: D.daySettledHTML(call.settled_date, body, BASE),
  };
}

test("the four pages print the same call in one order: the rule in the tag, the result bold, the allowed distance named once", () => {
  const recovery = BODY.calls.filter((c) => c.kind === "number" && /recovery score/.test(c.called_short));
  assert.ok(recovery.length >= 5, "the wire carries recovery-score calls");
  for (const call of recovery) {
    const pages = fourPages(call);
    for (const [page, html] of Object.entries(pages)) {
      const m = ORDER.exec(html);
      assert.ok(m, `${call.id} on the ${page} page is not in the house order:\n${html}`);
      assert.equal(m[1], call.verdict === "right" ? "Right" : "Wrong", `${page}: the tag is the call's verdict`);
      assert.equal(m[3], `${call.tolerance.text} out of 100`, `${page}: the tag carries the served allowed distance, with the score's unit`);
      assert.equal(m[5], call.happened_short, `${page}: the result is the bold part`);
      assert.equal(m[6], call.tolerance.statistic, `${page}: what the distance is, in the route's words`);
      assert.equal(html.split(`within ${call.tolerance.text} out of 100 either way`).length - 1, 1, `${page}: the allowed distance is printed once`);
      assert.doesNotMatch(html, /either way, his usual day-to-day swing|day-to-day swing/, `${page}: the old unnamed "swing"`);
      // a score out of 100 is a whole number on every page (#4808 box 2)
      // — unless the printed figures need a decimal for a reader's own check to agree with the
      // verdict (said_pair: 54.7 against 73 with 18.25 allowed), which the allowance's own second decimal shows
      if (!/\.\d{2,}/.test(call.tolerance.text)) assert.doesNotMatch(m[4], /at about \d+\.\d/, `${page}: ${m[4]}`);
    }
  }
});

test("a call with no rule is never a verdict on any page, and the pickers say how many they passed over", () => {
  const ruled = BODY.calls.filter((c) => c.kind === "number");
  const mute = (c) => ({ ...clone(c), called: c.called.replace(/ A call like this[^.]*\./, ""), tolerance: null });
  for (const call of ruled.slice(0, 6).map(mute)) {
    for (const [page, html] of Object.entries(fourPages(call))) {
      assert.doesNotMatch(html, /\b(Right|Wrong)\b|was (right|wrong)|Marked (right|wrong)|not available for this call/, `${page}: ${html}`);
    }
    assert.match(C.outcomeHTML(call), /The rule this call was checked by is not served, so it is not shown as right or wrong\./);
    assert.doesNotMatch(C.outcomeHTML(call), /ck-verdicts__tag[^"]*">(Right|Wrong)|was (right|wrong)\./);
  }
  // the coaches page's pair passes over them and counts them
  const mixed = { ...BODY, calls: BODY.calls.map((c, i) => (c.kind === "number" && i % 2 ? mute(c) : c)) };
  const n = mixed.calls.filter((c) => c.kind === "number" && !V.hasRule(c)).length;
  assert.ok(n > 1);
  assert.match(P.callVerdictsHTML(mixed, BASE), new RegExp(`${n} settled calls have no rule the page can print, so they are not shown as right or wrong here\\.`));
  assert.equal(V.ruleless(0), "");
  assert.equal(V.ruleless(1), "One settled call has no rule the page can print, so it is not shown as right or wrong here.");
});

test("Marcus Webb's page: a checked call whose rule the record line cannot read is passed over and counted", () => {
  // GET /api/coach/nutrition_coach as the live site served it on 2026-10-11 (read-only), the page
  // round 8 found "Marked wrong. The rule that decided it is not available for this call." on.
  const marcus = JSON.parse(readFileSync(join(HERE, "..", "fixtures", "verdict_house_rule_4808", "coach_nutrition_coach.json"), "utf8"));
  assert.equal(marcus.name, "Marcus Webb");
  const html = K.verdictsHTML(marcus, { state: "ok", calls: [] }, BASE);
  assert.doesNotMatch(html, /not available for this call|Marked (right|wrong)/);
  const { skipped } = K.verdictPair(marcus);
  assert.ok(skipped >= 1, "the fixture holds a line with no readable rule");
  assert.match(html, /settled calls? (has|have) no rule the page can print/);
});

test("a coach page whose two cards both open a call page says nothing about record lines it never shows", () => {
  // Lisa Park's page (kit capture): both cards are paged calls, so the record's own lines are
  // never read — one of them having no readable rule is not something this page held back.
  const lisa = load("coach_sleep_coach");
  const paged = K.pagedPair(lisa, BODY);
  assert.ok(paged.right && paged.wrong, "the capture pages both sides");
  const html = K.verdictsHTML(lisa, BODY, BASE);
  assert.doesNotMatch(html, /no rule the page can print/);
  assert.match(html, /Each allowed distance is /, "the shared allowed-distance line still prints once");
  // with no paged call the record's lines are read, and the one passed over is counted
  if (K.verdictPair(lisa).skipped > 0) assert.match(K.verdictsHTML(lisa, { state: "ok", calls: [] }, BASE), /no rule the page can print/);
});

test("a direction call graded across its own window (#4617) has a rule, and its band is said once with what it is", () => {
  const base = legacyTrend();
  const call = {
    ...base,
    verdict: "wrong",
    called: "Max Reyes called his weight to go down, in a prediction sealed before day one. It was checked on the change from the first reading of its window, September 6, to the last, September 20.",
    happened: "Weight held flat, from 319.5 lb on September 6 to 319.5 lb on September 20 — the call was for it to go down.",
    happened_short: "It held flat.",
    tolerance: { value: 1.0, text: "1 lb", statistic: "the median day-to-day change of his readings inside the window", window_days: null, n: 15 },
  };
  assert.equal(V.ruleFor(call, false), "by the change from September 6 to September 20");
  assert.equal(V.gradedOnText(call), "Graded on the readings from September 6 to September 20.");
  assert.equal(V.toleranceNote(call), "It counted as a move only beyond 1 lb either way, the median day-to-day change of his readings inside the window.");
  const card = V.callCardHTML(call);
  assert.match(card, /^<div><span class="ck-verdicts__tag">Wrong · by the change from September 6 to September 20<\/span><p>[^<]+ <b>It held flat\.<\/b><\/p>/);
  assert.equal(card.split("1 lb").length - 1, 1, "the band is printed once");
  // the legacy trend sentence still reads as before
  assert.equal(V.ruleFor(base, true), "by the trend in his most recent readings");
});

// Red team 2026-10-17: "not within 17.3 either way" had no unit. A served text with its unit keeps it;
// a bare number takes the unit of the score its sentence names; with neither, no number is printed.
test("every miss card's allowed distance carries a unit, or no number at all", () => {
  const recovery = BODY.calls.find((c) => c.kind === "number" && /recovery score/.test(c.called) && c.verdict === "wrong");
  assert.match(V.ruleFor(recovery, false), /^not within \d+(\.\d+)? out of 100 either way$/);
  const lb = { kind: "number", verdict: "wrong", called: "Max Reyes called his weight at about 304.5 lb for October 16.", tolerance: { text: "4 lb" } };
  assert.equal(V.ruleFor(lb, false), "not within 4 lb either way");
  const unknown = { kind: "number", verdict: "wrong", called: "A coach called his something at about 12.", tolerance: { text: "3.1" } };
  assert.equal(V.toleranceWithUnit(unknown), null);
  assert.equal(V.ruleFor(unknown, false), "not within the allowed distance");
  for (const c of BODY.calls.filter((x) => x.kind === "number")) assert.doesNotMatch(V.ruleFor(c, c.verdict === "right"), /within -?\d+(\.\d+)? either way/, c.id);
});
