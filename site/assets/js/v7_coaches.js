// v7_coaches.js — "The coaches", v7 page 5 (#4182, plan §2a row 5; Prototype C screen II).
//
// ONE coach's read at the top (chosen by coach_today.js's chain — rule 0 is the lead's daily
// read once served), written time in words, opened by its LEDGER LINES: `latest_checked`
// from /api/coach/<id> (#4230 — the most recent CHECKED call) and the whole
// `report_card.track_record.recent` list as right/wrong lines. Where two disagree,
// /api/coach_docket.open[] as a table with the engine's number between the witnesses. The
// record as "K of N so far" from /api/calibration platform.strata.coaches — never a bare
// percentage (ADR-105), and never a per-coach rate (three producers disagree, plan E4).
//
// Honesty rules that are load-bearing here:
//   * a coach's served words reach the page ONLY through the guarded slots
//     (`position_summary`, `daily`, `recent_outputs[].summary`, `commitments[].text` —
//     #4225 guarantees public register or empty); an empty slot renders as ABSENCE;
//   * `latest_checked.eval_type == "directional"` means `actual_value` is a SLOPE — the
//     line says whether the direction came true and never quotes the slope as a level;
//   * dates are words (entry_age.js), "Data through <day>" once, every number data-src;
//   * no "cycle" / "reset" / "attempt" word (owner ruling 2026-09-26): "since Day 1",
//     "so far", "all time";
//   * a coach whose instrument is dark is NAMED, never QUOTED — the engine's map and verdict
//     (/api/coaches[].instrument / absent / reason, #4217) with /api/source_freshness as the
//     second witness; the reason's date is printed in words.
//
// Pure functions first (tests/js/v7_coaches.test.mjs); run() composes them at the end.

import { chooseTodaysRead, ptDate } from "/assets/js/coach_today.js";
import { dayInWords, dataThrough, countWord } from "/assets/js/entry_age.js";
import { coachComparison } from "/assets/js/coach_comparison.js"; // #4585 — no coach count without what a simple guess scored

const PT = "America/Los_Angeles";
const esc = (s) =>
  String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");

// ── ids ─────────────────────────────────────────────────────────────────────────
// /api/coaching-dashboard and /api/calibration use the short id ("sleep"); /api/coach/<id>,
// /api/coaches and the docket use the persona id ("sleep_coach"). The lead is "eli_marsh" in both.
export function personaId(coachId) {
  const id = String(coachId || "");
  if (!id || id === "eli_marsh" || id.endsWith("_coach")) return id;
  return `${id}_coach`;
}
export function shortId(personaId_) {
  return String(personaId_ || "").replace(/_coach$/, "");
}

// ── words ───────────────────────────────────────────────────────────────────────
const ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"];
const TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"];
// A count in words to ninety-nine; numerals past that ("the n in words").
export function numberWords(n) {
  const v = Number(n);
  if (!Number.isInteger(v) || v < 0) return "";
  if (v < 20) return ONES[v];
  if (v < 100) return TENS[Math.floor(v / 10)] + (v % 10 ? `-${ONES[v % 10]}` : "");
  return v.toLocaleString("en-US");
}

// "Friday, September 25, at one minute past ten in the morning, Pacific time" — the
// written time in words (Prototype C's byline), from an instant.
export function timeInWords(iso) {
  const t = Date.parse(String(iso || ""));
  if (!Number.isFinite(t)) return "";
  const d = new Date(t);
  const day = dayInWords(d.toLocaleDateString("en-CA", { timeZone: PT }));
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: PT, hour: "numeric", minute: "numeric", hour12: false }).formatToParts(d);
  const h24 = Number((parts.find((p) => p.type === "hour") || {}).value) % 24;
  const m = Number((parts.find((p) => p.type === "minute") || {}).value);
  const h12 = h24 % 12 === 0 ? 12 : h24 % 12;
  const when = h24 < 12 ? "in the morning" : h24 < 17 ? "in the afternoon" : "in the evening";
  const hour = h24 === 0 ? "midnight" : h24 === 12 ? "noon" : `${ONES[h12]} ${when}`;
  const mins = m === 0 ? hour : `${numberWords(m)} minute${m === 1 ? "" : "s"} past ${hour}`;
  return `${day}, at ${mins}, Pacific time`;
}

