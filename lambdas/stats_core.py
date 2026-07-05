"""
stats_core.py — the single sanctioned statistics module (ADR-105, story #529).

One tested, stdlib-only home for the statistics the platform previously carried in
scattered copies (three pearson_r's with three different min-n, two erf-based
p-values, no CI machinery anywhere). Everything here is pure and deterministic:
no I/O, no numpy/scipy, and the bootstrap uses a fixed default seed so the same
data always yields the same interval (compute outputs must be reproducible
run-to-run).

The autocorrelation stance (ADR-105 rule 1): daily physiological series are not
i.i.d. — recovery, HRV, weight all carry day-to-day memory, so raw n overstates
the evidence. `effective_sample_size` applies the AR(1) first-order (Bartlett)
correction — for two series the Pyper & Peterman (1998) form
n_eff = n * (1 - r1x*r1y) / (1 + r1x*r1y) — and significance should be computed
on n_eff, not n. Negative-autocorrelation "bonuses" (n_eff > n) are clamped to n:
we only ever correct toward conservatism.

Adding a parallel implementation of anything in this module requires an ADR.
"""

import math
import random

# Two-sided critical z per supported confidence level. A lookup, not an inverse-CDF,
# because these four are the only levels any surface uses (0.80 is the forecast
# engine's interval — chosen so the coverage question "did the 80% interval cover
# 80% of outcomes?" is answerable with ~weeks of resolutions, not months).
_Z_CRIT = {0.80: 1.2816, 0.90: 1.6449, 0.95: 1.9600, 0.99: 2.5758}

# Bootstrap defaults. 1000 replicates keeps a 23-pair weekly sweep under a second;
# the fixed seed makes intervals reproducible (ADR-105: deterministic before narrative).
DEFAULT_N_BOOT = 1000
DEFAULT_SEED = 1337
_MIN_VALID_REPLICATES = 100


def clean_pairs(xs, ys):
    """Drop pairs where either side is None/non-numeric; returns (xs, ys) as float lists."""
    out_x, out_y = [], []
    for x, y in zip(xs, ys):
        if x is None or y is None:
            continue
        try:
            fx, fy = float(x), float(y)
        except (TypeError, ValueError):
            continue
        if math.isnan(fx) or math.isnan(fy):
            continue
        out_x.append(fx)
        out_y.append(fy)
    return out_x, out_y


def clean_series(xs):
    """Drop None/non-numeric entries, preserving order."""
    out = []
    for x in xs:
        if x is None:
            continue
        try:
            fx = float(x)
        except (TypeError, ValueError):
            continue
        if math.isnan(fx):
            continue
        out.append(fx)
    return out


def pearson_r(xs, ys, min_n=3):
    """Pearson correlation over paired lists (None pairs dropped).

    Returns an unrounded float clamped to [-1, 1], or None when n < min_n or
    either side has zero variance. Callers own presentation rounding.
    """
    xs2, ys2 = clean_pairs(xs, ys)
    n = len(xs2)
    if n < max(min_n, 2):
        return None
    mx = sum(xs2) / n
    my = sum(ys2) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs2, ys2))
    denom = math.sqrt(sum((x - mx) ** 2 for x in xs2) * sum((y - my) ** 2 for y in ys2))
    if denom == 0:
        return None
    return max(-1.0, min(1.0, num / denom))


def lag1_autocorr(xs):
    """Lag-1 autocorrelation of a series (None entries dropped, order kept).

    Returns 0.0 when there are fewer than 3 points or no variance — i.e. "no
    detectable memory", which makes the effective-n correction a no-op.
    """
    v = clean_series(xs)
    n = len(v)
    if n < 3:
        return 0.0
    m = sum(v) / n
    denom = sum((x - m) ** 2 for x in v)
    if denom == 0:
        return 0.0
    num = sum((v[i] - m) * (v[i + 1] - m) for i in range(n - 1))
    return max(-1.0, min(1.0, num / denom))


