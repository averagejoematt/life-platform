"""
personal_baselines.py — percentile bands from Matthew's own distribution (#543, ADR-105 rule 4).

ADR-105 rule 4: "New thresholds derive from personal variance — or document why not.
Percentile bands over Matthew's own distribution beat hand-set cutoffs (a 40-point
readiness floor means nothing if his p10 is 55)." This module is that rule's machinery.

TWO halves live here:

  1. The COMPUTE half (pure functions `compute_bands` + `percentile`) — the monthly
     `personal_baselines_lambda` collects Matthew's own history for each metric and calls
     `compute_bands` to turn it into per-metric percentile bands. stdlib only (no numpy).

  2. The READ half (`load_baselines` + the per-metric scorers) — the LIVE consumers
     (daily-metrics readiness, daily-insight momentum) read the stored bands and use them
     INSTEAD of the hand-set constants they use today.

FLOOR-GUARD (the load-bearing safety property, tested): a band is only produced — and only
used — when the metric has at least `MIN_N` observations. Below that, `compute_bands`
emits None for the metric and every consumer falls back to the EXACT constant it uses
today (`FALLBACK_ANCHORS`). So behavior is UNCHANGED until enough of Matthew's own data
exists; this is deliberately conservative because these thresholds feed live training/
readiness verdicts. The fallback anchors are chosen to reproduce the current formulas
exactly (see the module tests).

NOT personalized here (ADR-105 rule 4's carve-out — legitimate population-derived
constants, kept and LABELLED as such where used): ACWR's Gabbett zones and clinical lab
ranges. #543 changes ACWR's *estimator* (rolling mean → EWMA) and surfaces the
ratio-coupling caveat, but keeps the Gabbett zone thresholds — see acwr_compute_lambda.
"""

MIN_N = 30  # floor-guard: a band replaces its constant only with >= this many observations

# The DynamoDB address of the latest snapshot (SOURCE#personal_baselines).
BASELINES_SOURCE = "personal_baselines"
BASELINES_SK = "SNAPSHOT#LATEST"

# Hand-set / population fallbacks — the EXACT constants the consumers use today. When a
# metric's band is thin (or absent), the consumer uses these and behaves identically to
# pre-#543. Keep these in lock-step with the constants embedded in the consumers so the
# floor-guard path is a true no-op.
#
#   readiness_hrv_ratio: compute_readiness maps the 7d/30d HRV ratio to 0-100 via
#       clamp((ratio - 0.75) * 200) — i.e. ratio 0.75 -> 0, 1.0 -> 50, 1.25 -> 100.
#       Expressed as evenly-spaced anchors, a piecewise-linear map through them IS that
#       exact line, so the fallback reproduces the current score bit-for-bit.
#   grade_trend_pct: compute_momentum labels week-over-week grade trend "improving" above
#       +5% and "declining" below -5%.
FALLBACK_ANCHORS = {
    "readiness_hrv_ratio": {"p10": 0.75, "p50": 1.0, "p90": 1.25},
    "grade_trend_pct": {"lo": -5.0, "hi": 5.0},
}


# ─────────────────────────────────────────────────────────────────────────────
# COMPUTE HALF — pure percentile math (used by personal_baselines_lambda)
# ─────────────────────────────────────────────────────────────────────────────


def percentile(values, p):
    """Linear-interpolation percentile of a numeric list. p in [0, 100].

    Type-7 (the common spreadsheet/numpy default) linear interpolation between order
    statistics. Non-numeric / None entries are dropped. Returns None on an empty list.
    stdlib only.
    """
    clean = []
    for v in values:
        if v is None:
            continue
        try:
            clean.append(float(v))
        except (TypeError, ValueError):
            continue
    if not clean:
        return None
    clean.sort()
    n = len(clean)
    if n == 1:
        return clean[0]
    if p <= 0:
        return clean[0]
    if p >= 100:
        return clean[-1]
    rank = (p / 100.0) * (n - 1)
    lo = int(rank)
    frac = rank - lo
    if lo + 1 >= n:
        return clean[lo]
    return clean[lo] + frac * (clean[lo + 1] - clean[lo])


