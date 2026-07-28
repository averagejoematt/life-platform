"""lambdas/bsts_lite.py — BSTS-lite synthetic-control counterfactual (#1410, epic #1365).

Every concluded intervention must answer "compared to WHAT?" — this module builds
the ghost: what the criterion metric would plausibly have done had the experiment
never started, so the effect is observed − counterfactual instead of post − pre.

The model (a deliberately small subset of BSTS, pure Python, zero new deps):

    y_t = z_t + mu_t + eps_t          z_t = beta·[1, x_t]   (OLS on the pre-period)
    mu_t = mu_{t-1} + eta_t           eps ~ N(0, sigma_eps²), eta ~ N(0, sigma_eta²)

  * The regression component carries the control series (metrics the intervention
    should NOT move); the local level absorbs slow drift the controls don't explain.
  * Variances are estimated on the pre-period by maximizing the innovations
    (Kalman) likelihood over a FIXED grid of signal-to-noise ratios
    q = sigma_eta²/sigma_eps² — deterministic: same data, same ghost, always.
  * The post-period forecast freezes the level at its last filtered state and
    lets its variance grow (P_T + t·sigma_eta²) — the honestly-WIDENING interval:
    the further from the intervention start, the less the ghost claims to know.
  * Effect = mean(observed − ghost) over the post-period, with a CI that uses the
    full error covariance (the shared level error correlates post days — treating
    them independent would fake precision). The OLS prediction covariance is
    included exactly; Cov(eta, OLS) is zero by construction.

Honesty gates (ADR-104/105):
  * Pre-period one-step-ahead MAPE above the frozen gate ⇒ NO ghost — a model
    that couldn't track the pre-period has no business narrating the post-period.
  * Days where |y| is too small for a meaningful percentage error are skipped in
    MAPE; if too many are skipped the gate reports itself unevaluable and the
    ghost is withheld (never a gate quietly passed on 3 usable days).
  * Everything reported carries n_pre and the fitted spec; nothing is random.

Pure module: no I/O, no clock, no imports beyond math. Callers fetch series.
"""

import math

# Signal-to-noise grid for the local level (0 = static level). Fixed and small on
# purpose: an ML search over a continuum invites spec instability run-to-run;
# a coarse deterministic grid trades a little fit for total reproducibility.
Q_GRID = (0.0, 0.001, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0)

# Diffuse-ish prior scale for the initial level variance (× pre-period variance).
_DIFFUSE = 1e6

# |y| below this is uselessly small as a MAPE denominator (percentage of ~zero).
_MAPE_DENOM_FLOOR = 1e-9
# If more than this fraction of pre-period days are skipped for tiny |y|, the
# MAPE gate is unevaluable and the ghost is withheld.
_MAPE_MAX_SKIPPED_FRAC = 0.2

Z95 = 1.959963984540054


# ── tiny dense linear algebra (k ≤ a handful of controls) ────────────────────


def _solve(a, b):
    """Solve A x = b (Gaussian elimination, partial pivoting). Returns None when
    A is numerically singular (collinear controls)."""
    n = len(a)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-10:
            return None
        m[col], m[piv] = m[piv], m[col]
        for r in range(n):
            if r != col and m[r][col] != 0.0:
                f = m[r][col] / m[col][col]
                for c in range(col, n + 1):
                    m[r][c] -= f * m[col][c]
    return [m[i][n] / m[i][i] for i in range(n)]


def _inv(a):
    """Inverse via column-wise solves. None when singular."""
    n = len(a)
    cols = []
    for j in range(n):
        e = [1.0 if i == j else 0.0 for i in range(n)]
        x = _solve(a, e)
        if x is None:
            return None
        cols.append(x)
    return [[cols[j][i] for j in range(n)] for i in range(n)]


def _ols(y, X):
    """OLS of y on X (rows = observations, first column must be the intercept).
    Returns (beta, xtx_inv, s2) or None on collinearity / df <= 0."""
    n, k = len(X), len(X[0])
    if n <= k:
        return None
    xtx = [[sum(X[r][i] * X[r][j] for r in range(n)) for j in range(k)] for i in range(k)]
    xty = [sum(X[r][i] * y[r] for r in range(n)) for i in range(k)]
    beta = _solve(xtx, xty)
    if beta is None:
        return None
    xtx_inv = _inv(xtx)
    if xtx_inv is None:
        return None
    resid = [y[r] - sum(beta[i] * X[r][i] for i in range(k)) for r in range(n)]
    s2 = sum(e * e for e in resid) / (n - k)
    return beta, xtx_inv, s2


# ── local-level Kalman ───────────────────────────────────────────────────────


def _kalman(r, q):
    """Filter the residual series with sigma_eps²=1, sigma_eta²=q (scale-free).
    Returns (m_T, P_T, innovations v[1:], scaled innovation variances F[1:],
    concentrated sigma_eps² estimate, loglik). The first observation initializes
    the diffuse level and is excluded from the likelihood."""
    m, p = r[0], _DIFFUSE
    vs, fs = [], []
    for t in range(1, len(r)):
        p_pred = p + q
        f = p_pred + 1.0
        v = r[t] - m
        vs.append(v)
        fs.append(f)
        k = p_pred / f
        m = m + k * v
        p = p_pred * (1.0 - k)
    n = len(vs)
    if n == 0:
        return m, p, vs, fs, 0.0, float("-inf")
    s2 = sum(v * v / f for v, f in zip(vs, fs)) / n
    if s2 <= 0:
        s2 = 1e-12
    loglik = -0.5 * (n * math.log(2 * math.pi * s2) + sum(math.log(f) for f in fs) + n)
    return m, p, vs, fs, s2, loglik


