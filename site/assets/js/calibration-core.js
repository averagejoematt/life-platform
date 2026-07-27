// calibration-core.js — grade a forecaster (human or LLM) against what happened.
//
// Browser/Node ES module port of calibration_core.py. Zero dependencies, no
// network, no DOM: pure functions in, plain objects out.
//
// PARITY CONTRACT
// ---------------
// This file must reproduce vectors/calibration_vectors.json EXACTLY — the same
// fixture the Python package and the platform grader it was extracted from are
// held to. Not "within a tolerance": the same numbers.
//
// The trap that makes that non-trivial is rounding. Python's round(x, n) is
// round-half-to-EVEN applied to the exact binary value of the double.
// JavaScript has no such primitive: Math.round is half-up, and
// Number(x.toFixed(n)) rounds the shortest decimal repr, which disagrees with
// Python on values like 2.675 (whose double is really 2.67499999999999982).
// So pyRound() below does the exact thing with BigInt: decompose the double
// into mantissa * 2^exp, scale by 10^n as an exact rational, and round the
// quotient half-to-even. It is the load-bearing 30 lines in this file.
//
// Licence: MIT.

export const VERSION = "1.0.0";

// ──────────────────────────────────────────────────────────────────────────
// Exact Python-compatible rounding
// ──────────────────────────────────────────────────────────────────────────

const _RBUF = new DataView(new ArrayBuffer(8));

/**
 * round(x, nd) with CPython semantics: half-to-even on the exact binary value.
 * @param {number} x
 * @param {number} nd number of decimal places (0..15)
 * @returns {number}
 */
export function pyRound(x, nd) {
  if (typeof x !== "number" || !Number.isFinite(x)) return x;
  if (x === 0) return x; // preserves -0, as Python's round does
  const neg = x < 0;
  const ax = neg ? -x : x;

  _RBUF.setFloat64(0, ax);
  const hi = _RBUF.getUint32(0);
  const lo = _RBUF.getUint32(4);
  const biased = (hi >>> 20) & 0x7ff;
  let mant = (BigInt(hi & 0xfffff) << 32n) | BigInt(lo);
  let e2;
  if (biased === 0) {
    e2 = -1074n; // subnormal
  } else {
    mant |= 1n << 52n;
    e2 = BigInt(biased - 1075);
  }
  // ax === mant * 2^e2, exactly.

  const P = 10n ** BigInt(nd);
  let num;
  let den;
  if (e2 >= 0n) {
    num = mant * P * (1n << e2);
    den = 1n;
  } else {
    num = mant * P;
    den = 1n << -e2;
  }
  let q = num / den;
  const rem = num - q * den;
  const twice = rem * 2n;
  if (twice > den) {
    q += 1n;
  } else if (twice === den && q % 2n === 1n) {
    q += 1n;
  }
  // Number(q) / Number(P): both operands exact for our magnitudes, so IEEE
  // division returns the nearest double to the exact decimal — which is what
  // CPython's strtod round-trip produces too.
  const res = Number(q) / Number(P);
  return neg ? -res : res;
}

// ──────────────────────────────────────────────────────────────────────────
// Ledger vocabulary
// ──────────────────────────────────────────────────────────────────────────

export const WORD_CONFIDENCE = {
  "very low": 0.1,
  low: 0.2,
  medium: 0.5,
  med: 0.5,
  moderate: 0.5,
  high: 0.85,
  "very high": 0.95,
};

const TRUE_OUTCOMES = new Set(["confirmed", "confirming"]);
const FALSE_OUTCOMES = new Set(["refuted"]);

// Python float() accepts underscores between digits, a leading sign, an
// exponent, and the literals inf/infinity/nan (case-insensitive). Number()
// accepts none of the first, and accepts things Python rejects (0x10, "").
// This regex is the intersection we honour; anything outside it is a parse
// failure in both ports.
const PY_FLOAT_RE = /^[+-]?(?:(?:\d(?:_?\d)*)?\.?(?:\d(?:_?\d)*)(?:[eE][+-]?\d(?:_?\d)*)?|(?:\d(?:_?\d)*)\.(?:[eE][+-]?\d(?:_?\d)*)?|inf|infinity|nan)$/;

/**
 * Parse a string the way Python's float() would. Returns NaN-free failure as
 * `null` (Python raises ValueError there; callers treat null as "not a number").
 * A genuine "nan" literal returns NaN.
 */
