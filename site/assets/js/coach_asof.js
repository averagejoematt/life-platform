// coach_asof.js — the #802 (R22-CONTENT-03) honest "as of / refresh paused"
// disclosure for a coach narrative, extracted from coaching.js so it is unit-
// testable (#1971 — the daily_line.js idiom: shared copy logic lives in an
// importable leaf module, the page module composes it).
//
// budget_guard (ADR-063/125) can pause narrative regeneration at tier >= 2 —
// when it does, a served read is a HELD read from before the pause, not
// today's, and the site must say so rather than present it tense-free.
// Dates render in Pacific (site convention).

const PT_TZ = "America/Los_Angeles";

export function coachAsOf(generatedAt, paused) {
  const d = generatedAt ? new Date(generatedAt) : null;
  const valid = d && !isNaN(d.getTime());
  const dateStr = valid ? d.toLocaleDateString("en-US", { timeZone: PT_TZ, month: "short", day: "numeric" }) : "";
  if (paused) return dateStr ? `as of ${dateStr} — refresh paused (budget guard)` : "refresh paused (budget guard)";
  if (valid && (Date.now() - d.getTime()) / 36e5 > 48) return `as of ${dateStr} — next refresh pending`;
  return dateStr ? `as of ${dateStr}` : "";
}

// #1971 — the one honest reading of an API payload's `regeneration_paused`
// field. STRICTLY `=== true`: an ABSENT field is UNKNOWN, not "not paused" —
// the exact state during an API-deploy/site-deploy race (the site half
// auto-deploys on merge; the site-api half rides the owner's flush) — and an
// unknown must render NOTHING NEW, never a fabricated pause banner and never
// a crash. Anything other than the boolean true (absent, null, "true", 1)
// therefore reads as not-paused, which renders exactly what the page rendered
// before the field existed.
export function regenerationPaused(payload) {
  return !!payload && payload.regeneration_paused === true;
}
