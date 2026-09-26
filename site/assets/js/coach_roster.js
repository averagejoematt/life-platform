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

/*
  #4215 — the scorecard's retired seats. The training seat retired at the cycle-13
  genesis (ADR-153), but the cycle-17 pre-registration sealed two calls in its name
  about 18 hours before #3520's cast guard went live. Sealed calls cannot be edited
  (#1378) and hiding them would break ADR-104, so the scorecard keeps them — labelled,
  in their own group, never interleaved with the live cast. Before this, both
  scorecard lists in coaching.js built every by_coach key into one list and a stranger
  met "Dr. Sarah Chen" as a ninth current coach.

  The page never decides who is retired: the flag is the persona registry's, served on
  each /api/predictions row (and on by_coach once the server carries it, #4215's server
  box). evidence_intelligence.js's `_retiredTag` reads the same flag from /api/calibration.
*/

/** The set of bare coach ids the served payload marks retired. */
export function retiredSeats(data) {
  const out = new Set();
  const byc = (data && data.by_coach) || {};
  for (const cid of Object.keys(byc)) if (byc[cid] && byc[cid].retired === true) out.add(cid);
  for (const p of (data && data.predictions) || []) if (p && p.retired === true && p.coach_id) out.add(String(p.coach_id));
  return out;
}

/**
 * The scorecard's coach rows, split: `live` (the current cast, sorted by decided calls
 * this season then career) and `retired` (same order, rendered apart and labelled).
 * A coach with neither a season nor a career record is omitted, as before (#1376).
 */
export function scorecardSeats(data) {
  const byc = (data && data.by_coach) || {};
  const retired = retiredSeats(data);
  const ids = Object.keys(byc)
    .filter((c) => byc[c] && (byc[c].total || (byc[c].lifetime && byc[c].lifetime.total)))
    .sort((a, b) => (byc[b].decided || 0) - (byc[a].decided || 0) || ((byc[b].lifetime && byc[b].lifetime.decided) || 0) - ((byc[a].lifetime && byc[a].lifetime.decided) || 0));
  return { live: ids.filter((c) => !retired.has(c)), retired: ids.filter((c) => retired.has(c)) };
}

/** Why a retired seat still has rows: "retired seat · 2 sealed calls from this cycle's
 *  pre-registration, graded like any other" — or, with no calls this season, the career
 *  record that stays on file. */
export function retiredSeatNote(cid, data) {
  const byc = (data && data.by_coach) || {};
  const c = byc[cid] || {};
  const sealed = ((data && data.predictions) || []).filter((p) => p && p.coach_id === cid && p.pre_registered === true).length;
  const n = sealed || c.total || 0;
  if (n > 0) {
    const what = sealed ? "sealed call" : "call";
    return `retired seat · ${n} ${what}${n === 1 ? "" : "s"}${sealed ? " from this cycle's pre-registration" : " this cycle"}, graded like any other`;
  }
  return "retired seat · career record kept on file";
}
