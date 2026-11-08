// The Coaching Room's docket and the "refuted this month" ledger view (CR3, built dark — src/lib/room.js): the words of
// /system/docket/, /system/docket/<id>/, /system/ledger/refuted/ and the room entry on each disagreement page. Pure;
// proven in tests/docket.test.mjs.
//
// The owner's brief (2026-11-08): "make disagreements compelling without inventing concessions, motives or outcomes."
// Every value is CARRIED: a docket entry from coach_room.json (= /api/coach_docket as served), a call from the
// ledger's prediction objects. The rules that bind every function below:
//   * a side's position, a concession and a topic are the API's words or nothing: a withheld one shows the API's OWN
//     message when it served one (`unsourced.text`, `absent.reason`, `concession_unsourced.text`), otherwise only that
//     its words are not published — never a paraphrase, never a reconstruction;
//   * the result is the grader's: who won, the value the measure came in at and whether the test held, as served.
//     A sentence here only restates those fields; it never says why a coach argued or how it took the loss;
//   * a call under classification review is never right or wrong (lib/disputed.js); a corrected grade is shown with
//     its correction (lib/corrections.js); a grade is "as first graded" — none is published as re-verified.
import { callOutcome, dayInWords, num } from "./format.js";
import { correctionRows, instantInWords } from "./corrections.js";
import { isDisputed } from "./disputed.js";
import { datesInWords, wordsOrMessage } from "./coach_room.js";

/** The words a page prints for a docket field the API did not publish. */
export const DOCKET_NOT_PUBLISHED = {
  topic: "The words of this question are not published.",
  criterion: "The criterion's own words are not published; its measure, condition and line are.",
  concession: "No concession is served for this entry.",
  integrator: "No integrator's call is served for the docket.",
};

const CONDITION_WORDS = { gte: "at or above", gt: "above", lte: "at or below", lt: "below", eq: "at" };
/** A measure id in words: `recovery_score_7day_avg` → "recovery score, 7-day average". Only the id's own parts. */
export function measureWords(metric) {
  if (!metric) return null;
  const m = /^(.*?)_(\d+)day_avg$/.exec(String(metric));
  if (m) return `${m[1].replace(/_/g, " ")}, ${m[2]}-day average`;
  return String(metric).replace(/_/g, " ");
}

/** The frozen test in words: "recovery score, 7-day average, at or above 80" — or null when no measure is served. */
export function testWords(c) {
  if (!c || !c.metric) return null;
  const t = typeof c.threshold === "number" ? num(c.threshold, Number.isInteger(c.threshold) ? 0 : 1) : null;
  const m = measureWords(c.metric);
  const rest = [CONDITION_WORDS[c.condition] || c.condition, t].filter(Boolean).join(" ");
  return rest ? `${m}${m.includes(",") ? "," : ""} ${rest}` : m;
}

/** The room's docket entries, open first (soonest to settle), then settled (newest first). [] when none served. */
export function docketEntries(file) {
  if (!file || file.state !== "ok" || !Array.isArray(file.docket_entries)) return [];
  const open = file.docket_entries.filter((e) => e && e.status === "open");
  const done = file.docket_entries.filter((e) => e && e.status !== "open");
  open.sort((a, b) => String(a.resolution_date || "").localeCompare(String(b.resolution_date || "")) || a.id.localeCompare(b.id));
  done.sort((a, b) => String(b.resolved_date || b.resolution_date || "").localeCompare(String(a.resolved_date || a.resolution_date || "")) || a.id.localeCompare(b.id));
  return [...open, ...done];
}

/** One entry by id, or null. */
export function docketEntry(file, id) {
  return docketEntries(file).find((e) => e.id === id) || null;
}

/** "1 open · 3 settled" — the API's own tally, carried; null when it served none. */
export function tallyText(counts) {
  if (!counts || !Number.isInteger(counts.open) || !Number.isInteger(counts.resolved)) return null;
  return `${counts.open} open · ${counts.resolved} settled`;
}

/**
 * The question, as the API served it: the topic's words when published; otherwise the frozen criterion's description;
 * otherwise the frozen test itself, stated from its measure, condition and line (the structure, not a paraphrase).
 * `from` says which, so the page can say the topic's words are not published.
 */
export function questionOf(e) {
  if (!e) return null;
  if (typeof e.topic === "string" && e.topic.trim()) return { text: datesInWords(e.topic), from: "topic" };
  const c = e.criterion || {};
  if (typeof c.description === "string" && c.description.trim()) return { text: datesInWords(c.description), from: "criterion" };
  const t = testWords(c);
  if (t) return { text: `${t.charAt(0).toUpperCase()}${t.slice(1)}?`, from: "test" };
  return { text: null, from: "none" };
}

