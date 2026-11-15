// One Day → coaching (owner brief 2026-11-12): the day, what the coaches called about it, how the call's window
// closed, and what the grade says. Pure functions over the snapshot's PUBLIC prediction objects — the same objects the
// ledger pages (/system/ledger/<id>/) are built from, already gated server-side by web/call_publication.py (a
// non-eligible call — PUBLIC_BRIEF_DARK, UNREVIEWED_BET, private-sourced — never reaches /api/ledger_export, so it is
// not in the snapshot). This module adds the page's own fail-closed belts on top and never re-grades anything:
//
//   * a call is about a day when its test window CLOSED on that day (`due_date`) — the day the grader reads;
//   * withheld calls are left out entirely — no row, no placeholder, no count: a sealed call, a non-public object, an
//     observation (no window, no grade), a call with nothing publishable to say, and any call one of whose served
//     strings names a private family (journal, State of Mind, the video diary — private including by inference);
//   * "before the day" (said on an earlier day: a prediction) is told apart from "on the day" and "after the day"
//     (commentary, not a forecast made in advance);
//   * the wording is neutral — what was predicted, when the window closed, what the grader read. Nothing here says a
//     call, or the advice beside it, produced the outcome; and nothing here says what Matt did (an advice link is
//     owner-only and served by no public route — when one is, it lands as its own field, not as an inference here).
//
// Proven by tests/day_coaching.test.mjs (selection, timing, wording, the withheld control).
import { callOutcome, dayInWords } from "./format.js";
import { isDisputed } from "./disputed.js";

/** A private family named in any served string of a call (the producers' PRIVATE_FAMILY belt, twinned here). */
export const PRIVATE_FAMILY = /journal|diar(?:y|ies)|state[\s_-]*of[\s_-]*mind|\bsom_|\bmood\b|video|vlog/i;

/** Wording that would credit a call (or the advice beside it) with the outcome, or report an action. Never authored here. */
export const CAUSAL_WORDS =
  /\b(?:because|caus(?:e|ed|es|ing)|led to|leads? to|thanks to|result(?:ed|s)? in|as a result|due to|dr(?:ove|iven)|helped|paid off|worked|followed (?:the|his|her) (?:advice|call)|attribut\w*|credit(?:ed)?|so that)\b/i;

/** The most calls listed before the rest fold into "the other N". */
export const VISIBLE_CAP = 4;

const ISO = /\b(\d{4}-\d{2}-\d{2})\b/g;
const words = (iso) => (dayInWords(iso, { weekday: true }) || "").replace(/ \d{4}$/, "");
const deIso = (s) => (typeof s === "string" ? s.replace(ISO, (m) => (dayInWords(m) ? dayInWords(m) : m)) : s);

/** Every served string of a call that this section could print or that names it. */
function servedStrings(p) {
  const g = p.grading || {};
  return [p.id, p.title, p.claim, p.metric_key, p.metric_id, g.how, g.actual_text, g.tolerance_text, g.outcome_notes, p.verdict_text, p.simple_guess && p.simple_guess.text].filter(
    (s) => typeof s === "string",
  );
}

/** Why a call is left out of the day's section (null: it may be shown). The reasons are for tests and logs only. */
export function withheldReason(p) {
  if (!p || p.type !== "prediction") return "not a prediction";
  if (p.visibility !== "public") return "not public";
  if (p.sealed) return "sealed";
  if (p.kind === "observation" || p.status === "observation") return "an observation: no window, no grade";
  if (!p.due_date) return "no window";
  if (servedStrings(p).some((s) => PRIVATE_FAMILY.test(s))) return "names a private family";
  const how = p.grading && p.grading.how;
  if (p.claim_withheld && !how) return "nothing publishable to say";
  return null;
}

/** When the call was said, against the day it is about: "before" (a prediction), "on" or "after" (commentary). */
export function timing(p, date) {
  const said = String(p.logged_date || "").slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(said)) return null;
  if (said < date) return "before";
  return said === date ? "on" : "after";
}

export const TIMING_WORDS = {
  before: { tag: "Said before the day", note: "a prediction" },
  on: { tag: "Said on the day itself", note: "commentary, not a forecast made in advance" },
  after: { tag: "Said after the day", note: "commentary, not a forecast" },
};

/** The calls about `date` (their window closed that day), withheld ones left out, predictions first. */
export function callsAboutDay(predictions, date) {
  const out = [];
  for (const p of predictions || []) {
    if (!p || p.due_date !== date || withheldReason(p)) continue;
    const t = timing(p, date);
    if (!t) continue;
    out.push(dayCall(p, date, t));
  }
  const rank = { before: 0, on: 1, after: 2 };
  // graded calls first, then the ones still open or inconclusive, the ones that could not be checked last
  const settled = { confirmed: 0, refuted: 0, pending: 1, inconclusive: 1, expired: 2 };
  const sr = (c) => settled[c.status] ?? 1;
  return out.sort(
    (a, b) => rank[a.timing] - rank[b.timing] || sr(a) - sr(b) || (a.said < b.said ? -1 : a.said > b.said ? 1 : 0) || (a.id < b.id ? -1 : 1),
  );
}

/** What the window closed with, in words that follow "the window closed <day>": the grader's own outcome, never re-graded. */
export function closedWith(p) {
  const g = p.grading || {};
  if (p.status === "pending") return ", and it has not been graded yet";
  if (p.status === "expired") return ", and it could not be checked";
  if (p.status === "inconclusive") return ", and the grade was inconclusive";
  const disputed = isDisputed(p) ? " (disputed: under classification review)" : "";
  const reading = g.actual_text ? ` with a reading of ${deIso(g.actual_text)}` : "";
  return `${reading}: graded ${callOutcome(p.status)}${disputed}`;
}

/** One call, placed and worded for the day page. */
export function dayCall(p, date, t = timing(p, date)) {
  const g = p.grading || {};
  const how = g.how ? deIso(g.how) : null;
  return {
    id: p.id,
    coach_id: p.coach_id,
    coach_name: p.coach_name,
    status: p.status,
    disputed: isDisputed(p),
    timing: t,
    tag: TIMING_WORDS[t].tag,
    note: TIMING_WORDS[t].note,
    said: p.logged_date,
    saidWords: words(p.logged_date),
    closedWords: words(p.due_date),
    gradedWords: p.settled_date ? words(p.settled_date) : null,
    // the coach's own words only where the ledger publishes them; otherwise the grader's test, which the ledger prints
    words: p.claim_withheld ? null : p.claim,
    test: how,
    closed: closedWith(p),
    notes: g.outcome_notes ? deIso(g.outcome_notes) : null,
    tolerance: g.tolerance_text ? deIso(g.tolerance_text) : null,
    guess: p.simple_guess && p.simple_guess.text ? deIso(p.simple_guess.text) : null,
    flags: (p.quality_flags || []).map((f) => String(f).replace(/_/g, " ")),
    corrected: Array.isArray(p.corrections) && p.corrections.length > 0,
  };
}

/** The section's one-line lead: how many calls, and what a grade does and does not say. */
export function leadLine(calls, date) {
  const n = calls.length;
  const before = calls.filter((c) => c.timing === "before").length;
  const what = n === 1 ? "One call's window" : `${n} calls' windows`;
  const split =
    before === n
      ? n === 1
        ? "It was said before the day."
        : "All were said before the day."
      : before === 0
        ? "None was said before the day: what is here is commentary, not a forecast."
        : `${before} of ${n} were said before the day.`;
  return `${what} closed on ${words(date)}. ${split} A grade says whether the call matched the reading, not why the day went as it did.`;
}