export function pyParseFloat(s) {
  const t = String(s == null ? "" : s).trim();
  if (!t) return null;
  const lowered = t.toLowerCase();
  if (!PY_FLOAT_RE.test(lowered)) return null;
  const stripped = lowered.replace(/_/g, "");
  if (/^[+-]?nan$/.test(stripped)) return NaN;
  if (/^[+-]?inf(inity)?$/.test(stripped)) return stripped.startsWith("-") ? -Infinity : Infinity;
  const v = Number(stripped);
  return Number.isNaN(v) ? null : v;
}

/**
 * Clamp to [0,1] reproducing the reference implementation's min/max exactly:
 * Python's min/max do NOT propagate NaN, so a NaN confidence lands on 1.0
 * there. Math.min DOES propagate. Both ports route through this helper so the
 * degenerate case cannot silently diverge.
 */
function clamp01(v, dflt) {
  if (typeof v !== "number") return dflt;
  if (Number.isNaN(v)) return 1.0;
  if (v < 0.0) return 0.0;
  if (v > 1.0) return 1.0;
  return v;
}

/** Confidence -> number in [0,1]. Accepts a number, "0.4", "40%", or a word. */
export function normalizeConfidence(value, dflt = 0.5) {
  if (value === null || value === undefined) return dflt;
  if (typeof value === "boolean") return value ? 1.0 : 0.0;
  if (typeof value === "number") return clamp01(value, dflt);
  const s = String(value).trim().toLowerCase();
  if (Object.prototype.hasOwnProperty.call(WORD_CONFIDENCE, s)) return WORD_CONFIDENCE[s];
  if (s.endsWith("%")) {
    const v = pyParseFloat(s.slice(0, -1));
    if (v === null) return dflt;
    return clamp01(v / 100.0, dflt);
  }
  const v = pyParseFloat(s);
  if (v === null) return dflt;
  return clamp01(v, dflt);
}

/** "confirmed" -> 1, "refuted" -> 0, anything else -> null (not scorable). */
export function outcomeToBinary(status) {
  // Mirrors Python's `str(status or "")`: every falsy value collapses to "".
  const s = String(status || "")
    .trim()
    .toLowerCase();
  if (TRUE_OUTCOMES.has(s)) return 1;
  if (FALSE_OUTCOMES.has(s)) return 0;
  return null;
}

// ──────────────────────────────────────────────────────────────────────────
// The math
// ──────────────────────────────────────────────────────────────────────────

/** Python's int(x) for the values a ledger can produce: truncation toward zero. */
function pyInt(y) {
  if (typeof y === "boolean") return y ? 1 : 0;
  if (typeof y === "number") {
    if (!Number.isFinite(y)) return null;
    return Math.trunc(y);
  }
  const t = String(y == null ? "" : y).trim();
  if (!/^[+-]?\d(_?\d)*$/.test(t)) return null;
  return Number(t.replace(/_/g, ""));
}

/** (probability in [0,1], outcome in {0,1}) pairs, dropping malformed entries. */
export function cleanPairs(pairs) {
  const out = [];
  for (const pr of pairs || []) {
    if (!pr || typeof pr.length !== "number" || pr.length !== 2) continue;
    let p = pr[0];
    if (typeof p === "boolean") p = p ? 1 : 0;
    else if (typeof p === "string") p = pyParseFloat(p);
    if (typeof p !== "number" || p === null) continue;
    const y = pyInt(pr[1]);
    if (y === null) continue;
    if (Number.isNaN(p) || p < 0.0 || p > 1.0 || (y !== 0 && y !== 1)) continue;
    out.push([p, y]);
  }
  return out;
}

/** Mean Brier score. null when there are no valid pairs. Unrounded. */
export function brierScore(pairs) {
  const clean = cleanPairs(pairs);
  if (!clean.length) return null;
  let acc = 0;
  for (const [p, y] of clean) acc += (p - y) ** 2;
  return acc / clean.length;
}

/** Brier skill score vs. the base-rate climatology forecast. null if degenerate. */
export function brierSkillScore(pairs) {
  const clean = cleanPairs(pairs);
  if (clean.length < 2) return null;
  let ysum = 0;
  for (const [, y] of clean) ysum += y;
  const baseRate = ysum / clean.length;
  let bsAcc = 0;
  for (const [p, y] of clean) bsAcc += (p - y) ** 2;
  const bs = bsAcc / clean.length;
  let refAcc = 0;
  for (const [, y] of clean) refAcc += (baseRate - y) ** 2;
  const bsRef = refAcc / clean.length;
  if (bsRef === 0) return null;
  return 1.0 - bs / bsRef;
}

