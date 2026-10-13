"""tests/test_prop_stats_core.py — property-based (Hypothesis) proofs of the one sanctioned
statistics module, lambdas/common/stats_core.py (#4892; craft review 2026-10-13 finding 18).

stats_core is pure by its own docstring ("no I/O, no numpy/scipy ... the same data always
yields the same interval"), and it is the calculator behind every served correlation,
interval, p-value and forecast. tests/test_stats_core.py pins it against published values
at chosen points; this file proves the invariants over input SPACES. Every property below
is one the function's docstring (or the defining construction it names) promises — none
is invented:

  * clean_pairs / clean_series: idempotent, aligned, never emit None/NaN;
  * pearson_r: None or within [-1, 1] ("clamped to [-1, 1]"), symmetric in its two
    arguments, and independent of the ORDER the pairs arrive in;
  * lag1_autocorr: within [-1, 1]; 0.0 below 3 points ("no detectable memory");
  * effective_sample_size: clamped to [2, n] ("negative autocorrelation never inflates it
    past the raw count"), single and paired;
  * pearson_p_value: within [0, 1], two-tailed (p(r) == p(-r)), non-increasing in |r| and
    in n;
  * fisher_ci: contains r, nests by confidence, narrows with n, mirrors under r -> -r;
  * correlation_evidence: never raises on garbage ("tolerant of None/garbage inputs"),
    score in [0, 1], n_eff never above n ("effective n can only shrink the evidence"),
    FDR survival can only raise the score;
  * wilson_interval: within [0, 1], contains k/n, never zero-width (the Wald collapse it
    exists to avoid), nests by confidence, mirrors under k -> n - k;
  * exact_sign_test_p: within (0, 1], symmetric in (b, c), 1.0 when balanced;
  * the block bootstraps: deterministic for (data, seed), lo <= hi, a mean's interval
    inside the data's range, a mean-difference interval shifts exactly with the window;
  * start_point_randomization_test: p in [min_p, 1], candidate bookkeeping adds up,
    independent of candidate ORDER;
  * cohens_d: antisymmetric in (baseline, window);
  * detect_changepoints: every returned break clears both gates, is admissible and sorted,
    and never exceeds max_changepoints;
  * the EWMA family: level/series stay inside the convex hull of the data, the forecast
    interval contains its point and WIDENS with horizon;
  * bh_fdr: order-preserving, None pass-through, adjusted >= raw, capped at 1, monotone
    non-decreasing in sorted-p order, and permutation-equivariant;
  * Brier / reliability: bounds, skill <= 1, the bins account for every valid pair.

MUTATION CONTROL (acceptance box 3). `test_mutation_control_*` below rebuild stats_core
from its own source with ONE deliberately broken branch, point a named property at the
mutant with a derandomized search, and require the property to FAIL. A property suite that
cannot see a broken calculator is decoration; these are the proof that this one can.

Time budget: max_examples is modest (40-150), deadline=None, database=None (no in-tree
.hypothesis writes), and float comparisons use math.isclose — never ==.
"""

import math
import os
import sys
import types

from hypothesis import example, given, settings, strategies as st

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from common import stats_core  # noqa: E402

_STATS_CORE_PATH = os.path.join(_REPO, "lambdas", "common", "stats_core.py")

# Values drawn as bounded integers then scaled: realistic magnitudes for daily physiology,
# and no catastrophic-cancellation float pathologies dressed up as calculator defects.
_val = st.integers(min_value=-500, max_value=500).map(lambda i: i / 4.0)
_series = st.lists(_val, min_size=0, max_size=30)
_messy = st.lists(st.one_of(_val, st.none(), st.just(float("nan")), st.text(max_size=3)), max_size=25)
_conf = st.sampled_from(sorted(stats_core._Z_CRIT))
_r = st.floats(min_value=-0.999, max_value=0.999, allow_nan=False)
_n = st.floats(min_value=3.5, max_value=400.0, allow_nan=False)
_p = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
_EPS = 1e-9

_FAST = settings(max_examples=150, deadline=None, database=None)
_MED = settings(max_examples=80, deadline=None, database=None)
_SLOW = settings(max_examples=40, deadline=None, database=None)


