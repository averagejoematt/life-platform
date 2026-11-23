// Dated public corrections to published chapters (#6177, owner rulings 2026-11-22 §3 and §7).
//
// A correction is the platform's, signed "Correction, <date> — Average Joe Matt editorial record", with what the
// chapter published, what the record shows, the evidence and who approved it when. The snapshot's
// chapter_corrections.json carries ONLY the approved ones (the platform's /api/chapters, through
// lambdas/content/chapter_corrections.public_view); this module places them BESIDE a chapter — never inside its text,
// which stays as first published. A superseded correction is still shown, marked as replaced.
//
// The October 2026 editor's notes signed "Margaret Calloway" stay word for word (their audit trail); wherever one
// renders, PERSONA_DISCLOSURE renders beside it. It is pinned equal to the Python constant
// (tests/test_chapter_corrections_6177.py).

import { dayInWords } from "./format.js";
import { CHAPTER_TRUTH_LIVE } from "./chapter_truth.js";

/** The note's last sentence. Off: as before. On (#6177): the claim that the chapter "reads as first published" is not
 *  made — some chapters' text was later revised (a rewrite, a privacy revision, a removed passage), and a page cannot
 *  show which; what is always true is that the note itself changes no word of the text. */
export function footLine(live = CHAPTER_TRUTH_LIVE) {
  return live ? "This note does not change the chapter's text." : "The chapter's text below is unchanged; it reads as first published.";
}

export const PERSONA_DISCLOSURE = "Margaret Calloway is an AI editorial persona of the platform, not a person.";
export const LEGACY_SIGNER = "Margaret Calloway";
export const PLATFORM_SIGNATURE = "Average Joe Matt editorial record";
/** #6193: pass as `edition` to correctionsHtml on the archival first-edition page. */
export const ARCHIVAL_PAGE = Object.freeze({ archival: true });

const esc = (x) => String(x ?? "").replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);

/** True when the rendered text carries a note signed by the legacy persona, so the disclosure goes beside it. */
export function namesLegacyPersona(html) {
  return typeof html === "string" && html.includes(LEGACY_SIGNER);
}

/** A chapter's approved corrections from the snapshot file: the standing ones newest first, then the replaced ones.
 *  An absent file, a file in any other state or a correction not signed by the platform yields nothing. */
export function correctionsFor(doc, chapterId) {
  if (!doc || doc.state !== "ok" || !Array.isArray(doc.corrections)) return [];
  const mine = doc.corrections.filter(
    (c) => c && c.chapter_id === chapterId && typeof c.signature === "string" && c.signature.endsWith(`— ${PLATFORM_SIGNATURE}`) && Array.isArray(c.approvals) && c.approvals.length > 0,
  );
  const newest = (a, b) => (a.dated_on < b.dated_on ? 1 : a.dated_on > b.dated_on ? -1 : a.id < b.id ? 1 : -1);
  return [...mine.filter((c) => !c.superseded_by).sort(newest), ...mine.filter((c) => c.superseded_by).sort(newest)];
}

/** The story list's mark for a chapter with a standing correction: "corrected 25 Oct" (the newest), else null. */
export function rowMark(corrections) {
  const standing = (corrections || []).filter((c) => !c.superseded_by);
  if (!standing.length) return null;
  const c = standing[0];
  return `${c.kind === "qualification" ? "qualified" : "corrected"} ${dayInWords(c.dated_on, { short: true })}`;
}

function approvalWords(c) {
  const days = (c.approvals || []).map((a) => dayInWords(a.on)).filter(Boolean);
  return days.length ? `Approved by Matthew on ${days.join(", then ")}, through the platform's owner-only approval tool.` : "";
}

/** The foot's last sentence: where the text below stands against this correction. Without an edition (#6193) it is the
 *  sentence #6177 shipped, unchanged; with one, it says whether the edition makes the correction. */
