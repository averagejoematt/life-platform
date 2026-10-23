// ck_terms.js — the trade terms a coach's served words use, each with its plain line (#4586).
// The coach page glosses every one that appears (ck_coach.js termsHTML / glossLines); the front
// page quotes no line that uses one (ck_front.js plainLanguage, round 3 of the 10-17 red team).
// One list, two readers: a term added here is glossed on the coach page AND kept off the front.
// THE recovery unit when no body serves one (re-grade 2026-10-18): the route's own string, trimmed —
// prediction_reason.MEASURE_UNITS serves " out of 100" beside every recovery measure (PR #4964), so the
// band, the day page, the trend and the call card all print "62 out of 100" with or without it served.
export const RECOVERY_UNIT = "out of 100";
export const TERMS = [
  // One unit for recovery on every kit page (site-to-A round 1, re-graded 2026-10-18): the score is printed out of 100, as served.
  [/\brecovery\b/i, "Recovery", "his wrist strap’s morning score out of 100"],
  [/\bHRV\b|heart-rate variability/i, "HRV", "heart-rate variability: how much the gap between heartbeats changes overnight, as the wrist strap measures it"],
  [/deep[- ]sleep|slow-wave/i, "Deep sleep", "also called slow-wave sleep: the share of the night spent in the deepest stage"],
  [/\bREM\b|dreaming sleep/i, "REM", "the dreaming stage of sleep"],
  [/\bEWMA\b|running average/i, "Running average", "also written EWMA: an average that counts recent days more than older ones"],
  [/(seven|7)-(night|day) average/i, "Seven-day average", "the average of the last seven readings"],
  [/zone 2/i, "Zone 2", "steady, easy cardio, such as a brisk walk"],
  [/regression[- ]to[- ](the[- ])?mean|mean reversion/i, "Regression to the mean", "an unusual reading tends to be followed by a more ordinary one"],
  [/\bDEXA\b/i, "DEXA", "a body scan that measures fat, muscle and bone"],
  [/\bCGM\b/i, "CGM", "a worn sensor that reads blood sugar through the day"],
];
