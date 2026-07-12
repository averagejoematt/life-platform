/*
  read_aloud.js — the chronicle's per-article audio join (#1121).
  ----------------------------------------------------------------------------
  One pure function: which read-aloud episode belongs to THIS article?

  The key is the article's publication date — the same globally-unique id the
  story reader already routes by — because week numbers repeat across
  experiment resets (ADR-077): a week-keyed join let a new cycle's "Week N"
  silently inherit the PRIOR cycle's audio. Dates never repeat across cycles,
  so a stale pre-reset feed simply never matches and the article renders with
  no player (honest-empty) instead of another cycle's voice.

  Kept dependency-free so the node fixture test (tests/
  test_chronicle_read_aloud_1121.py) can execute it directly.
*/
export function readAloudFor(ent, episodes) {
  if (!ent || !ent.date) return undefined; // no per-article key → honest-empty
  const list = Array.isArray(episodes) ? episodes : [];
  return list.find((e) => e && e.date && e.url && String(e.date) === String(ent.date));
}