def _close(a, b, tol=1e-9):
    return math.isclose(a, b, rel_tol=tol, abs_tol=tol)


@st.composite
def _pairs(draw, min_size=0, max_size=30):
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    return draw(st.lists(_val, min_size=n, max_size=n)), draw(st.lists(_val, min_size=n, max_size=n))


# ── cleaning ──────────────────────────────────────────────────────────────────


@given(xs=_messy)
@_FAST
def test_clean_series_is_idempotent_and_clean(xs):
    once = stats_core.clean_series(xs)
    assert stats_core.clean_series(once) == once
    assert all(isinstance(v, float) and not math.isnan(v) for v in once)


@given(xs=_messy, ys=_messy)
@_FAST
def test_clean_pairs_is_idempotent_and_aligned(xs, ys):
    cx, cy = stats_core.clean_pairs(xs, ys)
    assert len(cx) == len(cy) <= min(len(xs), len(ys))
    assert stats_core.clean_pairs(cx, cy) == (cx, cy)
    assert not any(math.isnan(v) for v in cx + cy)


# ── correlation ───────────────────────────────────────────────────────────────


@given(xy=_pairs())
@_FAST
def test_pearson_r_bounded_and_symmetric(xy):
    xs, ys = xy
    r = stats_core.pearson_r(xs, ys)
    r_swapped = stats_core.pearson_r(ys, xs)
    assert (r is None) == (r_swapped is None)
    if r is not None:
        assert -1.0 <= r <= 1.0
        assert _close(r, r_swapped)


@given(xy=_pairs(min_size=3), data=st.data())
@_FAST
def test_pearson_r_independent_of_pair_order(xy, data):
    xs, ys = xy
    perm = data.draw(st.permutations(range(len(xs))))
    r = stats_core.pearson_r(xs, ys)
    r_perm = stats_core.pearson_r([xs[i] for i in perm], [ys[i] for i in perm])
    assert (r is None) == (r_perm is None)
    if r is not None:
        assert _close(r, r_perm)


@given(xs=_series)
@_FAST
def test_lag1_autocorr_bounded_and_zero_below_three(xs):
    r1 = stats_core.lag1_autocorr(xs)
    assert -1.0 <= r1 <= 1.0
    if len(xs) < 3:
        assert r1 == 0.0


@given(xs=_series)
@_FAST
def test_effective_sample_size_clamped_to_two_and_n_single(xs):
    n = len(xs)
    ne = stats_core.effective_sample_size(xs)
    if n < 3:
        assert ne == float(n)
    else:
        assert 2.0 <= ne <= n


@given(xy=_pairs())
@_FAST
def test_effective_sample_size_clamped_to_two_and_n_paired(xy):
    xs, ys = xy
    n = len(xs)
    ne = stats_core.effective_sample_size(xs, ys)
    if n < 3:
        assert ne == float(n)
    else:
        assert 2.0 <= ne <= n


@given(r=_r, n=_n)
@_FAST
def test_pearson_p_value_bounded_and_two_tailed(r, n):
    p = stats_core.pearson_p_value(r, n)
    assert p is not None and 0.0 <= p <= 1.0
    assert p == stats_core.pearson_p_value(-r, n)


@given(r1=_r, r2=_r, n=_n)
@_FAST
def test_pearson_p_value_non_increasing_in_abs_r(r1, r2, n):
    lo, hi = sorted((abs(r1), abs(r2)))
    assert stats_core.pearson_p_value(hi, n) <= stats_core.pearson_p_value(lo, n)


@given(r=_r, n1=_n, n2=_n)
@_FAST
def test_pearson_p_value_non_increasing_in_n(r, n1, n2):
    small, big = sorted((n1, n2))
    assert stats_core.pearson_p_value(r, big) <= stats_core.pearson_p_value(r, small)


@given(r=_r, n=_n, conf=_conf)
@_FAST
def test_fisher_ci_contains_r_and_mirrors(r, n, conf):
    lo, hi = stats_core.fisher_ci(r, n, conf)
    assert -1.0 <= lo <= r + _EPS and r - _EPS <= hi <= 1.0
    mlo, mhi = stats_core.fisher_ci(-r, n, conf)
    assert _close(mlo, -hi) and _close(mhi, -lo)


