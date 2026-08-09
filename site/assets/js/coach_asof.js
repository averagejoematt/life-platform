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

// #2333 — the same honest reading, for the cross-coach ensemble digest.
// coach_ensemble_digest stamps `_fallback: true` on a digest produced without
// the LLM (budget-paused at tier >= 1, ADR-125 — the common case, not the
// rare one). /api/coach_analysis and the observatory renderer both propagate
// that mark as `ensemble_fallback` so a template-generated cross-coach read
// never renders indistinguishably from a genuine one. STRICTLY `=== true` —
// same absent-is-unknown discipline as regenerationPaused() above.
export function ensembleFallback(payload) {
  return !!payload && payload.ensemble_fallback === true;
}

// #2383 — the as-of stamp for a WEEKLY AI-authored band (the tensions band and
// the integrator's call it carries — the EXPERT#integrator digest). Same honest-
// dating copy as coachAsOf, but staleness derives from the WRITER's cadence
// (weekly synthesis; the record's own TTL is 8 days), never the daily 48h
// window — a mid-week argument is current, not "pending". No `paused` argument:
// this writer has no budget-guard feature gate and no fallback path (a failed
// synthesis writes nothing), so the honest states are dated / dated-stale /
// undated — and an undated band must not render (datableTensions below).
const WEEKLY_STALE_HOURS = 8 * 24; // the writer's cadence + the record's TTL

export function weeklyAsOf(generatedAt) {
  const d = generatedAt ? new Date(generatedAt) : null;
  if (!d || isNaN(d.getTime())) return "";
  const dateStr = d.toLocaleDateString("en-US", { timeZone: PT_TZ, month: "short", day: "numeric" });
  return (Date.now() - d.getTime()) / 36e5 > WEEKLY_STALE_HOURS ? `as of ${dateStr} — next refresh pending` : `as of ${dateStr}`;
}

// #2383 — the tensions band REFUSES to render argument prose it cannot date: a
// tension with position text but no parseable generated_at is dropped (the band
// falls back to its honest-empty copy), so a paused/stale week's argument can
// never read as today's live coaching. The substance filter matches the
// historical tensionsHTML one (position_a / position_b / summary). Absent-field
// discipline mirrors regenerationPaused above: during an API-deploy/site-deploy
// race the field is UNKNOWN — the band renders its honest-empty state, never a
// fabricated date and never undated prose.
export function datableTensions(tensions) {
  return (Array.isArray(tensions) ? tensions : []).filter((t) => {
    if (!t || !(t.position_a || t.position_b || t.summary)) return false;
    const d = t.generated_at ? new Date(t.generated_at) : null;
    return !!d && !isNaN(d.getTime());
  });
}
