"""tests/test_block_model_5077.py — the block mesocycle model (#5077, owner ruling 2026-10-18: no scheduled deload).

A block is the charter's `rotation.anchors_fixed_weeks`; inside it the priority muscles' working sets ramp
from the MEV side to the MAV side (+1 set every 2 weeks, accessories first); the next block is modelled; a
deload exists only on the owner's DELOAD# record (C3, #5070). Pure — no clock, no network: every week is
given, every record is a literal.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "lambdas")):
    if p not in sys.path:
        sys.path.insert(0, p)

from training import block_model, plan_engine  # noqa: E402
from training.training_charter import charter_value, charter_version  # noqa: E402

LANDMARKS = json.loads((ROOT / "config" / "training_landmarks.json").read_text(encoding="utf-8"))["muscles"]
N = int(charter_value("rotation.anchors_fixed_weeks"))
FIRST_MONDAY = "2026-11-02"


def _record(start: str, words: str = "deload this week", sets_pct: int = -40, days: int = 7) -> dict:
    return {"start_date": start, "days": days, "sets_pct": sets_pct, "words": words, "loads": "held"}


def _sets(week: dict) -> dict[str, int]:
    return {m: v["sets"] for m, v in week["sets_by_muscle_target"].items()}


def test_a_block_is_the_charters_anchor_span_and_the_sequence_reads_it():
    from training import program_structure, session_sequence

    assert block_model.block_weeks() == N
    assert session_sequence._seq()["weeks_per_block"] == N
    assert "weeks_per_block" not in program_structure.SESSION_SEQUENCE
    assert "block_weeks" not in program_structure.ROTATION_RULE


def test_thirteen_weeks_ramp_within_each_block_model_the_next_and_never_deload():
    weeks = block_model.project(13, landmarks=LANDMARKS, first_week_start=FIRST_MONDAY)
    assert [w["block"] for w in weeks] == [1] * N + [2] * N + [3] * (13 - 2 * N)
    assert [w["week_in_block"] for w in weeks] == list(range(1, N + 1)) * 2 + list(range(1, 13 - 2 * N + 1))
    # no deload week anywhere, with no owner record
    assert not any(w["deload"]["applied"] for w in weeks)
    assert all(w["deload"]["sets_pct"] is None for w in weeks)
    plan = block_model.muscle_plan(LANDMARKS)
    priority = [m for m, r in plan.items() if r["priority"]]
    held = [m for m, r in plan.items() if not r["priority"]]
    assert {"shoulders"} <= set(priority)
    assert {"quadriceps", "hamstrings", "glutes"} <= set(held), "legs are the charter's maintenance posture"
    # #5162 (owner ruling 2026-10-23): the lats / upper-chest / arms bands were lowered to what fits inside the 75-set week
    # (a one-number band), so those muscles hold at their band start and never ramp — no room to climb into
    assert {"back", "chest", "biceps", "triceps"} <= set(held)
    for m in priority:
        series = [_sets(w)[m] for w in weeks]
        for b in range(2):
            blk = series[b * N : (b + 1) * N]
            assert blk == sorted(blk), (m, b, blk)  # volume only climbs inside a block
            steps = [blk[i] - blk[i - 1] for i in range(1, N)]
            assert all(s in (0, block_model.SETS_PER_STEP) for s in steps), (m, steps)
            assert blk[-1] > blk[0], (m, "the priority muscle never ramped")
        # the next block starts on a NEW MEV side: above block 1's start, below block 1's top
        assert series[0] < series[N] <= series[N - 1], (m, series)
        # the preview IS the next block's week 1
        assert weeks[0]["next_block_preview"]["sets_by_muscle_start"][m] == series[N]
        assert weeks[N]["next_block_preview"]["sets_by_muscle_start"][m] == series[2 * N]
    for m in held:
        assert len({_sets(w)[m] for w in weeks}) == 1, (m, "a maintenance muscle holds")
    assert [w["ramp_stage"] for w in weeks[:N]][0] == "MEV-side" and weeks[N - 1]["ramp_stage"] == "MAV-side"
    assert all(w["charter_version"] == charter_version() for w in weeks)


def test_the_landmark_and_charter_bounds_are_never_exceeded_over_a_long_run():
    """Twenty blocks: the start creeps up one set per block and must stop at the cap, never past MRV or the band."""
    for w in block_model.project(N * 20, landmarks=LANDMARKS):
        for m, t in w["sets_by_muscle_target"].items():
            lm = t["landmarks"]
            assert lm["MEV"] <= t["sets"] <= lm["MRV"], (w["program_week"], m, t)
            assert t["band"][0] <= t["sets"] <= t["band"][1], (w["program_week"], m, t)


def test_the_owner_record_week_is_cut_and_the_ramp_resumes():
    rec = _record("2026-12-23")  # the 8th week from FIRST_MONDAY opens 12-21; a mid-week start still covers it
    plain = block_model.project(10, landmarks=LANDMARKS, first_week_start=FIRST_MONDAY)
    cut = block_model.project(10, landmarks=LANDMARKS, first_week_start=FIRST_MONDAY, deload_records=[rec])
    applied = [w["program_week"] for w in cut if w["deload"]["applied"]]
    assert applied == [8, 9], "a 7-day window starting mid-week overlaps two program weeks"
    for i, w in enumerate(cut):
        if w["deload"]["applied"]:
            assert w["deload"]["sets_pct"] == -40 and w["deload"]["record_start"] == "2026-12-23"
            for m, t in w["sets_by_muscle_target"].items():
                assert t["sets"] == round(plain[i]["sets_by_muscle_target"][m]["sets"] * 0.6), m
                assert t["ramp_sets"] == plain[i]["sets_by_muscle_target"][m]["sets"]
        else:
            assert _sets(w) == _sets(plain[i]), w["program_week"]  # before and after: the ramp as if untouched
    # a week-aligned record cuts exactly that week
    one = block_model.project(10, landmarks=LANDMARKS, first_week_start=FIRST_MONDAY, deload_records=[_record("2026-12-21")])
    assert [w["program_week"] for w in one if w["deload"]["applied"]] == [8]


def test_a_recommendation_alone_never_cuts_a_week():
    w = block_model.week_plan(5, landmarks=LANDMARKS, week_start=FIRST_MONDAY, deload_records=[], recommended=True)
    assert w["deload"] == {**w["deload"], "recommended": True, "applied": False, "sets_pct": None}
    assert _sets(w) == _sets(block_model.week_plan(5, landmarks=LANDMARKS))


def test_every_charter_priority_group_is_mapped_to_a_landmark_muscle():
    bands = charter_value("volume_priorities.sets_per_wk")
    assert set(bands) <= set(block_model.GROUP_MUSCLES), set(bands) - set(block_model.GROUP_MUSCLES)
    assert all(m in LANDMARKS for ms in block_model.GROUP_MUSCLES.values() for m in ms)
    assert block_model.week_plan(1, landmarks=LANDMARKS)["unmapped_groups"] == []


def test_an_unknown_week_or_unreadable_landmarks_is_a_stated_state():
    assert block_model.for_session({"week": None})["state"] == "week_unknown"
    with patch.object(block_model, "load_landmarks", return_value=None):
        assert block_model.for_session({"week": 3})["state"] == "landmarks_unreadable"
    with pytest.raises(ValueError):
        block_model.week_plan(0, landmarks=LANDMARKS)


def test_the_constraint_block_and_the_served_session_carry_the_model():
    b = plan_engine.constraint_block(date="2026-10-20", block_workouts=[], deload_records=[])
    bm = b["block_model"]
    assert bm["state"] == "modelled" and bm is b["session"]["block_model"]
    assert (bm["block"], bm["week_in_block"]) == (b["session"]["block"], 1)
    assert bm["deload"]["recommended"] is b["deload_recommendation"]["active"] and bm["deload"]["applied"] is False
    assert bm["charter_version"] == b["charter_version"]


def test_the_predraft_carries_the_block_model_on_its_session():
    from mcp import nightly_predraft as npd

    served = {"label": "walk", "archetype": "aerobic", "block_model": {"state": "modelled", "block": 2}}
    with (
        patch.object(npd, "scheduled_session", return_value=served),
        patch.object(npd, "sweep_expired", return_value={}),
        patch.dict(os.environ, {"EMAIL_RECIPIENT": "x@example.com"}),
    ):
        out = npd.run("2026-10-20")
    assert out["session"]["block_model"] == {"state": "modelled", "block": 2}


def test_the_load_entry_ramp_is_not_the_block():
    """`load_ramp` stays the re-entry ramp; the block model never reads it (loads are #5052's)."""
    src = (ROOT / "lambdas" / "training" / "block_model.py").read_text(encoding="utf-8")
    code = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#"))
    assert "import load_ramp" not in code and "load_ramp." not in code
