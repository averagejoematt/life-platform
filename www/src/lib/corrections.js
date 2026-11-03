// One correction on a prediction, as the rows a ledger page prints (#5610, owner decision D 2026-11-02).
// Pure; proven in tests/corrections.test.mjs.
//
// The dates stay distinct and are never invented: the call was MADE on `said_on`; the original grade
// names the DAY it was graded (no writer recorded a time of day); the corrected grade names its own day
// only when the writer recorded one; the correction was RECORDED at `corrected_at` (an instant, UTC);
// it was PUBLISHED on `published_on`, which no writer has recorded yet — so the row says "not recorded"
// rather than borrowing the build day or the recorded instant. A missing value is "not recorded", in words.

import { callOutcome, dayInWords } from "./format.js";

const NOT_RECORDED = "not recorded";

/** An ISO instant as "11 October 2026, 02:48 UTC"; a bare day as the day in words; nothing as null. */
export function instantInWords(iso) {
  if (!iso) return null;
  const day = dayInWords(String(iso).slice(0, 10));
  if (!day) return null;
  const t = /T(\d{2}:\d{2})/.exec(String(iso));
  return t ? `${day}, ${t[1]} UTC` : day;
}

function verdict(status, day, dayWord) {
  if (!status) return NOT_RECORDED;
  const word = callOutcome(status);
  if (status === "pending") return `${word} — not yet graded`;
  return day ? `${word} — ${dayWord} ${dayInWords(day)}` : `${word} — ${dayWord} day ${NOT_RECORDED}`;
}

/** [label, value] rows for one correction, in reading order. Every value is words; no ISO date survives. */
export function correctionRows(c) {
  const rows = [
    ["Call made", dayInWords(c.said_on) || NOT_RECORDED],
    ["Original verdict", verdict(c.original_status, c.original_outcome_date, "graded")],
    ["Corrected verdict", c.corrected_status ? verdict(c.corrected_status, c.corrected_outcome_date, "graded") : NOT_RECORDED],
  ];
  if (c.target_before || c.target_after) {
    rows.push(["Day the call was about", `${dayInWords(c.target_before) || NOT_RECORDED}, corrected to ${dayInWords(c.target_after) || NOT_RECORDED}`]);
  }
  rows.push(["What changed", c.explanation]);
  rows.push(["Correction recorded", instantInWords(c.corrected_at) || NOT_RECORDED]);
  rows.push(["Correction published", dayInWords(c.published_on) || NOT_RECORDED]);
  if (c.aggregate_impact) rows.push(["Aggregate impact", c.aggregate_impact]);
  return rows;
}

/** The audit line under the stored reason: the rule id(s) and evaluator version, as recorded. */
// A rule id is an identifier, not a quotation: a date inside one (the owner's ruling of 2 November 2026 is
// `#5533:c+owner-2026-11-02`) is written in words on the page, like every other authored date.
const idInWords = (id) => String(id).replace(/\b(\d{4}-\d{2}-\d{2})\b/g, (iso) => dayInWords(iso) || iso);

export function ruleText(c) {
  return (c.rules || []).map((r) => (r.version ? `${idInWords(r.id)}, evaluator ${r.version}` : `${idInWords(r.id)}, version ${NOT_RECORDED}`)).join(" · ");
}

/** The specifics behind a Day-page note on a coach line (owner review of #5644, 2026-11-03: concise on the page,
 *  "the specific correction and dates available on demand"). `g` is one `coach_lines[].grade_corrections` entry — the
 *  same served shape the coach APIs use (lambdas/coach/authoritative_grades.CORRECTION_NOTE_FIELDS). Words only. */
export function gradeNoteRows(g) {
  const rows = [];
  if (g.original_status) rows.push(["Grade before", callOutcome(g.original_status)]);
  rows.push([g.original_status ? "Grade now" : "The ledger's grade", g.corrected_status ? callOutcome(g.corrected_status) : NOT_RECORDED]);
  if (g.original_status) rows.push(["Correction recorded", instantInWords(g.corrected_at) || NOT_RECORDED]);
  if (g.explanation) rows.push(["What changed", g.explanation]);
  return rows;
}
