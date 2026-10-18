// ck_verdict.js — the ONE place a preview page prints "Right" or "Wrong" (#4647, epic #4580).
//
// A verdict with no rule beside it reads as arbitrary grading: "called 83.7, came in at 97:
// Right" next to "called 59.3, came in at 82: Wrong" only makes sense once the reader sees
// that each call had its own allowed distance. So a verdict is never printed alone here.
// `verdictTag` takes the rule as an argument and, when there is none, returns "" — no tag
// and no stand-in sentence (#4808: no verdict without its rule). No other file builds the kit's
// `ck-verdicts__tag` (tests/js/ck_verdict_4647.test.mjs holds that).
//
// The rule is read from GET /api/calls and nowhere else. A number call's allowed distance is
// served ONCE, in `tolerance` (#4808: the number as printed, and in words the statistic and
// window it was computed from); a route deployed before that wrote it into `called` ("counts
// as right within 22.5 either way"), and this file still lifts that phrase when `tolerance`
// is absent. Nothing is computed, rounded or assumed.
//
// THE HOUSE RULE (#4808), one builder for every page that prints a graded call —
// `callCardHTML`: the tag first (the verdict and its rule: the rule is said HERE and nowhere
// else on the card), then the call with the RESULT in bold, then one soft line (what the
// allowed distance is, in words; the day it was graded on; the door). And a call whose rule
// cannot be read is never shown as right or wrong: the tag is "", the card is "", and the
// pickers skip it and say how many they skipped (`ruleless`).
import { esc } from "/assets/js/evidence_shared.js";

const MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December";
const RE_WITHIN = /counts as right within (.+?) either way/;
const RE_TREND = /against (the trend in [^.]+)\./;
// #4617: a direction call graded across its own window says so in its sentence.
const RE_WINDOW = /checked on the change from the first reading of its window, ([^,]+), to the last, ([^,.]+)/;
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
  if (!call || call.kind !== "number") return "";
  const t = call.tolerance && typeof call.tolerance.text === "string" ? call.tolerance.text.trim() : "";
  if (t) return t;
  const m = RE_WITHIN.exec(String(call.called || ""));
  return m ? m[1].trim() : "";
}
/** What the allowed distance is, in the route's words: "The allowed distance is one standard
 *  deviation of his readings over the 30 days before the call." "" when not served —
 *  the number in the tag still stands, and no wording is guessed. */
export function toleranceNote(call) {
  const t = call && call.tolerance;
  const st = t && typeof t.statistic === "string" ? t.statistic.trim().replace(/[.\s]+$/, "") : "";
  if (!st) return "";
  if (call.kind === "number") return `The allowed distance is ${st}.`;
  // A window-graded direction call (#4617): its band is said here, once, with what it is.
  const n = typeof t.text === "string" ? t.text.trim() : "";
  return call.kind === "direction" && n ? `It counted as a move only beyond ${n} either way, ${st}.` : "";
}

/** The unit a served allowed distance is in (red team 2026-10-17: "not within 17.3 either way"
 *  had none). A served text that carries its unit ("4 lb", "1.2 hours") keeps it. A bare number
 *  takes the unit of the measure the call's own served sentence names — only measures listed
 *  here, each one a score whose unit is not a guess. Anything else: null, and the rule is said
 *  without the number ("not within the allowed distance") rather than with a unit invented. */
const SCORE_UNITS = [[/\brecovery score\b/i, "points"]];
export function toleranceWithUnit(call) {
  const tol = toleranceText(call);
  if (!tol) return "";
  if (!/^-?\d+(?:\.\d+)?$/.test(tol)) return tol;
  const hit = SCORE_UNITS.find(([re]) => re.test(String((call && call.called) || "")));
  return hit ? `${tol} ${hit[1]}` : null;
}

/** The rule that decided a verdict on this call, in the route's own words. `right` is the
 *  verdict being printed (a bet has one per side; the simple guess has its own), so a miss
 *  on a number call reads "not within 18.6 points either way". "" when the sentence carries none. */
