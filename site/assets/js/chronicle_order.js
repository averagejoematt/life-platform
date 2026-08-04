/*
  chronicle_order.js — the one "newest first" comparator for chronicle/journal
  post records (#1988).
  ----------------------------------------------------------------------------
  posts.json (served by the chronicle feed builder, lambdas/emails/
  chronicle_render.py::publish_to_journal + its restart-pipeline counterpart
  deploy/restart_leadin_pages.py) already arrives newest-first by date. This
  module exists so story.js's client-side list can never independently drift
  from the server's tie-break rule for two posts sharing the SAME date — the
  case a "newest first" label gets provably wrong if the tie is broken by
  insertion order instead of narrative sequence (e.g. same-date Prologue Part
  II and Part III: the finale, Part III, must read ABOVE the earlier Part II).

  Both sides derive the tie-break from the SAME explicit `sequence` field the
  manifest now carries (the (date, sk)-derived ordinal that already numbers
  "Prologue · Part N" correctly) — never from array position. `week` is kept
  only as a last-resort fallback for a stale, pre-regen manifest snapshot that
  predates the `sequence` field.
*/

export function compareChronicleNewestFirst(a, b) {
  const ad = a && a.date ? a.date : "";
  const bd = b && b.date ? b.date : "";
  if (ad !== bd) return ad < bd ? 1 : -1;
  const aseq = a && (a.sequence ?? a.week) != null ? Number(a.sequence ?? a.week) : 0;
  const bseq = b && (b.sequence ?? b.week) != null ? Number(b.sequence ?? b.week) : 0;
  return bseq - aseq;
}

export function sortChronicleNewestFirst(posts) {
  return Array.isArray(posts) ? [...posts].sort(compareChronicleNewestFirst) : [];
}