def effective_sample_size(xs, ys=None):
    """Autocorrelation-corrected effective n (AR(1)/Bartlett first-order term).

    Single series: n_eff = n * (1 - r1) / (1 + r1).
    Paired series (for a correlation): the Pyper & Peterman (1998) AR(1) form,
    n_eff = n * (1 - r1x*r1y) / (1 + r1x*r1y).

    Clamped to [2, n]: positive autocorrelation shrinks the evidence; negative
    autocorrelation never inflates it past the raw count (conservative by design).
    Returns a float — downstream p-values accept fractional degrees of freedom.
    """
    if ys is not None:
        xs2, ys2 = clean_pairs(xs, ys)
        n = len(xs2)
        if n < 3:
            return float(n)
        rho = lag1_autocorr(xs2) * lag1_autocorr(ys2)
    else:
        v = clean_series(xs)
        n = len(v)
        if n < 3:
            return float(n)
        rho = lag1_autocorr(v)
    if rho >= 1.0:
        return 2.0
    n_eff = n * (1.0 - rho) / (1.0 + rho)
    return max(2.0, min(float(n), n_eff))


def pearson_p_value(r, n):
    """Two-tailed p-value for a Pearson r via the t-distribution, erf-based.

    The one sanctioned implementation (replaces the duplicate copies in
    weekly_correlation_compute_lambda and tools_training). Accepts fractional n
    so it composes with effective_sample_size. Normal approximation with the
    small-df shrink z = t * sqrt(df/(df+2)); accurate to ~3 decimals for df > 10
    and conservative below. Returns None when r is None, |r| >= 1, or n <= 2.
    """
    if r is None or n is None or n <= 2 or abs(r) >= 1.0:
        return None
    df = n - 2.0
    t_stat = r * math.sqrt(df) / math.sqrt(max(1e-10, 1.0 - r**2))
    if df >= 30:
        z = abs(t_stat)
    else:
        z = abs(t_stat) * math.sqrt(df / (df + 2.0))
    p = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(z / math.sqrt(2.0))))
    return round(max(0.0, min(1.0, p)), 4)


def fisher_ci(r, n, confidence=0.95):
    """Fisher z-transform CI for a correlation. Returns (lo, hi) or None.

    Accepts fractional n (pass effective_sample_size for autocorrelated series).
    """
    if r is None or n is None or n <= 3 or abs(r) >= 1.0:
        return None
    z_crit = _Z_CRIT.get(confidence)
    if z_crit is None:
        raise ValueError(f"unsupported confidence {confidence}; use one of {sorted(_Z_CRIT)}")
    z_r = math.atanh(r)
    se = 1.0 / math.sqrt(n - 3.0)
    return (math.tanh(z_r - z_crit * se), math.tanh(z_r + z_crit * se))


def _block_resample(n, block_len, rng):
    """Indices for one moving-block bootstrap replicate of length n."""
    idx = []
    max_start = n - block_len
    while len(idx) < n:
        start = rng.randint(0, max_start)
        idx.extend(range(start, start + block_len))
    return idx[:n]


def default_block_length(n):
    """Standard n^(1/3) block-length heuristic, floored at 2."""
    return max(2, round(n ** (1.0 / 3.0)))


