"""tests/test_exercise_history.py — facts + render + anti-hallucination guard.

The anti-hallucination test is the acceptance gate per the spec: every
numeric value that appears in a per-exercise note must trace back to the
underlying source workout records. Failing this test means the renderer
(or a future LLM phrasing layer) has invented something.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import exercise_history as eh
import pytest


@pytest.fixture(autouse=True)
def _reset():
    eh._reset_for_tests()
    yield
    eh._reset_for_tests()


def _sample_index() -> dict[str, list[dict]]:
    """Hand-built index that mirrors what load_recent_history would emit."""
    return {
        "3601968B": [  # db_bench_press_flat
            {
                "date": "2026-05-24",
                "sets": [{"weight_kg": 60.0, "reps": 8}, {"weight_kg": 60.0, "reps": 8}, {"weight_kg": 60.0, "reps": 7}],
                "top_weight_kg": 60.0,
            },
            {"date": "2026-05-17", "sets": [{"weight_kg": 57.5, "reps": 8}, {"weight_kg": 57.5, "reps": 8}], "top_weight_kg": 57.5},
        ],
        "6A6C31A5": [  # lat_pulldown
            {"date": "2026-05-24", "sets": [{"weight_kg": 45.0, "reps": 12}], "top_weight_kg": 45.0},
        ],
        # one-session-only lift
        "DEADBEEF": [
            {"date": "2026-05-24", "sets": [{"weight_kg": 20.0, "reps": 10}], "top_weight_kg": 20.0},
        ],
    }


def test_history_facts_extracts_last_session_top_set_only():
    facts = eh.history_facts("3601968B", _sample_index())
    assert facts["sessions_count"] == 2
    assert facts["last_top_weight_kg"] == 60.0
    assert facts["last_reps_list"] == [8, 8, 7]
    assert facts["last_date"] == "2026-05-24"


def test_history_facts_empty_for_unknown_template():
    facts = eh.history_facts("NOT_IN_INDEX", _sample_index())
    assert facts == {"sessions_count": 0}


def test_render_cue_default_format():
    facts = eh.history_facts("3601968B", _sample_index())
    cue = eh.render_history_cue(facts)
    assert cue == "Last: 60kg 8/8/7 (24 May)"


def test_render_cue_empty_for_no_history():
    cue = eh.render_history_cue({"sessions_count": 0})
    assert cue == ""


def test_render_cue_rounds_weight_to_half_kg():
    facts = {
        "sessions_count": 1,
        "last_date": "2026-05-24",
        "last_top_weight_kg": 57.49,
        "last_reps_list": [8, 8, 7],
    }
    assert eh.render_history_cue(facts) == "Last: 57.5kg 8/8/7 (24 May)"


def test_pick_note_one_best_line_prefers_history_when_no_ai():
    out = eh.pick_note("Last: 60kg 8/8/7 (24 May)", None, mode="one_best_line")
    assert out == "Last: 60kg 8/8/7 (24 May)"


def test_pick_note_one_best_line_prefers_ai_when_present():
    out = eh.pick_note("history", "Drive through the heels.", mode="one_best_line")
    assert out == "Drive through the heels."


def test_pick_note_show_both_concatenates():
    out = eh.pick_note("history", "ai", mode="show_both")
    assert "history" in out and "ai" in out


def test_pick_note_off_returns_empty():
    assert eh.pick_note("history", "ai", mode="off") == ""


# ── load_recent_history: schema-aware ingestion ──


def _ddb_item(date_iso: str, exercises: list[dict]) -> dict:
    return {
        "pk": "USER#matthew#SOURCE#hevy",
        "sk": f"DATE#{date_iso}#WORKOUT#abc",
        "date": date_iso,
        "source_workout_id": "abc",
        "exercises": exercises,
    }


def test_load_recent_history_skips_legacy_aggregates():
    """Legacy daily-aggregate records (no source_workout_id) must be ignored."""
    items = [
        {"pk": "USER#matthew#SOURCE#hevy", "sk": "DATE#2026-05-24", "workouts": [{"title": "old aggregate"}]},
        _ddb_item("2026-05-24", [{"template_id": "X", "sets": [{"weight_kg": Decimal("50"), "reps": Decimal("10")}]}]),
    ]

    class _FakeTable:
        def query(self, **_kwargs):
            return {"Items": items}

    with patch.object(eh, "_table", return_value=_FakeTable()):
        idx = eh.load_recent_history(lookback_days=30, today=date(2026, 5, 31))
    assert "X" in idx
    assert idx["X"][0]["top_weight_kg"] == 50.0


def test_load_recent_history_orders_sessions_most_recent_first():
    items = [
        _ddb_item("2026-05-10", [{"template_id": "X", "sets": [{"weight_kg": Decimal("40"), "reps": Decimal("10")}]}]),
        _ddb_item("2026-05-24", [{"template_id": "X", "sets": [{"weight_kg": Decimal("50"), "reps": Decimal("10")}]}]),
    ]

    class _FakeTable:
        def query(self, **_kwargs):
            return {"Items": items}

    with patch.object(eh, "_table", return_value=_FakeTable()):
        idx = eh.load_recent_history(lookback_days=60, today=date(2026, 5, 31))
    assert idx["X"][0]["date"] == "2026-05-24"
    assert idx["X"][1]["date"] == "2026-05-10"


def test_load_recent_history_decimals_become_floats_for_arithmetic():
    items = [
        _ddb_item("2026-05-24", [{"template_id": "X", "sets": [{"weight_kg": Decimal("57.5"), "reps": Decimal("8")}]}]),
    ]

    class _FakeTable:
        def query(self, **_kwargs):
            return {"Items": items}

    with patch.object(eh, "_table", return_value=_FakeTable()):
        idx = eh.load_recent_history(lookback_days=30, today=date(2026, 5, 31))
    set0 = idx["X"][0]["sets"][0]
    assert isinstance(set0["weight_kg"], float) and set0["weight_kg"] == 57.5
    assert isinstance(set0["reps"], int) and set0["reps"] == 8


# ── Anti-hallucination guard (acceptance gate) ──


def _numbers_in(text: str) -> set[str]:
    """Strip percent signs etc; collect bare numeric tokens."""
    return set(re.findall(r"\d+(?:\.\d+)?", text or ""))


def _ground_truth_numbers(facts: dict) -> set[str]:
    """All numbers that the renderer is permitted to quote."""
    allowed: set[str] = set()
    if facts.get("sessions_count", 0) == 0:
        return allowed
    weight = facts.get("last_top_weight_kg", 0)
    # weight may be rendered as e.g. "60" or "57.5" — allow both raw and rounded.
    allowed.add(str(int(weight))) if weight == int(weight) else None
    allowed.add(str(weight))
    allowed.add(str(round(weight * 2) / 2))
    allowed.add(str(int(round(weight * 2) / 2))) if (round(weight * 2) / 2) == int(round(weight * 2) / 2) else None
    for r in facts.get("last_reps_list") or []:
        allowed.add(str(int(r)))
    last_date = facts.get("last_date", "")
    if last_date:
        y, m, d = last_date.split("-")
        allowed.add(str(int(d)))
        allowed.add(str(int(m)))  # month number, in case it leaks
    return {a for a in allowed if a}


def test_anti_hallucination_render_quotes_only_source_numbers():
    """Every numeric token in render_history_cue's output must trace back to facts."""
    index = _sample_index()
    for template_id in index:
        facts = eh.history_facts(template_id, index)
        cue = eh.render_history_cue(facts)
        in_cue = _numbers_in(cue)
        allowed = _ground_truth_numbers(facts)
        leaked = in_cue - allowed
        assert not leaked, (
            f"Template {template_id}: numeric tokens {leaked} not in source facts. " f"Cue={cue!r}; allowed={sorted(allowed)}"
        )


def test_anti_hallucination_pick_note_does_not_inject_numbers():
    """pick_note must not inject numbers absent from its inputs."""
    history = "Last: 60kg 8/8/7 (24 May)"
    ai = "Drive through the heels and pause at the chest."
    combined = eh.pick_note(history, ai, mode="show_both")
    in_out = _numbers_in(combined)
    in_inputs = _numbers_in(history) | _numbers_in(ai)
    leaked = in_out - in_inputs
    assert not leaked, f"pick_note leaked numbers {leaked}"
