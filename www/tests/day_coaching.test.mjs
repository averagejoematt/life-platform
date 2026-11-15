// One Day → coaching (owner brief 2026-11-12): which calls a day shows, how "before the day" is told from commentary,
// that the wording never credits a call with the outcome — and that a withheld call never renders, proven against the
// built page with a planted control that MUST fail the same check.
import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { CAUSAL_WORDS, PRIVATE_FAMILY, TIMING_WORDS, VISIBLE_CAP, callsAboutDay, closedWith, leadLine, timing, withheldReason } from "../src/lib/day_coaching.js";

const WWW = resolve(dirname(fileURLToPath(import.meta.url)), "..");

const call = (o = {}) => ({
  type: "prediction",
  visibility: "public",
  id: "physical_coach-pred_20261015_weight",
  coach_id: "physical_coach",
  coach_name: "Marcus Webb",
  claim: "Weight will read 291 lb tomorrow.",
  claim_withheld: null,
  kind: "number",
  status: "confirmed",
  sealed: false,
  logged_date: "2026-10-15",
  due_date: "2026-10-16",
  settled_date: "2026-10-16",
  grading: { how: "weight within ±1.5 lb of 291 lb on 2026-10-16", actual_text: "290.8 lb", tolerance_text: "±1.5 lb", outcome_notes: "Weight came in at 290.8 lb against a call of 291 lb" },
  simple_guess: { state: "scored", right: true, text: "The simple guess was also right." },
  quality_flags: [],
  corrections: [],
  classification_review: false,
  ...o,
});

test("a call is about the day its window closed — not the day it was said, not a day inside the window", () => {
  const c = call();
  assert.equal(callsAboutDay([c], "2026-10-16").length, 1);
  assert.equal(callsAboutDay([c], "2026-10-15").length, 0, "the day it was said is not the day it is about");
  const wide = call({ id: "w", logged_date: "2026-10-01", due_date: "2026-10-14" });
  assert.equal(callsAboutDay([wide], "2026-10-07").length, 0, "a day inside an open window is not the window's day");
});