/** A coach's frozen stake: "Brier 0.251 over 20 calls, frozen at the open" — or null. */
export function stakeText(s) {
  if (!s || typeof s.brier !== "number") return null;
  return `Brier ${num(s.brier, 3)}${typeof s.brier_n === "number" ? ` over ${num(s.brier_n)} calls` : ""}, frozen at the open`;
}

const SIDE_WORDS = { true: "bet the test would hold", false: "bet the test would not hold" };
/** Both sides, coach_a first: who, which way they bet (served `sides`), their words or the API's message, their stake. */
export function sidesOf(e, nameOf = (x) => x) {
  if (!e) return [];
  return [e.coach_a, e.coach_b].map((id) => {
    const words = wordsOrMessage((e.claims || {})[id], (e.withheld || {})[id], "claim");
    const side = (e.sides || {})[id];
    return {
      id,
      name: nameOf(id),
      side: typeof side === "boolean" ? SIDE_WORDS[side] : "side not recorded",
      text: words.text,
      message: words.message,
      apiMessage: Boolean(words.message && (e.withheld || {})[id]),
      stake: stakeText((e.stakes || {})[id]) || "no stake served",
      won: e.status === "resolved" && e.winner === id,
      lost: e.status === "resolved" && Boolean(e.loser === id || (e.winner && e.winner !== id)),
    };
  });
}

/** Opened / settles / settled, in words. A missing day is "not recorded". */
export function datesOf(e) {
  const nr = "not recorded";
  if (!e) return null;
  return {
    opened: dayInWords(e.opened_date) || nr,
    settles: dayInWords(e.resolution_date) || nr,
    settled: e.status === "resolved" ? dayInWords(e.resolved_date) || nr : null,
  };
}

/**
 * The result, as graded by code: who won, the value the measure came in at, and whether the test held — each only when
 * served. `headline` restates those fields in one sentence and nothing more (no motive, no concession, no "why").
 */
export function resultOf(e, nameOf = (x) => x) {
  if (!e) return null;
  if (e.status !== "resolved") {
    const d = dayInWords(e.resolution_date);
    return { settled: false, headline: d ? `Not settled yet. The data decides on ${d}.` : "Not settled yet; no settle day is served.", value: null, held: null };
  }
  const value = typeof e.actual_value === "number" ? num(e.actual_value, 1) : null;
  const held = typeof e.holds === "boolean" ? (e.holds ? "the test held" : "the test did not hold") : null;
  const measured = value ? `The measure came in at ${value}${held ? `: ${held}` : ""}.` : held ? `${held.charAt(0).toUpperCase()}${held.slice(1)}.` : "";
  if (e.winner) {
    const loser = e.loser || [e.coach_a, e.coach_b].find((x) => x !== e.winner);
    return {
      settled: true,
      winner: e.winner,
      loser,
      headline: `${nameOf(e.winner)} won${loser ? `; ${nameOf(loser)} lost` : ""}.`,
      measured,
      value,
      held,
    };
  }
  const outcome = e.outcome ? String(e.outcome).replace(/_/g, " ") : "no winner";
  return { settled: true, winner: null, loser: null, headline: `Settled without a winner (${outcome}).`, measured, value, held };
}

/** The concession: the served words (to be quoted verbatim), the API's own withheld message, or null (none served). */
export function concessionOf(e) {
  if (!e || e.status !== "resolved") return null;
  if (typeof e.concession === "string" && e.concession.trim()) return { text: e.concession, message: null };
  if (typeof e.concession_withheld === "string" && e.concession_withheld.trim()) return { text: null, message: e.concession_withheld };
  return null;
}

/**
 * For an OPEN entry, the live measure beside the frozen test — only when the snapshot serves a series under the SAME
 * measure id (no proxy: a daily reading never stands in for a 7-day average). `{value, unit, day, label}` or
 * `{missing}`; null for a settled entry.
 */
export function liveMeasure(e, metric, series) {
  if (!e || e.status !== "open") return null;
  const id = e.criterion && e.criterion.metric;
  if (!id) return { missing: "No measure is served for this test." };
  const days = (series && Array.isArray(series.days) ? series.days : []).filter((d) => d && d.present && typeof d.value === "number");
  if (!metric || !days.length) return { missing: `The site serves no series for ${measureWords(id)}, so the live value is not shown.` };
  const last = days[days.length - 1];
  return {
    value: num(last.value, typeof metric.decimals === "number" ? metric.decimals : 1),
    unit: series.unit || metric.unit || "",
    day: dayInWords(last.date),
    label: metric.title || measureWords(id),
  };
}

