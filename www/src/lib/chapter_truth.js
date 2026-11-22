// Truthful chapter chrome (#6177, owner rulings 2026-11-22 §6 and §9): the lines a published chapter carries BESIDE its
// prose — the byline, the "coach records as published on" line, the covered days its charts read, and the Moments card
// that quotes its header — say only what the record shows. No word of any chapter changes here.
//
//   1. The byline names how the chapter was published, from the record (`published_via`, scripts/publish_snapshot_chapters.py
//      publication_via): after Matthew's recorded approval, or automatically under the 48-hour rule he had authorised in
//      advance. When the record cannot tell, the byline says nothing about approval. It never claims an approval it
//      cannot show (§6: "Do not falsely imply I personally reviewed every automatically published first edition").
//   2. A chapter whose served text was rewritten after publication (its own editor's note says so) has its quoted coach
//      records dated to the rewrite, not to the first publication (C1).
//   3. A published chapter with no stored covered days (Week 6) reads the days the platform's rule gives every other
//      chapter — the seven days ending on its data date, from Day 1 — instead of silently drawing the program week.
//   4. A Moments card that quotes a chapter's header says the quotation is the chapter as it now reads, points at a
//      standing dated correction, and does not quote a header that states a ratio to, or the value of, a withheld
//      threshold (#5074).
//
// THE SWITCH. Everything here is behind ONE committed constant. `false`: every function returns exactly what the pages
// printed before #6177 (tests/chapter_truth.test.mjs; a recursive dist diff against main is byte-identical). The
// activation is the one-line PR that sets it to `true`; scripts/www_launch_switch.py reads the same line as text for the
// RSS channel line (scripts/v4_build_rss.py), so there is one switch, never two that could disagree. Rollback: set it
// back to `false`.
import { CHAPTER_BYLINE, INDEX_BYLINE, NARRATOR_BYLINE, NARRATOR_WHO } from "./narrator.js";
import { dayInWords } from "./format.js";
import HEADER_REVISIONS from "./chapter_header_revisions.json" with { type: "json" };

/** THE SWITCH — keep it one line: `export const CHAPTER_TRUTH_LIVE = true|false;` (read as text by Python). */
export const CHAPTER_TRUTH_LIVE = false;

/** The byline of a chapter published after his recorded approval. */
export const BYLINE_APPROVAL = `${NARRATOR_BYLINE} Published after Matthew's recorded approval.`;
/** The byline of a chapter the 48-hour sweep published (it ran until 13 November 2026). */
export const BYLINE_RULE = `${NARRATOR_BYLINE} Published automatically under the platform's 48-hour rule, which Matthew had authorised in advance, rather than by a separate approval.`;
/** The story index's line about every chapter. */
export const INDEX_BYLINE_TRUE = `Each chapter is written by ${NARRATOR_WHO}. Earlier chapters were published either after Matthew's approval or automatically under a 48-hour rule he had authorised; each chapter's page says which, where the record shows it. A chapter now publishes only after he approves it.`;


const MONTH = "(?:January|February|March|April|May|June|July|August|September|October|November|December)";
const plain = (html) =>
  String(html || "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&#39;|&#x27;|&rsquo;|’/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ");
// "Editor's note, October 2026 — Margaret Calloway: this installment was rewritten after …" (the season rebuild's note)
const REWRITE_NOTE = new RegExp(`Editor's note(?:,\\s+(${MONTH}\\s+\\d{4}))?[^:]{0,80}:\\s*this (?:installment|prologue|chapter) was rewritten`, "i");

/** `{month}` when the chapter's own text says it was rewritten after publication ("October 2026", or null when the note
 *  names no month), else null. Read off the served body, the one record of the rewrite a page has. */
export function rewriteOf(html) {
  const m = REWRITE_NOTE.exec(plain(html));
  return m ? { month: m[1] || null } : null;
}

/** The chapter's byline. Off: the line every page printed before. On: by the record, or the narrator alone. */
export function chapterByline(c, live = CHAPTER_TRUTH_LIVE) {
  if (!live) return CHAPTER_BYLINE;
  const first = rewriteOf(c && c.body_html) ? "First published" : "Published";
  if (c && c.published_via === "approval") return BYLINE_APPROVAL.replace(" Published ", ` ${first} `);
  if (c && c.published_via === "rule") return BYLINE_RULE.replace(" Published ", ` ${first} `);
  return NARRATOR_BYLINE;
}

