"""#5232 - a string-typed habit tier must not crash the daily brief's AI sections.

2026-10-20: two registry rows stored `tier` as a string; `meta.get("tier", 2) > 1` raised
in the TL;DR+Guidance and BoD context builders. The registry is coerced once at the profile
read boundary and every tier comparison goes through `habit_tier`.
"""

from decimal import Decimal

import pytest
from ai import ai_calls, ai_context
from common.habit_registry import coerce_profile, coerce_registry, habit_tier
from health import habit_streaks

REGISTRY = {
    "Meditate": {"status": "active", "tier": "0", "why_matthew": "calm"},
    "Stretch": {"status": "active", "tier": "1", "why_matthew": "mobility"},
    "Read": {"status": "active", "tier": Decimal("2")},
    "Odd": {"status": "active", "tier": "weekly"},
}
HABITIFY = {"sk": "DATE#2026-10-19", "habits": {"Meditate": 0, "Stretch": 0, "Read": 0, "Odd": 0}}


@pytest.mark.parametrize("raw,want", [("0", 0), ("1", 1), (Decimal("2"), 2), (1.0, 1), (True, 2), ("weekly", 2), (None, 2)])
def test_habit_tier_reads_as_an_int(raw, want):
    assert habit_tier({"tier": raw}) == want


def test_coerce_registry_types_the_numeric_fields_and_copies():
    reg = {"A": {"tier": "1", "scoring_weight": "2", "target_frequency": "5"}}
    out = coerce_registry(reg)
    assert out["A"] == {"tier": 1, "scoring_weight": 2, "target_frequency": 5}
    assert reg["A"]["tier"] == "1"
    assert coerce_profile({"habit_registry": reg})["habit_registry"]["A"]["tier"] == 1


def test_tldr_missed_habit_filter_does_not_raise_on_string_tiers():
    missed = ai_calls._missed_registry_habits(REGISTRY, HABITIFY)
    kept = [n for n, meta in missed if habit_tier(meta) <= 1]
    assert kept == ["Meditate", "Stretch"]


class _ModelReached(Exception):
    """Raised by the stubbed model call: the context builder ran to the call without a TypeError."""


def _stub(monkeypatch, prompts):
    def boom(*a, **k):
        prompts.append(repr((a, k)))
        raise _ModelReached

    monkeypatch.setattr(ai_calls, "call_anthropic", boom)
    monkeypatch.setattr(ai_calls, "_ic3_send", boom)  # no live model call, ever


def test_board_of_directors_context_builds_with_string_tiers(monkeypatch):
    prompts = []
    _stub(monkeypatch, prompts)
    data = {"habitify": HABITIFY, "date": "2026-10-19"}
    with pytest.raises(_ModelReached):
        ai_calls.call_board_of_directors(data, {"habit_registry": REGISTRY}, None, "B", {}, api_key="x")
    # a string tier left uncoerced misclassifies under `==` (no raise): the prompt must still carry T0/T1 misses
    text = " ".join(prompts)
    assert "Meditate" in text and "Stretch" in text


def test_tldr_context_builds_with_string_tiers(monkeypatch, capsys):
    _stub(monkeypatch, [])
    data = {"habitify": HABITIFY, "date": "2026-10-19"}
    try:
        ai_calls.call_tldr_and_guidance(data, {"habit_registry": REGISTRY}, None, "B", {}, {}, 70, "green", "x")
    except _ModelReached:
        pass
    out = capsys.readouterr().out
    # the section swallows errors into a "TL;DR+Guidance failed: <err>" line; a TypeError on the
    # tier compare would read "'>' not supported between instances of 'str' and 'int'"
    assert "not supported between" not in out
    assert "TypeError" not in out


def test_outcome_context_and_streaks_read_string_tiers():
    ctx = ai_context._build_habit_outcome_context({"habitify_7d": [HABITIFY]}, {"habit_registry": REGISTRY})
    assert "T0" in ctx
    assert habit_streaks.habit_tier is habit_tier


def test_the_read_boundary_leaves_a_non_number_raw_so_the_4704_drift_report_still_names_it():
    """Review hold on #5232: coercing a bool/garbage value to the default at fetch_profile silenced
    `registry_type_drift` on the live path. Only a value that parses as a number is converted."""
    from common.habit_registry import coerce_profile
    from health import scoring_engine as se

    registry = {
        "Meditate": {"status": "active", "tier": "0"},
        "B": {"status": "active", "tier": "2", "target_frequency": "weekly", "scoring_weight": True},
    }
    profile = coerce_profile({"habit_registry": registry})
    assert profile["habit_registry"]["B"]["tier"] == 2  # a numeric string still becomes a number
    assert profile["habit_registry"]["Meditate"]["tier"] == 0
    data = {"date": "2026-10-06", "habitify": {"habits": {"Meditate": 1, "B": 1}}, "habitify_7d": [{"habits": {"Meditate": 1, "B": 1}}] * 6}
    _, details = se.score_habits_registry(data, profile)
    assert details["registry_type_drift"] == ["B.scoring_weight", "B.target_frequency"]