// The engine’s metric names in the reader’s words. Unknown → the name with its underscores
// opened, never hidden. Each BASE metric carries its words and what one reading spans (a
// night or a day); a windowed form — `<base>_7day_avg`, `_14day_avg`, … — is DERIVED from its
// base by rule ("the night’s recovery" → "the seven-night average recovery"), never typed as
// another row (R7 fix 2: `total_protein_g_7day_avg` and `deep_pct_7day_avg` printed raw
// because only two of the windowed forms had a row). tests/js/v7_coaches.test.mjs holds
// every metric of a served docket to words.
const METRIC_BASE = {
  recovery_score: ["the night’s recovery", "night"],
  sleep_duration_hours: ["the night’s hours of sleep", "night"],
  sleep_hours: ["the night’s hours of sleep", "night"],
  total_sleep_hours: ["the night’s hours of sleep", "night"],
  sleep_score: ["the night’s sleep score", "night"],
  hrv: ["heart-rate variability", "night"],
  hrv_ms: ["heart-rate variability", "night"],
  rhr: ["resting heart rate", "night"],
  resting_heart_rate: ["resting heart rate", "night"],
  weight_lbs: ["his weight", "day"],
  weight: ["his weight", "day"],
  total_calories_kcal: ["the day’s calories", "day"],
  calories: ["the day’s calories", "day"],
  total_protein_g: ["the day’s protein, in grams", "day"],
  protein_g: ["the day’s protein, in grams", "day"],
  steps: ["the day’s steps", "day"],
  deep_pct: ["the share of deep sleep", "night"],
  rem_pct: ["the share of dreaming sleep", "night"],
};
const RE_WINDOWED = /^(.+)_(\d+)day_avg$/;
// "" when the metric has no words (neither a base row nor a windowed form of one).
function resolveMetric(metric) {
  const m = String(metric || "");
  if (METRIC_BASE[m]) return METRIC_BASE[m][0];
  const w = RE_WINDOWED.exec(m);
  const base = w && METRIC_BASE[w[1]];
  const n = w ? Number(w[2]) : 0;
  if (!base || !(n > 1)) return "";
  const span = `${numberWords(n)}-${base[1]} average`;
  const words = base[0];
  if (words.startsWith("his ")) return `his ${span} ${words.slice(4)}`;
  return `the ${span} ${words.replace(/^the (night|day)’s /, "").replace(/^the /, "")}`;
}
/** True when the metric resolves to reader words — false is a field name about to print. */
export function metricKnown(metric) {
  return Boolean(resolveMetric(metric));
}
export function metricWords(metric) {
  const m = String(metric || "");
  return resolveMetric(m) || m.replace(/_/g, " ");
}
/** The words split from their unit: "the day’s protein, in grams" → { what: "the day’s protein",
 *  unit: "grams" } — so a sentence can put the unit after the number ("190 grams or better"). */
export function metricParts(metric) {
  const m = /^(.*), in ([a-z]+)$/.exec(metricWords(metric));
  return m ? { what: m[1], unit: m[2] } : { what: metricWords(metric), unit: "" };
}
const COND_WORDS = { lt: "under", lte: "at most", le: "at most", gt: "over", gte: "at or above", ge: "at or above", eq: "at", up: "up", down: "down" };
export function conditionWords(cond) {
  const c = String(cond || "").toLowerCase();
  return COND_WORDS[c] || c;
}
const fmtNum = (v) => {
  const n = Number(v);
  if (!Number.isFinite(n)) return "";
  return Number.isInteger(n) ? String(n) : String(Math.round(n * 10) / 10);
};
const surname = (name) => {
  const w = String(name || "").trim().split(/\s+/);
  return w.length ? w[w.length - 1] : "";
};

// ── the public-text lint (R6 fix 2) ─────────────────────────────────────────────
// A served slot is printed on the main screen only when it reads as public prose: no ISO
// date, no percent sign, no device brand, no "night of" (the model's log-entry opener —
// "On the night of 2026-09-23, Whoop logged…" — R6 named all four). A hit is not rewritten —
// it is folded under <details> "as served", where the reader opens it knowingly. Returns the
// reasons ([] = clean). Applied to every served coach sentence that would reach the main
// screen: `position_summary` and `latest_checked.claim`.
const BRANDS = /\b(Whoop|Hevy|Eight ?Sleep|Withings|Garmin|MacroFactor|Strava|Oura|Apple Health|Habitify|Todoist)\b/;
export function lintPublic(text) {
  const t = String(text || "");
  const why = [];
  if (/\d{4}-\d{2}-\d{2}/.test(t)) why.push("an ISO date");
  if (/\d\s?%/.test(t)) why.push("a percent sign");
  if (BRANDS.test(t)) why.push("a device brand");
  if (/\bnight of\b/i.test(t)) why.push("a “night of” log opener");
  return why;
}

// "Will the seven-night average recovery be 80 or better on Wednesday, October 7?" — the
// question from the docket's CRITERION (engine fields), never from the served topic prose.
const Q_COND = { gte: "or better", ge: "or better", gt: "or more", lte: "or lower", le: "or lower", lt: "under", eq: "exactly" };
export function docketQuestion(criterion, resolutionDate) {
  const c = criterion || {};
  if (!c.metric || c.threshold == null) return "";
  const { what, unit } = metricParts(c.metric);
  const cond = String(c.condition || "").toLowerCase();
  const thr = `${fmtNum(c.threshold)}${unit ? ` ${unit}` : ""}`;
  const when = dayInWords(resolutionDate);
  const on = when ? ` on ${when}` : "";
  if (cond === "lt" || cond === "gt") return `Will ${what} be ${cond === "lt" ? "under" : "over"} ${thr}${on}?`;
  return `Will ${what} be ${thr} ${Q_COND[cond] || ""}${on}?`.replace(/\s+\?/, "?");
}

