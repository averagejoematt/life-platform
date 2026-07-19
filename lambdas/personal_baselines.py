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

#1412 extends the machinery to the CHARACTER ENGINE's pillar-component targets
(CHARACTER_TARGET_SPECS below): sleep duration/deep/REM targets and the daily-steps
target derive from percentile bands over Matthew's own year of history (p75 = "a good
day by his own distribution"), with per-target provenance {method, window_days, n} and
the same MIN_N floor-guard — below it the authored constant survives, explicitly
labeled "population prior, n<30" wherever surfaced. Deliberately NOT derived (the
documented carve-outs, per rule 4's "or document why not"):
  - pillar/component WEIGHTS and EMA lambdas — priority/policy choices, not
    distributional thresholds; there is no personal distribution they estimate.
  - protein_total / calorie_adherence — goal-derived from body weight + the
    MacroFactor adaptive target (already personal), not from observed variance.
  - zone2_adequacy (150 min), training_frequency, strength/reading day targets —
    protocol commitments; deriving them from observed behavior would ratify drift.
  - clinical ranges (BP, glucose, labs, RHR) — population/clinical semantics.
Each derived target also carries a documented population GUARDRAIL band (`bounds`)
the personal value clamps into, labeled when applied — a bad stretch may lower his
p75, but a target may never drift into clinically indefensible territory silently.
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

# ── #1412: character pillar-component targets derived from personal variance ──
# The exact below-floor label the acceptance criteria require, verbatim, wherever a
# fallback is surfaced (component details, /api/character_config, receipts).
POPULATION_PRIOR_LABEL = "population prior, n<30"

CHARACTER_TARGET_METHOD = "percentile_band"

# metric → where its derived value lands in character_sheet.json config, which
# percentile of Matthew's own distribution becomes the target, the population
# guardrail band it clamps into (documented ADR-105 carve-out — labeled when
# applied), and output rounding (ndigits; 0 → int).
CHARACTER_TARGET_SPECS = {
    "sleep_duration_hours": {
        "pillar": "sleep",
        "component": "duration_vs_target",
        "key": "target_hours",
        "percentile": 75,
        "bounds": (6.5, 9.0),  # never target less sleep than the clinical floor
        "round": 2,
    },
    "deep_sleep_fraction": {
        "pillar": "sleep",
        "component": "deep_sleep_pct",
        "key": "target_pct",
        "percentile": 75,
        "bounds": (0.10, 0.25),
        "round": 4,
    },
    "rem_sleep_fraction": {
        "pillar": "sleep",
        "component": "rem_pct",
        "key": "target_pct",
        "percentile": 75,
        "bounds": (0.15, 0.30),
        "round": 4,
    },
    "daily_steps": {
        "pillar": "movement",
        "component": "daily_steps",
        "key": "target",
        "percentile": 75,
        "bounds": (6000.0, 15000.0),
        "round": 0,
    },
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


def _band_character_target(values):
    """Three-anchor percentile band {p25, p50, p75, n} over one metric's own history,
    or None below the MIN_N floor-guard (#1412). Non-numeric/None entries dropped."""
    clean = []
    for v in values or []:
        if v is None:
            continue
        try:
            clean.append(float(v))
        except (TypeError, ValueError):
            continue
    if len(clean) < MIN_N:
        return None
    return {
        "p25": round(percentile(clean, 25), 4),
        "p50": round(percentile(clean, 50), 4),
        "p75": round(percentile(clean, 75), 4),
        "n": len(clean),
    }


def compute_character_target_bands(series_by_metric, window_days=None):
    """Turn collected per-metric history into character-target bands (#1412).

    Returns {metric: band or None} for EVERY metric in CHARACTER_TARGET_SPECS —
    None means "too thin, authored constant survives (labeled)". `window_days`
    (the lambda's lookback) is stamped into each band as derivation provenance.
    Pure — the lambda owns the fetch. Deterministic; no I/O.
    """
    out = {}
    for metric in CHARACTER_TARGET_SPECS:
        band = _band_character_target((series_by_metric or {}).get(metric))
        if band is not None and window_days is not None:
            band["window_days"] = int(window_days)
        out[metric] = band
    return out


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
        out[metric] = {k: (int(_to_float(v) or 0) if k in ("n", "window_days") else _to_float(v)) for k, v in band.items()}
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


# ─────────────────────────────────────────────────────────────────────────────
# #1412: character-engine target derivation (READ half)
# ─────────────────────────────────────────────────────────────────────────────


def derive_component_target(metric, baselines):
    """Resolve ONE character-component target from the stored bands (#1412).

    Returns (value, provenance):
      - band present, n >= MIN_N → (the personal percentile value, rounded per
        spec and clamped into the documented guardrail bounds — labeled when
        the clamp bites), provenance {source: personal, method, window_days, n}.
      - below floor / absent → (None, {source: population_prior,
        label: "population prior, n<30", n}) — the caller keeps the authored
        constant and surfaces the label (the ADR-105 acceptance contract).
    """
    spec = CHARACTER_TARGET_SPECS[metric]
    band = (baselines or {}).get(metric)
    n = int(band.get("n") or 0) if isinstance(band, dict) else 0
    pkey = f"p{spec['percentile']}"
    if isinstance(band, dict) and n >= MIN_N and band.get(pkey) is not None:
        value = float(band[pkey])
        provenance = {
            "source": "personal",
            "method": f"{CHARACTER_TARGET_METHOD}_{pkey}",
            "window_days": band.get("window_days"),
            "n": n,
        }
        lo, hi = spec["bounds"]
        clamped = min(max(value, lo), hi)
        if clamped != value:
            provenance["clamped"] = True
            provenance["bounds"] = [lo, hi]
            value = clamped
        ndigits = spec.get("round", 2)
        value = int(round(value)) if ndigits == 0 else round(value, ndigits)
        return value, provenance
    return None, {"source": "population_prior", "label": POPULATION_PRIOR_LABEL, "n": n}


def apply_character_targets(config, baselines):
    """Overlay personal-variance targets onto a character config (#1412).

    Returns a DEEP COPY — the input is never mutated (the engine caches the S3
    config in-process; mutating it would leak the overlay into the cached copy
    and double-apply on warm starts). For every derivable component:
      - personal band cleared the floor → the target value is replaced;
      - below floor → the authored value survives untouched;
    and either way the component gains `target_provenance` (method/window/n or
    the population-prior label), which the engine surfaces into component
    details and /api/character_config. Components with no derivation spec are
    untouched — no fabricated labels (ADR-104). Deterministic: identical
    (config, baselines) always yields an identical effective config, which is
    what lets #1373 receipt config-hashes agree across write and replay.
    """
    if not config:
        return config
    import copy

    cfg = copy.deepcopy(config)
    for metric, spec in CHARACTER_TARGET_SPECS.items():
        component = (cfg.get("pillars") or {}).get(spec["pillar"], {}).get("components", {}).get(spec["component"])
        if not isinstance(component, dict):
            continue  # component absent from this config — nothing to personalize
        value, provenance = derive_component_target(metric, baselines)
        if value is not None:
            component[spec["key"]] = value
        provenance["metric"] = metric
        component["target_provenance"] = provenance
    return cfg


def effective_character_config(config, table, user_prefix):
    """The ONE way every consumer builds the config the engine actually runs
    under (#1412): nightly compute, qa_smoke receipt replay, and the site-api
    receipt verify all call THIS, so the #1373 config hash agrees across write
    and replay — a baselines refresh shows as labeled config_drift, never a
    permanent unlabeled mismatch. Never raises; any failure falls back to the
    authored config with population-prior labels (load_baselines returns {}).
    """
    try:
        baselines = load_baselines(table, user_prefix)
    except Exception:
        baselines = {}
    return apply_character_targets(config, baselines)
