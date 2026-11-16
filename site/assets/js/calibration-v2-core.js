// calibration-v2-core.js — the browser port of lambdas/experiment/calibration_v2.py (owner ruling 2026-11-09).
//
// /method/grade-your-coach/ grades a pasted ledger with the SAME calibration method the platform's own coaches are
// graded by: calibration-v2's three separate questions (docs/methods/CALIBRATION_V2.md). This file is a line-by-line
// port of the Python module's estimability and over/under-confidence tests, held to it EXACTLY by shared vectors
// (tests/fixtures/calibration_v2_vectors.json — tests/test_calibration_v2_js_parity.py checks the vectors against the
// Python, tests/js/calibration_v2_core.test.mjs checks this file against the vectors). A pasted ledger carries no
// same-call baseline, so its third answer is always "no baseline". Pure, deterministic, no dependencies, no network.
//
// The constants are the Python module's, copied — never tuned here.

export const METHOD_VERSION = "calibration-v2";
export const ALPHA = 0.05;
export const LEVEL_BINS = 10;
export const USABLE_CI_WIDTH = 0.5;
export const MIN_LEVELS = 2;
export const EVENTS_PER_PARAMETER = 10;
export const RECALIBRATION_PARAMETERS = 2;
export const SKILL_RULE = "nothing_changes";

// ── Python-compatible number handling ─────────────────────────────────────────────────────

/** Python's round(x, nd): round-half-even on the exact binary value. */
export function pyRound(x, nd = 0) {
  if (!Number.isFinite(x)) return x;
  const fixed = x.toFixed(nd); // correctly rounded on the exact value, ties away from zero
  // A tie is exactly representable only when the exact expansion ends in 5 at digit nd+1.
  const exact = Math.abs(x).toFixed(Math.min(100, nd + 60));
  const dot = exact.indexOf(".");
  const tail = exact.slice(dot + 1 + nd);
  if (/^50*$/.test(tail)) {
    const scaled = Math.round(Math.abs(x) * 10 ** nd - 0.5); // the lower neighbour
    const even = scaled % 2 === 0 ? scaled : scaled + 1;
    const v = even / 10 ** nd;
    return x < 0 ? -v : v;
  }
  return Number(fixed);
}

/** Python's str(float) for the values this method prints (repr; integers keep ".0"; exponents as e-05). */
export function pyFloat(x) {
  if (Number.isInteger(x)) return `${x}.0`;
  const s = String(x);
  return s.replace(/e([+-])(\d)$/, "e$10$2");
}

/** Python's f"{v:.0f}". */
function fmt0(v) {
  return String(pyRound(v, 0));
}

// ── exact binomial machinery ──────────────────────────────────────────────────────────────

const LOGFACT = [0];
function logFactorial(n) {
  for (let i = LOGFACT.length; i <= n; i++) LOGFACT[i] = LOGFACT[i - 1] + Math.log(i);
  return LOGFACT[n];
}

function logPmf(k, n, p) {
  if (p <= 0) return k === 0 ? 0 : -Infinity;
  if (p >= 1) return k === n ? 0 : -Infinity;
  return logFactorial(n) - logFactorial(k) - logFactorial(n - k) + k * Math.log(p) + (n - k) * Math.log1p(-p);
}

function cdf(k, n, p) {
  if (k < 0) return 0;
  if (k >= n) return 1;
  let s = 0;
  for (let i = 0; i <= k; i++) s += Math.exp(logPmf(i, n, p));
  return Math.min(1, s);
}

function sf(k, n, p) {
  if (k <= 0) return 1;
  if (k > n) return 0;
  let s = 0;
  for (let i = k; i <= n; i++) s += Math.exp(logPmf(i, n, p));
  return Math.min(1, s);
}

export function binomialTwoSidedP(k, n, p0) {
  if (n <= 0) throw new Error("binomial test needs n > 0");
  return Math.min(1, 2 * Math.min(cdf(k, n, p0), sf(k, n, p0)));
}

export function clopperPearson(k, n, confidence = 0.95) {
  if (n <= 0 || k < 0 || k > n) throw new Error("interval needs 0 <= k <= n and n > 0");
  const a = (1 - confidence) / 2;
  const solve = (f, target) => {
    let lo = 0;
    let hi = 1;
    for (let i = 0; i < 60; i++) {
      const mid = (lo + hi) / 2;
      if (f(mid) < target) lo = mid;
      else hi = mid;
    }
    return (lo + hi) / 2;
  };
  const lower = k === 0 ? 0 : solve((q) => sf(k, n, q), a);
  const upper = k === n ? 1 : solve((q) => 1 - cdf(k, n, q), 1 - a);
  return [lower, upper];
}