/** The served items this page cannot show, named — so a reader knows what is missing and from where. */
export function gapsOf(e, nameOf = (x) => x) {
  if (!e) return [];
  const out = [];
  if (!(typeof e.topic === "string" && e.topic.trim())) out.push("the question's own words (topic)");
  for (const id of [e.coach_a, e.coach_b]) if (!((e.claims || {})[id] || "").trim()) out.push(`${nameOf(id)}'s words (claims)`);
  if (!((e.criterion || {}).description || "").trim()) out.push("the criterion's own words (criterion.description)");
  if (e.status === "resolved" && !concessionOf(e)) out.push("a concession (concession)");
  out.push("an integrator's call (no field is served)");
  return out;
}

/** The disagreement page's matching docket entry: the same two seats, and the same settle day for a settled one. */
export function entryForDisagreement(entries, d) {
  if (!d) return null;
  const seats = (e) => [e.coach_a, e.coach_b].sort().join("|");
  const want = seats(d);
  return (
    (entries || []).find(
      (e) => seats(e) === want && (d.status === "open" ? e.status === "open" : e.status === "resolved" && (!d.resolved_date || e.resolved_date === d.resolved_date))
    ) || null
  );
}

// ── the "refuted this month" ledger view (the old Wrong Feed) ───────────────────────────────────────────────────────
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

/** "2026-11" from an ISO day; null when there is none. */
export function monthOf(iso) {
  const m = /^(\d{4})-(\d{2})/.exec(String(iso || ""));
  return m ? `${m[1]}-${m[2]}` : null;
}
/** "November 2026". */
export function monthWords(month) {
  const m = /^(\d{4})-(\d{2})$/.exec(String(month || ""));
  return m ? `${MONTHS[Number(m[2]) - 1]} ${m[1]}` : null;
}
/** The month before: "2026-01" → "2025-12". */
export function previousMonth(month) {
  const m = /^(\d{4})-(\d{2})$/.exec(String(month || ""));
  if (!m) return null;
  const y = Number(m[1]);
  const n = Number(m[2]);
  return n === 1 ? `${y - 1}-12` : `${y}-${String(n - 1).padStart(2, "0")}`;
}

const inMonth = (iso, month) => Boolean(month) && monthOf(iso) === month;

/** The call's words for a row: a quotation, or the exporter's withheld message (never a paraphrase). */
const CALL_NOT_PUBLISHED = "The words of this call are not published."; // the exporter's own phrase for a call
export function callWords(p) {
  if (!p) return { text: null, message: CALL_NOT_PUBLISHED };
  if (p.claim_withheld) return { text: null, message: p.claim || CALL_NOT_PUBLISHED };
  return typeof p.claim === "string" && p.claim.trim() ? { text: p.claim, message: null } : { text: null, message: CALL_NOT_PUBLISHED };
}

/**
 * One month of the ledger, from the served statuses:
 *   wrong     — graded wrong (`refuted`), settled in the month, NOT under review; newest first. As first graded.
 *   disputed  — graded wrong but under classification review: shown, never counted wrong (lib/disputed.js).
 *   corrected — a correction recorded in the month that moved a grade to or from wrong (lib/corrections.js).
 */
export function refutedLedger(predictions, month) {
  const rows = (predictions || []).filter((p) => p && p.status === "refuted" && inMonth(p.settled_date, month));
  const byDay = (a, b) => String(b.settled_date).localeCompare(String(a.settled_date)) || String(a.id).localeCompare(String(b.id));
  const corrected = [];
  for (const p of predictions || []) {
    for (const c of (p && p.corrections) || []) {
      if ((c.original_status === "refuted" || c.corrected_status === "refuted") && inMonth(c.corrected_at, month)) corrected.push({ p, c });
    }
  }
  corrected.sort((a, b) => String(b.c.corrected_at).localeCompare(String(a.c.corrected_at)));
  return {
    month,
    words: monthWords(month),
    wrong: rows.filter((p) => !isDisputed(p)).sort(byDay),
    disputed: rows.filter(isDisputed).sort(byDay),
    corrected,
  };
}

/** One row of the view: the call's words, who, when it was made and settled, and the grader's served notes. */
export function refutedRow(p, nameOf = (x) => x) {
  const words = callWords(p);
  const g = p.grading || {};
  return {
    id: p.id,
    coach: p.coach_name || nameOf(p.coach_id),
    made: dayInWords(p.logged_date) || "not recorded",
    settled: dayInWords(p.settled_date) || "not recorded",
    outcome: `${callOutcome(p.status)}, as first graded`,
    disputed: isDisputed(p),
    disputedReason: p.classification_review_reason ? datesInWords(p.classification_review_reason) : null,
    text: words.text,
    message: words.message,
    said: p.logged_date || null,
    how: g.how ? datesInWords(g.how) : null,
    notes: g.outcome_notes ? datesInWords(g.outcome_notes) : null,
    guess: (p.simple_guess && p.simple_guess.text) || null,
    corrections: (p.corrections || []).map((c) => ({ rows: correctionRows(c), recorded: instantInWords(c.corrected_at) })),
  };
}
