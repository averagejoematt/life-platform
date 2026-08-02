// mirror-core.js — The Mirror's deterministic scoring core (#1392).
//
// A browser port of the EXACT instruments that score Matthew every night:
//
//   percentile / readiness_hrv_score / compute_bands   lambdas/health/personal_baselines.py
//   score_sleep / score_recovery                        lambdas/health/scoring_engine.py
//   normalize_whoop_sleep / compute_readiness / avg     lambdas/compute/daily_metrics_compute_lambda.py
//
// "The same instruments" is a parity claim, not a vibe: every ported function is
// pinned to tests/vectors/mirror_vectors.json — generated FROM the deployed Python
// by scripts/gen_mirror_vectors.py — and tests/js/mirror_core.test.mjs requires
// EXACT equality (ADR-105: never a tolerance; every value is rounded at source).
//
// Python-semantics helpers (strict float(), truthiness, `or`) are deliberate: the
// port must reproduce CPython behaviour bit-for-bit, including banker's rounding
// (pyRound, shared with the calibration scorer) and `0 or fallback` coalescing.
//
// The parser half (parseCsv / extractWhoopExport / buildDays) is the Mirror's own:
// it maps a Whoop CSV export onto the ingestion field shape (mirroring
// lambdas/ingestion/whoop_lambda.py's extractors — minutes→hours at 2dp, the
// in-bed-minus-awake duration, the sleep_performance→sleep_quality_score alias)
// and is covered by JS unit tests rather than Python vectors, because the deployed
// pipeline ingests the Whoop API, not CSV files.
//
// No network, no storage, no DOM. Everything in this file is a pure function.

import { pyRound } from "/assets/js/calibration-core.js";

export const MIN_N = 30; // personal_baselines floor-guard: a band replaces its fallback only at n >= 30

export const FALLBACK_ANCHORS = {
  readiness_hrv_ratio: { p10: 0.75, p50: 1.0, p90: 1.25 },
};

// ──────────────────────────────────────────────────────────────────────────
// CPython-semantics helpers
// ──────────────────────────────────────────────────────────────────────────

/** Python float(x): strict — returns NaN where Python would raise. */
function strictFloat(v) {
  if (typeof v === "number") return v;
  if (typeof v === "boolean") return v ? 1 : 0;
  if (typeof v === "string") {
    const s = v.trim();
    if (s === "") return NaN;
    const n = Number(s);
    return Number.isFinite(n) || Number.isNaN(n) ? n : n; // Infinity kept: Python float("inf") accepts it
  }
  return NaN; // None / objects → TypeError in Python → our "raise" marker
}

/** Python truthiness for the value kinds this module meets (None/dict/number/str). */
function pyTruthy(v) {
  if (v === null || v === undefined) return false;
  if (typeof v === "number") return v !== 0 && !Number.isNaN(v) ? true : Number.isNaN(v); // NaN is truthy in Python
  if (typeof v === "string") return v.length > 0;
  if (Array.isArray(v)) return v.length > 0;
  if (typeof v === "object") return Object.keys(v).length > 0;
  return Boolean(v);
}

/** Python `a or b` for the numeric-or-None values compute_readiness coalesces. */
function pyOr(a, b) {
  return pyTruthy(a) ? a : b;
}

/** scoring_engine.safe_float — None on missing rec/field or unparseable value. */
export function safeFloat(rec, field, dflt = null) {
  if (pyTruthy(rec) && field in rec) {
    const f = strictFloat(rec[field]);
    return Number.isNaN(f) ? dflt : f;
  }
  return dflt;
}

/** scoring_engine.clamp */
export function clamp(val, lo = 0, hi = 100) {
  return Math.max(lo, Math.min(hi, val));
}

/** scoring_engine.avg — mean rounded to 1dp, null on an empty (post-filter) list. */
export function avg(vals) {
  const v = vals.filter((x) => x !== null && x !== undefined);
  if (!v.length) return null;
  return pyRound(v.reduce((a, b) => a + b, 0) / v.length, 1);
}

// ──────────────────────────────────────────────────────────────────────────
// personal_baselines ports
// ──────────────────────────────────────────────────────────────────────────

