"""tests/test_farmers_walk_carry_5372.py — the farmers walk logged under Hevy's standard template counts as the programmed carry (#5372).

Before: the charter/drafter programmed the never-logged custom 'Farmers Carry' template (`farmers_carry`, ce871c4e…) while the owner logs
Hevy's standard 'Farmers Walk' (`farmers_walk`, 50C613D0), so adherence read `farmers_carry: performed 0 / unreadable, missing` plus an
`extra` 50C613D0, and the coach packet's session rows dropped the set's distance. The regression fixture is the WIRE
(`fixtures/hevy_farmers_walk_wire_5372.json`, synthetic values in the live payload's shape), normalised through the real
`hevy_common.normalize_workout`.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")  # mcp.config requires these at import
os.environ.setdefault("USER_ID", "matthew")

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from health.adherence_calc import calculate_adherence  # noqa: E402
from training import hevy_common, intensity_prescription, program_structure  # noqa: E402
from training.carry_line import carry_line  # noqa: E402
from training.muscle_volume import normalize_hevy_items  # noqa: E402
from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402

from mcp import tools_hevy  # noqa: E402

WIRE = json.loads((REPO / "tests" / "fixtures" / "hevy_farmers_walk_wire_5372.json").read_text())
WALK_TID = "50C613D0"


def _ir(carry_key: str = "farmers_walk") -> RoutineSpec:
    """The shoulders+arms routine as compiled: 3 lateral raises and the carry at its 2 prescribed sets."""
    steps = program_structure.CARRY_EXPOSURE["carry_steps"]
    return RoutineSpec(
        routine_id="r-5372",
        target_date="2026-10-25",
        archetype="upper",
        exercises=[
            ExerciseBlock(movement_key="db_lateral_raise", sets=[Set(rep_range_start=8, rep_range_end=12) for _ in range(3)]),
            ExerciseBlock(movement_key=carry_key, sets=[Set(distance_meters=steps) for _ in range(2)]),
        ],
    )


def _carry(result: dict, key: str) -> dict:
    return next(m for m in result["movements"] if m["movement_key"] == key)


def test_the_carry_logged_under_the_standard_template_is_performed_three_against_two():
    result = calculate_adherence(_ir(), WIRE)
    carry = _carry(result, "farmers_walk")
    assert (carry["programmed_sets"], carry["performed_sets"], carry["programmed_working_sets"], carry["performed_working_sets"]) == (
        2,
        3,
        2,
        3,
    )
    assert carry["pct"] == 100.0
    assert "farmers_walk" not in result["missing"] and result["missing"] == []  # not missing
    assert WALK_TID not in result["extra"] and result["extra"] == []  # not extra


def test_a_reps_less_carry_is_never_called_unreadable():
    """Hevy has no RPE field on a distance set, so 'no RPE' on a carry is `rpe_absent` — named honestly, still outside the denominator."""
    intensity = _carry(calculate_adherence(_ir(), WIRE), "farmers_walk")["intensity"]
    assert intensity["status"] == "rpe_absent" and intensity["pct_within_ceiling"] is None
    assert intensity["working_sets"] == 3 and intensity["sets_rpe_absent"] == 3 and intensity["sets_graded"] == 0
    assert intensity["status"] != "unreadable"


def test_the_rpe_absent_name_is_only_for_reps_less_sets():
    """The control: reps-bearing working sets with no RPE stay `unreadable`; zero sets performed stays `unreadable`."""
    lifted = [{"type": "normal", "reps": 8, "weight_kg": 50.0}] * 2
    assert intensity_prescription.grade_sets(8.0, lifted)["status"] == "unreadable"
    assert intensity_prescription.grade_sets(8.0, [])["status"] == "unreadable"
    carried = [{"type": "normal", "reps": None, "distance_meters": 60, "weight_kg": 40.0}]
    assert intensity_prescription.grade_sets(8.0, carried)["status"] == "rpe_absent"
    with_rpe = [{"type": "normal", "reps": None, "distance_meters": 60, "rpe": 7.0}]
    assert intensity_prescription.grade_sets(8.0, with_rpe)["status"] == "graded"


def test_a_stored_routine_naming_the_retired_key_reads_the_walk_as_performed():
    """A routine pushed before the retirement keeps `farmers_carry` in its stored IR; the next performed carry session grades against it."""
    result = calculate_adherence(_ir("farmers_carry"), WIRE)
    carry = _carry(result, "farmers_carry")
    assert (carry["programmed_sets"], carry["performed_sets"]) == (2, 3) and result["missing"] == [] and result["extra"] == []


def test_the_control_the_pre_fix_catalog_reads_the_walk_as_missing_plus_extra(monkeypatch):
    """The control: restore the custom 'Farmers Carry' entry and drop the retirement map — the 2026-10-25 read comes back
    (`farmers_carry` missing with 0 performed, the real 50C613D0 listed extra)."""
    from health import adherence_calc

    catalog = json.loads(json.dumps(adherence_calc._load_catalog()))
    catalog["movements"]["farmers_carry"] = {"title": "Farmers Carry", "hevy_template_id_hint": "ce871c4e-6071-4523-bc2a-333e29f58114"}
    monkeypatch.setattr(adherence_calc, "_load_catalog", lambda: catalog)
    monkeypatch.setattr(adherence_calc, "canonical_key", lambda k: k)
    result = calculate_adherence(_ir("farmers_carry"), WIRE)
    assert _carry(result, "farmers_carry")["performed_sets"] == 0
    assert result["missing"] == ["farmers_carry"] and result["extra"] == [WALK_TID]


# ── box 4: load and steps on their own line, never weight x distance ────────────────────────────────────
def _stored() -> dict:
    return hevy_common.normalize_workout(WIRE)


def test_the_carry_has_its_own_line_of_load_and_steps_and_no_weight_times_distance():
    row = _stored()
    ex = next(e for e in row["exercises"] if e["name"] == "Farmers Walk")
    line = carry_line(ex["name"], ex["sets"], day="2026-10-25")
    assert line["sets"] == 3 and line["steps"] == [60, 62, 58] and line["steps_total"] == 180
    assert line["load_lb"] == [88.2, 88.2, 88.2]  # 40 kg as logged, in lb
    assert line["excluded_from_rep_tonnage"] is True and "step count" in line["steps_basis"]
    assert not any("tonnage" in k and "carry" in k for k in line) and "load_x_distance" not in line
    assert (
        carry_line(
            "Lateral Raise (Dumbbell)", next(e for e in row["exercises"] if e["name"].startswith("Lateral"))["sets"], day="2026-10-25"
        )
        is None
    )


def test_a_timed_cardio_block_is_not_a_carry():
    treadmill = [{"type": "normal", "reps": None, "weight_kg": None, "distance_m": 2400, "duration_sec": 1200}]
    assert carry_line("Treadmill", treadmill, day="2026-10-25") is None


def test_the_stored_total_volume_excludes_the_carry():
    row = _stored()
    raiser = [e for e in row["exercises"] if e["name"].startswith("Lateral")][0]
    assert row["total_volume_kg"] == round(sum(s["weight_kg"] * s["reps"] for s in raiser["sets"]), 2)  # the raise only, 10 kg x (12+11+10)


def test_get_workout_detail_reports_the_carry_line_and_keeps_the_sets_with_their_distance():
    row = {**_stored(), "workout_uid": "hevy:" + WIRE["id"]}
    detail = tools_hevy._slim_workout(row, include_sets=True)
    assert [c["name"] for c in detail["carries"]] == ["Farmers Walk"] and detail["carries"][0]["template_id"] == WALK_TID
    assert detail["carries"][0]["steps"] == [60, 62, 58]
    walk = next(e for e in detail["exercises"] if e["name"] == "Farmers Walk")
    assert [s["distance_m"] for s in walk["sets"]] == [60, 62, 58] and all(s["reps"] is None for s in walk["sets"])
    assert tools_hevy._slim_workout(row)["total_volume_kg"] == row["total_volume_kg"] and "carries" not in tools_hevy._slim_workout(row)


def test_the_coach_packet_session_rows_keep_the_carry_steps_and_never_call_them_metres():
    norm = normalize_hevy_items([{**_stored(), "sk": "DATE#2026-10-25#WORKOUT#" + WIRE["id"]}])[0]
    walk = next(e for e in norm["exercises"] if e["name"] == "Farmers Walk")
    assert walk["carry"]["steps"] == [60, 62, 58] and walk["carry"]["load_lb"] == [88.2, 88.2, 88.2]
    assert [s["steps"] for s in walk["sets"]] == [60.0, 62.0, 58.0]
    assert all("distance_m" not in s for s in walk["sets"])  # a step count is not a distance
    raiser = next(e for e in norm["exercises"] if e["name"].startswith("Lateral"))
    assert "carry" not in raiser and all("steps" not in s and "distance_m" not in s for s in raiser["sets"])
    assert sum(s["weight_lbs"] * s["reps"] for s in walk["sets"]) == 0  # the rep-tonnage sum (mcp/tools_training) counts nothing for it


def test_a_cardio_blocks_distance_and_time_now_survive_normalisation_as_distance():
    treadmill = {
        "sk": "DATE#2026-10-25#WORKOUT#x",
        "date": "2026-10-25",
        "title": "t",
        "exercises": [{"name": "Treadmill", "sets": [{"type": "normal", "reps": None, "distance_m": 2400, "duration_sec": 1200}]}],
    }
    st = normalize_hevy_items([treadmill])[0]["exercises"][0]["sets"][0]
    assert st["distance_m"] == 2400.0 and st["duration_sec"] == 1200.0 and "steps" not in st
