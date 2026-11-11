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

// ── CR2's two public-safe sources (owner ruling 2026-11-09, third, D and E) ──────────────────────────────────────────
// (D) the owner-approved historical words — the sealed day-one calls and the lead's approved daily reads, served by
//     /api/coach_room_words row by row; every other historical coach text stays unpublished.
// (E) the public-safe coaching brief — /api/coach_brief, six sections kept apart; the first cycle is the policy's.
// Both are CARRIED: an absent source (the route dark or not answering) is stated as absent, never shown as "none".

/** The sentence under the approved words, the same on every coach: what they are and what stays withheld. */
export const APPROVED_WORDS_NOTE =
  "Published by the owner's approval, item by item, after a check of what each was written from. Each is shown only while its stored words are unchanged since that check. Every other past word of this coach stays unpublished.";

/** The approved historical words of one coach: {state, calls, reads, approvedOn}. `state` is "ok" (served — the lists
 *  may be empty, meaning nothing of this coach's was approved) or "absent" (not served for this snapshot). */
export function approvedWords(entry) {
  const w = entry && entry.approved_words;
  if (!w || w.state !== "ok") return { state: "absent", calls: [], reads: [], approvedOn: null, window: null };
  const win = w.lead_window;
  return {
    state: "ok",
    approvedOn: dayInWords(w.approved_at) || null,
    // how many reads were WRITTEN in the checked window, served or not — the page says "n of written", never a bare n
    window:
      win && Number.isInteger(win.written) && dayInWords(win.from) && dayInWords(win.to)
        ? { written: win.written, from: dayInWords(win.from), to: dayInWords(win.to) }
        : null,
    calls: (w.sealed_calls || [])
      .filter((c) => c && typeof c.claim === "string" && c.claim.trim())
      .map((c) => ({
        id: c.prediction_id || null,
        claim: c.claim,
        said: c.logged_date || null,
        day: dayInWords(c.logged_date) || null,
        status: c.status || null,
        settled: c.settled_date || null,
        word: callOutcome(c.status),
        metric: c.metric ? String(c.metric).replace(/_/g, " ") : null,
      })),
    reads: (w.lead_reads || [])
      .filter((r) => r && typeof r.text === "string" && r.text.trim() && r.date)
      .map((r) => ({
        text: r.text,
        said: r.date,
        day: dayInWords(r.date, { weekday: true }),
        written: instantInWords(r.generated_at),
        through: dayInWords(r.data_through) || null,
        cited: (r.cited || []).map((c) => ({ metric: c.metric, value: datesInWords(c.value), asOf: dayInWords(c.as_of) || null })),
      })),
  };
}

/** The heading and the coverage line for the approved reads: "21 of the 28 daily reads written ..." when the window
 *  is served (and is no smaller than the list), else the bare count. Owner ruling 2026-11-11 (8): a sparse historical
 *  section must not look more complete than the evidence supports. */
export function readsCoverage(w) {
  const n = (w && w.reads && w.reads.length) || 0;
  const win = w && w.window;
  const noun = (k) => (k === 1 ? "read" : "reads");
  if (!win || win.written < n) return { heading: `${n} earlier ${noun(n)}`, line: null };
  const rest = win.written - n;
  return {
    heading: `${n} of ${win.written} earlier ${noun(win.written)}`,
    line:
      `${n} of the ${win.written} daily ${noun(win.written)} written between ${win.from} and ${win.to} ${n === 1 ? "is" : "are"} published here.` +
      (rest > 0 ? ` The other ${rest} ${rest === 1 ? "is" : "are"} not published. A day with no read here is a gap in what is shown, not a quiet day.` : ""),
  };
}

/** The coach's ledger calls with an approved call's words in place of "not published" — matched by the stored
 *  prediction id (the ledger object's id is `<coach>-<prediction id>`), for this coach's calls only. A call with its
 *  own served words keeps them; nothing else changes. */
export function withApprovedClaims(predictions, entry) {
  const calls = approvedWords(entry).calls.filter((c) => c.id);
  if (!calls.length) return predictions || [];
  return (predictions || []).map((p) => {
    if (!p || (typeof p.claim === "string" && p.claim.trim() && !p.claim_withheld)) return p;
    const hit = calls.find((c) => typeof p.id === "string" && p.id.endsWith(`-${c.id}`));
    return hit ? { ...p, claim: hit.claim, claim_withheld: null, approved: true } : p;
  });
}

const BRIEF_ACTION = {
  recorded: "recorded",
  no_record: "no reading in the window",
  pending: "the window has not closed",
  not_recorded: "not recorded",
  not_measured: "no check was set, so nothing is measured",
};

