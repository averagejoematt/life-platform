// The Coaching Room's coach profiles (CR2, built dark — src/lib/room.js): the words of /system/coaches/<id>/record/ and
// of the room entry on each coach page. Pure; proven in tests/coach_room.test.mjs.
//
// The owner's brief (2026-11-08): "make each coach's evolution understandable: what they believed, what changed, what
// they advised, and what I demonstrably did or didn't do" — analytical and editorial, simple on arrival, deep on demand.
//
// Every value is CARRIED from the snapshot (coach_room.json = /api/coach/<id> + /api/coach_docket +
// /api/voice_fidelity, as served; calibration.json and the prediction objects from CR1 and the ledger). Nothing is
// counted, divided or estimated here, and no label is invented: a status is the API's own word; a count is the
// producer's. Two rules from the owner bind every function below:
//   * a withheld read shows the API's OWN withheld message when the row carries one, and otherwise only that its
//     words are not published — never a paraphrase, never a guess at what it said;
//   * "what Matt did" is an owner-asserted, evidence-only advice link that no public route serves, so it reads
//     "not recorded" everywhere — it is never inferred from timing or from the data moving the way an ask wanted.
import { callOutcome, dayInWords, kOfN, num } from "./format.js";
import { instantInWords } from "./corrections.js";
import { isDisputed } from "./disputed.js";
import { intervalText, pct, v2Answers } from "./calibration.js";

/** The words a page prints for a read, a stance or an ask whose words the platform does not publish. The same phrase
 *  the exporter uses for a call ("The words of this call are not published."), so the site speaks one vocabulary. */
export const NOT_PUBLISHED = {
  read: "The words of this read are not published.",
  stance: "The words of this stance are not published.",
  ask: "The words of this ask are not published.",
  claim: "The words of this side are not published.",
};

/** What Matt did, for every ask and every call: no public route serves an advice link (owner ruling 2026-11-02). */
export const WHAT_MATT_DID = "not recorded";
export const WHAT_MATT_DID_NOTE =
  "Whether Matt acted on an ask is recorded only when he links a decision to it himself, with evidence. None of those links is published, so every row reads “not recorded”. The site never infers it from timing, or from the data moving the way the ask wanted.";

/** An ISO day or instant inside a served sentence, in words ("no sensor since 2026-10-12" → "… 12 October 2026"). */
export function datesInWords(text) {
  if (!text) return "";
  return String(text).replace(/\b(\d{4}-\d{2}-\d{2})(?:T[\d:.]+(?:Z|[+-]\d{2}:\d{2})?)?\b/g, (iso, day) => dayInWords(day) || iso);
}

/** One coach's entry in the room's data file, or null. */
export function roomCoach(file, id) {
  if (!file || file.state !== "ok" || !file.coaches) return null;
  return file.coaches[id] || null;
}

/** The served words of a read, or the message that stands in for them: {text, message}. Never both. */
export function wordsOrMessage(text, withheldText, kind = "read") {
  if (typeof text === "string" && text.trim()) return { text, message: null };
  return { text: null, message: withheldText || NOT_PUBLISHED[kind] || NOT_PUBLISHED.read };
}

/** The latest read, dated, with its provenance — or null when none was served. */
export function latestRead(entry) {
  const r = entry && entry.latest_read;
  if (!r) return null;
  const { text, message } = wordsOrMessage(r.text, r.withheld_text, "read");
  return {
    kind: r.kind,
    who: r.kind === "lead_daily" ? "The lead's daily read" : "The newest written read",
    day: dayInWords(r.date) || null,
    written: instantInWords(r.generated_at),
    through: dayInWords(r.data_through) || null,
    // the route, not the persona id: a raw id is never page text (#5568); the page names the coach already
    source: r.source ? String(r.source).replace(/^\/api\/coach\/[^\s·]+/, "/api/coach") : null,
    text,
    message,
    said: r.date || null,
    cited: (r.cited || []).map((c) => ({ metric: c.metric, value: datesInWords(c.value), asOf: dayInWords(c.as_of) || null })),
  };
}