@given(r=_r, n=_n, c1=_conf, c2=_conf)
@_FAST
def test_fisher_ci_nests_by_confidence(r, n, c1, c2):
    narrow, wide = sorted((c1, c2))
    nlo, nhi = stats_core.fisher_ci(r, n, narrow)
    wlo, whi = stats_core.fisher_ci(r, n, wide)
    assert wlo <= nlo + _EPS and nhi <= whi + _EPS


@given(r=_r, n1=_n, n2=_n)
@_FAST
def test_fisher_ci_narrows_with_n(r, n1, n2):
    small, big = sorted((n1, n2))
    slo, shi = stats_core.fisher_ci(r, small)
    blo, bhi = stats_core.fisher_ci(r, big)
    assert (bhi - blo) <= (shi - slo) + _EPS


_garbage = st.one_of(st.none(), st.text(max_size=4), st.floats(allow_nan=True, allow_infinity=True), st.integers(-50, 500))


@given(r=_garbage, n=_garbage, n_eff=_garbage, fdr=st.one_of(st.none(), st.booleans(), st.text(max_size=2)))
@example(r=0.5, n=float("inf"), n_eff=None, fdr=None)
@example(r=0.5, n=float("-inf"), n_eff=None, fdr=None)
@example(r=0.5, n=float("inf"), n_eff=float("inf"), fdr=True)
@_FAST
def test_correlation_evidence_total_on_garbage_and_bounded(r, n, n_eff, fdr):
    # The docstring promises no raise on garbage (it sits on a public serving path).
    # Hypothesis found int(float('inf')) raising OverflowError here; fixed in #4892.
    out = stats_core.correlation_evidence(r, n, n_eff=n_eff, fdr_significant=fdr)
    assert 0.0 <= out["score"] <= 1.0
    assert out["n_eff"] <= out["n"] + 0.05  # n_eff is rounded to 1 dp
    assert out["level"] in ("high", "medium", "low")
    assert out["fdr_significant"] in (True, False, None)


def test_correlation_evidence_infinite_n_is_zero_not_overflow():
    # The deterministic pin for #4892's product fix: int(float('inf')) raised OverflowError
    # out of correlation_evidence before the fix. The property above draws inf only
    # sometimes, so this plain test is what fails on EVERY run if the fix is reverted.
    for bad_n in (float("inf"), float("-inf")):
        out = stats_core.correlation_evidence(0.5, bad_n)
        assert out["n"] == 0 and out["n_eff"] == 0.0
        assert out["level"] == "low"


@given(r=_r, n=st.integers(0, 300), frac=st.floats(min_value=0.0, max_value=1.0))
@_FAST
def test_correlation_evidence_fdr_survival_never_lowers_score(r, n, frac):
    ne = n * frac
    survived = stats_core.correlation_evidence(r, n, n_eff=ne, fdr_significant=True)
    failed = stats_core.correlation_evidence(r, n, n_eff=ne, fdr_significant=False)
    assert survived["score"] >= failed["score"]
    assert stats_core.correlation_evidence(r, n, n_eff=ne, fdr_significant=True) == survived


# ── proportions and paired-forecaster tests ────────────────────────────────────


@st.composite
def _k_n(draw):
    n = draw(st.integers(min_value=1, max_value=500))
    return draw(st.integers(min_value=0, max_value=n)), n


@given(kn=_k_n(), conf=_conf)
@_FAST
def test_wilson_interval_bounded_contains_phat_never_collapses(kn, conf):
    k, n = kn
    lo, hi = stats_core.wilson_interval(k, n, conf)
    assert 0.0 <= lo <= k / n + _EPS and k / n - _EPS <= hi <= 1.0
    assert hi - lo > 0.0
    mlo, mhi = stats_core.wilson_interval(n - k, n, conf)
    assert _close(mlo, 1.0 - hi) and _close(mhi, 1.0 - lo)


