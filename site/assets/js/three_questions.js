/*
  three_questions.js — the cockpit's first screen (#4182, panel ruling 2(ii)).
  ----------------------------------------------------------------------------
  Three plain questions a reader — and Matthew himself — asks every morning, answered
  in third person from fields the API already serves:

    How's the week?  /api/snapshot → journey  (lost_lbs, weighin_count, current weight,
                     weekly_rate_lbs + its CI, rate_provisional, week_n)
    Last night?      /api/snapshot → vitals   (sleep_hours, recovery_pct, hrv_ms vs
                     hrv_avg_ms over hrv_avg_window_days, n = hrv_avg_n, night_of)
    Today?           /api/routine (archetype, counts, pushed, target_date/days_out) +
                     /api/nutrition_overview (latest_protein_g on latest_date; the
                     protein floor cleared on protein_floor_hit_days of days_logged) +
                     /api/coaching-dashboard open_actions[0] ("the one ask" — omitted
                     when the list is empty; never invented)

  Rules (ADR-104/105): every number carries its date, n or interval; a missing field
  DROPS ITS CLAUSE (never a dash); this module formats and compares served values —
  it computes no new statistic. Pure functions returning HTML strings, so node --test
  can pin them against a saved live payload without a DOM.
*/

import { dfn } from "/assets/js/orient.js";

const PT = "America/Los_Angeles";
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"];

export const GLOSS = {
  provisional: "Early: too few weeks of weigh-ins for the rate to be trusted yet. The range is the engine's interval around it.",
  recovery: "Whoop's 0–100% estimate of how ready his body is, built from heart-rate variability, resting heart rate and sleep.",
  HRV: "Heart rate variability — the millisecond-level variation between heartbeats; a higher number usually signals a better-recovered autonomic nervous system.",
  floor: "The minimum daily protein his plan sets.",
};

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Absent (null/undefined/""/non-finite) → null. Never coerces a missing value to 0. */
function num(x) {
  if (x == null || x === "" || typeof x === "boolean") return null;
  const n = Number(x);
  return Number.isFinite(n) ? n : null;
}

/** "2026-09-25" → "Sep 25"; anything else → "". */
export function fmtDay(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ""));
  return m ? `${MON[+m[2] - 1]} ${+m[3]}` : "";
}

const one = (n) => (Math.round(n * 10) / 10).toFixed(1);
const signed = (n) => (n < 0 ? `−${one(Math.abs(n))}` : one(n));
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
// A number never wraps away from its unit ("182 / g" at 390px): join them with a no-break space.
const NB = "\u00a0";

/** Unwrap the snapshot's per-block envelope ({_meta, journey:{…}}) or accept the bare block. */
export function unwrap(block, key) {
  if (!block || typeof block !== "object") return null;
  return block[key] && typeof block[key] === "object" ? block[key] : block;
}

/* ── How's the week? ─────────────────────────────────────────────────────── */
export function weekLine(j) {
  if (!j || j.pre_start) return "";
  const out = [];
  const lost = num(j.lost_lbs);
  const n = num(j.weighin_count);
  const cw = num(j.current_weight_lbs);
  if (lost != null && n != null && n >= 2) {
    const since = fmtDay(j.started_date);
    let s = `${lost >= 0 ? "Down" : "Up"} ${one(Math.abs(lost))}${NB}lb${since ? ` since ${since}` : ""}, over ${plural(n, "weigh-in")}`;
    const on = fmtDay(j.last_weighin_date);
    if (cw != null && on) s += `; ${one(cw)}${NB}lb on ${on}`;
    out.push(`${s}.`);
  } else if (cw != null && fmtDay(j.last_weighin_date)) {
    out.push(`${one(cw)}${NB}lb on ${fmtDay(j.last_weighin_date)}.`);
  }
  const rate = num(j.weekly_rate_lbs);
  if (rate != null) {
    const lo = num(j.weekly_rate_ci_low), hi = num(j.weekly_rate_ci_high);
    const range = lo != null && hi != null ? `the range is ${signed(lo)} to ${signed(hi)}` : "";
    if (j.rate_provisional) {
      const wk = num(j.week_n);
      const few = wk != null && wk >= 1 && wk < WORDS.length ? `${WORDS[wk]} week${wk === 1 ? "" : "s"} is too few to trust it` : "too few weeks to trust it";
      out.push(`The weekly rate is about ${signed(rate)}${NB}lb a week, but ${dfn("provisional", GLOSS.provisional)} — ${few}${range ? `; ${range}` : ""}.`);
    } else {
      out.push(`The weekly rate is about ${signed(rate)}${NB}lb a week${range ? `; ${range}` : ""}.`);
    }
  }
  return out.join(" ");
}

/* ── Last night? ─────────────────────────────────────────────────────────── */
export function nightLine(v) {
  if (!v || v.time_travel) return "";
  const bits = [];
  const slp = num(v.sleep_hours);
  if (slp != null) bits.push(`${one(slp)}${NB}h asleep`);
  const rec = num(v.recovery_pct);
  if (rec != null) bits.push(`${dfn("recovery", GLOSS.recovery)} ${Math.round(rec)}%`);
  const hrv = num(v.hrv_ms);
  if (hrv != null) {
    const avg = num(v.hrv_avg_ms), n = num(v.hrv_avg_n), win = num(v.hrv_avg_window_days);
    let s = `${dfn("HRV", GLOSS.HRV)} ${esc(String(hrv))}${NB}ms`;
    if (avg != null && n != null) s += ` vs his ${win != null ? `${win}-day ` : ""}average of ${esc(String(avg))} (n=${n})`;
    bits.push(s);
  }
  if (!bits.length) return "";
  const night = fmtDay(v.night_of);
  return `${bits.join("; ")}.${night ? ` The night of ${night}.` : ""}`;
}