def moving_block_bootstrap_ci(xs, ys=None, stat=None, n_boot=DEFAULT_N_BOOT, block_len=None, confidence=0.95, seed=DEFAULT_SEED):
    """Moving-block bootstrap percentile CI, preserving short-range autocorrelation.

    Paired mode (ys given): resamples index blocks jointly so the pairing survives;
    default stat is pearson_r. Single-series mode: default stat is the mean.
    A custom stat receives (xs, ys) in paired mode or (xs,) in single mode and may
    return None (replicate skipped, e.g. zero variance).

    Returns (lo, hi) unrounded, or None when n < 5 or too few replicates produce
    a valid statistic. Deterministic for a given (data, seed).
    """
    if confidence not in _Z_CRIT:
        raise ValueError(f"unsupported confidence {confidence}; use one of {sorted(_Z_CRIT)}")
    if ys is not None:
        xs2, ys2 = clean_pairs(xs, ys)
        n = len(xs2)
        stat_fn = stat or (lambda a, b: pearson_r(a, b, min_n=3))
    else:
        xs2 = clean_series(xs)
        ys2 = None
        n = len(xs2)
        stat_fn = stat or (lambda a: sum(a) / len(a) if a else None)
    if n < 5:
        return None
    b = block_len or default_block_length(n)
    b = max(2, min(b, n - 1))
    rng = random.Random(seed)
    values = []
    for _ in range(n_boot):
        idx = _block_resample(n, b, rng)
        rx = [xs2[i] for i in idx]
        if ys2 is not None:
            v = stat_fn(rx, [ys2[i] for i in idx])
        else:
            v = stat_fn(rx)
        if v is not None:
            values.append(v)
    if len(values) < _MIN_VALID_REPLICATES:
        return None
    values.sort()
    alpha = 1.0 - confidence
    lo_i = int(math.floor((alpha / 2.0) * len(values)))
    hi_i = min(len(values) - 1, int(math.ceil((1.0 - alpha / 2.0) * len(values))) - 1)
    return (values[lo_i], values[hi_i])


def bootstrap_mean_diff_ci(baseline, window, n_boot=DEFAULT_N_BOOT, block_len=None, confidence=0.95, seed=DEFAULT_SEED):
    """CI for mean(window) - mean(baseline), block-resampling each series independently.

    The hypothesis-engine primitive: "is this metric different in the test window
    than in baseline, and by how much?" Returns (lo, hi) unrounded, or None when
    either side has fewer than 5 points.
    """
    base = clean_series(baseline)
    win = clean_series(window)
    if len(base) < 5 or len(win) < 5:
        return None
    if confidence not in _Z_CRIT:
        raise ValueError(f"unsupported confidence {confidence}; use one of {sorted(_Z_CRIT)}")
    rng = random.Random(seed)
    nb, nw = len(base), len(win)
    bb = max(2, min(block_len or default_block_length(nb), nb - 1))
    bw = max(2, min(block_len or default_block_length(nw), nw - 1))
    diffs = []
    for _ in range(n_boot):
        rb = [base[i] for i in _block_resample(nb, bb, rng)]
        rw = [win[i] for i in _block_resample(nw, bw, rng)]
        diffs.append(sum(rw) / nw - sum(rb) / nb)
    diffs.sort()
    alpha = 1.0 - confidence
    lo_i = int(math.floor((alpha / 2.0) * len(diffs)))
    hi_i = min(len(diffs) - 1, int(math.ceil((1.0 - alpha / 2.0) * len(diffs))) - 1)
    return (diffs[lo_i], diffs[hi_i])


def cohens_d(baseline, window):
    """Cohen's d for mean(window) - mean(baseline), pooled-SD. None if degenerate."""
    a = clean_series(baseline)
    b = clean_series(window)
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return None
    ma, mb = sum(a) / na, sum(b) / nb
    va = sum((x - ma) ** 2 for x in a) / (na - 1)
    vb = sum((x - mb) ** 2 for x in b) / (nb - 1)
    pooled = math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2))
    if pooled == 0:
        return None
    return (mb - ma) / pooled


def _two_sided_z_p(z):
    """Two-sided normal-approximation p-value for a standardized statistic z.

    The same erf form the drift detector already uses inline — factored here so the
    changepoint scan and any future caller share one implementation. Underflows to
    0.0 for large |z| (a clean deterministic step), which is the honest answer.
    """
    return 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(z) / math.sqrt(2.0))))