/** The story index's byline. */
export function indexByline(live = CHAPTER_TRUTH_LIVE) {
  return live ? INDEX_BYLINE_TRUE : INDEX_BYLINE;
}

/** The first sentence of the line beside a quoted coach record (#6161), or null for no line. Off: "as published on
 *  <day>" exactly as before (null without a publication day). On: a rewritten chapter's records are as of the rewrite. */
export function recordAsOf(c, live = CHAPTER_TRUTH_LIVE) {
  const first = c && c.status === "published" && c.published_at ? dayInWords(c.published_at) : null;
  if (!live) return first ? `Coach records quoted in this chapter are as published on ${first}.` : null;
  if (!c || c.status !== "published") return null;
  const rw = rewriteOf(c.body_html);
  if (!rw) return first ? `Coach records quoted in this chapter are as published on ${first}.` : null;
  const when = rw.month ? `as of its rewrite in ${rw.month}` : "as of a later revision of this chapter";
  return `Coach records quoted in this chapter are ${when}${first ? `, not its first publication on ${first}` : ""}.`;
}

const ISO = /^\d{4}-\d{2}-\d{2}$/;
const ms = (iso) => Date.parse(`${iso}T00:00:00Z`);
const iso = (t) => new Date(t).toISOString().slice(0, 10);

/** The covered days the platform's rule gives a published chapter with none stored: the seven days ending on its data
 *  date, never before Day 1. Every chapter with a stored "Day A to Day B" span equals this rule (Week 1 Day 1–3, Weeks
 *  2–5 and Week 10 the seven days to their dates). Null when the rule cannot be read, or when its days would overlap
 *  another chapter's stored days (then nothing is guessed). */
export function derivedCovers(c, chapters = []) {
  if (!c || c.status !== "published" || !Number.isInteger(c.week) || c.week < 1) return null;
  if (ISO.test(c.covers_start || "") && ISO.test(c.covers_end || "")) return null;
  if (!ISO.test(c.date || "") || !ISO.test(c.week_start || "")) return null;
  const genesis = ms(c.week_start) - 7 * (c.week - 1) * 864e5;
  const end = ms(c.date);
  const start = Math.max(genesis, end - 6 * 864e5);
  if (end < genesis) return null;
  const [a, b] = [iso(start), iso(end)];
  const clash = (chapters || []).some((o) => o && o !== c && o.status === "published" && ISO.test(o.covers_start || "") && ISO.test(o.covers_end || "") && !(b < o.covers_start || a > o.covers_end));
  return clash ? null : { covers_start: a, covers_end: b };
}

/** Fill the derived covered days in place on every published chapter that has none (on only). Returns the ids filled. */
export function applyDerivedCovers(chapters, live = CHAPTER_TRUTH_LIVE) {
  if (!live) return [];
  const filled = [];
  for (const c of chapters || []) {
    const d = derivedCovers(c, chapters);
    if (d) {
      c.covers_start = d.covers_start;
      c.covers_end = d.covers_end;
      filled.push(c.id);
    }
  }
  return filled;
}

// A ratio to, or the value of, a threshold: "more than twice its lean-mass threshold", "3x the line", "a threshold of
// 2.5". The rate flag's line is withheld (#5074), so no card restates it; the card says nothing about what it left out.
const MULT = "(?:twice|double|triple|treble|half|(?:three|four|five)\\s+times|\\d+(?:\\.\\d+)?\\s*(?:x|×|times))";
export const WITHHELD_THRESHOLD = new RegExp(
  `\\b${MULT}(?![\\w])[^.;]{0,60}?\\b(?:threshold|cap|limit|ceiling|line)\\b|\\b(?:threshold|cap|limit|ceiling)\\s+(?:of|at|is|was)\\s+\\d`,
  "i",
);

/** True when a quotation states a ratio to, or the value of, a threshold. */
export function quotesThreshold(text) {
  return WITHHELD_THRESHOLD.test(String(text || ""));
}