// ── the ledger line (#4230) ─────────────────────────────────────────────────────
// {claim, created_date, outcome_date, metric, eval_type, condition, threshold, actual_value, status}
// → { verdict: "right"|"wrong", text, checked } — or null (no checked call yet).
export function ledgerLine(lc, who) {
  if (!lc || !lc.status || !["confirmed", "refuted"].includes(String(lc.status).toLowerCase())) return null;
  const right = String(lc.status).toLowerCase() === "confirmed";
  const name = surname(who) || "The coach";
  const made = dayInWords(lc.created_date);
  const on = made ? `On ${made}, ` : "";
  const what = metricWords(lc.metric);
  let text;
  // `rule` is what decided the verdict, for a page that prints the verdict as a tag
  // (#4647); "" when the served row carries none.
  let rule = "";
  if (String(lc.eval_type || "").toLowerCase() === "directional") {
    // actual_value is a slope: say the direction, never the number as a level.
    const dir = conditionWords(lc.condition) || "move";
    rule = RULE_TREND;
    text = `${on}${name} said ${what} would go ${dir} over the checked window — the direction ${right ? "came true" : "did not come true"}.`;
  } else {
    // a point call ("within" a tolerance of the threshold — the grader's own condition word,
    // live on every coach's latest_checked) lands NEAR the number; a bound call sits on
    // one side of it. "would be within 61" is not English (found by render, 2026-09-26).
    const near = String(lc.condition || "").toLowerCase() === "within" || String(lc.eval_type || "").toLowerCase() === "point";
    const cond = conditionWords(lc.condition);
    const thr = fmtNum(lc.threshold);
    const actual = fmtNum(lc.actual_value);
    // the live latest_checked serves no tolerance (the recent[] reason strings carry ±SD);
    // "give or take" prints only if a `tolerance` field is ever served, never from elsewhere
    const give = near && fmtNum(lc.tolerance) ? `, give or take ${fmtNum(lc.tolerance)}` : "";
    if (give) rule = ruleWithin(right, fmtNum(lc.tolerance));
    const call = !thr ? "made a call on it" : near ? `would land near ${thr}${give}` : `would be ${cond} ${thr}`;
    const came = actual ? ` — it came in at ${actual}.` : right ? " — it held." : " — it did not.";
    text = `${on}${name} said ${what} ${call}${came}`;
  }
  const checked = dayInWords(lc.outcome_date);
  return { verdict: right ? "right" : "wrong", text, rule, checked: checked ? `Checked ${checked}.` : "", claim: lc.claim ? String(lc.claim) : "" };
}

// ── the recent list: report_card.track_record.recent[] as right/wrong lines ───────
// Each row is {date, status, metric, reason}; `reason` is the grader's own string. Three
// shapes are read; anything else prints the verdict, the metric and the checked day only.
const RULE_TREND = "by which way the trend went over the checked window";
const ruleWithin = (right, tol) => `${right ? "within" : "not within"} ${tol} either way`;
const RE_VALUE = /^(\w+)=([-\d.]+) on (\d{4}-\d{2}-\d{2}) vs predicted ([-\d.]+)(?: ±([\d.]+))?/;
const RE_TREND = /^(\w+) trend=(\w+) \(slope=([-\d.]+)\), predicted=(\w+)/;
const RE_DOCKET = /^dispute docket resolved: (.+)$/;
// The docket criterion as the grader writes it — "total_calories_kcal_7day_avg >= 2200 on
// 2026-08-10" — into the reader's words: metric in words, the operator in words, the day in
// words. An unparsed criterion prints NOTHING raw (an ISO date and a snake_case metric on
// the main screen were found by render, 2026-09-26): the verdict and the metric only.
const RE_CRIT = /^(\w+)\s*(>=|<=|==|=|>|<)\s*([-\d.]+)(?:\s+on\s+(\d{4}-\d{2}-\d{2}))?\s*$/;
const OP_WORDS = { ">=": "at or above", "<=": "at most", ">": "over", "<": "under", "=": "at", "==": "at" };
export function criterionWords(desc) {
  const m = RE_CRIT.exec(String(desc || "").trim());
  if (!m) return "";
  const day = m[4] ? dayInWords(m[4]) : "";
  return `${metricWords(m[1])} ${OP_WORDS[m[2]]} ${fmtNum(m[3])}${day ? ` on ${day}` : ""}`;
}
export function recentLine(row, who) {
  if (!row || !row.status) return null;
  const st = String(row.status).toLowerCase();
  if (st !== "confirmed" && st !== "refuted") return null;
  const right = st === "confirmed";
  const name = surname(who) || "The coach";
  const reason = String(row.reason || "");
  const checked = dayInWords(row.date);
  let text;
  let rule = "";
  let m;
  if ((m = RE_VALUE.exec(reason))) {
    const what = metricWords(m[1]);
    const give = m[5] ? `, give or take ${fmtNum(m[5])}` : "";
    if (m[5]) rule = ruleWithin(right, fmtNum(m[5]));
    text = `For ${dayInWords(m[3])}, ${name} said ${what} would land near ${fmtNum(m[4])}${give} — it came in at ${fmtNum(m[2])}.`;
  } else if ((m = RE_TREND.exec(reason))) {
    rule = RULE_TREND;
    text = `${name} said ${metricWords(m[1])} would go ${m[4]} over the checked window — it went ${m[2]}.`;
  } else if ((m = RE_DOCKET.exec(reason))) {
    const crit = criterionWords(m[1]);
    rule = "by the question the bet fixed when it opened";
    text = crit ? `A disagreement settled by code: ${crit}.` : `A disagreement settled by code, on ${metricWords(row.metric)}.`;
  } else {
    text = `${name}’s call on ${metricWords(row.metric)}.`;
  }
  return { verdict: right ? "right" : "wrong", text, rule, checked: checked ? `Checked ${checked}.` : "" };
}
export function recentLines(recent, who) {
  return (Array.isArray(recent) ? recent : []).map((r) => recentLine(r, who)).filter(Boolean);
}
export function tally(lines) {
  const right = lines.filter((l) => l.verdict === "right").length;
  return { right, wrong: lines.length - right, n: lines.length };
}