/** Calibration-curve bins: stated vs. observed rate per confidence band. Unrounded. */
export function reliabilityBins(pairs, nBins = 10) {
  const clean = cleanPairs(pairs);
  if (!clean.length || nBins < 1) return [];
  const buckets = [];
  for (let i = 0; i < nBins; i += 1) buckets.push([]);
  for (const [p, y] of clean) {
    const idx = Math.min(nBins - 1, Math.trunc(p * nBins)); // p === 1.0 -> last bin
    buckets[idx].push([p, y]);
  }
  const out = [];
  for (let i = 0; i < nBins; i += 1) {
    const b = buckets[i];
    if (!b.length) continue;
    const n = b.length;
    let psum = 0;
    for (const [p] of b) psum += p;
    let ysum = 0;
    for (const [, y] of b) ysum += y;
    out.push({ lo: i / nBins, hi: (i + 1) / nBins, n, mean_confidence: psum / n, observed_rate: ysum / n });
  }
  return out;
}

/**
 * Score (confidence, outcome) pairs into a calibration summary.
 * Field-for-field identical to calibration_core.score_pairs.
 */
export function scorePairs(pairs, nBins = 10) {
  const scored = [];
  for (const pr of pairs || []) {
    const y = pr[1];
    if (y === 0 || y === 1) scored.push([pr[0], y]);
  }
  const n = scored.length;
  let confirmed = 0;
  for (const [, y] of scored) if (y === 1) confirmed += 1;
  const refuted = n - confirmed;
  const brier = brierScore(scored);
  const skill = brierSkillScore(scored);
  const bins = reliabilityBins(scored, nBins);
  const accuracyPct = n ? pyRound((100.0 * confirmed) / n, 1) : null;

  const skilled = skill === null ? null : skill > 0;

  let calibration = "insufficient_data";
  if (n >= 5 && bins.length) {
    let total = 0;
    for (const b of bins) total += b.n;
    let gapAcc = 0;
    for (const b of bins) gapAcc += b.n * (b.mean_confidence - b.observed_rate);
    const gap = gapAcc / total;
    if (gap > 0.15) calibration = "over-confident";
    else if (gap < -0.15) calibration = "under-confident";
    else if (skilled === false) calibration = "not_yet_skillful";
    else calibration = "well-calibrated";
  }

  let label;
  let score;
  if (n < 3) {
    label = "nascent";
    score = 30;
  } else if (skilled === false) {
    label = "not_yet_skillful";
    score = 45;
  } else if (brier !== null && brier <= 0.15 && n >= 12) {
    label = "authoritative";
    score = 90;
  } else if (brier !== null && brier <= 0.2) {
    label = "reliable";
    score = 70;
  } else {
    label = "developing";
    score = 50;
  }

  return {
    n,
    confirmed,
    refuted,
    accuracy_pct: accuracyPct,
    brier: brier === null ? null : pyRound(brier, 4),
    brier_skill: skill === null ? null : pyRound(skill, 4),
    skilled,
    reliability_bins: bins.map((b) => ({
      lo: pyRound(b.lo, 2),
      hi: pyRound(b.hi, 2),
      n: b.n,
      mean_confidence: pyRound(b.mean_confidence, 3),
      observed_rate: pyRound(b.observed_rate, 3),
    })),
    calibration,
    label,
    score,
  };
}

// ──────────────────────────────────────────────────────────────────────────
// Record extractors
// ──────────────────────────────────────────────────────────────────────────

export function pairsFromPredictionRecords(records) {
  const pairs = [];
  for (const r of records || []) {
    const raw = r.status || r.outcome;
    const y = outcomeToBinary(raw);
    if (y === null) continue;
    pairs.push([normalizeConfidence(r.confidence === undefined ? null : r.confidence), y]);
  }
  return pairs;
}

export function pairsFromCalibrationRows(rows) {
  const pairs = [];
  for (const r of rows || []) {
    if (r.record_type === "forecast_resolution") continue;
    const y = outcomeToBinary(r.outcome);
    if (y === null) continue;
    pairs.push([normalizeConfidence(r.stated_confidence === undefined ? null : r.stated_confidence), y]);
  }
  return pairs;
}

export function pairsFromForecastResolutionRows(rows) {
  const pairs = [];
  for (const r of rows || []) {
    if (r.record_type !== "forecast_resolution") continue;
    const covered = r.covered;
    if (covered === null || covered === undefined) continue;
    pairs.push([normalizeConfidence(r.confidence === undefined ? null : r.confidence), covered ? 1 : 0]);
  }
  return pairs;
}

// ──────────────────────────────────────────────────────────────────────────
// Paste-a-ledger input adapter
// ──────────────────────────────────────────────────────────────────────────

