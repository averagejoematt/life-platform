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