/** "the week of 16 November" for a cycle's Monday. */
export function weekOf(cycle) {
  const d = dayInWords(cycle, { short: false });
  return d ? `the week of ${d.replace(/ \d{4}$/, "")}` : null;
}

/** The public brief of one coach: {state, emptyText, latest, earlier}. `state`: "ok" with a brief, "due" (served, none
 *  yet — the first is due), "none" (served, none, and the first cycle has passed), "absent" (not served). */
export function briefView(entry, fetchedAt = null) {
  const b = entry && entry.public_briefs;
  const first = b && b.first_cycle ? weekOf(b.first_cycle) : null;
  if (!b || b.state !== "ok") {
    return { state: "absent", emptyText: "No public brief is served for this coach.", latest: null, earlier: [], firstWeek: first };
  }
  const briefs = (b.briefs || []).filter((x) => x && x.cycle);
  if (!briefs.length) {
    const before = first && (!fetchedAt || String(fetchedAt).slice(0, 10) < String(b.first_cycle));
    return before
      ? { state: "due", emptyText: `The first public brief arrives ${first}.`, latest: null, earlier: [], firstWeek: first }
      : { state: "none", emptyText: "No public brief has been published for this coach yet.", latest: null, earlier: [], firstWeek: first };
  }
  const view = (x) => {
    const obs = new Map((x.observations || []).map((o) => [o.id, o]));
    return {
      week: weekOf(x.cycle),
      through: dayInWords(x.data_through) || null,
      written: instantInWords(x.generated_at),
      said: x.cycle,
      observations: (x.observations || []).map((o) => ({
        label: o.label,
        unit: o.unit || "",
        last7: o.last7 && o.last7.mean != null ? `${o.last7.mean} ${o.unit || ""}`.trim() : "—",
        last7n: o.last7 ? o.last7.n : null,
        prior7: o.prior7 && o.prior7.mean != null ? `${o.prior7.mean} ${o.unit || ""}`.trim() : "—",
        last28: o.last28 && o.last28.mean != null ? `${o.last28.mean} ${o.unit || ""}`.trim() : "—",
        latest: o.latest && o.latest.value != null ? `${o.latest.value} ${o.unit || ""}`.trim() : "—",
        latestDay: o.latest ? dayInWords(o.latest.date) : null,
      })),
      interpretations: (x.interpretations || []).map((i) => ({
        text: i.text,
        rests: (i.cites || []).map((id) => (obs.get(id) || {}).label).filter(Boolean),
      })),
      predictions: (x.predictions || []).map((p) => ({
        id: p.id,
        claim: p.claim,
        status: p.status || "pending",
        settled: p.outcome_date || null,
        confidence: typeof p.confidence === "number" ? `${Math.round(p.confidence * 100)}% confidence` : null,
        rationale: p.rationale || null,
        rule: datesInWords(((x.evaluation_criteria || []).find((c) => c.prediction === p.id) || {}).rule_sentence || "") || null,
      })),
      recommendations: (x.recommendations || []).map((r) => {
        const a = (x.owner_actions || []).find((o) => o.recommendation_id === r.id) || null;
        let did = BRIEF_ACTION.not_recorded;
        if (a && a.state === "recorded" && a.days_with_data != null) {
          did = `${a.days_meeting ?? 0} of ${a.days_with_data} days with a reading met the check`;
        } else if (a && BRIEF_ACTION[a.state]) did = BRIEF_ACTION[a.state];
        return { text: r.text, rationale: r.rationale || null, did };
      }),
      revisions: (x.revisions || []).map((v) => ({ text: v.text, reason: v.reason || null, week: weekOf(v.revised_in_cycle) })),
    };
  };
  return { state: "ok", emptyText: null, latest: view(briefs[0]), earlier: briefs.slice(1).map(view), firstWeek: first };
}

/** The brief's four-word summary for the arrival row: "2 calls · 1 recommendation" or the empty state's short form. */
export function briefFact(view) {
  if (!view || view.state === "absent") return { line: "none served", sub: "" };
  if (view.state === "due") return { line: `first due ${view.firstWeek.replace(/^the /, "")}`, sub: "public-safe, weekly" };
  if (view.state === "none") return { line: "none published yet", sub: "public-safe, weekly" };
  const l = view.latest;
  const n = (k, one) => `${l[k].length} ${l[k].length === 1 ? one : `${one}s`}`;
  return { line: l.week.replace(/^the /, ""), sub: [n("predictions", "call"), n("recommendations", "recommendation")].join(" · ") };
}
