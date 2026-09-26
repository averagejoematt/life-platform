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

// #4182 — a served calendar date in words, the doors' one spelling: "Tuesday, September 22"
// (`{ weekday: false }` → "September 22"). Pinned to UTC noon so no viewer's offset can move
// it a day — the same trick ptDaysAgo uses. "" when the date is unusable: an ISO string
// never falls through to the reader.
export function dayInWords(dateStr, { weekday = true } = {}) {
  const iso = String(dateStr || "").slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return "";
  const d = new Date(_utcNoon(iso));
  if (isNaN(d.getTime())) return "";
  const md = d.toLocaleDateString("en-US", { timeZone: "UTC", month: "long", day: "numeric" });
  return weekday ? `${d.toLocaleDateString("en-US", { timeZone: "UTC", weekday: "long" })}, ${md}` : md;
}

// An instant ("2026-09-26T16:46:51Z") as the Pacific calendar day it fell on, in words —
// for a payload's own served-at stamp. "" when unusable.
export function instantDayInWords(instant, opts) {
  const t = Date.parse(String(instant || ""));
  if (!Number.isFinite(t)) return "";
  return dayInWords(PT_DAY.format(new Date(t)), opts);
}

// The ONE freshness line a door carries (#4182 consistency rule): "Data through Friday,
// September 25." — "" when the date is unusable, so an absent stamp prints nothing.
export function dataThrough(dateStr) {
  const w = dayInWords(dateStr);
  return w ? `Data through ${w}.` : "";
}

// Small counts in words for a sentence ("Four experiments"), numerals past ten ("63 ideas").
const _WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];
export function countWord(n, { capital = false } = {}) {
  const v = Number(n);
  if (!Number.isFinite(v)) return "";
  const w = Number.isInteger(v) && v >= 0 && v <= 10 ? _WORDS[v] : v.toLocaleString("en-US");
  return capital ? w.charAt(0).toUpperCase() + w.slice(1) : w;
}

// #4182 — the weekly write-up's return trigger: "Next write-up: Wednesday, September 30",
// from the served /api/content_cadence `chronicle.next_date`. The served display string
// (lambdas/common/content_cadence.py) carries a process clause — "…publishes once Matthew
// reviews and approves the draft" — that is cut here, on the client; the server copy is
// not rewritten. A held draft (`pending`, written onto posts.json) and a paused cadence
// keep their own served words: those ARE the news. "" when nothing is served.
export function nextWriteUpText(cad, pending) {
  if (pending && pending.display) return String(pending.display);
  const c = cad && cad.chronicle;
  if (!c) return "";
  if (!c.paused && c.next_date) {
    const w = dayInWords(c.next_date);
    if (w) return `Next write-up: ${w}`;
  }
  return String(c.display || "").replace(/\s*[—–-]\s*publishes once Matthew reviews and approves the draft\.?\s*$/i, ".").replace(/\.\.$/, ".");
}