/** A Moments card's quotation of a chapter header, or null for none. Off: as before. On: no quotation that restates a
 *  threshold, and the citation says what the quotation is — the summary as revised on its day (applyHeaderRevisions),
 *  or the chapter as it now reads (the snapshot's excerpt is read off today's text). */
export function cardQuote(quote, live = CHAPTER_TRUTH_LIVE, chapter = null) {
  if (!quote || !quote.text) return null;
  if (!live) return { ...quote, citeWords: `${quote.cite}, as published` };
  if (quotesThreshold(quote.text)) return null;
  if (chapter && chapter.header_revised_on && quote.text === chapter.excerpt) {
    return { ...quote, citeWords: `${quote.cite}, summary as revised on ${dayInWords(chapter.header_revised_on)}` };
  }
  return { ...quote, citeWords: `${quote.cite}, as the chapter now reads` };
}

/** The owner-approved replacement summary for a chapter (chapter_header_revisions.json), or null: only while the served
 *  summary still begins with the words it replaces, so a second edition's own summary is never overridden. */
export function revisedHeader(c, table = HEADER_REVISIONS) {
  const h = c && c.status === "published" && table && table.headers ? table.headers[c.id] : null;
  if (!h || typeof h.text !== "string" || typeof h.replaces !== "string" || !h.replaces) return null;
  if (typeof c.excerpt !== "string" || !c.excerpt.startsWith(h.replaces)) return null;
  return { text: h.text, revised_on: ISO.test(table.revised_on || "") ? table.revised_on : null };
}

/** Put the approved replacement summaries in place (on only): `excerpt` and `summary` read the new line everywhere a page
 *  prints a chapter's summary (header, description and og metadata, /story/ rows, the front page, Moments); the served
 *  line is kept as `excerpt_first`, so the chapter page still recognises it at the top of the body. Returns the ids. */
export function applyHeaderRevisions(chapters, live = CHAPTER_TRUTH_LIVE, table = HEADER_REVISIONS) {
  if (!live) return [];
  const done = [];
  for (const c of chapters || []) {
    const r = revisedHeader(c, table);
    if (!r) continue;
    c.excerpt_first = c.excerpt;
    c.excerpt = r.text;
    c.summary = r.text;
    c.header_revised_on = r.revised_on;
    done.push(c.id);
  }
  return done;
}

/** The muted line under a revised summary on the chapter page: "Summary revised on 22 November 2026." (on only). */
export function headerRevisedLine(c, live = CHAPTER_TRUTH_LIVE) {
  return live && c && c.header_revised_on ? `Summary revised on ${dayInWords(c.header_revised_on)}.` : null;
}

/** The line under a card whose chapter carries a standing dated correction (on only): "This chapter carries a dated
 *  correction of 22 November 2026." — null when off or when there is none. `standing` is correctionsFor(...) output. */
export function cardCorrection(standing, live = CHAPTER_TRUTH_LIVE) {
  if (!live) return null;
  const all = (standing || []).filter((x) => x && !x.superseded_by && ISO.test(x.dated_on || ""));
  if (!all.length) return null;
  const kind = (x) => (x.kind === "qualification" ? "qualification" : "correction");
  const kinds = [...new Set(all.map(kind))];
  const newest = all.map((x) => x.dated_on).sort().slice(-1)[0];
  if (all.length === 1) return `This chapter carries a dated ${kinds[0]} of ${dayInWords(newest)}.`;
  const noun = kinds.length > 1 ? "corrections and qualifications" : `${kinds[0]}s`;
  const oneDay = all.every((x) => x.dated_on === newest);
  return `This chapter carries ${all.length} dated ${noun}${oneDay ? " of" : ", the newest of"} ${dayInWords(newest)}.`;
}

/** The Moments page's sentence about its quotations: "every quotation is <this> chapter's own words" — "an approved"
 *  before #6177, "a published" on (some chapters were published by the 48-hour rule, not a separate approval). */
export function momentsQuoteWho(live = CHAPTER_TRUTH_LIVE) {
  return live ? "a published" : "an approved";
}

/** The story-so-far entry: "Each week has its days and, where one was <this>, its installment." */
export function entryVerb(live = CHAPTER_TRUTH_LIVE) {
  return live ? "published" : "approved";
}