/* ── Today? ──────────────────────────────────────────────────────────────── */
const ARCH = { upper: "upper body", lower: "lower body", full: "full body", full_body: "full body" };
function archetypeWords(a) {
  const k = String(a || "").toLowerCase();
  return ARCH[k] || k.replace(/_/g, " ");
}
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
const isBad = (v) => v == null || /^\s*$|^n\/a$|^\[.*\]$/i.test(String(v));

export function sessionLine(rt) {
  const r = rt && rt.routine;
  if (!r || isBad(r.archetype) || (rt && rt.pre_start)) return "";
  const type = archetypeWords(r.archetype);
  const nEx = num(r.exercise_count), nSets = num(r.total_sets);
  const counts = [nEx ? plural(nEx, "exercise") : "", nSets ? plural(nSets, "set") : ""].filter(Boolean).join(", ");
  const dOut = num(r.days_out);
  const when = fmtDay(r.target_date);
  let lead;
  if (dOut === 0) lead = `${cap(type)} today`;
  else if (dOut != null && dOut > 0 && when) lead = `Next session, ${when}: ${type}`;
  else if (when) lead = `Last session on the sheet, ${when}: ${type}`;
  else return "";
  const pushed = r.pushed === true && dOut != null && dOut >= 0 ? ", already in Hevy" : "";
  return `${esc(lead)}${counts ? ` — ${counts}` : ""}${pushed}.`;
}

export function proteinLine(nut) {
  const n = unwrap(nut, "nutrition");
  if (!n) return "";
  const g = num(n.latest_protein_g);
  const day = fmtDay(n.latest_date);
  const parts = [];
  if (g != null && day) parts.push(`Protein on ${day}: ${Math.round(g)}${NB}g`);
  const floor = num(n.protein_floor_g), hit = num(n.protein_floor_hit_days), logged = num(n.days_logged);
  if (floor != null && hit != null && logged) {
    parts.push(`the ${Math.round(floor)}${NB}g ${dfn("floor", GLOSS.floor)} was cleared on ${hit} of ${logged} logged days`);
  }
  if (!parts.length) return "";
  const s = parts.join("; ");
  return `${s[0].toUpperCase()}${s.slice(1)}.`;
}

/** "The one ask": the soonest-due open commitment a coach set (open_actions is sorted
 *  soonest-due-first by the API, #4187). The coach's own words, quoted — the page may
 *  frame a coach, never rewrite one. Empty list → "" (the line is omitted). */
export function askLine(dash) {
  const a = dash && Array.isArray(dash.open_actions) ? dash.open_actions[0] : null;
  if (!a || isBad(a.text)) return "";
  const who = isBad(a.coach_name) ? "" : String(a.coach_name);
  const asked = fmtDay(a.asked_on), due = fmtDay(a.due);
  const meta = [who, asked, due ? `due ${due}` : ""].filter(Boolean).join(", ");
  return `<span class="tq-ask-k">The one ask:</span> “${esc(String(a.text).trim())}”${meta ? ` — ${esc(meta)}` : ""}.`;
}

/* ── The single freshness line ───────────────────────────────────────────── */
/** "Friday · Day 20 · data through Sep 25" — the latest of the served data dates the
 *  first screen actually prints (vitals, weigh-in, food log). A comparison, not a
 *  computation; each block still carries its own date. */
export function freshLine({ journey, vitals, nutrition, now = new Date() } = {}) {
  const n = unwrap(nutrition, "nutrition");
  const dates = [vitals && vitals.as_of_date, journey && journey.last_weighin_date, n && n.latest_date]
    .map((d) => String(d || "").slice(0, 10))
    .filter((d) => /^\d{4}-\d{2}-\d{2}$/.test(d))
    .sort();
  const bits = [];
  try { bits.push(now.toLocaleDateString("en-US", { timeZone: PT, weekday: "long" })); } catch (e) { /* no Intl tz */ }
  const day = num(journey && journey.day_n);
  if (day != null && day >= 1 && !(journey && journey.pre_start)) bits.push(`Day ${day}`);
  if (dates.length) bits.push(`data through ${fmtDay(dates[dates.length - 1])}`);
  return bits.join(" · ");
}

/* ── The engine-vs-log contradiction, printed beside the pillar (ruling 2(iii)) ── */
/** When the engine scores eating near zero or marks its behaviors absent while the food
 *  log itself is full, say both, side by side. Only served fields; "" otherwise. */
export function nutritionPillarNote(pillar, nutrition) {
  const n = unwrap(nutrition, "nutrition");
  if (!pillar || !n || pillar.not_instrumented) return "";
  const score = num(pillar.raw_score);
  const absent = Array.isArray(pillar.absent_behaviors) ? pillar.absent_behaviors.length : 0;
  const logged = num(n.days_logged);
  if (score == null || !logged || (score >= 10 && !absent)) return "";
  const through = fmtDay(n.latest_date);
  return (
    `The engine scored eating ${one(score)} of 100${absent ? `, with ${plural(absent, "behavior")} marked absent` : ""}; ` +
    `the food log shows ${logged} days logged${through ? ` through ${through}` : ""}.`
  );
}