// ── the standing ask: a counted thread over recent_outputs ──────────────────────
// THE RULE, named on the page: a morning whose summary mentions the morning AND a rating,
// note, log, word, check or how he felt. Prototype C's keyword count, one producer
// (/api/coach/<id>.recent_outputs), never a hand number.
export const ASK_RULE = "a summary that mentions the morning and a rating, note, log, word, check or how he felt";
export function askCount(recentOutputs) {
  const outs = (Array.isArray(recentOutputs) ? recentOutputs : []).filter((o) => o && String(o.summary || "").trim());
  const asks = outs.filter((o) => /morning/i.test(o.summary) && /rating|felt|feel|subjective|check|note|log|word/i.test(o.summary));
  return { asks: asks.length, mornings: outs.length, first: outs.length ? outs[outs.length - 1].date : "", last: outs.length ? outs[0].date : "" };
}
// The newest pending commitment with served text — the ask's current form. null when none.
export function standingAsk(commitments) {
  const list = (Array.isArray(commitments) ? commitments : []).filter((c) => c && String(c.text || "").trim() && String(c.status || "") === "pending");
  list.sort((a, b) => String(b.date || "").localeCompare(String(a.date || "")));
  return list[0] || null;
}

// ── instruments: a coach whose sensor is dark is named, not quoted (plan E6 / #4217) ──
// The coach → instrument map is the ENGINE's: `source_registry` inverts its `instrument_for`
// facets and serves the result on /api/coaches[].instrument as {source, datatype} (null for a
// coach no single sensor grounds — the lead, mind and the explorer read the whole board), with
// the engine's own verdict beside it: `absent` (bool) and `reason` ("no sensor since
// <YYYY-MM-DD>"). The page reads THAT. `COACH_SOURCE` below is the pre-deploy FALLBACK only —
// used when no served coach carries an `instrument` key — and is held equal to the engine's
// rows by the PairContract "source_freshness -> the absent coach" (tests/pair_contract_registry.py),
// which lifts this block verbatim and runs darkCoaches() under node, so nothing between
// `COACH_SOURCE` and the end of `darkCoaches` may reach a module import.
export const COACH_SOURCE = {
  sleep_coach: { source: "whoop" },
  physical_coach: { source: "hevy" },
  nutrition_coach: { source: "macrofactor" },
  glucose_coach: { source: "apple_health", datatype: "cgm" },
  labs_coach: { source: "labs" },
  // mind_coach, explorer_coach, eli_marsh: no single instrument (the engine serves null) — never dark.
};
export const INSTRUMENT_WORDS = {
  sleep_coach: "the wrist strap",
  physical_coach: "the lifting log",
  nutrition_coach: "the food log",
  glucose_coach: "a blood-sugar sensor",
  labs_coach: "the blood-test panel",
};
// /api/coaches (persona ids) or /api/coaching-dashboard (short ids) → {map, absent, reasons}
// from the served `instrument` / `absent` / `reason` fields — null when NO coach carries an
// `instrument` key (the pre-deploy window: the caller falls back to COACH_SOURCE).
export function servedInstruments(coachesApi) {
  const list = coachesApi && Array.isArray(coachesApi.coaches) ? coachesApi.coaches : [];
  const carries = (c) => c && typeof c === "object" && Object.prototype.hasOwnProperty.call(c, "instrument");
  if (!list.some(carries)) return null;
  const pid = (c) => {
    const id = String(c.persona_id || c.coach_id || "");
    return !id || id === "eli_marsh" || id.endsWith("_coach") ? id : `${id}_coach`;
  };
  const out = { map: {}, absent: new Set(), reasons: {} };
  for (const c of list) {
    if (!carries(c)) continue;
    const id = pid(c);
    if (!id) continue;
    const inst = c.instrument;
    out.map[id] = inst && typeof inst === "object" && inst.source ? { source: String(inst.source), datatype: inst.datatype ? String(inst.datatype) : undefined } : null;
    if (c.absent === true) {
      out.absent.add(id);
      if (typeof c.reason === "string" && c.reason) out.reasons[id] = c.reason;
    }
  }
  return out;
}
// The dark set. `coachesApi` (optional) is /api/coaches: a served `absent: true` is the
// engine's verdict and darks the coach regardless of the board; a served `instrument`
// row is checked against /api/source_freshness as before (defence in depth: the two
// halves stand on one wire); `instrument: null` is never dark. Without a served
// `instrument` key anywhere the hand map stands in.
export function darkCoaches(freshness, coachesApi) {
  const out = new Set();
  const sources = (freshness && Array.isArray(freshness.sources) ? freshness.sources : []).reduce((m, s) => {
    if (s && s.id) m[s.id] = s;
    return m;
  }, {});
  const served = coachesApi ? servedInstruments(coachesApi) : null;
  for (const pid of served ? served.absent : []) out.add(pid);
  for (const [pid, ref] of Object.entries(served ? served.map : COACH_SOURCE)) {
    if (!ref || !ref.source) continue;
    const s = sources[ref.source];
    if (!s) continue;
    if (ref.datatype) {
      const dt = (Array.isArray(s.datatypes) ? s.datatypes : []).find((d) => d && d.key === ref.datatype);
      if (dt && dt.dark === true) out.add(pid);
    } else if (s.status === "stale" || s.status === "paused") out.add(pid);
  }
  return out;
}
// {pid: reason} — the engine's words for each served-absent coach ("no sensor since
// 2026-08-27"); {} before the engine serves them.
export function absentReasons(coachesApi) {
  const served = coachesApi ? servedInstruments(coachesApi) : null;
  return served ? served.reasons : {};
}
// The words beside a named-not-quoted coach: the engine's reason with its date in words
// ("no sensor since Thursday, August 27") — never the ISO string; without a served reason,
// the instrument ("a blood-sugar sensor is not worn").
export function darkWords(pid, reasons) {
  const r = String((reasons && reasons[pid]) || "");
  const m = r.match(/^no sensor since (\d{4}-\d{2}-\d{2})$/);
  const day = m ? dayInWords(m[1]) : "";
  if (day) return `no sensor since ${day}`;
  return `${INSTRUMENT_WORDS[pid] || "the instrument"} is not worn`;
}

