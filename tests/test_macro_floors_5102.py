"""#5102 — the fat, carbohydrate and fibre floors are graded: one reader, charter-owned values, floor + value in a miss.

Every number here is a synthetic fixture, never a real intake."""

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in ("lambdas", ""):
    sys.path.insert(0, os.path.join(_REPO, _p))

from health import macro_floors, nutrition_critics, scoring_engine  # noqa: E402
from training import owner_redlines, training_charter  # noqa: E402

FAT, CARB, FIBRE = (macro_floors.floor_g(m) for m in ("fat", "carb", "fibre"))


def _row(fat, carb, fibre):
    return {"total_fat_g": fat, "total_carbs_g": carb, "total_fiber_g": fibre}


def test_the_charter_owns_the_floors_and_the_redlines_read_them():
    assert (FAT, CARB, FIBRE) == (65, 58, 35)  # #5212 (owner ruling 2026-10-23): the carb floor lowered from 120 to ~60 g
    R = owner_redlines.REDLINES
    assert R["fat_floor_g"]["value"] == FAT and R["carb_floor_g"]["value"] == CARB
    assert R["carb_floor_g"]["fibre_g"] == training_charter.charter_value("nutrition.floors.fibre.target_range_g")
    entry = next(e for e in training_charter.charter_value("change_log") if "#5102" in e.get("by", "") + e.get("what", ""))
    assert entry["version"] == "1.14.0"


def test_a_day_under_each_floor_misses_all_three_with_floor_and_value():
    d = macro_floors.evaluate_day(_row(FAT - 10, CARB - 20, FIBRE - 5))
    assert [d[m]["met"] for m in ("fat", "carb", "fibre")] == [False, False, False]
    assert d["fat"] == {"value_g": FAT - 10, "floor_g": FAT, "met": False, "unknown": False}


def test_a_day_exactly_at_each_floor_is_met_strictly():
    d = macro_floors.evaluate_day(_row(FAT, CARB, FIBRE))
    assert all(d[m]["met"] is True for m in d)
    assert macro_floors.hit(FAT - 0.1, FAT) is False


def test_a_missing_or_malformed_field_is_unknown_never_a_miss():
    d = macro_floors.evaluate_day(_row(FAT + 1, CARB + 1, None))
    assert d["fibre"] == {"value_g": None, "floor_g": FIBRE, "met": None, "unknown": True}
    assert d["fat"]["met"] is True
    assert macro_floors.evaluate_day(None)["carb"]["unknown"] is True
    assert macro_floors.grade("fat", "n/a")["unknown"] is True


def test_the_miss_text_carries_the_floor_and_the_value():
    g = macro_floors.grade("fat", 40)
    assert macro_floors.miss_text("fat", g) == f"fat 40 g is below the {FAT:g} g floor"
    assert macro_floors.miss_text("fat", macro_floors.grade("fat", FAT)) is None
    assert macro_floors.miss_text("fibre", macro_floors.grade("fibre", None)) is None


def test_the_daily_grade_includes_the_three_floors_in_the_macro_slot():
    profile = {}
    met = scoring_engine.score_nutrition(
        {"date": "2026-10-19", "macrofactor": {**_row(FAT, CARB, FIBRE), "total_calories_kcal": 2100}}, profile
    )
    assert met[1]["macro_score"] == 100 and met[1]["macro_floors"]["fibre"]["met"] is True
    low = scoring_engine.score_nutrition(
        {"date": "2026-10-19", "macrofactor": {**_row(FAT, CARB, FIBRE / 2), "total_calories_kcal": 2100}}, profile
    )
    assert low[1]["macro_score"] == round((100 + 100 + 40) / 3) and low[0] < met[0]
    unk = scoring_engine.score_nutrition(
        {"date": "2026-10-19", "macrofactor": {"total_calories_kcal": 2100, "total_protein_g": 180}}, profile
    )
    assert "macro_score" not in unk[1] and unk[0] is not None  # all three unknown: the slot drops out


def test_the_critics_report_a_floor_miss_with_the_floor_and_the_value():
    inputs = {
        "fat_g_by_day": [FAT + 5] * 12 + [40, FAT],
        "carb_g_by_day": [CARB] * 14,
        "fiber_g_by_day": [None] * 14,
    }
    p = nutrition_critics.build_muscle_defense_packet(inputs)
    flag = next(f for f in p["flags"] if f["metric"] == "fat_days_missed_7d")
    assert f"fat 40 g is below the {FAT:g} g floor" in flag["reason"] and flag["to"] == FAT
    assert p["numbers"]["fat_floor_g"] == FAT and p["numbers"]["fat_days_missed_7d"] == 1
    assert p["numbers"]["carb_days_missed_7d"] == 0
    assert p["numbers"]["fibre_days_missed_7d"] is None and "fibre_days_missed_7d" in p["unknown"]
    assert not any(f["metric"] == "fibre_days_missed_7d" for f in p["flags"])  # unlogged fibre is never a miss


def test_the_critics_input_builder_carries_the_three_series():
    for k, v in (("S3_BUCKET", "test-bucket"), ("USER_ID", "matthew"), ("AWS_DEFAULT_REGION", "us-west-2")):
        os.environ.setdefault(k, v)
    from mcp.nutrition_critics_inputs import macro_floor_series

    rows = [{"date": "2026-10-18", **_row(70, 130, 36)}]
    out = macro_floor_series(rows, ["2026-10-17", "2026-10-18"])
    assert out == {"fat_g_by_day": [None, 70.0], "carb_g_by_day": [None, 130.0], "fiber_g_by_day": [None, 36.0]}
    assert macro_floor_series(None, ["2026-10-18"]) == {"fat_g_by_day": None, "carb_g_by_day": None, "fiber_g_by_day": None}