def _single_changepoint(v, min_segment, min_effect, min_confidence):
    """Best single changepoint in a contiguous segment, or None.

    CUSUM-style max-statistic scan: for every admissible split k (both sides at
    least `min_segment` long) we standardize the difference of segment means by the
    Welch standard error computed on the AUTOCORRELATION-CORRECTED effective n of
    each side (ADR-105 rule 1 — raw n overstates the evidence on daily physiology).
    The split maximizing |z| is the candidate; equivalently the extremum of the
    standardized cumulative sum, hence "CUSUM".

    Honest confidence: |z| is maximized over ~(n - 2*min_segment + 1) candidate
    positions, so the raw p is optimistically small. We apply a Bonferroni
    correction over the number of candidates before reporting confidence — the
    honest guard against declaring a break in pure noise. A changepoint is returned
    only if it clears BOTH gates: Bonferroni confidence >= min_confidence AND a
    Cohen's d effect >= min_effect (magnitude floor, so a barely-significant sliver
    is never dressed up as a regime shift).

    Returns a dict (indices/means/magnitude/effect_size/confidence/n_before/n_after)
    with `index` = the first point of the AFTER segment, or None.
    """
    n = len(v)
    n_candidates = n - 2 * min_segment + 1
    if n_candidates < 1:
        return None

    best = None  # (abs_t, k, mA, mB, varA, varB, nA, nB, dfEff)
    for k in range(min_segment, n - min_segment + 1):
        a, b = v[:k], v[k:]
        na, nb = len(a), len(b)
        ma = sum(a) / na
        mb = sum(b) / nb
        var_a = sum((x - ma) ** 2 for x in a) / (na - 1) if na > 1 else 0.0
        var_b = sum((x - mb) ** 2 for x in b) / (nb - 1) if nb > 1 else 0.0
        na_eff = effective_sample_size(a)
        nb_eff = effective_sample_size(b)
        se = math.sqrt(var_a / na_eff + var_b / nb_eff)
        # Fractional Welch-style degrees of freedom on the effective n (edge splits
        # have few effective points → fat t-tails → the honest penalty against
        # calling a break off a small, autocorrelated sliver).
        df_eff = max(1.0, na_eff + nb_eff - 2.0)
        if se == 0.0:
            # Both sides perfectly flat. A genuine step (means differ) is a
            # certain changepoint; identical means is no signal at all.
            if ma == mb:
                continue
            abs_t = float("inf")
        else:
            abs_t = abs(mb - ma) / se
        if best is None or abs_t > best[0]:
            best = (abs_t, k, ma, mb, var_a, var_b, na, nb, df_eff)

    if best is None:
        return None

    abs_t, k, ma, mb, var_a, var_b, na, nb, df_eff = best
    if abs_t == float("inf"):
        p_raw = 0.0
    else:
        # t → normal via the small-df shrink z = t * sqrt(df/(df+2)) (matches
        # pearson_p_value): accurate for df > 10, conservative below.
        z = abs_t if df_eff >= 30 else abs_t * math.sqrt(df_eff / (df_eff + 2.0))
        p_raw = _two_sided_z_p(z)
    # Bonferroni over the candidate positions scanned — honest confidence.
    confidence = 1.0 - min(1.0, p_raw * n_candidates)

    pooled = math.sqrt(((na - 1) * var_a + (nb - 1) * var_b) / (na + nb - 2))
    if pooled == 0.0:
        effect = float("inf") if ma != mb else 0.0
    else:
        effect = (mb - ma) / pooled

    if confidence < min_confidence or abs(effect) < min_effect:
        return None

    return {
        "index": k,
        "before_mean": ma,
        "after_mean": mb,
        "magnitude": mb - ma,
        "effect_size": effect,
        "confidence": confidence,
        "n_before": na,
        "n_after": nb,
        "direction": "increase" if mb > ma else "decrease",
    }


