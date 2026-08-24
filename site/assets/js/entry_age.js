// entry_age.js — how old a dated narrative entry is, in Pacific calendar days (#2957).
//
// The chronicle is a weekly serial: the reader always opens on the NEWEST installment,
// and "newest" is routinely days old. On Day 7 of cycle 14 the Day-2 installment was
// the featured read with nothing but its own ISO date to say so, and the reader-truth
// judge read that as a temporal contradiction. It was right — a five-day-old piece
// presented tense-free reads as today's.
//
// WHY THIS IS ITS OWN MODULE. Two renderers show the same entry (dispatches.js runs
// /story/, story.js runs Home's teaser) and they must never disagree about its age,
// so the arithmetic lives in one importable leaf and is unit-tested directly
// (the daily_line.js / coach_asof.js idiom).
//
// WHY THE ARITHMETIC LOOKS LIKE THIS. `Date.parse("YYYY-MM-DD")` is UTC midnight while
// `Date.now()` is an absolute instant, so `round((now - parse(date)) / 86400000)` tips
// over at 12:00 UTC — every Pacific viewer past ~05:00 local read one day too many, and
// this morning's post was announced as "yesterday". The platform's clock is Pacific
// (#2506/#2675) and the canonical fix is #2941's: take today's PT CALENDAR date via
// Intl, then diff two date-only values pinned to UTC noon, so the difference is an
// exact multiple of 86400000 and no DST transition can shift it.

const PT_DAY = new Intl.DateTimeFormat("en-CA", {
  timeZone: "America/Los_Angeles",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});
const _utcNoon = (iso) => Date.parse(`${iso}T12:00:00Z`);

// Whole Pacific calendar days between `dateStr` (YYYY-MM-DD) and today — null when the
// date is unusable. Negative for a future date, which callers treat as "not old".
export function ptDaysAgo(dateStr, now = new Date()) {
  const iso = String(dateStr || "").slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return null;
  const then = _utcNoon(iso);
  if (!Number.isFinite(then)) return null;
  return Math.round((_utcNoon(PT_DAY.format(now)) - then) / 86400000);
}

// The reader-facing suffix for an entry's kicker. "" when the date is unusable — a
// frame we cannot substantiate is worse than no frame. The "archive entry" clause is
// held back until the entry is genuinely no longer current: yesterday's installment is
// dated, not archived, and calling it an archive would be its own small dishonesty.
export function entryAgeSuffix(dateStr, now = new Date()) {
  const days = ptDaysAgo(dateStr, now);
  if (days === null || days < 0) return "";
  if (days === 0) return " · today";
  if (days === 1) return " · yesterday";
  return ` · written ${days} days ago — an archive entry, not today's`;
}
