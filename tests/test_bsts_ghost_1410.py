"""tests/test_bsts_ghost_1410.py — the Ghost: BSTS-lite synthetic-control counterfactual (#1410).

Pins the acceptance criteria:
  AC1 — pure-Python model recovers KNOWN effects on synthetic series (a real
        injected shift is detected with a CI that covers the truth and excludes
        zero; a null intervention's CI covers zero).
  AC2 — the pre-fit MAPE gate withholds the ghost with a stated reason (bad
        pre-fit, thin pre-period, unevaluable MAPE) — never a fabricated
        counterfactual, never a silent None.
  AC3 — the spec is part of the FROZEN design: validate_design rejects malformed
        counterfactual specs at creation, so nothing can be spec-shopped at close.
  AC4 — the served series carries the honestly-widening interval (point variance
        non-decreasing with distance from start) for the chart's band.
  AC5 — narration consumes only precomputed numbers: analysis_summary renders
        the ghost sentence (or its refusal) verbatim from the analysis block.
Plus: determinism (same input ⇒ same output), collinear-control refusal, and the
methods-registry fingerprint for the new entry.
"""

import math
import os
import sys
from datetime import datetime, timedelta

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import bsts_lite  # noqa: E402
import experiment_design  # noqa: E402

# Deterministic pseudo-noise: a fixed irrational-rotation sequence (no random module,
# so the test can never flake and the fixture can never drift).
_NOISE = [math.sin(1.7 * k) * 0.8 for k in range(400)]