def _band_readiness_hrv_ratio(ratios):
    """Three-anchor band {p10, p50, p90} for the HRV 7d/30d ratio, or None if thin."""
    clean = [r for r in ratios if r is not None]
    if len(clean) < MIN_N:
        return None
    return {
        "p10": round(percentile(clean, 10), 4),
        "p50": round(percentile(clean, 50), 4),
        "p90": round(percentile(clean, 90), 4),
        "n": len(clean),
    }


def _band_grade_trend(trends):
    """Two-anchor band {lo, hi} for week-over-week grade trend %, or None if thin.

    The middle 50% of Matthew's own week-over-week swings (p25..p75) is "stable"; a swing
    below his p25 is "declining", above his p75 is "improving". Replaces the symmetric
    hand-set +-5% band with what a normal week actually looks like for him.
    """
    clean = [t for t in trends if t is not None]
    if len(clean) < MIN_N:
        return None
    return {
        "lo": round(percentile(clean, 25), 3),
        "hi": round(percentile(clean, 75), 3),
        "n": len(clean),
    }


def compute_bands(hrv_ratios, grade_trends):
    """Turn collected history into per-metric bands. Pure — the lambda owns the fetch.

    Returns {metric: band_dict or None}. None means "too thin — consumers fall back to
    the constant". Deterministic; no I/O.
    """
    return {
        "readiness_hrv_ratio": _band_readiness_hrv_ratio(hrv_ratios),
        "grade_trend_pct": _band_grade_trend(grade_trends),
    }


# ─────────────────────────────────────────────────────────────────────────────
# READ HALF — consumers load the stored bands and score against them
# ─────────────────────────────────────────────────────────────────────────────


def _to_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_baselines(table, user_prefix):
    """Read the latest stored bands from DDB. Returns {metric: band} or {} on miss/error.

    `user_prefix` is the caller's `USER#{id}#SOURCE#` prefix. Never raises — any failure
    (missing record, throttle, bad shape) yields {} so consumers cleanly fall back to
    the constants (the floor-guard path).
    """
    try:
        resp = table.get_item(Key={"pk": user_prefix + BASELINES_SOURCE, "sk": BASELINES_SK})
    except Exception:
        return {}
    item = resp.get("Item") or {}
    bands = item.get("bands") or {}
    out = {}
    for metric, band in bands.items():
        if not isinstance(band, dict):
            continue
        out[metric] = {k: (_to_float(v) if k != "n" else int(_to_float(v) or 0)) for k, v in band.items()}
    return out


def _anchors_or_fallback(baselines, metric, required_keys):
    """Return (band, source_label). Uses the stored band only when it is present, has all
    required keys, and cleared the floor-guard (n >= MIN_N); else the population fallback.
    """
    band = (baselines or {}).get(metric)
    if band and band.get("n", 0) >= MIN_N and all(band.get(k) is not None for k in required_keys):
        return band, "personal"
    return FALLBACK_ANCHORS[metric], "population_fallback"


def _clamp(x, lo=0, hi=100):
    return max(lo, min(hi, x))


def readiness_hrv_score(ratio, baselines):
    """Map the HRV 7d/30d ratio to a 0-100 readiness sub-score via personal bands.

    Piecewise-linear through {p10 -> 0, p50 -> 50, p90 -> 100}, clamped to [0, 100].
    With the fallback anchors {0.75, 1.0, 1.25} this reproduces the legacy
    clamp((ratio - 0.75) * 200) exactly. Returns (score:int, source_label:str).
    """
    band, src = _anchors_or_fallback(baselines, "readiness_hrv_ratio", ("p10", "p50", "p90"))
    p10, p50, p90 = band["p10"], band["p50"], band["p90"]
    if ratio <= p50:
        span = p50 - p10
        score = 50.0 * (ratio - p10) / span if span > 0 else (0.0 if ratio < p50 else 50.0)
    else:
        span = p90 - p50
        score = 50.0 + 50.0 * (ratio - p50) / span if span > 0 else 100.0
    return int(_clamp(round(score))), src


def grade_trend_signal(trend_pct, baselines):
    """Label a week-over-week grade trend % using personal bands.

    Above the upper band -> "improving", below the lower band -> "declining", else
    "stable". Fallback band is +-5%. Returns (signal:str, source_label:str).
    """
    band, src = _anchors_or_fallback(baselines, "grade_trend_pct", ("lo", "hi"))
    if trend_pct > band["hi"]:
        return "improving", src
    if trend_pct < band["lo"]:
        return "declining", src
    return "stable", src
