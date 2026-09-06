/*
  coach_roster.js — the By-Coach / Team roster list entries (#3517).

  WHY THIS IS ITS OWN MODULE. coaching.js applied `preStart()` PER TAB, not per door:
  the Read tab rendered the honest "their first take lands here once Day 1's numbers
  exist", while `selectSection` enriched the By-Coach and Team rosters with each coach's
  LIVE `position_summary` outside every pre-start gate. On Day 0 of cycle 16 the same
  door therefore said two things at once, and the subtitle it served narrated the FUTURE
  genesis in the past tense ("No weight reading has arrived since the September 5th
  reset"). That is the #949 shape, second specimen.

  The mapping is extracted here so the gate is a testable pure function rather than a
  condition buried in a page module with top-level side effects: coaching.js runs
  `build()` on import, so `tests/js/` can never exercise it directly. `rosterEntries` is
  the whole decision — given the roster and whether the door is pre-start, what does the
  list render — and tests/js/coaching_prestart_3517.test.mjs pins both directions.
*/

/**
 * Roster list entries for the By-Coach / Team tabs.
 *
 * @param {Array} coaches   /api/coach_team's roster (persona_id, name, domain, tier),
 *                          optionally carrying `_live` (the coach's live one-line read).
 * @param {Object} opts     { preStart: truthy when genesis has not arrived }.
 * @returns {Array} [{ id, title, date, sub, tier }] — `sub` is ALWAYS a string.
 */
export function rosterEntries(coaches, opts) {
  const preStart = !!(opts && opts.preStart);
  return (coaches || []).map((c) => ({
    id: c.persona_id,
    title: String(c.name || "").trim(),
    date: c.domain ? String(c.domain).replace(/_/g, " ") : "",
    // Pre-start the subtitle is EMPTY, never the live read: the only board read that
    // exists before genesis is the wiped prior cycle's, and a card subtitle is exactly
    // where a reader meets it first. `|| ""` (not `c._live`) so an un-enriched roster
    // renders the same empty string rather than `undefined`.
    sub: preStart ? "" : c._live || "",
    tier: c.tier,
  }));
}
