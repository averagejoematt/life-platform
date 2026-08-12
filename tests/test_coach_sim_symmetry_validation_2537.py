"""
test_coach_sim_symmetry_validation_2537.py — grading the detector, and grading the grader
(#2537 items 2 and 4).

WHAT THIS GUARDS, AND WHY IT IS A SEPARATE FILE FROM THE DETECTOR'S OWN TESTS.
`test_coach_sim_balanced_clause_2537.py` asks "does the regex fire on the right
sentence". This file asks a different and harder question: "when we report that the
detector agrees with the judges, is that report capable of saying no?" Those fail in
different ways and should be able to go red independently.

THE FAILURE MODE BEING DESIGNED AGAINST. Run against the real 2026-08-10 corpus, the
previous version of `validate_against_judge_tells` returned `precision: 0.915`. True,
and badly misleading: 78.3% of the joined conversations carry a symmetry tell, so a
detector firing at random would score ~0.78 and the widened one looks triumphant for
beating coin-flip noise by a little. Every test below exists to make the flattering
number impossible to report alone — the base rate, the other arm, an interval, and a
control detector on the identical join all come back together or the shape is wrong.

THE CENTRAL TEST IS `test_a_detector_that_fires_at_random_shows_no_association`. It
constructs a predictor that fires at the SAME rate as the real one but on the wrong
conversations, and requires the report to call that null. A grader that cannot fail
on random input is not measuring agreement, it is measuring the base rate — which is
exactly the defect this file was written after finding.

NO REAL CORPUS HERE. The 2026-08-10 run carries Matthew's real health facts verbatim
and this repo is public, so the corpus lives outside the tree and is referenced by
sha256 only. Fixtures below are synthetic and constructed to have known answers; the
real-corpus numbers live in the PR and the issue, reproducible at $0 with
`scripts/coach_sim_replay.py --corpus <dir> --validate-symmetry <dir>/metrics.json`.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import random
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_ROOT, "scripts", f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


simval = _load("coach_sim_validation")
csa = _load("coach_sim_analyze")


# ── The statistics, against hand-computed values ──────────────────────────────
#
# scipy is not installed (stdlib-only, CLAUDE.md), so these are checked against
# values worked out by hand rather than against another implementation. That is the
# stronger check anyway: agreeing with a library you also chose proves nothing about
# whether the formula is the right one.


def test_wilson_interval_matches_the_hand_computed_value():
    lo, hi = simval.wilson_ci(54, 59)
    assert (lo, hi) == (0.816, 0.963)


def test_wilson_stays_inside_the_unit_interval_at_a_perfect_rate():
    """8/8 is the narrow control's real arm. The normal approximation gives a
    zero-width interval at 1.0 and can exceed 1; Wilson must not."""
    lo, hi = simval.wilson_ci(8, 8)
    assert hi <= 1.0 and lo < 1.0, "a perfect rate on n=8 must not report certainty"
    assert lo == pytest.approx(0.676, abs=0.002)


def test_wilson_reports_absence_on_an_empty_denominator():
    assert simval.wilson_ci(0, 0) == (None, None)


def test_fisher_matches_the_hand_computed_p_for_a_small_table():
    """The classic tea-tasting 2x2 [[3,1],[1,3]] has an exact two-sided p of 0.4857."""
    assert simval.fisher_exact_two_sided(3, 1, 1, 3) == pytest.approx(0.4857, abs=0.0005)


def test_fisher_survives_a_table_whose_factorials_overflow_a_float():
    """n=120 overflows the naive product form; the log-space path must return a real
    probability rather than NaN. This is the table the corpus actually produced."""
    p = simval.fisher_exact_two_sided(54, 5, 40, 21)
    assert math.isfinite(p) and 0.0 < p < 0.01


def test_fisher_is_one_for_a_table_with_no_association():
    assert simval.fisher_exact_two_sided(5, 5, 5, 5) == pytest.approx(1.0, abs=1e-9)


def test_spearman_is_exact_on_a_monotone_and_an_antitone_pair():
    assert simval.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert simval.spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)


def test_spearman_averages_ties_instead_of_inventing_an_order():
    """Most conversations have 0 or 1 detector hits. If ties were broken by position
    the coefficient would depend on the order files were globbed in."""
    forward = simval.spearman([0, 0, 0, 1], [5, 6, 7, 9])
    reversed_ties = simval.spearman([0, 0, 0, 1], [7, 6, 5, 9])
    assert forward == pytest.approx(reversed_ties), "tied x values must not read the order of y"


def test_partial_correlation_removes_a_pure_confound():
    """x and y are independent given z, and both are driven by z. The raw coefficient
    is strongly positive and the partial must collapse toward zero — this is the whole
    reason the confound controls are reported."""
    z = list(range(30))
    x = [v + (i % 3) for i, v in enumerate(z)]
    y = [v + (i % 5) for i, v in enumerate(z)]
    assert simval.spearman(x, y) > 0.9
    assert abs(simval.partial_spearman(x, y, z)) < 0.35


def test_bootstrap_is_deterministic_across_calls():
    """A CI that moves every invocation cannot be diffed run over run, which is the
    only reason the scoreboard (#2539) stores these."""
    rows = [{"a": i, "b": (i * 7) % 13} for i in range(40)]
    stat = lambda s: simval.spearman([r["a"] for r in s], [r["b"] for r in s])  # noqa: E731
    assert simval.bootstrap_ci(rows, stat) == simval.bootstrap_ci(rows, stat)


def test_bootstrap_reports_absence_rather_than_a_one_point_interval():
    assert simval.bootstrap_ci([{"a": 1}], lambda s: 1.0)[:2] == (None, None)


# ── The contingency cannot report a rate without its comparator ───────────────


def test_contingency_reports_both_arms_the_base_rate_and_an_interval():
    """The shape assertion. `p_label_given_fires` is precision; on its own it is the
    misleading number this module exists to stop. It must never be returned without
    the silent arm, the base rate, and an interval on each."""
    result = simval.contingency([(True, True)] * 54 + [(False, True)] * 5 + [(True, False)] * 40 + [(False, False)] * 21)
    for required in (
        "p_label_given_fires",
        "p_label_given_fires_ci",
        "p_label_given_silent",
        "p_label_given_silent_ci",
        "base_rate",
        "fire_rate",
        "risk_ratio",
        "phi",
        "fisher_p",
        "n",
    ):
        assert required in result, f"{required} missing — a conditional rate alone is not a finding"
    assert result["p_label_given_fires"] == 0.915
    assert result["base_rate"] == 0.783, "the number precision has to beat must be stated"
    assert result["phi"] == 0.315
    assert result["fisher_p"] < 0.001


def test_contingency_calls_a_null_a_null():
    """Predictions independent of the label: phi ~0 and a non-significant p, even
    though 'precision' is a healthy 0.75 because the base rate is 0.75."""
    pairs = [(True, True)] * 30 + [(False, True)] * 10 + [(True, False)] * 30 + [(False, False)] * 10
    result = simval.contingency(pairs)
    assert result["p_label_given_fires"] == 0.75, "a high precision on a high base rate is not evidence"
    assert result["base_rate"] == 0.75
    assert result["phi"] == pytest.approx(0.0, abs=1e-9)
    assert result["risk_ratio"] == pytest.approx(1.0, abs=1e-9)
    assert result["fisher_p"] > 0.9


# ── End to end, through the real entry point ──────────────────────────────────
#
# The payload is built by `conversation_metrics` over JSONL written the way
# `coach_chat_sim.py` writes it, so the join key and the detector are the production
# ones. Hand-building metric dicts would test a call shape production never uses.

_SYMMETRIC = "That's signal, not alarm."
_PLAIN = "Slept 7h12m. Same as Tuesday."
_SYM_TELL = "the reply lands on a balanced antithesis, very rhetorical symmetry"
_OTHER_TELL = "the reply is far longer than the message it answers"


def _corpus(tmp_path, convos):
    path = tmp_path / "sleep_coach.jsonl"
    path.write_text("\n".join(json.dumps(c) for c in convos) + "\n")
    return str(tmp_path)


def _convo(sid, replies):
    return {
        "scenario_id": sid,
        "coach": "sleep_coach",
        "coach_name": "Sleep Coach",
        "archetype": "day_in_life",
        "turns": [{"inbound": "how'd I sleep", "reply": r, "status": "sent"} for r in replies],
    }


def _payload(tmp_path, plan):
    """`plan` is a list of (n_symmetric_replies, n_plain_replies, labelled) triples."""
    convos, panel = [], {}
    for i, (n_sym, n_plain, labelled) in enumerate(plan):
        sid = f"s{i}"
        convos.append(_convo(sid, [_SYMMETRIC] * n_sym + [_PLAIN] * n_plain))
        panel[sid] = {
            "coach": "sleep_coach",
            "archetype": "day_in_life",
            "tells": ([_SYM_TELL] if labelled else []) + [_OTHER_TELL, _OTHER_TELL],
        }
    rows = [csa.conversation_metrics(c) for c in csa.load_runs(_corpus(tmp_path, convos))]
    return {"metrics": rows, "panel": panel}


def test_the_validation_carries_the_control_arm_and_the_caveats(tmp_path):
    result = csa.validate_against_judge_tells(_payload(tmp_path, [(1, 1, True)] * 15 + [(0, 2, False)] * 15))
    assert result["verdict"] == "measured"
    assert "detector" in result and "control_narrow" in result and "correlation" in result
    assert result["detector"]["base_rate"] == 0.5
    assert result["caveats"], "an in-sample, noisily-labelled correlation must carry its limits"
    assert result["label_rule"], "the reader must be able to see the rule that made the labels"


def test_the_backwards_compatible_keys_still_agree_with_the_new_block(tmp_path):
    """Consumers of the old flat keys must not silently diverge from `detector`."""
    result = csa.validate_against_judge_tells(_payload(tmp_path, [(1, 1, True)] * 15 + [(0, 2, False)] * 15))
    assert result["precision"] == result["detector"]["p_label_given_fires"]
    assert result["recall_on_labelled"] == result["detector"]["recall"]
    assert result["labelled_positive_rate"] == result["detector"]["base_rate"]
    assert result["true_positive"] == result["detector"]["true_positive"]


def test_a_perfectly_agreeing_detector_is_reported_as_significant(tmp_path):
    result = csa.validate_against_judge_tells(_payload(tmp_path, [(2, 1, True)] * 20 + [(0, 3, False)] * 20))
    det = result["detector"]
    assert det["p_label_given_fires"] == 1.0 and det["p_label_given_silent"] == 0.0
    assert det["fisher_p"] < 1e-6
    assert result["correlation"]["hits_vs_symmetry_tell_share"]["rho"] > 0.9


def test_a_detector_that_fires_at_random_shows_no_association(tmp_path):
    """THE test. A predictor firing at the real detector's rate but on the wrong
    conversations must be called null. If this passes with a positive verdict, the
    grader is measuring the base rate and not agreement."""
    rnd = random.Random(4)
    plan = []
    for _ in range(120):
        labelled = rnd.random() < 0.78  # the corpus's real base rate
        fires = rnd.random() < 0.49  # the corpus's real fire rate, independent of the label
        plan.append((1 if fires else 0, 2, labelled))
    result = csa.validate_against_judge_tells(_payload(tmp_path, plan))
    det = result["detector"]
    assert det["p_label_given_fires"] > 0.6, "sanity: precision is still high because the base rate is high"
    assert det["fisher_p"] > 0.05, f"random firing must not read as agreement (p={det['fisher_p']})"
    assert abs(det["phi"]) < 0.2
    lo, hi = result["correlation"]["hits_vs_symmetry_tell_share"]["ci95"]
    assert lo < 0 < hi, f"a null correlation's interval must contain zero, got [{lo}, {hi}]"


def test_firing_more_without_firing_better_does_not_improve_the_verdict(tmp_path):
    """Item 4 in one assertion: recall bought by flagging everything is not correctness.
    A detector that fires on every conversation has perfect recall and zero phi."""
    plan = [(1, 1, True)] * 40 + [(1, 1, False)] * 40
    result = csa.validate_against_judge_tells(_payload(tmp_path, plan))
    det = result["detector"]
    assert det["recall"] == 1.0, "fires everywhere, so recall is perfect"
    assert det["fire_rate"] == 1.0
    assert det["phi"] is None or abs(det["phi"]) < 1e-9, "…and it has learnt nothing"
    assert det["p_label_given_silent"] is None, "no silent arm exists to compare against"


def test_unjudged_conversations_are_dropped_not_counted_as_negatives(tmp_path):
    """A conversation the panel never scored is absence of a label (ADR-104). Counting
    it as 'no symmetry tell' would inflate every specificity number here."""
    payload = _payload(tmp_path, [(1, 1, True)] * 15 + [(0, 2, False)] * 15)
    payload["metrics"].append(csa.conversation_metrics(_convo("never-judged", [_SYMMETRIC] * 3)))
    result = csa.validate_against_judge_tells(payload)
    assert result["n_conversations_joined"] == 30


def test_the_thin_join_still_refuses_a_verdict(tmp_path):
    result = csa.validate_against_judge_tells(_payload(tmp_path, [(1, 1, True)] * 3))
    assert result["verdict"] is None and "correlation" not in result


def test_the_replay_validation_path_is_wired_and_needs_a_judged_run(tmp_path):
    """`--validate-symmetry` is the $0 reproduction route; an unjudged file must say
    so rather than return an empty perfect score."""
    replay = _load("coach_sim_replay")
    convos = csa.load_runs(_corpus(tmp_path, [_convo("s0", [_SYMMETRIC])]))
    unjudged = tmp_path / "metrics.json"
    unjudged.write_text(json.dumps({"metrics": []}))
    with pytest.raises(SystemExit, match="no `panel` block"):
        replay.validate_symmetry(convos, str(unjudged))
