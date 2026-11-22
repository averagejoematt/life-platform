// Second editions of published chapters (#6193, owner ruling 2026-11-22 §3).
//
// The snapshot's chapter_editions.json exists ONLY while the platform's switch is on (lambdas/content/chapter_editions.py
// LIVE; scripts/publish_snapshot_chapter_editions.py writes no file otherwise), and carries per chapter the latest
// edition Matthew approved, already through every publication gate, with its fixed platform-signed words: the edition
// line ("Second edition, revised <date>. First published <date>.") and, when he approved one separately, the archival
// rendering of the first edition with its one fixed note. No file = no edition: every page renders as before.
//
// The canonical chapter address serves the edition; /story/<id>/first-edition/ exists only for a chapter whose archival
// rendering was approved, and is noindex, out of the sitemap, and canonical to the chapter's own address.

import { PLATFORM_SIGNATURE } from "./chapter_corrections.js";

export const ARCHIVE_SEGMENT = "first-edition";

const ok = (e) =>
  e &&
  typeof e.chapter_id === "string" &&
  typeof e.body_html === "string" &&
  e.body_html.trim() !== "" &&
  typeof e.edition_line === "string" &&
  typeof e.signature === "string" &&
  e.signature.endsWith(`— ${PLATFORM_SIGNATURE}`) &&
  Array.isArray(e.approvals) &&
  e.approvals.length > 0;

/** A chapter's served edition, or null (no file, another state, nothing for this chapter, or anything malformed). */
export function editionFor(doc, chapterId) {
  if (!doc || doc.state !== "ok" || !Array.isArray(doc.editions)) return null;
  const e = doc.editions.find((x) => x && x.chapter_id === chapterId);
  return ok(e) ? e : null;
}

/** The archival rendering of a chapter's first edition, or null. Only an edition with an approved rendering has one. */
export function archivalFor(doc, chapterId) {
  const e = editionFor(doc, chapterId);
  const a = e && e.archival;
  if (!a || typeof a.body_html !== "string" || !a.body_html.trim() || typeof a.note !== "string" || !String(a.signature || "").endsWith(`— ${PLATFORM_SIGNATURE}`)) return null;
  return a;
}

/** Every chapter id with an archival page to build. */
export function archivalChapterIds(doc) {
  if (!doc || doc.state !== "ok" || !Array.isArray(doc.editions)) return [];
  return doc.editions.map((e) => e && e.chapter_id).filter((id) => typeof id === "string" && archivalFor(doc, id));
}

/** The sitemap's filter: an archival first-edition page is never listed (it is noindex and canonical elsewhere). */
export function notArchivalPage(url) {
  return !new RegExp(`/${ARCHIVE_SEGMENT}/?$`).test(String(url));
}

/** Words and reading minutes for the served text (the exporter's rule: 230 words a minute, at least one). */
export function editionReading(e) {
  const wc = e && Number.isInteger(e.word_count) && e.word_count > 0 ? e.word_count : null;
  return { word_count: wc, read_minutes: wc ? Math.max(1, Math.round(wc / 230)) : null };
}
