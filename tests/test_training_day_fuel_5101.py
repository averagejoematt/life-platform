"""tests/test_training_day_fuel_5101.py — training-day fuel through the ONE calorie resolver (#5101, epic #5091).

Lifting, rest, travel and unknown days; the week; the lifting date resolves above the rest date; pre/post targets in
the plan's block. Owner rulings 2026-10-23 (#5091 R1, #5212, and follow-up 2): the base is ~1,500, the floors are warnings
(never a clamp), a lifting day is the base +150 and a rest day stays at the base — no payback below the target, so the
week averages above the base by design — swept over 0..7 lifting days at the live charter. Pure: no clock, no AWS.
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


def test_lifting_date_is_above_rest_date_and_rest_stays_at_the_base():
    lift = _res(WEEK[0], "lifting")
    rest = _res(WEEK[5], "rest")
    unk = ct.resolve(WEEK[0])
    assert lift["kcal"] > unk["kcal"] == rest["kcal"] == unk["base_kcal"]
    assert unk["day_type"] == "unknown" and unk["uplift_kcal"] == 0 and rest["uplift_kcal"] == 0
    assert lift["uplift_kcal"] == training_charter.charter_value("nutrition.training_day.lifting_uplift_kcal") == 150
    assert lift["kcal"] == lift["base_kcal"] + lift["uplift_kcal"] == 1650


def test_travel_holds_the_base_and_unknown_is_never_a_guessed_rest_day():
    base = ct.resolve(MON)["kcal"]
    assert _res(MON, "travel")["kcal"] == base
    assert _res(MON, "unknown")["kcal"] == base
    assert _res(MON, "bogus")["day_type"] == "unknown"
    assert _res(MON, "travel")["pre_post_session"] is not None
    assert _res(MON, "rest")["pre_post_session"] is None and _res(MON, "unknown")["pre_post_session"] is None


def test_the_week_averages_above_the_base_by_design_no_rest_day_payback():
    """Owner ruling 2026-10-23 (#5091 follow-up 2): 'Rest days are not paid back below the target. The week averages
    above 1,500 by design.' Five lifting days: (5 x 1,650 + 2 x 1,500) / 7 = 1,607."""
    types = ["lifting" if d in PLANNED else "rest" for d in WEEK]
    days = [_res(d, t, week_day_types=types) for d, t in zip(WEEK, types)]
    base = ct.resolve(MON)["kcal"]
    assert [r["kcal"] for r in days] == [base + 150] * 5 + [base] * 2
    assert round(sum(r["kcal"] for r in days) / 7) == 1607
    assert all(r["balance_held"] for r in days) and all(r["kcal"] >= r["base_kcal"] for r in days)
    # the default (no week list) gives the same numbers: the rest day never depends on the week's count
    assert _res(WEEK[5], "rest")["kcal"] == base


def test_travel_and_no_lifting_weeks_stay_at_the_base():
    # a count of 0 is a real count; travel and rest days are the base whatever the week holds
    for types in (["travel"] * 5 + ["rest", "rest"], ["lifting", "lifting", "travel", "rest", "rest", "travel", "travel"]):
        kcal = [_res(MON, t, week_day_types=types)["kcal"] for t in types]
        base = ct.resolve(MON)["kcal"]
        assert kcal == [base + 150 if t == "lifting" else base for t in types], kcal


def test_split_holds_protein_and_fat_and_moves_carbohydrate():
    lift, rest, unk = _res(MON, "lifting"), _res(MON, "rest"), ct.resolve(MON)
    for r in (lift, rest, unk):
        assert r["split"]["protein_g"] == unk["split"]["protein_g"] and r["split"]["fat_g"] == unk["split"]["fat_g"]
        total = 4 * r["split"]["protein_g"] + 9 * r["split"]["fat_g"] + 4 * r["split"]["carb_g"]
        assert abs(total - r["kcal"]) <= 9
    assert lift["split"]["carb_g"] > unk["split"]["carb_g"] == rest["split"]["carb_g"]
    # the ruled numbers: 1,650 = 170 / 65 / 96 g, 1,500 = 170 / 65 / 59 g
    assert {k: lift["split"][k] for k in ("protein_g", "fat_g", "carb_g")} == {"protein_g": 170, "fat_g": 65, "carb_g": 96}
    assert {k: rest["split"][k] for k in ("protein_g", "fat_g", "carb_g")} == {"protein_g": 170, "fat_g": 65, "carb_g": 59}


def test_the_session_carbohydrate_fits_the_lifting_day_with_room_for_the_fibre_floor():
    """Owner ruling 2026-10-23 (#5091 follow-up 2): the pre/post carbohydrate targets are checked against the 1,650 kcal
    lifting day (59 + 37.5 g ~ 96 g). The pre-ruling 40 + 60 = 100 g exceeded the whole day; the scaled 24 + 36 = 60 g
    leaves the rest of the day's food at least the fibre floor's grams."""
    read = training_charter.charter_value
    lift = _res(MON, "lifting")
    pp = lift["pre_post_session"]
    session = pp["pre"]["carb_g"] + pp["post"]["carb_g"]
    assert (pp["pre"]["carb_g"], pp["post"]["carb_g"]) == (24, 36)
    assert session + read("nutrition.floors.fibre.floor_g") <= lift["split"]["carb_g"], (session, lift["split"])


def test_floors_warn_and_never_clamp():
    """Owner ruling 2026-10-23 R1: the energy floors stay as WARNINGS — a day under its floor keeps its kcal and says so."""
    block = {"target_kcal": 1500, "prescribed_band_kcal": [1400, 1600], "floor_any_day_kcal": 1600, "floor_lifting_day_kcal": 1900}
    vals = {
        "nutrition.calories": block,
        "nutrition.training_day": {"lifting_uplift_kcal": 150, "fat_pct_of_base_kcal": 30},
        "nutrition.protein.range_g.low": 100,
        "nutrition.floors.fat.floor_g": 40,
        "split.lifting_days_per_wk": 5,
        "version": "t",
    }
    rest = ct.resolve(MON, charter_reader=vals.get, day_type="rest")
    lift = ct.resolve(MON, charter_reader=vals.get, day_type="lifting")
    assert rest["kcal"] == 1500 and rest["balance_held"] is True and "under its 1600 kcal floor" in rest["floor_warnings"][0]
    assert lift["kcal"] == 1650 and lift["balance_held"] is True and "under its 1900 kcal floor" in lift["provenance"]
    assert ct.resolve(MON, charter_reader=vals.get)["kcal"] == 1500, "no clamp"


def test_every_lifting_day_count_holds_the_macro_floors_at_the_ruled_charter_5207():
    """#5207 / #5212 at the LIVE charter (~1,500, carb floor lowered, protein and fat floors kept): over 0..7 lifting days
    every planned day's split holds the protein, fat and carbohydrate floors and no day sits under the base (no payback).
    One test that reports every offender (a parametrize is one census gate per case)."""
    read = training_charter.charter_value
    floors = {"protein_g": read("nutrition.protein.range_g.low"), "fat_g": read("nutrition.floors.fat.floor_g")}
    floors["carb_g"] = read("nutrition.floors.carb.floor_g")
    base = ct.resolve(MON)["kcal"]
    assert base == read("nutrition.calories.target_kcal") == 1500
    offenders = []
    for n in range(8):
        types = ["lifting"] * n + ["rest"] * (7 - n)
        days = [_res(d, t, week_day_types=types) for d, t in zip(WEEK, types)]
        for r in days:
            short = [k for k, f in floors.items() if r["split"][k] < f]
            if short or r["kcal"] < base or not r["balance_held"]:
                offenders.append((n, r["day_type"], r["kcal"], r["split"], short))
        mean = sum(r["kcal"] for r in days) / 7
        if abs(mean - (base + 150 * n / 7)) > 0.5:
            offenders.append((n, "week", round(mean, 1)))
    assert not offenders, offenders


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
    # the sequence has no calendar: it serves the next undone session every day, so it never types a date
    assert c(WEEK[0])["day_type"] == "unknown"


def test_plan_block_carries_the_day_and_the_pre_post_targets():
    from training import disruption

    out = ct.plan_block(MON, None)
    assert out["day_type"] == "unknown" and out["uplift_kcal"] == 0 and out["kcal"] == out["base_kcal"]
    # a non-lifting date served by the sequence does NOT get the uplift; the uplift is stated as conditional
    assert out["if_lifting_day"]["kcal"] > out["kcal"] == out["if_rest_day"]["kcal"]
    pp = out["if_lifting_day"]["pre_post_session"]
    assert pp["pre"]["carb_g"] and pp["post"]["protein_g"]
    rec = disruption.build_disruption_record(
        start_date=MON, until="2026-11-05", words="w", template="travel", recorded_at="2026-11-02T00:00:00Z"
    )
    away = ct.plan_block(MON, disruption.state([rec], MON))
    assert away["day_type"] == "travel" and away["uplift_kcal"] == 0 and away["pre_post_session"] is not None


def test_plan_engine_wires_the_block_without_typing_a_date_lifting():
    from training import plan_engine

    blk = plan_engine._effort_blocks(MON, [], [], {}, None)["training_day_fuel"]
    assert blk["day_type"] == "unknown" and blk["uplift_kcal"] == 0
