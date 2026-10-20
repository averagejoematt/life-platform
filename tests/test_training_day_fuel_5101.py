"""tests/test_training_day_fuel_5101.py — training-day fuel through the ONE calorie resolver (#5101, epic #5091).

Built on the panel default, pending R1. Lifting, rest, travel and unknown days; the weekly balance; the
lifting date resolves above the rest date; pre/post targets in the plan's block. Pure: no clock, no AWS.
"""

from __future__ import annotations

import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parent.parent
for _p in (_REPO / "lambdas", _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from health import calorie_target as ct  # noqa: E402
from training import training_charter  # noqa: E402

MON = "2026-11-02"  # a fixed Monday
WEEK = [f"2026-11-{n:02d}" for n in range(2, 9)]
PLANNED = {WEEK[0], WEEK[1], WEEK[2], WEEK[3], WEEK[4]}  # five lifting days, two rest


def _res(day, dt, **kw):
    return ct.resolve(day, day_type=dt, **kw)


def test_lifting_date_is_above_rest_date_and_base_is_unchanged_for_unknown():
    lift = _res(WEEK[0], "lifting")
    rest = _res(WEEK[5], "rest")
    unk = ct.resolve(WEEK[0])
    assert lift["kcal"] > unk["kcal"] > rest["kcal"]
    assert unk["day_type"] == "unknown" and unk["kcal"] == unk["base_kcal"] and unk["uplift_kcal"] == 0
    assert lift["uplift_kcal"] == training_charter.charter_value("nutrition.training_day.lifting_uplift_kcal")
    assert lift["kcal"] == lift["base_kcal"] + lift["uplift_kcal"]


def test_travel_holds_the_base_and_unknown_is_never_a_guessed_rest_day():
    base = ct.resolve(MON)["kcal"]
    assert _res(MON, "travel")["kcal"] == base
    assert _res(MON, "unknown")["kcal"] == base
    assert _res(MON, "bogus")["day_type"] == "unknown"
    assert _res(MON, "travel")["pre_post_session"] is not None
    assert _res(MON, "rest")["pre_post_session"] is None and _res(MON, "unknown")["pre_post_session"] is None


def test_weekly_mean_equals_the_base_target():
    types = ["lifting" if d in PLANNED else "rest" for d in WEEK]
    kcal = [_res(d, t, week_day_types=types)["kcal"] for d, t in zip(WEEK, types)]
    base = ct.resolve(MON)["kcal"]
    assert abs(sum(kcal) / 7 - base) < 0.5, kcal
    assert all(_res(d, t, week_day_types=types)["balance_held"] for d, t in zip(WEEK, types))
    # the default (no week list) uses the charter's five lifting days and gives the same numbers
    assert _res(WEEK[5], "rest")["kcal"] == kcal[5]


def test_a_travel_week_still_balances_around_its_base_days():
    types = ["lifting", "lifting", "travel", "rest", "rest", "travel", "travel"]
    kcal = [_res(MON, t, week_day_types=types)["kcal"] for t in types]
    base = ct.resolve(MON)["kcal"]
    assert abs(sum(kcal) - 7 * base) <= 2


def test_split_holds_protein_and_fat_and_moves_carbohydrate():
    lift, rest, unk = _res(MON, "lifting"), _res(MON, "rest"), ct.resolve(MON)
    for r in (lift, rest, unk):
        assert r["split"]["protein_g"] == unk["split"]["protein_g"] and r["split"]["fat_g"] == unk["split"]["fat_g"]
        total = 4 * r["split"]["protein_g"] + 9 * r["split"]["fat_g"] + 4 * r["split"]["carb_g"]
        assert abs(total - r["kcal"]) <= 9
    assert lift["split"]["carb_g"] > unk["split"]["carb_g"] > rest["split"]["carb_g"]


def test_floors_clamp_and_say_the_balance_is_not_held():
    block = {"target_kcal": 1650, "prescribed_band_kcal": [1600, 1700], "floor_any_day_kcal": 1600, "floor_lifting_day_kcal": 1900}
    vals = {
        "nutrition.calories": block,
        "nutrition.training_day": {"lifting_uplift_kcal": 150},
        "split.lifting_days_per_wk": 5,
        "version": "t",
    }
    rest = ct.resolve(MON, charter_reader=vals.get, day_type="rest")
    lift = ct.resolve(MON, charter_reader=vals.get, day_type="lifting")
    assert rest["kcal"] == 1650 - 1650 + 1600 and rest["balance_held"] is False and "NOT held" in rest["provenance"]
    assert lift["kcal"] == 1900 and lift["balance_held"] is False


def test_unreadable_charter_is_an_absence():
    out = ct.resolve(MON, charter_reader=lambda p: None, day_type="lifting")
    assert out["kcal"] is None and out["split"] is None and out["uplift_kcal"] == 0


def test_classify_day_type():
    c = ct.classify_day_type
    assert c(WEEK[0], planned_dates=PLANNED)["day_type"] == "lifting"
    assert c(WEEK[5], planned_dates=PLANNED)["day_type"] == "rest"
    assert (
        c(WEEK[0], planned_dates=PLANNED, disruption={"phase": "active", "template": "travel", "start_date": WEEK[0], "until": WEEK[3]})[
            "day_type"
        ]
        == "travel"
    )
    # a busy-mode disruption is not travel
    assert (
        c(WEEK[0], planned_dates=PLANNED, disruption={"phase": "active", "template": "busy", "start_date": WEEK[0], "until": WEEK[3]})[
            "day_type"
        ]
        == "lifting"
    )
    seq = {"session_role": "upper_heavy"}
    assert c(WEEK[0], sequence_entry=seq, as_of=WEEK[0])["day_type"] == "lifting"
    assert c(WEEK[1], sequence_entry=seq, as_of=WEEK[0])["day_type"] == "unknown"  # the sequence has no calendar
    assert c(WEEK[0])["day_type"] == "unknown"


def test_plan_block_carries_the_day_and_the_pre_post_targets():
    from training import disruption, plan_engine

    out = plan_engine._training_day_fuel(MON, {"source": "session_sequence", "session_role": "upper_heavy"}, None)
    assert out["day_type"] == "lifting" and out["pre_post_session"]["pre"]["carb_g"] and out["pre_post_session"]["post"]["protein_g"]
    unread = plan_engine._training_day_fuel(MON, {"source": "sequence_unreadable"}, None)
    assert unread["day_type"] == "unknown" and unread["uplift_kcal"] == 0
    rec = disruption.build_disruption_record(
        start_date=MON, until="2026-11-05", words="w", template="travel", recorded_at="2026-11-02T00:00:00Z"
    )
    away = plan_engine._training_day_fuel(MON, {"source": "session_sequence", "session_role": "x"}, [rec])
    assert away["day_type"] == "travel" and away["uplift_kcal"] == 0 and away["pre_post_session"] is not None