@given(kn=_k_n(), c1=_conf, c2=_conf)
@_FAST
def test_wilson_interval_nests_by_confidence(kn, c1, c2):
    k, n = kn
    narrow, wide = sorted((c1, c2))
    nlo, nhi = stats_core.wilson_interval(k, n, narrow)
    wlo, whi = stats_core.wilson_interval(k, n, wide)
    assert wlo <= nlo + _EPS and nhi <= whi + _EPS


@given(n=st.integers(-5, 0), k=st.integers(-5, 5))
@_FAST
def test_wilson_interval_none_outside_domain(n, k):
    assert stats_core.wilson_interval(k, n) is None
    assert stats_core.wilson_interval(-1, 10) is None and stats_core.wilson_interval(11, 10) is None


@given(b=st.integers(0, 150), c=st.integers(0, 150))
@_FAST
def test_exact_sign_test_bounded_symmetric_balanced_is_one(b, c):
    p = stats_core.exact_sign_test_p(b, c)
    assert 0.0 < p <= 1.0
    assert p == stats_core.exact_sign_test_p(c, b)
    if b == c:
        assert p == 1.0


# ── resampling ────────────────────────────────────────────────────────────────

_boot_series = st.lists(_val, min_size=5, max_size=25)


@given(xs=_boot_series, seed=st.integers(0, 10_000))
@_SLOW
def test_block_bootstrap_mean_ci_deterministic_and_inside_data_range(xs, seed):
    ci = stats_core.moving_block_bootstrap_ci(xs, n_boot=200, seed=seed)
    assert ci == stats_core.moving_block_bootstrap_ci(xs, n_boot=200, seed=seed)
    lo, hi = ci
    assert min(xs) - _EPS <= lo <= hi <= max(xs) + _EPS


@given(base=_boot_series, win=_boot_series, shift=_val, seed=st.integers(0, 10_000))
@_SLOW
def test_bootstrap_mean_diff_ci_ordered_and_shifts_with_window(base, win, shift, seed):
    ci = stats_core.bootstrap_mean_diff_ci(base, win, n_boot=200, seed=seed)
    assert ci == stats_core.bootstrap_mean_diff_ci(base, win, n_boot=200, seed=seed)
    lo, hi = ci
    assert lo <= hi
    assert min(win) - max(base) - _EPS <= lo and hi <= max(win) - min(base) + _EPS
    slo, shi = stats_core.bootstrap_mean_diff_ci(base, [w + shift for w in win], n_boot=200, seed=seed)
    assert _close(slo, lo + shift, 1e-7) and _close(shi, hi + shift, 1e-7)


# ── randomization test, effect size, changepoints ─────────────────────────────