// ── the docket: the engine's number between the witnesses ────────────────────────
// The last seven nightly recovery readings from /api/sleep_detail.sleep_trend[] (dates named),
// for a recovery criterion; other metrics print no series (never a number from elsewhere).
export function engineNumber(criterion, sleepDetail) {
  const metric = String((criterion && criterion.metric) || "");
  if (!/^recovery_score/.test(metric)) return null;
  const trend = (sleepDetail && Array.isArray(sleepDetail.sleep_trend) ? sleepDetail.sleep_trend : []).filter((r) => r && r.date && r.recovery_score != null && Number.isFinite(Number(r.recovery_score)));
  if (!trend.length) return null;
  const last = trend.slice(-7);
  const readings = last.map((r) => fmtNum(r.recovery_score));
  const from = dayInWords(last[0].date, { weekday: false });
  const to = dayInWords(last[last.length - 1].date, { weekday: false });
  const avg = sleepDetail && sleepDetail.sleep_detail && sleepDetail.sleep_detail.avg_recovery_window;
  const nights = sleepDetail && sleepDetail.sleep_detail && sleepDetail.sleep_detail.avg_window_days;
  return {
    readings,
    span: `${from} to ${to}`,
    avg: Number.isFinite(Number(avg)) ? fmtNum(avg) : "",
    nights: Number.isInteger(nights) ? nights : null,
    src: "api_sleep_detail.sleep_trend[].recovery_score",
  };
}
export function docketRow(item, names, dark, sleepDetail, reasons) {
  if (!item || !item.coach_a || !item.coach_b) return null;
  const sides = item.sides || {};
  // #4217: the docket entry's own `absent: {pid: {reason, instrument}}` block (served when
  // the engine omitted a dark side's claim) darks the seat too, and its reason wins.
  const absent = item.absent && typeof item.absent === "object" ? item.absent : {};
  const isDark = (pid) => dark.has(pid) || Object.prototype.hasOwnProperty.call(absent, pid);
  const why = (pid) => darkWords(pid, { ...(reasons || {}), ...(absent[pid] && absent[pid].reason ? { [pid]: absent[pid].reason } : {}) });
  const yes = Object.keys(sides).find((k) => sides[k] === true) || item.coach_a;
  const no = Object.keys(sides).find((k) => sides[k] === false) || item.coach_b;
  const nm = (pid) => (names && names[pid]) || pid.replace(/_coach$/, "").replace(/_/g, " ");
  const crit = item.criterion || {};
  const settle = dayInWords(item.resolution_date);
  const rule = crit.threshold != null ? `${metricWords(crit.metric)} ${conditionWords(crit.condition)} ${fmtNum(crit.threshold)}` : String(crit.description || "").replace(/_/g, " ");
  const claims = item.claims || {};
  return {
    question: docketQuestion(crit, item.resolution_date) || String(item.topic || "").replace(/_/g, " "),
    topic: String(item.topic || ""),
    yes: { id: yes, name: nm(yes), dark: isDark(yes), claim: isDark(yes) ? "" : String(claims[yes] || ""), why: isDark(yes) ? why(yes) : "" },
    no: { id: no, name: nm(no), dark: isDark(no), claim: isDark(no) ? "" : String(claims[no] || ""), why: isDark(no) ? why(no) : "" },
    engine: engineNumber(crit, sleepDetail),
    settled: settle ? `Code, on ${settle}: ${rule} and ${nm(yes)} wins. The loser’s miss stays on the record.` : `Code: ${rule} and ${nm(yes)} wins.`,
    opened: dayInWords(item.opened_date),
    resolution_date: item.resolution_date || "",
  };
}

// ── the record: K of N so far / all time, from ONE producer ──────────────────────
export function platformRecord(cal) {
  const p = cal && cal.platform;
  const so = p && p.strata && p.strata.coaches;
  const lt = p && p.lifetime && p.lifetime.strata && p.lifetime.strata.coaches;
  const pair = (s) => (s && Number.isInteger(s.n) && s.n > 0 && Number.isInteger(s.confirmed) ? { k: s.confirmed, n: s.n } : null);
  return { soFar: pair(so), allTime: pair(lt), through: cal && cal.as_of ? String(cal.as_of) : "" };
}
// The roster rows: every served coach except the one at the top; "K of N" only where
// /api/calibration.coaches[] serves an n > 0 for the seat, retired seats left out.
export function rosterRows(coachesApi, cal, topPersonaId) {
  const rec = {};
  for (const r of cal && Array.isArray(cal.coaches) ? cal.coaches : []) if (r && r.coach_id && r.retired !== true) rec[personaId(r.coach_id)] = r;
  const out = [];
  for (const c of coachesApi && Array.isArray(coachesApi.coaches) ? coachesApi.coaches : []) {
    if (!c || !c.persona_id || c.persona_id === topPersonaId) continue;
    const r = rec[c.persona_id];
    const role = c.tier === "lead" ? "runs the program — makes no checked calls" : String(c.domain || "").replace(/_/g, " ");
    let record = "";
    if (r && Number.isInteger(r.n) && r.n > 0) record = `${Number(r.confirmed) || 0} of ${numberWords(r.n)} checked call${r.n === 1 ? "" : "s"} right so far`;
    out.push({ id: c.persona_id, name: String(c.name || ""), role, record, src: r ? `api_calibration.coaches[${r.coach_id}]` : "" });
  }
  return out;
}

