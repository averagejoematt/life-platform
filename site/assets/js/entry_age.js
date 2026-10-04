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

// #4182 — the compact date LABEL: "Fri Sep 25" (short weekday, short month). Where
// dayInWords() is the prose spelling every fold SENTENCE uses, this is the one spelling
// for compact chart labels, captions and kickers — same UTC-noon pin, so the two never
// disagree about which calendar day a served date names. coach_today.js's calendarDay()
// delegates here so its many callers keep one import path.
export function dayLabel(dateStr) {
  const iso = String(dateStr || "").slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return "";
  const d = new Date(_utcNoon(iso));
  if (isNaN(d.getTime())) return "";
  const wd = d.toLocaleDateString("en-US", { timeZone: "UTC", weekday: "short" });
  const md = d.toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric" });
  return `${wd} ${md}`;
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

// #4182 — the loop close's return trigger on every page ("…the write-up lands Wednesday,
// September 30"). The SAME rule as the story door's nextWriteUpText — one source for the
// date, only the sentence frame differs: a held draft or a paused cadence keeps its own
// served words. "" when nothing is served (the static fallback copy then stands).
export function loopReturnText(cad, pending) {
  const t = nextWriteUpText(cad, pending);
  const m = /^Next write-up: (.+)$/.exec(t);
  return m ? `the write-up lands ${m[1]}` : t;
}

// #4182 (R6 fix 4; R5's twenty-week test) — the ONE spelling of the next weigh-in on every
// v7 page (Home, This week, Today, Follow), so no page can print a past day as "due". The
// rule: the day after the last weigh-in is the next one, and it is "due" while it is on or
// after the page's data-through day (`throughDate`, the PT day the page's data runs to) —
// so a last weigh-in of through − 1 reads "due <the data-through day>", spelled as the day,
// never as "today". Once that day is BEFORE the data-through day the honest line is the
// silence, counted: "no weigh-in since <last weigh-in> — N days" (N = through − last, so
// always ≥ 2). `day` is the ISO the caller puts in <time datetime> and the margin: the due
// day in the first case, the last weigh-in in the second. Both "" when the last weigh-in is
// unusable. An unusable `throughDate` cannot judge lateness, so it takes the due branch.
// Callers name the served field in data-src (…journey.last_weighin_date), never "+ 1 day".
export function nextWeighInText(lastWeighinDate, throughDate, { capital = false } = {}) {
  const last = String(lastWeighinDate || "").slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(last) || !Number.isFinite(_utcNoon(last))) return { text: "", day: "" };
  const due = new Date(_utcNoon(last) + 86400000).toISOString().slice(0, 10);
  const through = String(throughDate || "").slice(0, 10);
  const cap = (t) => (capital ? t.charAt(0).toUpperCase() + t.slice(1) : t);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(through) || due >= through) return { text: cap(`the next weigh-in is due ${dayInWords(due)}`), day: due };
  const n = Math.round((_utcNoon(through) - _utcNoon(last)) / 86400000);
  return { text: cap(`no weigh-in since ${dayInWords(last)} — ${n} day${n === 1 ? "" : "s"}`), day: last };
}

// #4329 (R7 fix 5) — the ONE spelling of the engine's date to goal on the v7 pages (Home, His
// numbers). "Wednesday, June 9" with no year reads, in October, as a day that has passed; and
// a single day is more precision than a projection has. The reader gets the month, the year
// and the engine's own range: "At this rate the goal lands around June 2027 — between May and
// September 2027." From /api/journey `projected_goal_date` (+ `_earliest` / `_latest`); the
// range is dropped when either bound is unserved or both fall in the projected month. ""
// when no date is served — the caller prints its own absence line.
const _monthYear = (iso) => {
  const d = new Date(_utcNoon(String(iso || "").slice(0, 10)));
  if (!/^\d{4}-\d{2}-\d{2}/.test(String(iso || "")) || isNaN(d.getTime())) return null;
  return { month: d.toLocaleDateString("en-US", { timeZone: "UTC", month: "long" }), year: d.getUTCFullYear() };
};
export function goalWindowText(journey) {
  const j = journey || {};
  const mid = _monthYear(j.projected_goal_date);
  if (!mid) return "";
  const lo = _monthYear(j.projected_goal_date_earliest);
  const hi = _monthYear(j.projected_goal_date_latest);
  const same = (a, b) => a.month === b.month && a.year === b.year;
  let range = "";
  if (lo && hi && !(same(lo, mid) && same(hi, mid))) {
    range = lo.year === hi.year ? ` — between ${lo.month} and ${hi.month} ${hi.year}` : ` — between ${lo.month} ${lo.year} and ${hi.month} ${hi.year}`;
  }
  return `At this rate the goal lands around ${mid.month} ${mid.year}${range}.`;
}

// #4219 — how many Pacific calendar days an open coach ask is past its `due` date. The
// cockpit served an ask due September 19 as "the one ask" on September 26 with nothing
// saying it was late. A served `days_overdue` (the issue's server-side box) wins when it
// is a number; otherwise it is ptDaysAgo(due) on the #2506 PT clock. 0 when due today or
// later; null when `due` is unusable (a lateness we cannot substantiate is never printed).
export function daysOverdue(action, now = new Date()) {
  if (!action) return null;
  const served = action.days_overdue;
  if (typeof served === "number" && Number.isFinite(served)) return Math.max(0, Math.round(served));
  const d = ptDaysAgo(action.due, now);
  return d === null ? null : Math.max(0, d);
}

// "7 days late" / "1 day late" — "" when not late.
export function lateWords(days) {
  const n = Number(days);
  return Number.isFinite(n) && n > 0 ? `${n} day${n === 1 ? "" : "s"} late` : "";
}

// #4370 — the real span behind a genesis-clamped `_30d` count. The count is honest (a
// short window understates, never overstates); a fixed "in 30 days" beside it is not —
// on Day 22 there are not 30 days behind it, and the reader-truth judge rightly calls
// that a temporal contradiction. The API names the window (`window_days` + `window_full`
// on /api/training_overview's `training` block). `dayN` is the caller's fallback for a
// payload served before that field existed: the PT day count since Day 1, capped at the
// requested length. Returns null when neither is known — callers then name NO window.
export function servedWindow(block, requested = 30, dayN = null) {
  const wd = Number(block && block.window_days);
  if (block && block.window_days != null && Number.isFinite(wd) && wd > 0) {
    return { days: Math.min(wd, requested), full: block.window_full === true || wd >= requested };
  }
  const dn = Number(dayN);
  if (dayN != null && Number.isFinite(dn) && dn > 0) return { days: Math.min(dn, requested), full: dn >= requested };
  return null;
}

// "in the last 30 days" once the window is whole; "in the 22 days since the experiment
// began" before it.
export function windowPhrase(win, requested = 30) {
  if (!win) return "";
  if (win.full) return `in the last ${requested} days`;
  return `in the ${win.days} day${win.days === 1 ? "" : "s"} since the experiment began`;
}