def _dates(start, n):
    d0 = datetime.strptime(start, "%Y-%m-%d")
    return [(d0 + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]


def _synthetic(n_pre=40, n_post=14, effect=0.0, base=60.0):
    """Criterion driven by a control (y = 0.8·x + 10 + noise) with an injected
    post-period shift of `effect`. Returns (pre_y, pre_x, post_y, post_x)."""
    xs = [base + 5 * math.sin(k / 5.0) + _NOISE[k] for k in range(n_pre + n_post)]
    ys = [0.8 * x + 10 + _NOISE[k + 100] for k, x in enumerate(xs)]
    pre_y, post_y = ys[:n_pre], [v + effect for v in ys[n_pre:]]
    pre_x = [[x] for x in xs[:n_pre]]
    post_x = [[x] for x in xs[n_pre:]]
    return pre_y, pre_x, post_y, post_x


# ── AC1: known effects recovered ─────────────────────────────────────────────


def test_real_effect_detected_ci_covers_truth_excludes_zero():
    pre_y, pre_x, post_y, post_x = _synthetic(effect=5.0)
    fit = bsts_lite.fit_counterfactual(pre_y, len(post_y), pre_x=pre_x, post_x=post_x)
    assert fit is not None and fit["mape_pct"] is not None and fit["mape_pct"] < 5
    eff = bsts_lite.effect_summary(post_y, fit)
    assert eff["ci95_low"] <= 5.0 <= eff["ci95_high"]  # covers the truth
    assert eff["ci95_low"] > 0  # and excludes zero
    assert abs(eff["effect_mean"] - 5.0) < 1.0


def test_null_effect_ci_covers_zero():
    pre_y, pre_x, post_y, post_x = _synthetic(effect=0.0)
    fit = bsts_lite.fit_counterfactual(pre_y, len(post_y), pre_x=pre_x, post_x=post_x)
    eff = bsts_lite.effect_summary(post_y, fit)
    assert eff["ci95_low"] <= 0.0 <= eff["ci95_high"]


def test_pure_level_ghost_without_controls():
    # No controls: the ghost is the frozen level — still a valid counterfactual.
    pre_y = [70 + _NOISE[k] for k in range(30)]
    post_y = [73 + _NOISE[k + 200] for k in range(10)]
    fit = bsts_lite.fit_counterfactual(pre_y, len(post_y))
    eff = bsts_lite.effect_summary(post_y, fit)
    assert eff["ci95_low"] > 0  # the +3 shift is real against a flat level
    assert 2.0 < eff["effect_mean"] < 4.0


# ── AC4: the interval widens honestly ────────────────────────────────────────


def test_point_variance_never_shrinks_with_horizon():
    # A drifting pre-period forces sigma_eta² > 0, so the band must widen.
    pre_y = [60 + 0.3 * k + _NOISE[k] for k in range(40)]
    fit = bsts_lite.fit_counterfactual(pre_y, 12)
    assert fit["sigma_eta2"] > 0
    pv = fit["point_var"]
    assert all(pv[i + 1] >= pv[i] for i in range(len(pv) - 1))
    assert pv[-1] > pv[0]


def test_deterministic():
    pre_y, pre_x, post_y, post_x = _synthetic(effect=2.0)
    a = bsts_lite.fit_counterfactual(pre_y, len(post_y), pre_x=pre_x, post_x=post_x)
    b = bsts_lite.fit_counterfactual(pre_y, len(post_y), pre_x=pre_x, post_x=post_x)
    assert a["ghost"] == b["ghost"] and a["point_var"] == b["point_var"] and a["mape_pct"] == b["mape_pct"]


def test_collinear_controls_refused_structurally():
    pre_y, pre_x, post_y, post_x = _synthetic()
    pre_x2 = [[x[0], 2 * x[0]] for x in pre_x]  # perfectly collinear pair
    post_x2 = [[x[0], 2 * x[0]] for x in post_x]
    assert bsts_lite.fit_counterfactual(pre_y, len(post_y), pre_x=pre_x2, post_x=post_x2) is None


# ── AC3: the spec is frozen — validation at create ───────────────────────────


def _design(cf):
    return {
        "baseline_days": 14,
        "washout_days": 0,
        "stopping_rule": "run the full window regardless of interim trend; abort only on illness",
        "criterion": {"metric": "recovery_score", "direction": "higher", "min_effect": 2},
        "counterfactual": cf,
    }


def test_validate_design_accepts_good_spec_and_rejects_bad_ones():
    ok, issues = experiment_design.validate_design(_design({"controls": ["resting_heart_rate"], "pre_days": 28}))
    assert ok, issues
    for bad, needle in [
        ({"controls": ["nope_metric"]}, "unknown metric"),
        ({"controls": ["recovery_score"]}, "criterion metric itself"),
        ({"controls": ["resting_heart_rate", "resting_heart_rate"]}, "repeat"),
        ({"controls": [], "pre_days": 5}, "pre_days"),
        ({"controls": [], "mape_gate_pct": 90}, "mape_gate_pct"),
        ({"controls": [], "spec_shop": True}, "unknown counterfactual fields"),
        ("not-a-dict", "must be an object"),
    ]:
        ok, issues = experiment_design.validate_design(_design(bad))
        assert not ok and any(needle in i for i in issues), (bad, issues)


# ── AC2 + orchestration: counterfactual_analysis (pure) ──────────────────────


def _dated(start, values):
    return dict(zip(_dates(start, len(values)), values))


def _run_analysis(effect=5.0, n_pre=40, n_post=14, cf=None, gap_days=()):
    pre_y, pre_x, post_y, post_x = _synthetic(n_pre=n_pre, n_post=n_post, effect=effect)
    start = "2026-05-01"
    pre_start = (datetime.strptime(start, "%Y-%m-%d") - timedelta(days=n_pre)).strftime("%Y-%m-%d")
    crit = _dated(pre_start, pre_y + post_y)
    ctrl = _dated(pre_start, [x[0] for x in pre_x + post_x])
    for d in gap_days:
        crit.pop(d, None)
    design = _design(cf if cf is not None else {"controls": ["resting_heart_rate"], "pre_days": n_pre})
    end = _dates(start, n_post)[-1]
    return experiment_design.counterfactual_analysis(design, crit, {"resting_heart_rate": ctrl}, start, end)


def test_analysis_ok_end_to_end_with_series_and_level():
    out = _run_analysis(effect=5.0)
    assert out["state"] == "ok"
    assert out["ci95_low"] > 0 and out["ci95_low"] <= 5.0 <= out["ci95_high"]
    s = out["series"]
    assert len(s["dates"]) == len(s["observed"]) == len(s["ghost"]) == len(s["ci_low"]) == len(s["ci_high"]) == out["n_post"]
    assert s["truncated"] is False
    assert out["level"] == "high" and out["spec"]["engine"] == "bsts-lite-v1"
    # the band the chart draws is the widening interval: strictly ordered
    assert all(lo <= g <= hi for lo, g, hi in zip(s["ci_low"], s["ghost"], s["ci_high"]))


def test_analysis_counts_dropped_days_honestly():
    out = _run_analysis(gap_days=("2026-04-10", "2026-04-11", "2026-05-03"))
    assert out["state"] == "ok"
    assert out["n_pre_dropped"] >= 2 and out["n_post_dropped"] >= 1


def test_thin_pre_period_refused_with_reason():
    out = _run_analysis(n_pre=20, cf={"controls": ["resting_heart_rate"], "pre_days": 15})
    # pre window of 15 days can align at most 15 < 14? (15 >= 14) — force thinner via gaps
    out = _run_analysis(
        n_pre=20,
        cf={"controls": ["resting_heart_rate"], "pre_days": 15},
        gap_days=tuple(_dates("2026-04-16", 5)),
    )
    assert out["state"] == "no_counterfactual"
    assert "insufficient pre-period" in out["reason"]


def test_bad_prefit_mape_gate_refuses_with_reason():
    # A pre-period the model cannot track: huge alternating swings, tight gate.
    start = "2026-05-01"
    pre = [50 + (200 if k % 2 else -20) for k in range(30)]
    post = [60.0] * 10
    crit = _dated("2026-04-01", pre + post)
    design = _design({"controls": [], "pre_days": 30, "mape_gate_pct": 5})
    out = experiment_design.counterfactual_analysis(design, crit, {}, start, _dates(start, 10)[-1])
    assert out["state"] == "no_counterfactual"
    assert "MAPE" in out["reason"] and "gate" in out["reason"]
    assert out["mape_pct"] > 5


def test_near_zero_criterion_mape_unevaluable_refused():
    start = "2026-05-01"
    crit = _dated("2026-04-01", [0.0] * 30 + [1.0] * 10)
    design = _design({"controls": [], "pre_days": 30})
    out = experiment_design.counterfactual_analysis(design, crit, {}, start, _dates(start, 10)[-1])
    assert out["state"] == "no_counterfactual"
    assert "unevaluable" in out["reason"]


# ── AC5: narration reads the block, never computes ───────────────────────────


def test_summary_sentence_renders_ghost_and_refusal_verbatim():
    design = _design({"controls": [], "pre_days": 28})
    base = {
        "effect_size": 3.0,
        "mean_window": 63.0,
        "mean_baseline": 60.0,
        "n_window": 14,
        "n_baseline": 14,
        "ci95_low": 1.0,
        "ci95_high": 5.0,
        "cohens_d": 0.9,
        "verdict": "supported",
    }
    ok_line = experiment_design.analysis_summary(
        design,
        {**base, "counterfactual": {"state": "ok", "effect_mean": 4.2, "ci95_low": 1.1, "ci95_high": 7.3, "mape_pct": 6.4, "n_pre": 28}},
    )
    assert "vs the counterfactual: +4.2" in ok_line and "MAPE 6.4%" in ok_line and "n_pre 28" in ok_line
    refused_line = experiment_design.analysis_summary(
        design, {**base, "counterfactual": {"state": "no_counterfactual", "reason": "pre-fit MAPE 22% exceeds the frozen gate 15%"}}
    )
    assert "no counterfactual (pre-fit MAPE 22% exceeds the frozen gate 15%)" in refused_line


def test_methods_registry_fingerprint_current():
    import methods_registry

    entry = methods_registry.REGISTRY["bsts_lite_counterfactual"]
    assert (
        entry["fingerprint"] == entry["recorded_fingerprint"]
    ), "bsts_lite.fit_counterfactual changed — re-verify the registry prose and update the recorded fingerprint"