test("withheld calls are left out entirely: sealed, non-public, observation, private family, nothing to say", () => {
  const day = "2026-10-16";
  const withheld = [
    call({ id: "s", sealed: true }),
    call({ id: "p", visibility: "private" }),
    call({ id: "h", visibility: "held" }),
    call({ id: "o", kind: "observation", status: "observation" }),
    call({ id: "j", grading: { how: "journal sentiment up over 7 days" } }),
    call({ id: "m", metric_key: "som_valence" }),
    call({ id: "v", claim: "The video diary will read calmer." }),
    call({ id: "d", claim: "Mood rises.", claim_withheld: "no_words", grading: null }),
    call({ id: "n", due_date: null }),
  ];
  for (const w of withheld) assert.ok(withheldReason(w), `${w.id} must be withheld`);
  const shown = callsAboutDay([call(), ...withheld], day);
  assert.deepEqual(
    shown.map((c) => c.id),
    [call().id],
  );
  // no count anywhere reveals what was left out: the lead counts what is shown, only
  assert.match(leadLine(shown, day), /^One call's window closed/);
  assert.equal(callsAboutDay(withheld, day).length, 0, "a day whose only calls are withheld shows nothing");
});

test("a call whose words are not published is shown by the grader's test, never by its words", () => {
  const c = callsAboutDay([call({ claim: "The words of this call are not published.", claim_withheld: "no_words" })], "2026-10-16")[0];
  assert.equal(c.words, null);
  assert.equal(c.test, "weight within ±1.5 lb of 291 lb on 16 October 2026", "an ISO date in a served string is written out");
});

test("before the day is a prediction; on or after the day is commentary — and is labelled so", () => {
  assert.equal(timing(call(), "2026-10-16"), "before");
  assert.equal(timing(call({ logged_date: "2026-10-16" }), "2026-10-16"), "on");
  assert.equal(timing(call({ logged_date: "2026-10-18" }), "2026-10-16"), "after");
  assert.equal(timing(call({ logged_date: null }), "2026-10-16"), null);
  const mixed = callsAboutDay(
    [call({ id: "z-after", logged_date: "2026-10-17" }), call({ id: "a-on", logged_date: "2026-10-16" }), call({ id: "m-before" })],
    "2026-10-16",
  );
  assert.deepEqual(
    mixed.map((c) => c.timing),
    ["before", "on", "after"],
    "predictions first",
  );
  assert.equal(mixed[0].tag, "Said before the day");
  assert.match(mixed[1].note, /not a forecast/);
  assert.match(mixed[2].note, /not a forecast/);
  assert.notEqual(TIMING_WORDS.before.tag, TIMING_WORDS.after.tag);
  assert.match(leadLine(mixed, "2026-10-16"), /1 of 3 were said before the day/);
  assert.match(leadLine(mixed.slice(1), "2026-10-16"), /None was said before the day/);
});

test("the outcome is the grader's, in neutral words: predicted X; the window closed with Y", () => {
  assert.equal(closedWith(call()), " with a reading of 290.8 lb: graded right");
  assert.equal(closedWith(call({ status: "refuted" })), " with a reading of 290.8 lb: graded wrong");
  assert.equal(closedWith(call({ status: "refuted", grading: { how: "x" } })), ": graded wrong");
  assert.equal(closedWith(call({ status: "pending" })), ", and it has not been graded yet");
  assert.equal(closedWith(call({ status: "expired" })), ", and it could not be checked");
  assert.match(closedWith(call({ status: "refuted", classification_review: true })), /disputed/);
});

test("no causal wording and no action status in anything this section authors", () => {
  const statuses = ["confirmed", "refuted", "pending", "expired", "inconclusive"];
  const authored = [
    ...Object.values(TIMING_WORDS).flatMap((t) => [t.tag, t.note]),
    ...statuses.map((s) => closedWith(call({ status: s }))),
    leadLine([callsAboutDay([call()], "2026-10-16")[0]], "2026-10-16"),
    leadLine(callsAboutDay([call(), call({ id: "x", logged_date: "2026-10-17" })], "2026-10-16"), "2026-10-16"),
  ];
  for (const s of authored) {
    assert.ok(!CAUSAL_WORDS.test(s), `causal wording: ${s}`);
    assert.ok(!/what (?:matt|he) did|followed|acted on|took the advice/i.test(s), `an action status: ${s}`);
  }
  // the regex itself catches what it must (control)
  for (const bad of ["the call led to a lower weight", "recovery rose because of the advice", "thanks to the coach", "the plan worked"]) {
    assert.ok(CAUSAL_WORDS.test(bad), bad);
  }
  assert.ok(PRIVATE_FAMILY.test("State of Mind") && PRIVATE_FAMILY.test("journal") && !PRIVATE_FAMILY.test("recovery score"));
});

test("the list is capped on arrival; graded calls lead, calls that could not be checked trail", () => {
  assert.ok(VISIBLE_CAP >= 3 && VISIBLE_CAP <= 5);
  const order = callsAboutDay(
    [call({ id: "e", status: "expired" }), call({ id: "p", status: "pending" }), call({ id: "r", status: "refuted" })],
    "2026-10-16",
  ).map((c) => c.id);
  assert.deepEqual(order, ["r", "p", "e"]);
});

// ── the built page: a withheld call never renders (fixture build: scripts/check_www_build.py leaves www/dist) ──────
const DIST = resolve(process.env.DAY_COACHING_DIST || join(WWW, "dist"));
const SNAP = join(WWW, "content", "snapshot", "predictions.json");
const HAVE = existsSync(DIST) && existsSync(SNAP);

/** The coaching part of a built day page ("" when the day has none). */
export function coachingPart(html) {
  const m = html.match(/<div data-day-part="coaching"[^>]*>([\s\S]*?)<\/div>\s*<section[^>]*data-day-part="coaches-calls"/);
  return m ? m[1] : null;
}

/** The ids of withheld calls a coaching part names (data-day-call or a ledger link). */
export function leaked(part, withheldIds) {
  return withheldIds.filter((id) => part.includes(`data-day-call="${id}"`) || part.includes(`/system/ledger/${id}/`));
}

test("built pages: no withheld call in any day's coaching part (control: a planted withheld call is caught)", { skip: HAVE ? false : `no built dist at ${DIST}` }, () => {
  const preds = JSON.parse(readFileSync(SNAP, "utf8"));
  const days = JSON.parse(readFileSync(join(WWW, "content", "snapshot", "days.json"), "utf8"));
  let checked = 0;
  let shownSomewhere = 0;
  for (const d of days) {
    const f = join(DIST, "data", "day", d.id, "index.html");
    if (!existsSync(f)) continue;
    const html = readFileSync(f, "utf8");
    const part = coachingPart(html);
    assert.notEqual(part, null, `${d.id}: the coaching anchor is on every day page (the in-place swap needs it)`);
    const sameDay = preds.filter((p) => p.due_date === d.id);
    const withheldIds = sameDay.filter((p) => withheldReason(p)).map((p) => p.id);
    assert.deepEqual(leaked(part, withheldIds), [], `${d.id}: a withheld call rendered`);
    for (const p of sameDay.filter((p) => !withheldReason(p))) {
      assert.ok(part.includes(`data-day-call="${p.id}"`), `${d.id}: ${p.id} should render`);
      shownSomewhere += 1;
    }
    if (!callsAboutDay(preds, d.id).length) assert.equal(part.trim(), "", `${d.id}: no calls, no section`);
    assert.ok(!CAUSAL_WORDS.test(part.replace(/<[^>]+>/g, " ")), `${d.id}: causal wording in the coaching part`);
    // the control: plant a withheld call into this part — the same check MUST catch it
    if (withheldIds.length) {
      const planted = `${part}<li data-day-call="${withheldIds[0]}"></li>`;
      assert.deepEqual(leaked(planted, withheldIds), [withheldIds[0]], "control: the leak check must fail on a planted withheld call");
    }
    checked += 1;
  }
  assert.ok(checked > 0, "no day page checked");
  // the fixture carries a sealed call due on a day with a page — the control above must have had something to plant
  const sealedDue = preds.filter((p) => p.sealed && p.due_date && days.some((d) => d.id === p.due_date));
  if (preds.some((p) => p.sample)) {
    assert.ok(sealedDue.length > 0, "the fixture's sealed call falls on a built day (the control's subject)");
    assert.ok(shownSomewhere > 0, "the fixture shows at least one call");
  }
});