const MIN_LEVEL_N = new Map();
export function minLevelN(width = USABLE_CI_WIDTH, confidence = 0.95) {
  const key = `${width}|${confidence}`;
  if (!MIN_LEVEL_N.has(key)) {
    let n = 1;
    for (;;) {
      let widest = 0;
      for (let k = 0; k <= n; k++) {
        const [lo, hi] = clopperPearson(k, n, confidence);
        widest = Math.max(widest, hi - lo);
      }
      if (widest <= width) break;
      n += 1;
    }
    MIN_LEVEL_N.set(key, n);
  }
  return MIN_LEVEL_N.get(key);
}

function order(pvalues) {
  // Python's sorted() is stable: equal p-values keep input order.
  return pvalues.map((p, i) => [p, i]).sort((x, y) => x[0] - y[0] || x[1] - y[1]).map((x) => x[1]);
}

export function holm(pvalues, alpha = ALPHA) {
  const m = pvalues.length;
  const reject = new Array(m).fill(false);
  const idx = order(pvalues);
  for (let rank = 0; rank < idx.length; rank++) {
    const i = idx[rank];
    if (pvalues[i] <= alpha / (m - rank)) reject[i] = true;
    else break;
  }
  return reject;
}

export function holmAdjusted(pvalues) {
  const m = pvalues.length;
  const adj = new Array(m).fill(1);
  let running = 0;
  order(pvalues).forEach((i, rank) => {
    running = Math.max(running, Math.min(1, (m - rank) * pvalues[i]));
    adj[i] = running;
  });
  return adj;
}

// ── levels ────────────────────────────────────────────────────────────────────────────────

function clean(pairs) {
  const out = [];
  for (const pr of pairs || []) {
    if (!Array.isArray(pr) || pr.length !== 2) continue;
    const p = Number(pr[0]);
    const y = Number(pr[1]);
    if (!Number.isFinite(p) || p < 0 || p > 1 || (y !== 0 && y !== 1)) continue;
    out.push([p, y]);
  }
  return out;
}

function levelsOf(rows) {
  const buckets = new Map();
  for (const [p, y] of rows) {
    const idx = Math.min(LEVEL_BINS - 1, Math.trunc(p * LEVEL_BINS));
    if (!buckets.has(idx)) buckets.set(idx, []);
    buckets.get(idx).push([p, y]);
  }
  return [...buckets.keys()]
    .sort((a, b) => a - b)
    .map((idx) => {
      const r = buckets.get(idx);
      let stated = 0;
      let hits = 0;
      for (const [p, y] of r) {
        stated += p;
        hits += y;
      }
      return { lo: pyRound(idx / LEVEL_BINS, 2), hi: pyRound((idx + 1) / LEVEL_BINS, 2), n: r.length, hits, stated: stated / r.length };
    });
}

const pct = (x) => `${fmt0(100 * x)}%`;
const ciWords = (ci) => `95% CI ${pct(ci[0])}–${pct(ci[1])}`;
const levelName = (t) => pct(t.stated);
function foundWords(t) {
  const p = t.p_holm < 0.0001 ? "< 0.0001" : pyFloat(t.p_holm);
  return `${t.hits} of ${t.n} came true, ${ciWords(t.ci95)}; Holm-adjusted p ${p}`;
}

// ── question 1: can calibration be estimated? ─────────────────────────────────────────────

function logit(p) {
  const q = Math.min(0.99, Math.max(0.01, p));
  return Math.log(q / (1 - q));
}

export function recalibrationSlope(rows) {
  const xs = rows.map(([p]) => logit(p));
  const ys = rows.map(([, y]) => y);
  if (new Set(xs.map((x) => pyRound(x, 9))).size < 2 || new Set(ys).size < 2) return null;
  let a = 0;
  let b = 0;
  for (let it = 0; it < 100; it++) {
    let g0 = 0;
    let g1 = 0;
    let h00 = 0;
    let h01 = 0;
    let h11 = 0;
    for (let j = 0; j < xs.length; j++) {
      const x = xs[j];
      const y = ys[j];
      const mu = 1 / (1 + Math.exp(-(a + b * x)));
      const w = mu * (1 - mu);
      g0 += y - mu;
      g1 += (y - mu) * x;
      h00 += w;
      h01 += w * x;
      h11 += w * x * x;
    }
    const det = h00 * h11 - h01 * h01;
    if (det <= 1e-12) return null;
    const da = (h11 * g0 - h01 * g1) / det;
    const db = (h00 * g1 - h01 * g0) / det;
    a += da;
    b += db;
    if (Math.abs(b) > 50) return null;
    if (Math.abs(da) < 1e-10 && Math.abs(db) < 1e-10) {
      const se = Math.sqrt(h00 / det);
      return {
        estimate: pyRound(b, 3),
        ci95: [pyRound(b - 1.959964 * se, 3), pyRound(b + 1.959964 * se, 3)],
        intercept: pyRound(a, 3),
        method: "logistic recalibration slope (Cox 1958), Wald 95% interval",
      };
    }
  }
  return null;
}