/** personal_baselines.percentile — type-7 linear interpolation, dirty entries dropped. */
export function percentile(values, p) {
  const clean = [];
  for (const v of values) {
    if (v === null || v === undefined) continue;
    const f = strictFloat(v);
    if (Number.isNaN(f)) continue;
    clean.push(f);
  }
  if (!clean.length) return null;
  clean.sort((a, b) => a - b);
  const n = clean.length;
  if (n === 1) return clean[0];
  if (p <= 0) return clean[0];
  if (p >= 100) return clean[n - 1];
  const rank = (p / 100.0) * (n - 1);
  const lo = Math.floor(rank);
  const frac = rank - lo;
  if (lo + 1 >= n) return clean[lo];
  return clean[lo] + frac * (clean[lo + 1] - clean[lo]);
}

/** personal_baselines._band_readiness_hrv_ratio — {p10,p50,p90,n} or null below the floor-guard. */
export function computeHrvBand(ratios) {
  const clean = ratios.filter((r) => r !== null && r !== undefined);
  if (clean.length < MIN_N) return null;
  return {
    p10: pyRound(percentile(clean, 10), 4),
    p50: pyRound(percentile(clean, 50), 4),
    p90: pyRound(percentile(clean, 90), 4),
    n: clean.length,
  };
}

function anchorsOrFallback(baselines) {
  const band = (baselines || {}).readiness_hrv_ratio;
  if (
    band &&
    (band.n ?? 0) >= MIN_N &&
    band.p10 !== null && band.p10 !== undefined &&
    band.p50 !== null && band.p50 !== undefined &&
    band.p90 !== null && band.p90 !== undefined
  ) {
    return [band, "personal"];
  }
  return [FALLBACK_ANCHORS.readiness_hrv_ratio, "population_fallback"];
}

/** personal_baselines.readiness_hrv_score — [score 0-100, "personal"|"population_fallback"]. */
export function readinessHrvScore(ratio, baselines) {
  const [band, src] = anchorsOrFallback(baselines);
  const { p10, p50, p90 } = band;
  let score;
  if (ratio <= p50) {
    const span = p50 - p10;
    score = span > 0 ? (50.0 * (ratio - p10)) / span : ratio < p50 ? 0.0 : 50.0;
  } else {
    const span = p90 - p50;
    score = span > 0 ? 50.0 + (50.0 * (ratio - p50)) / span : 100.0;
  }
  return [clamp(pyRound(score, 0)), src];
}

// ──────────────────────────────────────────────────────────────────────────
// daily_metrics_compute ports
// ──────────────────────────────────────────────────────────────────────────

/** daily_metrics_compute_lambda.normalize_whoop_sleep — Whoop fields → scoring schema. */
export function normalizeWhoopSleep(item) {
  if (!pyTruthy(item)) return item;
  const out = { ...item };
  if ("sleep_quality_score" in out && !("sleep_score" in out)) out.sleep_score = out.sleep_quality_score;
  if ("sleep_efficiency_percentage" in out && !("sleep_efficiency_pct" in out)) {
    out.sleep_efficiency_pct = out.sleep_efficiency_percentage;
  }
  let dur = null;
  const rawDur = strictFloat(out.sleep_duration_hours ?? 0);
  if (!Number.isNaN(rawDur)) dur = pyOr(rawDur, null);
  if (pyTruthy(dur) && dur > 0) {
    for (const [srcField, pctField] of [
      ["slow_wave_sleep_hours", "deep_pct"],
      ["rem_sleep_hours", "rem_pct"],
      ["light_sleep_hours", "light_pct"],
    ]) {
      const hrs = strictFloat(out[srcField] ?? 0);
      if (Number.isNaN(hrs)) continue;
      if (!(pctField in out)) out[pctField] = pyRound((hrs / dur) * 100, 1);
    }
  }
  if ("time_awake_hours" in out && !("waso_hours" in out)) out.waso_hours = out.time_awake_hours;
  if ("disturbance_count" in out && !("toss_and_turns" in out)) out.toss_and_turns = out.disturbance_count;
  return out;
}

