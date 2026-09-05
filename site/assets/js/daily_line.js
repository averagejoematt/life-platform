/*
  daily_line.js — shared Day-1-safe copy for the home hero and the brief line
  ----------------------------------------------------------------------------
  Two pieces of copy that only reveal their broken branch on Day 1 of a cycle
  live here as PURE functions/constants so tests/js/daily_line.test.mjs can pin
  them (they have no unit owner otherwise — the defect class is "never rendered
  until a zero-delta day").

  #1994 — heroProofLine(): the hero's weight-delta sentence. The zero-delta
  branch used to emit the bare mid-sentence token "even" sentence-initial
  ("even since the start —"), a guaranteed broken fragment on Day 1 of every
  cycle. The delta word is now composed to read as deliberate English in ALL
  three branches (down / up / holding even), in both the multi-weigh-in and
  single-weigh-in templates.

  #1995 — BRIEF_LINE_KICKER: the ONE label for the morning brief's daily line
  (elena_hero_line). The line's deictics ("today"/"tomorrow") are anchored to
  the DATA day — the brief is minted before the render-day has any data (#1251)
  — so a render-day "today" kicker inverts its meaning whenever the line says
  "tomorrow" (on Day 1 the site said "DAY 1 · running now" and "starts
  tomorrow" at once). All three consumers (cockpit, coaching, home) import this
  constant; none may re-anchor the line to the render-day. Guard the SET: the
  unit test scans site/assets/js/ for stray render-day kickers.
*/

// The honest anchor label (#1251 wording, previously cockpit-only). Never
// "today's …" — the line describes the data day, which is yesterday by mint time.
export const BRIEF_LINE_KICKER = "the daily line · yesterday's read · from the morning brief";

/* The three-way delta phrase, safe sentence-initial: "down 3.2 lb" / "up 1.6 lb"
   / "holding even" (never the bare token "even" — #1994). */
export function heroDeltaPhrase(lost) {
  const mag = Math.round(Math.abs(Number(lost)) * 10) / 10;
  return lost > 0.05 ? `down ${mag} lb` : lost < -0.05 ? `up ${mag} lb` : "holding even";
}

/* The hero's second data line, composed from /api/journey. Pure: the caller
   passes dayN (genesisCount) and now (Date.now) so tests control the clock.
   #1225 — "in N days" is a TREND claim; it needs >= 2 weigh-ins spanning the
   stretch. Off a single Day-1 weigh-in we say "since the start" and name the
   lone weigh-in instead (ADR-105). */
export function heroProofLine(journey, dayN, now = Date.now()) {
  const dir = heroDeltaPhrase(Number(journey.lost_lbs));
  const nWeighins = Number(journey.weighin_count) || 0;
  const span = Number(journey.weighin_span_days) || 0;
  // Honest as-of: the day counter ticks live while the weight only moves at
  // weigh-ins — during a quiet stretch the pairing reads false without the anchor date.
  let lwLabel = "";
  let lwMs = NaN;
  if (journey.last_weighin_date) {
    const lw = new Date(`${journey.last_weighin_date}T12:00:00`);
    if (!isNaN(lw.getTime())) {
      lwLabel = lw.toLocaleDateString("en-US", { month: "short", day: "numeric" });
      lwMs = lw.getTime();
    }
  }
  if (nWeighins >= 2 && span >= 1) {
    // A real multi-weigh-in trend — keep the elapsed-days framing, anchored when stale.
    const asof = lwLabel && (now - lwMs) / 86400000 > 1.5 ? ` (last weigh-in ${lwLabel})` : "";
    return `${dir} in ${dayN} days${asof} — the shape of it, every day, just below.`;
  }
  // A single weigh-in: no N-day trend. State it honestly.
  const one = lwLabel ? ` — one weigh-in so far, ${lwLabel}` : " so far";
  return `${dir} since the start${one}. The shape of it, every day, just below.`;
}

/* ── #3524 · the home hub + the stat row ─────────────────────────────────────
   Two more Day-1-only branches, extracted here for the same reason as the two
   above: they are only WRONG in a window nobody browses (launch eve, and the
   morning of Day 1 before the first weigh-in), so nothing ever pinned them.

   dialCopy() — the dial hub renders THREE glyphs (eyebrow / number / caption)
   and only two of them were ever bound. The eyebrow shipped static as "day" in
   site/index.html, so on T−1 the hub read DAY / 1 / DAY TO GO — the same three
   glyphs that mean "Day 1, the experiment is running" the very next morning.
   Composing all three together is the fix: the eyebrow can no longer be left
   behind by a branch, because there is no branch that returns only two.

   journeyFigures() — the "where it started · where it is" row. The pre-start
   branch rewrote `lost` and `progress` to "—" but wrote `current` only when a
   weigh-in existed, so the HTML's own static shimmer survived into the rendered
   page and the row read "— / ··· / —": three placeholder vocabularies in one
   row, the middle one indistinguishable from a widget that failed to load.
   This returns a decision for ALL THREE figures in every state, so a figure
   with no number behind it is always the SAME deliberate absence glyph.       */

// ADR-104's honest-absence glyph for a figure with no measurement behind it.
// One glyph, everywhere in this row — never a second placeholder.
export const ABSENT_FIGURE = "—";

export function dialCopy(pre, dayN, weekN) {
  if (pre) {
    const n = Number(pre.daysUntil);
    const label = pre.startLabel;
    // The eyebrow NAMES the frame in every pre-start branch, so the number under
    // it can never be misread as a day-of-experiment count.
    if (n >= 2) return { eyebrow: "until day 1", num: String(n), cap: `days to go — the experiment begins ${label}` };
    if (n === 1) return { eyebrow: "until day 1", num: "1", cap: `day to go — the experiment begins tomorrow, ${label}` };
    return { eyebrow: "until day 1", num: "0", cap: "the experiment begins today, with the first weigh-in" };
  }
  if (!(Number(dayN) >= 1)) return null;  // no genesis frame yet — leave the shimmer
  const d = Number(dayN);
  return {
    eyebrow: "day",
    num: String(d),
    cap: d === 1 ? "day one of the experiment" : `days into the experiment · week ${weekN}`,
  };
}

export function journeyFigures(journey, pre) {
  const j = journey || {};
  const absent = (cap) => ({ present: false, text: ABSENT_FIGURE, cap });
  const present = () => ({ present: true, text: null, cap: null });
  const cur = j.current_weight_lbs != null ? present() : null;
  if (pre) {
    return {
      // Pre-start there is no baseline delta and no progress by definition — the
      // record has not started. A weigh-in banked before genesis is still real, so
      // `current` keeps its live branch when one exists.
      lost: absent("lbs — counts from Day 1"),
      current: cur || absent(`lbs — first weigh-in ${pre.startLabel}`),
      progress: absent("to goal — counts from Day 1"),
    };
  }
  return {
    lost: j.lost_lbs != null ? present() : absent("lbs — counts from the first weigh-in"),
    current: cur || absent("lbs — awaiting the first weigh-in"),
    progress: j.progress_pct != null ? present() : absent("to goal — counts from the first weigh-in"),
  };
}