// ── the byline's role word ───────────────────────────────────────────────────────
const ROLE_WORDS = { sleep: "sleep", physical: "training", nutrition: "nutrition", mind: "mind", glucose: "blood sugar", labs: "blood tests", explorer: "statistics", eli_marsh: "lead" };
export function roleWord(coachId) {
  const id = shortId(coachId);
  return ROLE_WORDS[id] || id.replace(/_/g, " ");
}

// ── HTML ─────────────────────────────────────────────────────────────────────────
const marginHTML = (ymd) => {
  const iso = String(ymd || "").slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return "";
  const d = new Date(Date.parse(`${iso}T12:00:00Z`));
  const day = d.getUTCDate();
  const mo = d.toLocaleDateString("en-US", { timeZone: "UTC", month: "short" });
  const wd = d.toLocaleDateString("en-US", { timeZone: "UTC", weekday: "long" });
  return `<span class="v7c-d">${day}</span><span class="v7c-mo">${esc(mo)}</span><span class="v7c-w">${esc(wd)}</span>`;
};
const lineHTML = (l) => `<li><span class="v7c-tag${l.verdict === "right" ? " v7c-hit" : ""}">${l.verdict}</span>${esc(l.text)}${l.checked ? ` <span class="v7c-g">${esc(l.checked)}</span>` : ""}</li>`;

// The reason a coach is at the top, as a sentence with its producer (R6 fix 3).
export function reasonSentence(pick, calibration) {
  if (!pick) return "";
  if (pick.rule === "lead") return { text: "Today’s lead read, written this morning from the day’s facts.", src: "api_coaching-dashboard.lead_daily" };
  if (pick.rule === "ask") return { text: "At the top because the open ask is this coach’s.", src: "api_coaching-dashboard.open_actions[0]" };
  if (pick.rule === "record") {
    const sid = shortId(pick.coach && pick.coach.coach_id);
    const r = (calibration && Array.isArray(calibration.coaches) ? calibration.coaches : []).find((x) => x && x.coach_id === sid);
    const kn = r ? `${Number(r.confirmed) || 0} of ${numberWords(r.n)}` : "";
    return { text: `At the top for the best checked record since Day 1${kn ? `: ${kn} calls held up` : ""}.`, src: `api_calibration.coaches[${sid}]` };
  }
  return { text: "At the top as the freshest read on the board.", src: "api_coaching-dashboard.coaches[].analysis_generated_at" };
}

