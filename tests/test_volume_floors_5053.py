"""tests/test_volume_floors_5053.py — the coverage floors (#5053).

THE INCIDENT: 2026-10-04 the Flex day was dropped; side/rear delts and core went to 0 sets and calves sat at 6/wk with no
alert (`muscle_volume` counted it; nothing compared the count with the landmark). Two halves, held here:

  * TEMPLATES — every charter MEV floor (`volume_priorities.mev_floors_in_every_template`: side/rear delts, traps, calves,
    core) has a slot in a role and meets its landmark MEV; side/rear delts sit inside the charter band; the week stays
    inside the owner's 60–75 hard-set redline and every session inside the charter's lifting-minute cap.
  * THE FLAG — `below_mev_14d` rides the coach packet and the plan packet, derived from `get_muscle_volume`'s trailing-14d
    counts (`working_sets_by_muscle`, the one computation) — and a fixture of the 2026-10-04 drop trips it on day 14, not 13.

RESIDUAL (named, shrink-only): the charter bands for lats / upper chest / arms are not reachable inside the 75-set week;
`KNOWN_BAND_GAPS` pins today's shortfall so it can only shrink — closing it is an owner call on the redline, not a template edit.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import pytest  # noqa: E402
from test_muscle_volume_working_sets_4071 import _ex, _row, tool  # noqa: E402,F401 — the wire-shaped Hevy fixtures + tool seam
from training import owner_redlines, program_structure, session_shape, volume_floors  # noqa: E402
from training.training_charter import charter_value  # noqa: E402

CATALOG = json.loads((REPO / "config" / "movement_catalog.json").read_text())["movements"]
ROLES = list(program_structure.SESSION_TEMPLATES)

# gap (sets/wk) below each charter band's floor today — may only shrink (#5053 residual; see the module docstring)
KNOWN_BAND_GAPS = {"side_rear_delts": 0, "lats": 2, "upper_chest": 6, "legs": 0, "arms": 4}


@pytest.fixture(scope="module")
def coverage():
    return program_structure.volume_floor_coverage(CATALOG)


def test_every_charter_floor_muscle_has_a_slot_and_meets_its_mev(coverage):
    floors = coverage["floors"]
    assert set(floors) == set(charter_value("volume_priorities.mev_floors_in_every_template"))
    for name, row in floors.items():
        assert row["meets_mev"], (name, row)
    assert floors["traps"]["slot_roles"] == ["shoulders_arms"]
    assert floors["calves"]["sets"] >= 8 and floors["core"]["sets"] >= 4


def test_every_floor_movement_is_in_a_role_and_in_the_pool():
    accs = {r: t["accessories"] for r, t in program_structure.SESSION_TEMPLATES.items()}
    flat = {a for v in accs.values() for a in v}
    assert {"db_lateral_raise", "face_pull", "reverse_pec_deck", "shrug_dumbbell", "calf_raise_machine", "machine_crunch"} <= flat
    pool = {k for v in program_structure.ACCESSORY_POOL.values() for k in v}
    assert flat <= pool
    # delts 3x/week, with a rear-delt slot on an upper day and the lateral raise on the aesthetic day
    assert "reverse_pec_deck" in accs["upper_heavy"] and "db_lateral_raise" in accs["shoulders_arms"]


def test_weekly_sets_by_muscle_delts_sit_in_the_charter_band():
    lo, hi = charter_value("volume_priorities.sets_per_wk.side_rear_delts")
    delts = program_structure.weekly_sets_by_muscle(CATALOG)["delts"]
    assert lo <= delts["sets"] <= hi, delts
    assert delts["frequency_per_wk"] >= charter_value("split.frequency.delts_per_wk")


def test_band_gaps_only_shrink(coverage):
    gaps = {g: r["gap_to_floor"] for g, r in coverage["bands"].items()}
    assert set(gaps) == set(KNOWN_BAND_GAPS) == set(charter_value("volume_priorities.sets_per_wk"))
    for g, gap in gaps.items():
        assert gap <= KNOWN_BAND_GAPS[g], f"{g}: gap {gap} grew past the pinned {KNOWN_BAND_GAPS[g]}"
    assert coverage["bands"]["legs"]["gap_to_floor"] == 0  # strong maintenance, 8-10
    assert all(row["band"][0] <= max(row["member_sets"]) or row["gap_to_floor"] for row in coverage["bands"].values())


def test_the_week_and_every_session_stay_inside_the_caps():
    total = sum(program_structure.session_prescription_for_role(r, catalog_movements=CATALOG)["total_sets"] for r in ROLES)
    lo, hi = owner_redlines.REDLINES["lifting_sessions_per_wk"]["total_hard_sets_wk"]
    assert lo <= total <= hi, total
    cap = charter_value("split.session_minutes.lifting")[1]
    for r in ROLES:
        rx = program_structure.session_prescription_for_role(r, catalog_movements=CATALOG)
        est = session_shape.session_minutes_estimate(rx["exposures"])
        assert est["within_cap"] and est["lifting_minutes"] <= cap, (r, est["lifting_minutes"])
        assert rx["time_trim"] is None, f"{r}: a floor accessory was trimmed for time"


def test_the_short_lower_sessions_moved_toward_the_low_end():
    mins = {
        r: session_shape.session_minutes_estimate(
            program_structure.session_prescription_for_role(r, catalog_movements=CATALOG)["exposures"]
        )["lifting_minutes"]
        for r in ROLES
    }
    assert mins["lower_heavy"] > 47.0 and mins["lower_volume"] > 41.0, mins  # the 2026-10-18 panel's estimates


# ── the flag ───────────────────────────────────────────────────────────────────
def _flex_day_rows():
    """2026-10-04, the last day with delt/core/calf work: 16 side/rear-delt sets, 8 core, 16 calf (= MEV over two weeks)."""
    return [
        _row(
            "2026-10-04",
            "flex-0001",
            [
                _ex("Lateral Raise (Dumbbell)", "LATRAISE1", 8),
                _ex("Face Pull", "FACEPULL1", 8),
                _ex("Calf Press (Machine)", "91237BDD", 16),
                _ex("Crunch (Machine)", "CRUNCH001", 8),
            ],
        )
    ]


def test_the_2026_10_04_drop_trips_the_flag_on_day_14_and_not_day_13(tool):  # noqa: F811
    read = tool(_flex_day_rows())
    day13 = read({"start_date": "2026-10-04", "end_date": "2026-10-17"})["below_mev_14d"]
    day14 = read({"start_date": "2026-10-05", "end_date": "2026-10-18"})["below_mev_14d"]
    assert day13["status"] == day14["status"] == "ok"
    for m in ("Shoulders", "Calves", "Core"):
        assert day13["muscles"][m]["below_mev"] is False, (m, day13["muscles"][m])
        assert day14["muscles"][m]["below_mev"] is True and day14["muscles"][m]["sets_per_wk"] == 0.0, m
    assert {"Shoulders", "Calves", "Core"} <= set(day14["flagged"]) and not {"Shoulders", "Calves", "Core"} & set(day13["flagged"])
    assert day14["muscles"]["Shoulders"]["mev"] == 8  # the landmark, not a copy


def test_the_flag_compares_the_one_count_with_the_landmark_and_can_fail():
    window = {
        "days": 14,
        "weeks": 2.0,
        "start": "a",
        "end": "b",
        "muscles": {"Shoulders": {"total_sets": 15.0}, "Calves": {"total_sets": 16.0}},
    }
    lm = {"shoulders": {"MEV": 8}, "calves": {"MEV": 8}}
    out = volume_floors.below_mev_14d(window, lm)
    assert out["flagged"] == ["Shoulders"] and out["muscles"]["Calves"]["below_mev"] is False  # 7.5/wk < 8; 8.0/wk is not below
    assert volume_floors.below_mev_14d(None)["status"] == "unavailable"


def test_the_coach_packet_and_the_plan_packet_carry_it(monkeypatch):
    from mcp import tools_coach_packet, tools_plan, tools_strength

    flag = {"status": "ok", "flagged": ["Core"], "muscles": {}}
    muscles = {"Chest": {"total_sets": 6.0, "direct_sets": 6, "sets_per_week": 6.0}}
    monkeypatch.setattr(
        tools_strength,
        "tool_get_muscle_volume",
        lambda a: {
            "muscle_volume": {"Chest": {"total_sets": 20.0, "avg_sets_per_week": 5.0, "volume_landmark_status": "MEV"}},
            "trailing_windows": {"7d": {"muscles": muscles}, "28d": {"muscles": muscles}},
            "below_mev_14d": flag,
        },
    )
    value, _ = tools_coach_packet._muscle_volume("2026-10-19")
    assert value["below_mev_14d"] == flag
    assert "below_mev_14d" in tools_coach_packet.SOURCES["muscle_volume"]
    block: dict = {}
    tools_plan._attach_below_mev(block, {"below_mev_14d": flag})
    assert block["below_mev_14d"] == flag
    tools_plan._attach_below_mev(block, {})
    assert block["below_mev_14d"]["status"] == "unavailable"