export function estimability(pairs) {
  const rows = clean(pairs);
  const n = rows.length;
  const needN = minLevelN();
  const needEvents = EVENTS_PER_PARAMETER * RECALIBRATION_PARAMETERS;
  const levels = levelsOf(rows).map((lv) => {
    const [lo, hi] = clopperPearson(lv.hits, lv.n);
    const ci = [pyRound(lo, 3), pyRound(hi, 3)];
    return {
      lo: lv.lo,
      hi: lv.hi,
      n: lv.n,
      hits: lv.hits,
      stated: pyRound(lv.stated, 3),
      observed: pyRound(lv.hits / lv.n, 3),
      ci95: ci,
      ci_usable: lv.n >= needN,
      statement: `Calls stated at about ${pct(lv.stated)} came true ${lv.hits} of ${lv.n} (${ciWords(ci)}).`,
    };
  });
  const usable = levels.filter((lv) => lv.ci_usable).length;
  const hits = rows.reduce((s, [, y]) => s + y, 0);
  const minority = Math.min(hits, n - hits);
  const reasons = [];
  if (usable < MIN_LEVELS) reasons.push(`${usable} confidence level(s) with at least ${needN} calls, ${MIN_LEVELS} needed`);
  if (minority < needEvents) reasons.push(`${minority} calls of the rarer outcome, ${needEvents} needed`);
  let slope = null;
  if (!reasons.length) {
    slope = recalibrationSlope(rows);
    if (slope === null) reasons.push("the recalibration fit is degenerate on these calls");
  }
  let wording;
  let short;
  if (n === 0) {
    wording = "No resolved calls.";
    short = "no resolved calls";
  } else if (slope !== null) {
    const [l, h] = slope.ci95.map(pyFloat);
    wording =
      `Calibration across confidence levels is estimable over ${n} calls: recalibration slope ${pyFloat(slope.estimate)} ` +
      `(95% CI ${l} to ${h}; 1 means stated confidence tracks outcomes).`;
    short = `estimable: slope ${pyFloat(slope.estimate)} (95% CI ${l} to ${h})`;
  } else {
    wording = "Calibration across confidence levels not estimable: " + reasons.join("; ") + ".";
    short = "not estimable across confidence levels";
  }
  return {
    result: reasons.length ? "not_estimable" : "estimable",
    n,
    estimate: slope ? slope.estimate : null,
    ci95: slope ? slope.ci95 : null,
    slope,
    levels,
    usable_levels: usable,
    minority_outcome_n: minority,
    reasons,
    wording,
    short,
    method:
      `Levels are the ${LEVEL_BINS} stated-confidence bands, each with an exact (Clopper-Pearson) 95% interval. ` +
      `Across levels is estimable with at least ${MIN_LEVELS} levels of at least ${needN} calls (exact interval ` +
      `no wider than ${pyFloat(USABLE_CI_WIDTH)}) and at least ${needEvents} calls of the rarer outcome (10 per parameter); ` +
      "the estimate is the logistic recalibration slope with a Wald 95% interval.",
  };
}

// ── question 2: over- or under-confidence ─────────────────────────────────────────────────

