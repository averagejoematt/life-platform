"""tests/test_volume_floors_5053.py — the coverage floors (#5053).

THE INCIDENT: 2026-10-04 the Flex day was dropped; side/rear delts and core went to 0 sets and calves sat at 6/wk with no
alert (`muscle_volume` counted it; nothing compared the count with the landmark). Two halves, held here:

  * TEMPLATES — every charter MEV floor (`volume_priorities.mev_floors_in_every_template`: side/rear delts, traps, calves,
    core) has a slot in a role and meets its landmark MEV (side/rear delts were 6 direct sets vs MEV 8 until #5162 traded the
    press for lateral raises and face pulls: 14); the week stays inside the owner's 60–75 hard-set redline and every session
    inside the charter's lifting-minute cap.
  * THE FLAG — `below_mev_14d` rides the coach packet and the plan packet, derived from `get_muscle_volume`'s trailing-14d
    counts (`working_sets_by_muscle`, the one computation) — and a fixture of the 2026-10-04 drop trips it on day 14, not 13.

RESIDUAL — CLOSED by #5162 (owner ruling 2026-10-23, "trade inside 75"): 8 of the 9 weekly shoulder-press sets became
lateral raises and face pulls (side/rear delts 6 -> 14, the band's floor), and the lats / upper-chest / arms bands were
lowered to what fits inside the 75-set week (charter 1.20.0: 4, 0, 6). `KNOWN_BAND_GAPS` is all zeros and stays
shrink-only. Side/rear delts, upper chest and lats are still counted BY MOVEMENT (`volume_floors.FLOOR_MOVEMENTS` /
`BAND_MOVEMENTS`): upper chest has 0 incline sets (the 8 catalog-'chest' sets are flat bench + cable fly), lats has 4
(the lat pulldown; rows and the shrug are not lat work). The LOGGED Shoulders flag cannot
see a side/rear-delt drop that continued pressing masks (live 2026-10-05..18: 16 Shoulders sets, 8.0/wk); that follow-on is
#5164 — so the day-14 trip below is asserted for Calves and Core, and Shoulders is asserted NOT flagged, as it really was.
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

# gap (sets/wk) below each charter band's floor today — may only shrink (#5053 residual, closed by #5162; see the docstring)
KNOWN_BAND_GAPS = {"side_rear_delts": 0, "lats": 0, "upper_chest": 0, "legs": 0, "arms": 0}


@pytest.fixture(scope="module")
def coverage():
    return program_structure.volume_floor_coverage(CATALOG)


def test_every_charter_floor_muscle_has_a_slot_and_meets_its_mev(coverage):
    floors = coverage["floors"]
    assert set(floors) == set(charter_value("volume_priorities.mev_floors_in_every_template"))
    for name, row in floors.items():
        assert row["slot_roles"], (name, row)
        assert row["meets_mev"], (name, row)
    delts = floors["side_rear_delts"]
    # #5162: the press sets traded for lateral raises + face pulls (presses are NOT side/rear-delt work: 6 before)
    assert (delts["sets"], delts["mev"], delts["meets_mev"]) == (14, 8, True)
    assert delts["slot_roles"] == ["upper_heavy", "shoulders_arms", "upper_volume"]
    assert floors["traps"]["sets"] == 2  # the shrug slot, not all Back
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


def test_weekly_sets_by_muscle_delts_frequency_and_the_real_side_rear_count(coverage):
    delts = program_structure.weekly_sets_by_muscle(CATALOG)["delts"]
    assert delts["frequency_per_wk"] >= charter_value("split.frequency.delts_per_wk")
    # 15 catalog-'shoulders' sets = 1 press + 14 direct (#5162; were 9 press + 6 direct); only the 14 count toward the band
    assert delts["sets"] == 15 and coverage["sets_by_muscle"]["side_rear_delts_direct"] == 14
    assert coverage["bands"]["side_rear_delts"]["member_sets"] == [14]
    assert coverage["bands"]["side_rear_delts"]["band"][0] == 14  # the floor is closed, not lowered


def test_upper_chest_and_lats_are_counted_by_movement_not_catalog_muscle(coverage):
    by = coverage["sets_by_muscle"]
    # catalog 'chest' 8 = 6 flat bench + 2 cable fly: none of it is incline, so none of it is upper-chest work
    assert by["chest"] == 8 and by["upper_chest_direct"] == 0
    assert coverage["bands"]["upper_chest"]["member_sets"] == [0]
    # catalog 'back' 12 = 6 machine row + 4 lat pulldown + 2 dumbbell shrug: only the pulldown is a vertical pull
    assert by["back"] == 12 and by["lats_direct"] == 4
    assert coverage["bands"]["lats"]["member_sets"] == [4]
    for excluded in ("barbell_bench_press", "cable_chest_fly", "machine_chest_press"):
        assert excluded not in volume_floors.BAND_MOVEMENTS["upper_chest"], excluded
    for excluded in ("machine_row", "seated_cable_row", "t_bar_row", "shrug_dumbbell", "shrug_barbell", "scap_pulldowns"):
        assert excluded not in volume_floors.BAND_MOVEMENTS["lats"], excluded
    # every counted movement exists in the catalog (a typo would silently count 0)
    assert {m for v in volume_floors.BAND_MOVEMENTS.values() for m in v} <= set(CATALOG)


def test_band_gaps_only_shrink(coverage):
    gaps = {g: r["gap_to_floor"] for g, r in coverage["bands"].items()}
    assert set(gaps) == set(KNOWN_BAND_GAPS) == set(charter_value("volume_priorities.sets_per_wk"))
    for g, gap in gaps.items():
        assert gap <= KNOWN_BAND_GAPS[g], f"{g}: gap {gap} grew past the pinned {KNOWN_BAND_GAPS[g]}"
    assert coverage["bands"]["legs"]["gap_to_floor"] == 0  # strong maintenance, 8-10
    assert all(row["band"][0] <= max(row["member_sets"]) or row["gap_to_floor"] for row in coverage["bands"].values())


def test_5162_the_ruled_trade_inside_75():
    """Owner ruling 2026-10-23 (#5162): "Trade inside 75. Shoulder-press sets become lateral raises and face pulls ... The
    2 -> 4 calf sets and the dropped second leg curl stay." Held as numbers: the week is still 75; the press keeps 1 of its
    9 sets; the 8 traded sets are lateral raises + face pulls; the calf and leg-curl trades are unchanged."""
    by_mv = program_structure._week_movement_sets(CATALOG)
    total = sum(program_structure.session_prescription_for_role(r, catalog_movements=CATALOG)["total_sets"] for r in ROLES)
    assert total == owner_redlines.REDLINES["lifting_sessions_per_wk"]["total_hard_sets_wk"][1] == 75
    assert by_mv.get("machine_shoulder_press", 0) == 1
    assert (by_mv["db_lateral_raise"], by_mv["face_pull"], by_mv["reverse_pec_deck"]) == (6, 6, 2)  # were 2 / 2 / 2
    tmpl = program_structure.SESSION_TEMPLATES
    assert tmpl["lower_heavy"]["accessory_sets"]["calf_raise_machine"] == 4 and by_mv["calf_raise_machine"] == 8
    assert "leg_curl" not in tmpl["lower_volume"]["accessories"] and by_mv["leg_curl"] == 2
    # the lowered bands are the week's own counts — a band above what the week carries would re-open a gap
    bands = charter_value("volume_priorities.sets_per_wk")
    assert (bands["lats"], bands["upper_chest"], bands["arms"]) == ([4, 4], [0, 0], [6, 6])


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
    """2026-10-04, the last day with delt/core/calf work: 16 side/rear-delt sets, 8 core, 16 calf (= MEV over two weeks);
    then the world as it was: shoulder PRESSING continued (16 sets 2026-10-05..18 = 8.0/wk), the lateral/rear/calf/core did not."""
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
        ),
        _row("2026-10-10", "press-0001", [_ex("Seated Shoulder Press (Machine)", "9237BAD1", 16)]),
    ]


def test_the_2026_10_04_drop_trips_the_flag_on_day_14_and_not_day_13(tool):  # noqa: F811
    read = tool(_flex_day_rows())
    day13 = read({"start_date": "2026-10-04", "end_date": "2026-10-17"})["below_mev_14d"]
    day14 = read({"start_date": "2026-10-05", "end_date": "2026-10-18"})["below_mev_14d"]
    assert day13["status"] == day14["status"] == "ok"
    for m in ("Calves", "Core"):
        assert day13["muscles"][m]["below_mev"] is False, (m, day13["muscles"][m])
        assert day14["muscles"][m]["below_mev"] is True and day14["muscles"][m]["sets_per_wk"] == 0.0, m
    assert {"Calves", "Core"} <= set(day14["flagged"]) and not {"Calves", "Core"} & set(day13["flagged"])
    # the coarse Shoulders flag stays quiet because pressing carried on (the live read: 8.0/wk) — #5164 owns the finer flag
    assert day14["muscles"]["Shoulders"]["sets_per_wk"] == 8.0 and day14["muscles"]["Shoulders"]["below_mev"] is False
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