def detect_changepoints(series, dates=None, min_segment=7, min_effect=1.0, min_confidence=0.99, max_changepoints=3):
    """Honest changepoint detection over a single time series (stdlib only, ADR-105).

    Finds abrupt LEVEL shifts — "the mean stepped from A to B around this date" —
    which fixed-window drift comparisons miss when the break falls between window
    boundaries. Algorithm: CUSUM-style max-statistic single-changepoint test (see
    `_single_changepoint`) applied recursively via binary segmentation — detect the
    strongest break, then recurse into the left and right sub-segments — up to
    `max_changepoints`. Each accepted break must clear a significance gate
    (Bonferroni-corrected over the scan) AND a magnitude gate, both conservative by
    default so flat or noisy series yield nothing rather than a spurious shift.

    Args:
        series: sequence of values (None/non-numeric entries dropped, order kept).
        dates: optional parallel sequence of ISO date strings; when given, each
            changepoint carries the approximate `date` at which the level changed.
            Dropped in lockstep with any non-numeric values so alignment survives.
        min_segment: minimum points on each side of a break (default 7).
        min_effect: minimum |Cohen's d| for a break to count (default 1.0 — a full
            pooled-SD level shift; conservative so only genuine regime changes fire).
        min_confidence: minimum Bonferroni-corrected confidence (default 0.99).
        max_changepoints: cap on breaks returned (default 3).

    Returns a dict:
        {
          "status": "ok" | "insufficient_data",
          "n": <clean point count>,
          "changepoints": [ {index, date?, before_mean, after_mean, magnitude,
                             effect_size, confidence, n_before, n_after, direction}, ... ],
          "reason": <present only when insufficient_data>,
        }
    Thin data (fewer than 2*min_segment clean points — no admissible split) returns
    status "insufficient_data" with an empty changepoint list: we never claim a shift
    we cannot test. All numbers unrounded; callers own presentation rounding.
    """
    # Keep dates aligned with values through the None/non-numeric drop.
    cleaned, cleaned_dates = [], []
    for i, x in enumerate(series):
        if x is None:
            continue
        try:
            fx = float(x)
        except (TypeError, ValueError):
            continue
        if math.isnan(fx):
            continue
        cleaned.append(fx)
        if dates is not None and i < len(dates):
            cleaned_dates.append(dates[i])
        else:
            cleaned_dates.append(None)

    n = len(cleaned)
    if n < 2 * min_segment:
        return {
            "status": "insufficient_data",
            "n": n,
            "changepoints": [],
            "reason": f"need >= {2 * min_segment} points to test a changepoint, have {n}",
        }

    changepoints = []
    # Binary segmentation: a work-list of (start, end) half-open sub-segments.
    segments = [(0, n)]
    while segments and len(changepoints) < max_changepoints:
        start, end = segments.pop(0)
        sub = cleaned[start:end]
        cp = _single_changepoint(sub, min_segment, min_effect, min_confidence)
        if cp is None:
            continue
        abs_index = start + cp["index"]
        record = dict(cp)
        record["index"] = abs_index
        if dates is not None:
            record["date"] = cleaned_dates[abs_index] if abs_index < len(cleaned_dates) else None
        changepoints.append(record)
        # Recurse into both sides (each must still admit a split to yield more).
        segments.append((start, abs_index))
        segments.append((abs_index, end))

    changepoints.sort(key=lambda c: c["index"])
    return {"status": "ok", "n": n, "changepoints": changepoints[:max_changepoints]}


