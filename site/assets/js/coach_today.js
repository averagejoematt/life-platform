// coach_today.js — the coaching door's first screen: ONE read, dated in words (#4182, #4188).
//
// The door used to open on a tutorial paragraph and then on the integrator's WEEKLY call,
// served unlabelled on a Friday (4.6 days old, two figures wrong by then). The panel's
// ruling (epic #4182, ruling 2(iv)) is one read at the top, the week's call labelled as
// the week's, and a read older than 48 h saying so in its first line — with what moved
// since computed from served endpoints, never from the read.
//
// Pure functions only (the coach_asof.js / daily_line.js idiom): coaching.js composes
// them, tests/js/coach_today_4182.test.mjs pins them. Every function that depends on the
// clock takes `now` explicitly, so no fixture rots on the wall clock (#3535).
//
// Two honesty rules are load-bearing here:
//   * the served coach text is NEVER edited — this module only chooses, dates and glosses
//     it (panel §4 item 6: "the page may gloss a coach; it may not rewrite one");
//   * every timestamp is in words and Pacific ("written Thursday 10:10 AM PT"), never the
//     machine form "as of 2026-09-21" (vocabulary ruling vii-6).

const PT = "America/Los_Angeles";
export const READ_STALE_HOURS = 48; // older than this, the read is demoted beneath a banner
export const READ_OFF_FIRST_SCREEN_DAYS = 7; // older than this, it leaves the first screen

function toDate(iso) {
  const d = iso ? new Date(iso) : null;
  return d && !isNaN(d.getTime()) ? d : null;
}
const nowMs = (now) => (now instanceof Date ? now.getTime() : Number(now));

// PT calendar date (YYYY-MM-DD) of an instant — the platform's canonical clock (#2506).
export function ptDate(iso) {
  const d = toDate(iso);
  return d ? d.toLocaleDateString("en-CA", { timeZone: PT }) : "";
}

// The selection rule (the brief for #4182): the freshest staff read whose text is served.
// A read with no parseable timestamp is never chosen — an undatable read cannot be put
// first under a "written" stamp (the #2383 absent-is-unknown discipline).
export function pickTodaysRead(coaches) {
  let best = null;
  let bestT = -Infinity;
  for (const c of Array.isArray(coaches) ? coaches : []) {
    if (!c || !String(c.position_summary || "").trim()) continue;
    const d = toDate(c.analysis_generated_at);
    if (!d) continue;
    if (d.getTime() > bestT) {
      best = c;
      bestT = d.getTime();
    }
  }
  return best;
}

// #4182 — THE SELECTION CHAIN. "Freshest" alone resolved to whichever coach the daily
// batch ran LAST (all seven are written within ~10 minutes), i.e. the same coach every
// day regardless of merit. The chain is deterministic and every pick states its reason
// on the page (a mono provenance line under the byline):
//   1. the open ask — the coach who owns open_actions[0] (the soonest-due live ask),
//      so the ask renders WITH its author's read. Requires that coach to have a served,
//      datable read; otherwise fall through (a byline over no text is not a read).
//   2. the best checked record — among reads written within 24 h of the newest one, the
//      coach with the highest THIS-CYCLE accuracy_pct at n >= 10 in /api/calibration
//      (retired seats excluded). Below n = 10 a percentage is noise — Okafor's 100 % is
//      n = 1 — so those coaches are ineligible, however high. Ties -> the newer read. The
//      reason prints "<confirmed> of <n> held up", never a bare percentage (ADR-105).
//   3. the freshest read.
export const RECORD_MIN_N = 10;
export const SAME_BATCH_HOURS = 24;
export function chooseTodaysRead(coaches, openActions, calibration) {
  const servable = (Array.isArray(coaches) ? coaches : []).filter(
    (c) => c && String(c.position_summary || "").trim() && toDate(c.analysis_generated_at),
  );
  if (!servable.length) return null;
  const t = (c) => toDate(c.analysis_generated_at).getTime();
  const acts = (Array.isArray(openActions) ? openActions : []).filter((a) => a && String(a.text || "").trim());
  if (acts.length) {
    const owner = servable.find((c) => c.coach_id === acts[0].coach_id);
    if (owner) return { coach: owner, rule: "ask", reason: "chosen: the open ask" };
  }
  const newest = Math.max(...servable.map(t));
  const batch = servable.filter((c) => newest - t(c) <= SAME_BATCH_HOURS * 36e5);
  const rec = {};
  for (const r of (calibration && Array.isArray(calibration.coaches) ? calibration.coaches : [])) {
    if (r && !r.retired && Number(r.n) >= RECORD_MIN_N && r.accuracy_pct != null && !isNaN(Number(r.accuracy_pct))) rec[r.coach_id] = r;
  }
  const ranked = batch
    .filter((c) => rec[c.coach_id])
    .sort((a, b) => Number(rec[b.coach_id].accuracy_pct) - Number(rec[a.coach_id].accuracy_pct) || t(b) - t(a));
  if (ranked.length) {
    const r = rec[ranked[0].coach_id];
    return {
      coach: ranked[0],
      rule: "record",
      reason: `chosen: the best checked record this cycle — ${Number(r.confirmed) || 0} of ${Number(r.n)} held up`,
    };
  }
  return { coach: pickTodaysRead(servable), rule: "freshest", reason: "chosen: the freshest read" };
}