/** scoring_engine.score_sleep — [score|null, details]. */
export function scoreSleep(data, profile) {
  const sleep = data.sleep;
  if (!pyTruthy(sleep)) return [null, {}];
  const sleepScore = safeFloat(sleep, "sleep_score");
  const efficiency = safeFloat(sleep, "sleep_efficiency_pct");
  const durationHrs = safeFloat(sleep, "sleep_duration_hours");
  const deepPct = safeFloat(sleep, "deep_pct");
  const remPct = safeFloat(sleep, "rem_pct");
  const lightPct = safeFloat(sleep, "light_pct");
  const targetHrs = profile.sleep_target_hours_ideal ?? 7.5;
  const details = {
    sleep_score: sleepScore,
    efficiency,
    duration_hrs: durationHrs,
    target_hrs: targetHrs,
    deep_pct: deepPct,
    rem_pct: remPct,
    light_pct: lightPct,
  };
  const parts = [];
  const weights = [];
  if (sleepScore !== null) {
    parts.push(sleepScore * 0.4);
    weights.push(0.4);
  }
  if (efficiency !== null) {
    parts.push(efficiency * 0.3);
    weights.push(0.3);
  }
  if (durationHrs !== null) {
    const durScore = clamp(100 - (Math.abs(durationHrs - targetHrs) / 2.0) * 100);
    parts.push(durScore * 0.3);
    weights.push(0.3);
    details.duration_score = pyRound(durScore, 1);
  }
  if (!weights.length) return [null, details];
  const total = parts.reduce((a, b) => a + b, 0) / weights.reduce((a, b) => a + b, 0);
  return [clamp(pyRound(total, 0)), details];
}

/** scoring_engine.score_recovery — [score|null, details]. */
export function scoreRecovery(data) {
  const recovery = safeFloat(data.whoop, "recovery_score");
  if (recovery === null) return [null, {}];
  return [clamp(pyRound(recovery, 0)), { recovery_score: recovery }];
}

/**
 * daily_metrics_compute_lambda.compute_readiness — [score|null, colour, breakdown].
 * Weights: recovery 0.40, sleep 0.25, hrv_trend 0.20, tsb 0.10 — renormalised over
 * whatever is PRESENT (ADR-104 honest absence: a missing component is missing, not zero).
 */
export function computeReadiness(data, baselines) {
  const components = [];
  const recovery = pyOr(safeFloat(data.whoop_today, "recovery_score"), safeFloat(data.whoop, "recovery_score"));
  if (recovery !== null) components.push(["recovery", recovery, 0.4]);
  const sleepScore = safeFloat(data.sleep, "sleep_score");
  if (sleepScore !== null) components.push(["sleep", sleepScore, 0.25]);
  const hrv7 = (data.hrv || {}).hrv_7d;
  const hrv30 = (data.hrv || {}).hrv_30d;
  if (pyTruthy(hrv7) && pyTruthy(hrv30) && hrv30 > 0) {
    const [hrvScore] = readinessHrvScore(hrv7 / hrv30, baselines);
    components.push(["hrv_trend", hrvScore, 0.2]);
  }
  const tsb = data.tsb;
  if (tsb !== null && tsb !== undefined) components.push(["tsb", clamp(pyRound(60 + tsb * 2, 0)), 0.1]);
  if (!components.length) return [null, "gray", []];
  const tw = components.reduce((a, [, , w]) => a + w, 0);
  const score = pyRound(components.reduce((a, [, v, w]) => a + v * w, 0) / tw, 0);
  const breakdown = components.map(([k, v, w]) => ({ key: k, score: pyRound(v, 1), weight: w }));
  if (score >= 80) return [score, "green", breakdown];
  if (score >= 60) return [score, "yellow", breakdown];
  return [score, "red", breakdown];
}

// ──────────────────────────────────────────────────────────────────────────
// The Mirror's own half: Whoop CSV export → the ingestion field shape
// ──────────────────────────────────────────────────────────────────────────

/** RFC-4180-ish CSV → array of row arrays. Handles quotes, embedded commas, CRLF. */
export function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        field += c;
      }
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ",") {
      row.push(field);
      field = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field);
      field = "";
      if (row.length > 1 || row[0] !== "") rows.push(row);
      row = [];
    } else {
      field += c;
    }
  }
  if (field !== "" || row.length) {
    row.push(field);
    if (row.length > 1 || row[0] !== "") rows.push(row);
  }
  return rows;
}