def ewma_fit(xs, alpha=None):
    """Fit simple exponential smoothing to a series (None entries dropped, order kept).

    When alpha is None it is chosen by a deterministic grid search (0.05..0.95,
    step 0.05) minimizing one-step-ahead squared error, ties going to the
    smaller alpha — same data always yields the same fit. Returns
    (level, alpha, residuals) where residuals are the one-step-ahead errors
    under the chosen alpha, or None when fewer than 4 clean points.
    """
    v = clean_series(xs)
    if len(v) < 4:
        return None

    def _sse(a):
        level = v[0]
        total = 0.0
        for x in v[1:]:
            err = x - level
            total += err * err
            level += a * err
        return total

    if alpha is None:
        best = None
        for step in range(1, 20):  # 0.05 .. 0.95
            a = step / 20.0
            s = _sse(a)
            if best is None or s < best[1] - 1e-12:
                best = (a, s)
        alpha = best[0]
    level = v[0]
    residuals = []
    for x in v[1:]:
        err = x - level
        residuals.append(err)
        level += alpha * err
    return (level, alpha, residuals)


def ewma_forecast(xs, horizon=1, alpha=None, confidence=0.80, min_n=10):
    """Deterministic h-step-ahead expectation with a residual-based interval.

    Simple exponential smoothing: the point forecast at any horizon is the final
    smoothed level; interval width grows with horizon via the SES forecast-variance
    form sigma_h = sigma * sqrt(1 + (h-1) * alpha^2), where sigma is the sample SD
    of the one-step-ahead residuals. This is an EXPECTATION from observed patterns
    — never a causal claim (ADR-105 framing rule).

    Returns {"point", "lo", "hi", "alpha", "sigma", "n", "horizon", "confidence"}
    (unrounded — callers own presentation rounding), or None when fewer than
    min_n clean points or the residuals are degenerate.
    """
    z_crit = _Z_CRIT.get(confidence)
    if z_crit is None:
        raise ValueError(f"unsupported confidence {confidence}; use one of {sorted(_Z_CRIT)}")
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    v = clean_series(xs)
    n = len(v)
    if n < max(min_n, 4):
        return None
    fit = ewma_fit(v, alpha=alpha)
    if fit is None:
        return None
    level, a, residuals = fit
    m = len(residuals)
    if m < 3:
        return None
    mean_r = sum(residuals) / m
    var_r = sum((r - mean_r) ** 2 for r in residuals) / (m - 1)
    sigma = math.sqrt(var_r)
    if sigma == 0:
        return None
    sigma_h = sigma * math.sqrt(1.0 + (horizon - 1) * a * a)
    return {
        "point": level,
        "lo": level - z_crit * sigma_h,
        "hi": level + z_crit * sigma_h,
        "alpha": a,
        "sigma": sigma,
        "n": n,
        "horizon": horizon,
        "confidence": confidence,
    }


def ewma_series(daily_values_chrono, decay_days, seed=0.0):
    """Exponentially-weighted moving average with a time-constant of decay_days.

    The single sanctioned EWMA implementation (ADR-105 — one tested home for the
    platform's math). alpha = 1 - exp(-1/decay_days), applied over a chronologically-
    ordered [(label, value), ...] series. Returns [(label, ewa), ...] UNROUNDED —
    callers own presentation rounding.

    `seed` is the initial level (default 0.0, matching the original helper). A caller can
    warm-start it (e.g. the mean of the first days) to remove start-of-series bias when
    the leading window would otherwise anchor the average at zero — EWMA-ACWR uses this so
    a 28-day chronic average isn't dragged down by the seed over a short lookback.

    This mirrors the formula that lived in `mcp/helpers.py:compute_ewa` (the platform's
    original EWMA helper, which now delegates here); EWMA-ACWR (#543) re-uses it so
    acute/chronic training load is a smoothly-decaying weighted average rather than a
    flat rolling mean — recent days count more, and a single missed/huge day doesn't
    step-change the ratio the way a rolling window's drop-off does. Deterministic:
    same input always yields the same series (no I/O, no randomness).
    """
    if decay_days <= 0:
        raise ValueError("decay_days must be > 0")
    alpha = 1.0 - math.exp(-1.0 / decay_days)
    ewa = float(seed)
    out = []
    for label, val in daily_values_chrono:
        ewa = alpha * float(val) + (1.0 - alpha) * ewa
        out.append((label, ewa))
    return out