export function readHTML(pick, profile, now, calibration) {
  const c = pick && pick.coach;
  if (!c) return "";
  const pid = personaId(c.coach_id);
  const name = String(c.name || "");
  const who = `<div class="v7c-voice"><span class="v7c-who">${esc(name)}</span><span class="v7c-role" data-src="api_coaching-dashboard.coaches[].analysis_generated_at">${esc(roleWord(c.coach_id))} · written ${esc(timeInWords(c.analysis_generated_at))}</span></div>`;
  const parts = [who];
  // the ledger line opens the read
  const lc = profile && profile.latest_checked ? ledgerLine(profile.latest_checked, name) : null;
  const recent = recentLines(profile && profile.report_card && profile.report_card.track_record && profile.report_card.track_record.recent, name);
  if (lc) {
    parts.push(`<p class="v7c-dated">The last call of ${esc(surname(name))}’s that code checked:</p>`);
    // the coach's own wording of the call is a served sentence like any other: linted, and on
    // a hit folded under <details> ("61% tomorrow with 80% confidence" was in the 390 fold)
    const claimWhy = lintPublic(lc.claim);
    const claimLine = !lc.claim
      ? ""
      : !claimWhy.length
        ? `<li class="v7c-claim">In the coach’s words, as served: “${esc(lc.claim)}”</li>`
        : `<li class="v7c-claim"><details class="v7c-details"><summary>The call in the coach’s words, as served</summary><p>“${esc(lc.claim)}”</p><p class="v7c-note">Kept off the main screen: it carries ${esc(claimWhy.join(", "))}. Served without edits.</p></details></li>`;
    parts.push(`<ul class="v7c-ledger" data-src="api_coach_${esc(pid)}.latest_checked">${lineHTML(lc)}${claimLine}</ul>`);
  } else if (!recent.length) {
    // absence only when the profile served NOTHING checked — a null ledger line above a
    // list of checked calls would contradict the list (R6 fix 1)
    parts.push(`<p class="v7c-absent" data-src="api_coach_${esc(pid)}.latest_checked">No checked call yet.</p>`);
  }
  if (recent.length) {
    const t = tally(recent);
    parts.push(`<p class="v7c-dated">The last ${numberWords(t.n)} checked call${t.n === 1 ? "" : "s"}, newest first — ${numberWords(t.right)} right, ${numberWords(t.wrong)} wrong:</p>`);
    parts.push(`<ul class="v7c-ledger" data-src="api_coach_${esc(pid)}.report_card.track_record.recent">${recent.map(lineHTML).join("")}</ul>`);
    const tr = profile && profile.report_card && profile.report_card.track_record;
    parts.push(coachComparison(tr && tr.comparison, { cls: "v7c-note", src: `api_coach_${pid}.report_card.track_record.comparison.sentence` })); // #4585
  }
  // the read itself: the guarded slot, linted; a hit folds under <details>, never rewritten
  const text = String(c.position_summary || "").trim();
  const src = c.lead ? "api_coaching-dashboard.lead_daily.text" : "api_coaching-dashboard.coaches[].position_summary";
  const why = lintPublic(text);
  if (text && !why.length) parts.push(`<blockquote class="v7c-coach" data-src="${src}">${esc(text)}</blockquote>`);
  else if (text) parts.push(`<details class="v7c-details"><summary>The read, as served</summary><blockquote class="v7c-coach" data-src="${src}">${esc(text)}</blockquote><p class="v7c-note">Kept off the main screen: it carries ${esc(why.join(", "))}. Served without edits.</p></details>`);
  else parts.push(`<p class="v7c-absent">No public read is served for today.</p>`);
  const reason = reasonSentence(pick, calibration);
  if (reason) parts.push(`<p class="v7c-note" data-src="${esc(reason.src)}">${esc(reason.text)}</p>`);
  // #4585: a "K of N held up" reason is a coach count — it never appears alone.
  if (reason && pick.rule === "record") {
    const sid = shortId(c.coach_id);
    const r = (calibration && Array.isArray(calibration.coaches) ? calibration.coaches : []).find((x) => x && x.coach_id === sid);
    parts.push(coachComparison(r && r.comparison, { cls: "v7c-note", src: `api_calibration.coaches[${sid}].comparison.sentence` }));
  }
  // the standing ask, counted
  const ask = standingAsk(profile && profile.dossier && profile.dossier.commitments);
  const n = askCount(profile && profile.recent_outputs);
  if (ask && n.asks >= 2) {
    const due = dayInWords(ask.due_date);
    const first = dayInWords(n.first);
    parts.push(
      `<div class="v7c-thread" data-src="api_coach_${esc(pid)}.recent_outputs"><div class="v7c-t">The standing ask — the thread, counted</div>` +
        `<p>On <b data-src="api_coach_${esc(pid)}.recent_outputs (count)">${n.asks}</b> of ${esc(numberWords(n.mornings))} mornings${first ? ` since ${esc(first)}` : ""}, by a keyword count of the mornings (${esc(ASK_RULE)}), ${esc(surname(name))} has asked him for the same thing. ` +
        `The latest form, asked ${esc(dayInWords(ask.date))}${due ? `, is due ${esc(due)}` : ""}: <q data-src="api_coach_${esc(pid)}.dossier.commitments[].text">${esc(ask.text)}</q>.` +
        `${ask.outcome ? "" : ' <span class="v7c-late">Nothing has come back yet, and there is no channel yet to receive one.</span>'}</p></div>`,
    );
  }
  const daily = profile && typeof profile.daily === "string" ? profile.daily.trim() : "";
  if (daily && daily !== text) {
    parts.push(`<details class="v7c-details"><summary>What ${esc(surname(name))} wrote to Matthew, as served</summary><blockquote class="v7c-coach" data-src="api_coach_${esc(pid)}.daily">${esc(daily)}</blockquote><p class="v7c-note">Served without edits.</p></details>`);
  }
  return parts.join("\n");
}

export function docketHTML(rows) {
  if (!rows.length) return "";
  return rows
    .map((r) => {
      const eng = r.engine
        ? `<span class="v7c-num" data-src="${esc(r.engine.src)}">${r.engine.readings.map(esc).join(" · ")}</span> — the last ${esc(numberWords(r.engine.readings.length))} nightly recovery readings, ${esc(r.engine.span)}${r.engine.avg ? `; the average over ${r.engine.nights ? `${esc(numberWords(r.engine.nights))} nights` : "the window"} is <span class="v7c-num" data-src="api_sleep_detail.sleep_detail.avg_recovery_window">${esc(r.engine.avg)}</span>` : ""}.`
        : "No series for this number is served here.";
      const served = [r.yes, r.no]
        .map((s) => (s.dark ? `<p class="v7c-dated">${esc(s.name)} is named but not quoted: ${esc(s.why || darkWords(s.id))}.</p>` : s.claim ? `<p class="v7c-dated">${esc(s.name)}:</p><blockquote class="v7c-coach" data-src="api_coach_docket.open[].claims.${esc(s.id)}">${esc(s.claim)}</blockquote>` : `<p class="v7c-dated">${esc(s.name)}: no words served.</p>`))
        .join("");
      return (
        `<table class="v7c-table" data-src="api_coach_docket.open[]">` +
        `<tr><th>The question</th><td>${esc(r.question)}</td></tr>` +
        `<tr><th>${esc(r.yes.name)}</th><td><b>Says yes</b>${r.yes.dark ? ` — named, not quoted: ${esc(r.yes.why || darkWords(r.yes.id))}.` : "."}</td></tr>` +
        `<tr><th>${esc(r.no.name)}</th><td><b>Says no</b>${r.no.dark ? ` — named, not quoted: ${esc(r.no.why || darkWords(r.no.id))}.` : "."}</td></tr>` +
        `<tr class="v7c-engine"><th>The number between them</th><td>${eng}</td></tr>` +
        `<tr><th>Settled by</th><td data-src="api_coach_docket.open[].resolution_date">${esc(r.settled)}</td></tr>` +
        `</table>` +
        `<details class="v7c-details"><summary>What each wrote, as served</summary>${r.topic ? `<p class="v7c-dated">The docket’s own wording of the question, as served: ${esc(r.topic)}</p>` : ""}${served}</details>` +
        (r.opened ? `<p class="v7c-note">Opened ${esc(r.opened)}.</p>` : "")
      );
    })
    .join("\n");
}