// Header matchers for the Whoop export files (physiological_cycles.csv and
// sleeps.csv). Matched case-insensitively on the whole header cell so minor
// wording drift in future exports degrades to "column not found", never to a
// misread column.
const WHOOP_COLUMNS = {
  cycle_start: /cycle start time|^sleep onset$/,
  recovery: /recovery score/,
  rhr: /resting heart rate/,
  hrv: /heart rate variability/,
  strain: /day strain/,
  sleep_performance: /sleep performance/,
  sleep_efficiency: /sleep efficiency/,
  in_bed_min: /in bed duration/,
  awake_min: /awake duration/,
  asleep_min: /asleep duration/,
  deep_min: /deep \(sws\) duration|sws duration|deep sleep duration/,
  rem_min: /rem duration|rem sleep duration/,
  light_min: /light sleep duration/,
  nap: /^nap$/,
};

function columnIndex(header) {
  const idx = {};
  header.forEach((cell, i) => {
    const label = cell.trim().toLowerCase();
    for (const [key, re] of Object.entries(WHOOP_COLUMNS)) {
      if (idx[key] === undefined && re.test(label)) idx[key] = i;
    }
  });
  return idx;
}

function cellFloat(row, i) {
  if (i === undefined) return null;
  const f = strictFloat(row[i] ?? "");
  return Number.isNaN(f) ? null : f;
}

function minutesToHours(min) {
  // whoop_lambda ms_to_h: round(ms / 3_600_000, 2); the export ships minutes.
  return pyRound(min / 60, 2);
}

/**
 * One Whoop export CSV → { records: {date → ingestion-shaped record}, meta }.
 * Mirrors whoop_lambda's extractors: duration = in-bed − awake (fallback: asleep),
 * minutes→hours at 2dp, stage hours only when > 0, hrv at 2dp,
 * sleep_performance → sleep_performance_percentage + sleep_quality_score alias.
 * Nap rows (sleeps.csv) are skipped, as the platform's main-sleep selection does.
 */
export function extractWhoopExport(text) {
  const rows = parseCsv(text);
  if (rows.length < 2) return { records: {}, meta: { rows: 0, skipped: 0, kind: "empty" } };
  const idx = columnIndex(rows[0]);
  if (idx.cycle_start === undefined) {
    return { records: {}, meta: { rows: 0, skipped: rows.length - 1, kind: "unrecognised" } };
  }
  const kind = idx.recovery !== undefined || idx.strain !== undefined ? "cycles" : "sleeps";
  const records = {};
  let skipped = 0;
  for (const row of rows.slice(1)) {
    const start = (row[idx.cycle_start] || "").trim();
    const date = start.slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
      skipped++;
      continue;
    }
    if (idx.nap !== undefined && /^true$/i.test((row[idx.nap] || "").trim())) {
      skipped++;
      continue;
    }
    const rec = records[date] || (records[date] = {});
    const set = (field, value) => {
      if (value !== null && !(field in rec)) rec[field] = value;
    };
    set("recovery_score", cellFloat(row, idx.recovery));
    set("resting_heart_rate", cellFloat(row, idx.rhr));
    const hrv = cellFloat(row, idx.hrv);
    if (hrv !== null) set("hrv", pyRound(hrv, 2));
    const strain = cellFloat(row, idx.strain);
    if (strain !== null) set("strain", pyRound(strain, 2));

    const inBed = cellFloat(row, idx.in_bed_min);
    const awake = cellFloat(row, idx.awake_min);
    const asleep = cellFloat(row, idx.asleep_min);
    let sleepMin = null;
    if (inBed !== null && awake !== null) sleepMin = inBed - awake;
    else if (asleep !== null) sleepMin = asleep;
    if (sleepMin !== null && sleepMin > 0) set("sleep_duration_hours", minutesToHours(sleepMin));
    for (const [col, field] of [
      ["deep_min", "slow_wave_sleep_hours"],
      ["rem_min", "rem_sleep_hours"],
      ["light_min", "light_sleep_hours"],
      ["awake_min", "time_awake_hours"],
    ]) {
      const mins = cellFloat(row, idx[col]);
      if (mins !== null && mins > 0) set(field, minutesToHours(mins));
    }
    const eff = cellFloat(row, idx.sleep_efficiency);
    if (eff !== null) set("sleep_efficiency_percentage", pyRound(eff, 2));
    const perf = cellFloat(row, idx.sleep_performance);
    if (perf !== null) {
      set("sleep_performance_percentage", perf);
      set("sleep_quality_score", perf);
    }
  }
  return { records, meta: { rows: Object.keys(records).length, skipped, kind } };
}

