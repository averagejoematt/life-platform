// ck_terms.js — the trade terms a coach's served words use, each with its plain line (#4586).
// The coach page glosses every one that appears (ck_coach.js termsHTML / glossLines); the front
// page quotes no line that uses one (ck_front.js plainLanguage, round 3 of the 10-17 red team).
// One list, two readers: a term added here is glossed on the coach page AND kept off the front.
export const TERMS = [
  // One unit for recovery on every kit page (site-to-A round 1): the score is printed as a percentage.
  [/\brecovery\b/i, "Recovery", "his wrist strap’s morning score, as a percentage"],
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