/** The coach's current stance: the stage, the read (or its message), what changed, and a correction that overtook it. */
export function currentStance(entry) {
  const s = entry && entry.stance;
  if (!s || s.source === "none") return null;
  if (s.source === "absent") return { absent: true, reason: datesInWords(entry.absent_reason) || "This coach's instrument is not reporting." };
  const read = wordsOrMessage(s.headline_read, s.withheld_text, "stance");
  return {
    absent: false,
    authored: s.source === "ladder", // no written stance: the stage plan the author wrote stands in
    asOf: dayInWords(s.as_of) || null,
    stage: s.stage_label || null,
    text: read.text,
    message: read.message,
    changed: s.how_my_read_changed || null,
    focused: s.focused_on_now || [],
    aside: s.set_aside_for_now || [],
    gate: s.graduation_gate || null,
    superseded: s.summary_state === "superseded_by_correction",
    supersededAt: instantInWords(s.summary_as_of),
    corrections: s.summary_corrections || [],
    rung: s.rung || null,
    ladder: s.ladder || [],
  };
}

/** The dated stances, newest first, each with its read or the message, and any grade correction riding beside it. */
export function stanceTimeline(entry) {
  return ((entry && entry.stance_history) || []).map((h) => {
    const read = wordsOrMessage(h.headline_read, h.withheld_text, "stance");
    return {
      date: h.as_of,
      day: dayInWords(h.as_of),
      stage: h.stage_label || null,
      text: read.text,
      message: read.message,
      changed: h.how_my_read_changed || null,
      corrections: h.grade_corrections || [],
    };
  });
}

/** The ask statuses, in the API's own words. */
const ASK_WORDS = {
  kept: "kept",
  broken: "broken",
  pending: "pending",
  unresolved: "unresolved",
  ungradeable: "ungradeable — its measure was never observed",
};
export function askWord(status) {
  return ASK_WORDS[status] || (status ? String(status).replace(/_/g, " ") : "not recorded");
}

const COUNT_ORDER = ["kept", "broken", "pending", "unresolved", "ungradeable"];
/** "59 held: 2 kept, 2 broken, 2 pending, 53 unresolved" — the producer's tally, carried; a zero bucket is left out. */
export function askCountsText(counts) {
  if (!counts || !Number.isInteger(counts.held)) return null;
  if (counts.held === 0) return "No ask on the record this cycle.";
  const parts = COUNT_ORDER.filter((k) => Number.isInteger(counts[k]) && counts[k] > 0).map((k) => `${counts[k]} ${k}`);
  return `${counts.held} held${parts.length ? `: ${parts.join(", ")}` : ""}.`;
}

const DIRECTION_WORDS = { up: "up", down: "down", flat: "steady" };
/** "sleep duration hours, up" — what the grader checks an ask against, as served. */
export function checkWords(check) {
  if (!check || !check.metric) return null;
  const m = String(check.metric).replace(/_/g, " ");
  return check.direction ? `${m}, ${DIRECTION_WORDS[check.direction] || check.direction}` : m;
}

/** One row per ask, newest first as served. The outcome is the grader's; what Matt did is never inferred. */
export function askRows(entry) {
  return (((entry && entry.asks) || {}).rows || []).map((a) => {
    const words = wordsOrMessage(a.text, a.withheld_text, "ask");
    return {
      asked: dayInWords(a.date),
      due: dayInWords(a.due_date) || "not recorded",
      status: a.status,
      outcome: askWord(a.status),
      settled: dayInWords(a.outcome_date) || null,
      checked: checkWords(a.check) || "not recorded",
      text: words.text,
      message: words.message,
      did: WHAT_MATT_DID,
    };
  });
}

const CONDITION_WORDS = { gte: "at or above", gt: "above", lte: "at or below", lt: "below", eq: "at" };
/** A docket criterion in words: "recovery score 7day avg at or above 80". */
export function criterionWords(c) {
  if (!c) return null;
  if (c.description) return c.description;
  if (!c.metric) return null;
  const t = typeof c.threshold === "number" ? num(c.threshold, Number.isInteger(c.threshold) ? 0 : 1) : null;
  return [String(c.metric).replace(/_/g, " "), CONDITION_WORDS[c.condition] || c.condition, t].filter(Boolean).join(" ");
}

/** The docket entries this coach stood on, from its side: what it bet, the stake, how it ended. Names via `nameOf`. */
export function docketRows(entry, id, nameOf = (x) => x) {
  return ((entry && entry.docket) || []).map((d) => {
    const other = d.coach_a === id ? d.coach_b : d.coach_a;
    const side = d.sides ? d.sides[id] : null;
    const stake = d.stakes ? d.stakes[id] : null;
    const mine = wordsOrMessage(d.claims && d.claims[id], null, "claim");
    const theirs = wordsOrMessage(d.claims && d.claims[other], null, "claim");
    let result = "not settled yet";
    if (d.status === "resolved") {
      if (d.winner === id) result = "won";
      else if (d.winner === other) result = "lost";
      else result = d.outcome ? String(d.outcome).replace(/_/g, " ") : "settled without a winner";
    }
    return {
      id: d.id || null, // CR3: the docket entry's room page (/system/docket/<id>/), when the producer assigned one
      status: d.status,
      versus: nameOf(other),
      opened: dayInWords(d.opened_date),
      settles: dayInWords(d.resolution_date),
      settled: dayInWords(d.resolved_date),
      criterion: criterionWords(d.criterion) || "not published",
      side: side === true ? "said it would hold" : side === false ? "said it would not hold" : "side not recorded",
      stake: stake && typeof stake.brier === "number" ? `its Brier score ${num(stake.brier, 3)} over ${num(stake.brier_n)} calls, frozen at the open` : null,
      actual: typeof d.actual_value === "number" ? num(d.actual_value, 1) : null,
      result,
      mine,
      theirs,
      concession: d.concession || null,
    };
  });
}

