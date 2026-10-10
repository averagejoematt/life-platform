"""#4704 — a hand-edited habit_registry field stored as a string must not crash the day grade.

On 2026-10-04 two registry entries stored `target_frequency` as the DynamoDB string
"7"/"5". `score_habits_registry` compared it with an int and raised, so every
daily-metrics-compute run from 2026-10-05 died before the day grade and the badge sweep.
"""

from decimal import Decimal

import pytest
from health import scoring_engine as se


def _data(done: dict[str, int]) -> dict:
    return {
        "date": "2026-10-06",  # a Tuesday
        "habitify": {"habits": done},
        "habitify_7d": [{"habits": done} for _ in range(6)],
    }


def _registry(**fields) -> dict:
    return {
        "Meditate": {"status": "active", "tier": 0},
        "Psyllium": {"status": "active", "tier": 2, **fields},
    }


def _score(registry: dict, done: dict[str, int]):
    return se.score_habits_registry(_data(done), {"habit_registry": registry})


@pytest.mark.parametrize("stored", ["7", Decimal("7"), 7, 7.0])
def test_target_frequency_reads_as_its_number_however_it_was_stored(stored):
    want = _score(_registry(target_frequency=7), {"Meditate": 1, "Psyllium": 1})
    got = _score(_registry(target_frequency=stored), {"Meditate": 1, "Psyllium": 1})
    assert got[0] == want[0]
    assert "registry_type_drift" not in got[1]


def test_the_live_specimen_does_not_raise_and_scores_the_week_against_five():
    score, details = _score(_registry(target_frequency="5"), {"Meditate": 1, "Psyllium": 1})
    # 7 of 7 days done against a target of 5 caps at 100; the T0 habit is done → 100.
    assert score == 100
    assert details["composite_method"] == "tier_weighted"


def test_a_non_numeric_value_falls_back_to_the_default_and_is_named():
    score, details = _score(_registry(target_frequency="weekly", scoring_weight="heavy"), {"Meditate": 1, "Psyllium": 0})
    assert score is not None
    assert details["registry_type_drift"] == ["Psyllium.scoring_weight", "Psyllium.target_frequency"]


@pytest.mark.parametrize("tier", ["0", Decimal("0"), 0])
def test_a_string_or_decimal_tier_is_still_tier_zero(tier):
    registry = {"Meditate": {"status": "active", "tier": tier}}
    _, details = _score(registry, {"Meditate": 0})
    assert details["tier0"] == {"done": 0, "total": 1}


def test_a_boolean_is_not_a_number_here():
    _, details = _score(_registry(target_frequency=True), {"Meditate": 1, "Psyllium": 1})
    assert details["registry_type_drift"] == ["Psyllium.target_frequency"]
