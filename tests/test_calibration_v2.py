"""tests/test_calibration_v2.py — calibration-v2: three questions, three tests (owner requirement 2026-11-09).

"Whether calibration can be estimated at all. Whether the sample supports a claim of overconfidence or underconfidence.
Whether a coach demonstrates forecasting skill relative to the baseline. These are different questions and shouldn't
share one arbitrary threshold." Every forecaster here is SYNTHETIC.

Each question has a firing case, a not-firing case and a mutation control (the test is re-run with the decision
disabled or inverted and must then fail to tell the cases apart).
"""

from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from experiment import calibration_core, calibration_v2 as V  # noqa: E402

assess_v2 = V.assess

LABELS = {"over_confident", "under_confident", "mixed", "advantage", "baseline_better"}
NEVER = ("well-calibrated", "well_calibrated", "authoritative", "reliable")


def _calls(stated: float, hits: int, n: int) -> list:
    return [(stated, 1)] * hits + [(stated, 0)] * (n - hits)


# ── the constants are pre-declared, derived and pinned ─────────────────────────────────────


def test_constants_are_pinned():
    """Moving any of these is a method change (a new method_version), not a tuning knob."""
    assert V.METHOD_VERSION == "calibration-v2"
    assert V.ALPHA == 0.05
    assert V.LEVEL_BINS == 10
    assert V.USABLE_CI_WIDTH == 0.5
    assert V.MIN_LEVELS == 2
    assert V.EVENTS_PER_PARAMETER * V.RECALIBRATION_PARAMETERS == 20
    assert V.SKILL_RULE == "nothing_changes"


def test_min_level_n_is_derived_from_the_usable_width():
    n = V.min_level_n()
    assert n == 17
    widest = lambda m: max(hi - lo for lo, hi in (V.clopper_pearson(k, m) for k in range(m + 1)))  # noqa: E731
    assert widest(n) <= V.USABLE_CI_WIDTH < widest(n - 1)


def test_the_baseline_and_records_are_the_sites_own():
    from coach import coach_baseline

    assert V.SKILL_RULE == coach_baseline.RULE_ID
    assert V.SKILL_RECORDS == coach_baseline.RECORDS
    assert V.ALPHA == coach_baseline.SIGNIFICANCE


def test_exact_machinery_against_known_values():
    lo, hi = V.clopper_pearson(10, 44)
    assert round(lo, 4) == 0.1147 and round(hi, 4) == 0.3784  # R: binom.test(10, 44)$conf.int
    assert V.clopper_pearson(0, 10) == (0.0, pytest.approx(0.3085, abs=1e-4))
    assert V.binomial_two_sided_p(5, 5, 0.5) == pytest.approx(0.0625)
    assert V.holm([0.01, 0.04, 0.03], 0.05) == [True, False, False]
    assert V.holm_adjusted([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])


# ── question 1: estimability ──────────────────────────────────────────────────────────────


def test_all_at_fifty_percent_is_not_estimable_across_levels_but_states_its_one_level():
    a = V.assess(_calls(0.5, 30, 200))
    est = a["estimability"]
    assert est["result"] == "not_estimable" and est["slope"] is None and est["estimate"] is None
    assert "not estimable" in est["wording"] and "1 confidence level" in est["wording"]
    [level] = est["levels"]
    assert level["n"] == 200 and level["hits"] == 30 and level["ci_usable"] is True
    assert level["statement"].startswith("Calls stated at about 50% came true 30 of 200 (95% CI")
    # A single level CAN still carry a direction claim — that is question 2, asked separately.
    assert a["confidence_direction"]["label"] == "over_confident"


def test_two_well_filled_levels_are_estimable_with_a_slope_and_interval():
    pairs = _calls(0.3, 9, 30) + _calls(0.8, 24, 30)
    est = V.estimability(pairs)
    assert est["result"] == "estimable", est["reasons"]
    lo, hi = est["slope"]["ci95"]
    assert lo < est["slope"]["estimate"] < hi and lo < 1.0 < hi
    assert est["n"] == 60 and est["estimate"] == est["slope"]["estimate"]


def test_a_handful_off_the_main_level_does_not_make_it_estimable():
    pairs = _calls(0.5, 60, 200) + _calls(0.7, 5, 8)
    est = V.estimability(pairs)
    assert est["result"] == "not_estimable" and est["usable_levels"] == 1


