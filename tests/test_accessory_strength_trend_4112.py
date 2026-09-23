"""tests/test_accessory_strength_trend_4112.py — the accessory half of the two-tier trend split.

Owner ruling, 2026-09-23 ~06:00 PT: "B but more emphasis on A as a benchmark, B more
ancillary tracked." The four core anchors (bench, row, squat, hinge) stay the benchmark
(`_worst_anchor`, `anchor_lift_strength_drop`, unchanged by this issue — held by
test_exercise_identity_4069.py and test_anchor_e1rm_not_before_week_4098.py). This file holds
the OTHER half: `training.accessory_strength_trend`, the block every other drafted lift's
e1RM trend is tracked and reported in, and the critic-side tier gate is held in
test_anchor_e1rm_not_before_week_4098.py::test_the_critic_never_escalates_an_accessory_drop_4112
and test_plan_critics_3752.py::test_an_accessory_drop_never_reaches_the_muscle_defense_verdict_4112.
"""

from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))

from training import accessory_strength_trend as ast  # noqa: E402

_CORE_ROW = {
    "idx": 0,
    "label": "Squat (Barbell)",
    "anchor_family": "squat",
    "n_sessions": 6,
    "drop_pct": 12.0,
    "sessions_below": 2,
}
_ACCESSORY_ROW = {
    "idx": 1,
    "label": "Leg Extension (Machine)",
    "identity": "9237BAD1",
    "n_sessions": 6,
    "n_sessions_e1rm": 6,
    "drop_pct": 3.0,
    "sessions_below": 0,
    "recent_median_e1rm_lb": 105.0,
    "baseline_median_e1rm_lb": 108.0,
    "last_top_lbs": 100.0,
}
_ACCESSORY_ROW_INSUFFICIENT = {
    "idx": 2,
    "label": "Cable Row",
    "n_sessions": 3,
    "n_sessions_e1rm": 3,
    "insufficient": "3 session(s) — the rolling 3-session median against the 6-session baseline needs 9",
}
_NO_HISTORY_ROW = {"idx": 3, "label": "Custom Movement"}  # `_anchor_trend` returned {} — no `n_sessions` key at all


def test_core_anchor_rows_are_excluded():
    """MUTATION CONTROL: drop the `not e.get("anchor_family")` filter and this reds — the core
    row would leak into the tracked-only accessory tier, which is exactly what a tier split
    exists to prevent."""
    block = ast.build([_CORE_ROW, _ACCESSORY_ROW])
    labels = [x["label"] for x in block["lifts"]]
    assert "Squat (Barbell)" not in labels
    assert "Leg Extension (Machine)" in labels


def test_a_row_with_no_resolvable_history_is_left_out_not_padded():
    block = ast.build([_ACCESSORY_ROW, _NO_HISTORY_ROW])
    assert len(block["lifts"]) == 1
    assert block["lifts"][0]["label"] == "Leg Extension (Machine)"


def test_an_insufficient_accessory_trend_is_still_tracked():
    """Tracked means reported, not just the drops — an accessory with too few sessions for a
    rolling median still appears, carrying `insufficient` rather than a `drop_pct`."""
    block = ast.build([_ACCESSORY_ROW_INSUFFICIENT])
    assert block["state"] == "tracked"
    row = block["lifts"][0]
    assert row["drop_pct"] is None and row["insufficient"]


def test_state_is_explicit_when_nothing_to_track():
    block = ast.build([_CORE_ROW, _NO_HISTORY_ROW])
    assert block["lifts"] == [] and block["state"] == "no_accessory_trend_data"


def test_no_evidence_reads_the_same_empty_state_never_raises():
    assert ast.build(None) == ast.build([])


def test_the_note_names_the_owner_ruling_and_never_a_change_or_veto():
    block = ast.build([_ACCESSORY_ROW])
    assert "#4112" in block["note"]
    assert "never" in block["note"] and "change" in block["note"] and "veto" in block["note"]


def test_attach_mutates_the_block_in_place_keyed_accessory_strength_trend():
    """The stable block name the weekly report (#4111) is told to read (#4112's coordination note)."""
    block: dict = {"date": "2026-09-24"}
    ast.attach(block, {"exercises": [_CORE_ROW, _ACCESSORY_ROW]})
    assert "accessory_strength_trend" in block
    assert [x["label"] for x in block["accessory_strength_trend"]["lifts"]] == ["Leg Extension (Machine)"]


def test_attach_with_no_evidence_still_sets_the_key():
    block: dict = {}
    ast.attach(block, None)
    assert block["accessory_strength_trend"]["state"] == "no_accessory_trend_data"
