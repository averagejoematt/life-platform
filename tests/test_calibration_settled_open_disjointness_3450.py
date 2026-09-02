"""tests/test_calibration_settled_open_disjointness_3450.py — #3450.

Two calibration honesty gaps in one issue, verifier-confirmed by the Session S
calculation-proof pass:

  1. `calibration_core.score_pairs` served a bare `accuracy_pct` with no
     uncertainty interval — a hit rate off a small n reads as more precise than
     it is (21.6% and "somewhere between 11% and 37%" are different decisions).
     Covered by `test_calibration_accuracy_never_ships_without_interval_3450`
     below and by the vector-file parity suite (`test_calibration_core_parity.py`).

  2. `calibration_core._TRUE_OUTCOMES` counted the status word "confirming" as
     settled-TRUE, while EVERY OTHER reader of this exact vocabulary —
     `coach_prediction_evaluator.EVALUABLE_STATUSES`,
     `coach_nudge_lambda.PREDICTION_EVALUABLE_STATUSES`,
     `coach_domain_facts._OPEN_PREDICTION_STATUSES`,
     `phase_taxonomy.OPEN_BET_STATUSES` — treats "confirming" as still OPEN (the
     hypothesis engine writes it as an in-progress state, one step before
     "confirmed"). That's the #2219 shape again: one settled-set, one open-set,
     one word claimed by both. Verified strictly latent (0 live rows carry the
     status today — CALIB# is written at resolution, PREDICTION# statuses never
     include it), but the summarizer's own prompt vocabulary offers the word,
     so the divergence was one prompt drift from a real double-count.

This module is the structural guard the issue asks for: it holds the actual
open-status registries (not a hand-typed guess) disjoint from calibration_core's
settled sets, so a future writer cannot silently re-form the class by adding
"confirming" (or any other still-open word) back into a settled set, or by
adding a new settled outcome to any of the open registries.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from coach import coach_domain_facts, coach_prediction_evaluator  # noqa: E402
from emails import coach_nudge_lambda  # noqa: E402
from experiment import calibration_core, phase_taxonomy  # noqa: E402

# The platform's own open-status registries — the still-open half of the
# settled/open pair. Sourced by name, not retyped, so this test tracks whatever
# the real writers actually declare.
OPEN_REGISTRIES = {
    "coach_prediction_evaluator.EVALUABLE_STATUSES": coach_prediction_evaluator.EVALUABLE_STATUSES,
    "coach_nudge_lambda.PREDICTION_EVALUABLE_STATUSES": coach_nudge_lambda.PREDICTION_EVALUABLE_STATUSES,
    "coach_domain_facts._OPEN_PREDICTION_STATUSES": set(coach_domain_facts._OPEN_PREDICTION_STATUSES),
    "phase_taxonomy.OPEN_BET_STATUSES": set(phase_taxonomy.OPEN_BET_STATUSES),
}

SETTLED = set(calibration_core._TRUE_OUTCOMES) | set(calibration_core._FALSE_OUTCOMES)


def test_settled_outcomes_are_internally_disjoint():
    """A word cannot itself be both the settled-true and settled-false grade."""
    overlap = set(calibration_core._TRUE_OUTCOMES) & set(calibration_core._FALSE_OUTCOMES)
    assert overlap == set(), f"a status cannot be both settled-true and settled-false: {overlap}"


def test_settled_set_is_disjoint_from_every_open_registry():
    """The #3450 class: no status token may count as both settled and still-open.

    This is the guard, not a hunt for affected rows — it holds calibration_core's
    settled vocabulary against every registry on the platform that names the
    still-open half of the same vocabulary, and fails loud the moment either
    side claims a word the other already owns.
    """
    for name, open_set in OPEN_REGISTRIES.items():
        overlap = SETTLED & open_set
        assert overlap == set(), (
            f"{name} and calibration_core's settled set both claim {overlap} — "
            "a status cannot be simultaneously settled (scored as a decided "
            "outcome) and still-open (excluded from grading, evaluable later)"
        )


def test_confirming_is_not_settled():
    """Regression pin for the specific word #3450 found: 'confirming' is open."""
    assert "confirming" not in calibration_core._TRUE_OUTCOMES
    assert "confirming" not in calibration_core._FALSE_OUTCOMES
    assert calibration_core.outcome_to_binary("confirming") is None
    for name, open_set in OPEN_REGISTRIES.items():
        assert "confirming" in open_set, f"{name} was expected to still carry 'confirming' as open"


def test_calibration_open_outcomes_constant_matches_the_real_registries():
    """`calibration_core.OPEN_OUTCOMES` names the vocabulary this module must never
    settle. It should be a superset of every live open registry so the
    disjointness check above is against the real vocabulary, not a stale list."""
    live_open = set()
    for open_set in OPEN_REGISTRIES.values():
        live_open |= open_set
    assert live_open.issubset(
        calibration_core.OPEN_OUTCOMES
    ), f"calibration_core.OPEN_OUTCOMES is missing live open statuses: {live_open - calibration_core.OPEN_OUTCOMES}"