export function confidenceDirection(pairs, alpha = ALPHA) {
  const levels = levelsOf(clean(pairs));
  const n = levels.reduce((s, lv) => s + lv.n, 0);
  const method =
    "Exact two-sided binomial test of each level's hits against its mean stated confidence (conservative when the " +
    `stated values inside a level differ), Holm-adjusted across the levels tested, family-wise alpha ${pyFloat(alpha)}. Calls ` +
    "that share a metric and a window are not independent, so the p-values are optimistic.";
  const base = { n, significance: alpha, method };
  if (!levels.length) {
    return { ...base, result: "no_resolved_calls", label: null, estimate: null, ci95: null, tests: [], wording: "No resolved calls.", short: "no resolved calls" };
  }
  const ps = levels.map((lv) => binomialTwoSidedP(lv.hits, lv.n, lv.stated));
  const adjusted = holmAdjusted(ps);
  const rejected = holm(ps, alpha);
  const m = levels.length;
  const couldReject = levels.some((lv) => Math.min(binomialTwoSidedP(0, lv.n, lv.stated), binomialTwoSidedP(lv.n, lv.n, lv.stated)) <= alpha / m);
  const tests = levels.map((lv, i) => {
    const observed = lv.hits / lv.n;
    const [lo, hi] = clopperPearson(lv.hits, lv.n);
    return {
      lo: lv.lo,
      hi: lv.hi,
      n: lv.n,
      hits: lv.hits,
      stated: pyRound(lv.stated, 3),
      observed: pyRound(observed, 3),
      gap: pyRound(lv.stated - observed, 3),
      gap_ci95: [pyRound(lv.stated - hi, 3), pyRound(lv.stated - lo, 3)],
      ci95: [pyRound(lo, 3), pyRound(hi, 3)],
      p: pyRound(ps[i], 4),
      p_holm: pyRound(adjusted[i], 4),
      rejects: rejected[i],
      direction: rejected[i] ? (observed < lv.stated ? "over" : "under") : null,
    };
  });
  // Python's min() keeps the FIRST of equal keys.
  let lead = tests[0];
  for (const t of tests.slice(1)) if (t.p_holm < lead.p_holm || (t.p_holm === lead.p_holm && -t.n < -lead.n)) lead = t;
  const found = tests.filter((t) => t.direction);
  const dirs = new Set(found.map((t) => t.direction));
  const scope =
    found.length > 1
      ? " — findings about calls at those confidence levels, not about calibration across confidence levels."
      : " — a finding about calls at that confidence level, not about calibration across confidence levels.";
  let result;
  let label;
  let wording;
  let short;
  if (dirs.size === 2) {
    result = label = "mixed";
    wording = "Mixed: " + found.map((t) => `${t.direction}-confident at its ${levelName(t)} calls (${foundWords(t)})`).join("; ") + scope;
    short = "mixed: " + found.map((t) => `${t.direction}-confident at its ${levelName(t)} calls`).join(", ");
  } else if (dirs.size === 1) {
    const d = [...dirs][0];
    result = label = `${d}_confident`;
    const lv = found.map(levelName).join(" and ");
    const detail = found.length > 1 ? found.map((t) => `${levelName(t)}: ${foundWords(t)}`).join("; ") : foundWords(found[0]);
    wording = `${d.charAt(0).toUpperCase()}${d.slice(1)}-confident at its ${lv} calls (${detail})${scope}`;
    short = `${d}-confident at its ${lv} calls`;
  } else if (!couldReject) {
    result = "insufficient_evidence";
    label = null;
    wording = `Insufficient evidence: with ${n} calls, no confidence level could have shown a departure at alpha ${pyFloat(alpha)}.`;
    short = "insufficient evidence";
  } else {
    result = "consistent_not_established";
    label = null;
    wording = `Consistent with stated confidence (not established): no level departs at alpha ${pyFloat(alpha)} over ${n} calls.`;
    short = "consistent with stated confidence (not established)";
  }
  return { ...base, result, label, estimate: lead.gap, ci95: lead.gap_ci95, estimate_level: [lead.lo, lead.hi], tests, wording, short };
}

// ── question 3: a pasted ledger has no same-call baseline ─────────────────────────────────

export function skillNoBaseline(alpha = ALPHA) {
  const method =
    `Paired against '${SKILL_RULE}' on the same calls: exact sign test on the calls only one of the two got ` +
    "right. The estimate is the hit-rate difference (coach minus rule); its interval is exact conditional on the " +
    "number of disagreements (Clopper-Pearson on the coach's share), Bonferroni-adjusted across the records. Records " +
    "are never added together. Calls that share a metric and a window are not independent, so it is optimistic.";
  return { baseline: null, significance: alpha, method, result: "no_baseline", label: null, records: {}, n: 0, wording: "No baseline for this stratum.", short: "no baseline for this stratum" };
}

/** calibration_v2.assess(pairs) with no baseline — the three answers for one pasted ledger. */
export function assess(pairs) {
  const est = estimability(pairs);
  return { method_version: METHOD_VERSION, n: est.n, estimability: est, confidence_direction: confidenceDirection(pairs), skill: skillNoBaseline() };
}