export function ageHours(iso, now) {
  const d = toDate(iso);
  return d ? (nowMs(now) - d.getTime()) / 36e5 : null;
}

// "fresh" (<= 48 h) · "stale" (> 48 h: banner first) · "old" (> 7 d: off the first screen)
// · "unknown" (no parseable timestamp).
export function freshness(iso, now) {
  const h = ageHours(iso, now);
  if (h == null) return "unknown";
  if (h > READ_OFF_FIRST_SCREEN_DAYS * 24) return "old";
  if (h > READ_STALE_HOURS) return "stale";
  return "fresh";
}

export function daysOld(iso, now) {
  const h = ageHours(iso, now);
  return h == null ? null : Math.max(0, Math.floor(h / 24));
}

// "Monday Sep 21"
export function writtenDay(iso) {
  const d = toDate(iso);
  if (!d) return "";
  const wd = d.toLocaleDateString("en-US", { timeZone: PT, weekday: "long" });
  const md = d.toLocaleDateString("en-US", { timeZone: PT, month: "short", day: "numeric" });
  return `${wd} ${md}`;
}

// "written Thursday 10:10 AM PT" — the weekday alone while it is unambiguous (inside a
// week); the date joins it once the read is six days old or more.
export function writtenStamp(iso, now) {
  const d = toDate(iso);
  if (!d) return "";
  const time = d.toLocaleTimeString("en-US", { timeZone: PT, hour: "numeric", minute: "2-digit" });
  const h = ageHours(iso, now);
  const dated = h != null && h >= 6 * 24;
  const day = dated ? `${writtenDay(iso)},` : d.toLocaleDateString("en-US", { timeZone: PT, weekday: "long" });
  return `written ${day} ${time} PT`;
}

// A served calendar date ("2026-10-02", a due date) in words: "Friday Oct 2". Pinned to UTC
// noon so no viewer's offset can move it a day.
export function calendarDay(ymd) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(ymd || ""))) return "";
  const d = new Date(`${ymd}T12:00:00Z`);
  if (isNaN(d.getTime())) return "";
  const wd = d.toLocaleDateString("en-US", { timeZone: "UTC", weekday: "long" });
  const md = d.toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric" });
  return `${wd} ${md}`;
}

// The integrator's weekly call, labelled at its own cadence (#4188).
export function weekCallLabel(iso) {
  const day = writtenDay(iso);
  return day ? `the week's call · written ${day}` : "the week's call";
}

// The /method/board/ cadence line (closes the open half of #4163). The day number is the
// frame the integrator's prose dates itself in (#3252) — rendered only when served.
export function weeklyCadenceLine(iso, asOfDayN) {
  const day = writtenDay(iso);
  if (!day) return "";
  const n = Number.isInteger(asOfDayN) && asOfDayN > 0 ? `, Day ${asOfDayN}` : "";
  return `The integrator's read is weekly — written Mondays; this one is from ${day}${n}.`;
}