const OUTCOME_ALIASES = {
  1: "confirmed",
  true: "confirmed",
  t: "confirmed",
  y: "confirmed",
  yes: "confirmed",
  hit: "confirmed",
  right: "confirmed",
  correct: "confirmed",
  happened: "confirmed",
  confirmed: "confirmed",
  confirming: "confirmed",
  0: "refuted",
  false: "refuted",
  f: "refuted",
  n: "refuted",
  no: "refuted",
  miss: "refuted",
  wrong: "refuted",
  incorrect: "refuted",
  refuted: "refuted",
};

const UNRESOLVED_OUTCOMES = new Set([
  "",
  "pending",
  "open",
  "unresolved",
  "unknown",
  "inconclusive",
  "expired",
  "tbd",
  "n/a",
  "na",
  "-",
]);

const CONF_HEADERS = new Set(["confidence", "conf", "probability", "prob", "p", "stated_confidence"]);
const OUTCOME_HEADERS = new Set(["outcome", "result", "actual", "y", "status", "truth"]);

/** Strict confidence parse for pasted text -> [value, note] or [null, reason]. */
export function parseConfidenceField(raw) {
  const s = String(raw == null ? "" : raw)
    .trim()
    .toLowerCase();
  if (!s) return [null, "empty confidence"];
  if (Object.prototype.hasOwnProperty.call(WORD_CONFIDENCE, s)) return [WORD_CONFIDENCE[s], null];
  const pct = s.endsWith("%");
  const body = pct ? s.slice(0, -1).trim() : s;
  const parsed = pyParseFloat(body);
  if (parsed === null) return [null, "unreadable confidence"];
  if (Number.isNaN(parsed) || !Number.isFinite(parsed)) return [null, "unreadable confidence"];
  let v = parsed;
  let note = null;
  if (pct) {
    v = v / 100.0;
  } else if (v >= 0.0 && v <= 1.0) {
    note = null;
  } else if (v > 1.0 && v <= 100.0) {
    v = v / 100.0;
    note = "read as a percentage";
  } else {
    return [null, "confidence out of range"];
  }
  if (v < 0.0 || v > 1.0) return [null, "confidence out of range"];
  return [v, note];
}

function splitFields(line) {
  const parts = line.includes("\t") ? line.split("\t") : line.split(",");
  return parts.map((p) => p.trim().replace(/^"+|"+$/g, "").trim());
}

/**
 * Parse a pasted CSV/TSV ledger into scorable pairs.
 * Returns {pairs, unresolved, rejected, notes} — nothing is defaulted or invented.
 */
export function parseLedgerText(text) {
  const pairs = [];
  const rejected = [];
  const notes = [];
  let unresolved = 0;
  let ci = 0;
  let oi = 1;
  let headerSeen = false;

  const lines = String(text == null ? "" : text)
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .split("\n");

  for (let i = 0; i < lines.length; i += 1) {
    const lineNo = i + 1;
    const line = lines[i].trim();
    if (!line || line.startsWith("#")) continue;
    const fields = splitFields(line);
    if (fields.length < 2) {
      rejected.push({ line: lineNo, raw: line, reason: "need at least two fields (confidence, outcome)" });
      continue;
    }

    if (!headerSeen) {
      headerSeen = true;
      const lowered = fields.map((f) => f.toLowerCase());
      let foundC = null;
      let foundO = null;
      for (let k = 0; k < lowered.length; k += 1) {
        if (foundC === null && CONF_HEADERS.has(lowered[k])) foundC = k;
      }
      for (let k = 0; k < lowered.length; k += 1) {
        if (foundO === null && OUTCOME_HEADERS.has(lowered[k])) foundO = k;
      }
      if (foundC !== null && foundO !== null) {
        ci = foundC;
        oi = foundO;
        continue;
      }
    }

    if (ci >= fields.length || oi >= fields.length) {
      rejected.push({ line: lineNo, raw: line, reason: "missing confidence or outcome column" });
      continue;
    }

    const outcomeRaw = String(fields[oi] || "")
      .trim()
      .toLowerCase();
    if (UNRESOLVED_OUTCOMES.has(outcomeRaw)) {
      unresolved += 1;
      continue;
    }
    const canonical = Object.prototype.hasOwnProperty.call(OUTCOME_ALIASES, outcomeRaw) ? OUTCOME_ALIASES[outcomeRaw] : null;
    if (canonical === null) {
      rejected.push({ line: lineNo, raw: line, reason: "unreadable outcome" });
      continue;
    }
    const y = outcomeToBinary(canonical);

    const [conf, reasonOrNote] = parseConfidenceField(fields[ci]);
    if (conf === null) {
      rejected.push({ line: lineNo, raw: line, reason: reasonOrNote });
      continue;
    }
    if (reasonOrNote) notes.push({ line: lineNo, note: reasonOrNote });
    pairs.push([conf, y]);
  }

  return { pairs, unresolved, rejected, notes };
}
