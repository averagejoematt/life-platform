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

/* #3525 — which chronicle installment narrates a given date?

   The rule the timeline states: "the soonest week ending ON OR AFTER it" — a
   milestone is narrated by the week it falls in, and that week is published at
   its end. The implementation in dispatches.js ended with `|| posts[0]`, so
   whenever NOTHING was dated on or after the milestone it silently returned the
   NEWEST installment instead. That branch is not an edge case: it is the state of
   the Day-1 milestone in every cycle (the week that narrates Day 1 publishes six
   days later), and of any milestone in the days before a Wednesday publish. Live
   on 2026-09-05 it pointed the Day-1 milestone's "Read Week 1 →" at
   /story/chronicle/#2026-09-04 — the previous cycle's Prologue, presented as the
   week that narrates Day 1. The honest-absence branch already existed downstream
   ("see more" / no link) and was structurally unreachable while `posts` was
   non-empty.

   `genesis` (the running cycle's start — /api/journey `started_date`) adds the
   second rule: a milestone and the installment that narrates it must sit on the
   SAME side of the genesis line. A prior cycle's installment cannot narrate this
   cycle's Day 1, and this cycle's installments cannot narrate a carried-forward
   pre-genesis lead-in (ADR-077 `--keep-chronicle`).

   Returns null when nothing qualifies — the caller then SAYS there is no
   installment yet, rather than linking whichever one is plausible.            */
export function postForDate(posts, date, genesis) {
  const d = String(date == null ? "" : date).slice(0, 10);
  if (!d) return null;
  const g = genesis ? String(genesis).slice(0, 10) : "";
  const side = g ? d >= g : null;
  let best = null;
  for (const p of Array.isArray(posts) ? posts : []) {
    if (!p || !p.date) continue;
    const pd = String(p.date).slice(0, 10);
    if (g && (pd >= g) !== side) continue;
    if (pd < d) continue;
    if (!best || pd < String(best.date).slice(0, 10)) best = p;
  }
  return best;
}