def test_mutation_control_estimability_gate():
    """With the level floor removed (min 1 call) the handful case WOULD be estimable — so the floor is what holds it."""
    pairs = _calls(0.5, 60, 200) + _calls(0.7, 5, 8)
    real = V._MIN_LEVEL_N_CACHE.copy()
    try:
        V._MIN_LEVEL_N_CACHE[(V.USABLE_CI_WIDTH, 0.95)] = 1
        assert V.estimability(pairs)["result"] == "estimable"
    finally:
        V._MIN_LEVEL_N_CACHE.clear()
        V._MIN_LEVEL_N_CACHE.update(real)
    assert V.estimability(pairs)["result"] == "not_estimable"


# ── question 2: over/under-confidence ─────────────────────────────────────────────────────


def _spread_overconfident(scale: int) -> list:
    """Stated 0.6 / 0.75 / 0.9, true rates 0.45 / 0.5 / 0.55 — a real over-confidence, at `scale` calls per level."""
    return _calls(0.6, round(0.45 * scale), scale) + _calls(0.75, round(0.5 * scale), scale) + _calls(0.9, round(0.55 * scale), scale)


def test_a_spread_miscalibrated_coach_fires_over_confidence():
    d = V.confidence_direction(_spread_overconfident(60))
    assert d["result"] == d["label"] == "over_confident"
    assert any(t["rejects"] and t["direction"] == "over" for t in d["tests"])
    assert d["estimate"] > 0 and d["ci95"][0] <= d["estimate"] <= d["ci95"][1] and d["n"] == 180 and "Holm" in d["method"]
    assert V.estimability(_spread_overconfident(60))["result"] == "estimable"


def test_the_same_miscalibration_on_too_few_calls_does_not_fire():
    d = V.confidence_direction(_spread_overconfident(4))
    assert d["label"] is None and d["result"] in ("consistent_not_established", "insufficient_evidence")
    assert "well" not in d["wording"].lower()


def test_insufficient_evidence_when_no_level_could_have_rejected():
    d = V.confidence_direction(_calls(0.5, 2, 4))  # even 0 of 4 at 50% gives p = 0.125
    assert d["result"] == "insufficient_evidence" and d["label"] is None


def test_consistent_is_never_praise():
    d = V.confidence_direction(_calls(0.6, 60, 100))
    assert d["result"] == "consistent_not_established" and d["label"] is None
    assert d["wording"].startswith("Consistent with stated confidence (not established)")


def test_under_confidence_and_mixed():
    assert V.confidence_direction(_calls(0.6, 95, 100))["label"] == "under_confident"
    assert V.confidence_direction(_calls(0.6, 95, 100) + _calls(0.9, 50, 100))["label"] == "mixed"


def test_holm_controls_the_family():
    """A level whose raw p is just under alpha does not fire once two more levels share the family."""
    one = _calls(0.5, 17, 50)  # raw two-sided p ≈ 0.033
    assert V.confidence_direction(one)["label"] == "over_confident"
    family = one + _calls(0.7, 7, 10) + _calls(0.9, 9, 10)
    d = V.confidence_direction(family)
    assert d["label"] is None and d["tests"][0]["p"] < 0.05 < d["tests"][0]["p_holm"]


def test_mutation_control_direction_test():
    """Invert the decision (reject when p_holm > alpha) and the firing and not-firing cases swap — the test discriminates."""
    big, small = _spread_overconfident(60), _spread_overconfident(4)
    real = V.holm
    try:
        V.holm = lambda ps, alpha=V.ALPHA: [not r for r in real(ps, alpha)]
        assert V.confidence_direction(big)["label"] is None
        assert V.confidence_direction(small)["label"] is not None
    finally:
        V.holm = real


# ── question 3: skill against the nothing-changes guess ───────────────────────────────────


def _paired(coach_only: int, rule_only: int, both: int = 10, neither: int = 10, record: str = "number") -> dict:
    pairs = [(True, False)] * coach_only + [(False, True)] * rule_only + [(True, True)] * both + [(False, False)] * neither
    return {record: {"pairs": pairs, "unscorable": 2, "not_yet_scored": 1}}


def test_skill_label_only_when_the_interval_excludes_zero():
    s = V.skill_vs_baseline(_paired(25, 5))
    rec = s["records"]["number"]
    assert s["label"] == "advantage" and rec["ci"][0] > 0 and rec["n"] == 50
    assert rec["estimate"] == round(20 / 50, 3) and rec["unscorable"] == 2 and rec["not_yet_scored"] == 1
    worse = V.skill_vs_baseline(_paired(5, 25))
    assert worse["label"] == "baseline_better" and worse["records"]["number"]["ci"][1] < 0