def fit_counterfactual(pre_y, post_len, pre_x=None, post_x=None):
    """Fit on the pre-period, forecast `post_len` counterfactual points.

    pre_x / post_x: optional list-of-rows of control values (no intercept column
    — added here). Returns None only on structural failure (collinear controls,
    post_x length mismatch); thin data and bad fit are reported, not raised —
    the CALLER applies the MAPE gate so the refusal is visible, never silent.
    """
    n = len(pre_y)
    if n < 3 or post_len <= 0:
        return None
    if pre_x is not None:
        if post_x is None or len(post_x) != post_len or len(pre_x) != n:
            return None
        X = [[1.0] + [float(v) for v in row] for row in pre_x]
        fit = _ols([float(v) for v in pre_y], X)
        if fit is None:
            return None
        beta, xtx_inv, s2_reg = fit
        z_pre = [sum(beta[i] * X[r][i] for i in range(len(beta))) for r in range(n)]
        Xp = [[1.0] + [float(v) for v in row] for row in post_x]
        z_post = [sum(beta[i] * Xp[r][i] for i in range(len(beta))) for r in range(post_len)]

        def reg_cov(i, j):
            xi, xj = Xp[i], Xp[j]
            k = len(beta)
            return s2_reg * sum(xi[a] * xtx_inv[a][b] * xj[b] for a in range(k) for b in range(k))

    else:
        z_pre = [0.0] * n
        z_post = [0.0] * post_len

        def reg_cov(i, j):
            return 0.0

    r = [float(y) - z for y, z in zip(pre_y, z_pre)]

    best = None
    for q in Q_GRID:
        m_T, p_T, vs, fs, s2, ll = _kalman(r, q)
        if best is None or ll > best[0]:
            best = (ll, q, m_T, p_T, vs, fs, s2)
    _ll, q, m_T, p_T, vs, fs, s2_eps = best
    sigma_eps2 = s2_eps
    sigma_eta2 = q * s2_eps
    p_T_scaled = p_T * s2_eps  # filter ran scale-free; rescale the state variance

    # One-step-ahead pre-period predictions on the y scale (t >= 1): the level
    # prediction is the previous filtered mean — rebuild by re-filtering at the
    # chosen q and recording predictions before each update.
    m, p = r[0], _DIFFUSE
    abs_pct, skipped, used = [], 0, 0
    for t in range(1, n):
        y_hat = z_pre[t] + m
        denom = abs(float(pre_y[t]))
        if denom < _MAPE_DENOM_FLOOR:
            skipped += 1
        else:
            abs_pct.append(abs(float(pre_y[t]) - y_hat) / denom)
            used += 1
        p_pred = p + q
        f = p_pred + 1.0
        k = p_pred / f
        m = m + k * (r[t] - m)
        p = p_pred * (1.0 - k)

    if used == 0 or skipped / max(1, used + skipped) > _MAPE_MAX_SKIPPED_FRAC:
        mape_pct = None  # unevaluable — caller must withhold the ghost
    else:
        mape_pct = 100.0 * sum(abs_pct) / used

    ghost = [z_post[t] + m_T for t in range(post_len)]
    point_var = [max(0.0, p_T_scaled + (t + 1) * sigma_eta2 + sigma_eps2 + reg_cov(t, t)) for t in range(post_len)]

    def effect_cov(i, j):
        """Cov of forecast errors e_i, e_j (shared frozen-level error + the
        random-walk accumulation + observation noise + OLS prediction cov)."""
        c = p_T_scaled + min(i + 1, j + 1) * sigma_eta2 + reg_cov(i, j)
        if i == j:
            c += sigma_eps2
        return c

    return {
        "ghost": ghost,
        "point_var": point_var,
        "effect_cov": effect_cov,
        "mape_pct": round(mape_pct, 2) if mape_pct is not None else None,
        "mape_n_used": used,
        "mape_n_skipped": skipped,
        "n_pre": n,
        "q": q,
        "sigma_eps2": sigma_eps2,
        "sigma_eta2": sigma_eta2,
        "n_controls": 0 if pre_x is None else len(pre_x[0]),
    }


def effect_summary(observed_post, fit):
    """Mean effect (observed − ghost) over the post-period with its 95% CI from
    the FULL forecast-error covariance. observed_post must align 1:1 with the
    fitted ghost; None entries (missing days) are excluded from the mean and
    from the covariance sum — the honest n is reported."""
    ghost = fit["ghost"]
    idx = [i for i, v in enumerate(observed_post) if v is not None]
    if not idx:
        return None
    diffs = [float(observed_post[i]) - ghost[i] for i in idx]
    h = len(idx)
    mean_effect = sum(diffs) / h
    cov = fit["effect_cov"]
    var_mean = sum(cov(i, j) for i in idx for j in idx) / (h * h)
    se = math.sqrt(max(0.0, var_mean))
    return {
        "effect_mean": round(mean_effect, 3),
        "ci95_low": round(mean_effect - Z95 * se, 3),
        "ci95_high": round(mean_effect + Z95 * se, 3),
        "n_post_used": h,
    }
