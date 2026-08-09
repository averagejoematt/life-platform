/*
  absence_read.js — the one honest translation of a pillar's absence state (#2388)
  ----------------------------------------------------------------------------
  PURE. No DOM, no fetch, no imports — so both readers (story.js's family panel and
  cockpit.js's pillar detail) speak the SAME sentence about the same state, and
  tests/js/absence_read_2388.test.mjs can exercise it with a real `await import()`.

  WHY IT EXISTS
  Over a cycle with zero food logs (MacroFactor quiet 45+ days, #2326) the two reader
  surfaces both translated an ADR-104 behavioral zero into a trend verb:

      home family panel   →  "EATING eased off a little"
      cockpit pillar read →  "Nutrition is at 1 and slipping"

  …while the same cockpit printed "MACROFACTOR 44D AGO" three sections above. A family
  reader was told "he's eating slightly less well" when the true sentence is "nothing is
  logged". The engine was never wrong — `data_coverage: 1.0` with an unlogged habit
  scoring 0 at full weight is ADR-104's documented design and must NOT be "fixed". The
  defect was entirely this translation.

  The state comes from the server (`/api/character` → `pillar.absence`, derived in
  `lambdas/health/pillar_absence.py` from each source's OWN registry `stale_hours`).
  It is never re-derived here: a hardcoded staleness window in JS would drift from the
  registry the moment a source's cadence changed, which is the whole reason the
  derivation lives next to the registry.

  Three states, and only one of them silences the trend verb:
    dark    → the pillar's own sources are ALL past their window. Nothing was logged;
              a trend claim is fabricated. Render the absence copy.
    logged  → at least one source is reporting. Normal trend copy.
    unknown → the server could not observe a feeding source. Unknown is never narrated
              as absence — the surface keeps its existing behavior.
*/

// The absence block as served, or null. Tolerates the pre-#2388 payload (a CloudFront-
// cached body from before the API deploy has no `absence` key at all) — that reads as
// no state, and every caller falls through to what it did before.
export function pillarAbsence(pillar) {
  const a = pillar && typeof pillar === "object" ? pillar.absence : null;
  return a && typeof a === "object" && typeof a.state === "string" ? a : null;
}

// True when this pillar's own sources are dark past their registry windows.
export function isDark(pillar) {
  const a = pillarAbsence(pillar);
  return !!a && a.state === "dark";
}

/* The plain-language absence line. Short enough for a family-panel chip, and true:

   - never_logged → NO day-count is attached, deliberately. The #2382 rule: a channel
     with no log anywhere in the window has no "stopped N days ago" event to describe,
     and attaching the window's own age is how "39 days quiet" became "paused four days
     ago" on six live coach cards.
   - paused       → the real measured gap, which IS a transition that happened.
   - otherwise    → the plain state, with the source-dark day count when the server
     measured one (a pillar with no log category never gets a transition kind).
*/
export function absenceLine(pillar, { short = false } = {}) {
  const a = pillarAbsence(pillar);
  if (!a || a.state !== "dark") return null;
  const days = Number.isFinite(a.days_since_last_log) ? a.days_since_last_log : null;
  const dark = Number.isFinite(a.days_dark) ? a.days_dark : null;
  if (a.transition === "never_logged") {
    return short ? "nothing logged this cycle" : "Nothing has been logged for this since the cycle began — there is no trend here to read, only an absence.";
  }
  if (a.transition === "paused" && days != null) {
    return short
      ? `nothing logged for ${days} days`
      : `Last logged ${a.last_log_date} — ${days} days ago. Nothing since, so there is no trend to read, only the gap.`;
  }
  if (dark != null) {
    return short ? `nothing logged for ${dark} days` : `No log has landed for ${dark} days. Nothing to trend — the gap is the finding.`;
  }
  return short ? "nothing logged" : "Nothing is being logged for this right now, so there is no trend to read.";
}

/* The family panel's chip, for the pillars where absence outranks the trend (#2388).

   Returns {txt, state} when the honest answer is an absence, or null when the pillar is
   free to render its normal trend copy. story.js calls this BEFORE its coverage heuristic
   and before any trend verb — the gating decision lives here, not in the DOM module, so
   it is reachable by `await import()` and a sabotage of it fails a test.

   `trendState` is the caller's already-computed "up" | "down" | "flat".
*/
export function familyChip(pillar, trendState) {
  if (isDark(pillar)) return { txt: absenceLine(pillar, { short: true }) || "nothing logged", state: "absent" };
  // Not dark, but the engine flagged behaviors that didn't happen inside the window. The
  // score moved; attributing that move to effort ("eased off a little") credits a trend
  // to days that were simply never logged. Name the absence instead.
  const flagged = pillar && Array.isArray(pillar.absent_behaviors) ? pillar.absent_behaviors.length : 0;
  if (trendState === "down" && flagged) return { txt: "some days went unlogged", state: "absent" };
  return null;
}

/* The cockpit's deterministic pillar read, when no coach analysis is served.

   `label` is the display name, `pillar` the /api/character pillar object. A dark pillar
   gets the absence sentence and NEVER the "is at N and slipping" phrasing — the score is
   real, but "slipping" is a claim about a behavior that produced no data.
*/
export function deterministicPillarRead(label, pillar) {
  const p = pillar && typeof pillar === "object" ? pillar : {};
  const score = Math.round(Number(p.raw_score) || 0);
  const line = absenceLine(p);
  if (line) {
    return `${label} scores ${score} because nothing is being logged for it, not because it declined. ${line} Open the Data door for the components behind the score.`;
  }
  const d = Number(p.xp_delta);
  const dir = !Number.isFinite(d) || d === 0 ? "flat" : d > 0.05 ? "up" : d < -0.05 ? "down" : "flat";
  const moving = dir === "up" ? "climbing" : dir === "down" ? "slipping" : "holding";
  return (
    `${label} is at ${score} and ${moving} (${p.tier || "Foundation"}). ` +
    `Correlative read only — open the Data door for the components behind it.`
  );
}

/* The coach-analysis payload reader (the #2388 cockpit bug).

   `/api/coach_analysis` serves `analysis` as a STRING at the top level, alongside
   `key_recommendation`, `confidence_language` and `data_availability`. cockpit.js did
   `const a = data.analysis || data.coach_analysis || data;` and then read `a.summary`,
   `a.analysis`, `a.read` — every one of them `undefined` on a string — so the served
   coach read was thrown away and the deterministic fallback fired on EVERY pillar that
   had one. This reads the real fields, and still tolerates a nested-object shape.
*/
export function coachPayloadRead(data) {
  const d = data && typeof data === "object" ? data : {};
  const nested = d.analysis && typeof d.analysis === "object" ? d.analysis : d.coach_analysis && typeof d.coach_analysis === "object" ? d.coach_analysis : {};
  const str = (v) => (typeof v === "string" && v.trim() ? v.trim() : "");
  const text = str(d.analysis) || str(nested.summary) || str(nested.analysis) || str(nested.read) || str(d.summary) || str(d.read);
  const action = str(d.key_recommendation) || str(nested.action) || str(nested.recommendation) || str(nested.one_thing) || str(d.action);
  const n = [d.observations, d.n, d.sample_size, nested.observations, nested.n, nested.sample_size].find((v) => typeof v === "number");
  let confidence = "";
  if (typeof n === "number") confidence = n < 12 ? "preliminary pattern" : n < 30 ? "low confidence (n<30)" : `n=${n}`;
  else if (str(d.confidence_language)) confidence = str(d.confidence_language).replace(/_/g, " ");
  return { text, action, confidence };
}