def test_skill_neutral_when_the_interval_spans_zero():
    s = V.skill_vs_baseline(_paired(9, 5))
    rec = s["records"]["number"]
    assert rec["ci"][0] < 0 < rec["ci"][1]
    assert s["label"] is None and s["result"] == "no_demonstrated_advantage"
    assert s["wording"].startswith("No demonstrated advantage")


def test_skill_interval_agrees_with_the_exact_sign_test():
    """The conditional interval excludes 0 at 95% only when the site's own exact sign test rejects at 0.05."""
    from common import stats_core

    for b in range(0, 31):
        c = 30 - b
        s = V.skill_vs_baseline(_paired(b, c))["records"]["number"]
        p = stats_core.exact_sign_test_p(b, c)
        assert (s["label"] is not None) == (p < 0.05), (b, c, p, s["ci"])


def test_skill_records_are_never_added_and_bonferroni_widens():
    one = V.skill_vs_baseline(_paired(20, 6))["records"]["number"]
    two = V.skill_vs_baseline({**_paired(20, 6), **_paired(3, 3, record="direction")})["records"]["number"]
    assert one["ci_confidence"] == 0.95 and two["ci_confidence"] == 0.975
    assert two["ci"][0] < one["ci"][0] and two["n"] == one["n"]


def test_no_baseline_and_not_comparable():
    assert V.skill_vs_baseline(None)["result"] == "no_baseline"
    s = V.skill_vs_baseline({"number": {"pairs": [], "unscorable": 3, "not_yet_scored": 4}})
    assert s["result"] == "not_comparable" and s["label"] is None and s["records"]["number"]["not_yet_scored"] == 4


def test_mutation_control_skill_test():
    """With the interval collapsed to its point (no uncertainty), a 9-vs-5 split WOULD be labelled."""
    real = V.clopper_pearson
    try:
        V.clopper_pearson = lambda k, n, confidence=0.95: (k / n, k / n)
        assert V.skill_vs_baseline(_paired(9, 5))["label"] == "advantage"
    finally:
        V.clopper_pearson = real
    assert V.skill_vs_baseline(_paired(9, 5))["label"] is None


# ── the shape every output carries ────────────────────────────────────────────────────────


def test_every_answer_carries_n_estimate_interval_and_method_and_no_praise():
    a = assess_v2(_spread_overconfident(60), _paired(25, 5))
    assert a["method_version"] == "calibration-v2" and a["n"] == 180
    for q in ("estimability", "confidence_direction"):
        assert {"n", "estimate", "ci95", "method", "wording"} <= set(a[q]), q
    for rec in a["skill"]["records"].values():
        assert {"n", "estimate", "ci", "p"} <= set(rec)
    assert a["skill"]["method"] and a["skill"]["baseline"] == "nothing_changes"
    blob = json.dumps(a).lower()
    assert not [w for w in NEVER if w in blob]
    for q in ("confidence_direction", "skill"):
        assert a[q]["label"] is None or a[q]["label"] in LABELS


def test_v1_is_untouched_by_v2():
    """v2 is additive: score_pairs' output for the same pairs is what it was, and v1 never reads v2."""
    pairs = _spread_overconfident(60)
    before = calibration_core.score_pairs(pairs)
    assess_v2(pairs, _paired(25, 5))
    assert calibration_core.score_pairs(pairs) == before
    assert "assessment_v2" not in before and "method_version" not in before
    with open(calibration_core.__file__, encoding="utf-8") as fh:
        assert "calibration_v2" not in fh.read()


# ── the route ─────────────────────────────────────────────────────────────────────────────


def test_baseline_paired_mirrors_the_served_comparison():
    """Question 3 is asked of exactly the rows coach_baseline.comparison_block tallies."""
    from coach import coach_baseline
    from web import site_api_calibration_v2 as L

    def row(status, right, kind="directional", rule="nothing_changes"):
        r = {"status": status, "evaluation": {"type": kind, "metric": "hrv", "condition": "up"}}
        if rule:
            r["baseline"] = {"rule": rule, "right": right}
        return r

    rows = (
        [row("confirmed", False)] * 6
        + [row("refuted", True)] * 2
        + [row("confirmed", True)] * 3
        + [row("refuted", None)] * 2
        + [row("refuted", False, rule=None)] * 1
    )
    paired = L.baseline_paired(rows)
    comp = coach_baseline.comparison_block(rows)["records"]
    for rec, block in paired.items():
        s = V.skill_vs_baseline(paired)["records"][rec]
        c = comp[rec]
        assert (s["n"], s["coach_only"], s["rule_only"], s["unscorable"], s["not_yet_scored"]) == (
            c["scored"],
            c["coach_only"],
            c["rule_only"],
            c["unscorable"],
            c["not_yet_scored"],
        )