const fmtLb = (v) => (Math.round(Number(v) * 10) / 10).toFixed(1);

// The >48 h banner. Its figures come from served series — /api/weight_progress (the
// weigh-ins) and /api/nutrition_overview (the 7-day protein average) — never from the
// read. "Before" is the newest weigh-in dated BEFORE the day the read was written — the
// reads are written from data through the day before, so that is the figure the writer
// saw (the Monday 09-21 call quoted Sunday's 316.9); "after" is the newest weigh-in, shown
// only when it is a later one. Anything missing is left out, never guessed.
export function sinceBanner(iso, now, weights, nutrition) {
  const n = daysOld(iso, now);
  if (n == null) return "";
  const head = `This read is ${n} day${n === 1 ? "" : "s"} old.`;
  const parts = [];
  const written = ptDate(iso);
  const series = (Array.isArray(weights) ? weights : [])
    .filter((w) => w && w.date && w.weight_lbs != null && !isNaN(Number(w.weight_lbs)))
    .slice()
    .sort((a, b) => String(a.date).localeCompare(String(b.date)));
  const before = series.filter((w) => String(w.date) < written).pop();
  const latest = series[series.length - 1];
  if (before && latest && String(latest.date) > String(before.date)) parts.push(`weight ${fmtLb(before.weight_lbs)} → ${fmtLb(latest.weight_lbs)} lb`);
  const p7 = nutrition && (nutrition.pro_7d_avg != null ? nutrition.pro_7d_avg : nutrition.pro_avg_recent_g);
  if (p7 != null && !isNaN(Number(p7))) parts.push(`protein 7-day ${Math.round(Number(p7))} g`);
  return parts.length ? `${head} Since it was written: ${parts.join(", ")}.` : head;
}

// The record line — "33 predictions checked, 17 came true". Counts, not a percentage
// (the editor's rule, panel §2(ix)); it replaces "153 falsifiable calls · 33 decided ·
// 51.5% held up". Nothing decided -> "" (never a zero dressed as a record).
export function recordLine(overall) {
  const o = overall || {};
  const decided = Number(o.decided) || 0;
  if (!decided) return "";
  const hit = Number(o.confirmed) || 0;
  return `${decided} prediction${decided === 1 ? "" : "s"} checked, ${hit} came true`;
}

// Plain-English glosses for the three terms the coaches use most (panel table, ruling
// vii). Rendered as chrome UNDER a coach's read, only for terms the served text actually
// uses — the text itself is never touched. HRV's and EWMA's lines are the site glossary's
// own (site/config/glossary.json, #4035 — tests/js/coach_today_4182.test.mjs pins them
// equal, one definition per term). "recovery" is not a registry term (the registry is
// exact-case acronyms; the word is everyday English everywhere else on the site), so its
// panel wording lives here.
export const READER_GLOSS = [
  { term: "HRV", re: /\bHRV\b/, plain: "Heart rate variability — the millisecond-level variation between heartbeats; a higher number usually signals a better-recovered autonomic nervous system." },
  { term: "recovery", re: /\brecovery\b/i, plain: "Whoop's 0–100 morning score of how rested his body looks." },
  { term: "EWMA", re: /\bEWMA\b/, plain: "Exponentially weighted moving average — a running average that counts recent days more than older ones, so a trend reacts to change without chasing one noisy day." },
];
export function glossesFor(text) {
  const t = String(text || "");
  return READER_GLOSS.filter((g) => g.re.test(t));
}

// The ask under the read — the chosen coach's own open action when it has one, else the
// soonest-due one on the board. `open_actions` is served `[]` until #4187 deploys: then
// this returns null and the slot is omitted, never invented.
export function pickAsk(openActions, coachId) {
  const list = (Array.isArray(openActions) ? openActions : []).filter((a) => a && String(a.text || "").trim());
  return list.find((a) => a.coach_id === coachId) || list[0] || null;
}