export function recordHTML(rec, comparison) {
  if (!rec.soFar) return "";
  let s = `<p>All coaches together, by the site’s scorekeeper: <b class="v7c-num" data-src="api_calibration.platform.strata.coaches">${rec.soFar.k} of ${rec.soFar.n}</b> checked calls right so far`;
  if (rec.allTime) s += `; <span class="v7c-num" data-src="api_calibration.platform.lifetime.strata.coaches">${rec.allTime.k} of ${rec.allTime.n}</span> all time`;
  // #4585 / epic #4580 rule 3: the count never appears alone.
  return `${s}.</p>` + coachComparison(comparison, { cls: "v7c-note", src: "api_calibration.comparison.sentence" });
}
export function rosterHTML(rows) {
  if (!rows.length) return "";
  return `<table class="v7c-table v7c-rec"><tbody>${rows.map((r) => `<tr><td class="v7c-k2"${r.src ? ` data-src="${esc(r.src)}"` : ""}>${r.record ? esc(r.record) : "—"}</td><td>${esc(r.name)} · ${esc(r.role)}${r.record ? "" : r.role.startsWith("runs") ? "" : " — no checked call yet"}</td></tr>`).join("")}</tbody></table>`;
}

// ── the page ─────────────────────────────────────────────────────────────────────
// Exported for the test. A non-2xx body is DRAINED before the null return: an unread body
// stays "in flight" to Chromium, so `networkidle` never arrives and the visual-QA gate that
// waits on it times out — a rollback class (proven live by the Today lane, 2026-09-26).
export async function getJSON(url) {
  try {
    const r = await fetch(url, { headers: { Accept: "application/json" } });
    if (!r.ok) {
      await r.text().catch(() => "");
      return null;
    }
    return await r.json();
  } catch (e) {
    return null;
  }
}
const setHTML = (id, html) => {
  const el = document.getElementById(id);
  if (el && html) el.innerHTML = html;
};

const NOT_SERVED = (what) => `<p class="v7c-absent">${what} not served right now.</p>`;

export async function run(doc) {
  const d = doc || (typeof document !== "undefined" ? document : null);
  if (!d || !d.getElementById("v7c-read-body")) return;
  const now = new Date();
  const [dash, docket, cal, sleep, fresh, coachesApi] = await Promise.all([
    getJSON("/api/coaching-dashboard"),
    getJSON("/api/coach_docket"),
    getJSON("/api/calibration"),
    getJSON("/api/sleep_detail"),
    getJSON("/api/source_freshness"),
    getJSON("/api/coaches"),
  ]);
  // "Data through <day>" once, from the record's own stamp.
  const rec = platformRecord(cal);
  const through = d.getElementById("v7c-through");
  if (through && rec.through) through.textContent = dataThrough(rec.through);

  // (1) today's read — a null fetch says so; an empty served board is absence
  const pick = dash ? chooseTodaysRead(dash.coaches, dash.open_actions, cal, dash.lead_daily, now) : null;
  let topPid = "";
  if (!dash) setHTML("v7c-read-body", NOT_SERVED("The coaches’ reads are"));
  else if (!pick || !pick.coach) setHTML("v7c-read-body", `<p class="v7c-absent">No read is served today.</p>`);
  else {
    topPid = personaId(pick.coach.coach_id);
    const profile = await getJSON(`/api/coach/${encodeURIComponent(topPid)}`);
    setHTML("v7c-read-body", readHTML(pick, profile, now, cal));
    setHTML("v7c-read-m", marginHTML(ptDate(pick.coach.analysis_generated_at)));
  }

  // (2) where two disagree
  const names = {};
  for (const c of coachesApi && Array.isArray(coachesApi.coaches) ? coachesApi.coaches : []) if (c && c.persona_id) names[c.persona_id] = String(c.name || "");
  // #4217: the engine's map + verdict from /api/coaches (instrument / absent / reason); the
  // freshness board is the second witness; the hand map stands in only before the deploy.
  const dark = darkCoaches(fresh, coachesApi);
  const reasons = absentReasons(coachesApi);
  const rows = (docket && Array.isArray(docket.open) ? docket.open : []).map((it) => docketRow(it, names, dark, sleep, reasons)).filter(Boolean);
  if (!docket) setHTML("v7c-docket-body", NOT_SERVED("The docket is"));
  else if (!rows.length) setHTML("v7c-docket-body", `<p class="v7c-absent">No open disagreement on the record.</p>`);
  else {
    setHTML("v7c-docket-body", docketHTML(rows));
    setHTML("v7c-docket-m", marginHTML(rows[0].resolution_date));
  }

  // (3) the record + the roster
  if (!cal) setHTML("v7c-record-body", NOT_SERVED("The record is"));
  else if (!rec.soFar) setHTML("v7c-record-body", `<p class="v7c-absent">No checked call yet.</p>`);
  else {
    setHTML("v7c-record-body", recordHTML(rec, cal.comparison));
    setHTML("v7c-record-m", marginHTML(rec.through));
  }
  const roster = rosterRows(coachesApi, cal, topPid);
  if (!coachesApi) setHTML("v7c-roster-body", NOT_SERVED("The roster is"));
  else if (roster.length) {
    setHTML("v7c-roster-body", rosterHTML(roster));
    const sum = d.getElementById("v7c-roster-sum");
    if (sum) sum.textContent = `${topPid ? "The rest of the staff" : "The staff"} (${roster.length})`;
  }
}

if (typeof document !== "undefined" && document.getElementById("v7c-read-body")) {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => run());
  else run();
}
