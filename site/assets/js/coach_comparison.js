// coach_comparison.js — the coaches' record never appears alone (#4585, epic #4580 rule 3).
//
// Every API payload that serves a coach count (/api/predictions, /api/calibration,
// /api/coaches, /api/coach/{id} report_card.track_record, /api/wrong) now serves a
// `comparison` block beside it, built server-side by lambdas/coach/coach_baseline.py from
// the SAME rows the count is counted from. Its `sentence` is the one line a page prints:
//   * until every graded call carries the "nothing changes" rule's verdict, the engine's
//     existing skill score in plain words, with its n ("Across 96 checked calls, so far
//     they do not beat a simple guess.");
//   * after, the rule's right / scored counts per record — number calls, direction calls,
//     yes/no bets, sealed day-one predictions, never added together — saying so when the
//     guess did better.
// This module only prints it. It computes nothing and invents nothing: a missing block
// (an older response, or a failed ledger read) is said as an absence, never as a verdict.
//
// tests/test_coach_count_comparison_guard_4585.py holds the SET: every site module that
// renders a coach count calls `coachComparison` (or `comparisonText`).

const ABSENT = "What a simple guess would have scored on these calls is not available right now.";

const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/** The comparison sentence as plain text — the served sentence, or the honest absence. */
export function comparisonText(cmp) {
  const s = cmp && typeof cmp.sentence === "string" ? cmp.sentence.trim() : "";
  return s || ABSENT;
}

/** The comparison as one paragraph of HTML, to sit directly beside a coach count.
 *  `cls` lets a page keep its own type (a label line, a note); `src` names the payload
 *  path for the data-src provenance convention the v7 pages use. */
export function coachComparison(cmp, { cls = "coach-cmp", src = "" } = {}) {
  const srcAttr = src ? ` data-src="${esc(src)}"` : "";
  return `<p class="${esc(cls)}" data-coach-comparison${srcAttr}>${esc(comparisonText(cmp))}</p>`;
}
