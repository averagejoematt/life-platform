"""tests/test_side_rear_delt_flag_5164.py — the side/rear-delt floor, counted by movement (#5164).

THE GAP: `below_mev_14d` (#5053) compares each `MUSCLES` label's trailing-14-day sets with its MEV. `Shoulders` is one
label — presses included — so continued pressing kept it at MEV while lateral and rear-delt work was 0. The live read
2026-10-05..2026-10-18: 16 Shoulders sets (8.0/wk, MEV 8, not flagged), every one of them `Shoulder Press (Dumbbell)`;
the last lateral raise / face pull was the 2026-10-04 Flex day.

THE FIX, held here: `movement_floors['side_rear_delts']` sums `FLOOR_MOVEMENTS['side_rear_delts']` (the template side's
own list) from `working_sets_by_muscle`'s per-exercise working sets — the one computation, no second count — against the
shoulders MEV, and joins `flagged` when below it. It rides the coach packet and the plan packet inside `below_mev_14d`.

The fixture is the logged fortnight 2026-10-04..18, read-only from DDB on 2026-10-23 and trimmed to the per-workout keys
(`tests/fixtures/side_rear_delts_5164/`). The real Flex day carried only 6 side/rear-delt sets (3.0/wk over 14 days) —
below MEV on its own — so the day-13/day-14 edge is proven on the same rows with that day's two side/rear-delt
exercises raised to 8 working sets each (16 = MEV over two weeks), every other row verbatim.
"""

from __future__ import annotations

import copy
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

from test_muscle_volume_working_sets_4071 import tool  # noqa: E402,F401 — the tool seam over a fake table
from training import muscle_volume, volume_floors  # noqa: E402

from mcp.strength_helpers import normalize_hevy_items  # noqa: E402

FIXTURE = REPO / "tests" / "fixtures" / "side_rear_delts_5164" / "hevy_2026-10-04_2026-10-18.json"
CATALOG = json.loads((REPO / "config" / "movement_catalog.json").read_text())["movements"]
SIDE_REAR = ("Lateral Raise (Dumbbell)", "Face Pull")


def _logged() -> list[dict]:
    return json.loads(FIXTURE.read_text())["rows"]


def _flex_day_at_mev() -> list[dict]:
    """The logged rows, with the 2026-10-04 lateral raise and face pull each raised to 8 working sets (real set shape)."""
    rows = copy.deepcopy(_logged())
    for row in rows:
        if row["date"] != "2026-10-04":
            continue
        for ex in row["exercises"]:
            if ex["name"] in SIDE_REAR:
                ex["sets"] = [dict(ex["sets"][0], set_index=i) for i in range(8)]
    return rows


def test_the_fixture_is_the_logged_shape():
    rows = _logged()
    assert [r["date"] for r in rows] == sorted(r["date"] for r in rows)
    assert {r["date"] for r in rows} >= {"2026-10-04", "2026-10-07", "2026-10-11", "2026-10-15", "2026-10-18"}
    assert all("#WORKOUT#" in r["sk"] and r["pk"] == "USER#matthew#SOURCE#hevy" for r in rows)
    flex = next(r for r in rows if r["date"] == "2026-10-04")
    assert {e["name"]: (e["template_id"], len(e["sets"])) for e in flex["exercises"] if e["name"] in SIDE_REAR} == {
        "Lateral Raise (Dumbbell)": ("422B08F1", 3),
        "Face Pull": ("BE640BA0", 3),
    }
    assert all("type" in s and "weight_kg" in s for r in rows for e in r["exercises"] for s in e["sets"])


def test_the_logged_fortnight_flags_side_rear_delts_while_pressing_holds_shoulders_at_mev(tool):  # noqa: F811
    out = tool(_logged())({"start_date": "2026-10-05", "end_date": "2026-10-18"})["below_mev_14d"]
    assert out["status"] == "ok"
    # the coarse row, as it really read: 16 press sets = 8.0/wk, at MEV, quiet
    assert out["muscles"]["Shoulders"] == {"sets_per_wk": 8.0, "mev": 8, "below_mev": False, "landmark_key": "shoulders"}
    assert "Shoulders" not in out["flagged"]
    floor = out["movement_floors"]["side_rear_delts"]
    assert (floor["status"], floor["sets_per_wk"], floor["mev"], floor["below_mev"]) == ("ok", 0.0, 8, True)
    assert floor["movements"] == {} and floor["counted_by"] == "movement" and floor["landmark_key"] == "shoulders"
    assert "side_rear_delts" in out["flagged"]


def test_the_real_flex_day_alone_was_already_below_mev(tool):  # noqa: F811
    """Unscaled, day 13 (2026-10-04..17) still holds the Flex day: 3 + 3 sets = 3.0/wk, below MEV 8 — the movement count
    says so, and the Shoulders row (3 + 3 + 12 press sets = 9.0/wk) does not."""
    out = tool(_logged())({"start_date": "2026-10-04", "end_date": "2026-10-17"})["below_mev_14d"]
    floor = out["movement_floors"]["side_rear_delts"]
    assert floor["movements"] == {"db_lateral_raise": 3, "face_pull": 3}
    assert (floor["sets_per_wk"], floor["below_mev"]) == (3.0, True)
    assert out["muscles"]["Shoulders"]["sets_per_wk"] == 9.0 and out["muscles"]["Shoulders"]["below_mev"] is False