/** "Judges picked this coach's own writing in 4 of 8 blind reads (50%)" — carried, with the API's label. */
export function fidelityText(f) {
  if (!f || typeof f.n !== "number" || f.n <= 0 || typeof f.correct !== "number") return null;
  const p = pct(f.accuracy_pct, 1);
  return `Judges picked this coach's own writing in ${num(f.correct)} of ${num(f.n)} blind reads${p ? ` (${p})` : ""}${f.distinguishability ? ` — “${String(f.distinguishability).replace(/_/g, " ")}”, as the platform labels it` : ""}.`;
}

/** The voice spec's served lines, labelled; empty lines are left out. */
export function voiceRows(v) {
  if (!v) return [];
  return [
    ["Tone", v.tone],
    ["How it writes", v.style],
    ["Before it calls a trend", v.evidence_threshold],
    ["Bold claims", v.bold_claims],
    ["When it revises", v.revision_style],
    ["How it says it is unsure", v.uncertainty_style],
  ].filter(([, t]) => typeof t === "string" && t.trim());
}

/** The coach's calls grouped by the day each was made, newest day first; each call keeps its own verdict word. */
export function callsByDay(predictions) {
  const byDay = new Map();
  for (const p of predictions || []) {
    if (!p || !p.logged_date) continue;
    if (!byDay.has(p.logged_date)) byDay.set(p.logged_date, []);
    byDay.get(p.logged_date).push(p);
  }
  return [...byDay.entries()]
    .sort((a, b) => (a[0] < b[0] ? 1 : -1))
    .map(([date, calls]) => ({
      date,
      day: dayInWords(date, { weekday: true }),
      calls: calls
        .slice()
        .sort((a, b) => String(a.id).localeCompare(String(b.id)))
        .map((p) => ({ p, word: callOutcome(p.status), disputed: isDisputed(p), corrected: (p.corrections || []).length > 0 })),
    }));
}

/** "wrong → right" for a correction's verdicts, in the call-outcome words; a missing side is "not recorded". */
export function correctionArrow(c) {
  const a = c && c.original_status ? callOutcome(c.original_status) : "not recorded";
  const b = c && c.corrected_status ? callOutcome(c.corrected_status) : "not recorded";
  return `${a} → ${b}`;
}

/**
 * The record a reader meets on the coach's record page: the calibration file's entry for this coach (its Wilson
 * interval, its comparison with a simple guess), labelled AS FIRST GRADED — no re-verified split is served per coach,
 * so this is never a validated headline. Falls back to the coach page's served record line; null when neither exists.
 */
export function coachRecord(calCoach, card) {
  if (calCoach && Number.isInteger(calCoach.n)) {
    return {
      from: "calibration",
      line: `${kOfN(calCoach.confirmed, calCoach.n)}, as first graded`,
      pct: pct(calCoach.accuracy_pct),
      interval: intervalText(calCoach.accuracy_ci95) || "no interval served",
      skill: (((calCoach.comparison || {}).skill) || {}).sentence || null,
      records: (calCoach.comparison || {}).records || null,
      calibration: v2Answers(calCoach.assessment_v2), // calibration-v2 (owner 2026-11-09): three answers, never the v1 label
      underReview: Number.isInteger(calCoach.under_review) ? calCoach.under_review : 0,
      quality: calCoach.quality || null,
      lifetime: calCoach.lifetime || null,
    };
  }
  if (card && Number.isInteger(card.n)) {
    return {
      from: "coach",
      line: `${kOfN(card.right, card.n)}, as first graded`,
      pct: null,
      interval: "no interval served",
      skill: card.skill_sentence || null,
      records: card.records || null,
      calibration: [],
      underReview: 0,
      quality: null,
      lifetime: null,
    };
  }
  return null;
}
