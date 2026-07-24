"""tests/test_prop_bsts_lite.py — property-based (Hypothesis) proofs of the BSTS-lite
synthetic-control counterfactual (lambdas/bsts_lite.py), #1664 / epic #1648.

bsts_lite is pure by construction (its own docstring: "no I/O, no clock, no imports
beyond math"; deterministic q-grid). The invariants proven over input SPACES:

  * fit_counterfactual returns a well-formed, finite ghost of the requested length;
  * the forecast interval WIDENS (point_var is non-decreasing) — the honestly-growing
    uncertainty the module is built to express;
  * with no controls the ghost is a flat frozen-level forecast (all equal);
  * the fit is deterministic (same data -> same ghost, always);
  * a CONSTANT pre-period against a matching post-period yields ~zero effect with a CI
    that straddles zero — no signal, no effect (an honesty invariant);
  * effect_summary's CI always contains its mean and reports an honest n;
  * the internal linear solver recovers the solution of a well-conditioned system.
"""

import math
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import bsts_lite  # noqa: E402

_finite = st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False)
_pre_y = st.lists(_finite, min_size=3, max_size=20)
_post_len = st.integers(min_value=1, max_value=10)


@given(pre_y=_pre_y, post_len=_post_len)
@settings(max_examples=200, deadline=None)
def test_fit_shape_and_finiteness(pre_y, post_len):
    fit = bsts_lite.fit_counterfactual(pre_y, post_len)
    assert fit is not None
    assert len(fit["ghost"]) == post_len
    assert all(math.isfinite(g) for g in fit["ghost"])
    assert len(fit["point_var"]) == post_len
    assert all(v >= 0.0 and math.isfinite(v) for v in fit["point_var"])
    assert fit["n_pre"] == len(pre_y)
    assert fit["q"] in bsts_lite.Q_GRID
    assert fit["n_controls"] == 0
    assert fit["sigma_eps2"] >= 0.0 and fit["sigma_eta2"] >= 0.0


@given(pre_y=_pre_y, post_len=_post_len)
@settings(max_examples=200, deadline=None)
def test_point_var_is_non_decreasing(pre_y, post_len):
    # The interval must WIDEN away from the intervention — never tighten.
    pv = bsts_lite.fit_counterfactual(pre_y, post_len)["point_var"]
    for a, b in zip(pv, pv[1:]):
        assert b >= a - 1e-9


@given(pre_y=_pre_y, post_len=_post_len)
@settings(max_examples=150, deadline=None)
def test_no_controls_ghost_is_flat(pre_y, post_len):
    ghost = bsts_lite.fit_counterfactual(pre_y, post_len)["ghost"]
    assert max(ghost) - min(ghost) < 1e-6


@given(pre_y=_pre_y, post_len=_post_len)
@settings(max_examples=150, deadline=None)
def test_fit_is_deterministic(pre_y, post_len):
    a = bsts_lite.fit_counterfactual(pre_y, post_len)
    b = bsts_lite.fit_counterfactual(pre_y, post_len)
    assert a["ghost"] == b["ghost"]
    assert a["point_var"] == b["point_var"]
    assert a["q"] == b["q"] and a["mape_pct"] == b["mape_pct"]


@given(c=_finite, n=st.integers(min_value=3, max_value=15), post_len=_post_len)
@settings(max_examples=150, deadline=None)
def test_constant_series_has_zero_effect(c, n, post_len):
    # A perfectly flat pre-period whose post-period continues flat: the ghost equals
    # the observed, so the estimated effect is ~0 and its CI straddles 0.
    fit = bsts_lite.fit_counterfactual([c] * n, post_len)
    summary = bsts_lite.effect_summary([c] * post_len, fit)
    assert summary is not None
    assert abs(summary["effect_mean"]) < 1e-3
    assert summary["ci95_low"] <= 1e-6 <= summary["ci95_high"] + 1e-6


@given(pre_y=_pre_y, post_len=_post_len, data=st.data())
@settings(max_examples=200, deadline=None)
def test_effect_summary_ci_contains_mean_and_honest_n(pre_y, post_len, data):
    fit = bsts_lite.fit_counterfactual(pre_y, post_len)
    observed = data.draw(
        st.lists(st.one_of(st.none(), _finite), min_size=post_len, max_size=post_len),
    )
    summary = bsts_lite.effect_summary(observed, fit)
    n_present = sum(1 for v in observed if v is not None)
    if n_present == 0:
        assert summary is None
        return
    assert summary["ci95_low"] <= summary["effect_mean"] + 1e-9
    assert summary["effect_mean"] <= summary["ci95_high"] + 1e-9
    assert summary["n_post_used"] == n_present <= len(observed)


@given(post_len=_post_len, pre_y=_pre_y)
@settings(max_examples=50, deadline=None)
def test_all_missing_observations_return_none(post_len, pre_y):
    fit = bsts_lite.fit_counterfactual(pre_y, post_len)
    assert bsts_lite.effect_summary([None] * post_len, fit) is None


@given(
    n=st.integers(min_value=1, max_value=4),
    seed=st.lists(_finite, min_size=4, max_size=4),
    data=st.data(),
)
@settings(max_examples=150, deadline=None)
def test_solve_recovers_well_conditioned_system(n, seed, data):
    # Strictly diagonally dominant => non-singular; the solver must recover A x = b.
    x = data.draw(st.lists(_finite, min_size=n, max_size=n))
    a = []
    for i in range(n):
        row = [data.draw(st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False)) for _ in range(n)]
        row[i] = 100.0 + abs(seed[i % 4])  # dominate the diagonal
        a.append(row)
    b = [sum(a[i][j] * x[j] for j in range(n)) for i in range(n)]
    got = bsts_lite._solve([r[:] for r in a], b[:])
    assert got is not None
    for i in range(n):
        residual = sum(a[i][j] * got[j] for j in range(n)) - b[i]
        assert abs(residual) < 1e-6