def bh_fdr(pvals):
    """Benjamini-Hochberg adjusted p-values, input order preserved.

    Accepts a list that may contain None (untestable entries pass through as
    None and don't count toward m). Adjusted values are monotone non-decreasing
    in the sorted order and capped at 1.0.
    """
    labeled = [(i, p) for i, p in enumerate(pvals) if p is not None]
    out = [None] * len(pvals)
    m = len(labeled)
    if m == 0:
        return out
    labeled.sort(key=lambda t: t[1])
    adj = [min(1.0, m / (k + 1) * p) for k, (_, p) in enumerate(labeled)]
    for k in range(m - 2, -1, -1):
        adj[k] = min(adj[k], adj[k + 1])
    for k, (i, _) in enumerate(labeled):
        out[i] = adj[k]
    return out


def _clean_forecast_pairs(pairs):
    """(probability in [0,1], outcome in {0,1}) pairs, dropping malformed entries."""
    out = []
    for pr in pairs or []:
        try:
            p, y = pr
            p = float(p)
            y = int(y)
        except (TypeError, ValueError):
            continue
        if math.isnan(p) or p < 0.0 or p > 1.0 or y not in (0, 1):
            continue
        out.append((p, y))
    return out


def brier_score(pairs):
    """Mean Brier score for probabilistic forecasts (#538/calibration scoreboard).

    pairs: iterable of (stated_probability in [0,1], realized_outcome in {0,1}).
    Returns mean((p - y)^2) — 0.0 is perfect, 0.25 is the always-say-50% baseline,
    1.0 is confidently-wrong-every-time. None when there are no valid pairs.
    Unrounded; the caller owns presentation rounding (matches the module contract).
    """
    clean = _clean_forecast_pairs(pairs)
    if not clean:
        return None
    return sum((p - y) ** 2 for p, y in clean) / len(clean)


def brier_skill_score(pairs):
    """Brier skill score vs. the base-rate climatology forecast. None if degenerate.

    1.0 perfect, 0.0 = no better than always predicting the observed base rate,
    negative = worse than the base rate. The honest "does stated confidence beat
    just guessing the average?" number.
    """
    clean = _clean_forecast_pairs(pairs)
    if len(clean) < 2:
        return None
    base_rate = sum(y for _, y in clean) / len(clean)
    bs = sum((p - y) ** 2 for p, y in clean) / len(clean)
    bs_ref = sum((base_rate - y) ** 2 for _, y in clean) / len(clean)
    if bs_ref == 0:
        return None  # every outcome identical — skill is undefined
    return 1.0 - bs / bs_ref


def reliability_bins(pairs, n_bins=10):
    """Calibration-curve bins: for each confidence band, stated vs. observed rate.

    pairs: (probability in [0,1], outcome in {0,1}). Splits [0,1] into n_bins equal
    bands (the top edge is inclusive on the last bin) and, for the non-empty ones,
    returns dicts {lo, hi, n, mean_confidence, observed_rate}. mean_confidence is the
    average stated probability in the bin; observed_rate is the fraction that came
    true. A well-calibrated forecaster has mean_confidence ≈ observed_rate in every
    bin. Empty list when no valid pairs. Unrounded.
    """
    clean = _clean_forecast_pairs(pairs)
    if not clean or n_bins < 1:
        return []
    buckets = [[] for _ in range(n_bins)]
    for p, y in clean:
        idx = min(n_bins - 1, int(p * n_bins))  # p == 1.0 lands in the last bin
        buckets[idx].append((p, y))
    out = []
    for i, b in enumerate(buckets):
        if not b:
            continue
        n = len(b)
        out.append(
            {
                "lo": i / n_bins,
                "hi": (i + 1) / n_bins,
                "n": n,
                "mean_confidence": sum(p for p, _ in b) / n,
                "observed_rate": sum(y for _, y in b) / n,
            }
        )
    return out