function textBelow(c, edition) {
  if (!edition) return footLine(); // #6177: off = "The chapter's text below is unchanged; it reads as first published."
  // #6193 B6: on the archival page the text below is the historical rendering the correction concerns, not the current one
  if (edition === ARCHIVAL_PAGE) return "It concerns the chapter as published; the text below is an archival rendering of it, superseded by the current edition.";
  const carried = Array.isArray(edition.carries) && edition.carries.includes(c.id);
  return carried ? "The text below is a later edition, and it makes this correction." : "It was made to the first edition; the text below is a later edition.";
}

/** One correction as an HTML block, every value escaped. A replaced one says what replaced it. */
export function correctionHtml(c, all = [], edition = null) {
  const by = c.superseded_by ? all.find((x) => x.id === c.superseded_by) : null;
  const replaced = c.superseded_by
    ? `<p class="correction-replaced" data-correction-replaced>Replaced by the ${esc(by ? by.kind : "correction")}${by ? ` of ${esc(dayInWords(by.dated_on))}` : ""}. Kept here as it was published.</p>`
    : "";
  return (
    `<aside class="chapter-correction${c.superseded_by ? " replaced" : ""}" data-correction="${esc(c.id)}" data-kind="${esc(c.kind)}">` +
    `<p class="label correction-signature">${esc(c.signature)}</p>` +
    `<p><b>What the chapter published.</b> ${esc(c.published_said)}</p>` +
    `<p><b>What the record shows.</b> ${esc(c.record_shows)}</p>` +
    `<p class="correction-foot">Evidence: ${esc(c.evidence)} ${esc(approvalWords(c))} ${esc(textBelow(c, edition))}</p>` +
    replaced +
    `</aside>`
  );
}

/** Every correction of a chapter, standing first, as one HTML string ("" when there is none). ``edition`` (#6193): the
 *  served later edition, if any — only the foot's last sentence changes. */
export function correctionsHtml(corrections, edition = null) {
  return (corrections || []).map((c) => correctionHtml(c, corrections, edition)).join("");
}

// For COMPARING only (never emitted): tags stripped until none is left.
const untag = (x) => {
  let prev;
  let out = String(x ?? "");
  do {
    prev = out;
    out = out.replace(/<[^>]*>/g, " ");
  } while (out !== prev);
  return out;
};
const words = (x) =>
  untag(x)
    .replace(/&#39;|&#x27;|&rsquo;|&lsquo;|[’‘]/g, "'")
    .replace(/&quot;|&ldquo;|&rdquo;|[“”]/g, '"')
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ")
    .trim();

/** #6193 (rehearsal ruling §4): on the archival page, each correction with an owner-approved anchor is printed directly
 *  after the paragraph that carries its passage (the platform's signed block, as above the text — never mistakable for a
 *  note of the time), with one line saying which passage it concerns. Returns `{ html, placed }`: the body with the blocks
 *  placed, and the ids placed (the page prints the rest above the text). A passage not found in exactly one paragraph is
 *  not placed. */
export function placeBeside(bodyHtml, anchors, corrections, edition = ARCHIVAL_PAGE) {
  let html = String(bodyHtml || "");
  const placed = [];
  for (const a of anchors || []) {
    const c = (corrections || []).find((x) => x.id === a.correction_id);
    if (!c) continue;
    const blocks = [...html.matchAll(/<(p|blockquote)\b[^>]*>[\s\S]*?<\/\1>/g)].filter((m) => words(m[0]).includes(words(a.passage)));
    if (blocks.length !== 1) continue;
    const end = blocks[0].index + blocks[0][0].length;
    const lead = `<p class="correction-foot" data-correction-anchor>This ${c.kind === "qualification" ? "qualification" : "correction"} concerns the passage above, beginning “${esc(a.passage)}”</p>`;
    const block = correctionHtml(c, corrections, edition).replace(/^<aside class="chapter-correction/, '<aside style="margin:18px 0" data-anchored class="chapter-correction').replace(/<\/aside>$/, `${lead}</aside>`);
    html = html.slice(0, end) + block + html.slice(end);
    placed.push(c.id);
  }
  return { html, placed };
}
