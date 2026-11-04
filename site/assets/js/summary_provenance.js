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

/** The served as-of in words: "3 November 2026, 18:55 UTC" for an instant; the day alone for a bare day. */
export function asOfWords(iso) {
  const day = dayWords(iso);
  if (!day) return "";
  const t = /T(\d{2}:\d{2})/.exec(String(iso || ""));
  return t ? `${day}, ${t[1]} UTC` : day;
}

/** The ledger page of a served call reference ({prediction_id, coach_id}), or null when the ledger does not serve it. */
export function ledgerHref(note) {
  return note && note.prediction_id && note.coach_id ? `/system/ledger/${note.coach_id}-${note.prediction_id}/` : null;
}

/** The one-line provenance under a summary: as-of, and what it was built from. "" when not served. Concise by
 *  design (owner review of #5644): the specific corrections are behind "What changed". */
export function provenanceLine(c) {
  if (!c || !c.summary_state) return "";
  const df = c.derived_from || {};
  if (c.summary_state === "unverified") return "Not shown: this read could not be checked against the ledger just now.";
  const when = dayWords(c.summary_as_of || df.as_of);
  if (c.summary_state === "superseded_by_correction") return `As of ${when || "a day not recorded"} · from the ledger's records.`;
  const n = Array.isArray(df.predictions) ? df.predictions.length + (df.predictions_not_public || 0) : null;
  const from = n == null ? "the coach's own read" : `the coach's read, built from ${n} call${n === 1 ? "" : "s"} on the ledger`;
  return `Written ${when || "on a day not recorded"} · ${from}.`;
}

/** One line per served correction (dated, the registered explanation verbatim) and its ledger link when served. */
export function correctionLines(list) {
  return (Array.isArray(list) ? list : [])
    .filter((x) => x && typeof x === "object")
    .map((x) => {
      const head = x.original_status
        ? `${asOfWords(x.corrected_at) || "A date not recorded"}: a call graded ${outcomeWords(x.original_status)} is now ${outcomeWords(x.corrected_status)}.`
        : `The ledger holds the call this names as ${outcomeWords(x.corrected_status)}.`;
      return { text: `${head}${x.explanation ? ` ${x.explanation}` : ""}`, href: ledgerHref(x) };
    });
}

function detailsHTML(list, cls) {
  const notes = correctionLines(list);
  if (!notes.length) return "";
  const items = notes
    .map((n) => `<li>${escHTML(n.text)}${n.href ? ` <a href="${escHTML(n.href)}">The call on the ledger</a>` : ""}</li>`)
    .join("");
  return `<details class="${escHTML(cls)}-changed"><summary>What changed</summary><ul>${items}</ul></details>`;
}

/** The provenance line + the corrections on demand, as HTML (escaped). `inline: true` renders one <span> and no
 *  disclosure — for a slot inside a button or a link (phrasing content only); the details live one click deeper. */
export function summaryProvenanceHTML(c, { cls = "sp", src = "", inline = false } = {}) {
  const line = provenanceLine(c);
  const s = src ? ` data-src="${escHTML(src)}"` : "";
  if (inline) return line ? `<span class="${escHTML(cls)}-asof provenance"${s}>${escHTML(line)}</span>` : "";
  const more = detailsHTML(c && c.summary_corrections, cls);
  if (!line && !more) return "";
  return (line ? `<p class="${escHTML(cls)}-asof provenance"${s}>${escHTML(line)}</p>` : "") + more;
}

/** Corrections beside a dated, verbatim trail entry (`grade_corrections` on /api/coach/<id> recent_outputs[] and
 *  stance_history[]): one concise note, the specifics on demand. The entry's own words are never touched. */
export function trailCorrectionsHTML(entry, { cls = "ce" } = {}) {
  const list = entry && Array.isArray(entry.grade_corrections) ? entry.grade_corrections : [];
  if (!list.length) return "";
  const dated = list.find((x) => x && x.original_status && x.corrected_at);
  const lead = dated
    ? `Corrected ${dayWords(dated.corrected_at)}: the prediction this refers to has since been re-graded.`
    : "The ledger grades the prediction this refers to differently.";
  return `<p class="${escHTML(cls)}-correction correction" role="note">${escHTML(lead)}</p>` + detailsHTML(list, cls);
}
