// summary_provenance.js — what a coach summary was built from, as of when, and the corrections beside it
// (owner ruling 2026-11-03: "Include provenance and an as-of timestamp … available to the reader where useful,
// not merely stored internally"; "Add dated corrections rather than rewriting what was originally said").
//
// The API serves, beside every judged summary (/api/coaching-dashboard coaches[], /api/coach_analysis,
// /api/coach/<id> stance; lambdas/web/derived_summary_freshness.py):
//   summary_state        "current" | "superseded_by_correction" | "unverified"
//   summary_as_of        an ISO instant
//   derived_from         {built_from: "coach_read" | "ledger_records", as_of, predictions: [ids] | null, predictions_not_public}
//   summary_corrections  [{prediction_id | null, original_status, corrected_status, corrected_at, explanation}]
// Pure: strings in, HTML string out. Every value is escaped; a field the API did not serve renders nothing
// (an API deploy racing the site deploy shows exactly what showed before). Proven in tests/js/summary_provenance.test.mjs.

const OUTCOME = {
  confirmed: "right",
  refuted: "wrong",
  expired: "could not be checked",
  inconclusive: "inconclusive",
  pending: "open",
  observation: "not graded",
  observational: "not graded",
};
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

const escHTML = (s) =>
  String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

/** "2026-11-03T18:55:07Z" → "3 November 2026"; anything else → "". */
export function dayWords(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ""));
  if (!m) return "";
  const mo = Number(m[2]);
  return mo >= 1 && mo <= 12 ? `${Number(m[3])} ${MONTHS[mo - 1]} ${m[1]}` : "";
}

export function outcomeWords(status) {
  return OUTCOME[status] || String(status || "");
}

/** The one-line provenance under a summary: as-of, and what it was built from. "" when not served. */
export function provenanceLine(c) {
  if (!c || !c.summary_state) return "";
  const df = c.derived_from || {};
  const when = dayWords(c.summary_as_of || df.as_of);
  if (c.summary_state === "unverified") return "Not shown: this read could not be checked against the ledger just now.";
  if (c.summary_state === "superseded_by_correction") {
    const was = dayWords(df.superseded_read_as_of);
    return `Built from the ledger's records${when ? `, as of ${when}` : ""}${was ? ` · the read of ${was} waits to be rewritten` : ""}.`;
  }
  const n = Array.isArray(df.predictions) ? df.predictions.length + (df.predictions_not_public || 0) : null;
  const from = n == null ? "the coach's own read" : `the coach's read, built from ${n} call${n === 1 ? "" : "s"} on the ledger`;
  return `Written ${when || "on a day not recorded"} · ${from}.`;
}

/** One dated correction line per served correction, the registered explanation verbatim. */
export function correctionLines(c, ledgerHref) {
  const list = (c && Array.isArray(c.summary_corrections) ? c.summary_corrections : []).filter((x) => x && typeof x === "object");
  return list.map((x) => {
    const day = dayWords(x.corrected_at) || "a date not recorded";
    const head = x.original_status
      ? `Corrected ${day}: a call graded ${outcomeWords(x.original_status)} is now ${outcomeWords(x.corrected_status)}.`
      : `The ledger holds the call this names as ${outcomeWords(x.corrected_status)}.`;
    const link = x.prediction_id && typeof ledgerHref === "function" ? ledgerHref(x.prediction_id) : null;
    return { text: `${head}${x.explanation ? ` ${x.explanation}` : ""}`, href: link || null };
  });
}

/** The provenance + corrections block as HTML (escaped). `cls` prefixes the class names. */
/** `inline: true` renders <span>s and no links — for a slot inside a button or a link (phrasing content only). */
export function summaryProvenanceHTML(c, { cls = "sp", ledgerHref = null, src = "", inline = false } = {}) {
  const line = provenanceLine(c);
  const notes = correctionLines(c, inline ? null : ledgerHref);
  if (!line && !notes.length) return "";
  const tag = inline ? "span" : "p";
  const s = src ? ` data-src="${escHTML(src)}"` : "";
  let h = line ? `<${tag} class="${escHTML(cls)}-asof provenance"${s}>${escHTML(line)}</${tag}>` : "";
  for (const n of notes) {
    h += `<${tag} class="${escHTML(cls)}-correction correction" role="note">${escHTML(n.text)}${n.href ? ` <a href="${escHTML(n.href)}">The call on the ledger</a>` : ""}</${tag}>`;
  }
  return h;
}

/** Dated grade corrections beside a dated, verbatim trail entry (`grade_corrections` on /api/coach/<id>
 *  recent_outputs[] and stance_history[]). The entry's own words are never touched. */
export function trailCorrectionsHTML(entry, { cls = "ce" } = {}) {
  const list = entry && Array.isArray(entry.grade_corrections) ? entry.grade_corrections : [];
  return correctionLines({ summary_corrections: list })
    .map((n) => `<p class="${escHTML(cls)}-correction correction" role="note">${escHTML(n.text)}</p>`)
    .join("");
}
