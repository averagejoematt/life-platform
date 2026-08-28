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

// 2026-08-27 — the DAY NUMBER is part of the dateline, not decoration.
//
// A coach's frozen prose dates ITSELF in experiment days ("I'm ten days into
// this restart with you — Day 10 as of today"), because that is the frame the
// coach is written in. A dateline in calendar days alone ("as of Aug 26") does
// not reconcile that sentence: the reader would have to know that Aug 26 was
// Day 10 to hear "Day 10" as history rather than as a claim about today. While
// regeneration is paused the gap grows by one day EVERY day, and on 2026-08-27
// a Day-10 sentence served on Day 11 tripped the gating visual-QA judge on
// /coaching/by-coach/#physical_coach and auto-rolled the site back.
//
// So the dateline carries BOTH frames — "as of Aug 26 · Day 10" — and the
// frozen "Day 10" inside the prose is then correctly datelined rather than
// silently re-asserted as current. `asOfDayN` is the API's derived
// `as_of_day_n`; anything that is not a positive integer is UNKNOWN and renders
// NOTHING (the same absent-is-unknown discipline as regenerationPaused below —
// a wrong day number would be strictly worse than no day number).
function dayLabel(asOfDayN) {
  return Number.isInteger(asOfDayN) && asOfDayN > 0 ? `Day ${asOfDayN}` : "";
}

export function coachAsOf(generatedAt, paused, asOfDayN) {
  const d = generatedAt ? new Date(generatedAt) : null;
  const valid = d && !isNaN(d.getTime());
  const dateStr = valid ? d.toLocaleDateString("en-US", { timeZone: PT_TZ, month: "short", day: "numeric" }) : "";
  const stamp = [dateStr ? `as of ${dateStr}` : "", dayLabel(asOfDayN)].filter(Boolean).join(" · ");
  if (paused) return stamp ? `${stamp} — refresh paused (budget guard)` : "refresh paused (budget guard)";
  if (valid && (Date.now() - d.getTime()) / 36e5 > 48) return `${stamp} — next refresh pending`;
  return stamp;
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
//
// #3252 — the DAY NUMBER, for the same reason coachAsOf carries one. The
// integrator's weekly call is the block a reader meets first on /method/board/ and
// on /coaching/'s week lens, and its prose dates ITSELF in experiment days ("he's
// been eleven days into the cycle with no active logging"). A calendar date alone
// does not reconcile that sentence — the reader would have to know that Aug 27 was
// Day 11 — and while the record is held the sentence keeps asserting its frozen day
// as today's. `asOfDayN` is the API's derived `as_of_day_n`; anything that is not a
// positive integer is UNKNOWN and renders nothing (a wrong day number is strictly
// worse than none). The argument is OPTIONAL so every existing call site keeps its
// exact previous output.
const WEEKLY_STALE_HOURS = 8 * 24; // the writer's cadence + the record's TTL

export function weeklyAsOf(generatedAt, asOfDayN) {
  const d = generatedAt ? new Date(generatedAt) : null;
  if (!d || isNaN(d.getTime())) return "";
  const dateStr = d.toLocaleDateString("en-US", { timeZone: PT_TZ, month: "short", day: "numeric" });
  const stamp = [`as of ${dateStr}`, dayLabel(asOfDayN)].filter(Boolean).join(" · ");
  return (Date.now() - d.getTime()) / 36e5 > WEEKLY_STALE_HOURS ? `${stamp} — next refresh pending` : stamp;
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