@st.composite
def _sced(draw):
    # Biased so the observed split is usable on most draws (>= 2 non-None points per arm
    # even after the largest washout): an unbiased draw returned None on 51-78 of 80
    # examples, so the bookkeeping assertions examined almost nothing.
    values = draw(st.lists(_val, min_size=6, max_size=30))
    gaps = draw(st.lists(st.integers(0, len(values) - 1), max_size=len(values) // 5, unique=True))
    for i in gaps:
        values[i] = None
    usable = [
        k
        for k in range(len(values) + 1)
        if sum(v is not None for v in values[:k]) >= 2 and sum(v is not None for v in values[k + 2 :]) >= 2
    ]
    pool = usable or list(range(len(values) + 1))
    actual = draw(st.sampled_from(pool))
    # One more usable split guarantees n_used >= 2; the rest may be unusable (bookkeeping).
    rival = [k for k in pool if k != actual]
    others = [draw(st.sampled_from(rival))] if rival else []
    others += draw(st.lists(st.integers(0, len(values)), max_size=8))
    cands = list(dict.fromkeys([actual] + others))
    return values, draw(st.permutations(cands)), actual


@given(case=_sced(), direction=st.sampled_from(["higher", "lower"]), washout=st.integers(0, 2), data=st.data())
@_MED
def test_start_point_randomization_bounds_bookkeeping_and_order_independence(case, direction, washout, data):
    values, cands, actual = case
    out = stats_core.start_point_randomization_test(values, cands, actual, direction=direction, washout=washout)
    if out is None:
        return
    assert out["min_p"] - 1e-4 <= out["p_value"] <= 1.0
    assert out["n_used"] + out["n_excluded"] == out["n_candidates"] == len(cands)
    assert out["n_used"] >= 2
    shuffled = data.draw(st.permutations(cands))
    assert stats_core.start_point_randomization_test(values, shuffled, actual, direction=direction, washout=washout) == out


@given(a=st.lists(_val, max_size=20), b=st.lists(_val, max_size=20))
@_FAST
def test_cohens_d_antisymmetric(a, b):
    d = stats_core.cohens_d(a, b)
    d_rev = stats_core.cohens_d(b, a)
    assert (d is None) == (d_rev is None)
    if d is not None:
        assert _close(d, -d_rev)


@st.composite
def _cp_case(draw):
    # Length drawn from min_segment so most series admit a split: an unbiased list drew
    # fewer than 2*min_segment points on ~39 of 40 examples and the gate assertions below
    # examined nothing. A few short series stay in so the insufficient branch is covered.
    min_segment = draw(st.integers(2, 7))
    lo = draw(st.sampled_from([0, 2 * min_segment, 2 * min_segment, 2 * min_segment, 2 * min_segment]))
    xs = draw(st.lists(_val, min_size=lo, max_size=40))
    return xs, min_segment


@given(case=_cp_case(), max_cp=st.integers(1, 3), level_shift=st.integers(0, 400))
@example(case=([0.0, 1.0] * 7 + [100.0, 101.0] * 7, 3), max_cp=1, level_shift=0)
@_SLOW
def test_detect_changepoints_every_break_clears_both_gates(case, max_cp, level_shift):
    xs, min_segment = case
    # Half the drawn series get a planted step so the accept branch is exercised too.
    half = len(xs) // 2
    series = xs[:half] + [x + level_shift for x in xs[half:]]
    out = stats_core.detect_changepoints(series, min_segment=min_segment, max_changepoints=max_cp)
    n = len(series)
    assert out["n"] == n
    if n < 2 * min_segment:
        assert out["status"] == "insufficient_data" and out["changepoints"] == []
        return
    cps = out["changepoints"]
    assert len(cps) <= max_cp
    assert [c["index"] for c in cps] == sorted(c["index"] for c in cps)
    for c in cps:
        assert c["confidence"] >= 0.99 and abs(c["effect_size"]) >= 1.0
        assert min_segment <= c["index"] <= n - min_segment
        assert c["n_before"] >= min_segment and c["n_after"] >= min_segment
        assert c["direction"] == ("increase" if c["magnitude"] > 0 else "decrease")


# ── smoothing and forecasting ─────────────────────────────────────────────────


@given(xs=st.lists(_val, min_size=4, max_size=30))
@_MED
def test_ewma_fit_level_in_hull_alpha_on_grid(xs):
    level, alpha, residuals = stats_core.ewma_fit(xs)
    assert min(xs) - _EPS <= level <= max(xs) + _EPS
    assert any(_close(alpha, s / 20.0) for s in range(1, 20))
    assert len(residuals) == len(xs) - 1
    assert stats_core.ewma_fit(xs) == (level, alpha, residuals)


@given(xs=st.lists(_val, min_size=10, max_size=30), h1=st.integers(1, 30), h2=st.integers(1, 30), conf=_conf)
@_MED
def test_ewma_forecast_contains_point_and_widens_with_horizon(xs, h1, h2, conf):
    near, far = sorted((h1, h2))
    a = stats_core.ewma_forecast(xs, horizon=near, confidence=conf)
    if a is None:
        return
    b = stats_core.ewma_forecast(xs, horizon=far, confidence=conf)
    assert a["lo"] <= a["point"] <= a["hi"]
    assert min(xs) - _EPS <= a["point"] <= max(xs) + _EPS
    assert (b["hi"] - b["lo"]) >= (a["hi"] - a["lo"]) - _EPS


@given(vals=st.lists(_val, max_size=40), decay=st.floats(min_value=0.5, max_value=60.0), seed=_val)
@_FAST
def test_ewma_series_stays_in_convex_hull(vals, decay, seed):
    out = stats_core.ewma_series([(i, v) for i, v in enumerate(vals)], decay, seed=seed)
    assert [label for label, _ in out] == list(range(len(vals)))
    lo, hi = min(vals + [seed]), max(vals + [seed])
    assert all(lo - 1e-6 <= ewa <= hi + 1e-6 for _, ewa in out)


# ── multiple comparisons ──────────────────────────────────────────────────────

_pvals = st.lists(st.one_of(_p, st.none()), max_size=30)


@given(pvals=_pvals)
@_FAST
def test_bh_fdr_order_preserving_bounded_and_not_below_raw(pvals):
    adj = stats_core.bh_fdr(pvals)
    assert len(adj) == len(pvals)
    for p, a in zip(pvals, adj):
        assert (p is None) == (a is None)
        if p is not None:
            assert p - _EPS <= a <= 1.0


@given(pvals=_pvals)
@_FAST
def test_bh_fdr_monotone_in_sorted_order(pvals):
    adj = stats_core.bh_fdr(pvals)
    ranked = sorted((p, a) for p, a in zip(pvals, adj) if p is not None)
    for (p1, a1), (p2, a2) in zip(ranked, ranked[1:]):
        assert a1 <= a2 + _EPS, f"p={p1} adjusted {a1} > p={p2} adjusted {a2}"


@given(pvals=_pvals, data=st.data())
@_FAST
def test_bh_fdr_permutation_equivariant(pvals, data):
    perm = data.draw(st.permutations(range(len(pvals))))
    adj = stats_core.bh_fdr(pvals)
    adj_perm = stats_core.bh_fdr([pvals[i] for i in perm])
    for j, i in enumerate(perm):
        assert (adj[i] is None) == (adj_perm[j] is None)
        if adj[i] is not None:
            assert _close(adj[i], adj_perm[j])


# ── calibration ───────────────────────────────────────────────────────────────

_fpairs = st.lists(st.tuples(_p, st.integers(0, 1)), max_size=40)


@given(pairs=_fpairs, data=st.data())
@_FAST
def test_brier_bounded_order_independent_skill_at_most_one(pairs, data):
    bs = stats_core.brier_score(pairs)
    if not pairs:
        assert bs is None
        return
    assert 0.0 <= bs <= 1.0
    assert _close(bs, stats_core.brier_score(data.draw(st.permutations(pairs))))
    bss = stats_core.brier_skill_score(pairs)
    if bss is not None:
        assert bss <= 1.0 + _EPS


@given(pairs=_fpairs, n_bins=st.integers(1, 12))
@_FAST
def test_reliability_bins_account_for_every_pair(pairs, n_bins):
    bins = stats_core.reliability_bins(pairs, n_bins=n_bins)
    assert sum(b["n"] for b in bins) == len(pairs)
    for b in bins:
        assert b["lo"] - _EPS <= b["mean_confidence"] <= b["hi"] + _EPS
        assert 0.0 <= b["observed_rate"] <= 1.0


# ── mutation control (acceptance box 3) ───────────────────────────────────────
# Each mutant is stats_core's REAL source with one branch broken. The named property's
# body is re-run against it under a derandomized search (same examples every run, so the
# control itself cannot flake) and must FAIL; the same search against the real module must
# PASS (the control's baseline). If a refactor moves a mutated line, the `count == 1`
# check reports it rather than letting the control go silently vacuous. One test that
# iterates every mutant and reports every survivor (a parametrized test would count as one
# gate per parameter in scripts/gate_census.py).

_CONTROL = settings(max_examples=300, deadline=None, database=None, derandomize=True)

# name -> (exact source text, its broken replacement, property that must catch it, the
# property's strategies — restated because a @given test cannot be re-settings'd).
MUTANTS = {
    # bh_fdr without its step-down pass: adjusted values stop being monotone in p.
    "bh_fdr_no_step_down": (
        "        adj[k] = min(adj[k], adj[k + 1])\n",
        "        adj[k] = adj[k]\n",
        "test_bh_fdr_monotone_in_sorted_order",
        {"pvals": _pvals},
    ),
    # Wilson without the z^2/4n^2 term is the Wald width: it collapses at k=0 / k=n.
    "wilson_wald_margin": (
        "math.sqrt(phat * (1.0 - phat) / n + z2 / (4.0 * n * n))",
        "math.sqrt(phat * (1.0 - phat) / n)",
        "test_wilson_interval_bounded_contains_phat_never_collapses",
        {"kn": _k_n(), "conf": _conf},
    ),
    # effective_sample_size without its upper clamp: negative autocorrelation inflates n.
    "n_eff_no_upper_clamp": (
        "    return max(2.0, min(float(n), n_eff))\n",
        "    return max(2.0, n_eff)\n",
        "test_effective_sample_size_clamped_to_two_and_n_single",
        {"xs": _series},
    ),
    # correlation_evidence letting a caller's n_eff exceed raw n.
    "evidence_n_eff_unclamped": (
        "    ne = max(0.0, min(float(n_int), ne)) if n_int else 0.0\n",
        "    ne = max(0.0, ne) if n_int else 0.0\n",
        "test_correlation_evidence_total_on_garbage_and_bounded",
        {"r": _garbage, "n": _garbage, "n_eff": _garbage, "fdr": st.one_of(st.none(), st.booleans(), st.text(max_size=2))},
    ),
    # detect_changepoints with BOTH acceptance gates removed: every scanned best split is
    # reported, including insignificant, sub-d=1 slivers.
    "changepoint_no_gates": (
        "    if confidence < min_confidence or abs(effect) < min_effect:\n",
        "    if False:\n",
        "test_detect_changepoints_every_break_clears_both_gates",
        {"case": _cp_case(), "max_cp": st.integers(1, 3), "level_shift": st.integers(0, 400)},
    ),
    # detect_changepoints without its significance gate (magnitude gate kept).
    "changepoint_no_confidence_gate": (
        "    if confidence < min_confidence or abs(effect) < min_effect:\n",
        "    if abs(effect) < min_effect:\n",
        "test_detect_changepoints_every_break_clears_both_gates",
        {"case": _cp_case(), "max_cp": st.integers(1, 3), "level_shift": st.integers(0, 400)},
    ),
}


def _mutant(name):
    old, new = MUTANTS[name][:2]
    with open(_STATS_CORE_PATH, encoding="utf-8") as fh:
        src = fh.read()
    if src.count(old) != 1:
        return None
    mod = types.ModuleType(f"stats_core_mutant_{name}")
    exec(compile(src.replace(old, new), f"<mutant {name}>", "exec"), mod.__dict__)  # noqa: S102 — test-only mutation control
    return mod


def _search(prop_name, strategies):
    """A fresh, derandomized Hypothesis run of the property's undecorated body."""
    body = globals()[prop_name].hypothesis.inner_test
    fresh = types.FunctionType(body.__code__, body.__globals__, body.__name__, body.__defaults__, body.__closure__)
    return given(**strategies)(_CONTROL(fresh))


def test_mutation_control_every_broken_branch_is_caught(monkeypatch):
    problems = []
    module = sys.modules[__name__]
    # Bound ONCE: inside the loop the global `stats_core` IS the mutant after a setattr, so
    # restoring "to stats_core" by name would re-install the previous mutant and run the
    # next baseline against it (two mutants aimed at one property exposed exactly that).
    real = stats_core
    for name, (_old, _new, prop_name, strategies) in sorted(MUTANTS.items()):
        mutant = _mutant(name)
        if mutant is None:
            problems.append(f"{name}: target text moved/duplicated in stats_core.py — re-aim the control")
            continue
        monkeypatch.setattr(module, "stats_core", real)
        _search(prop_name, strategies)()  # baseline: the real module passes
        monkeypatch.setattr(module, "stats_core", mutant)
        try:
            _search(prop_name, strategies)()
        except (AssertionError, ExceptionGroup):
            continue
        finally:
            monkeypatch.setattr(module, "stats_core", real)
        problems.append(f"{name}: {prop_name} PASSED against the mutant — the property cannot see this broken branch")
    assert not problems, "\n".join(problems)