/** Merge extracts from several files (cycles + sleeps): first file to set a field per date wins. */
export function mergeExtracts(extracts) {
  const records = {};
  for (const ex of extracts) {
    for (const [date, rec] of Object.entries(ex.records)) {
      const merged = records[date] || (records[date] = {});
      for (const [k, v] of Object.entries(rec)) if (!(k in merged)) merged[k] = v;
    }
  }
  return records;
}

const DAY_MS = 86400000;

function dateAdd(iso, days) {
  const t = Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10)) + days * DAY_MS;
  return new Date(t).toISOString().slice(0, 10);
}

/**
 * Score every exported day on the platform's instruments.
 *
 * Two passes, exactly as the platform runs them: (1) trailing HRV means per day —
 * the 7- and 30-day windows END on the scored day, matching assemble_data's
 * [today−N .. yesterday] fetch — then the reader's OWN readiness_hrv_ratio band
 * from their whole export (personal_baselines with the same MIN_N floor-guard);
 * (2) per-day pillar scores + readiness against that band. TSB is absent by
 * construction (a Whoop export carries no external training-load series), so
 * readiness renormalises over the present components — labelled, never faked.
 */
export function buildDays(records) {
  const dates = Object.keys(records).sort();
  const hrvByDate = {};
  for (const d of dates) {
    const h = records[d].hrv;
    if (h !== undefined && h !== null) hrvByDate[d] = h;
  }
  const windows = {};
  for (const d of dates) {
    const w7 = [];
    const w30 = [];
    for (let k = 0; k < 30; k++) {
      const dk = dateAdd(d, -k);
      const h = hrvByDate[dk];
      if (h === undefined) continue;
      if (k < 7) w7.push(h);
      w30.push(h);
    }
    windows[d] = { hrv_7d: avg(w7), hrv_30d: avg(w30) };
  }
  const ratios = dates
    .map((d) => {
      const { hrv_7d, hrv_30d } = windows[d];
      return pyTruthy(hrv_7d) && pyTruthy(hrv_30d) && hrv_30d > 0 ? hrv_7d / hrv_30d : null;
    })
    .filter((r) => r !== null);
  const band = computeHrvBand(ratios);
  const baselines = band ? { readiness_hrv_ratio: band } : {};

  const days = dates.map((d) => {
    const rec = records[d];
    const sleepNorm = normalizeWhoopSleep(rec);
    const data = { whoop_today: rec, whoop: null, sleep: sleepNorm, hrv: windows[d], tsb: null };
    const [sleepScore, sleepDetails] = scoreSleep({ sleep: sleepNorm }, {});
    const [readiness, colour, breakdown] = computeReadiness(data, baselines);
    return {
      date: d,
      record: rec,
      sleep_norm: sleepNorm,
      hrv_7d: windows[d].hrv_7d,
      hrv_30d: windows[d].hrv_30d,
      sleep_pillar: sleepScore,
      sleep_details: sleepDetails,
      recovery_pillar: scoreRecovery({ whoop: rec })[0],
      readiness,
      readiness_colour: colour,
      readiness_breakdown: breakdown,
    };
  });
  return { days, baselines, band_n: band ? band.n : ratios.length };
}

// ──────────────────────────────────────────────────────────────────────────
// Percentile placement against the published distributions
// ──────────────────────────────────────────────────────────────────────────

/**
 * Exact midrank percentile of `value` within a SORTED sample:
 * (count_below + count_equal/2) / n × 100. Null on an empty sample.
 */
export function percentileRank(sortedSample, value) {
  const n = sortedSample.length;
  if (!n || value === null || value === undefined) return null;
  let below = 0;
  let equal = 0;
  for (const s of sortedSample) {
    if (s < value) below++;
    else if (s === value) equal++;
    else break;
  }
  return ((below + equal / 2) / n) * 100;
}
