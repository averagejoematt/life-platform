// ck_verdict.js — the ONE place a preview page prints "Right" or "Wrong" (#4647, epic #4580).
//
// A verdict with no rule beside it reads as arbitrary grading: "called 83.7, came in at 97:
// Right" next to "called 59.3, came in at 82: Wrong" only makes sense once the reader sees
// that each call had its own allowed distance. So a verdict is never printed alone here.
// `verdictTag` takes the rule as an argument and, when there is none, prints a sentence
// saying the rule is not available instead of a tag. No other file builds the kit's
// `ck-verdicts__tag` (tests/js/ck_verdict_4647.test.mjs holds that).
//
// The rule is read from the served sentences of GET /api/calls and nowhere else: the route
// writes "A call like this counts as right within 22.5 either way" into `called`, and this
// file lifts that phrase. Nothing is computed, rounded or assumed; a sentence this file
// cannot read yields no rule, and the page says so.
import { esc } from "/assets/js/evidence_shared.js";

const MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December";
const RE_WITHIN = /counts as right within (.+?) either way/;
const RE_TREND = /against (the trend in [^.]+)\./;
const RE_BET = /\b(whether .+?)\. [^.]*\bsaid\b/;
const RE_FOR_DAY = new RegExp(`\\bfor ((?:${MONTHS}) \\d{1,2})\\.`);
const RE_ON_DAY = new RegExp(`\\bon ((?:${MONTHS}) \\d{1,2})$`);
const RE_CALLED_AT = /\bat about (-?\d+(?:\.\d+)?)/;
const plain = (s) => String(s || "").replace(/\s*\([^)]*\)/g, "");
const betQuestion = (call) => {
  const m = RE_BET.exec(plain(call && call.called));
  return m ? m[1] : "";
};

/** The allowed distance of a number call, as served: "22.5", "1.2 hours". "" when none. */
export function toleranceText(call) {
  const m = call && call.kind === "number" ? RE_WITHIN.exec(String(call.called || "")) : null;
  return m ? m[1].trim() : "";
}

/** The rule that decided a verdict on this call, in the route's own words. `right` is the
 *  verdict being printed (a bet has one per side; the simple guess has its own), so a miss
 *  on a number call reads "not within 18.6 either way". "" when the sentence carries none. */
export function ruleFor(call, right) {
  if (!call) return "";
  if (call.kind === "number") {
    const tol = toleranceText(call);
    return tol ? `${right ? "within" : "not within"} ${tol} either way` : "";
  }
  if (call.kind === "direction") {
    const m = RE_TREND.exec(String(call.called || ""));
    return m ? `by ${m[1]}` : "";
  }
  if (call.kind === "bet") {
    const q = betQuestion(call);
    return q ? `on ${q}` : "";
  }
  return "";
}

/** The verdict and its rule as plain text: "Right · within 22.5 either way". With no rule
 *  it is a sentence that says so, never the bare word. `label` names whose verdict it is
 *  when it is not the coach's ("The simple guess"). */
export function verdictText(right, rule, label = "") {
  const word = right ? "right" : "wrong";
  const r = String(rule || "").trim();
  if (!r) return `${label ? `${label} was marked` : "Marked"} ${word}. The rule that decided it is not available for this call.`;
  return `${label ? `${label}: ${word}` : right ? "Right" : "Wrong"} · ${r}`;
}

/** The kit's verdict tag, always with its rule. No rule: a soft sentence, not a tag. */
export function verdictTag(right, rule, label = "") {
  const text = esc(verdictText(right, rule, label));
  if (!String(rule || "").trim()) return `<span class="ck-soft">${text}</span>`;
  return `<span class="ck-verdicts__tag${right ? " ck-verdicts__tag--right" : ""}">${text}</span>`;
}

/** The tag for one settled call from /api/calls, on the call's own verdict. */
export const callVerdictTag = (call) => verdictTag(call.verdict === "right", ruleFor(call, call.verdict === "right"));
export const callVerdictText = (call) => verdictText(call.verdict === "right", ruleFor(call, call.verdict === "right"));

/** A card heading in the tag's type that is NOT a verdict ("The simple guess", before it is
 *  checked). It refuses a verdict word, so it cannot be used to print one bare. */
export function cardLabel(text) {
  const t = String(text || "");
  return /\b(right|wrong)\b/i.test(t) ? "" : `<span class="ck-verdicts__tag">${esc(t)}</span>`;
}

/** The day whose reading the call was graded on, in words, from the served sentence: a
 *  number call is "for September 20"; a bet's question ends "on September 30". A direction
 *  call is graded on a trend, not one day, so it has none. "" when the sentence names none. */
export function measuredDay(call) {
  if (!call) return "";
  if (call.kind === "number") {
    const m = RE_FOR_DAY.exec(String(call.called || ""));
    return m ? m[1] : "";
  }
  if (call.kind === "bet") {
    const m = RE_ON_DAY.exec(betQuestion(call));
    return m ? m[1] : "";
  }
  return "";
}

/** "Graded on the reading for September 20." / "Graded on the trend in his most recent
 *  readings." — what the grade was measured on. "" when the served sentence does not say. */
export function gradedOnText(call) {
  const day = measuredDay(call);
  if (day) return `Graded on the reading for ${day}.`;
  if (call && call.kind === "direction") {
    const m = RE_TREND.exec(String(call.called || ""));
    return m ? `Graded on ${m[1]}.` : "";
  }
  return "";
}

// ── which calls to show as the pair ────────────────────────────────────────────
const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const calledAt = (call) => {
  const m = RE_CALLED_AT.exec(String((call && call.called) || ""));
  return m ? Number(m[1]) : null;
};
const tolNumber = (call) => {
  const m = /^(\d+(?:\.\d+)?)/.exec(toleranceText(call));
  return m ? Number(m[1]) : null;
};
/** How tight a number call's rule was: the allowed distance as a share of the number
 *  called, so hours and points compare. null when either is not on the wire. */
export function tightness(call) {
  const [tol, at] = [tolNumber(call), calledAt(call)];
  return tol !== null && at ? tol / Math.abs(at) : null;
}
/** How far a number call landed from its number, in allowed distances (1 = on the edge). */
export function missBy(call) {
  const [tol, at, actual] = [tolNumber(call), calledAt(call), num(call && call.actual && call.actual.value)];
  return tol && at !== null && actual !== null ? Math.abs(actual - at) / tol : null;
}
/** The pair to show: the right call whose rule was tightest, and the wrong call that
 *  missed by the most allowed distances. Ties go to the newer call (the list arrives
 *  newest first). With no number call of a kind, the newest call of that kind stands in. */
export function showcasePair(calls) {
  const list = (Array.isArray(calls) ? calls : []).filter((c) => c && c.kind !== "bet");
  const best = (verdict, score, wantHigh) => {
    const of = list.filter((c) => c.verdict === verdict);
    let pick = null;
    let top = null;
    for (const c of of) {
      const s = score(c);
      if (s === null) continue;
      if (top === null || (wantHigh ? s > top : s < top)) [pick, top] = [c, s];
    }
    return pick || of[0] || null;
  };
  return { right: best("right", tightness, false), wrong: best("wrong", missBy, true) };
}