def test_the_2026_10_04_drop_trips_on_day_14_and_not_day_13(tool):  # noqa: F811
    read = tool(_flex_day_at_mev())
    day13 = read({"start_date": "2026-10-04", "end_date": "2026-10-17"})["below_mev_14d"]
    day14 = read({"start_date": "2026-10-05", "end_date": "2026-10-18"})["below_mev_14d"]
    f13, f14 = day13["movement_floors"]["side_rear_delts"], day14["movement_floors"]["side_rear_delts"]
    assert f13["movements"] == {"db_lateral_raise": 8, "face_pull": 8}
    assert (f13["sets_per_wk"], f13["below_mev"]) == (8.0, False) and "side_rear_delts" not in day13["flagged"]
    assert (f14["sets_per_wk"], f14["below_mev"]) == (0.0, True) and "side_rear_delts" in day14["flagged"]
    # pressing continued the whole time, so the Shoulders row is quiet on both days
    assert day13["muscles"]["Shoulders"]["below_mev"] is False and day14["muscles"]["Shoulders"]["below_mev"] is False


def test_a_press_never_counts_and_every_side_rear_movement_resolves():
    exercise_sets = [
        {"name": "Shoulder Press (Dumbbell)", "template_id": "878CD1D0", "working_sets": 16},
        {"name": "Seated Shoulder Press (Machine)", "template_id": None, "working_sets": 4},
        {"name": "Lateral Raise (Dumbbell)", "template_id": "422b08f1", "working_sets": 3},  # by id, any case
        {"name": "rear delt reverse fly (machine)", "template_id": "UNKNOWN1", "working_sets": 2},  # hint-less: by title
    ]
    got = volume_floors.logged_movement_sets(exercise_sets, CATALOG)
    assert got == {"db_lateral_raise": 3, "reverse_pec_deck": 2}
    for key in volume_floors.FLOOR_MOVEMENTS["side_rear_delts"]:
        entry = CATALOG[key]
        assert entry.get("hevy_template_id_hint") or entry.get("title"), key
        row = {"name": entry["title"], "template_id": entry.get("hevy_template_id_hint"), "working_sets": 1}
        assert volume_floors.logged_movement_sets([row], CATALOG) == {key: 1}, key
    assert volume_floors.logged_movement_sets(None, CATALOG) is None
    assert volume_floors.logged_movement_sets(exercise_sets, {}) is None  # an unreadable catalog resolves nothing, never raises


def test_the_per_exercise_sets_are_the_one_counts_own():
    counted = muscle_volume.working_sets_by_muscle(normalize_hevy_items(_logged()), "2026-10-04", "2026-10-18")
    by_ex = {e["name"]: e["working_sets"] for e in counted["exercise_sets"]}
    assert sum(by_ex.values()) == counted["working_sets_counted"]
    shoulder_names = {"Lateral Raise (Dumbbell)", "Face Pull", "Shoulder Press (Dumbbell)"}
    assert sum(by_ex[n] for n in shoulder_names) == counted["muscles"]["Shoulders"]["direct_sets"] == 22
    assert "Treadmill" not in by_ex and "Stretching" not in by_ex  # non-resistance carries no sets here either


def test_unavailable_when_the_window_has_no_movement_counts():
    window = {"days": 14, "weeks": 2.0, "start": "a", "end": "b", "muscles": {"Shoulders": {"total_sets": 16.0}}}
    out = volume_floors.below_mev_14d(window, {"shoulders": {"MEV": 8}})
    assert out["movement_floors"]["side_rear_delts"]["status"] == "unavailable"
    assert out["flagged"] == []


def test_it_rides_the_coach_and_plan_packets(tool, monkeypatch):  # noqa: F811
    from mcp import tools_coach_packet, tools_plan, tools_strength

    real = tool(_logged())
    monkeypatch.setattr(tools_strength, "tool_get_muscle_volume", lambda a: real({"start_date": "2026-10-05", "end_date": "2026-10-18"}))
    value, _ = tools_coach_packet._muscle_volume("2026-10-19")
    assert value["below_mev_14d"]["movement_floors"]["side_rear_delts"]["below_mev"] is True
    assert "side_rear_delts" in value["below_mev_14d"]["flagged"]
    block: dict = {}
    tools_plan._attach_below_mev(block, real({"start_date": "2026-10-05", "end_date": "2026-10-18"}))
    assert block["below_mev_14d"]["movement_floors"]["side_rear_delts"]["sets_per_wk"] == 0.0
    assert "side_rear_delts" in block["below_mev_14d"]["flagged"]