export function ruleFor(call, right) {
  if (!call) return "";
  if (call.kind === "number") {
    const tol = toleranceWithUnit(call);
    if (tol === null) return right ? "within the allowed distance" : "not within the allowed distance";
    return tol ? `${right ? "within" : "not within"} ${tol} either way` : "";
  }
  if (call.kind === "direction") {
    const w = RE_WINDOW.exec(String(call.called || ""));
    if (w) return `by the change from ${w[1]} to ${w[2]}`;
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
 *  it is "" — never the bare word, and never "marked wrong" with the rule missing (#4808: a
 *  verdict a reader cannot check is not printed at all). `label` names whose verdict it is
 *  when it is not the coach's ("The simple guess"). */
export function verdictText(right, rule, label = "") {
  const r = String(rule || "").trim();
  if (!r) return "";
  return `${label ? `${label}: ${right ? "right" : "wrong"}` : right ? "Right" : "Wrong"} · ${r}`;
}

/** The kit's verdict tag, always with its rule. No rule: "" — the caller shows no verdict. */
export function verdictTag(right, rule, label = "") {
  const text = verdictText(right, rule, label);
  if (!text) return "";
  return `<span class="ck-verdicts__tag${right ? " ck-verdicts__tag--right" : ""}">${esc(text)}</span>`;
}

/** The tag for one settled call from /api/calls, on the call's own verdict. */
export const callVerdictTag = (call) => verdictTag(call.verdict === "right", ruleFor(call, call.verdict === "right"));
export const callVerdictText = (call) => verdictText(call.verdict === "right", ruleFor(call, call.verdict === "right"));
/** Whether a settled call can be shown as a verdict: it has a rule a reader can read. A bet's
 *  rule is its question. */
export const hasRule = (call) => Boolean(call && ruleFor(call, call.verdict === "right"));
/** "2 settled calls have no rule the page can print, so they are not shown as right or wrong
 *  here." for the calls a picker skipped; "" for none. (Not a record count — the record and
 *  its comparison are said elsewhere on the page, #4585.) */
export function ruleless(n) {
  const k = Number(n) || 0;
  if (k < 1) return "";
  return `${k === 1 ? "One settled call has" : `${k} settled calls have`} no rule the page can print, so ${k === 1 ? "it is" : "they are"} not shown as right or wrong here.`;
}

/** A pair of cards whose allowed distances were all computed the same way says so ONCE, under
 *  the pair, instead of once per card: "Each allowed distance is one standard deviation of …".
 *  "" when the shown number calls disagree or none serves its statistic — then each card says
 *  its own (`note: true`). */
export function sharedToleranceNote(calls) {
  const stats = (calls || []).filter((c) => c && c.kind === "number").map((c) => (c.tolerance && typeof c.tolerance.statistic === "string" ? c.tolerance.statistic.trim() : ""));
  if (stats.length < 2 || !stats[0] || stats.some((x) => x !== stats[0])) return "";
  return `Each allowed distance is ${stats[0].replace(/[.\s]+$/, "")}.`;
}

/** THE card for one settled call — the house rule (#4808), the same on the front page, the
 *  coaches page, a coach's page and a day page: the tag (verdict and rule) first; then the call
 *  with the RESULT in bold; then one soft line — what the allowed distance is in words, then
 *  `when` (the page's own dating), then the door. "" for a call with no readable rule or no
 *  sentences: it is never shown as a verdict. Options:
 *    full     the call's whole sentence (`called`, with its gloss) instead of `called_short`
 *    when     the page's dating sentence, e.g. "Graded on the reading for October 9."
 *    extra    one more soft sentence (the front page's simple guess)
 *    href     the call's own page; linkText its words
 *    wrap     "div" (a card in a .ck-verdicts pair), "li" (a day page's row) or "" (inside a
 *             card the caller already drew)
 *    note     false when the caller prints `sharedToleranceNote` once under a pair */
/** Round 4: "Henning Brandt called his weight" → "called Matthew's weight". The possessive in a
 *  served call sentence refers to Matthew; on a page that also names coaches, "his" reads as the
 *  coach's. One helper, so every page that prints a call says it the same way. */
export const matthewsCall = (text) => String(text || "").replace(/\bcalled his\b/g, "called Matthew’s");
export function callCardHTML(call, { full = false, when = "", extra = "", href = "", linkText = "The whole call", wrap = "div", note = true, moreDoor = "" } = {}) {
  if (!call || call.kind === "bet") return "";
  const tag = callVerdictTag(call);
  const said = matthewsCall(String((full && call.called) || call.called_short || "").trim());
  const result = String(call.happened_short || "").trim();
  if (!tag || !said || !result) return "";
  const soft = [note ? toleranceNote(call) : "", String(when || "").trim(), String(extra || "").trim()].filter(Boolean).join(" ");
  // `moreDoor`: trusted HTML, a second door sharing the line (the front page's "Every settled call").
  const door = href ? `<a class="ck-link" href="${esc(href)}">${esc(linkText)}</a>${moreDoor ? ` · ${moreDoor}` : ""}` : "";
  const softHTML = soft || door ? `<p class="ck-soft">${esc(soft)}${soft && door ? " " : ""}${door}</p>` : "";
  const inner = `${tag}<p>${esc(said)} <b>${esc(result)}</b></p>${softHTML}`;
  return wrap ? `<${wrap}>${inner}</${wrap}>` : inner;
}

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
    const w = RE_WINDOW.exec(String(call.called || ""));
    if (w) return `Graded on the readings from ${w[1]} to ${w[2]}.`;
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
  // A call with no readable rule is never a verdict on a page (#4808), so it is never picked.
  const list = (Array.isArray(calls) ? calls : []).filter((c) => c && c.kind !== "bet" && hasRule(c));
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
